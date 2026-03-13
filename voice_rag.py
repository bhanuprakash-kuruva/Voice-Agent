import asyncio
import time
import uuid

import psutil

from voice.stt import record_audio, speech_to_text
from voice.tts import speak
from rag_pipeline import build_rag

from observability.logs_traces import setup_tracing, setup_logging

from observability.metrics import *


# --------------------------------
# OBSERVABILITY
# --------------------------------

tracer = setup_tracing()
logger = setup_logging()

start_metrics_server()

logger.info("Metrics server started on port 8000")


# --------------------------------
# MAIN PIPELINE
# --------------------------------

async def main():

    rag = await build_rag()

    print("\nProcessing document...\n")

    await rag.process_document_complete(
        file_path="./data/document.pdf",
        output_dir="./output",
        parse_method="auto"
    )

    print("\nDocument processed successfully\n")

    while True:

        user_choice = input("\nPress Enter to speak or type 'exit': ")

        if user_choice.lower() == "exit":
            break

        correlation_id = str(uuid.uuid4())

        print(f"\nRequest ID: {correlation_id}")

        rag_active_requests.inc()

        pipeline_start = time.time()

        try:

            with tracer.start_as_current_span("rag_pipeline"):

                # AUDIO RECORD

                with tracer.start_as_current_span("audio_record"):

                    start = time.time()

                    audio_file = record_audio()

                    duration = time.time() - start

                    audio_latency.observe(duration)
                    audio_duration_seconds.observe(duration)

                # STT

                with tracer.start_as_current_span("speech_to_text"):

                    start = time.time()

                    query = speech_to_text(audio_file)

                    stt_latency.observe(time.time() - start)

                    query_length.observe(len(query))
                    stt_word_count.observe(len(query.split()))

                    print("\nUser:", query)

                # RETRIEVAL

                with tracer.start_as_current_span("rag_retrieval"):

                    start = time.time()

                    result = await rag.aquery(query, mode="hybrid")

                    retrieval_latency.observe(time.time() - start)

                    if not result:
                        rag_no_documents_found.inc()

                response_length.observe(len(result))

                print("\nAI:", result)

                # TTS

                with tracer.start_as_current_span("text_to_speech"):

                    start = time.time()

                    speak(result)

                    tts_latency.observe(time.time() - start)

                rag_requests_total.labels(status="success").inc()

        except Exception as e:

            rag_requests_total.labels(status="failed").inc()

            rag_errors_total.labels(stage="pipeline").inc()

            logger.error({
                "correlation_id": correlation_id,
                "error": str(e)
            })

            print("Error:", e)

        finally:

            rag_active_requests.dec()

        total_latency = time.time() - pipeline_start

        pipeline_latency.observe(total_latency)

        print("Pipeline latency:", total_latency)

        # SYSTEM METRICS

        cpu_usage_percent.set(psutil.cpu_percent())
        memory_usage_mb.set(psutil.virtual_memory().used / (1024 * 1024))
        process_threads.set(psutil.Process().num_threads())


if __name__ == "__main__":
    asyncio.run(main())