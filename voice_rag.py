import asyncio
import time
import uuid
import os
import glob
import psutil
import signal
import sys
from typing import Optional, Dict, Any
from datetime import datetime

from voice.stt import record_audio, speech_to_text
from voice.tts import speak, speak_async, get_tts_info, cleanup_tts
from rag_pipeline import build_rag, query_rag, process_document, health_check, cleanup as rag_cleanup

from observability.logs_traces import setup_tracing, setup_logging, create_span, log_stage_boundary
from observability.metrics import *
from observability.context import (
    set_correlation_id, set_user_id, set_session_id,
    get_correlation_id, get_user_id, get_session_id,
    ObservabilityContext, clear_context, get_trace_id
)

from opentelemetry.trace import get_current_span, SpanKind
from opentelemetry import trace

# --------------------------------
# OBSERVABILITY
# --------------------------------

tracer = setup_tracing(service_name="voice-rag-agent", service_version="2.0")
logger = setup_logging(
    log_level="INFO",
    log_file="C:/Users/Bhanu Prakash Kuruva/Documents/ollama-rag/voice-rag.log",
    enable_console=True
)

# Start metrics server
metrics_port = int(os.getenv("METRICS_PORT", "8000"))
start_metrics_server(port=metrics_port)

logger.info(f"Metrics server started on port {metrics_port}")

# --------------------------------
# CONFIGURATION
# --------------------------------

