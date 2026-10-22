"""LLM-judge backend for --deep mode (B2). Stdlib only — no new deps."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

JUDGE_MODEL_DEFAULT = "gpt-4o-mini"

#: Per-call HTTP timeout for judge requests. The default (120 s) matches the
#: hosted-judge era; the model-derived prompt budget (ADR 0010/0013) lets
#: local-GPU runs send much larger prompts, so the operator pins the
#: timeout explicitly for big-context endpoints via
#: PULSE_JUDGE_TIMEOUT_S (seconds, > 0; G4 measurement: a 1M-context
#: local judge needs minutes per call — the client must not time out
#: before the endpoint answers; ADR 0016).
JUDGE_TIMEOUT_DEFAULT_S = 120.0


def judge_timeout_s() -> float:
    raw = os.environ.get("PULSE_JUDGE_TIMEOUT_S", "").strip()
    if not raw:
        return JUDGE_TIMEOUT_DEFAULT_S
    try:
        val = float(raw)
    except ValueError as e:
        raise RuntimeError(f"PULSE_JUDGE_TIMEOUT_S={raw!r} is not a number") from e
    if val <= 0:
        raise RuntimeError("PULSE_JUDGE_TIMEOUT_S must be > 0 seconds")
    return val

#: Metadata keys different OpenAI-compatible local servers use to expose
#: the model's context window through the read-only /v1/models listing
#: (llama.cpp --props, llama-server, Ollama shims, vLLM). First hit wins.
_CONTEXT_KEYS = (
    "llama_cpp.n_ctx",
    "n_ctx",
    "num_ctx",
    "context_window",
    "max_context_length",
    "llama_cpp.context_window",
)

_OVERFLOW_RE = re.compile(
    r"(context.{0,40}(long|length|exceed)|too many tokens|maximum context|"
    r"prompt is too long|exceeds (the )?(model|context)|reduce (the )?(prompt|input))",
    re.IGNORECASE | re.DOTALL,
)


class JudgeContextOverflow(RuntimeError):
    """The provider REJECTED the prompt as over-long (ADR 0010: fail loud,
    never let silent server-side clipping masquerade as a verdict)."""


@dataclass
class JudgeResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


class JudgeBackend:
    def __init__(self) -> None:
        self.last_result: JudgeResult | None = None

    def judge(self, prompt: str) -> JudgeResult:
        raise NotImplementedError


def resolve_api_key() -> str:
    """PULSE_API_KEY -> OPENAI_API_KEY -> HERMES_API_KEY -> $HERMES_HOME/.env.

    Plugin-specific vars carry the plugin prefix (PULSE_); the OpenAI/Hermes
    fallbacks mirror unroll's existing key resolution. The .env fallback
    honors the active Hermes home, never a hardcoded ~/.hermes.
    """
    for var in ("PULSE_API_KEY", "OPENAI_API_KEY", "HERMES_API_KEY"):
        val = os.environ.get(var)
        if val:
            return val
    from .paths import hermes_home

    env_file = hermes_home() / ".env"
    try:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                k, sep, v = line.partition("=")
                if sep and k.strip() in ("OPENAI_API_KEY", "HERMES_API_KEY") and v.strip():
                    return v.strip().strip("'\"")
    except OSError:
        pass
    raise SystemExit("no API key: set OPENAI_API_KEY/HERMES_API_KEY or $HERMES_HOME/.env")


class OpenAIJudge(JudgeBackend):
    """Single chat-completions call, temperature 0, JSON object response."""

    def __init__(self, model: str = JUDGE_MODEL_DEFAULT, base_url: str = "") -> None:
        super().__init__()
        self.model = model or os.environ.get("PULSE_JUDGE_MODEL", JUDGE_MODEL_DEFAULT)
        env_base = os.environ.get("PULSE_JUDGE_BASE_URL", "") or os.environ.get(
            "OPENAI_BASE_URL", ""
        )
        self.base_url = (base_url or env_base).rstrip("/")

    def context_window(self) -> int | None:
        """Read-only probe of the pinned endpoint's context window via
        GET /v1/models (ADR 0010/0013; ADR 0007: never starts, stops, or
        toggles anything — the endpoint must already be live).

        Returns None when unprovable (no local base_url, unreachable, no
        metadata field); the CALLER decides how loudly to degrade. Exact
        model-id matches win over other entries' metadata.
        """
        if not self.base_url:
            return None
        try:
            req = urllib.request.Request(self.base_url + "/v1/models", method="GET")
            with urllib.request.urlopen(req, timeout=15) as resp:
                listing = json.load(resp)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        best: int | None = None
        for entry in listing.get("data", []) if isinstance(listing, dict) else []:
            if not isinstance(entry, dict):
                continue
            sources = [entry]
            for meta_key in ("meta", "metadata"):
                meta = entry.get(meta_key)
                if isinstance(meta, dict):
                    sources.append(meta)
            for src in sources:
                for key in _CONTEXT_KEYS:
                    val = src.get(key)
                    if isinstance(val, int) and val > 0:
                        if entry.get("id") == self.model:
                            return val
                        best = best or val
        return best

    def judge(self, prompt: str) -> JudgeResult:
        url = (
            (self.base_url + "/chat/completions")
            if self.base_url
            else "https://api.openai.com/v1/chat/completions"
        )
        body = {
            "model": self.model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + resolve_api_key(),
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=judge_timeout_s()) as resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:400]
            except OSError:
                detail = ""
            # Provider rejection of an over-long prompt must be LOUD —
            # a silent server-side clip would judge a window the corpus
            # stamps never saw (ADR 0010).
            if e.code in (400, 413) and _OVERFLOW_RE.search(detail):
                raise JudgeContextOverflow(
                    f"provider rejected prompt ({len(prompt)} chars) as over-long "
                    f"at {url}: {detail}"
                ) from e
            raise
        msg = payload["choices"][0]["message"]
        usage = payload.get("usage", {}) or {}
        res = JudgeResult(
            text=msg.get("content", "") or "",
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )
        self.last_result = res
        return res


class StubJudge(JudgeBackend):
    """Scripted results for offline tests. Pops in order; repeats last."""

    def __init__(self, script: list[JudgeResult]) -> None:
        super().__init__()
        self.script = script
        self.model = "stub"
        self.base_url = ""

    def judge(self, prompt: str) -> JudgeResult:
        if len(self.script) > 1:
            res = self.script.pop(0)
        else:
            res = self.script[0]
        self.last_result = res
        return res


__all__ = [
    "JUDGE_MODEL_DEFAULT",
    "JUDGE_TIMEOUT_DEFAULT_S",
    "JudgeBackend",
    "JudgeContextOverflow",
    "JudgeResult",
    "OpenAIJudge",
    "StubJudge",
    "judge_timeout_s",
    "resolve_api_key",
]
