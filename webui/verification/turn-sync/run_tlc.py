#!/usr/bin/env python3
"""Check bounded turn-sync models without writing generated files into the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

SOURCE = Path(__file__).resolve().parent
ATTACH_CASE = "attach-reconciliation"
REVISED_CASES = (
    "revised-mounted", "revised-unmounted",
    "revised-mounted-fragments", "revised-unmounted-fragments",
    "revised-mounted-live", "revised-unmounted-live",
)
USAGE_CASES = (
    "requests-two-no-invalidations", "requests-one", "authority",
    "lifecycle-fullpage-dynamic", "handoff-fullpage-active", "handoff-fullpage-idle",
)
# Larger products are reproducible explicitly, not claimed exhausted by defaults.
OPTIONAL_CASES = ("requests-two", "lifecycle-fullpage-two-chats")
DEFAULT_CASES = REVISED_CASES + USAGE_CASES + (ATTACH_CASE,)
CASES = DEFAULT_CASES + OPTIONAL_CASES
MODULES = {
    **{case: "RevisedTurnSync.tla" for case in REVISED_CASES},
    **{case: "SharedRequests.tla" for case in ("requests-one", "requests-two-no-invalidations", "requests-two")},
    "authority": "CompletionAuthority.tla",
    **{case: "CacheHandoff.tla" for case in ("handoff-fullpage-active", "handoff-fullpage-idle")},
    "lifecycle-fullpage-dynamic": "UsageLifecycle.tla",
    "lifecycle-fullpage-two-chats": "UsageLifecycle.tla",
    ATTACH_CASE: "AttachReconciliation.tla",
}
COUNTS = re.compile(
    r"([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue"
)
IMPLEMENTATION_FILES = (
    "webui/src/hooks/useReconnectRuns.ts", "webui/src/hooks/useNanobotStream.ts",
    "webui/src/lib/client-run-ledger.ts", "webui/src/lib/nanobot-client.ts",
    "webui/src/lib/canonical-run-snapshot.ts", "webui/src/lib/latest-thread-request.ts",
    "webui/src/lib/thread-transcript.ts", "webui/src/lib/webui-thread-cache.ts",
    "webui/src/components/thread/ThreadShell.tsx", "webui/src/lib/types.ts",
    "nanobot/session/webui_turns.py", "nanobot/webui/inbound_commands.py",
    "nanobot/webui/session_projection.py", "nanobot/webui/outbound_delivery.py",
    "nanobot/webui/ws_http.py", "nanobot/channels/websocket/runtime.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="External official tla2tools.jar; never copied")
    parser.add_argument("--output-root", type=Path, help="New task-owned directory outside this checkout")
    parser.add_argument("--implementation-root", type=Path, help="Optional read-only implementation provenance; not mechanical verification")
    parser.add_argument("--case", action="append", choices=CASES, dest="cases", help="Repeat to select cases")
    parser.add_argument("--java", default="java")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--heap-mb", type=int, default=1536)
    parser.add_argument("--timeout-seconds", type=int, default=600, help="Per-case hard timeout")
    args = parser.parse_args()
    jar = args.jar.resolve(strict=True)
    if args.workers < 1 or args.heap_mb < 64 or args.timeout_seconds < 1:
        parser.error("workers/timeout must be positive and heap must be at least 64 MiB")
    checkout = next((path for path in SOURCE.parents if (path / ".git").exists()), SOURCE)
    if args.output_root is None:
        output = Path(tempfile.mkdtemp(prefix="nanobot-turn-sync-tlc-"))
    else:
        output = args.output_root.resolve()
        if output == checkout or checkout in output.parents:
            parser.error("output-root must be outside the checkout")
        output.mkdir(parents=True, exist_ok=False)
    inputs = sorted((*SOURCE.glob("*.tla"), *SOURCE.glob("*.cfg")))
    manifest = {
        "scope": "finite history, request, completion and attach partitions; not a checked implementation/compositional proof",
        "jar": {"path": str(jar), "sha256": sha256(jar)},
        "source_sha256": {path.name: sha256(path) for path in inputs},
        "results": [],
    }
    if args.implementation_root:
        implementation = args.implementation_root.resolve(strict=True)
        manifest["implementation_snapshot"] = {
            "root": str(implementation),
            "sha256": {name: sha256(implementation / name) for name in IMPLEMENTATION_FILES},
            "note": "Read-only provenance, not a checked refinement of implementation code",
        }
    print(f"Evidence: {output}", flush=True)
    failed = 0
    selected = args.cases or DEFAULT_CASES
    for case in selected:
        case_dir = output / case
        case_dir.mkdir()
        # TLC can create trace modules on failure. Run an immutable input copy
        # outside the checkout so even unexpected outputs stay task-owned.
        for path in inputs:
            shutil.copyfile(path, case_dir / path.name)
        module = MODULES[case]
        temp = case_dir / "temp"
        temp.mkdir()
        command = [
            args.java, f"-Xmx{args.heap_mb}m", "-XX:+UseParallelGC", f"-Djava.io.tmpdir={temp}", "-cp", str(jar),
            "tlc2.TLC", "-workers", str(args.workers), "-config", f"{case}.cfg",
            "-metadir", str(case_dir / "states"), module,
        ]
        started = time.monotonic()
        timed_out = False
        try:
            run = subprocess.run(
                command, cwd=case_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=args.timeout_seconds, check=False,
            )
            actual_exit, text = run.returncode, run.stdout
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            actual_exit = None
            text = exc.stdout or b""
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
        except OSError as exc:
            actual_exit, text = None, str(exc)
        (case_dir / "tlc.log").write_text(text, encoding="utf-8")
        matches = list(COUNTS.finditer(text))
        counts = tuple(int(value.replace(",", "")) for value in matches[-1].groups()) if matches else None
        exhausted = (
            actual_exit == 0 and "Model checking completed. No error has been found." in text
            and counts is not None and counts[2] == 0
        )
        status = "EXHAUSTED_NO_COUNTEREXAMPLE" if exhausted else "UNEXPECTED_RESULT"
        result = {
            "case": case, "status": status,
            "category": ("attach-model" if case == ATTACH_CASE else
                         "expanded-usage-model" if case in USAGE_CASES + OPTIONAL_CASES else "fixed-mount-model"),
            "actual_exit": actual_exit,
            "timed_out": timed_out, "seconds": round(time.monotonic() - started, 3),
            "generated": counts[0] if counts else None, "distinct": counts[1] if counts else None,
            "left_on_queue": counts[2] if counts else None,
            "command": command, "cwd": str(case_dir), "log": str(case_dir / "tlc.log"),
        }
        manifest["results"].append(result)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{case}: {status}; exit={actual_exit}; distinct={result['distinct']}", flush=True)
        if not exhausted:
            failed += 1
            print(text[-5000:], flush=True)
    print(f"Exhausted checks: {len(selected) - failed}; failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
