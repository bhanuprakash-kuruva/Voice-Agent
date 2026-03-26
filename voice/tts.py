# import pyttsx3
# import os
# import psutil
# import time
# import tempfile
# import logging
# from typing import Optional, Dict, Any
# import asyncio
# from concurrent.futures import ThreadPoolExecutor
# import threading

# from observability.logs_traces import setup_tracing, setup_logging, create_span, log_stage_boundary
# from observability.metrics import (
#     stage_cpu_usage,
#     stage_memory_usage,
#     tts_latency,
#     tts_errors_total,
#     observe_latency,
#     count_errors
# )
# from observability.context import get_correlation_id, get_user_id, get_session_id
# from opentelemetry import trace
# from opentelemetry.trace import get_current_span

# # --------------------------------
# # OBSERVABILITY SETUP
# # --------------------------------

# tracer = setup_tracing()
# logger = setup_logging(
#     log_level="INFO",
#     log_file="C:/Users/Bhanu Prakash Kuruva/Documents/ollama-rag/voice-rag.log",
#     enable_console=True
# )

# # --------------------------------
# # CONFIGURATION
# # --------------------------------

# DEFAULT_RATE = 170
# DEFAULT_VOLUME = 1.0
# DEFAULT_VOICE_ID = None

# # Thread pool for async TTS operations
# _tts_executor = ThreadPoolExecutor(max_workers=1)


# # --------------------------------
# # SYSTEM METRICS HELPER
# # --------------------------------

# def capture_system_metrics() -> Dict[str, float]:
#     """Capture current system metrics"""
#     process = psutil.Process()
#     cpu_times = process.cpu_times()
    
#     return {
#         "cpu_time": cpu_times.user + cpu_times.system,
#         "memory": process.memory_info().rss / (1024 * 1024),
#         "cpu_percent": process.cpu_percent(interval=None)
#     }


# def calculate_metrics_delta(start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
#     """Calculate delta between two metric snapshots"""
#     return {
#         "cpu_used": end["cpu_time"] - start["cpu_time"],
#         "memory_used": end["memory"] - start["memory"],
#         "cpu_percent_used": end["cpu_percent"] - start["cpu_percent"]
#     }


# # --------------------------------
# # TEXT TO SPEECH (FIXED - CREATES NEW ENGINE EACH TIME)
# # --------------------------------

# @count_errors(tts_errors_total, "tts")
# def speak(
#     text: str,
#     filename: Optional[str] = None,
#     rate: int = DEFAULT_RATE,
#     volume: float = DEFAULT_VOLUME,
#     wait: bool = True
# ) -> str:
#     """
#     Convert text to speech - creates fresh engine each time (working pattern)
#     """
#     # Skip empty text
#     if not text or not text.strip():
#         logger.warning("Empty text provided for TTS")
#         return ""
    
#     correlation_id = get_correlation_id()
    
#     with tracer.start_as_current_span("tts_engine") as span:
        
#         # Generate filename if not provided
#         if filename is None:
#             filename = os.path.join(
#                 tempfile.gettempdir(),
#                 f"tts_response_{int(time.time())}.wav"
#             )
        
#         # Add span attributes
#         span.set_attribute("tts.text_length", len(text))
#         span.set_attribute("tts.word_count", len(text.split()))
#         span.set_attribute("tts.rate", rate)
#         span.set_attribute("tts.volume", volume)
#         span.set_attribute("tts.filename", filename)
#         span.set_attribute("correlation_id", correlation_id)
        
#         user_id = get_user_id()
#         session_id = get_session_id()
#         if user_id:
#             span.set_attribute("user_id", user_id)
#         if session_id:
#             span.set_attribute("session_id", session_id)
        
#         # Capture start metrics
#         start_metrics = capture_system_metrics()
#         start_time = time.time()
        
#         engine = None
        
#         try:
#             logger.info({
#                 "event": "tts_start",
#                 "text_length": len(text),
#                 "word_count": len(text.split()),
#                 "filename": filename,
#                 "correlation_id": correlation_id
#             })
            
#             print("\n🔊 Generating speech audio...")
            
