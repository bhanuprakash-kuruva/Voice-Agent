# import asyncio
# import time
# import os
# import numpy as np
# import psutil

# from openai import OpenAI
# from raganything import RAGAnything
# from raganything.config import RAGAnythingConfig
# from lightrag import LightRAG
# from lightrag.utils import EmbeddingFunc

# from observability.logs_traces import setup_tracing, setup_logging

# from observability.metrics import (
#     embedding_requests_total,
#     embedding_latency,
#     llm_requests_total,
#     llm_latency,
#     prompt_tokens,
#     completion_tokens,
#     total_tokens,
#     tokens_per_second,
#     # 🔥 NEW METRICS
#     stage_cpu_usage,
#     stage_memory_usage,
#     llm_memory_usage,
#     llm_cpu_usage
# )

# import httpx
# from opentelemetry.propagate import inject
# from observability.context import get_correlation_id
# from opentelemetry.trace import get_current_span


# # --------------------------------
# # OBSERVABILITY
# # --------------------------------

# tracer = setup_tracing()
# logger = setup_logging()

# # --------------------------------
# # SYSTEM METRICS HELPER (🔥 CRITICAL)
# # --------------------------------

# def capture_system_metrics():
#     process = psutil.Process()
#     cpu_times = process.cpu_times()
    
#     return {
#         "cpu_time": cpu_times.user + cpu_times.system,
#         "memory": process.memory_info().rss / (1024 * 1024)
#     }


# # --------------------------------
# # OLLAMA CLIENT (USED ONLY FOR EMBEDDINGS)
# # --------------------------------

# client = OpenAI(
#     base_url="http://localhost:11434/v1",
#     api_key="ollama"
# )


# # --------------------------------
# # LLM FUNCTION
# # --------------------------------

# async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):

#     with tracer.start_as_current_span("llm_generation") as span:

#         correlation_id = get_correlation_id()
#         span.set_attribute("correlation_id", correlation_id)

#         current_span = get_current_span()
#         trace_id = format(current_span.get_span_context().trace_id, "032x")

#         # 🔥 START RESOURCE CAPTURE
#         start_metrics = capture_system_metrics()

#         start = time.time()
#         llm_requests_total.inc()

#         messages = []

#         if system_prompt:
#             messages.append({"role": "system", "content": system_prompt})

#         for msg in history_messages:
#             messages.append(msg)

#         messages.append({"role": "user", "content": prompt})

#         headers = {}
#         inject(headers)
#         headers["x-correlation-id"] = correlation_id

#         payload = {
#             "model": os.getenv("LLM_MODEL", "phi3"),
#             "messages": messages,
#             "temperature": 0.3,
#             "max_tokens": 256
#         }

#         logger.info({
#             "event": "outgoing_llm_request",
#             "correlation_id": correlation_id,
#             "trace_id": trace_id
#         })

#         try:
#             async with httpx.AsyncClient(timeout=1200.0) as client_http:
#                 response = await client_http.post(
#                     "http://localhost:11434/v1/chat/completions",
#                     json=payload,
#                     headers=headers
#                 )

#             data = response.json()

#             if not data or "choices" not in data:
#                 raise ValueError("Invalid LLM response")

#             answer = data["choices"][0]["message"]["content"]

#         except Exception as e:
#             logger.error({
#                 "event": "llm_request_failed",
#                 "correlation_id": correlation_id,
#                 "trace_id": trace_id,
#                 "error": str(e)
#             })
#             return "LLM request failed."

#         # 🔥 END RESOURCE CAPTURE
#         end_metrics = capture_system_metrics()

#         cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#         memory_used = end_metrics["memory"] - start_metrics["memory"]

#         # --------------------------------
#         # 🔥 TRACE ATTRIBUTES (MOST IMPORTANT)
#         # --------------------------------

#         span.set_attribute("cpu_start", start_metrics["cpu"])
#         span.set_attribute("cpu_end", end_metrics["cpu"])
#         span.set_attribute("memory_start_mb", start_metrics["memory"])
#         span.set_attribute("memory_end_mb", end_metrics["memory"])
#         span.set_attribute("memory_used_mb", memory_used)

#         # --------------------------------
#         # 🔥 METRICS (VictoriaMetrics)
#         # --------------------------------

#         llm_latency.observe(time.time() - start)

#         stage_cpu_usage.labels(stage="llm_generation").observe(cpu_used)
#         stage_memory_usage.labels(stage="llm_generation").observe(memory_used)

#         llm_memory_usage.observe(memory_used)
#         llm_cpu_usage.observe(cpu_used)

#         # tokens
#         prompt_token_count = len(prompt.split())
#         completion_token_count = len(answer.split()) if answer else 0

#         prompt_tokens.observe(prompt_token_count)
#         completion_tokens.observe(completion_token_count)
#         total_tokens.observe(prompt_token_count + completion_token_count)

#         generation_time = time.time() - start

#         if generation_time > 0:
#             tokens_per_second.observe(
#                 completion_token_count / generation_time if completion_token_count > 0 else 0
#             )

