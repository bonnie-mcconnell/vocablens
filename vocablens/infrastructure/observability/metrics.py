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

EXPERIMENT_HEALTH_STATUS = Gauge(
    "vocablens_experiment_health_status",
    "Current experiment health state as a one-hot gauge",
    ["experiment_key", "status"],
)

EXPERIMENT_HEALTH_RATE = Gauge(
    "vocablens_experiment_health_metric",
    "Current evaluated experiment health metrics",
    ["experiment_key", "metric"],
)

EXPERIMENT_HEALTH_TRANSITIONS = Counter(
    "vocablens_experiment_health_transitions_total",
    "Experiment health state transitions",
    ["experiment_key", "from_status", "to_status"],
)

EXPERIMENT_HEALTH_ALERTS = Counter(
    "vocablens_experiment_health_alerts_total",
    "Experiment health alerts emitted",
    ["experiment_key", "code", "severity"],
)

EXPERIMENT_HEALTH_EXPERIMENTS = Gauge(
    "vocablens_experiment_health_experiments",
    "Current count of experiments by health status",
    ["status"],
)

EXPERIMENT_ACTIVE_ALERTS = Gauge(
    "vocablens_experiment_active_alerts",
    "Current active experiment alerts by experiment and severity",
    ["experiment_key", "severity"],
)

MONETIZATION_HEALTH_STATUS = Gauge(
    "vocablens_monetization_health_status",
    "Current monetization health state as a one-hot gauge",
    ["scope_key", "status"],
)

MONETIZATION_HEALTH_RATE = Gauge(
    "vocablens_monetization_health_metric",
    "Current evaluated monetization health metrics",
    ["scope_key", "metric"],
)

MONETIZATION_HEALTH_TRANSITIONS = Counter(
    "vocablens_monetization_health_transitions_total",
    "Monetization health state transitions",
    ["scope_key", "from_status", "to_status"],
)

MONETIZATION_HEALTH_ALERTS = Counter(
    "vocablens_monetization_health_alerts_total",
    "Monetization health alerts emitted",
    ["scope_key", "code", "severity"],
)

MONETIZATION_HEALTH_SCOPES = Gauge(
    "vocablens_monetization_health_scopes",
    "Current count of monetization scopes by health status",
    ["status"],
)

MONETIZATION_ACTIVE_ALERTS = Gauge(
    "vocablens_monetization_active_alerts",
    "Current active monetization alerts by scope and severity",
    ["scope_key", "severity"],
)

LIFECYCLE_HEALTH_STATUS = Gauge(
    "vocablens_lifecycle_health_status",
    "Current lifecycle health state as a one-hot gauge",
    ["scope_key", "status"],
)

LIFECYCLE_HEALTH_RATE = Gauge(
    "vocablens_lifecycle_health_metric",
    "Current evaluated lifecycle health metrics",
    ["scope_key", "metric"],
)

LIFECYCLE_HEALTH_TRANSITIONS = Counter(
    "vocablens_lifecycle_health_transitions_total",
    "Lifecycle health state transitions",
    ["scope_key", "from_status", "to_status"],
)

LIFECYCLE_HEALTH_ALERTS = Counter(
    "vocablens_lifecycle_health_alerts_total",
    "Lifecycle health alerts emitted",
    ["scope_key", "code", "severity"],
)

LIFECYCLE_HEALTH_SCOPES = Gauge(
    "vocablens_lifecycle_health_scopes",
    "Current count of lifecycle scopes by health status",
    ["status"],
)

LIFECYCLE_ACTIVE_ALERTS = Gauge(
    "vocablens_lifecycle_active_alerts",
    "Current active lifecycle alerts by scope and severity",
    ["scope_key", "severity"],
)

DAILY_LOOP_HEALTH_STATUS = Gauge(
    "vocablens_daily_loop_health_status",
    "Current daily loop health state as a one-hot gauge",
    ["scope_key", "status"],
)

DAILY_LOOP_HEALTH_RATE = Gauge(
    "vocablens_daily_loop_health_metric",
    "Current evaluated daily loop health metrics",
    ["scope_key", "metric"],
)

