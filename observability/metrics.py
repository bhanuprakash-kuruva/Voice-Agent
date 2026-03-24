from prometheus_client import start_http_server, Counter, Histogram, Gauge

# --------------------------------
# REQUEST METRICS
# --------------------------------

rag_requests_total = Counter(
    "rag_requests_total",
    "Total RAG queries",
    ["status"]
)

rag_active_requests = Gauge(
    "rag_active_requests",
    "Currently active RAG queries"
)

# --------------------------------
# LATENCY METRICS
# --------------------------------

pipeline_latency = Histogram("rag_pipeline_latency_seconds", "Total pipeline latency")
audio_latency = Histogram("audio_record_latency_seconds", "Audio recording latency")
stt_latency = Histogram("stt_latency_seconds", "Speech-to-text latency")
retrieval_latency = Histogram("rag_retrieval_latency_seconds", "Vector retrieval latency")
llm_latency = Histogram("llm_latency_seconds", "LLM generation latency")
tts_latency = Histogram("tts_latency_seconds", "Text-to-speech latency")

# --------------------------------
# TOKEN METRICS
# --------------------------------

prompt_tokens = Histogram("llm_prompt_tokens", "Prompt token count")
completion_tokens = Histogram("llm_completion_tokens", "Completion token count")
total_tokens = Histogram("llm_total_tokens", "Total tokens")
tokens_per_second = Histogram("llm_tokens_per_second", "Token generation speed")

# --------------------------------
# QUERY METRICS
# --------------------------------

query_length = Histogram("rag_query_length_chars", "Length of user queries")
response_length = Histogram("rag_response_length_chars", "Length of responses")

# --------------------------------
# RETRIEVAL QUALITY METRICS
# --------------------------------

documents_retrieved = Histogram("rag_documents_retrieved", "Number of retrieved documents")
rag_no_documents_found = Counter("rag_no_documents_found_total", "Queries with no documents retrieved")
retrieval_similarity_score = Histogram("rag_retrieval_similarity_score", "Similarity scores")

# --------------------------------
# VOICE METRICS
# --------------------------------

audio_duration_seconds = Histogram("audio_input_duration_seconds", "Audio duration")
stt_word_count = Histogram("stt_word_count", "STT word count")

# --------------------------------
# EMBEDDING METRICS
# --------------------------------

embedding_requests_total = Counter("embedding_requests_total", "Total embedding requests")
embedding_latency = Histogram("embedding_latency_seconds", "Embedding latency")

# --------------------------------
# LLM REQUESTS
# --------------------------------

llm_requests_total = Counter("llm_requests_total", "Total LLM requests")

# --------------------------------
# 🔥 RESOURCE METRICS (NEW - VERY IMPORTANT)
# --------------------------------

cpu_usage_percent = Gauge("system_cpu_usage_percent", "CPU usage percent")
memory_usage_mb = Gauge("system_memory_usage_mb", "Memory usage in MB")
process_threads = Gauge("process_threads", "Number of threads")

# 🔥 Per-stage resource usage
stage_cpu_usage = Histogram(
    "rag_stage_cpu_usage_percent",
    "CPU usage per pipeline stage",
    ["stage"]
)

stage_memory_usage = Histogram(
    "rag_stage_memory_usage_mb",
    "Memory usage per pipeline stage",
    ["stage"]
)

# 🔥 LLM specific (IMPORTANT for Ollama analysis)
llm_memory_usage = Histogram(
    "llm_memory_usage_mb",
    "Memory used during LLM execution"
)

llm_cpu_usage = Histogram(
    "llm_cpu_usage_percent",
    "CPU used during LLM execution"
)

# --------------------------------
# ERROR METRICS
# --------------------------------

rag_errors_total = Counter(
    "rag_errors_total",
    "Errors in RAG pipeline",
    ["stage"]
)

# --------------------------------
# START METRICS SERVER
# --------------------------------

def start_metrics_server():
    start_http_server(8000, addr="0.0.0.0")