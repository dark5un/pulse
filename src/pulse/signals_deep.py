"""LLM-judge detectors (B2 + verdict schema v2): goal_completion,
context_retention, correction_quality, hallucination. One combined
temperature-0 call; verdicts map to normal Signals (penalty ceiling 25,
evidence quotes).

Schema v2 (ADR 0006 + 0012): every declared signal gets a verdict with
``finding: yes | no | unscoreable`` — "yes" means the PROBLEM was found.
``unscoreable`` is the explicit abstain (thin/truncated window); an
ABSENT verdict abstains too and is never counted as "no" (omission was
laundering forced-choice bias). Evidence for penalty>0 must be a verbatim
transcript quote; quotes are substring-grounded against the prompt body
(ML-A4) and ungrounded ones become parse diagnostics, never silent trust.
Unparseable output -> [] with diagnostics (never fabricate). Judge CALL
failure -> JudgeCallError, loud in every path (M0 contract).
PROMPT_VERSION pinned; verdict caches key on it and store the finding."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass

from .judge import JudgeBackend
from .models import Signal

PROMPT_VERSION = "v2"

#: Legacy fixed prompt bound — from the hosted-judge era. Retained ONLY as
#: the explicit static fallback when no context window is configured or
#: probed for the interactive paths (ADR 0010/0013); the gate batch path
#: derives the budget from the judge model's context window instead.
#: MAX_MESSAGE_CHARS is the per-message cap — flagged for S3 measurement
#: as the likely tool-output-evidence limiter (plan decision 11).
MAX_PROMPT_CHARS = 12_000
MAX_MESSAGE_CHARS = 500

#: Decision 11 / ADR 0013: batch judge budget = pinned endpoint's context
#: window minus reserved headroom (output + instructions/schema +
#: estimation slack), converted to chars. Conversions are estimates; the
#: ACTUAL per-call prompt size + truncated flag is measured at judge time
#: (JudgeRun) and feeds the G4/CW-7 distribution block — the effective cap
#: is a measured knob, never a guess baked back in.
CHARS_PER_TOKEN_ESTIMATE = 4
JUDGE_RESERVE_TOKENS = 1536
MIN_PROMPT_BUDGET = 2_000

DEEP_SIGNALS = (
    "goal_completion",
    "context_retention",
    "correction_quality",
    "hallucination",
)

#: Verdict findings the judge may return (ADR 0006). Anything else is dropped.
FINDINGS = ("yes", "no", "unscoreable")

#: Absolute penalty ceiling per verdict.
MAX_VERDICT_PENALTY = 25.0
#: Max evidence strings accepted per verdict; each capped at this length.
MAX_EVIDENCE_ITEMS = 4
MAX_EVIDENCE_CHARS = 200

#: build_prompt's disclosed cut marker; its presence means the judge sees a
#: truncated window (shared with the corpus approx_truncated stamp).
TRUNCATION_MARKER = "transcript truncated: middle omitted"

# correction_quality describes the USER's correction specificity -> user target; rest agent.
TARGETS = {
    "correction_quality": "user",
    "goal_completion": "agent",
    "context_retention": "agent",
    "hallucination": "agent",
}


class JudgeCallError(RuntimeError):
    """Judge/backend CALL failure (network, API, auth, refused connection).

    M0 loud-failure contract: this must surface to batch callers — a judge
    that never answered is NOT "no verdicts". Unparseable judge OUTPUT is a
    different shape and still yields [] with parse diagnostics.
    """


class JudgeBudgetError(RuntimeError):
    """No judge prompt budget can be determined (ADR 0010/0013): the
    context window is unknown and no explicit budget is configured. The
    batch path refuses to run rather than assume a window."""


@dataclass(frozen=True)
class PromptBudget:
    """Judge prompt budget + its provenance (loud, inspectable)."""

    budget_chars: int
    context_window_tokens: int | None
    source: str  # explicit | env | probe | config-fallback | static-fallback


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise JudgeBudgetError(f"{name}={raw!r} is not an integer") from e


def _reserve_tokens() -> int:
    reserve = _env_int("PULSE_JUDGE_RESERVE_TOKENS")
    if reserve is not None and reserve < 0:
        raise JudgeBudgetError("PULSE_JUDGE_RESERVE_TOKENS must be >= 0")
    return JUDGE_RESERVE_TOKENS if reserve is None else reserve


def budget_from_context(context_tokens: int) -> int:
    """Model-derived char budget: window minus reserved headroom (ADR 0010)."""
    reserve = _reserve_tokens()
    if context_tokens <= reserve:
        raise JudgeBudgetError(
            f"context window {context_tokens} <= reserved headroom {reserve} "
            "(PULSE_JUDGE_RESERVE_TOKENS): nothing left for transcript"
        )
    return max(MIN_PROMPT_BUDGET, (context_tokens - reserve) * CHARS_PER_TOKEN_ESTIMATE)


def resolve_prompt_budget(
    backend: JudgeBackend, explicit_context_tokens: int | None = None
) -> PromptBudget:
    """Batch-path budget (Decision 11): explicit (manifest/CLI) -> env
    PULSE_JUDGE_CONTEXT -> read-only probe of the pinned endpoint's
    /v1/models metadata -> explicit char config PULSE_JUDGE_MAX_PROMPT_CHARS.
    If none exist: loud JudgeBudgetError naming the knobs — never assume."""
    explicit = explicit_context_tokens
    ctx = explicit or _env_int("PULSE_JUDGE_CONTEXT")
    source = "explicit" if explicit else "env"
    if not ctx:
        probe = getattr(backend, "context_window", None)
        if callable(probe):
            probed = probe()
            ctx = probed if isinstance(probed, int) else None
        source = "probe"
    if ctx:
        return PromptBudget(budget_from_context(ctx), ctx, source)
    fixed = _env_int("PULSE_JUDGE_MAX_PROMPT_CHARS")
    if fixed:
        return PromptBudget(max(MIN_PROMPT_BUDGET, fixed), None, "config-fallback")
    base = getattr(backend, "base_url", "") or "endpoint"
    raise JudgeBudgetError(
        "no judge context window available: the read-only probe of "
        f"{base}/v1/models exposed nothing. Set PULSE_JUDGE_CONTEXT=<tokens> "
        "(or supply the manifest context_window field) or pin an explicit "
        "budget via PULSE_JUDGE_MAX_PROMPT_CHARS=<chars>; the batch gate "
        "never assumes a window (ADR 0010)."
    )


def default_prompt_budget() -> PromptBudget:
    """Interactive/plugin/corpus paths where no endpoint probe applies:
    env-derived if configured, else the explicit static fallback
    (MAX_PROMPT_CHARS) — recorded with its source so the fallback is
    visible, and flagged for S3 measurement."""
    ctx = _env_int("PULSE_JUDGE_CONTEXT")
    if ctx:
        return PromptBudget(budget_from_context(ctx), ctx, "env")
    fixed = _env_int("PULSE_JUDGE_MAX_PROMPT_CHARS")
    if fixed:
        return PromptBudget(max(MIN_PROMPT_BUDGET, fixed), None, "config-fallback")
    return PromptBudget(MAX_PROMPT_CHARS, None, "static-fallback")


class VerdictParseResult:
    """parse_verdict_text outcome: accepted signals + per-verdict diagnostics.

    ``findings`` maps every accepted signal to its v2 finding
    (yes|no|unscoreable) — the finding-aware payload batch callers cache.
    ``grounded``/``total_quotes`` count verbatim-evidence grounding (ML-A4)
    over accepted penalty>0 verdicts when the prompt was supplied.
    """

    def __init__(
        self,
        signals: list[Signal],
        diagnostics: list[str],
        findings: dict[str, str] | None = None,
        grounded: int = 0,
        total_quotes: int = 0,
    ) -> None:
        self.signals = signals
        self.diagnostics = diagnostics
        self.findings = findings or {}
        self.grounded = grounded
        self.total_quotes = total_quotes

    def __iter__(self):  # unpack as (signals, diagnostics)
        yield self.signals
        yield self.diagnostics


def _prompt_head() -> str:
    schema = (
        '{"prompt_version": "'
        + PROMPT_VERSION
        + '", "verdicts": [{"signal": "<one of '
        + "|".join(DEEP_SIGNALS)
        + '>", "finding": "yes|no|unscoreable", "penalty": <0-25>, '
        + '"evidence": "<verbatim quote copied from the TRANSCRIPT>"}]}'
    )
    return (
        "You are Pulse, a session-quality judge. Return exactly one verdict for "
        "EACH of the four signals — never omit a signal. 'yes' means the PROBLEM "
        "was found (penalty 1-25 requires a verbatim evidence quote copied from "
        "the transcript); 'no' means you checked and the problem was NOT found "
        "(penalty 0); 'unscoreable' means you cannot decide from the window shown. "
        "Abstain with 'unscoreable' exactly when the transcript is thin (too few "
        "turns to judge that signal at all) or truncated (the bracketed "
        "truncation notice says the middle of the transcript was omitted, "
        "and the signal's evidence could plausibly sit in that omitted middle) — "
        "never abstain on a signal you can actually check, "
        "and never guess yes/no where you should abstain. Evidence must be copied "
        f"verbatim from the transcript. Reply with exactly this JSON shape: "
        f"{schema}\n\nTRANSCRIPT:\n"
    )


def _compose_prompt(messages: list[dict], budget_chars: int) -> tuple[str, bool]:
    head = _prompt_head()
    redacted_lines = []
    for m in messages:
        text = redact_text(str(m.get("content", ""))[:MAX_MESSAGE_CHARS])
        redacted_lines.append(f"{m.get('role', '?')}: {text}")
    body = "\n".join(redacted_lines)
    # Bound the transcript: cut from the middle (keep opening + recent tail),
    # and disclose the cut so the judge knows it sees a window. Middle
    # truncation is the FALLBACK path after the model-derived budget (ADR
    # 0010); the truncated flag is reported per call, never hidden.
    budget = budget_chars - len(head)
    truncated = len(body) > budget
    if truncated:
        keep_head = budget * 2 // 3
        keep_tail = budget - keep_head - 60
        body = (
            body[:keep_head]
            + "\n[… " + TRUNCATION_MARKER + " …]\n"
            + body[len(body) - keep_tail:]
        )
    return head + body, truncated


def build_prompt(messages: list[dict], budget: PromptBudget | None = None) -> str:
    """Judge prompt at the given budget (default: default_prompt_budget())."""
    chars = budget.budget_chars if budget is not None else default_prompt_budget().budget_chars
    return _compose_prompt(messages, chars)[0]


#: Version of the redaction pattern set below. Stamped into corpus
#: snapshots and run manifests so a redaction-vintage change is visible
#: (deep-judge gate plan M2/decision 7). Bump when patterns change.
REDACT_VERSION = "v1"


def redact_text(text: str) -> str:
    """Redact secrets from judge-bound text (keys, tokens, emails)."""
    patterns = [
        r"sk-(?:proj-)?[A-Za-z0-9_-]{8,}",
        r"\bgh[pousr]_[A-Za-z0-9]{8,}\b",
        r"Bearer\s+[A-Za-z0-9\-._~+/=]{8,}",
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        r"(?i)\b((?:api[_-]?key|secret|token|password)\b[^A-Za-z0-9]{0,10})([0-9a-f]{32,})\b",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, "[REDACTED]", out)
    return out


def detect_deep(messages: list[dict], backend: JudgeBackend) -> list[Signal]:
    """Judge one transcript; return verdict signals.

    Raises JudgeCallError when the backend call itself fails (loud in every
    path, matching the /pulse deep contract: silent [] laundered outages
    into "clean" transcripts in September's gate run).
    """
    try:
        result = backend.judge(build_prompt(messages))
    except JudgeCallError:
        raise
    except Exception as e:
        ident = getattr(backend, "model", "?")
        base = getattr(backend, "base_url", "") or "default endpoint"
        raise JudgeCallError(f"judge call failed ({ident} @ {base}): {e}") from e
    return parse_verdict_text(result.text).signals


def _validate_evidence(raw: object) -> list[str] | None:
    """Normalize evidence to a bounded list of bounded strings. None if invalid."""
    if isinstance(raw, str):
        items = [raw] if raw else []
    elif isinstance(raw, list):
        items = raw
    else:
        return None
    if len(items) > MAX_EVIDENCE_ITEMS:
        return None
    clean: list[str] = []
    for item in items:
        if not isinstance(item, str):
            return None
        if len(item) > MAX_EVIDENCE_CHARS * 10:
            return None
        clean.append(item[:MAX_EVIDENCE_CHARS])
    return clean


_GROUND_ELLIPSIS = re.compile(r"(?:\.{3}|…|\u22ef)+")
_GROUND_BRACKETS = re.compile(r"\[[^\]]*\]")
_GROUND_WS = re.compile(r"\s+")
#: Fragments shorter than this carry no discriminating signal (substring
#: checks on crumbs left by truncation edges are noise, not evidence).
_GROUND_MIN_FRAGMENT = 4


def _is_grounded(quote: str, prompt: str) -> bool:
    """Substring-match an evidence quote against the prompt body (ML-A4).

    Normalizes for what judges legitimately do to quotes: bracketed
    insertions (incl. [REDACTED]) and ellipses split the quote into
    fragments — every usable fragment must be found in the prompt. A quote
    truncated at the 500-char message cap or MAX_EVIDENCE_CHARS is still a
    contiguous substring, so plain prefix truncation grounds naturally.
    A quote with no usable fragment is too vague to falsify and counts as
    grounded (empty-evidence rules are policed elsewhere).
    """
    parts = _GROUND_BRACKETS.sub(" ⋯ ", quote)
    parts = _GROUND_ELLIPSIS.sub(" ⋯ ", parts)
    fragments = [_GROUND_WS.sub(" ", p).strip().lower() for p in parts.split(" ⋯ ")]
    fragments = [f for f in fragments if len(f) >= _GROUND_MIN_FRAGMENT]
    if not fragments:
        return True
    hay = _GROUND_WS.sub(" ", prompt).lower()
    return all(f in hay for f in fragments)


def parse_verdict_text(text: str, prompt: str = "") -> VerdictParseResult:
    """Parse a judge JSON payload into signals + diagnostics.

    Invalid verdicts (bad finding, non-finite penalty, penalty without
    evidence, bad evidence shape) are dropped with a diagnostic — they can
    never carry a penalty into scoring. Duplicate signal names merge
    deterministically (highest penalty wins).

    v2 rules: ``unscoreable`` is an accepted abstain — penalty forced to 0,
    evidence optional. When a ``prompt`` is supplied, evidence for
    penalty>0 verdicts is substring-grounded against it; an ungrounded
    quote does NOT drop the signal (the finding may still be real) but
    emits a parse diagnostic and lowers the reported grounded-quote rate —
    fabricated evidence becomes visible data, never silent trust (ML-A4).
    """
    signals: list[Signal] = []
    diagnostics: list[str] = []
    try:
        payload = json.loads(text)
    except Exception:  # noqa: BLE001 — malformed judge output reads as no verdicts
        return VerdictParseResult([], ["payload is not valid JSON"])
    if not isinstance(payload, dict) or payload.get("prompt_version") != PROMPT_VERSION:
        return VerdictParseResult([], ["payload missing or mismatched prompt_version"])
    verdicts = payload.get("verdicts", [])
    if not isinstance(verdicts, list):
        return VerdictParseResult([], ["verdicts is not a list"])
    merged: dict[str, dict] = {}
    for i, v in enumerate(verdicts):
        where = f"verdict[{i}]"
        if not isinstance(v, dict) or v.get("signal") not in DEEP_SIGNALS:
            diagnostics.append(f"{where}: unknown or missing signal")
            continue
        name = str(v["signal"])
        finding = v.get("finding", "?")
        if finding not in FINDINGS:
            diagnostics.append(f"{where} {name}: finding {finding!r} not in {list(FINDINGS)} — dropped")
            continue
        try:
            penalty = float(v.get("penalty", 0))
        except (TypeError, ValueError):
            diagnostics.append(f"{where} {name}: penalty not numeric — dropped")
            continue
        if not math.isfinite(penalty):
            diagnostics.append(f"{where} {name}: penalty {penalty!r} not finite — dropped")
            continue
        penalty = max(0.0, min(MAX_VERDICT_PENALTY, penalty))
        if finding == "unscoreable" and penalty != 0:
            diagnostics.append(
                f"{where} {name}: finding=unscoreable with penalty {penalty} — abstain forced to 0"
            )
            penalty = 0.0
        if finding == "no" and penalty != 0:
            diagnostics.append(f"{where} {name}: finding=no with penalty {penalty} — dropped")
            continue
        evidence = _validate_evidence(v.get("evidence", ""))
        if evidence is None:
            diagnostics.append(f"{where} {name}: evidence wrong shape or oversized — dropped")
            continue
        if penalty > 0 and not any(e.strip() for e in evidence):
            diagnostics.append(f"{where} {name}: penalty {penalty} with empty evidence — dropped")
            continue
        if name in merged:
            diagnostics.append(f"{where} {name}: duplicate signal — keeping highest penalty")
            if penalty > merged[name]["penalty"]:
                merged[name] = {"penalty": penalty, "evidence": evidence, "finding": finding}
        else:
            merged[name] = {"penalty": penalty, "evidence": evidence, "finding": finding}
    grounded = total_quotes = 0
    for name, m in merged.items():
        penalty = m["penalty"]
        if prompt and penalty > 0:
            for quote in m["evidence"]:
                if not quote.strip():
                    continue
                total_quotes += 1
                if _is_grounded(quote, prompt):
                    grounded += 1
                else:
                    diagnostics.append(
                        f"{name}: evidence quote not grounded in the prompt body "
                        f"(verbatim quote required): {quote[:60]!r}"
                    )
        signals.append(
            Signal(
                name=name,
                target=TARGETS[name],
                severity=(
                    "info" if penalty == 0 else ("warning" if penalty <= 10 else "critical")
                ),
                penalty=penalty,
                evidence=m["evidence"],
                detail="llm-judge " + PROMPT_VERSION + " — provisional until agreement-gated",
                label=f"Judge: {m['finding']} — {name}",
            )
        )
    findings = {name: m["finding"] for name, m in merged.items()}
    return VerdictParseResult(signals, diagnostics, findings, grounded, total_quotes)


class JudgeRun:
    """One full judge pass with the measurement surface S3 needs:
    per-call prompt size + truncated flag, grounding counts, findings map,
    and the budget (with provenance) the prompt was built under."""

    def __init__(
        self,
        signals: list[Signal],
        findings: dict[str, str],
        diagnostics: list[str],
        grounded: int,
        total_quotes: int,
        prompt_chars: int,
        truncated: bool,
        budget: PromptBudget | None = None,
    ) -> None:
        self.signals = signals
        self.findings = findings
        self.diagnostics = diagnostics
        self.grounded = grounded
        self.total_quotes = total_quotes
        self.prompt_chars = prompt_chars
        self.truncated = truncated
        self.budget = budget


def run_judge(
    messages: list[dict],
    backend: JudgeBackend,
    budget: PromptBudget | None = None,
) -> JudgeRun:
    """Judge with model-derived budget + prompt-size/grounding exposure
    (gate batch path, Decision 11 / ADR 0010).

    Budget resolution is loud: no context window and no explicit config ->
    JudgeBudgetError before any GPU time is spent. Same call-failure
    contract as detect_deep: backend failure raises JudgeCallError (a
    provider over-long rejection surfaces through it too — the prompt was
    built to the budget, so a rejection means the estimate was wrong:
    fix the knob, Pulse never silently clips). The exact prompt sent is
    retained so evidence quotes can be grounded against it (ML-A4).
    """
    budget = budget or resolve_prompt_budget(backend)
    prompt, truncated = _compose_prompt(messages, budget.budget_chars)
    try:
        result = backend.judge(prompt)
    except JudgeCallError:
        raise
    except Exception as e:
        ident = getattr(backend, "model", "?")
        base = getattr(backend, "base_url", "") or "default endpoint"
        detail = f"judge call failed ({ident} @ {base}): {e}"
        if "context" in str(e).lower() or "too long" in str(e).lower():
            detail += (
                " — provider rejected the prompt as over-long; the derived "
                "budget estimate (chars/token or reserve) is too generous for "
                "this endpoint: lower PULSE_JUDGE_CONTEXT or raise "
                "PULSE_JUDGE_RESERVE_TOKENS (Pulse does not silently clip)"
            )
        raise JudgeCallError(detail) from e
    parsed = parse_verdict_text(result.text, prompt=prompt)
    return JudgeRun(
        signals=parsed.signals,
        findings=parsed.findings,
        diagnostics=parsed.diagnostics,
        grounded=parsed.grounded,
        total_quotes=parsed.total_quotes,
        prompt_chars=len(prompt),
        truncated=truncated,
        budget=budget,
    )


__all__ = [
    "DEEP_SIGNALS",
    "FINDINGS",
    "MAX_PROMPT_CHARS",
    "PROMPT_VERSION",
    "REDACT_VERSION",
    "TRUNCATION_MARKER",
    "JudgeBudgetError",
    "JudgeCallError",
    "JudgeRun",
    "PromptBudget",
    "VerdictParseResult",
    "budget_from_context",
    "build_prompt",
    "default_prompt_budget",
    "detect_deep",
    "parse_verdict_text",
    "resolve_prompt_budget",
    "run_judge",
]
