from collections.abc import Mapping, Sequence
from typing import Any

from opspilot.agent.schemas import FinalAnswerDecision, ProposedActionDecision


class PolicyViolationError(ValueError):
    """Raised when a structurally valid model decision violates safety policy."""


class SafetyGuard:
    _forbidden_keys = frozenset(
        {"command", "cmd", "shell", "script", "powershell", "bash"}
    )
    _shell_metacharacters = ("&&", "||", ";", "`", "$(", "\n", "\r")

    def validate_action(
        self,
        action: ProposedActionDecision,
        known_evidence_ids: set[str],
    ) -> None:
        unknown = set(action.evidence_ids) - known_evidence_ids
        if unknown:
            raise PolicyViolationError(
                f"Action references unknown evidence: {sorted(unknown)}"
            )
        self._reject_command_material(action.arguments)

    def validate_final_answer(
        self,
        answer: FinalAnswerDecision,
        known_evidence_ids: set[str],
    ) -> None:
        unknown = set(answer.evidence_ids) - known_evidence_ids
        if unknown:
            raise PolicyViolationError(
                f"Answer references unknown evidence: {sorted(unknown)}"
            )
        if not answer.evidence_ids and not answer.insufficient_information:
            raise PolicyViolationError(
                "An answer without evidence must declare insufficient information"
            )
        if answer.insufficient_information and answer.confidence > 0.5:
            raise PolicyViolationError(
                "Insufficient-information answers cannot have high confidence"
            )

    def _reject_command_material(self, value: Any, path: str = "arguments") -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                normalized = str(key).casefold()
                if normalized in self._forbidden_keys:
                    raise PolicyViolationError(
                        f"Shell-like argument key is forbidden: {path}.{key}"
                    )
                self._reject_command_material(nested, f"{path}.{key}")
            return
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            for index, nested in enumerate(value):
                self._reject_command_material(nested, f"{path}[{index}]")
            return
        if isinstance(value, str) and any(
            marker in value for marker in self._shell_metacharacters
        ):
            raise PolicyViolationError(
                f"Shell control characters are forbidden in {path}"
            )