#         logger.info({
#             "event": "llm_response",
#             "correlation_id": correlation_id,
#             "trace_id": trace_id,
#             "memory_used_mb": memory_used,
#             "cpu_used": cpu_used
#         })

#         return answer


# # --------------------------------
# # EMBEDDING FUNCTION
# # --------------------------------

# async def embed_texts(texts):

#     with tracer.start_as_current_span("embedding_generation") as span:

#         start_metrics = capture_system_metrics()

#         start = time.time()
#         embedding_requests_total.inc()

#         response = client.embeddings.create(
#             model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
#             input=texts
#         )

#         embeddings = [item.embedding for item in response.data]

#         embedding_latency.observe(time.time() - start)

#         end_metrics = capture_system_metrics()

#         cpu_used = end_metrics["cpu"] - start_metrics["cpu"]
#         memory_used = end_metrics["memory"] - start_metrics["memory"]

#         # 🔥 TRACE ATTRIBUTES
#         span.set_attribute("memory_used_mb", memory_used)
#         span.set_attribute("cpu_used", cpu_used)

#         # 🔥 METRICS
#         stage_cpu_usage.labels(stage="embedding").observe(cpu_used)
#         stage_memory_usage.labels(stage="embedding").observe(memory_used)

#         return np.array(embeddings, dtype=np.float32)


# # --------------------------------
# # BUILD RAG
# # --------------------------------

# async def build_rag():

#     logger.info("Initializing RAG pipeline")

#     working_dir = os.getenv("WORKING_DIR", "./rag_storage")

#     embedding_func = EmbeddingFunc(
#         embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
#         max_token_size=8192,
#         func=embed_texts
#     )

#     lightrag_instance = LightRAG(
#         working_dir=working_dir,
#         llm_model_func=llm_func,
#         embedding_func=embedding_func
#     )

#     await lightrag_instance.initialize_storages()

#     config = RAGAnythingConfig(
#         working_dir=working_dir
#     )

#     rag = RAGAnything(
#         config=config,
#         lightrag=lightrag_instance
#     )

#     logger.info("RAG pipeline initialized")

#     return rag


# # --------------------------------
# # SIMPLE QUERY LOOP
# # --------------------------------

# async def main():

#     rag = await build_rag()

#     print("\nRAG ready. Upload documents via WebUI.\n")

#     while True:

#         query = input("Ask something (type 'exit'): ")

#         if query.lower() == "exit":
#             break

#         correlation_id = get_correlation_id()

#         result = await rag.aquery(
#             query,
#             mode="hybrid",
#             correlation_id=correlation_id
#         )

#         print("\n=============================")
#         print("ANSWER:")
#         print("=============================\n")
#         print(result)


# # --------------------------------
# # ENTRY POINT
# # --------------------------------

# if __name__ == "__main__":
#     asyncio.run(main())

import asyncio
import time
import os
import numpy as np
import psutil

from openai import OpenAI
from raganything import RAGAnything
from raganything.config import RAGAnythingConfig
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc

from observability.logs_traces import setup_tracing, setup_logging

from observability.metrics import (
    embedding_requests_total,
    embedding_latency,
    llm_requests_total,
    llm_latency,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    tokens_per_second,
    stage_cpu_usage,
    stage_memory_usage,
    llm_memory_usage,
    llm_cpu_usage
)

import httpx
from opentelemetry.propagate import inject
from observability.context import get_correlation_id
from opentelemetry.trace import get_current_span, SpanKind


# --------------------------------
# OBSERVABILITY
# --------------------------------

tracer = setup_tracing()
logger = setup_logging()


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
# OLLAMA CLIENT
# --------------------------------

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)


# --------------------------------
# LLM FUNCTION (FINAL VERSION)
# --------------------------------

