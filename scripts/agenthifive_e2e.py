"""Manual end-to-end exercise for the AgentHiFive adapter in nanobot.

This script is intentionally not part of CI. It expects a locally running
AgentHiFive API plus a temp config file created during a live setup.
"""

import asyncio
import json
import os
import sys

# Add the repo root to path so we can import both packages
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from agenthifive_nanobot.types import ApprovalResult, BearerAuthConfig, PendingApproval
from agenthifive_nanobot.vault_client import VaultClient

# Load config from local setup
CONFIG = json.loads(open("/tmp/nanobot-spike-config.json", encoding="utf-8").read())
BASE_URL = "http://localhost:4000"
AGENT_TOKEN = CONFIG["agentToken"]
CONN_ID = CONFIG["connId"]
JWT = CONFIG["jwt"]

results_received: list[tuple[ApprovalResult, PendingApproval]] = []


async def mock_on_result(result: ApprovalResult, approval: PendingApproval) -> None:
    """Capture results instead of injecting into MessageBus."""
    results_received.append((result, approval))
    print(f"  [RESULT] approval={result.approval_request_id} status={result.status}")
    if result.execution_result:
        vault_status = result.execution_result.get("status", "?")
        print(f"  [RESULT] vault response status: {vault_status}")
        if result.execution_result.get("body"):
            body_preview = json.dumps(result.execution_result["body"])[:200]
            print(f"  [RESULT] body: {body_preview}")
    if result.error:
        print(f"  [RESULT] error: {result.error}")


async def approve_via_api(approval_id: str) -> None:
    """Approve a request via the AH5 dashboard API."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v1/approvals/{approval_id}/approve",
            headers={"Authorization": f"Bearer {JWT}"},
        )
        print(f"  [APPROVE] {resp.status_code}: {resp.json()}")


async def main():
    print("=" * 60)
    print("  AgentHiFive Adapter E2E Test")
    print("=" * 60)

    vault = VaultClient(
        base_url=BASE_URL,
        auth=BearerAuthConfig(mode="bearer", token=AGENT_TOKEN),
    )
    from agenthifive_nanobot.pending_store import PendingStore

    store = PendingStore("/tmp/e2e-test-pending.json")
    from agenthifive_nanobot.approval_poller import ApprovalPoller

    poller = ApprovalPoller(
        vault_client=vault,
        store=store,
        on_result=mock_on_result,
        poll_interval=2.0,
    )

    print("\n--- Test 1: Full approval lifecycle ---")

    print("Step 1: Sending execute request...")
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/vault/execute",
            headers={
                "Authorization": f"Bearer {AGENT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": "B",
                "connectionId": CONN_ID,
                "method": "GET",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
            },
        )
        data = resp.json()
        print(f"  Response: {resp.status_code} approvalRequired={data.get('approvalRequired')}")
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}"
        approval_id = data["approvalRequestId"]
        print(f"  Approval ID: {approval_id}")

    print("Step 2: Tracking approval in adapter...")
    poller.add_pending(
        PendingApproval(
            approval_request_id=approval_id,
            original_payload={
                "model": "B",
                "connectionId": CONN_ID,
                "method": "GET",
                "url": "https://generativelanguage.googleapis.com/v1beta/models",
            },
            channel="test",
            chat_id="test-chat",
            sender_id="test-user",
        )
    )

    print("Step 3: Starting poller...")
    await poller.start()

    print("Step 4: Approving request...")
    await approve_via_api(approval_id)

    print("Step 5: Waiting for poller to detect and replay...")
    for i in range(15):
        await asyncio.sleep(2)
        if results_received:
            break
        print(f"  ... polling ({i + 1})")

    print("\nStep 6: Verifying...")
    assert len(results_received) == 1, f"Expected 1 result, got {len(results_received)}"
    result, approval = results_received[0]
    assert result.status == "approved", f"Expected 'approved', got '{result.status}'"
    print(f"  Status: {result.status}")
    print(f"  Replay attempted: {'yes' if result.execution_result or result.error else 'no'}")

    await poller.stop()

    print("\n--- Test 2: Tampered replay rejection ---")
    results_received.clear()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/vault/execute",
            headers={
                "Authorization": f"Bearer {AGENT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": "B",
                "connectionId": CONN_ID,
                "method": "POST",
                "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                "body": {"contents": [{"parts": [{"text": "original"}]}]},
            },
        )
        data = resp.json()
        assert resp.status_code == 202
        approval_id2 = data["approvalRequestId"]
        print(f"  Approval ID: {approval_id2}")

    await approve_via_api(approval_id2)

    print("  Replaying with tampered body...")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/vault/execute",
            headers={
                "Authorization": f"Bearer {AGENT_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "model": "B",
                "connectionId": CONN_ID,
                "method": "POST",
                "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                "body": {"contents": [{"parts": [{"text": "TAMPERED"}]}]},
                "approvalId": approval_id2,
            },
        )
        data = resp.json()
        print(f"  Response: {resp.status_code} error={data.get('error', 'none')}")
        assert resp.status_code == 403, f"Expected 403, got {resp.status_code}"
        assert "payload does not match" in data.get("error", ""), f"Wrong error: {data}"

    print("\n" + "=" * 60)
    print("  ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