DAILY_LOOP_HEALTH_TRANSITIONS = Counter(
    "vocablens_daily_loop_health_transitions_total",
    "Daily loop health state transitions",
    ["scope_key", "from_status", "to_status"],
)

DAILY_LOOP_HEALTH_ALERTS = Counter(
    "vocablens_daily_loop_health_alerts_total",
    "Daily loop health alerts emitted",
    ["scope_key", "code", "severity"],
)

DAILY_LOOP_HEALTH_SCOPES = Gauge(
    "vocablens_daily_loop_health_scopes",
    "Current count of daily loop scopes by health status",
    ["status"],
)

DAILY_LOOP_ACTIVE_ALERTS = Gauge(
    "vocablens_daily_loop_active_alerts",
    "Current active daily loop alerts by scope and severity",
    ["scope_key", "severity"],
)

SESSION_HEALTH_STATUS = Gauge(
    "vocablens_session_health_status",
    "Current session health state as a one-hot gauge",
    ["scope_key", "status"],
)

SESSION_HEALTH_RATE = Gauge(
    "vocablens_session_health_metric",
    "Current evaluated session health metrics",
    ["scope_key", "metric"],
)

SESSION_HEALTH_TRANSITIONS = Counter(
    "vocablens_session_health_transitions_total",
    "Session health state transitions",
    ["scope_key", "from_status", "to_status"],
)

SESSION_HEALTH_ALERTS = Counter(
    "vocablens_session_health_alerts_total",
    "Session health alerts emitted",
    ["scope_key", "code", "severity"],
)

SESSION_HEALTH_SCOPES = Gauge(
    "vocablens_session_health_scopes",
    "Current count of session scopes by health status",
    ["status"],
)

SESSION_ACTIVE_ALERTS = Gauge(
    "vocablens_session_active_alerts",
    "Current active session alerts by scope and severity",
    ["scope_key", "severity"],
)

LEARNING_HEALTH_STATUS = Gauge(
    "vocablens_learning_health_status",
    "Current learning health state as a one-hot gauge",
    ["scope_key", "status"],
)

LEARNING_HEALTH_RATE = Gauge(
    "vocablens_learning_health_metric",
    "Current evaluated learning health metrics",
    ["scope_key", "metric"],
)

LEARNING_HEALTH_TRANSITIONS = Counter(
    "vocablens_learning_health_transitions_total",
    "Learning health state transitions",
    ["scope_key", "from_status", "to_status"],
)

LEARNING_HEALTH_ALERTS = Counter(
    "vocablens_learning_health_alerts_total",
    "Learning health alerts emitted",
    ["scope_key", "code", "severity"],
)

LEARNING_HEALTH_SCOPES = Gauge(
    "vocablens_learning_health_scopes",
    "Current count of learning scopes by health status",
    ["status"],
)

LEARNING_ACTIVE_ALERTS = Gauge(
    "vocablens_learning_active_alerts",
    "Current active learning alerts by scope and severity",
    ["scope_key", "severity"],
)

CONTENT_QUALITY_HEALTH_STATUS = Gauge(
    "vocablens_content_quality_health_status",
    "Current content quality health state as a one-hot gauge",
    ["scope_key", "status"],
)

CONTENT_QUALITY_HEALTH_RATE = Gauge(
    "vocablens_content_quality_health_metric",
    "Current evaluated content quality health metrics",
    ["scope_key", "metric"],
)

CONTENT_QUALITY_HEALTH_TRANSITIONS = Counter(
    "vocablens_content_quality_health_transitions_total",
    "Content quality health state transitions",
    ["scope_key", "from_status", "to_status"],
)

CONTENT_QUALITY_HEALTH_ALERTS = Counter(
    "vocablens_content_quality_health_alerts_total",
    "Content quality health alerts emitted",
    ["scope_key", "code", "severity"],
)

CONTENT_QUALITY_HEALTH_SCOPES = Gauge(
    "vocablens_content_quality_health_scopes",
    "Current count of content quality scopes by health status",
    ["status"],
)

CONTENT_QUALITY_ACTIVE_ALERTS = Gauge(
    "vocablens_content_quality_active_alerts",
    "Current active content quality alerts by scope and severity",
    ["scope_key", "severity"],
)
