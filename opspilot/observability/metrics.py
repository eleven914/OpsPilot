from prometheus_client import Counter, Histogram

HTTP_REQUESTS = Counter(
    "opspilot_http_requests_total",
    "HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_DURATION = Histogram(
    "opspilot_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "route"),
)
DIAGNOSIS_RUNS = Counter(
    "opspilot_diagnosis_runs_total",
    "Diagnosis runs by final outcome.",
    ("mode", "outcome"),
)
DIAGNOSIS_DURATION = Histogram(
    "opspilot_diagnosis_duration_seconds",
    "Diagnosis runtime in seconds.",
    ("mode",),
)
TASK_RUNS = Counter(
    "opspilot_task_runs_total",
    "Celery diagnosis tasks by outcome.",
    ("outcome",),
)
TASK_DURATION = Histogram(
    "opspilot_task_duration_seconds",
    "Celery diagnosis task runtime in seconds.",
)
MODEL_REQUESTS = Counter(
    "opspilot_model_requests_total",
    "OpenAI-compatible model requests by outcome.",
    ("model", "outcome"),
)
MODEL_DURATION = Histogram(
    "opspilot_model_request_duration_seconds",
    "OpenAI-compatible model latency in seconds.",
    ("model",),
)
MODEL_TOKENS = Counter(
    "opspilot_model_tokens_total",
    "Model token consumption.",
    ("model", "kind"),
)
MODEL_ESTIMATED_COST = Counter(
    "opspilot_model_estimated_cost_usd_total",
    "Estimated model cost in US dollars from configured token prices.",
    ("model",),
)
MODEL_FALLBACKS = Counter(
    "opspilot_model_fallbacks_total",
    "Model requests that fell back to the mock orchestrator.",
    ("reason",),
)
