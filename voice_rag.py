# import asyncio
# import time
# import uuid
# import os
# import glob
# import psutil

# from voice.stt import record_audio, speech_to_text
# from voice.tts import speak
# from rag_pipeline import build_rag

# from observability.logs_traces import setup_tracing, setup_logging
# from observability.metrics import *

# from observability.context import set_correlation_id
# from opentelemetry.trace import get_current_span


# # --------------------------------
# # OBSERVABILITY
# # --------------------------------

# tracer = setup_tracing()
# logger = setup_logging()

# start_metrics_server()

# logger.info("Metrics server started on port 8000")


# # --------------------------------
# # SYSTEM METRICS HELPER (🔥 CRITICAL)
# # --------------------------------

# def capture_system_metrics():
#     process = psutil.Process()
#     return {
#         "cpu": process.cpu_percent(interval=None),
#         "memory": process.memory_info().rss / (1024 * 1024)
#     }


# # --------------------------------
# # CHECK IF DOCUMENT EXISTS
# # --------------------------------

# async def is_document_processed():
#     rag_storage_path = os.getenv("WORKING_DIR", "./rag_storage")

#     graph_file = os.path.join(rag_storage_path, "graph_chunk_entity_relation.graphml")
#     if os.path.exists(graph_file) and os.path.getsize(graph_file) > 100:
#         return True

#     vdb_files = glob.glob(os.path.join(rag_storage_path, "vdb_*.json"))
#     for vdb in vdb_files:
#         if os.path.getsize(vdb) > 1000:
#             return True

#     chunks_file = os.path.join(rag_storage_path, "text_chunks.json")
#     if os.path.exists(chunks_file) and os.path.getsize(chunks_file) > 100:
#         return True

#     return False


# # --------------------------------
# # MAIN PIPELINE
# # --------------------------------

# async def main():

#     docs_exist = await is_document_processed()

#     if not docs_exist:
#         print("Processing document.pdf...")
#         rag = await build_rag()
#         await rag.process_document_complete(
#             file_path="./data/document.pdf",
#             output_dir="./output",
#             parse_method="auto"
#         )
#     else:
#         print("Using existing documents...")

#     rag = await build_rag()

#     while True:

#         user_choice = input("\nPress Enter to speak or type 'sacchipo': ")

#         if user_choice.lower() == "sacchipo":
#             break

#         # --------------------------------
#         # CORRELATION
#         # --------------------------------

#         correlation_id = str(uuid.uuid4())
#         set_correlation_id(correlation_id)

#         print(f"\nRequest ID: {correlation_id}")

#         rag_active_requests.inc()
#         pipeline_start = time.time()

#         try:

#             with tracer.start_as_current_span("rag_pipeline") as root_span:

#                 root_span.set_attribute("correlation_id", correlation_id)

#                 span_ctx = get_current_span()
#                 trace_id = format(span_ctx.get_span_context().trace_id, "032x")

#                 logger.info({
#                     "event": "request_started",
#                     "correlation_id": correlation_id,
#                     "trace_id": trace_id
#                 })

#                 # --------------------------------
#                 # AUDIO RECORD
#                 # --------------------------------

#                 with tracer.start_as_current_span("audio_record") as span:

#                     start_metrics = capture_system_metrics()
#                     start = time.time()

#                     audio_file = record_audio()

#                     duration = time.time() - start
#                     end_metrics = capture_system_metrics()

#                     cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#                     memory_used = end_metrics["memory"] - start_metrics["memory"]

#                     span.set_attribute("memory_used_mb", memory_used)
#                     span.set_attribute("cpu_used", cpu_used)

#                     stage_cpu_usage.labels(stage="audio_record").observe(cpu_used)
#                     stage_memory_usage.labels(stage="audio_record").observe(memory_used)

#                     audio_latency.observe(duration)
#                     audio_duration_seconds.observe(duration)

#                 # --------------------------------
#                 # STT
#                 # --------------------------------