#             # CRITICAL FIX: Create a NEW engine instance for each request
#             # This avoids the deadlock issues with reused engines
#             engine = pyttsx3.init()
#             engine.setProperty("rate", rate)
#             engine.setProperty("volume", volume)
            
#             # Set voice if specified
#             if DEFAULT_VOICE_ID:
#                 voices = engine.getProperty('voices')
#                 for voice in voices:
#                     if DEFAULT_VOICE_ID in voice.id:
#                         engine.setProperty('voice', voice.id)
#                         break
            
#             # Generate speech
#             engine.save_to_file(text, filename)
            
#             if wait:
#                 # Run and wait - this will complete normally
#                 engine.runAndWait()
            
#             # Calculate metrics
#             duration = time.time() - start_time
#             end_metrics = capture_system_metrics()
#             metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
#             # Add trace attributes
#             span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
#             span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
#             span.set_attribute("duration_sec", duration)
            
#             if os.path.exists(filename):
#                 span.set_attribute("tts.file_size_bytes", os.path.getsize(filename))
            
#             # Record metrics
#             stage_cpu_usage.labels(stage="tts").observe(metrics_delta["cpu_used"])
#             stage_memory_usage.labels(stage="tts").observe(metrics_delta["memory_used"])
#             tts_latency.observe(duration)
            
#             logger.info({
#                 "event": "tts_completed",
#                 "filename": filename,
#                 "duration": duration,
#                 "cpu_used": metrics_delta["cpu_used"],
#                 "memory_used_mb": metrics_delta["memory_used"],
#                 "text_length": len(text),
#                 "correlation_id": correlation_id
#             })
            
#             return filename
            
#         except Exception as e:
#             span.set_attribute("error", True)
#             span.set_attribute("error.type", type(e).__name__)
#             span.set_attribute("error.message", str(e))
            
#             logger.error({
#                 "event": "tts_failed",
#                 "error": str(e),
#                 "error_type": type(e).__name__,
#                 "text": text[:100],
#                 "correlation_id": correlation_id
#             })
#             raise
        
#         finally:
#             # CRITICAL FIX: Always stop and cleanup the engine
#             if engine:
#                 try:
#                     engine.stop()
#                 except Exception as e:
#                     logger.warning(f"Error stopping TTS engine: {e}")


# # --------------------------------
# # ASYNC VERSION WITH CONTEXT PROPAGATION
# # --------------------------------

# async def speak_async(
#     text: str,
#     filename: Optional[str] = None,
#     rate: int = DEFAULT_RATE,
#     volume: float = DEFAULT_VOLUME
# ) -> str:
#     """
#     Async version of speak function with proper context propagation
#     """
#     if not text or not text.strip():
#         return ""
    
#     # Capture current context BEFORE switching threads
#     correlation_id = get_correlation_id()
#     user_id = get_user_id()
#     session_id = get_session_id()
    
#     # Get current span for trace propagation
#     current_span = get_current_span()
#     current_context = trace.set_span_in_context(current_span)
    
#     log_stage_boundary("text_to_speech", "enter", correlation_id)
    
#     loop = asyncio.get_event_loop()
    
#     def speak_with_context():
#         """Wrapper to restore observability context in the thread pool thread"""
#         from observability.context import set_correlation_id, set_user_id, set_session_id
        
#         # Restore context variables in this thread
#         set_correlation_id(correlation_id)
#         if user_id:
#             set_user_id(user_id)
#         if session_id:
#             set_session_id(session_id)
        
#         # Create a new span linked to parent trace
#         with tracer.start_as_current_span("tts_engine_async", context=current_context) as span:
#             span.set_attribute("correlation_id", correlation_id)
#             span.set_attribute("tts.text_length", len(text))
#             return speak(text, filename, rate, volume, True)
    
#     try:
#         result = await loop.run_in_executor(
#             _tts_executor,
#             speak_with_context
#         )
#         log_stage_boundary("text_to_speech", "exit", correlation_id)
#         return result
#     except Exception as e:
#         logger.error({
#             "event": "tts_async_failed",
#             "error": str(e),
#             "correlation_id": correlation_id
#         })
#         log_stage_boundary("text_to_speech", "exit", correlation_id, status="failed")
#         return ""
#     finally:
#         log_stage_boundary("text_to_speech", "exit", correlation_id)


