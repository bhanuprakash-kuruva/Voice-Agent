import asyncio
import numpy as np
import ollama

from raganything import RAGAnything, RAGAnythingConfig
from lightrag.utils import EmbeddingFunc


# -----------------------------
# OLLAMA LLM FUNCTION
# -----------------------------

async def llm_func(prompt, system_prompt=None, history_messages=[], **kwargs):

    messages = []

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    for msg in history_messages:
        messages.append(msg)

    messages.append({"role": "user", "content": prompt})

    response = ollama.chat(
        model="qwen2:7b",
        messages=messages
    )

    return response["message"]["content"]


# -----------------------------
# OLLAMA EMBEDDING FUNCTION
# -----------------------------

async def embed_texts(texts):

    embeddings = []

    for text in texts:

        response = ollama.embeddings(
            model="nomic-embed-text",
            prompt=text
        )

        embeddings.append(response["embedding"])

    return np.array(embeddings)


# -----------------------------
# MAIN PIPELINE
# -----------------------------

async def main():

    config = RAGAnythingConfig(

        working_dir="./rag_storage",

        parser="pymupdf",

        parse_method="auto",

        enable_image_processing=False,

        enable_table_processing=False,

        enable_equation_processing=False,
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


    # ---------------------------------
    # DOCUMENT INGESTION
    # ---------------------------------

    await rag.process_document_complete(
        file_path="./data/document.pdf",
        output_dir="./output",
        parse_method="auto"
    )


    # ---------------------------------
    # QUERY
    # ---------------------------------

    result = await rag.aquery(
        "What is this document about?",
        mode="hybrid"
    )


    print("\n=============================")
    print("ANSWER:")
    print("=============================\n")

    print(result)


# -----------------------------
# RUN PIPELINE
# -----------------------------

if __name__ == "__main__":
    asyncio.run(main())
