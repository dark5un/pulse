#!/usr/bin/env python3
"""Loud-failure + cache-resume drill (deep-judge gate M0 / CW-3, v2 plane).

Proves the batch judge contract end to end WITHOUT touching any real model
service: a throwaway localhost HTTP fake judge answers for snapshot #1, the
port is then CLOSED, and snapshot #2 must (a) make `pulse agreement` exit
2 naming the failed snapshot, (b) leave snapshot #1's verdict flushed to
the cache (per-record flush), and (c) a rerun with a fresh fake endpoint
must resume from cache — exactly one new judge call.

CW-5a moved this onto the manifest data plane: synthetic snapshots + a
synthetic run manifest in a temp dir (still fully hermetic; the missing-
corpus refusal happens before ANY endpoint contact).

Usage:  uv run python scripts/drill_judge_failure.py
Exits 0 only when every assertion in the drill holds. Tests never hit the
network; 127.0.0.1 fake servers + closed ports only.
"""

import hashlib
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

from pulse.signals_deep import PROMPT_VERSION, REDACT_VERSION

VERDICT_TEXT = json.dumps({"prompt_version": PROMPT_VERSION, "verdicts": []})


def write_snapshot(d: Path, session_id: str) -> dict:
    """One eligible synthetic snapshot (chat task type) -> manifest item."""
    messages = [
        {"role": "user", "content": f"fix the python api bug {i} and add a test"}
        for i in range(3)
    ] + [
        {"role": "assistant", "content": f"answer {i}: patched and ran tests"}
        for i in range(2)
    ]
    payload = {
        "schema": "pulse-corpus-snapshot/v1",
        "session_id": session_id,
        "model": "m-drill",
        "started_at": "2026-10-01T00:00:00+00:00",
        "ended_at": "2026-10-01T01:00:00+00:00",
        "task_type": "chat",
        "message_count": len(messages),
        "messages": messages,
        "redact_version": REDACT_VERSION,
        "approx_truncated": False,
        "advisory": {
            "note": "advisory only",
            "pulse_version": "drill",
            "det_signals": [],
            "det_pairs": {"correction_chain": 0, "premature_stop": 0},
        },
    }
    content = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    name = f"{digest[:16]}.json"
    (d / name).write_text(content, encoding="utf-8")
    return {
        "path": name,
        "sha256": digest,
        "session_id": session_id,
        "stratum": "core",
        "task_type": "chat",
        "model": "m-drill",
        "approx_truncated": False,
        "det_pairs": {"correction_chain": 0, "premature_stop": 0},
    }


def write_manifest(d: Path, items: list[dict]) -> Path:
    manifest = {
        "schema": "pulse-corpus-manifest/v1",
        "kind": "pulse-corpus-selection",
        "variable": "drill",
        "timestamp": "2026-10-22T00:00:00+00:00",
        "pulse_version": "drill",
        "seed": 1,
        "corpus_dir": str(d),
        "redact_version": REDACT_VERSION,
        "prompt_version": PROMPT_VERSION,
        "counts": {},
        "params": {},
        "judge": {
            "lane": "api",
            "model": "drill-stub",
            "base_url": "",
            "model_checkpoint": None,
            "context_window": None,
        },
        "items": items,
    }
    path = d / "manifest.json"
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
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


def run_agreement(manifest: Path, cache: Path, base_url: str, limit: int) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "src")
    env["PULSE_API_KEY"] = "drill-dummy-key-never-sent-anywhere-real"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pulse",
            "agreement",
            "--manifest",
            str(manifest),
            "--limit",
            str(limit),
            "--cache",
            str(cache),
            "--judge-base-url",
            base_url,
            "--judge-context",
            "16384",
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
    items = [write_snapshot(corpus, "t1"), write_snapshot(corpus, "t2")]
    manifest = write_manifest(corpus, items)

    print("step 0: deleted snapshot fails LOUD before any endpoint contact")
    gone = corpus / items[0]["path"]
    backup = gone.read_text()
    gone.unlink()
    r0 = run_agreement(manifest, cache, "http://127.0.0.1:1", limit=2)
    gone.write_text(backup, encoding="utf-8")
    check(
        "missing snapshot -> exit 2 'K of N missing; re-run pulse corpus export'",
        r0.returncode == 2 and "1 of 2 missing; re-run pulse corpus export" in r0.stderr,
        f"rc={r0.returncode} err={r0.stderr[-300:]}",
    )

    print("step 1: fake judge live, judge snapshot #1")
    fake = FakeJudge()
    url = fake.start()
    r1 = run_agreement(manifest, cache, url, limit=1)
    fake.stop()
    check("snapshot #1 judged over localhost", fake.requests == 1 and len(json.loads(cache.read_text())) == 1,
          f"rc={r1.returncode} reqs={fake.requests} err={r1.stderr[-200:]}")
    check("model-derived budget stated", "judge prompt budget:" in r1.stderr
          and "source=explicit" in r1.stderr, f"stderr={r1.stderr[-300:]}")
    check("small-n cells REFUSE the gate, never a bare FAIL (ADR 0009)",
          r1.returncode == 2 and "gate: NOT EVALUATED" in r1.stdout and "gate: FAIL" not in r1.stdout,
          f"rc={r1.returncode} out={r1.stdout[-400:]}")
    check("distribution block printed before any kappa",
          "── kappa cell: correction_chain × core" in r1.stdout
          and "marginals:" in r1.stdout and "confusion:" in r1.stdout,
          f"out={r1.stdout[-400:]}")

    print("step 2: port CLOSED, snapshot #2 must fail LOUD (exit 2, names the snapshot)")
    r2 = run_agreement(manifest, cache, url, limit=2)
    check("nonzero exit on judge call failure", r2.returncode == 2, f"rc={r2.returncode}")
    check(
        "failure names the failed snapshot",
        "judge call failure on snapshot" in r2.stderr and items[1]["path"] in r2.stderr,
        f"stderr={r2.stderr[-300:]}",
    )
    check(
        "cache intact through the failure (per-record flush)",
        len(json.loads(cache.read_text())) == 1,
    )

    print("step 3: fresh fake endpoint, rerun resumes from cache")
    fake2 = FakeJudge()
    url = fake2.start()
    r3 = run_agreement(manifest, cache, url, limit=2)
    fake2.stop()
    check("rerun completes after resume", r3.returncode == 2, f"rc={r3.returncode} err={r3.stderr[-200:]}")
    check("only the un-judged snapshot hit the endpoint", fake2.requests == 1, f"reqs={fake2.requests}")
    check("cache now holds both verdicts", len(json.loads(cache.read_text())) == 2)
    check("resume visible in output", "cache hits: 1/2" in r3.stdout, f"out={r3.stdout[-300:]}")

    print("DRILL PASS: loud failure + per-record flush + cache resume verified" if not fails
          else f"DRILL FAIL: {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
