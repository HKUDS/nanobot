# Session inbox lifecycle model

`CombinedLifecycle.tla` models shutdown admission, worker lifetime, and control handoff across two session keys, with at most one control and one replacement per key. It checks that shutdown waits for all workers and controls before closing shared resources, and that shutdown eventually finishes if workers and controls can complete their cleanup.

## Run the checks

Use [TLC 2.19 (TLA+ v1.7.4)](https://github.com/tlaplus/tlaplus/releases/tag/v1.7.4). Run these commands from a scratch copy of this directory so TLC output stays out of the source tree. Replace `/path/to/tla2tools.jar` with the path to the downloaded JAR.

```sh
java -XX:+UseParallelGC -cp "/path/to/tla2tools.jar" tlc2.TLC -config combined-final.cfg CombinedLifecycle.tla
java -XX:+UseParallelGC -cp "/path/to/tla2tools.jar" tlc2.TLC -config combined-baseline.cfg CombinedLifecycle.tla
```

- `combined-final.cfg` checks the current model and exhausts 333 distinct states without a violation.
- `combined-baseline.cfg` disables joining in-flight controls. It must violate `CloseJoinsAllOwners`: shutdown can close resources while a control is still running after its worker exits.

The Python replay is `test_shutdown_joins_control_when_no_worker_remains` in [the inbox regression tests](../../tests/agent/test_session_inbox_controls.py). The same tests cover automation arriving during queue retirement and replacement workers waiting for cleanup. The model does not verify the Python implementation and excludes direct SDK calls, forced shutdown deadlines, subprocess termination, and SQLite recovery. The smaller models used during diagnosis are preserved in [the original PR snapshot](https://github.com/HKUDS/nanobot/tree/f552eccf358cd5bbe5f295e6138921fb0d425475/verification/async-session-stop).
