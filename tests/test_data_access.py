"""Real shared-data leases across process and installation identities."""

import json
import os
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from uuid import uuid4

import pytest

from nanobot.data_access import (
    DataStartupGrant,
    data_access,
    profile_data_access,
    profile_data_paths,
)
from nanobot.installation_lock import InstallationBusyError

_CHILD = """
import json, os, sys
from nanobot.data_access import DataStartupGrant, data_access
sys.prefix = sys.argv[1]
grant = DataStartupGrant(**json.loads(os.environ['TEST_DATA_GRANT'])) if 'TEST_DATA_GRANT' in os.environ else None
with data_access(sys.argv[4:], updating=sys.argv[2] == 'update', job_id=sys.argv[3] or None, grant=grant) as lease:
    if sys.argv[3] and sys.argv[2] == 'update':
        lease.reserve()
    print('ready', flush=True)
    sys.stdin.read(1)
"""


@pytest.fixture
def private_home(tmp_path, monkeypatch):
    home = tmp_path / "private home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


@contextmanager
def process_access(environment, paths, *, updating=False, job_id=None, grant=None):
    env = os.environ.copy()
    if grant is not None:
        env["TEST_DATA_GRANT"] = json.dumps({"job_id": grant.job_id, "participant": grant.participant, "token": grant.token})
    process = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(environment), "update" if updating else "runtime", job_id or "", *map(str, paths)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert process.stdout.readline().strip() == "ready", process.stderr.read()
        yield process
    finally:
        if process.poll() is None:
            process.stdin.write("x")
            process.stdin.flush()
        process.communicate(timeout=10)


def crash_process(process):
    # Windows venv python.exe redirects to a child interpreter. Killing only
    # that launcher leaves the actual lease holder alive until stdin closes.
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       check=True, capture_output=True, timeout=10)
    else:
        process.kill()
    process.wait(timeout=10)


def test_shared_data_blocks_update_across_installations_until_last_writer_exits(private_home, tmp_path):
    store = tmp_path / "shared sessions"
    with process_access(tmp_path / "first environment", [store]) as first:
        with process_access(tmp_path / "second environment", [store]):
            with data_access([store]):
                pass  # Normal runtime sharing remains allowed.
            crash_process(first)
            with pytest.raises(InstallationBusyError, match="data is in use"):
                with data_access([store], updating=True):
                    pytest.fail("The other installation's writer was ignored")
        with data_access([store], updating=True):
            pass


@pytest.mark.parametrize("held_parent", [False, True])
def test_overlapping_roots_block_but_siblings_remain_usable(private_home, tmp_path, held_parent):
    parent = tmp_path / "sessions"
    child = parent / "chat.jsonl"
    held, requested = (parent, child) if held_parent else (child, parent)
    with process_access(tmp_path / "another environment", [held], updating=True):
        with pytest.raises(InstallationBusyError):
            with data_access([requested]):
                pytest.fail("An ancestor/descendant path bypassed maintenance")
        with data_access([tmp_path / "separate sessions"]):
            pass


