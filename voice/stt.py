import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from faster_whisper import WhisperModel
import psutil
import time
import os
import logging
from typing import Optional, Tuple, Dict, Any

from observability.logs_traces import setup_tracing, setup_logging, create_span, log_stage_boundary
from observability.metrics import (
    stage_cpu_usage, 
    stage_memory_usage,
    stt_latency,
    stt_word_count,
    stt_confidence,
    stt_errors_total,
    audio_duration_seconds,
    observe_latency,
    count_errors
)
from observability.context import get_correlation_id, get_user_id, get_session_id

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

SAMPLE_RATE = 16000
DEFAULT_DURATION = 5
MODEL_SIZE = os.getenv("WHISPER_MODEL", "small")
DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# --------------------------------
# MODEL INITIALIZATION
# --------------------------------

class WhisperModelManager:
    """Singleton manager for Whisper model"""
    
    _instance = None
    _model = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_model(self):
        """Get or initialize Whisper model"""
        if self._model is None:
            logger.info(f"Initializing Whisper model: {MODEL_SIZE} on {DEVICE} with {COMPUTE_TYPE}")
            self._model = WhisperModel(
                MODEL_SIZE,
                device=DEVICE,
                compute_type=COMPUTE_TYPE,
                cpu_threads=os.cpu_count(),
                num_workers=1
            )
            logger.info("Whisper model initialized successfully")
        return self._model


_model_manager = WhisperModelManager()


# --------------------------------
# SYSTEM METRICS HELPER
# --------------------------------

def capture_system_metrics() -> Dict[str, float]:
    """Capture current system metrics"""
    process = psutil.Process()
    cpu_times = process.cpu_times()
    
    return {
        "cpu_time": cpu_times.user + cpu_times.system,
        "memory": process.memory_info().rss / (1024 * 1024)
    }


def calculate_metrics_delta(start: Dict[str, float], end: Dict[str, float]) -> Dict[str, float]:
    """Calculate delta between two metric snapshots"""
    return {
        "cpu_used": end["cpu_time"] - start["cpu_time"],
        "memory_used": end["memory"] - start["memory"]
    }


# --------------------------------
# AUDIO RECORDING
# --------------------------------

@observe_latency(audio_duration_seconds)
def record_audio(
    filename: str = "mic_input.wav", 
    duration: int = DEFAULT_DURATION,
    sample_rate: int = SAMPLE_RATE
) -> str:
    """
    Record audio from microphone
    """
    correlation_id = get_correlation_id()
    log_stage_boundary("audio_record", "enter", correlation_id)
    
    with tracer.start_as_current_span("audio_capture") as span:
        
        # Add span attributes
        span.set_attribute("audio.duration", duration)
        span.set_attribute("audio.sample_rate", sample_rate)
        span.set_attribute("audio.filename", filename)
        span.set_attribute("correlation_id", correlation_id)
        
        # Capture start metrics
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        try:
            logger.info({
                "event": "audio_record_start",
                "duration": duration,
                "sample_rate": sample_rate,
                "correlation_id": correlation_id
            })
            
            print(f"\n🎤 Recording for {duration} seconds... Speak now!")
            
            # Record audio
            recording = sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="float32"
            )
            
            sd.wait()
            
            # Save to file
            write(filename, sample_rate, recording)
            
            # Calculate metrics
            duration_taken = time.time() - start_time
            end_metrics = capture_system_metrics()
            metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
            # Add trace attributes
            span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
            span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
            span.set_attribute("duration_sec", duration_taken)
            span.set_attribute("audio.size_bytes", os.path.getsize(filename))
            
            # Record metrics
            stage_cpu_usage.labels(stage="audio_capture").observe(metrics_delta["cpu_used"])
            stage_memory_usage.labels(stage="audio_capture").observe(metrics_delta["memory_used"])
            
            logger.info({
                "event": "audio_record_complete",
                "filename": filename,
                "duration": duration_taken,
                "size_bytes": os.path.getsize(filename),
                "cpu_used": metrics_delta["cpu_used"],
                "memory_used_mb": metrics_delta["memory_used"],
                "correlation_id": correlation_id
            })
            
            log_stage_boundary("audio_record", "exit", correlation_id, duration=duration_taken)
            return filename
            
        except Exception as e:
            logger.error({
                "event": "audio_record_failed",
                "error": str(e),
                "error_type": type(e).__name__,
                "correlation_id": correlation_id
            })
            raise


# --------------------------------
# SPEECH TO TEXT
# --------------------------------

