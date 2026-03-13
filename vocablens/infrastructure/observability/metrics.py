from prometheus_client import Counter, Histogram

# HTTP
REQUEST_LATENCY = Histogram(
    "vocablens_http_request_seconds",
    "HTTP request latency",
    ["method", "endpoint", "status"],
)

# LLM
LLM_LATENCY = Histogram(
    "vocablens_llm_latency_seconds",
    "LLM call latency",
    ["provider", "model"],
)
LLM_TOKENS = Counter(
    "vocablens_llm_tokens_total",
    "Total tokens used by LLM",
    ["provider", "model", "type"],
)
LLM_COST = Counter(
    "vocablens_llm_cost_usd_total",
    "Estimated USD cost of LLM calls",
    ["provider", "model"],
)

# Cache
CACHE_HITS = Counter(
    "vocablens_cache_hits_total",
    "Cache hits",
    ["cache", "op"],
)
CACHE_MISSES = Counter(
    "vocablens_cache_misses_total",
    "Cache misses",
    ["cache", "op"],
)

# DB
DB_QUERY_LATENCY = Histogram(
    "vocablens_db_query_seconds",
    "DB query duration",
    ["db"],
)
