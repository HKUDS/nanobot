# External gateway supervisor

`python -m nanobot.operations.supervisor --config /absolute/config.json` performs
one check. The repository's `deploy/nanobot-supervisor.timer` schedules it every
ten minutes and after boot. The service runs outside the gateway process.

The supervisor checks systemd's current MainPID and the loopback `/health`
endpoint twice before treating an HTTP failure as persistent. When goal recovery
is enabled, it also verifies a recent completed scan or startup heartbeat from
that same process. A stale heartbeat from an earlier gateway is not liveness.

After the startup grace period, a stopped gateway, failed readiness check, or
expired goal scanner triggers an asynchronous systemd restart. The native goal
watchdog then continues eligible saved goals under the existing session locks.
Paused goals, pending approvals, and tools with unknown external effects retain
their existing holds. This supervisor never replays a tool or creates a new goal.

Restart attempts are saved before the systemd request and limited to three per
hour. The state and reason are saved in `operations/supervisor.json` beside the
gateway config. An exhausted restart budget is reported as `held`; it is not
reported as successful recovery.

For planned maintenance, `--pause` suspends supervisor intervention persistently;
`--resume` re-enables checks. These flags do not start or stop the gateway and do
not erase the restart budget. The health listener must be reachable on this
host's `127.0.0.1` using `gateway.port`; SSH/WireGuard carry remote client access.

The `.service.in` template requires installer substitution of the absolute
Python interpreter, config path, and gateway unit. Do not install that unresolved
template directly.
