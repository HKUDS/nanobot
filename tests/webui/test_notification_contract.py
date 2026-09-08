import importlib.util
import io
import json
import tarfile
from pathlib import Path

from nanobot.events import ContextCompactionEvent, RecoveryStateEvent, RetryStatusEvent
from nanobot.webui.outbound_wire import project_notification

ROOT = Path(__file__).resolve().parents[2]


def test_wire_fixtures_are_real_python_projections(monkeypatch):
    monkeypatch.setattr("nanobot.webui.outbound_wire.time.time", lambda: 100.0)
    fixtures = json.loads((ROOT / "packages/client-events/fixtures.json").read_text())
    for expected in fixtures:
        fields = {key: value for key, value in expected.items() if key not in {"event", "chat_id"}}
        event_type = {
            "context_compaction": ContextCompactionEvent,
            "recovery_state": RecoveryStateEvent,
            "retry_status": RetryStatusEvent,
        }[expected["event"]]
        if "retry_after_s" in fields:
            fields["next_retry_at"] = 100.0 + fields.pop("retry_after_s")
        projection = project_notification(expected["chat_id"], event_type(**fields))
        assert projection is not None
        assert projection.payload == expected


def test_tui_source_archive_preserves_shared_module_import_path():
    spec = importlib.util.spec_from_file_location("package_release", ROOT / "tui/scripts/package-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tarfile.open(fileobj=io.BytesIO(module._source_archive(ROOT / "tui"))) as archive:
        names = set(archive.getnames())
        assert "nanobot-tui-source/tui/src/protocol.ts" in names
        assert "nanobot-tui-source/packages/client-events/notifications.ts" in names
        assert "nanobot-tui-source/tui/bun.lock" in names
        assert "nanobot-tui-source/LICENSE" in names
