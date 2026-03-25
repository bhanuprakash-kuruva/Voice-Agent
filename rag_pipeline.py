import asyncio
import time
import os
import numpy as np
import psutil
import hashlib
import json
import pickle
from typing import List, Dict, Any, Optional, Tuple
from functools import lru_cache
from datetime import datetime

from openai import OpenAI
from raganything import RAGAnything
from raganything.config import RAGAnythingConfig
from lightrag import LightRAG
from lightrag.utils import EmbeddingFunc

from observability.logs_traces import setup_tracing, setup_logging, create_span, log_stage_boundary
from observability.metrics import (
    embedding_requests_total,
    embedding_latency,
    embedding_batch_size,
    llm_requests_total,
    llm_latency,
    llm_cache_hits,
    llm_cache_misses,
    prompt_tokens,
    completion_tokens,
    total_tokens,
    tokens_per_second,
    stage_cpu_usage,
    stage_memory_usage,
    llm_memory_usage,
    llm_cpu_usage,
    documents_retrieved,
    retrieval_similarity_score,
    rag_errors_total,
    observe_latency,
    count_errors
)
from observability.context import get_correlation_id, get_user_id, get_session_id

import httpx
from opentelemetry.propagate import inject
from opentelemetry.trace import get_current_span, SpanKind
from opentelemetry import trace

# --------------------------------
# OBSERVABILITY
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

LLM_MODEL = os.getenv("LLM_MODEL", "phi3")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "768"))
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
WORKING_DIR = os.getenv("WORKING_DIR", "./rag_storage")
CACHE_ENABLED = os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true"
CACHE_TTL = int(os.getenv("LLM_CACHE_TTL", "3600"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))  # 2 minute timeout default
RAG_TIMEOUT = int(os.getenv("RAG_TIMEOUT", "180"))  # 3 minute timeout default

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
# LLM CACHE
# --------------------------------

class LLMCache:
    """In-memory cache for LLM responses with TTL"""
    
    def __init__(self, ttl_seconds: int = 3600, max_size: int = 1000):
        self._cache = {}
        self._ttl = ttl_seconds
        self._max_size = max_size
    
    def _generate_key(self, prompt: str, system_prompt: Optional[str], 
                      history_messages: List[Dict]) -> str:
        """Generate cache key from request parameters"""
        content = f"{system_prompt or ''}|{json.dumps(history_messages)}|{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get(self, prompt: str, system_prompt: Optional[str], 
            history_messages: List[Dict]) -> Optional[str]:
        """Get cached response if available and not expired"""
        if not CACHE_ENABLED:
            return None
        
        key = self._generate_key(prompt, system_prompt, history_messages)
        
        if key in self._cache:
            entry = self._cache[key]
            if time.time() - entry['timestamp'] < self._ttl:
                llm_cache_hits.inc()
                logger.debug(f"LLM cache hit for key: {key[:8]}")
                return entry['response']
            else:
                del self._cache[key]
        
        llm_cache_misses.inc()
        return None
    
    def set(self, prompt: str, system_prompt: Optional[str], 
            history_messages: List[Dict], response: str) -> None:
        """Cache the response"""
        if not CACHE_ENABLED:
            return
        
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache.keys(), 
                           key=lambda k: self._cache[k]['timestamp'])
            del self._cache[oldest_key]
        
        key = self._generate_key(prompt, system_prompt, history_messages)
        self._cache[key] = {
            'response': response,
            'timestamp': time.time()
        }
        logger.debug(f"Cached LLM response for key: {key[:8]}")
    
    def clear(self) -> None:
        """Clear the cache"""
        self._cache.clear()
        logger.info("LLM cache cleared")


_llm_cache = LLMCache(ttl_seconds=CACHE_TTL)


# --------------------------------
# OLLAMA CLIENT
# --------------------------------

