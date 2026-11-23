import hashlib
import json

import pytest

from nanobot.update_manager import read_manager_policy


def read(tmp_path, manager, data):
    raw = data.encode() if isinstance(data, str) else json.dumps(data).encode()
    path = tmp_path / ("uv-receipt.toml" if manager == "uv" else "pipx_metadata.json")
    path.write_bytes(raw)
    result = read_manager_policy(tmp_path, manager, hashlib.sha256(raw).hexdigest())
    assert path.read_bytes() == raw, "Inspection must never rewrite the manager's receipt"
    return result


def pipx_record(**main):
    return {"pipx_metadata_version": "0.12", "backend": "pip", "main_package": {
        "package": "nanobot-ai", "package_or_url": "nanobot-ai[webui]>=0.3.4,<0.4", **main,
    }, "injected_packages": {"fixture-plugin": {
        "package": "fixture-plugin", "package_or_url": "fixture-plugin==1.0.0",
    }}}


def test_uv_intent_preserves_extras_constraints_and_injected_packages(tmp_path):
    policy = read(tmp_path, "uv", '''[tool]
requirements = [
  { name = "nanobot-ai", extras = ["webui", "image_gen"], specifier = ">=0.3.4,<0.4" },
  { name = "fixture-plugin", specifier = "==1.0.0" }
]
[tool.options]
index-url = "https://private-user:fixture-secret@example.invalid/simple"
''')
    assert policy.extras == ["image-gen", "webui"]
    assert policy.injected_packages == ["fixture-plugin"]
    assert policy.restriction("0.3.6.dev1") is None
    assert "constraints" in policy.restriction("0.4.0")
    assert "fixture-secret" not in policy.model_dump_json()


@pytest.mark.parametrize("main,reason", [
    ({"pinned": True}, "pinned"),
    ({"lock_file": {"__type__": "Path", "__Path__": "/private/pylock.toml"}}, "lock file"),
    ({"package_or_url": "nanobot-ai[webui]==0.3.4"}, "constraints"),
    ({"package_or_url": "nanobot-ai[webui] @ git+https://example.invalid/nanobot.git"}, "manual review"),
    ({"package_or_url": "/private/custom-source"}, "manual review"),
])
def test_pipx_pins_locks_and_nonregistry_sources_are_not_silently_replaced(tmp_path, main, reason):
    policy = read(tmp_path, "pipx", pipx_record(**main))
    assert reason in policy.restriction("0.3.5")
    assert policy.injected_packages == ["fixture-plugin"]


def test_pipx_named_wheel_preserves_extras_without_recording_credential_url(tmp_path):
    policy = read(tmp_path, "pipx", pipx_record(
        package_or_url="nanobot-ai[webui] @ https://private:fixture-secret@example.invalid/nanobot.whl",
    ))
    assert policy.source == "artifact"
    assert policy.extras == ["webui"]
    assert policy.restriction("0.3.5") is None
    assert "fixture-secret" not in policy.model_dump_json()


def test_older_pipx_receipt_keeps_extras_and_pin_without_metadata_migration(tmp_path):
    record = pipx_record(pinned=True, package_or_url="nanobot-ai[webui] @ file:///private/nanobot.whl")
    record["pipx_metadata_version"] = "0.5"
    del record["backend"]  # pipx 1.7.1 only had the pip backend.
    policy = read(tmp_path, "pipx", record)
    assert policy.backend == "pip"
    assert policy.extras == ["webui"]
    assert policy.injected_packages == ["fixture-plugin"]
    assert "pinned" in policy.restriction("0.3.5")


@pytest.mark.parametrize("main", [
    {"package_or_url": "nanobot-ai>=0.3.4,<0.4"},
    {"package_or_url": "nanobot-ai", "pip_args": ["--index-url", "https://user:fixture-secret@example.invalid/simple"]},
])
def test_pipx_generic_upgrade_cannot_discard_original_install_policy(tmp_path, main):
    policy = read(tmp_path, "pipx", pipx_record(**main))
    assert "generic pipx upgrade" in policy.restriction("0.3.5")
    assert "fixture-secret" not in policy.model_dump_json()


def test_changed_receipt_is_rejected_between_probe_and_read(tmp_path):
    path = tmp_path / "pipx_metadata.json"
    raw = json.dumps(pipx_record()).encode()
    path.write_bytes(raw)
    path.write_text(json.dumps(pipx_record(pinned=True)))
    with pytest.raises(ValueError, match="Could not verify"):
        read_manager_policy(tmp_path, "pipx", hashlib.sha256(raw).hexdigest())


@pytest.mark.parametrize("change", [
    {"pipx_metadata_version": "future-version"},
    {"main_package": {"package": "other-package", "package_or_url": "other-package"}},
    {"main_package": {"package": "nanobot-ai", "package_or_url": {"token": "fixture-secret"}}},
])
def test_unconfirmed_receipts_fail_without_leaking_parser_input(tmp_path, change):
    with pytest.raises(ValueError, match="Could not verify") as failure:
        read(tmp_path, "pipx", {**pipx_record(), **change})
    assert "fixture-secret" not in str(failure.value)


def test_uv_unknown_requirement_semantics_require_review(tmp_path):
    policy = read(tmp_path, "uv", '''[tool]
requirements = [{ name = "nanobot-ai", directory = "/private/checkout", editable = true }]
''')
    assert policy.source == "unrecognized"
    assert "manual review" in policy.restriction("0.3.5")


def test_uv_wheel_url_is_not_misrepresented_as_an_overridable_registry_requirement(tmp_path):
    # A real uv tool upgrade retains this URL even when a newer wheel is passed.
    # Refuse before shutdown instead of discovering an offline-cache miss afterwards.
    policy = read(tmp_path, "uv", '''[tool]
requirements = [{ name = "nanobot-ai", url = "https://example.invalid/nanobot_ai-0.3.5-py3-none-any.whl" }]
''')
    assert policy.source == "artifact"
    assert "bound to a wheel URL" in policy.restriction("0.3.6")
