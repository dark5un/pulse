from dataclasses import dataclass, field


@dataclass
class Signal:
    """A single finding with traceable evidence.

    Every Signal must answer: what was detected, who is it about,
    how severe is it, what evidence supports it, and what penalty
    (if any) is applied to the attribution score.
    """
    name: str            # short identifier, e.g. "correction_chain"
    target: str          # "user" | "agent" | "system"
    severity: str        # "info" | "warning" | "critical"
    penalty: float = 0.0  # 0–25 score deduction
    evidence: list[str] = field(default_factory=list)
    detail: str = ""
    label: str = ""


@dataclass
class SignalResult:
    """Output of the signal extraction phase."""
    signals: list[Signal]
    metrics: dict
    skipped_reason: str | None = None