async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):

    with tracer.start_as_current_span("llm_generation") as span:

        span.set_attribute("component", "llm")

        correlation_id = get_correlation_id()
        span.set_attribute("correlation_id", correlation_id)

        current_span = get_current_span()
        trace_id = format(current_span.get_span_context().trace_id, "032x")

        start_metrics = capture_system_metrics()
        start = time.time()

        llm_requests_total.inc()

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        headers = {}
        inject(headers)
        headers["x-correlation-id"] = correlation_id

        payload = {
            "model": os.getenv("LLM_MODEL", "phi3"),
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 256
        }

        logger.info({
            "event": "outgoing_llm_request",
            "correlation_id": correlation_id,
            "trace_id": trace_id
        })

        try:
            # 🔥 CLIENT SPAN (THIS ENABLES JAEGER GRAPH)
            with tracer.start_as_current_span("ollama_call", kind=SpanKind.CLIENT) as client_span:

                client_span.set_attribute("peer.service", "ollama")
                client_span.set_attribute("http.method", "POST")
                client_span.set_attribute("http.url", "http://localhost:11434/v1/chat/completions")

                async with httpx.AsyncClient(timeout=1200.0) as client_http:
                    response = await client_http.post(
                        "http://localhost:11434/v1/chat/completions",
                        json=payload,
                        headers=headers
                    )

            data = response.json()

            if not data or "choices" not in data:
                raise ValueError("Invalid LLM response")

            answer = data["choices"][0]["message"]["content"]

        except Exception as e:
            logger.error({
                "event": "llm_request_failed",
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "error": str(e)
            })
            return "LLM request failed."

        # --------------------------------
        # METRICS
        # --------------------------------

        end_metrics = capture_system_metrics()

        cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
        memory_used = end_metrics["memory"] - start_metrics["memory"]
        duration = time.time() - start

        # --------------------------------
        # TRACE ANALYTICS
        # --------------------------------

        span.set_attribute("cpu_time_used", cpu_used)
        span.set_attribute("memory_used_mb", memory_used)
        span.set_attribute("llm_duration_sec", duration)

        efficiency = duration / cpu_used if cpu_used > 0 else 0
        span.set_attribute("llm_efficiency", efficiency)

        if duration > 120:
            span.set_attribute("load_level", "HIGH")
        elif duration > 60:
            span.set_attribute("load_level", "MEDIUM")
        else:
            span.set_attribute("load_level", "LOW")

        if cpu_used < 2 and duration > 60:
            span.set_attribute("bottleneck", "IO_BOUND")
        elif cpu_used > 5:
            span.set_attribute("bottleneck", "CPU_BOUND")
        else:
            span.set_attribute("bottleneck", "NORMAL")

        # --------------------------------
        # PROMETHEUS METRICS
        # --------------------------------

        llm_latency.observe(duration)

        stage_cpu_usage.labels(stage="llm_generation").observe(cpu_used)
        stage_memory_usage.labels(stage="llm_generation").observe(memory_used)

        llm_memory_usage.observe(memory_used)
        llm_cpu_usage.observe(cpu_used)

        prompt_token_count = len(prompt.split())
        completion_token_count = len(answer.split()) if answer else 0

        prompt_tokens.observe(prompt_token_count)
        completion_tokens.observe(completion_token_count)
        total_tokens.observe(prompt_token_count + completion_token_count)

        if duration > 0:
            tokens_per_second.observe(
                completion_token_count / duration if completion_token_count > 0 else 0
            )

        logger.info({
            "event": "llm_response",
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "cpu_time_used": cpu_used,
            "duration": duration,
            "bottleneck": span.attributes.get("bottleneck")
        })

        return answer


# --------------------------------
# EMBEDDING FUNCTION
# --------------------------------

async def embed_texts(texts):

    with tracer.start_as_current_span("embedding_generation") as span:

        span.set_attribute("component", "embedding")

        start_metrics = capture_system_metrics()
        start = time.time()

        embedding_requests_total.inc()

        response = client.embeddings.create(
            model=os.getenv("EMBEDDING_MODEL", "nomic-embed-text"),
            input=texts
        )

        embeddings = [item.embedding for item in response.data]

        duration = time.time() - start

        end_metrics = capture_system_metrics()

        cpu_used = end_metrics["cpu_time"] - start_metrics["cpu_time"]
        memory_used = end_metrics["memory"] - start_metrics["memory"]

        span.set_attribute("cpu_time_used", cpu_used)
        span.set_attribute("memory_used_mb", memory_used)
        span.set_attribute("embedding_duration_sec", duration)

        stage_cpu_usage.labels(stage="embedding").observe(cpu_used)
        stage_memory_usage.labels(stage="embedding").observe(memory_used)

        embedding_latency.observe(duration)

        return np.array(embeddings, dtype=np.float32)


# --------------------------------
# BUILD RAG
# --------------------------------

async def build_rag():

    logger.info("Initializing RAG pipeline")

    working_dir = os.getenv("WORKING_DIR", "./rag_storage")

    embedding_func = EmbeddingFunc(
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
        max_token_size=8192,
        func=embed_texts
    )

    lightrag_instance = LightRAG(
        working_dir=working_dir,
        llm_model_func=llm_func,
        embedding_func=embedding_func
    )

    await lightrag_instance.initialize_storages()

    config = RAGAnythingConfig(
        working_dir=working_dir
    )

    rag = RAGAnything(
        config=config,
        lightrag=lightrag_instance
    )

    logger.info("RAG pipeline initialized")

    return rag


# --------------------------------
# SIMPLE QUERY LOOP
# --------------------------------

async def main():

    rag = await build_rag()

    print("\nRAG ready. Upload documents via WebUI.\n")

    while True:

        query = input("Ask something (type 'exit'): ")

        if query.lower() == "exit":
            break

        correlation_id = get_correlation_id()

        result = await rag.aquery(
            query,
            mode="hybrid",
            correlation_id=correlation_id
        )

        print("\n=============================")
        print("ANSWER:")
        print("=============================\n")
        print(result)


# --------------------------------
# ENTRY POINT
# --------------------------------

if __name__ == "__main__":
    asyncio.run(main())