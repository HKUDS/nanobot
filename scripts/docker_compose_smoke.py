"""Verify Compose first boot, WebUI authentication, restart, and API readiness."""

import argparse
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(url: str, secret: str = "", body: dict[str, object] | None = None) -> tuple[int, bytes]:
    headers = {"Authorization": f"Bearer {secret}"} if secret else {}
    if body is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=3) as response:
            return response.status, response.read()
    except HTTPError as exc:
        return exc.code, exc.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Already-built Docker image")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = json.loads(subprocess.check_output(
        ["docker", "compose", "-f", str(repo / "docker-compose.yml"),
         "--profile", "cli", "config", "--format", "json"],
        text=True,
    ))
    with tempfile.TemporaryDirectory(prefix="nanobot-compose-smoke-") as temporary:
        root = Path(temporary)
        config.pop("name", None)
        for network in config.get("networks", {}).values():
            network.pop("name", None)
        for service in config["services"].values():
            service.pop("build", None)
            service.pop("container_name", None)
            service["image"] = args.image
            for port in service.get("ports", []):
                port.update(host_ip="127.0.0.1", published="0")
        compose_path = root / "compose.json"
        compose = ["docker", "compose", "-p", root.name, "-f", str(compose_path)]

        def run(*arguments: str) -> str:
            return subprocess.check_output([*compose, *arguments], text=True)

        def endpoint(service: str, port: int) -> str:
            return "http://" + run("port", service, str(port)).strip()

        def wait_for(url: str) -> None:
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    if request(url)[0] == 200:
                        return
                except (URLError, ConnectionError, TimeoutError):
                    pass
                time.sleep(1)
            raise RuntimeError(f"Endpoint did not become ready: {url}")

        for label, secret in (("generated", ""), ("custom", 'review&|"\\secret')):
            data = root / label
            data.mkdir()
            for service in config["services"].values():
                service["volumes"] = [{
                    "type": "bind", "source": str(data),
                    "target": "/home/nanobot/.nanobot",
                }]
                service["environment"].update(
                    NANOBOT_WEB_TOKEN=secret, NANOBOT_API_KEY=secret,
                )
            compose_path.write_text(json.dumps(config), encoding="utf-8")
            try:
                onboard = run("run", "--rm", "--no-deps", "-T", "nanobot-cli", "onboard")
                assert "Overwrite?" not in onboard
                assert "Created config" in onboard
                subprocess.run([
                    "docker", "run", "--rm", "--user", "1000:1000", "--entrypoint", "python",
                    "-v", f"{data}:/home/nanobot/.nanobot", args.image,
                    "-c", "from pathlib import Path; Path('/home/nanobot/.nanobot/config.json').unlink()",
                ], check=True)
                run("up", "-d")
                health = endpoint("nanobot-gateway", 18790)
                webui = endpoint("nanobot-gateway", 8765)
                wait_for(health + "/health")
                wait_for(webui + "/")
                assert set(run("ps", "--services").split()) == {"nanobot-gateway", "nanobot-api"}
                path = data / "config.json"
                saved = json.loads(path.read_text(encoding="utf-8"))
                password = saved["channels"]["websocket"]["tokenIssueSecret"]
                api_key = saved["api"]["apiKey"]
                logs = run("logs", "--no-color")
                assert logs.count("[entrypoint] initialized") == 1
                assert password in logs and api_key in logs
                if secret:
                    assert password == api_key == secret
                else:
                    assert len(password) == len(api_key) == 32 and password != api_key
                assert request(webui + "/webui/bootstrap", "wrong-password")[0] == 401
                status, body = request(webui + "/webui/bootstrap", password)
                assert status == 200 and json.loads(body)["token"]
                api = endpoint("nanobot-api", 8900)
                wait_for(api + "/health")
                for stream in (False, True):
                    status, body = request(api + "/v1/chat/completions", api_key, {
                        "messages": [{"role": "user", "content": "hello"}], "stream": stream,
                    })
                    assert status == 503 and json.loads(body)["error"]["type"] == "configuration_error"
                assert request(api + "/v1/models")[0] == 401
                print(f"PASS {label}: both default services, authenticated WebUI, API model-setup errors")

                # Configure a provider without making external model requests.
                saved["providers"]["custom"] = {
                    "apiKey": "smoke-provider-key", "apiBase": "http://127.0.0.1:9/v1",
                }
                saved["agents"]["defaults"].update(provider="custom", model="smoke-model")
                subprocess.run([
                    *compose, "exec", "-T", "--user", "1000:1000", "nanobot-gateway", "python", "-c",
                    "import json, sys; from pathlib import Path; "
                    "from nanobot.config.schema import Config; from nanobot.config.loader import save_config; "
                    "save_config(Config.model_validate(json.load(sys.stdin)), "
                    "Path('/home/nanobot/.nanobot/config.json'))",
                ], input=json.dumps(saved), text=True, check=True)
                previous = path.read_bytes()
                for service in config["services"].values():
                    service["environment"].update(
                        NANOBOT_WEB_TOKEN="changed-env", NANOBOT_API_KEY="changed-env",
                    )
                compose_path.write_text(json.dumps(config), encoding="utf-8")
                run("up", "-d", "--force-recreate", "nanobot-gateway")
                webui = endpoint("nanobot-gateway", 8765)
                wait_for(webui + "/")
                assert path.read_bytes() == previous
                assert request(webui + "/webui/bootstrap", password)[0] == 200
                assert request(webui + "/webui/bootstrap", "changed-env")[0] == 401
                print(f"PASS {label}: recreate preserves provider settings and credentials")

                run("up", "-d", "--force-recreate", "nanobot-api")
                api = endpoint("nanobot-api", 8900)
                deadline = time.monotonic() + 60
                while True:
                    try:
                        status, _body = request(api + "/v1/models", api_key)
                        if status == 200:
                            break
                    except (URLError, ConnectionError, TimeoutError):
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Configured API did not start")
                    time.sleep(1)
                assert request(api + "/v1/models")[0] == 401
                print(f"PASS {label}: configured API starts and requires its persisted key")
            except Exception:
                print(run("logs", "--no-color", "--tail", "80"), flush=True)
                raise
            finally:
                subprocess.run([*compose, "down", "--volumes"], check=True)
                # The non-root container owns the bind mount on Linux.
                if os.name != "nt":
                    subprocess.run([
                        "docker", "run", "--rm", "--entrypoint", "chown",
                        "-v", f"{data}:/data", args.image,
                        "-R", f"{os.getuid()}:{os.getgid()}", "/data",
                    ], check=True)

        readonly = root / "readonly"
        readonly.mkdir()
        result = subprocess.run([
            "docker", "run", "--rm", "--read-only",
            "-e", "NANOBOT_DOCKER_BOOTSTRAP=1",
            "-v", f"{readonly}:/home/nanobot/.nanobot:ro", args.image, "status",
        ], capture_output=True, text=True)
        assert result.returncode == 1, result.stdout + result.stderr
        assert not (readonly / "config.json").exists()
        assert "password:" not in result.stdout
        print("PASS read-only mount: initialization fails without a partial config or success message")


if __name__ == "__main__":
    main()