# # --------------------------------
# # UTILITY FUNCTIONS
# # --------------------------------

# def get_available_voices() -> list:
#     """Get list of available voices"""
#     try:
#         engine = pyttsx3.init()
#         voices = engine.getProperty('voices')
#         result = [
#             {
#                 "id": voice.id,
#                 "name": voice.name,
#                 "languages": voice.languages,
#                 "gender": getattr(voice, 'gender', 'unknown')
#             }
#             for voice in voices
#         ]
#         engine.stop()
#         return result
#     except Exception as e:
#         logger.error(f"Failed to get voices: {e}")
#         return []


# def set_default_voice(voice_name: str) -> bool:
#     """Set default voice by name"""
#     global DEFAULT_VOICE_ID
#     try:
#         engine = pyttsx3.init()
#         voices = engine.getProperty('voices')
#         for voice in voices:
#             if voice_name.lower() in voice.name.lower():
#                 DEFAULT_VOICE_ID = voice.id
#                 logger.info(f"Default voice set to: {voice.name}")
#                 engine.stop()
#                 return True
#         engine.stop()
#         logger.warning(f"Voice '{voice_name}' not found")
#         return False
#     except Exception as e:
#         logger.error(f"Failed to set voice: {e}")
#         return False


# def get_tts_info() -> Dict[str, Any]:
#     """Get TTS engine information"""
#     try:
#         engine = pyttsx3.init()
#         info = {
#             "rate": engine.getProperty('rate'),
#             "volume": engine.getProperty('volume'),
#             "voices": len(engine.getProperty('voices')),
#             "available": True
#         }
#         engine.stop()
#         return info
#     except Exception as e:
#         logger.error(f"Failed to get TTS info: {e}")
#         return {
#             "available": False,
#             "error": str(e)
#         }


# def cleanup_tts():
#     """Cleanup TTS resources"""
#     logger.info("Cleaning up TTS resources")
#     _tts_executor.shutdown(wait=False)
import pyttsx3
import os
import psutil
import time
import tempfile
import logging
from typing import Optional, Dict, Any
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

from observability.logs_traces import setup_tracing, setup_logging, create_span, log_stage_boundary
from observability.metrics import (
    stage_cpu_usage,
    stage_memory_usage,
    tts_latency,
    tts_errors_total,
    observe_latency,
    count_errors
)
from observability.context import get_correlation_id, get_user_id, get_session_id
from opentelemetry import trace
from opentelemetry.trace import get_current_span

# --------------------------------
# OBSERVABILITY SETUP
# --------------------------------

tracer = setup_tracing()
logger = setup_logging(
    log_level="INFO",
    log_file="C:/Users/Bhanu Prakash Kuruva/Documents/ollama-rag/voice-rag.log",
    enable_console=True
)

# --------------------------------
# CONFIGURATION
# --------------------------------

DEFAULT_RATE = 170
DEFAULT_VOLUME = 1.0
DEFAULT_VOICE_ID = None
AUTO_PLAY = False  # Set to False to ask user before playing
OUTPUT_FILENAME = "response.wav"  # Fixed output filename in current folder

# Thread pool for async TTS operations
_tts_executor = ThreadPoolExecutor(max_workers=1)


# --------------------------------
# SYSTEM METRICS HELPER
# --------------------------------

def capture_system_metrics() -> Dict[str, float]:
    """Capture current system metrics"""
    process = psutil.Process()
    cpu_times = process.cpu_times()
    
    return {
        "cpu_time": cpu_times.user + cpu_times.system,
        "memory": process.memory_info().rss / (1024 * 1024),
        "cpu_percent": process.cpu_percent(interval=None)
    }