def test_alias_and_partial_acquisition_do_not_bypass_or_leak_leases(private_home, tmp_path):
    store, available = tmp_path / "z-store", tmp_path / "a-store"
    store.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(store, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks are not enabled for this account")
    with process_access(tmp_path / "other environment", [alias]) as writer:
        with pytest.raises(InstallationBusyError):
            with data_access([available, store], updating=True):
                pytest.fail("A symlink alias bypassed the writer lease")
        with data_access([available]):
            pass  # Failed multi-store acquisition released its earlier leases.
        crash_process(writer)
        with data_access([store], updating=True):
            pass


def test_job_reservation_survives_process_exit_until_same_scope_is_recovered(private_home, tmp_path):
    store, sibling = tmp_path / "sessions", tmp_path / "unrelated sessions"
    job_id = str(uuid4())
    with process_access(tmp_path / "update environment", [store], updating=True, job_id=job_id) as worker:
        crash_process(worker)
    # No process holds the leases now. The durable reservation still excludes
    # overlapping readers/writers from other installations, but not unrelated data.
    for path in (store, store / "chat.jsonl", store.parent):
        with pytest.raises(InstallationBusyError, match="reserved"):
            with data_access([path]):
                pytest.fail("A runtime entered an interrupted maintenance scope")
    with data_access([sibling]):
        pass
    with pytest.raises(InstallationBusyError, match="unfinished update"):
        with data_access([store], updating=True, job_id=str(uuid4())):
            pytest.fail("Another job took over the interrupted update")
    with pytest.raises(InstallationBusyError, match="unfinished update"):
        with data_access([sibling], updating=True, job_id=job_id):
            pytest.fail("The same ID changed the approved data scope")
    with data_access([store], updating=True, job_id=job_id) as recovered:
        recovered.release_reservation()
    with data_access([store]):
        pass


@pytest.mark.parametrize("legacy", [False, True])
def test_profile_handoff_keeps_delivery_leased_without_expanding_old_grant(private_home, tmp_path, legacy):
    selectors = dict(home=private_home, data_dir=tmp_path / "data",
                     config=tmp_path / "data/config.json", workspace=tmp_path / "workspace")
    delivery = selectors["data_dir"] / "delivery"
    scope = tuple(path for path in profile_data_paths(**selectors) if not legacy or path != delivery)
    job_id, participant = str(uuid4()), "a" * 64
    with data_access(scope, updating=True, job_id=job_id) as owner:
        owner.reserve()
    with ExitStack() as runtime:
        with data_access(scope, job_id=job_id) as owner:
            grant = owner.grant_startup(participant, scope)
            runtime.enter_context(profile_data_access(**selectors, grant=grant))
            # The old reservation is not enlarged to authorize initialization.
            saved = json.loads(owner.reservation_path.read_text())
            assert saved["grants"][participant]["roots"] == sorted(str(path.resolve()).casefold() for path in scope)
            assert not delivery.exists()
            owner.release_reservation()
        # Once handoff ends, the running profile still owns the new store lease.
        with pytest.raises(InstallationBusyError, match="data is in use"):
            with data_access((delivery,), updating=True):
                pytest.fail("A delivery store writer escaped the runtime lease")
    with data_access((delivery,), updating=True):
        pass


def test_profile_handoff_cannot_defer_an_existing_store(private_home, tmp_path):
    selectors = dict(home=private_home, data_dir=tmp_path / "data",
                     config=tmp_path / "data/config.json", workspace=tmp_path / "workspace")
    scope = tuple(path for path in profile_data_paths(**selectors)
                  if path not in {selectors["data_dir"] / "delivery", selectors["data_dir"] / "auth"})
    job_id = str(uuid4())
    with data_access(scope, updating=True, job_id=job_id) as owner:
        owner.reserve()
    with data_access(scope, job_id=job_id) as handoff:
        with pytest.raises(ValueError, match="exceeds the reviewed data scope"):
            handoff.grant_profile_startup("a" * 64, **selectors)


def test_verified_handoff_admits_only_granted_scope_until_explicit_completion(private_home, tmp_path):
    store = tmp_path / "sessions"
    runtime_scope = [store / "profile"]
    job_id, participant = str(uuid4()), "a" * 64
    with data_access([store], updating=True, job_id=job_id) as owner:
        owner.reserve()
    with data_access([store], job_id=job_id) as handoff:
        grant = handoff.grant_startup(participant, runtime_scope)
        assert grant.token not in handoff.reservation_path.read_text()
        assert grant.token not in repr(grant)
        with pytest.raises(ValueError, match="exceeds"):
            handoff.grant_startup("b" * 64, [store.parent])
        with pytest.raises(InstallationBusyError, match="scope"):
            with data_access([store], grant=grant):
                pytest.fail("A participant expanded its allowed data roots")
        invalid = DataStartupGrant(job_id, participant, "0" * 64)
        with pytest.raises(InstallationBusyError, match="scope"):
            with data_access(runtime_scope, grant=invalid):
                pytest.fail("A job ID and participant name bypassed the grant")
        with process_access(tmp_path / "target environment", runtime_scope, grant=grant):
            with pytest.raises(InstallationBusyError):
                with data_access(runtime_scope, grant=grant):
                    pytest.fail("Two processes claimed one startup participant")
            with pytest.raises(InstallationBusyError, match="still running"):
                handoff.grant_startup(participant, runtime_scope)
            with pytest.raises(InstallationBusyError, match="reserved"):
                with data_access(runtime_scope):
                    pytest.fail("An ordinary startup entered maintenance")
            # Only the lifecycle owner calls this after verifying the runtime;
            # participant leases are shared, so completion does not deadlock.
            handoff.release_reservation()
            with data_access(runtime_scope):
                pass
    with pytest.raises(InstallationBusyError, match="no longer reserved"):
        with data_access(runtime_scope, grant=grant):
            pytest.fail("A completed startup grant was replayed")


def test_crashed_handoff_keeps_fence_and_child_lease_until_recovery(private_home, tmp_path):
    store = tmp_path / "sessions"
    job_id, participant = str(uuid4()), "c" * 64
    with data_access([store], updating=True, job_id=job_id) as owner:
        owner.reserve()
    coordinator = subprocess.Popen([
        sys.executable, "-c", """
import json, sys
from dataclasses import asdict
from nanobot.data_access import data_access
with data_access([sys.argv[1]], job_id=sys.argv[2]) as handoff:
    grant = handoff.grant_startup(sys.argv[3], [sys.argv[1]])
    print(json.dumps(asdict(grant)), flush=True)
    sys.stdin.read(1)
""", str(store), job_id, participant,
    ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        encoded = coordinator.stdout.readline()
        assert encoded, coordinator.stderr.read()
        grant = DataStartupGrant(**json.loads(encoded))
        with process_access(tmp_path / "target environment", [store], grant=grant) as child:
            crash_process(coordinator)
            # The coordinator's OS leases are gone, but the child owns its own.
            with pytest.raises(InstallationBusyError):
                with data_access([store], updating=True, job_id=job_id):
                    pytest.fail("Repair raced an orphan startup still using data")
            with pytest.raises(InstallationBusyError, match="reserved"):
                with data_access([store]):
                    pytest.fail("Coordinator exit incorrectly lifted maintenance")
            crash_process(child)
    finally:
        if coordinator.poll() is None:
            crash_process(coordinator)
        coordinator.communicate(timeout=10)
    with data_access([store], job_id=job_id) as recovered:
        replacement = recovered.grant_startup(participant, [store])
        with pytest.raises(InstallationBusyError, match="scope"):
            with data_access([store], grant=grant):
                pytest.fail("An obsolete grant survived explicit reauthorization")
        with data_access([store], grant=replacement) as startup:
            with pytest.raises(ValueError, match="Only an update job"):
                startup.release_reservation()
            with pytest.raises(ValueError, match="Only an update job"):
                startup.reserve()
        # Exiting the recovered handoff still does not mean verification passed.
    with data_access([store], updating=True, job_id=job_id) as repair:
        repair.reserve()  # New package mutation revokes all startup grants.
    with pytest.raises(InstallationBusyError, match="scope"):
        with data_access([store], grant=replacement):
            pytest.fail("A grant from before repair authorized a new startup")
    with data_access([store], updating=True, job_id=job_id) as repair:
        repair.release_reservation()