#                 with tracer.start_as_current_span("speech_to_text") as span:

#                     start_metrics = capture_system_metrics()
#                     start = time.time()

#                     query = speech_to_text(audio_file)

#                     duration = time.time() - start
#                     end_metrics = capture_system_metrics()

#                     cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#                     memory_used = end_metrics["memory"] - start_metrics["memory"]

#                     span.set_attribute("memory_used_mb", memory_used)
#                     span.set_attribute("cpu_used", cpu_used)

#                     stage_cpu_usage.labels(stage="speech_to_text").observe(cpu_used)
#                     stage_memory_usage.labels(stage="speech_to_text").observe(memory_used)

#                     stt_latency.observe(duration)
#                     query_length.observe(len(query))
#                     stt_word_count.observe(len(query.split()))

#                     print("\nUser:", query)

#                 # --------------------------------
#                 # RAG RETRIEVAL
#                 # --------------------------------

#                 with tracer.start_as_current_span("rag_retrieval") as span:

#                     start_metrics = capture_system_metrics()
#                     start = time.time()

#                     result = await rag.aquery(query, mode="hybrid")

#                     duration = time.time() - start
#                     end_metrics = capture_system_metrics()

#                     cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#                     memory_used = end_metrics["memory"] - start_metrics["memory"]

#                     span.set_attribute("memory_used_mb", memory_used)
#                     span.set_attribute("cpu_used", cpu_used)

#                     stage_cpu_usage.labels(stage="rag_retrieval").observe(cpu_used)
#                     stage_memory_usage.labels(stage="rag_retrieval").observe(memory_used)

#                     retrieval_latency.observe(duration)

#                     if not result or "no documents found" in result.lower():
#                         rag_no_documents_found.inc()

#                 response_length.observe(len(result) if result else 0)
#                 print("\nAI:", result)

#                 # --------------------------------
#                 # TTS
#                 # --------------------------------

#                 with tracer.start_as_current_span("text_to_speech") as span:

#                     start_metrics = capture_system_metrics()
#                     start = time.time()

#                     speak(result)

#                     duration = time.time() - start
#                     end_metrics = capture_system_metrics()

#                     cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#                     memory_used = end_metrics["memory"] - start_metrics["memory"]

#                     span.set_attribute("memory_used_mb", memory_used)
#                     span.set_attribute("cpu_used", cpu_used)

#                     stage_cpu_usage.labels(stage="text_to_speech").observe(cpu_used)
#                     stage_memory_usage.labels(stage="text_to_speech").observe(memory_used)

#                     tts_latency.observe(duration)

#                 rag_requests_total.labels(status="success").inc()

#                 logger.info({
#                     "event": "request_completed",
#                     "correlation_id": correlation_id,
#                     "trace_id": trace_id
#                 })

#         except Exception as e:

#             span_ctx = get_current_span()
#             trace_id = format(span_ctx.get_span_context().trace_id, "032x")

#             rag_requests_total.labels(status="failed").inc()
#             rag_errors_total.labels(stage="pipeline").inc()

#             logger.error({
#                 "event": "request_failed",
#                 "correlation_id": correlation_id,
#                 "trace_id": trace_id,
#                 "error": str(e)
#             })

#             print("Error:", e)

#         finally:
#             rag_active_requests.dec()

#         # --------------------------------
#         # PIPELINE METRICS
#         # --------------------------------

#         total_latency = time.time() - pipeline_start
#         pipeline_latency.observe(total_latency)

#         print("Pipeline latency:", total_latency)

#         cpu_usage_percent.set(psutil.cpu_percent())
#         memory_usage_mb.set(psutil.virtual_memory().used / (1024 * 1024))
#         process_threads.set(psutil.Process().num_threads())


# # --------------------------------
# # ENTRY POINT
# # --------------------------------

# if __name__ == "__main__":
#     asyncio.run(main())

import asyncio
import time
import uuid
import os
import glob
import psutil

