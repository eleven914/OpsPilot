import re
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any


class ToolExecutionError(RuntimeError):
    """Stable error exposed when a tool adapter exhausts its retry policy."""


class ToolTimeoutError(ToolExecutionError):
    pass


class CircuitOpenError(ToolExecutionError):
    pass


@dataclass(slots=True)
class _CircuitState:
    consecutive_failures: int = 0
    open_until: float = 0.0


class ToolResilience:
    """Bound read calls with timeout, retry, and a per-tool circuit breaker."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        max_retries: int = 1,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if timeout_seconds <= 0 or max_retries < 0 or failure_threshold <= 0:
            raise ValueError("Invalid resilience configuration")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._states: dict[str, _CircuitState] = {}
        self._state_lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def call(self, tool_name: str, operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._state_lock:
            state = self._states.setdefault(tool_name, _CircuitState())
            now = self._clock()
            if state.open_until > now:
                raise CircuitOpenError(f"Circuit is open for tool: {tool_name}")
            if state.open_until:
                state.open_until = 0.0
                state.consecutive_failures = 0

        last_error: BaseException | None = None
        for _attempt in range(self.max_retries + 1):
            future = self._executor.submit(operation)
            try:
                result = future.result(timeout=self.timeout_seconds)
            except FutureTimeoutError:
                future.cancel()
                last_error = ToolTimeoutError(
                    f"Tool {tool_name} exceeded {self.timeout_seconds:.3f}s timeout"
                )
            except (ConnectionError, OSError) as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
                break
            else:
                with self._state_lock:
                    state.consecutive_failures = 0
                return result

        with self._state_lock:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.failure_threshold:
                state.open_until = self._clock() + self.recovery_seconds
        if isinstance(last_error, ToolTimeoutError):
            raise last_error
        raise ToolExecutionError(f"Tool {tool_name} failed after retries") from last_error


_SENSITIVE_KEYS = frozenset(
    {"password", "passwd", "token", "access_token", "api_key", "secret", "authorization"}
)
_BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret)=([^\s,;]+)"
)


def sanitize_output(
    value: Any,
    *,
    max_string_length: int = 2000,
    max_collection_items: int = 200,
) -> Any:
    """Recursively redact credentials and cap untrusted output size."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for index, (key, nested) in enumerate(value.items()):
            if index >= max_collection_items:
                sanitized["_truncated"] = True
                break
            normalized = str(key).casefold().replace("-", "_")
            sanitized[str(key)] = (
                "[REDACTED]"
                if normalized in _SENSITIVE_KEYS
                else sanitize_output(
                    nested,
                    max_string_length=max_string_length,
                    max_collection_items=max_collection_items,
                )
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = list(value[:max_collection_items])
        return [
            sanitize_output(
                item,
                max_string_length=max_string_length,
                max_collection_items=max_collection_items,
            )
            for item in items
        ]
    if isinstance(value, str):
        redacted = _BEARER_PATTERN.sub("Bearer [REDACTED]", value)
        redacted = _ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
        if len(redacted) > max_string_length:
            return f"{redacted[:max_string_length]}...[TRUNCATED]"
        return redacted
    return deepcopy(value)
