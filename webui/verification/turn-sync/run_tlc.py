#!/usr/bin/env python3
"""Check bounded current-policy models without writing generated files into the checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


SOURCE = Path(__file__).resolve().parent
EXPECTED_LIMITS = {
    "lifecycle-failed-read-limit": (13, "Temporal properties were violated"),
    "lifecycle-fragment-id-limit": (13, "Temporal properties were violated"),
}
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
LIMIT_CASES = tuple(EXPECTED_LIMITS)
CASES = REVISED_CASES + USAGE_CASES + OPTIONAL_CASES + LIMIT_CASES
MODULES = {
    **{case: "RevisedTurnSync.tla" for case in REVISED_CASES},
    **{case: "SharedRequests.tla" for case in ("requests-one", "requests-two-no-invalidations", "requests-two")},
    "authority": "CompletionAuthority.tla",
    **{case: "CacheHandoff.tla" for case in ("handoff-fullpage-active", "handoff-fullpage-idle")},
    **{case: "UsageLifecycle.tla" for case in (
        "lifecycle-fullpage-dynamic", "lifecycle-fullpage-two-chats", *LIMIT_CASES,
    )},
}
COUNTS = re.compile(
    r"([\d,]+) states generated, ([\d,]+) distinct states found, ([\d,]+) states left on queue"
)
IMPLEMENTATION_FILES = (
    "webui/src/hooks/useReconnectRuns.ts", "webui/src/hooks/useNanobotStream.ts",
    "webui/src/lib/client-run-ledger.ts", "webui/src/lib/nanobot-client.ts",
    "webui/src/lib/canonical-run-snapshot.ts", "webui/src/lib/latest-thread-request.ts",
    "webui/src/lib/thread-transcript.ts", "webui/src/lib/webui-thread-cache.ts",
    "webui/src/components/thread/ThreadShell.tsx",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jar", required=True, type=Path, help="External official tla2tools.jar; never copied")
    parser.add_argument("--output-root", type=Path, help="New task-owned directory outside this checkout")
    parser.add_argument("--implementation-root", type=Path, help="Optional read-only TypeScript provenance; not mechanical verification")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case", action="append", choices=CASES, dest="cases", help="Repeat to select cases")
    selection.add_argument("--limits", action="store_true", help="Run ONLY current-policy missing-evidence counterexamples, not positive checks")
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
        "scope": "finite fixed-mount, dynamic lifecycle, shared-request and completion partitions; not a checked TypeScript/compositional/all-system proof",
        "jar": {"path": str(jar), "sha256": sha256(jar)},
        "source_sha256": {path.name: sha256(path) for path in inputs},
        "results": [],
    }
    if args.implementation_root:
        implementation = args.implementation_root.resolve(strict=True)
        manifest["implementation_snapshot"] = {
            "root": str(implementation),
            "sha256": {name: sha256(implementation / name) for name in IMPLEMENTATION_FILES},
            "note": "Read-only provenance, not a checked refinement of TypeScript",
        }
    print(f"Evidence: {output}", flush=True)
    unexpected = 0
    selected = args.cases or (LIMIT_CASES if args.limits else REVISED_CASES + USAGE_CASES)
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
        expected_exit, required_error = EXPECTED_LIMITS.get(case, (0, None))
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
        matched = not timed_out and actual_exit == expected_exit
        if required_error:
            matched = matched and required_error in text
        else:
            matched = (matched and "Model checking completed. No error has been found." in text
                       and counts is not None and counts[2] == 0)
        status = ("LIMITATION_COUNTEREXAMPLE" if required_error else "EXHAUSTED_NO_COUNTEREXAMPLE") if matched else "UNEXPECTED_RESULT"
        unexpected += not matched
        result = {
            "case": case, "status": status,
            "category": ("missing-evidence-limit" if case in LIMIT_CASES else
                         "expanded-usage-model" if case in USAGE_CASES + OPTIONAL_CASES else "fixed-mount-model"),
            "expected_exit": expected_exit, "actual_exit": actual_exit, "required_error": required_error,
            "timed_out": timed_out, "seconds": round(time.monotonic() - started, 3),
            "generated": counts[0] if counts else None, "distinct": counts[1] if counts else None,
            "left_on_queue": counts[2] if counts else None,
            "command": command, "cwd": str(case_dir), "log": str(case_dir / "tlc.log"),
        }
        manifest["results"].append(result)
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"{case}: {status}; exit={actual_exit}, expected={expected_exit}; distinct={result['distinct']}", flush=True)
        if not matched:
            print(text[-5000:], flush=True)
    positive_count = sum(result["status"] == "EXHAUSTED_NO_COUNTEREXAMPLE" for result in manifest["results"])
    limit_count = sum(result["status"] == "LIMITATION_COUNTEREXAMPLE" for result in manifest["results"])
    print(f"Positive exhausted checks: {positive_count}; missing-evidence counterexamples: {limit_count}; unexpected: {unexpected}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