from voice.stt import record_audio, speech_to_text
from voice.tts import speak
from rag_pipeline import build_rag

from observability.logs_traces import setup_tracing, setup_logging
from observability.metrics import *

from observability.context import set_correlation_id
from opentelemetry.trace import get_current_span


# --------------------------------
# OBSERVABILITY
# --------------------------------

tracer = setup_tracing()
logger = setup_logging()

start_metrics_server()

logger.info("Metrics server started on port 8000")


# --------------------------------
# SYSTEM METRICS HELPER
# --------------------------------

def capture_system_metrics():
    process = psutil.Process()
    cpu_times = process.cpu_times()

    return {
        "cpu_time": cpu_times.user + cpu_times.system,
        "memory": process.memory_info().rss / (1024 * 1024)
    }


# --------------------------------
# CHECK IF DOCUMENT EXISTS
# --------------------------------

async def is_document_processed():
    rag_storage_path = os.getenv("WORKING_DIR", "./rag_storage")

    graph_file = os.path.join(rag_storage_path, "graph_chunk_entity_relation.graphml")
    if os.path.exists(graph_file) and os.path.getsize(graph_file) > 100:
        return True

    vdb_files = glob.glob(os.path.join(rag_storage_path, "vdb_*.json"))
    for vdb in vdb_files:
        if os.path.getsize(vdb) > 1000:
            return True

    chunks_file = os.path.join(rag_storage_path, "text_chunks.json")
    if os.path.exists(chunks_file) and os.path.getsize(chunks_file) > 100:
        return True

    return False


# --------------------------------
# MAIN PIPELINE
# --------------------------------