class OllamaClient:
    """Enhanced Ollama client with retry and error handling"""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL, timeout: float = 1200.0):
        self.base_url = base_url
        self.timeout = timeout
        self._client = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client
    
    async def chat_completion(self, messages: List[Dict], model: str, 
                              temperature: float = 0.3, 
                              max_tokens: int = 256,
                              headers: Optional[Dict] = None) -> Dict:
        """Send chat completion request to Ollama"""
        client = await self._get_client()
        
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }
        
        response = await client.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            headers=headers or {}
        )
        
        response.raise_for_status()
        return response.json()
    
    async def embeddings(self, texts: List[str], model: str) -> List[List[float]]:
        """Get embeddings from Ollama"""
        client = await self._get_client()
        
        if isinstance(texts, str):
            texts = [texts]
        
        payload = {
            "model": model,
            "input": texts
        }
        
        response = await client.post(
            f"{self.base_url}/v1/embeddings",
            json=payload
        )
        
        response.raise_for_status()
        data = response.json()
        
        return [item["embedding"] for item in data["data"]]
    
    async def close(self):
        """Close HTTP client"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


_ollama_client = OllamaClient()


# --------------------------------
# LLM FUNCTION WITH TIMEOUT
# --------------------------------

async def llm_func(
    prompt: str, 
    system_prompt: Optional[str] = None, 
    history_messages: List[Dict] = None,
    temperature: float = 0.3,
    max_tokens: int = 256,
    **kwargs
) -> str:
    """
    Enhanced LLM function with caching, retries, timeout, and comprehensive metrics
    """
    history_messages = history_messages or []
    correlation_id = get_correlation_id()
    
    # Check cache first
    cached_response = _llm_cache.get(prompt, system_prompt, history_messages)
    if cached_response:
        return cached_response
    
    with tracer.start_as_current_span("llm_generation") as span:
        
        span.set_attribute("component", "llm")
        span.set_attribute("llm.model", LLM_MODEL)
        span.set_attribute("llm.temperature", temperature)
        span.set_attribute("llm.max_tokens", max_tokens)
        span.set_attribute("correlation_id", correlation_id)
        
        user_id = get_user_id()
        if user_id:
            span.set_attribute("user_id", user_id)
        
        current_span = get_current_span()
        trace_id = format(current_span.get_span_context().trace_id, "032x")
        
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        llm_requests_total.labels(model=LLM_MODEL, status="pending").inc()
        
        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        for msg in history_messages:
            messages.append(msg)
        
        messages.append({"role": "user", "content": prompt})
        
        # Prepare headers with trace context
        headers = {}
        inject(headers)
        headers["x-correlation-id"] = correlation_id
        headers["x-user-id"] = user_id or "anonymous"
        
        logger.info({
            "event": "outgoing_llm_request",
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "model": LLM_MODEL,
            "prompt_length": len(prompt),
            "messages_count": len(messages)
        })
        
        answer = None
        error = None
        
        try:
            # ADD TIMEOUT PROTECTION
            with tracer.start_as_current_span("ollama_call", kind=SpanKind.CLIENT) as client_span:
                client_span.set_attribute("peer.service", "ollama")
                client_span.set_attribute("http.method", "POST")
                client_span.set_attribute("llm.model", LLM_MODEL)
                
                response = await asyncio.wait_for(
                    _ollama_client.chat_completion(
                        messages=messages,
                        model=LLM_MODEL,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        headers=headers
                    ),
                    timeout=LLM_TIMEOUT
                )
                
                client_span.set_attribute("http.status_code", 200)
            
            if response and "choices" in response and response["choices"]:
                answer = response["choices"][0]["message"]["content"]
            else:
                raise ValueError("Invalid LLM response structure")
            
            llm_requests_total.labels(model=LLM_MODEL, status="success").inc()
            
        except asyncio.TimeoutError:
            error = "LLM timeout"
            llm_requests_total.labels(model=LLM_MODEL, status="timeout").inc()
            rag_errors_total.labels(stage="llm", error_type="TimeoutError").inc()
            
            logger.error({
                "event": "llm_request_timeout",
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "timeout": LLM_TIMEOUT,
                "message": f"LLM request timed out after {LLM_TIMEOUT}s"
            })
            
            return f"I'm sorry, the request timed out after {LLM_TIMEOUT} seconds. Please try again."
            
        except Exception as e:
            error = e
            llm_requests_total.labels(model=LLM_MODEL, status="failed").inc()
            rag_errors_total.labels(stage="llm", error_type=type(e).__name__).inc()
            
            logger.error({
                "event": "llm_request_failed",
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            
            return f"LLM request failed: {str(e)}"
        
        # Calculate metrics
        end_metrics = capture_system_metrics()
        metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
        duration = time.time() - start_time
        
        prompt_token_count = len(prompt.split()) + sum(len(msg.get("content", "").split()) for msg in messages)
        completion_token_count = len(answer.split()) if answer else 0
        total_token_count = prompt_token_count + completion_token_count
        generation_speed = completion_token_count / duration if duration > 0 and completion_token_count > 0 else 0
        
        span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
        span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
        span.set_attribute("llm_duration_sec", duration)
        span.set_attribute("prompt_tokens", prompt_token_count)
        span.set_attribute("completion_tokens", completion_token_count)
        span.set_attribute("total_tokens", total_token_count)
        span.set_attribute("tokens_per_second", generation_speed)
        
        llm_latency.observe(duration)
        stage_cpu_usage.labels(stage="llm_generation").observe(metrics_delta["cpu_used"])
        stage_memory_usage.labels(stage="llm_generation").observe(metrics_delta["memory_used"])
        llm_memory_usage.observe(metrics_delta["memory_used"])
        llm_cpu_usage.observe(metrics_delta["cpu_used"])
        prompt_tokens.observe(prompt_token_count)
        completion_tokens.observe(completion_token_count)
        total_tokens.observe(total_token_count)
        
        if generation_speed > 0:
            tokens_per_second.observe(generation_speed)
        
        logger.info({
            "event": "llm_response",
            "correlation_id": correlation_id,
            "trace_id": trace_id,
            "cpu_time_used": metrics_delta["cpu_used"],
            "memory_used_mb": metrics_delta["memory_used"],
            "duration": duration,
            "prompt_tokens": prompt_token_count,
            "completion_tokens": completion_token_count,
            "tokens_per_second": generation_speed
        })
        
        _llm_cache.set(prompt, system_prompt, history_messages, answer)
        
        return answer


# --------------------------------
# EMBEDDING FUNCTION
# --------------------------------

async def embed_texts(texts: List[str]) -> np.ndarray:
    """Enhanced embedding function with batching and metrics"""
    if not texts:
        return np.array([], dtype=np.float32)
    
    if isinstance(texts, str):
        texts = [texts]
    
    batch_size = len(texts)
    correlation_id = get_correlation_id()
    
    with tracer.start_as_current_span("embedding_generation") as span:
        
        span.set_attribute("component", "embedding")
        span.set_attribute("embedding.model", EMBEDDING_MODEL)
        span.set_attribute("embedding.batch_size", batch_size)
        span.set_attribute("correlation_id", correlation_id)
        
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        embedding_requests_total.labels(
            model=EMBEDDING_MODEL,
            batch_size_range="small" if batch_size <= 10 else "medium" if batch_size <= 50 else "large"
        ).inc()
        
        embedding_batch_size.observe(batch_size)
        
        try:
            embeddings = await _ollama_client.embeddings(texts, EMBEDDING_MODEL)
            
            duration = time.time() - start_time
            end_metrics = capture_system_metrics()
            metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
            span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
            span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
            span.set_attribute("embedding_duration_sec", duration)
            span.set_attribute("embedding_count", len(embeddings))
            span.set_attribute("embedding_dim", len(embeddings[0]) if embeddings else 0)
            
            stage_cpu_usage.labels(stage="embedding").observe(metrics_delta["cpu_used"])
            stage_memory_usage.labels(stage="embedding").observe(metrics_delta["memory_used"])
            embedding_latency.observe(duration)
            
            logger.info({
                "event": "embeddings_generated",
                "batch_size": batch_size,
                "duration": duration,
                "embedding_dim": len(embeddings[0]) if embeddings else 0,
                "cpu_used": metrics_delta["cpu_used"],
                "memory_used_mb": metrics_delta["memory_used"],
                "correlation_id": correlation_id
            })
            
            return np.array(embeddings, dtype=np.float32)
            
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            
            rag_errors_total.labels(stage="embedding", error_type=type(e).__name__).inc()
            
            logger.error({
                "event": "embedding_failed",
                "batch_size": batch_size,
                "error": str(e),
                "error_type": type(e).__name__,
                "correlation_id": correlation_id
            })
            
            raise


# --------------------------------
# RAG QUERY WITH TIMEOUT
# --------------------------------

async def query_rag(
    rag: RAGAnything,
    query: str,
    mode: str = "hybrid",
    top_k: int = 5,
    similarity_threshold: float = 0.5
) -> Tuple[str, Dict[str, Any]]:
    """
    Execute RAG query with timeout protection
    """
    correlation_id = get_correlation_id()
    log_stage_boundary("rag_retrieval", "enter", correlation_id)
    
    with tracer.start_as_current_span("rag_query") as span:
        
        span.set_attribute("query.length", len(query))
        span.set_attribute("query.mode", mode)
        span.set_attribute("query.top_k", top_k)
        span.set_attribute("correlation_id", correlation_id)
        
        start_metrics = capture_system_metrics()
        start_time = time.time()
        
        try:
            # ADD TIMEOUT PROTECTION
            result = await asyncio.wait_for(
                rag.aquery(query, mode=mode, top_k=top_k),
                timeout=RAG_TIMEOUT
            )
            
            duration = time.time() - start_time
            end_metrics = capture_system_metrics()
            metrics_delta = calculate_metrics_delta(start_metrics, end_metrics)
            
            metadata = {
                "retrieved_docs": getattr(result, 'retrieved_docs', 0),
                "similarity_scores": getattr(result, 'similarity_scores', []),
                "source_documents": getattr(result, 'source_documents', [])
            }
            
            if metadata["retrieved_docs"] > 0:
                documents_retrieved.observe(metadata["retrieved_docs"])
            
            if metadata["similarity_scores"]:
                for score in metadata["similarity_scores"]:
                    retrieval_similarity_score.observe(score)
            
            span.set_attribute("cpu_time_used", metrics_delta["cpu_used"])
            span.set_attribute("memory_used_mb", metrics_delta["memory_used"])
            span.set_attribute("duration_sec", duration)
            span.set_attribute("retrieved_docs", metadata["retrieved_docs"])
            span.set_attribute("response_length", len(result) if result else 0)
            
            stage_cpu_usage.labels(stage="rag_retrieval").observe(metrics_delta["cpu_used"])
            stage_memory_usage.labels(stage="rag_retrieval").observe(metrics_delta["memory_used"])
            
            logger.info({
                "event": "rag_query_completed",
                "query_length": len(query),
                "retrieved_docs": metadata["retrieved_docs"],
                "response_length": len(result) if result else 0,
                "duration": duration,
                "cpu_used": metrics_delta["cpu_used"],
                "memory_used_mb": metrics_delta["memory_used"],
                "correlation_id": correlation_id
            })
            
            log_stage_boundary("rag_retrieval", "exit", correlation_id, 
                              duration=duration, docs=metadata["retrieved_docs"])
            
            return result, metadata
            
        except asyncio.TimeoutError:
            duration = time.time() - start_time
            span.set_attribute("error", True)
            span.set_attribute("error.type", "TimeoutError")
            
            rag_errors_total.labels(stage="retrieval", error_type="TimeoutError").inc()
            
            logger.error({
                "event": "rag_query_timeout",
                "query": query[:100],
                "timeout": RAG_TIMEOUT,
                "duration": duration,
                "correlation_id": correlation_id
            })
            
            timeout_message = f"I'm sorry, the query took too long (over {RAG_TIMEOUT} seconds). Please try a simpler question."
            
            log_stage_boundary("rag_retrieval", "exit", correlation_id, 
                              duration=duration, status="timeout")
            
            return timeout_message, {"retrieved_docs": 0, "error": "timeout"}
            
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            
            rag_errors_total.labels(stage="retrieval", error_type=type(e).__name__).inc()
            
            logger.error({
                "event": "rag_query_failed",
                "query": query[:100],
                "error": str(e),
                "error_type": type(e).__name__,
                "correlation_id": correlation_id
            })
            
            raise


# --------------------------------
# BUILD RAG
# --------------------------------

async def build_rag() -> RAGAnything:
    """Build and initialize RAG pipeline with enhanced configuration"""
    with tracer.start_as_current_span("build_rag") as span:
        
        span.set_attribute("working_dir", WORKING_DIR)
        span.set_attribute("embedding_model", EMBEDDING_MODEL)
        span.set_attribute("embedding_dim", EMBEDDING_DIM)
        span.set_attribute("llm_model", LLM_MODEL)
        
        logger.info({
            "event": "rag_initialization_start",
            "working_dir": WORKING_DIR,
            "embedding_model": EMBEDDING_MODEL,
            "llm_model": LLM_MODEL
        })
        
        start_time = time.time()
        
        embedding_func = EmbeddingFunc(
            embedding_dim=EMBEDDING_DIM,
            max_token_size=8192,
            func=embed_texts
        )
        
        lightrag_instance = LightRAG(
            working_dir=WORKING_DIR,
            llm_model_func=llm_func,
            embedding_func=embedding_func
        )
        
        await lightrag_instance.initialize_storages()
        
        config = RAGAnythingConfig(
            working_dir=WORKING_DIR
        )
        
        rag = RAGAnything(
            config=config,
            lightrag=lightrag_instance
        )
        
        duration = time.time() - start_time
        
        span.set_attribute("initialization_duration_sec", duration)
        
        logger.info({
            "event": "rag_initialization_complete",
            "duration": duration
        })
        
        return rag


# --------------------------------
# DOCUMENT PROCESSING
# --------------------------------

async def process_document(
    rag: RAGAnything,
    file_path: str,
    output_dir: str = "./output",
    parse_method: str = "auto"
) -> Dict[str, Any]:
    """Process document with enhanced metrics"""
    with tracer.start_as_current_span("document_processing") as span:
        
        span.set_attribute("document.file_path", file_path)
        span.set_attribute("document.parse_method", parse_method)
        span.set_attribute("document.output_dir", output_dir)
        
        start_time = time.time()
        
        logger.info({
            "event": "document_processing_start",
            "file_path": file_path,
            "parse_method": parse_method
        })
        
        try:
            await rag.process_document_complete(
                file_path=file_path,
                output_dir=output_dir,
                parse_method=parse_method
            )
            
            duration = time.time() - start_time
            file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
            
            span.set_attribute("document.size_bytes", file_size)
            span.set_attribute("processing_duration_sec", duration)
            
            logger.info({
                "event": "document_processing_complete",
                "file_path": file_path,
                "duration": duration,
                "file_size_bytes": file_size
            })
            
            return {
                "status": "success",
                "file_path": file_path,
                "duration": duration,
                "file_size": file_size
            }
            
        except Exception as e:
            span.set_attribute("error", True)
            span.set_attribute("error.type", type(e).__name__)
            
            rag_errors_total.labels(stage="document_processing", error_type=type(e).__name__).inc()
            
            logger.error({
                "event": "document_processing_failed",
                "file_path": file_path,
                "error": str(e),
                "error_type": type(e).__name__
            })
            
            raise


# --------------------------------
# HEALTH CHECK
# --------------------------------

async def health_check() -> Dict[str, Any]:
    """Perform health check on all components"""
    health_status = {
        "ollama": {"status": "unknown", "latency": None},
        "rag": {"status": "unknown", "latency": None},
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        start = time.time()
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if response.status_code == 200:
                health_status["ollama"]["status"] = "healthy"
            else:
                health_status["ollama"]["status"] = "unhealthy"
        health_status["ollama"]["latency"] = time.time() - start
    except Exception as e:
        health_status["ollama"]["status"] = "unavailable"
        health_status["ollama"]["error"] = str(e)
    
    try:
        if os.path.exists(WORKING_DIR):
            health_status["rag"]["status"] = "healthy"
            health_status["rag"]["storage_exists"] = True
        else:
            health_status["rag"]["status"] = "not_initialized"
    except Exception as e:
        health_status["rag"]["status"] = "error"
        health_status["rag"]["error"] = str(e)
    
    return health_status


# --------------------------------
# CLEANUP
# --------------------------------

async def cleanup():
    """Cleanup resources"""
    logger.info("Cleaning up RAG pipeline resources")
    await _ollama_client.close()
    _llm_cache.clear()


__all__ = [
    "build_rag",
    "query_rag",
    "process_document",
    "health_check",
    "cleanup",
    "llm_func",
    "embed_texts"
]