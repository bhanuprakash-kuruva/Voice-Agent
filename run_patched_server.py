#!/usr/bin/env python3
"""
Launcher for LightRAG server with automatic patching
"""
import asyncio
import sys
import os
import httpx

# Patch before importing anything else
import lightrag.llm.ollama as ollama_module

async def patched_ollama_embed(
    texts: list[str],
    embed_model: str = "nomic-embed-text",
    host: str = "http://localhost:11434",
    timeout: float = 600.0,
    **kwargs
) -> list[list[float]]:
    """Patched version with truncation - no external dependencies"""
    MAX_CHARS = 10000
    MAX_BATCH_SIZE = 10
    
    # Simple truncation function
    def simple_truncate(text, max_chars):
        if len(text) <= max_chars:
            return text
        keep_start = int(max_chars * 0.7)
        keep_end = int(max_chars * 0.3)
        return text[:keep_start] + f"\n\n...[TRUNCATED: {len(text) - max_chars} chars]...\n\n" + text[-keep_end:]
    
    # Truncate each text
    truncated_texts = []
    for i, text in enumerate(texts):
        if len(text) > MAX_CHARS:
            truncated = simple_truncate(text, MAX_CHARS)
            truncated_texts.append(truncated)
            print(f"⚠️ Truncated text {i}: {len(text)} -> {len(truncated)} chars")
        else:
            truncated_texts.append(text)
    
    # Process in batches
    all_embeddings = []
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i in range(0, len(truncated_texts), MAX_BATCH_SIZE):
            batch = truncated_texts[i:i + MAX_BATCH_SIZE]
            
            payload = {
                "model": embed_model,
                "input": batch,
                "options": {
                    "num_ctx": 4096
                }
            }
            
            try:
                response = await client.post(f"{host}/v1/embeddings", json=payload)
                response.raise_for_status()
                data = response.json()
                
                batch_embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(batch_embeddings)
                
                if i + MAX_BATCH_SIZE < len(truncated_texts):
                    await asyncio.sleep(0.05)
                    
            except Exception as e:
                print(f"Error in embedding batch {i}: {e}")
                raise
    
    return all_embeddings

# Apply patch
ollama_module.ollama_embed = patched_ollama_embed
print("✓ Patch applied to lightrag.llm.ollama.ollama_embed")

# Now import and run the server
from lightrag.api.lightrag_server import main

if __name__ == "__main__":
    # Clear any existing sys.argv and set our own
    sys.argv = ["lightrag-server", "--timeout", "60000"]
    main()