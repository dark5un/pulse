"""LLM-judge backend for --deep mode (B2). Stdlib only — no new deps."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

JUDGE_MODEL_DEFAULT = "gpt-4o-mini"


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
    """PULSE_API_KEY -> OPENAI_API_KEY -> HERMES_API_KEY -> ~/.hermes/.env.

    Plugin-specific vars carry the plugin prefix (PULSE_); the OpenAI/Hermes
    fallbacks mirror unroll's existing key resolution.
    """
    for var in ("PULSE_API_KEY", "OPENAI_API_KEY", "HERMES_API_KEY"):
        val = os.environ.get(var)
        if val:
            return val
    env_file = Path.home() / ".hermes" / ".env"
    try:
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                k, sep, v = line.partition("=")
                if sep and k.strip() in ("OPENAI_API_KEY", "HERMES_API_KEY") and v.strip():
                    return v.strip().strip("'\"")
    except OSError:
        pass
    raise SystemExit("no API key: set OPENAI_API_KEY/HERMES_API_KEY or ~/.hermes/.env")


class OpenAIJudge(JudgeBackend):
    """Single chat-completions call, temperature 0, JSON object response."""

    def __init__(self, model: str = JUDGE_MODEL_DEFAULT, base_url: str = "") -> None:
        super().__init__()
        self.model = model or os.environ.get("PULSE_JUDGE_MODEL", JUDGE_MODEL_DEFAULT)
        env_base = os.environ.get("PULSE_JUDGE_BASE_URL", "") or os.environ.get(
            "OPENAI_BASE_URL", ""
        )
        self.base_url = (base_url or env_base).rstrip("/")

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
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.load(resp)
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

    def judge(self, prompt: str) -> JudgeResult:
        if len(self.script) > 1:
            res = self.script.pop(0)
        else:
            res = self.script[0]
        self.last_result = res
        return res


__all__ = [
    "JUDGE_MODEL_DEFAULT",
    "JudgeBackend",
    "JudgeResult",
    "OpenAIJudge",
    "StubJudge",
    "resolve_api_key",
]