@count_errors(stt_errors_total, "stt")
@observe_latency(stt_latency)
def speech_to_text(
    audio_file: str,
    beam_size: int = 5,
    vad_filter: bool = True,
    language: Optional[str] = None
) -> str:
    """
    Convert speech to text using Whisper
    """
    correlation_id = get_correlation_id()
    log_stage_boundary("speech_to_text", "enter", correlation_id)
    
    with tracer.start_as_current_span("whisper_inference") as span:
        
        # Add span attributes
        span.set_attribute("stt.model", MODEL_SIZE)
        span.set_attribute("stt.beam_size", beam_size)
        span.set_attribute("stt.vad_filter", vad_filter)
        span.set_attribute("stt.language", language or "auto")
        span.set_attribute("audio.file", audio_file)
        span.set_attribute("correlation_id", correlation_id)
        
        # Capture start metrics
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        try:
            # Get model instance
            model = _model_manager.get_model()
            
            # Transcribe
            logger.info({
                "event": "stt_start",
                "audio_file": audio_file,
                "model": MODEL_SIZE,
                "correlation_id": correlation_id
            })
            
            segments, info = model.transcribe(
                audio_file,
                beam_size=beam_size,
                vad_filter=vad_filter,
                language=language
            )
            
            # Process segments
            text_parts = []
            word_count = 0
            confidence_scores = []
            
            for segment in segments:
                text_parts.append(segment.text)
                word_count += len(segment.text.split())
                confidence_scores.append(segment.avg_logprob)
            
            text = " ".join(text_parts).strip()
            avg_confidence = np.mean(confidence_scores) if confidence_scores else 0
            
            # Calculate metrics
            duration = time.time() - start_time
            end_metrics = capture_system_metrics()
            metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
            # Add trace attributes
            span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
            span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
            span.set_attribute("duration_sec", duration)
            span.set_attribute("stt.text_length", len(text))
            span.set_attribute("stt.word_count", word_count)
            span.set_attribute("stt.confidence", avg_confidence)
            span.set_attribute("stt.language_detected", info.language if hasattr(info, 'language') else "unknown")
            
            # Record metrics
            stage_cpu_usage.labels(stage="stt").observe(metrics_delta["cpu_used"])
            stage_memory_usage.labels(stage="stt").observe(metrics_delta["memory_used"])
            stt_word_count.observe(word_count)
            stt_confidence.observe(avg_confidence)
            
            # Log successful transcription
            logger.info({
                "event": "stt_completed",
                "text": text[:100],
                "text_length": len(text),
                "word_count": word_count,
                "confidence": avg_confidence,
                "duration": duration,
                "cpu_used": metrics_delta["cpu_used"],
                "memory_used_mb": metrics_delta["memory_used"],
                "language_detected": info.language if hasattr(info, 'language') else "unknown",
                "correlation_id": correlation_id
            })
            
            log_stage_boundary("speech_to_text", "exit", correlation_id, 
                              duration=duration, word_count=word_count)
            
            return text
            
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            span.set_attribute("error.message", str(e))
            
            logger.error({
                "event": "stt_failed",
                "audio_file": audio_file,
                "error": str(e),
                "error_type": type(e).__name__,
                "correlation_id": correlation_id
            })
            raise


# --------------------------------
# UTILITY FUNCTIONS
# --------------------------------

def transcribe_with_timestamps(audio_file: str) -> Tuple[str, list]:
    """Transcribe with word-level timestamps"""
    with tracer.start_as_current_span("whisper_timestamp") as span:
        
        model = _model_manager.get_model()
        segments, _ = model.transcribe(audio_file, word_timestamps=True)
        
        full_text = []
        timestamps = []
        
        for segment in segments:
            full_text.append(segment.text)
            
            if hasattr(segment, 'words'):
                for word in segment.words:
                    timestamps.append({
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                        "confidence": word.probability if hasattr(word, 'probability') else None
                    })
        
        span.set_attribute("stt.word_count", len(timestamps))
        span.set_attribute("stt.segment_count", len(segments))
        
        return " ".join(full_text), timestamps


def get_audio_info(audio_file: str) -> Dict[str, Any]:
    """Get audio file information"""
    try:
        import wave
        with wave.open(audio_file, 'rb') as wav:
            return {
                "channels": wav.getnchannels(),
                "sample_width": wav.getsampwidth(),
                "frame_rate": wav.getframerate(),
                "frames": wav.getnframes(),
                "duration": wav.getnframes() / wav.getframerate()
            }
    except Exception as e:
        logger.warning(f"Could not read audio info: {e}")
        return {}