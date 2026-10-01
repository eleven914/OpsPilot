import json

MODEL_CONTRACT = {
    "decision_types": {
        "tool_call": ["type", "tool", "arguments", "reason"],
        "proposed_action": [
            "type",
            "tool",
            "arguments",
            "risk",
            "evidence_ids",
            "rollback_plan",
        ],
        "final_answer": [
            "type",
            "summary",
            "root_causes",
            "confidence",
            "evidence_ids",
            "next_steps",
            "insufficient_information",
        ],
    },
    "tools": {
        "query_metrics": {
            "service": "string",
            "metric": "string",
            "start": "ISO-8601 datetime",
            "end": "ISO-8601 datetime",
        },
        "query_logs": {
            "service": "string",
            "keywords": "array[string]",
            "level": "string|null",
            "start": "ISO-8601 datetime",
            "end": "ISO-8601 datetime",
            "limit": "integer 1..200",
        },
        "get_service_info": {"service": "string"},
        "search_runbook": {
            "query": "string",
            "service": "string",
            "top_k": "integer 1..10",
        },
        "search_incidents": {
            "query": "string",
            "service": "string",
            "top_k": "integer 1..10",
        },
        "restart_service": {
            "service": "string",
            "instance_ids": "array[string]",
            "reason": "string",
        },
        "rollback_deployment": {
            "service": "string",
            "target_version": "string",
            "reason": "string",
        },
    },
}
SYSTEM_POLICY = (
    "You are OpsPilot. Output exactly one JSON decision with no markdown or extra text. "
    "Use only the supplied tool contract and copy opaque values exactly from the context. "
    "Cite collected evidence, and propose approval instead of directly executing changes. "
    "Contract:"
    + json.dumps(MODEL_CONTRACT, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
)
READ_TOOLS = (
    "query_metrics",
    "query_logs",
    "get_service_info",
    "search_runbook",
    "search_incidents",
)
