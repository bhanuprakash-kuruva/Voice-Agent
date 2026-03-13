import asyncio
import time
import numpy as np

from openai import OpenAI
from raganything import RAGAnything
from raganything.config import RAGAnythingConfig
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
    tokens_per_second
)


# --------------------------------
# OBSERVABILITY
# --------------------------------

tracer = setup_tracing()
logger = setup_logging()


# --------------------------------
# OLLAMA CLIENT
# --------------------------------

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama"
)


# --------------------------------
# LLM FUNCTION
# --------------------------------

async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):

    with tracer.start_as_current_span("llm_generation"):

        start = time.time()

        llm_requests_total.inc()

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        for msg in history_messages:
            messages.append(msg)

        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model="qwen2:7b",
            messages=messages
        )

        answer = response.choices[0].message.content

        llm_latency.observe(time.time() - start)

        # ---------------------------
        # TOKEN METRICS
        # ---------------------------

        prompt_token_count = len(prompt.split())
        completion_token_count = len(answer.split())

        prompt_tokens.observe(prompt_token_count)
        completion_tokens.observe(completion_token_count)

        total = prompt_token_count + completion_token_count
        total_tokens.observe(total)

        generation_time = time.time() - start

        if generation_time > 0:
            tokens_per_second.observe(completion_token_count / generation_time)

        logger.info({
            "event": "llm_response",
            "prompt_tokens": prompt_token_count,
            "completion_tokens": completion_token_count
        })

        return answer


# --------------------------------
# EMBEDDING FUNCTION
# --------------------------------

async def embed_texts(texts):

    with tracer.start_as_current_span("embedding_generation"):

        start = time.time()

        embedding_requests_total.inc()

        response = client.embeddings.create(
            model="nomic-embed-text",
            input=texts
        )

        embeddings = [item.embedding for item in response.data]

        embedding_latency.observe(time.time() - start)

        return np.array(embeddings, dtype=np.float32)


# --------------------------------
# BUILD RAG
# --------------------------------

async def build_rag():

    logger.info("Initializing RAG pipeline")

    config = RAGAnythingConfig(
        working_dir="./rag_storage",
        parser="pymupdf",
        parse_method="auto",
        enable_image_processing=False,
        enable_table_processing=False,
        enable_equation_processing=False
    )

    embedding_func = EmbeddingFunc(
        embedding_dim=768,
        max_token_size=8192,
        func=embed_texts
    )

    rag = RAGAnything(
        config=config,
        llm_model_func=llm_func,
        embedding_func=embedding_func
    )

    logger.info("RAG pipeline initialized")

    return rag


# --------------------------------
# TEST PIPELINE
# --------------------------------

async def main():

    rag = await build_rag()

    print("\nProcessing document...\n")

    await rag.process_document_complete(
        file_path="./data/document.pdf",
        output_dir="./output",
        parse_method="auto"
    )

    print("\nDocument processed successfully.\n")

    result = await rag.aquery(
        "What is this document about?",
        mode="hybrid"
    )

    print("\n=============================")
    print("ANSWER:")
    print("=============================\n")

    print(result)


if __name__ == "__main__":
    asyncio.run(main())