def calculate_metrics_delta(start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
    """Calculate delta between two metric snapshots"""
    return {
        "cpu_used": end["cpu_time"] - start["cpu_time"],
        "memory_used": end["memory"] - start["memory"],
        "cpu_percent_used": end["cpu_percent"] - start["cpu_percent"]
    }


# --------------------------------
# TEXT TO SPEECH (WITH USER PROMPT)
# --------------------------------

@count_errors(tts_errors_total, "tts")
def speak(
    text: str,
    filename: Optional[str] = None,
    rate: int = DEFAULT_RATE,
    volume: float = DEFAULT_VOLUME,
    wait: bool = True,
    auto_play: bool = AUTO_PLAY
) -> str:
    """
    Convert text to speech - saves to response.wav, asks user if they want to play
    """
    # Skip empty text
    if not text or not text.strip():
        logger.warning("Empty text provided for TTS")
        return ""
    
    correlation_id = get_correlation_id()
    
    with tracer.start_as_current_span("tts_engine") as span:
        
        # Use fixed filename in current folder if not specified
        if filename is None:
            # Get the current working directory
            current_dir = os.getcwd()
            filename = os.path.join(current_dir, OUTPUT_FILENAME)
        
        # Add span attributes
        span.set_attribute("tts.text_length", len(text))
        span.set_attribute("tts.word_count", len(text.split()))
        span.set_attribute("tts.rate", rate)
        span.set_attribute("tts.volume", volume)
        span.set_attribute("tts.filename", filename)
        span.set_attribute("correlation_id", correlation_id)
        
        user_id = get_user_id()
        session_id = get_session_id()
        if user_id:
            span.set_attribute("user_id", user_id)
        if session_id:
            span.set_attribute("session_id", session_id)
        
        # Capture start metrics
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        engine = None
        
        try:
            logger.info({
                "event": "tts_start",
                "text_length": len(text),
                "word_count": len(text.split()),
                "filename": filename,
                "correlation_id": correlation_id
            })
            
            print("\n🔊 Generating speech audio...")
            
            # Create a NEW engine instance for each request
            engine = pyttsx3.init()
            engine.setProperty("rate", rate)
            engine.setProperty("volume", volume)
            
            # Set voice if specified
            if DEFAULT_VOICE_ID:
                voices = engine.getProperty('voices')
                for voice in voices:
                    if DEFAULT_VOICE_ID in voice.id:
                        engine.setProperty('voice', voice.id)
                        break
            
            # Generate speech
            engine.save_to_file(text, filename)
            
            if wait:
                engine.runAndWait()
            
            # Calculate metrics
            duration = time.time() - start_time
            end_metrics = capture_system_metrics()
            metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
            # Add trace attributes
            span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
            span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
            span.set_attribute("duration_sec", duration)
            
            if os.path.exists(filename):
                span.set_attribute("tts.file_size_bytes", os.path.getsize(filename))
            
            # Record metrics
            stage_cpu_usage.labels(stage="tts").observe(metrics_delta["cpu_used"])
            stage_memory_usage.labels(stage="tts").observe(metrics_delta["memory_used"])
            tts_latency.observe(duration)
            
            logger.info({
                "event": "tts_completed",
                "filename": filename,
                "duration": duration,
                "cpu_used": metrics_delta["cpu_used"],
                "memory_used_mb": metrics_delta["memory_used"],
                "text_length": len(text),
                "correlation_id": correlation_id
            })
            
            print(f"✅ Audio saved as: {filename}")
            
            # --------------------------------
            # ASK USER IF THEY WANT TO PLAY (INTERACTIVE)
            # --------------------------------
            if auto_play:
                print("\n🔊 Playing response...")
                try:
                    if os.name == 'nt':  # Windows
                        os.startfile(filename)
                    elif os.name == 'posix':  # macOS/Linux
                        import subprocess
                        subprocess.run(['afplay' if os.uname().sysname == 'Darwin' else 'aplay', filename])
                except Exception as e:
                    logger.warning(f"Could not auto-play audio: {e}")
                    print(f"⚠️ Could not auto-play. File saved at: {filename}")
            else:
                # Ask user if they want to listen (like original working version)
                choice = input("Do you want to listen to the response? (y/n): ").lower()
                if choice == "y":
                    print("\n🔊 Playing response...")
                    try:
                        if os.name == 'nt':
                            os.startfile(filename)
                        elif os.name == 'posix':
                            import subprocess
                            subprocess.run(['afplay' if os.uname().sysname == 'Darwin' else 'aplay', filename])
                    except Exception as e:
                        logger.warning(f"Could not play audio: {e}")
                        print(f"⚠️ Could not play. File saved at: {filename}")
                else:
                    print(f"ℹ️ You can play the file later: {filename}")
            
            return filename
            
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            
            logger.error({
                "event": "tts_failed",
                "error": str(e),
                "error_type": type(e).__name__,
                "text": text[:100],
                "correlation_id": correlation_id
            })
            raise
        
        finally:
            # Always stop and cleanup the engine
            if engine:
                try:
                    engine.stop()
                except Exception as e:
                    logger.warning(f"Error stopping TTS engine: {e}")


# --------------------------------
# ASYNC VERSION WITH CONTEXT PROPAGATION
# --------------------------------

async def speak_async(
    text: str,
    filename: Optional[str] = None,
    rate: int = DEFAULT_RATE,
    volume: float = DEFAULT_VOLUME,
    auto_play: bool = AUTO_PLAY
) -> str:
    """
    Async version of speak function with proper context propagation
    """
    if not text or not text.strip():
        return ""
    
    # Capture current context BEFORE switching threads
    correlation_id = get_correlation_id()
    user_id = get_user_id()
    session_id = get_session_id()
    
    # Get current span for trace propagation
    current_span = get_current_span()
    current_context = trace.set_span_in_context(current_span)
    
    log_stage_boundary("text_to_speech", "enter", correlation_id)
    
    loop = asyncio.get_event_loop()
    
    def speak_with_context():
        """Wrapper to restore observability context in the thread pool thread"""
        from observability.context import set_correlation_id, set_user_id, set_session_id
        
        # Restore context variables in this thread
        set_correlation_id(correlation_id)
        if user_id:
            set_user_id(user_id)
        if session_id:
            set_session_id(session_id)
        
        # Create a new span linked to parent trace
        with tracer.start_as_current_span("tts_engine_async", context=current_context) as span:
            span.set_attribute("correlation_id", correlation_id)
            span.set_attribute("tts.text_length", len(text))
            return speak(text, filename, rate, volume, True, auto_play)
    
    try:
        result = await loop.run_in_executor(
            _tts_executor,
            speak_with_context
        )
        log_stage_boundary("text_to_speech", "exit", correlation_id)
        return result
    except Exception as e:
        logger.error({
            "event": "tts_async_failed",
            "error": str(e),
            "correlation_id": correlation_id
        })
        log_stage_boundary("text_to_speech", "exit", correlation_id, status="failed")
        return ""
    finally:
        log_stage_boundary("text_to_speech", "exit", correlation_id)


# --------------------------------
# UTILITY FUNCTIONS
# --------------------------------

def get_available_voices() -> list:
    """Get list of available voices"""
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        result = [
            {
                "id": voice.id,
                "name": voice.name,
                "languages": voice.languages,
                "gender": getattr(voice, 'gender', 'unknown')
            }
            for voice in voices
        ]
        engine.stop()
        return result
    except Exception as e:
        logger.error(f"Failed to get voices: {e}")
        return []


def set_default_voice(voice_name: str) -> bool:
    """Set default voice by name"""
    global DEFAULT_VOICE_ID
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        for voice in voices:
            if voice_name.lower() in voice.name.lower():
                DEFAULT_VOICE_ID = voice.id
                logger.info(f"Default voice set to: {voice.name}")
                engine.stop()
                return True
        engine.stop()
        logger.warning(f"Voice '{voice_name}' not found")
        return False
    except Exception as e:
        logger.error(f"Failed to set voice: {e}")
        return False


def get_tts_info() -> Dict[str, Any]:
    """Get TTS engine information"""
    try:
        engine = pyttsx3.init()
        info = {
            "rate": engine.getProperty('rate'),
            "volume": engine.getProperty('volume'),
            "voices": len(engine.getProperty('voices')),
            "available": True
        }
        engine.stop()
        return info
    except Exception as e:
        logger.error(f"Failed to get TTS info: {e}")
        return {
            "available": False,
            "error": str(e)
        }


def cleanup_tts():
    """Cleanup TTS resources"""
    logger.info("Cleaning up TTS resources")
    _tts_executor.shutdown(wait=False)