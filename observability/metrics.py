from prometheus_client import start_http_server, Counter, Histogram, Gauge, Summary, Info
import psutil
import time
from typing import Dict, Any
import asyncio
from functools import wraps

# --------------------------------
# SERVICE INFO
# --------------------------------

service_info = Info("voice_rag_service", "Voice RAG Service Information")
service_info.info({
    "version": "2.0",
    "name": "voice-rag-agent"
})

# --------------------------------
# REQUEST METRICS
# --------------------------------

rag_requests_total = Counter(
    "rag_requests_total",
    "Total RAG queries",
    ["status", "user_type", "response_quality"]
)

rag_active_requests = Gauge(
    "rag_active_requests",
    "Currently active RAG queries"
)

rag_request_duration = Histogram(
    "rag_request_duration_seconds",
    "Request duration in seconds",
    ["stage"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300)
)

# --------------------------------
# LATENCY METRICS (Enhanced)
# --------------------------------

pipeline_latency = Histogram(
    "rag_pipeline_latency_seconds", 
    "Total pipeline latency",
    buckets=(1, 2, 5, 10, 20, 30, 45, 60, 90, 120, 180, 240, 300)
)

audio_latency = Histogram(
    "audio_record_latency_seconds", 
    "Audio recording latency",
    buckets=(0.1, 0.5, 1, 2, 3, 4, 5)
)

stt_latency = Histogram(
    "stt_latency_seconds", 
    "Speech-to-text latency",
    buckets=(0.5, 1, 2, 3, 5, 7, 10, 15, 20)
)

retrieval_latency = Histogram(
    "rag_retrieval_latency_seconds", 
    "Vector retrieval latency",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30)
)

llm_latency = Histogram(
    "llm_latency_seconds", 
    "LLM generation latency",
    buckets=(0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30)
)

tts_latency = Histogram(
    "tts_latency_seconds", 
    "Text-to-speech latency",
    buckets=(0.5, 1, 2, 3, 5, 7, 10)
)

# --------------------------------
# TOKEN METRICS
# --------------------------------

prompt_tokens = Histogram(
    "llm_prompt_tokens", 
    "Prompt token count",
    buckets=(50, 100, 200, 300, 500, 750, 1000, 1500, 2000)
)

completion_tokens = Histogram(
    "llm_completion_tokens", 
    "Completion token count",
    buckets=(10, 20, 50, 100, 150, 200, 250, 300, 400, 500)
)

total_tokens = Histogram(
    "llm_total_tokens", 
    "Total tokens",
    buckets=(50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 2500)
)

tokens_per_second = Histogram(
    "llm_tokens_per_second", 
    "Token generation speed",
    buckets=(5, 10, 20, 30, 40, 50, 75, 100, 150, 200)
)

# --------------------------------
# QUERY METRICS
# --------------------------------

query_length = Histogram(
    "rag_query_length_chars", 
    "Length of user queries",
    buckets=(10, 20, 50, 100, 200, 500, 1000)
)

response_length = Histogram(
    "rag_response_length_chars", 
    "Length of responses",
    buckets=(20, 50, 100, 200, 500, 1000, 2000, 5000)
)

# --------------------------------
# RETRIEVAL QUALITY METRICS
# --------------------------------

documents_retrieved = Histogram(
    "rag_documents_retrieved", 
    "Number of retrieved documents",
    buckets=(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
)

rag_no_documents_found = Counter(
    "rag_no_documents_found_total", 
    "Queries with no documents retrieved",
    ["query_topic"]
)

retrieval_similarity_score = Histogram(
    "rag_retrieval_similarity_score", 
    "Similarity scores",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99)
)

# --------------------------------
# VOICE METRICS
# --------------------------------

audio_duration_seconds = Histogram(
    "audio_input_duration_seconds", 
    "Audio duration",
    buckets=(0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
)

stt_word_count = Histogram(
    "stt_word_count", 
    "STT word count",
    buckets=(1, 2, 5, 10, 15, 20, 25, 30, 40, 50)
)

stt_confidence = Histogram(
    "stt_confidence_score",
    "Speech recognition confidence score",
    buckets=(0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99)
)

# --------------------------------
# EMBEDDING METRICS
# --------------------------------

embedding_requests_total = Counter(
    "embedding_requests_total", 
    "Total embedding requests",
    ["model", "batch_size_range"]
)

embedding_latency = Histogram(
    "embedding_latency_seconds", 
    "Embedding latency",
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5)
)

embedding_batch_size = Histogram(
    "embedding_batch_size",
    "Number of texts in embedding batch",
    buckets=(1, 2, 5, 10, 20, 50, 100)
)

# --------------------------------
# LLM REQUESTS
# --------------------------------

llm_requests_total = Counter(
    "llm_requests_total", 
    "Total LLM requests",
    ["model", "status"]
)

llm_cache_hits = Counter(
    "llm_cache_hits_total",
    "LLM cache hits"
)

llm_cache_misses = Counter(
    "llm_cache_misses_total",
    "LLM cache misses"
)

# --------------------------------
# RESOURCE METRICS (Enhanced)
# --------------------------------

cpu_usage_percent = Gauge(
    "system_cpu_usage_percent", 
    "CPU usage percent",
    ["core"]
)

memory_usage_mb = Gauge(
    "system_memory_usage_mb", 
    "Memory usage in MB",
    ["type"]
)