DOCUMENT_PATH = os.getenv("DOCUMENT_PATH", "./data/document.pdf")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "./output")
RAG_STORAGE_PATH = os.getenv("WORKING_DIR", "./rag_storage")
SESSION_TIMEOUT = int(os.getenv("SESSION_TIMEOUT", "3600"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# --------------------------------
# SYSTEM METRICS HELPER
# --------------------------------

class SystemMetricsCollector:
    """Enhanced system metrics collector"""
    
    def __init__(self):
        self.process = psutil.Process()
        self._last_cpu_time = 0
        self._last_time = time.time()
    
    def capture(self) -> Dict[str, float]:
        """Capture current system metrics"""
        cpu_times = self.process.cpu_times()
        
        return {
            "cpu_time": cpu_times.user + cpu_times.system,
            "memory": self.process.memory_info().rss / (1024 * 1024),
            "memory_percent": self.process.memory_percent(),
            "cpu_percent": self.process.cpu_percent(interval=0),
            "threads": self.process.num_threads(),
            "open_files": len(self.process.open_files()) if hasattr(self.process, 'open_files') else 0
        }
    
    def calculate_delta(self, start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
        """Calculate delta between two metric snapshots"""
        return {
            "cpu_used": end["cpu_time"] - start["cpu_time"],
            "memory_used": end["memory"] - start["memory"],
            "cpu_percent": end["cpu_percent"],
            "memory_percent": end["memory_percent"]
        }


_metrics_collector = SystemMetricsCollector()


# --------------------------------
# SESSION MANAGEMENT
# --------------------------------

class SessionManager:
    """Manage user sessions with timeouts"""
    
    def __init__(self, timeout_seconds: int = SESSION_TIMEOUT):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._timeout = timeout_seconds
    
    def get_or_create_session(self, session_id: Optional[str] = None) -> str:
        """Get existing session or create new one"""
        if session_id and session_id in self._sessions:
            self._sessions[session_id]["last_activity"] = time.time()
            return session_id
        
        session_id = session_id or str(uuid.uuid4())
        self._sessions[session_id] = {
            "created_at": time.time(),
            "last_activity": time.time(),
            "request_count": 0,
            "total_tokens": 0
        }
        
        active_sessions.set(len(self._sessions))
        
        logger.info({
            "event": "session_created",
            "session_id": session_id
        })
        
        return session_id
    
    def update_session_stats(self, session_id: str, tokens: int = 0):
        """Update session statistics"""
        if session_id in self._sessions:
            self._sessions[session_id]["request_count"] += 1
            self._sessions[session_id]["total_tokens"] += tokens
            self._sessions[session_id]["last_activity"] = time.time()
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions"""
        now = time.time()
        expired = []
        
        for sid, data in self._sessions.items():
            if now - data["last_activity"] > self._timeout:
                expired.append(sid)
        
        for sid in expired:
            del self._sessions[sid]
        
        if expired:
            active_sessions.set(len(self._sessions))
            logger.info({
                "event": "sessions_cleaned",
                "expired_count": len(expired),
                "active_count": len(self._sessions)
            })
    
    def get_session_stats(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session statistics"""
        return self._sessions.get(session_id)


_session_manager = SessionManager()


# --------------------------------
# CHECK IF DOCUMENT EXISTS
# --------------------------------

async def is_document_processed() -> bool:
    """Check if documents have been processed with enhanced validation"""
    with tracer.start_as_current_span("check_documents") as span:
        
        rag_storage_path = RAG_STORAGE_PATH
        
        indicators = [
            ("graph_chunk_entity_relation.graphml", 100),
            ("text_chunks.json", 100),
        ]
        
        vdb_files = glob.glob(os.path.join(rag_storage_path, "vdb_*.json"))
        if vdb_files:
            for vdb in vdb_files:
                if os.path.getsize(vdb) > 1000:
                    indicators.append((vdb, 1000))
        
        for file_pattern, min_size in indicators:
            if "*" in file_pattern:
                files = glob.glob(os.path.join(rag_storage_path, file_pattern))
                for f in files:
                    if os.path.exists(f) and os.path.getsize(f) > min_size:
                        span.set_attribute("document_exists", True)
                        span.set_attribute("document_indicator", file_pattern)
                        return True
            else:
                file_path = os.path.join(rag_storage_path, file_pattern)
                if os.path.exists(file_path) and os.path.getsize(file_path) > min_size:
                    span.set_attribute("document_exists", True)
                    span.set_attribute("document_indicator", file_pattern)
                    return True
        
        span.set_attribute("document_exists", False)
        return False


# --------------------------------
# PROCESS DOCUMENT WITH RETRY
# --------------------------------

async def process_document_with_retry(rag, max_retries: int = MAX_RETRIES) -> bool:
    """Process document with retry logic"""
    for attempt in range(max_retries):
        try:
            logger.info({
                "event": "document_processing_attempt",
                "attempt": attempt + 1,
                "max_retries": max_retries,
                "document_path": DOCUMENT_PATH
            })
            
            result = await process_document(
                rag=rag,
                file_path=DOCUMENT_PATH,
                output_dir=OUTPUT_DIR,
                parse_method="auto"
            )
            
            documents_processed.labels(document_type="pdf", status="success").inc()
            
            logger.info({
                "event": "document_processed_successfully",
                "attempt": attempt + 1,
                "duration": result.get("duration")
            })
            
            return True
            
        except Exception as e:
            logger.warning({
                "event": "document_processing_failed",
                "attempt": attempt + 1,
                "error": str(e)
            })
            
            if attempt == max_retries - 1:
                documents_processed.labels(document_type="pdf", status="failed").inc()
                logger.error({
                    "event": "document_processing_all_attempts_failed",
                    "max_retries": max_retries,
                    "error": str(e)
                })
                return False
            
            await asyncio.sleep(2 ** attempt)
    
    return False


# --------------------------------
# HANDLE USER REQUEST (ENHANCED)
# --------------------------------

async def handle_user_request(
    rag,
    session_id: str,
    user_id: Optional[str] = None,
    enable_tts: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Handle a single user request with full observability and proper context propagation
    """
    correlation_id = str(uuid.uuid4())
    
    with ObservabilityContext(
        correlation_id=correlation_id,
        request_id=str(uuid.uuid4()),
        user_id=user_id,
        session_id=session_id
    ):
        print(f"\n{'='*70}")
        print(f"🔵 REQUEST START: {correlation_id[:8]}...")
        print(f"👤 Session: {session_id[:8]}...")
        print(f"{'='*70}")
        
        # Track active requests
        rag_active_requests.inc()
        concurrent_requests.inc()
        pipeline_start = time.time()
        
        if user_id:
            requests_per_user.labels(user_id=user_id, user_type="authenticated").inc()
        
        result_metadata = {
            "correlation_id": correlation_id,
            "session_id": session_id,
            "user_id": user_id,
            "stages": {}
        }
        
        try:
            with tracer.start_as_current_span("voice_rag_pipeline", kind=SpanKind.SERVER) as root_span:
                
                root_span.set_attribute("correlation_id", correlation_id)
                root_span.set_attribute("session_id", session_id)
                root_span.set_attribute("user_id", user_id or "anonymous")
                
                span_ctx = get_current_span()
                trace_id = format(span_ctx.get_span_context().trace_id, "032x")
                
                logger.info({
                    "event": "request_started",
                    "correlation_id": correlation_id,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "user_id": user_id,
                    "message": f"🚀 REQUEST {correlation_id[:8]} STARTED"
                })
                
                # --------------------------------
                # AUDIO RECORD STAGE
                # --------------------------------
                
                log_stage_boundary("audio_record", "enter", correlation_id)
                stage_start = time.time()
                start_metrics = _metrics_collector.capture()
                
                audio_file = record_audio(duration=5)
                
                duration = time.time() - stage_start
                end_metrics = _metrics_collector.capture()
                metrics_delta = _metrics_collector.calculate_delta(start_metrics, end_metrics)
                
                stage_cpu_usage.labels(stage="audio_record").observe(metrics_delta["cpu_used"])
                stage_memory_usage.labels(stage="audio_record").observe(metrics_delta["memory_used"])
                audio_latency.observe(duration)
                audio_duration_seconds.observe(duration)
                
                result_metadata["stages"]["audio_record"] = {
                    "duration": duration,
                    "cpu_used": metrics_delta["cpu_used"],
                    "memory_used": metrics_delta["memory_used"]
                }
                
                log_stage_boundary("audio_record", "exit", correlation_id, duration=duration)
                
                # --------------------------------
                # SPEECH TO TEXT STAGE
                # --------------------------------
                
                log_stage_boundary("speech_to_text", "enter", correlation_id)
                stage_start = time.time()
                start_metrics = _metrics_collector.capture()
                
                query = speech_to_text(audio_file)
                
                duration = time.time() - stage_start
                end_metrics = _metrics_collector.capture()
                metrics_delta = _metrics_collector.calculate_delta(start_metrics, end_metrics)
                
                stage_cpu_usage.labels(stage="speech_to_text").observe(metrics_delta["cpu_used"])
                stage_memory_usage.labels(stage="speech_to_text").observe(metrics_delta["memory_used"])
                stt_latency.observe(duration)
                query_length.observe(len(query))
                stt_word_count.observe(len(query.split()))
                
                print(f"\n🎤 User: {query}")
                
                result_metadata["stages"]["stt"] = {
                    "duration": duration,
                    "cpu_used": metrics_delta["cpu_used"],
                    "memory_used": metrics_delta["memory_used"],
                    "query": query,
                    "query_length": len(query),
                    "word_count": len(query.split())
                }
                
                log_stage_boundary("speech_to_text", "exit", correlation_id, 
                                  duration=duration, word_count=len(query.split()))
                
                # --------------------------------
                # RAG RETRIEVAL STAGE
                # --------------------------------
                
                result, retrieval_metadata = await query_rag(
                    rag=rag,
                    query=query,
                    mode="hybrid",
                    top_k=5
                )
                
                # Track no documents found
                if not result or "no documents found" in result.lower() or "can't assist" in result.lower():
                    rag_no_documents_found.labels(query_topic="general").inc()
                
                response_length.observe(len(result) if result else 0)
                
                print(f"\n🤖 AI: {result}")
                
                result_metadata["stages"]["rag_retrieval"] = retrieval_metadata
                result_metadata["response"] = result
                
                # --------------------------------
                # TEXT TO SPEECH STAGE (with context propagation)
                # --------------------------------
                
                if enable_tts and result:
                    log_stage_boundary("text_to_speech", "enter", correlation_id)
                    stage_start = time.time()
                    start_metrics = _metrics_collector.capture()
                    
                    # speak_async now properly propagates correlation context
                    audio_output = await speak_async(result)
                    
                    duration = time.time() - stage_start
                    end_metrics = _metrics_collector.capture()
                    metrics_delta = _metrics_collector.calculate_delta(start_metrics, end_metrics)
                    
                    stage_cpu_usage.labels(stage="text_to_speech").observe(metrics_delta["cpu_used"])
                    stage_memory_usage.labels(stage="text_to_speech").observe(metrics_delta["memory_used"])
                    tts_latency.observe(duration)
                    
                    result_metadata["stages"]["tts"] = {
                        "duration": duration,
                        "cpu_used": metrics_delta["cpu_used"],
                        "memory_used": metrics_delta["memory_used"],
                        "audio_file": audio_output
                    }
                    
                    log_stage_boundary("text_to_speech", "exit", correlation_id, duration=duration)
                
                # --------------------------------
                # PIPELINE COMPLETE
                # --------------------------------
                
                total_latency = time.time() - pipeline_start
                
                root_span.set_attribute("pipeline_latency_sec", total_latency)
                root_span.set_attribute("total_stages", len(result_metadata["stages"]))
                
                conversation_turns.observe(1)
                
                rag_requests_total.labels(
                    status="success",
                    user_type="authenticated" if user_id else "anonymous",
                    response_quality="good" if result and len(result) > 50 else "short"
                ).inc()
                
                _session_manager.update_session_stats(
                    session_id,
                    tokens=len(query.split()) + len(result.split()) if result else 0
                )
                
                logger.info({
                    "event": "request_completed",
                    "correlation_id": correlation_id,
                    "session_id": session_id,
                    "trace_id": trace_id,
                    "pipeline_latency": total_latency,
                    "stages": list(result_metadata["stages"].keys()),
                    "message": f"✅ REQUEST {correlation_id[:8]} COMPLETED in {total_latency:.1f}s"
                })
                
                print(f"\n{'='*70}")
                print(f"🟢 REQUEST COMPLETE: {total_latency:.1f}s")
                print(f"{'='*70}")
                
                return result_metadata
                
        except Exception as e:
            span_ctx = get_current_span()
            trace_id = format(span_ctx.get_span_context().trace_id, "032x") if span_ctx else "unknown"
            
            rag_requests_total.labels(
                status="failed",
                user_type="authenticated" if user_id else "anonymous",
                response_quality="error"
            ).inc()
            
            rag_errors_total.labels(
                stage="pipeline",
                error_type=type(e).__name__
            ).inc()
            
            logger.error({
                "event": "request_failed",
                "correlation_id": correlation_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "message": f"❌ REQUEST {correlation_id[:8]} FAILED: {str(e)[:100]}"
            })
            
            print(f"\n❌ Error: {e}")
            return None
            
        finally:
            rag_active_requests.dec()
            concurrent_requests.dec()
            
            cpu_usage_percent.labels(core="all").set(psutil.cpu_percent(interval=0.5))
            memory_usage_mb.labels(type="used").set(psutil.virtual_memory().used / (1024 * 1024))
            process_threads.set(psutil.Process().num_threads())
            
            total_latency = time.time() - pipeline_start
            pipeline_latency.observe(total_latency)
            rag_request_duration.labels(stage="total").observe(total_latency)
            
            clear_context()


# --------------------------------
# GRACEFUL SHUTDOWN
# --------------------------------

_shutdown_requested = False

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global _shutdown_requested
    print("\n\n🛑 Shutdown requested. Cleaning up...")
    _shutdown_requested = True


async def shutdown(rag):
    """Graceful shutdown of all components"""
    logger.info("Shutting down voice RAG agent...")
    cleanup_tts()
    await rag_cleanup()
    
    logger.info({
        "event": "shutdown_complete",
        "active_sessions": len(_session_manager._sessions)
    })


# --------------------------------
# MAIN PIPELINE
# --------------------------------

async def main():
    """Main entry point with enhanced observability"""
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info({
        "event": "application_start",
        "document_path": DOCUMENT_PATH,
        "rag_storage": RAG_STORAGE_PATH,
        "metrics_port": metrics_port
    })
    
    docs_exist = await is_document_processed()
    rag = await build_rag()
    
    if not docs_exist:
        print("\n📄 Processing document...")
        logger.info("Processing document for first time")
        
        success = await process_document_with_retry(rag)
        
        if not success:
            print("❌ Failed to process document. Please check logs.")
            logger.error("Document processing failed, exiting")
            return
    else:
        print("\n✅ Using existing document index")
    
    tts_info = get_tts_info()
    logger.info({
        "event": "tts_initialized",
        "tts_info": tts_info
    })
    
    print("\n" + "="*50)
    print("🎙️  VOICE RAG AGENT READY")
    print("="*50)
    print("\nCommands:")
    print("  • Press Enter to speak")
    print("  • Type 'exit' to quit")
    print("  • Type 'stats' to see session stats")
    print("  • Type 'health' for health check")
    print("="*50 + "\n")
    
    session_id = _session_manager.get_or_create_session()
    user_id = os.getenv("USER_ID", None)
    
    if user_id:
        set_user_id(user_id)
        print(f"👤 User: {user_id}")
    
    set_session_id(session_id)
    
    last_cleanup = time.time()
    
    while not _shutdown_requested:
        
        try:
            user_input = input("Press Enter to speak or type command: ").strip().lower()
            
            if user_input == "exit":
                break
            elif user_input == "stats":
                stats = _session_manager.get_session_stats(session_id)
                print(f"\n📊 Session Stats:")
                print(f"  • Requests: {stats.get('request_count', 0)}")
                print(f"  • Total Tokens: {stats.get('total_tokens', 0)}")
                print(f"  • Duration: {time.time() - stats.get('created_at', time.time()):.0f}s")
                continue
            elif user_input == "health":
                health = await health_check()
                print(f"\n💚 Health Status:")
                for component, status in health.items():
                    if component != "timestamp":
                        print(f"  • {component}: {status.get('status', 'unknown')}")
                continue
            elif user_input and user_input not in ["", "stats", "health", "exit"]:
                print(f"❌ Unknown command: {user_input}")
                continue
            
            await handle_user_request(
                rag=rag,
                session_id=session_id,
                user_id=user_id,
                enable_tts=True
            )
            
            if time.time() - last_cleanup > 300:
                _session_manager.cleanup_expired_sessions()
                last_cleanup = time.time()
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error({
                "event": "main_loop_error",
                "error": str(e),
                "error_type": type(e).__name__
            })
            print(f"\n❌ Unexpected error: {e}")
    
    await shutdown(rag)
    print("\n👋 Goodbye!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        logger.critical({
            "event": "fatal_error",
            "error": str(e),
            "error_type": type(e).__name__
        })
        print(f"\n💥 Fatal error: {e}")
        sys.exit(1)