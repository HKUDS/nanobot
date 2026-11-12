"""Replace real Docker images while retaining isolated config and chat data.

The image owner performs the upgrade, not nanobot's in-place updater. Reuse the
packaged-update data contract inside each image; never install into a container.
"""

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote


def product_phase(phase: str, version: str) -> None:
    import nanobot
    from nanobot.gateway.runtime import GatewayInstance, GatewayRuntime

    spec = importlib.util.spec_from_file_location("probe", Path(__file__).with_name("verify_packaged_update.py"))
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    root = Path("/home/nanobot/.nanobot/acceptance")
    assert nanobot.__version__ == version
    assert Path(nanobot.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())

    def ready(root, expected):
        instance = GatewayInstance.resolve(config_path=root / "account/.nanobot/config.json")
        runtime = GatewayRuntime(paths=instance.paths)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = runtime.status()
            if status.running and status.ready:
                assert nanobot.__version__ == expected and status.command[0] == sys.executable
                terminal = probe.request(root, "/webui/terminal")
                assert terminal["protocolVersion"] == 1 and terminal["gatewayId"]
                return SimpleNamespace(run_id=f"{version}:{status.pid}:{status.started_at}")
            time.sleep(0.2)
        raise RuntimeError("Installed container gateway did not become ready")

    def history(root, key):
        rows = probe.request(root, "/api/sessions")["sessions"]
        assert key in {row["key"] for row in rows}
        response = probe.request(root, "/api/sessions/" + quote(key, safe="") + "/webui-thread")
        # Released 0.3.5 returns rendered messages; 0.4 returns events. These
        # command-only fixtures compare visible text plus completed-turn identity.
        if "messages" in response:
            events = []
            for message in response["messages"]:
                assert message["role"] in {"user", "assistant"}
                events.append({"event": "user" if message["role"] == "user" else "message",
                               "text": message["content"]})
        else:
            events = [{"event": "user" if event["event"] == "user_message" else event["event"],
                       "text": event["text"]} for event in response["events"]
                      if event["event"] in {"user", "user_message", "message"}]
        assert events
        return {"events": events, "completed_turn_ids": response["completed_turn_ids"]}

    probe.ready, probe.history = ready, history
    try:
        if phase == "seed":
            root.mkdir()
            probe.write(root / "case.json", {"dock": False, "baseline_version": version})
            probe.seed(root)
            probe.snapshot(root)
        else:
            probe.gateway(root, "--background")
            assert probe.verify_data(root, version)
    finally:
        probe.gateway(root, "stop")


def run(args) -> dict:
    scripts = Path(__file__).resolve().parent
    images = {key: json.loads(subprocess.check_output(
        ["docker", "image", "inspect", image], text=True,
    ))[0]["Id"] for key, image in (("baseline", args.baseline_image), ("target", args.image))}
    with tempfile.TemporaryDirectory(prefix="nanobot-docker-upgrade-") as temporary:
        root = Path(temporary)
        volume = root.name
        container = volume + "-run"
        subprocess.run(["docker", "volume", "create", volume], check=True, capture_output=True)
        try:
            # Initialize ownership of this newly-created volume only. Both
            # product phases execute as the image's non-root user.
            subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", "chown",
                            "-v", volume + ":/data", images["target"], "1000:1000", "/data"], check=True)
            for phase, image, version in (("seed", images["baseline"], args.baseline_version),
                                           ("verify", images["target"], args.version)):
                # Logs may contain fixture credentials; only the structured
                # result is published. No host home/config/workspace is mounted.
                with (root / (phase + ".log")).open("w") as log:
                    result = subprocess.run([
                        "docker", "run", "--rm", "--name", container, "--network", "none",
                        "--user", "1000:1000", "--cap-drop", "ALL",
                        "--security-opt", "no-new-privileges:true", "--entrypoint", "python",
                        "-v", volume + ":/home/nanobot/.nanobot",
                        "-v", str(scripts) + ":/probe:ro", image,
                        "-I", "/probe/docker_upgrade_smoke.py", "--phase", phase, "--version", version,
                    ], stdout=log, stderr=log, timeout=240)
                    if result.returncode:
                        # Emit diagnostics without dumping HTTP tokens/config.
                        lines = (root / (phase + ".log")).read_text().splitlines()
                        frames = [line for line in lines if line.lstrip().startswith('File "')]
                        print("\n".join(frames[-12:]), file=sys.stderr)
                        raise RuntimeError(f"Docker upgrade {phase} failed; container exit {result.returncode}")
        finally:
            subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["docker", "volume", "rm", volume], check=True, capture_output=True)
    return {"source_commit": args.source_commit, "baseline_image": images["baseline"], "target_image": images["target"],
            "baseline_version": args.baseline_version, "target_version": args.version,
            "probe_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "same_volume_image_replacement": True, "config_and_legacy_bytes_preserved": True,
            "authenticated_history_preserved": True, "canonical_only_and_display_only_preserved": True,
            "continued_write_and_second_start": True, "non_root": True, "no_external_network": True,
            "container_and_volume_cleaned": True, "in_place_update_or_automatic_rollback": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image")
    parser.add_argument("--baseline-image")
    parser.add_argument("--baseline-version", default="0.3.5")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--phase", choices=("seed", "verify"), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.phase:
        product_phase(args.phase, args.version)
        return
    if not args.image or not args.baseline_image or not args.output or not args.source_commit:
        parser.error("--image, --baseline-image, --source-commit and --output are required")
    result = run(args)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("PASS Docker: real old-image upgrade retains data, authenticated reads, writes and second start")


if __name__ == "__main__":
    main()
