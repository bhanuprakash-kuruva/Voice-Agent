import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from faster_whisper import WhisperModel

import psutil
import time

from observability.logs_traces import setup_tracing, setup_logging
from observability.metrics import stage_cpu_usage, stage_memory_usage

tracer = setup_tracing()
logger = setup_logging()

SAMPLE_RATE = 16000

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8"
)


def capture_system_metrics():
    process = psutil.Process()
    return {
        "cpu": process.cpu_percent(interval=None),
        "memory": process.memory_info().rss / (1024 * 1024)
    }


def record_audio(filename="mic_input.wav", duration=5):

    with tracer.start_as_current_span("audio_capture") as span:

        start_metrics = capture_system_metrics()
        start = time.time()

        print("\n🎤 Speak now...")

        recording = sd.rec(
            int(duration * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32"
        )

        sd.wait()

        write(filename, SAMPLE_RATE, recording)

        duration_taken = time.time() - start
        end_metrics = capture_system_metrics()

        cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
        memory_used = end_metrics["memory"] - start_metrics["memory"]

        span.set_attribute("cpu_used", cpu_used)
        span.set_attribute("memory_used_mb", memory_used)

        stage_cpu_usage.labels(stage="audio_capture").observe(cpu_used)
        stage_memory_usage.labels(stage="audio_capture").observe(memory_used)

    return filename


def speech_to_text(audio_file):

    with tracer.start_as_current_span("whisper_inference") as span:

        start_metrics = capture_system_metrics()
        start = time.time()

        segments, _ = model.transcribe(
            audio_file,
            beam_size=5,
            vad_filter=True
        )

        text = ""
        for segment in segments:
            text += segment.text

        duration = time.time() - start
        end_metrics = capture_system_metrics()

        cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
        memory_used = end_metrics["memory"] - start_metrics["memory"]

        span.set_attribute("cpu_used", cpu_used)
        span.set_attribute("memory_used_mb", memory_used)
        span.set_attribute("duration", duration)

        stage_cpu_usage.labels(stage="whisper_inference").observe(cpu_used)
        stage_memory_usage.labels(stage="whisper_inference").observe(memory_used)

        logger.info({
            "event": "stt_completed",
            "cpu_used": cpu_used,
            "memory_used_mb": memory_used,
            "duration": duration
        })

        return text.strip()