async def main():

    docs_exist = await is_document_processed()

    if not docs_exist:
        print("Processing document.pdf...")
        rag = await build_rag()
        await rag.process_document_complete(
            file_path="./data/document.pdf",
            output_dir="./output",
            parse_method="auto"
        )
    else:
        print("Using existing documents...")

    rag = await build_rag()

    while True:

        user_choice = input("\nPress Enter to speak or type 'sacchipo': ")

        if user_choice.lower() == "sacchipo":
            break

        correlation_id = str(uuid.uuid4())
        set_correlation_id(correlation_id)

        print(f"\nRequest ID: {correlation_id}")

        rag_active_requests.inc()
        pipeline_start = time.time()

        try:

            with tracer.start_as_current_span("rag_pipeline") as root_span:

                root_span.set_attribute("correlation_id", correlation_id)

                span_ctx = get_current_span()
                trace_id = format(span_ctx.get_span_context().trace_id, "032x")

                logger.info({
                    "event": "request_started",
                    "correlation_id": correlation_id,
                    "trace_id": trace_id
                })

                # --------------------------------
                # AUDIO RECORD
                # --------------------------------

                with tracer.start_as_current_span("audio_record") as span:

                    start_metrics = capture_system_metrics()
                    start = time.time()

                    audio_file = record_audio()

                    duration = time.time() - start
                    end_metrics = capture_system_metrics()

                    cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
                    memory_used = end_metrics["memory"] - start_metrics["memory"]

                    span.set_attribute("cpu_time_used", cpu_used)
                    span.set_attribute("memory_used_mb", memory_used)
                    span.set_attribute("duration_sec", duration)

                    stage_cpu_usage.labels(stage="audio_record").observe(cpu_used)
                    stage_memory_usage.labels(stage="audio_record").observe(memory_used)

                    audio_latency.observe(duration)
                    audio_duration_seconds.observe(duration)

                # --------------------------------
                # STT
                # --------------------------------

                with tracer.start_as_current_span("speech_to_text") as span:

                    start_metrics = capture_system_metrics()
                    start = time.time()

                    query = speech_to_text(audio_file)

                    duration = time.time() - start
                    end_metrics = capture_system_metrics()

                    cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
                    memory_used = end_metrics["memory"] - start_metrics["memory"]

                    span.set_attribute("cpu_time_used", cpu_used)
                    span.set_attribute("memory_used_mb", memory_used)
                    span.set_attribute("duration_sec", duration)

                    stage_cpu_usage.labels(stage="speech_to_text").observe(cpu_used)
                    stage_memory_usage.labels(stage="speech_to_text").observe(memory_used)

                    stt_latency.observe(duration)
                    query_length.observe(len(query))
                    stt_word_count.observe(len(query.split()))

                    print("\nUser:", query)

                # --------------------------------
                # RAG RETRIEVAL
                # --------------------------------

                with tracer.start_as_current_span("rag_retrieval") as span:

                    start_metrics = capture_system_metrics()
                    start = time.time()

                    result = await rag.aquery(query, mode="hybrid")

                    duration = time.time() - start
                    end_metrics = capture_system_metrics()

                    cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
                    memory_used = end_metrics["memory"] - start_metrics["memory"]

                    span.set_attribute("cpu_time_used", cpu_used)
                    span.set_attribute("memory_used_mb", memory_used)
                    span.set_attribute("duration_sec", duration)

                    stage_cpu_usage.labels(stage="rag_retrieval").observe(cpu_used)
                    stage_memory_usage.labels(stage="rag_retrieval").observe(memory_used)

                    retrieval_latency.observe(duration)

                    if not result or "no documents found" in result.lower():
                        rag_no_documents_found.inc()

                response_length.observe(len(result) if result else 0)
                print("\nAI:", result)

                # --------------------------------
                # TTS
                # --------------------------------

                with tracer.start_as_current_span("text_to_speech") as span:

                    start_metrics = capture_system_metrics()
                    start = time.time()

                    speak(result)

                    duration = time.time() - start
                    end_metrics = capture_system_metrics()

                    cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
                    memory_used = end_metrics["memory"] - start_metrics["memory"]

                    span.set_attribute("cpu_time_used", cpu_used)
                    span.set_attribute("memory_used_mb", memory_used)
                    span.set_attribute("duration_sec", duration)

                    stage_cpu_usage.labels(stage="text_to_speech").observe(cpu_used)
                    stage_memory_usage.labels(stage="text_to_speech").observe(memory_used)

                    tts_latency.observe(duration)

                # --------------------------------
                # 🔥 PIPELINE ANALYTICS (KEY ADDITION)
                # --------------------------------

                total_latency = time.time() - pipeline_start

                root_span.set_attribute("pipeline_latency_sec", total_latency)

                # Load classification
                if total_latency > 300:
                    root_span.set_attribute("pipeline_load", "HIGH")
                elif total_latency > 120:
                    root_span.set_attribute("pipeline_load", "MEDIUM")
                else:
                    root_span.set_attribute("pipeline_load", "LOW")

                rag_requests_total.labels(status="success").inc()

                logger.info({
                    "event": "request_completed",
                    "correlation_id": correlation_id,
                    "trace_id": trace_id,
                    "pipeline_latency": total_latency
                })

        except Exception as e:

            span_ctx = get_current_span()
            trace_id = format(span_ctx.get_span_context().trace_id, "032x")

            rag_requests_total.labels(status="failed").inc()
            rag_errors_total.labels(stage="pipeline").inc()

            logger.error({
                "event": "request_failed",
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "error": str(e)
            })

            print("Error:", e)

        finally:
            rag_active_requests.dec()

        # --------------------------------
        # METRICS
        # --------------------------------

        total_latency = time.time() - pipeline_start
        pipeline_latency.observe(total_latency)

        print("Pipeline latency:", total_latency)

        cpu_usage_percent.set(psutil.cpu_percent(interval=0.5))
        memory_usage_mb.set(psutil.virtual_memory().used / (1024 * 1024))
        process_threads.set(psutil.Process().num_threads())


# --------------------------------
# ENTRY POINT
# --------------------------------

if __name__ == "__main__":
    asyncio.run(main())