process_threads = Gauge(
    "process_threads", 
    "Number of threads"
)

process_open_files = Gauge(
    "process_open_files",
    "Number of open file descriptors"
)

# GC metrics
gc_cycles_total = Counter(
    "python_gc_cycles_total",
    "Garbage collection cycles",
    ["generation"]
)

# Per-stage resource usage
stage_cpu_usage = Histogram(
    "rag_stage_cpu_usage_seconds",
    "CPU usage per pipeline stage",
    ["stage"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60)
)

stage_memory_usage = Histogram(
    "rag_stage_memory_usage_mb",
    "Memory usage per pipeline stage",
    ["stage"],
    buckets=(10, 50, 100, 200, 300, 500, 750, 1000, 1500, 2000)
)

# LLM specific resource metrics
llm_memory_usage = Histogram(
    "llm_memory_usage_mb",
    "Memory used during LLM execution",
    buckets=(50, 100, 200, 300, 500, 750, 1000, 1500)
)

llm_cpu_usage = Histogram(
    "llm_cpu_usage_seconds",
    "CPU used during LLM execution",
    buckets=(0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30)
)

# --------------------------------
# CUSTOMER EXPERIENCE METRICS
# --------------------------------

user_satisfaction = Gauge(
    "user_satisfaction_score",
    "User satisfaction score (0-10)",
    ["user_type"]
)

response_helpfulness = Counter(
    "response_helpfulness_total",
    "User feedback on response helpfulness",
    ["helpful", "not_helpful"]
)

conversation_turns = Histogram(
    "conversation_turns_per_session",
    "Number of turns per conversation session",
    buckets=(1, 2, 3, 5, 7, 10, 15, 20)
)

# --------------------------------
# ERROR METRICS (Enhanced)
# --------------------------------

rag_errors_total = Counter(
    "rag_errors_total",
    "Errors in RAG pipeline",
    ["stage", "error_type"]
)

stt_errors_total = Counter(
    "stt_errors_total",
    "Speech-to-text errors",
    ["error_type"]
)

tts_errors_total = Counter(
    "tts_errors_total",
    "Text-to-speech errors",
    ["error_type"]
)

# --------------------------------
# BUSINESS METRICS
# --------------------------------

requests_per_user = Counter(
    "requests_per_user_total",
    "Total requests per user",
    ["user_id", "user_type"]
)

documents_processed = Counter(
    "documents_processed_total",
    "Total documents processed",
    ["document_type", "status"]
)

active_sessions = Gauge(
    "active_sessions",
    "Number of active user sessions"
)

# --------------------------------
# PERFORMANCE METRICS
# --------------------------------

queue_wait_time = Histogram(
    "request_queue_wait_seconds",
    "Time spent waiting in queue",
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5)
)

throughput = Gauge(
    "requests_per_second",
    "Request throughput"
)

concurrent_requests = Gauge(
    "concurrent_requests",
    "Number of concurrent requests"
)

# --------------------------------
# METRICS COLLECTOR
# --------------------------------

class MetricsCollector:
    """Async metrics collector for system resources"""
    
    def __init__(self, interval_seconds: int = 10):
        self.interval = interval_seconds
        self._running = False
        self._task = None
        
    async def start(self):
        """Start collecting system metrics"""
        self._running = True
        self._task = asyncio.create_task(self._collect_loop())
        
    async def stop(self):
        """Stop collecting metrics"""
        self._running = False
        if self._task:
            self._task.cancel()
            await self._task
            
    async def _collect_loop(self):
        """Background metrics collection loop"""
        while self._running:
            try:
                await self._collect_metrics()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logging.error(f"Metrics collection error: {e}")
                
    async def _collect_metrics(self):
        """Collect system metrics"""
        # CPU per core
        for i, percent in enumerate(psutil.cpu_percent(percpu=True)):
            cpu_usage_percent.labels(core=f"core_{i}").set(percent)
        
        # Memory metrics
        mem = psutil.virtual_memory()
        memory_usage_mb.labels(type="used").set(mem.used / (1024 * 1024))
        memory_usage_mb.labels(type="available").set(mem.available / (1024 * 1024))
        
        # Process metrics
        process = psutil.Process()
        process_threads.set(process.num_threads())
        process_open_files.set(process.num_fds() if hasattr(process, 'num_fds') else 0)


# --------------------------------
# METRICS SERVER
# --------------------------------

_metrics_server_started = False

def start_metrics_server(port: int = 8000, addr: str = "0.0.0.0"):
    """Start Prometheus metrics server"""
    global _metrics_server_started
    
    if not _metrics_server_started:
        start_http_server(port, addr)
        _metrics_server_started = True
        logging.info(f"Metrics server started on {addr}:{port}")


# --------------------------------
# DECORATORS FOR EASY METRICS
# --------------------------------

def observe_latency(metric: Histogram, labels: Dict[str, str] = None):
    """Decorator to observe function latency"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                if labels:
                    metric.labels(**labels).observe(duration)
                else:
                    metric.observe(duration)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def count_errors(metric: Counter, stage: str):
    """Decorator to count errors"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                error_type = type(e).__name__
                metric.labels(stage=stage, error_type=error_type).inc()
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_type = type(e).__name__
                metric.labels(stage=stage, error_type=error_type).inc()
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


# Import logging
import logging