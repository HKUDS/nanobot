"""Hatch build hook that bundles the webui (Vite) into nanobot/web/dist.

Triggered automatically by `python -m build` (and any other hatch-driven build)
so published wheels and sdists ship a fresh webui without requiring developers
to remember `cd webui && bun run build` beforehand.

Behaviour:

- Skips for editable installs (`pip install -e .`). Editable mode is for Python
  development; webui contributors use `cd webui && bun run dev` (Vite HMR) and
  do not need a packaged `dist/`.
- No-op when `webui/package.json` is absent (e.g. installing from an sdist that
  already contains a prebuilt `nanobot/web/dist/`).
- Skips when `NANOBOT_SKIP_WEBUI_BUILD=1` is set.
- Skips when `nanobot/web/dist/index.html` already exists, unless
  `NANOBOT_FORCE_WEBUI_BUILD=1` is set.
- Uses `bun` when available, otherwise falls back to `npm`. The chosen tool
  performs `install` followed by `run build`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebUIBuildHook(BuildHookInterface):
    PLUGIN_NAME = "webui-build"

    def initialize(self, version: str, build_data: dict) -> None:  # noqa: D401
        root = Path(self.root)
        webui_dir = root / "webui"
        package_json = webui_dir / "package.json"
        dist_dir = root / "nanobot" / "web" / "dist"
        index_html = dist_dir / "index.html"

        # `pip install -e .` builds an editable wheel; skip the (slow) webui
        # bundle since editable installs target Python development and webui
        # work uses `bun run dev` instead.
        if self.target_name == "wheel" and version == "editable":
            self.app.display_info(
                "[webui-build] skipped for editable install "
                "(use `cd webui && bun run build` to bundle webui manually)"
            )
            return

        if os.environ.get("NANOBOT_SKIP_WEBUI_BUILD") == "1":
            self.app.display_info("[webui-build] skipped via NANOBOT_SKIP_WEBUI_BUILD=1")
            return

        if not package_json.is_file():
            self.app.display_info(
                "[webui-build] no webui/ source tree, assuming prebuilt nanobot/web/dist/"
            )
            return

        force = os.environ.get("NANOBOT_FORCE_WEBUI_BUILD") == "1"
        if index_html.is_file() and not force:
            self.app.display_info(
                f"[webui-build] reusing existing build at {dist_dir} "
                "(set NANOBOT_FORCE_WEBUI_BUILD=1 to rebuild)"
            )
            return

        runner = self._pick_runner()
        if runner is None:
            raise RuntimeError(
                "[webui-build] neither `bun` nor `npm` is available on PATH; "
                "install one or set NANOBOT_SKIP_WEBUI_BUILD=1 to bypass."
            )

        self.app.display_info(f"[webui-build] using {runner} to build webui")
        self._run([runner, "install"], cwd=webui_dir)
        self._run([runner, "run", "build"], cwd=webui_dir)

        if not index_html.is_file():
            raise RuntimeError(
                f"[webui-build] build finished but {index_html} is missing; "
                "check webui/vite.config.ts outDir."
            )
        self.app.display_info(f"[webui-build] webui ready at {dist_dir}")

    @staticmethod
    def _pick_runner() -> str | None:
        for candidate in ("bun", "npm"):
            if shutil.which(candidate):
                return candidate
        return None

    def _run(self, cmd: list[str], *, cwd: Path) -> None:
        self.app.display_info(f"[webui-build] $ {' '.join(cmd)} (cwd={cwd})")
        try:
            subprocess.run(cmd, cwd=cwd, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"[webui-build] command failed ({exc.returncode}): {' '.join(cmd)}"
            ) from exc
