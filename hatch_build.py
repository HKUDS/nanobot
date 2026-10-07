"""Hatch build hook that bundles the webui (Vite) into nanobot/web/dist.

Triggered automatically by `python -m build` (and any other hatch-driven build)
so published wheels and sdists ship a fresh webui without requiring developers
to remember `cd webui && bun run build` beforehand.

Behavior:

- Skips for editable installs (`pip install -e .`). Editable mode is for Python
  development; webui contributors use `cd webui && bun run dev` (Vite HMR) and
  do not need a packaged `dist/`.
- No-op when `webui/package.json` is absent (e.g. installing from an sdist that
  already contains a prebuilt `nanobot/web/dist/`).
- Skips when `NANOBOT_SKIP_WEBUI_BUILD=1` is set.
- Reuses `nanobot/web/dist/` only when it is already fresh, unless
  `NANOBOT_FORCE_WEBUI_BUILD=1` is set.
- Uses `bun` when available, otherwise falls back to `npm`. The chosen tool
  performs `install` followed by `run build`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import ModuleType

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _load_webui_build_module() -> ModuleType:
    from nanobot.webui import build as webui_build

    return webui_build


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

        webui_build = _load_webui_build_module()
        status = webui_build.inspect_webui_bundle(source_dir=webui_dir, dist_dir=dist_dir)
        force = os.environ.get("NANOBOT_FORCE_WEBUI_BUILD") == "1"
        if not status.needs_build and not force:
            self.app.display_info(
                f"[webui-build] reusing existing build at {dist_dir} "
                "(already fresh; set NANOBOT_FORCE_WEBUI_BUILD=1 to rebuild)"
            )
            return

        if status.needs_build and not force:
            self.app.display_info(
                f"[webui-build] {webui_build.describe_webui_bundle_status(status)}"
            )

        try:
            webui_build.build_webui_bundle(
                source_dir=webui_dir,
                dist_dir=dist_dir,
                output=self.app.display_info,
            )
        except webui_build.WebUIBuildError as exc:
            raise RuntimeError(
                "[webui-build] "
                f"{exc}. Install `bun` or `npm`, or set NANOBOT_SKIP_WEBUI_BUILD=1 to bypass."
            ) from exc

        if not index_html.is_file():
            raise RuntimeError(
                f"[webui-build] build finished but {index_html} is missing; "
                "check webui/vite.config.ts outDir."
            )
        self.app.display_info(f"[webui-build] webui ready at {dist_dir}")
