#!/usr/bin/env python3
"""Loud-failure + cache-resume drill (deep-judge gate M0 / CW-3).

Proves the batch judge contract end to end WITHOUT touching any real model
service: a throwaway localhost HTTP fake judge answers for trace #1, the
port is then CLOSED, and trace #2 must (a) make `pulse agreement` exit
nonzero naming the failed trace, (b) leave trace #1's verdict flushed to
the cache (per-record flush), and (c) a rerun with a fresh fake endpoint
must resume from cache — exactly one new judge call.

Usage:  uv run python scripts/drill_judge_failure.py
Exits 0 only when every assertion in the drill holds. Tests never hit the
network; 127.0.0.1 fake servers + closed ports only.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pulse.signals_deep import PROMPT_VERSION

VERDICT_TEXT = json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": []})


def write_trace(d: Path, name: str) -> Path:
    lines = [
        f'SESSION_ID = "{name}"',
        'MODEL = "m-drill"',
        'COST = {"cost_usd": 0.01}',
        "TIMELINE = [",
        ' {"kind": "user_message", "text": "user question 0 about python code"},',
        ' {"kind": "user_message", "text": "user question 1 about python code"},',
        ' {"kind": "user_message", "text": "user question 2 about python code"},',
        ' {"kind": "llm_call", "text": "assistant answer 0 with enough words here"},',
        ' {"kind": "llm_call", "text": "assistant answer 1 with enough words here"}',
        "]",
    ]
    path = d / f"{name}.py"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class FakeJudge:
    """Localhost chat-completions stand-in; counts requests."""

    def __init__(self) -> None:
        self.requests = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                owner.requests += 1
                body = json.dumps(
                    {
                        "choices": [{"message": {"role": "assistant", "content": VERDICT_TEXT}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):  # silence
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> str:
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def run_agreement(corpus: Path, cache: Path, base_url: str, limit: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["PULSE_API_KEY"] = "drill-dummy-key-never-sent-anywhere-real"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pulse",
            "agreement",
            "--corpus",
            str(corpus),
            "--limit",
            str(limit),
            "--cache",
            str(cache),
            "--judge-base-url",
            base_url,
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=120,
    )


def main() -> int:
    fails: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))
        if not ok:
            fails.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="pulse-drill-"))
    corpus, cache = tmp / "corpus", tmp / "cache.json"
    corpus.mkdir()
    write_trace(corpus, "t1")
    write_trace(corpus, "t2")

    print("step 1: fake judge live, judge trace #1")
    fake = FakeJudge()
    url = fake.start()
    r1 = run_agreement(corpus, cache, url, limit=1)
    fake.stop()
    check("trace #1 judged over localhost", r1.returncode == 1 and fake.requests == 1,
          f"rc={r1.returncode} reqs={fake.requests} err={r1.stderr[-200:]}")
    entries_after_1 = len(json.loads(cache.read_text())) if cache.exists() else 0
    check("cache holds 1 flushed verdict", entries_after_1 == 1, f"entries={entries_after_1}")

    print("step 2: port CLOSED, trace #2 must fail LOUD (exit 2, names the trace)")
    r2 = run_agreement(corpus, cache, url, limit=2)
    check("nonzero exit on judge call failure", r2.returncode == 2, f"rc={r2.returncode}")
    check("failure names the failed trace", "t2.py" in r2.stderr and "judge call failure" in r2.stderr,
          f"stderr={r2.stderr[-300:]}")
    check(
        "cache intact through the failure (per-record flush)",
        len(json.loads(cache.read_text())) == 1,
    )

    print("step 3: fresh fake endpoint, rerun resumes from cache")
    fake2 = FakeJudge()
    url = fake2.start()
    r3 = run_agreement(corpus, cache, url, limit=2)
    fake2.stop()
    check("rerun completes after resume", r3.returncode == 1, f"rc={r3.returncode} err={r3.stderr[-200:]}")
    check("only the un-judged trace hit the endpoint", fake2.requests == 1, f"reqs={fake2.requests}")
    check("cache now holds both verdicts", len(json.loads(cache.read_text())) == 2)

    print("DRILL PASS: loud failure + per-record flush + cache resume verified" if not fails
          else f"DRILL FAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
