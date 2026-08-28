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
class RuntimeLog:
    """A runtime error or infrastructure failure logged during a session.

    These are NOT signals — they don't penalise the session score.
    They're displayed in a separate 'Runtime Log' section of the pulse card
    with module provenance, so the user can see what actually failed
    without it affecting their quality metrics.
    """
    module: str          # which Hermes tool produced this (e.g. "terminal", "read_file")
    error: str           # the first error line, cleaned
    severity: str = "info"  # "info" | "warning" | "critical"


@dataclass
class SignalResult:
    """Output of the signal extraction phase."""
    signals: list[Signal]
    metrics: dict
    runtime_logs: list[RuntimeLog] = field(default_factory=list)
    skipped_reason: str | None = None