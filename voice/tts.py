import pyttsx3
import os
import psutil
import time

from observability.logs_traces import setup_tracing, setup_logging
from observability.metrics import stage_cpu_usage, stage_memory_usage

tracer = setup_tracing()
logger = setup_logging()


def capture_system_metrics():
    process = psutil.Process()
    return {
        "cpu": process.cpu_percent(interval=None),
        "memory": process.memory_info().rss / (1024 * 1024)
    }


def speak(text, filename="response.wav"):

    with tracer.start_as_current_span("tts_engine") as span:

        start_metrics = capture_system_metrics()
        start = time.time()

        print("\n🔊 Generating speech audio...\n")

        engine = pyttsx3.init()
        engine.setProperty("rate", 170)

        try:
            engine.save_to_file(text, filename)
            engine.runAndWait()
        finally:
            engine.stop()

        duration = time.time() - start
        end_metrics = capture_system_metrics()

        cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
        memory_used = end_metrics["memory"] - start_metrics["memory"]

        # 🔥 TRACE ATTRIBUTES
        span.set_attribute("cpu_used", cpu_used)
        span.set_attribute("memory_used_mb", memory_used)
        span.set_attribute("duration", duration)

        # 🔥 METRICS
        stage_cpu_usage.labels(stage="tts_engine").observe(cpu_used)
        stage_memory_usage.labels(stage="tts_engine").observe(memory_used)

        logger.info({
            "event": "tts_completed",
            "cpu_used": cpu_used,
            "memory_used_mb": memory_used,
            "duration": duration
        })

    print(f"Audio saved as: {filename}")

    choice = input("Do you want to listen to the response? (y/n): ").lower()

    if choice == "y":
        print("\n🔊 Playing response...\n")
        os.startfile(filename)