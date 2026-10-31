from __future__ import annotations

import json
import os


def check_results(needs: dict, event: str) -> list[str]:
    changes = needs["changes"]
    if changes["result"] != "success":
        return ["Change selection did not succeed"]
    outputs = changes["outputs"]
    selected = {}
    for domain in ("python", "webui", "tui", "docker", "native"):
        value = outputs.get(f"{domain}_required")
        if value not in ("true", "false"):
            return [f"Invalid or missing selection: {domain}"]
        selected[domain] = value == "true"
    jobs = {"test": selected["python"], "windows_process": selected["python"],
            "webui_checks": selected["webui"], "webui_browser": selected["webui"],
            "webui": selected["webui"], "tui": selected["tui"], "docker": selected["docker"],
            "native": selected["native"] and event != "push",
            "windows_installers": selected["python"] and selected["native"] and event != "push"}
    errors = []
    for job, required in jobs.items():
        result = needs[job]["result"]
        if result != "success" and (required or result != "skipped"):
            errors.append(f"{job}: {'required' if required else 'unselected'}, got {result}")
    return errors


def main() -> None:
    errors = check_results(json.loads(os.environ["CHECK_RESULTS"]), os.environ["EVENT_NAME"])
    if errors:
        raise SystemExit("\n".join(errors))
    print("All selected checks passed; other checks were intentionally skipped.")


if __name__ == "__main__":
    main()
