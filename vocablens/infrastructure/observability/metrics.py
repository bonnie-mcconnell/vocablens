from prometheus_client import Counter, Gauge, Histogram

# HTTP
REQUEST_LATENCY = Histogram(
    "vocablens_http_request_seconds",
    "HTTP request latency",
    ["method", "endpoint", "status"],
)

ERROR_COUNT = Counter(
    "vocablens_http_errors_total",
    "Count of error responses",
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

EXTERNAL_CALLS = Counter(
    "vocablens_external_calls_total",
    "External provider call outcomes",
    ["name", "result"],
)

CIRCUIT_BREAKER_EVENTS = Counter(
    "vocablens_circuit_breaker_events_total",
    "Circuit breaker state changes and blocked calls",
    ["name", "event"],
)

JOB_EVENTS = Counter(
    "vocablens_job_events_total",
    "Background job lifecycle events",
    ["task", "event"],
)

NOTIFICATION_POLICY_HEALTH_STATUS = Gauge(
    "vocablens_notification_policy_health_status",
    "Current notification policy health state as a one-hot gauge",
    ["policy_key", "status"],
)

NOTIFICATION_POLICY_HEALTH_RATE = Gauge(
    "vocablens_notification_policy_health_rate_percent",
    "Current evaluated notification policy rates",
    ["policy_key", "metric"],
)

NOTIFICATION_POLICY_HEALTH_TRANSITIONS = Counter(
    "vocablens_notification_policy_health_transitions_total",
    "Notification policy health state transitions",
    ["policy_key", "from_status", "to_status"],
)

NOTIFICATION_POLICY_HEALTH_ALERTS = Counter(
    "vocablens_notification_policy_health_alerts_total",
    "Notification policy health alerts emitted",
    ["policy_key", "code", "severity"],
)

NOTIFICATION_POLICY_HEALTH_POLICIES = Gauge(
    "vocablens_notification_policy_health_policies",
    "Current count of notification policies by health status",
    ["status"],
)

NOTIFICATION_POLICY_ACTIVE_ALERTS = Gauge(
    "vocablens_notification_policy_active_alerts",
    "Current active notification policy alerts by policy and severity",
    ["policy_key", "severity"],
)
