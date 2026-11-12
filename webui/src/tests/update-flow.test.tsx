import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";
import { copyTextToClipboard } from "@/lib/clipboard";
import type { NanobotClient } from "@/lib/nanobot-client";
import type { ConnectionStatus } from "@/lib/types";
import { UpdateFlowProvider, useUpdateFlow } from "@/providers/UpdateFlowProvider";
import { ClientProvider } from "@/providers/ClientProvider";
import { AboutSettings } from "@/components/settings/overview/OverviewSettings";
import { settingsPayload } from "@/tests/settings-test-utils";

vi.mock("@/lib/api", async (original) => ({
  ...await original<typeof api>(), createUpdateReview: vi.fn(), readUpdateReview: vi.fn(),
  readUpdateJob: vi.fn(), prepareUpdate: vi.fn(), executeUpdate: vi.fn(), settleUpdate: vi.fn(), checkVersion: vi.fn(), fetchSettings: vi.fn(),
}));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn() }));
const id = "71c91a73-842e-42e9-aeb4-61a5bfe51135";
let connectionStatus: ConnectionStatus = "open";
const client = { get status() { return connectionStatus; } } as NanobotClient;
const review: api.UpdateReviewResponse = {
  plan: { id, installation_id: "installed-a", host: "test Mac", running_version: "0.3.5", target_version: "0.3.6",
    action: "upgrade", validity: "current", execution_blocked_reason: null, profiles: [] },
  installation_allowed: true, execution_available: true,
};
const externalReview: api.UpdateReviewResponse = {
  ...review, execution_available: false,
  plan: { ...review.plan, execution_blocked_reason: "installation_owner", guide: {
    method: "pipx", host: "remote-server", environment: "/server/pipx/venvs/nanobot-ai-work", shell: "sh", reason: "registry",
    inspect_command: "env PIPX_HOME=/server/pipx pipx list",
    update_command: "env PIPX_HOME=/server/pipx pipx upgrade nanobot-ai-work",
    verify_command: "/server/pipx/venvs/nanobot-ai-work/bin/python -I -m nanobot --version",
  } },
};
const job = (phase: api.UpdateJobPhase, confirmation: string | null = null): api.UpdateJob => ({
  id, installation_id: "installed-a", target_version: "0.3.6", running_version: "0.3.5",
  recorded_phase: phase, mutation_started: false, execution_confirmation_id: confirmation,
});
function Entry() {
  const flow = useUpdateFlow();
  return <button disabled={!flow.open} onClick={flow.open}>Update entry</button>;
}
function view(token = "gateway-a", enabled = true, canSettleHandoff = true) {
  return <UpdateFlowProvider client={client} token={token} enabled={enabled} canSettleHandoff={canSettleHandoff}><Entry /></UpdateFlowProvider>;
}
beforeEach(() => {
  connectionStatus = "open";
  vi.resetAllMocks(); sessionStorage.clear();
  vi.mocked(api.createUpdateReview).mockResolvedValue(review);
  vi.mocked(api.readUpdateReview).mockResolvedValue(review);
  vi.mocked(api.prepareUpdate).mockResolvedValue({ job: job("preparing") });
  vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("ready") });
  vi.mocked(api.executeUpdate).mockResolvedValue({ job: job("checking", "confirmed") });
  vi.mocked(api.checkVersion).mockResolvedValue({ updateAvailable: null });
});
afterEach(() => { cleanup(); sessionStorage.clear(); vi.useRealTimers(); });

describe("Real update consent and recovery", () => {
  it("opens the original confirmation from an automatically checked About update without consenting to installation", async () => {
    vi.mocked(api.checkVersion).mockResolvedValue({ installation_method: "managed",
      updateAvailable: { currentVersion: "0.3.5", latestVersion: "0.3.6" } });
    render(<ClientProvider client={client} token="about-confirmation" webuiCapabilities={["webui.update-flow.v1"]}>
      <AboutSettings settings={settingsPayload()} />
    </ClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /^Update$/ }));
    expect(await screen.findByRole("button", { name: "Update & restart" })).toBeEnabled();
    expect(api.checkVersion).toHaveBeenCalledOnce();
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("offers installation-bound instructions and copy feedback, without installation consent", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue(externalReview);
    vi.mocked(copyTextToClipboard).mockResolvedValueOnce(false).mockResolvedValueOnce(true);
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    await screen.findByRole("heading", { name: "Update via pipx" });
    expect(screen.getByText("Gateway: remote-server")).toBeVisible();
    expect(screen.getByText(/connect by SSH or its server console/)).toBeVisible();
    expect(screen.getByLabelText("Update command")).toHaveValue(externalReview.plan.guide!.update_command);
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await screen.findByText("Could not copy. Select and copy the command above.");
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    await screen.findByRole("button", { name: "Copied" });
    expect(copyTextToClipboard).toHaveBeenLastCalledWith(externalReview.plan.guide!.update_command);
    fireEvent.click(screen.getByRole("button", { name: "Inspect this installation" }));
    expect(screen.getByRole("button", { name: "Inspect this installation" })).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("button", { name: "Inspect this installation" }));
    expect(screen.getByRole("button", { name: "Inspect this installation" })).toHaveAttribute("aria-expanded", "false");
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("verifies the running gateway, reports mismatch and offline errors, never infers success from package installation", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue(externalReview);
    vi.mocked(api.fetchSettings).mockResolvedValueOnce({ ...settingsPayload(), version: { current: "0.3.5" } })
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ ...settingsPayload(), version: { current: "0.3.6" } });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    const check = await screen.findByRole("button", { name: "Check running gateway" });
    fireEvent.click(check);
    await screen.findByText(/reports v0.3.5, not the notice’s v0.3.6/);
    fireEvent.click(check);
    await screen.findByText(/Could not read the running version/);
    fireEvent.click(check);
    await screen.findByText("Confirmed: this gateway is running v0.3.6.");
    expect(api.fetchSettings).toHaveBeenLastCalledWith("gateway-a");
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("discards an old gateway's late verification on a credential switch", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue(externalReview);
    let resolve!: (value: Awaited<ReturnType<typeof api.fetchSettings>>) => void;
    vi.mocked(api.fetchSettings).mockImplementation(() => new Promise(done => { resolve = done; }));
    const mounted = render(view());
    fireEvent.click(screen.getByText("Update entry"));
    fireEvent.click(await screen.findByRole("button", { name: "Check running gateway" }));
    mounted.rerender(view("gateway-b"));
    await act(async () => { resolve({ ...settingsPayload(), version: { current: "0.3.6" } }); });
    expect(screen.queryByText(/Confirmed: this gateway/)).not.toBeInTheDocument();
    expect(screen.queryByText("Gateway: remote-server")).not.toBeInTheDocument();
  });
  it("retains the safe fallback for an older host without optional guidance", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, execution_available: false,
      plan: { ...review.plan, execution_blocked_reason: "installation_owner" } });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    await screen.findByRole("link", { name: "Update instructions for your installation" });
    expect(screen.queryByRole("button", { name: "Update & restart" })).not.toBeInTheDocument();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("guides an already installed target through restart without offering another installation", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...externalReview,
      plan: { ...externalReview.plan, action: "restart", execution_blocked_reason: "not_upgrade",
        guide: { ...externalReview.plan.guide!, reason: "restart", update_command: null, inspect_command: null } } });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    await screen.findByRole("heading", { name: "Restart and verify" });
    expect(screen.getByRole("button", { name: "Check running gateway" })).toBeVisible();
    expect(screen.queryByLabelText("Update command")).not.toBeInTheDocument();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
  });
  it("does not send a managed-install user to the terminal during a long reconnect", async () => {
    vi.useFakeTimers();
    connectionStatus = "closed";
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    sessionStorage.setItem("nanobot.pending-update-recovery.v1", JSON.stringify({
      id, command: "private recovery command", automatic: true,
    }));
    render(view());
    await act(async () => { await vi.advanceTimersByTimeAsync(123_000); });
    expect(screen.getByText(/nanobot will try to restore service/)).toBeVisible();
    expect(screen.queryByDisplayValue("private recovery command")).not.toBeInTheDocument();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    expect(api.readUpdateJob).not.toHaveBeenCalled();
  });
  it("reports a restored service without claiming the update succeeded or asking for terminal repair", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("failed", "confirmed"), previous_version: "0.3.5", service_restored: true,
      mutation_started: true, recovery_command: "private recovery command",
    } });
    render(view());
    await screen.findByText("Previous version restored");
    expect(screen.getByText(/v0.3.5 is running again/)).toBeInTheDocument();
    expect(screen.queryByText("Update complete")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("private recovery command")).not.toBeInTheDocument();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("keeps polling a failed attempt while its independent recovery owner is active", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValueOnce({ job: {
      ...job("failed", "confirmed"), recovery_active: true, mutation_started: true,
    } }).mockResolvedValue({ job: {
      ...job("failed", "confirmed"), previous_version: "0.3.5", service_restored: true,
    } });
    render(view());
    await screen.findByText("Previous version restored", {}, { timeout: 4000 });
    expect(api.readUpdateJob).toHaveBeenCalledTimes(2);
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it.each(["0.3.7.dev42", "0.3.7"])("shows preview risk only for a preview installation target (%s)", async (version) => {
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, plan: { ...review.plan, target_version: version } });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    await screen.findByRole("button", { name: "Update & restart" });
    expect(screen.queryByText("This is a preview release and may have bugs.") !== null).toBe(version.includes(".dev"));
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it.each(["preparation_requested", "preparing"] as const)("settles a refreshed %s job before reviewing a fresh plan, without the handoff extension", async (phase) => {
    vi.useFakeTimers();
    vi.mocked(api.prepareUpdate).mockResolvedValue({ job: job(phase) });
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job(phase) });
    let resolveSettlement!: (value: { job: api.UpdateJob }) => void;
    vi.mocked(api.settleUpdate).mockImplementation(() => new Promise(resolve => { resolveSettlement = resolve; }));
    const mounted = render(view("gateway-a", true, false));
    fireEvent.click(screen.getByText("Update entry"));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Update & restart" }));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Please wait" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Review update" })).not.toBeInTheDocument();
    mounted.unmount();

    // A refresh restores the durable ID, not the old tab's installation consent.
    render(view("gateway-a", true, false));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Review update" })).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(123_000); });
    expect(screen.getByRole("button", { name: "Review update" })).toBeEnabled();
    expect(api.settleUpdate).not.toHaveBeenCalled();
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);

    const nextId = "81c91a73-842e-42e9-aeb4-61a5bfe51135";
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, plan: { ...review.plan, id: nextId, target_version: "0.3.7" } });
    fireEvent.click(screen.getByRole("button", { name: "Review update" }));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Please wait" })).toBeDisabled();
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    await act(async () => resolveSettlement({ job: job("preparation_failed") }));
    expect(screen.getByText(/Updating to v0.3.7/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Update & restart" })).toBeEnabled();
    expect(api.settleUpdate).toHaveBeenCalledOnce();
    expect(api.settleUpdate).toHaveBeenCalledWith(client, id);
    expect(api.createUpdateReview).toHaveBeenCalledTimes(2);
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBeNull();
    expect(sessionStorage.getItem("nanobot.pending-update-recovery.v1")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("keeps an active preparer's refused settlement and retries status read-only", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("preparing") });
    vi.mocked(api.settleUpdate).mockRejectedValue(new api.ApiError(409, "Preparation owner still active"));
    render(view("gateway-a", true, false));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Review update" }));
    await act(async () => {});
    expect(screen.getByText(/previous update could not be cleared safely/)).toBeVisible();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(api.readUpdateJob).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Review update" })).toBeEnabled();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByRole("button", { name: "Review update" })).toBeEnabled();
    expect(api.settleUpdate).toHaveBeenCalledOnce();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
  });
  it("keeps a lost preparation-settlement response recoverable without creating another job", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    sessionStorage.setItem("nanobot.pending-update-recovery.v1", JSON.stringify({ id, command: "saved recovery command" }));
    let saved = job("preparing");
    vi.mocked(api.readUpdateJob).mockImplementation(async () => ({ job: saved }));
    vi.mocked(api.settleUpdate).mockImplementation(async () => {
      saved = job("preparation_failed");
      throw new Error("response lost after settlement");
    });
    const mounted = render(view("gateway-a", true, false));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Review update" }));
    await act(async () => {});
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    expect(sessionStorage.getItem("nanobot.pending-update-recovery.v1")).toContain("saved recovery command");
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(screen.getByText("Update did not finish")).toBeVisible();
    expect(api.readUpdateJob).toHaveBeenCalledTimes(2);
    expect(api.settleUpdate).toHaveBeenCalledOnce();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    mounted.unmount();
    render(view("gateway-a", true, false));
    await act(async () => {});
    expect(screen.getByText("Update did not finish")).toBeVisible();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("retires a restored failed handoff and reviews a fresh plan before new consent", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("handoff_failed", "previous") });
    vi.mocked(api.settleUpdate).mockResolvedValue({ job: job("cancelled", "previous") });
    const nextId = "81c91a73-842e-42e9-aeb4-61a5bfe51135";
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, plan: { ...review.plan, id: nextId } });
    render(view());
    fireEvent.click(await screen.findByRole("button", { name: "Review update" }));
    await screen.findByRole("button", { name: "Update & restart" });
    expect(api.settleUpdate).toHaveBeenCalledWith(client, id);
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBeNull();
    vi.mocked(api.prepareUpdate).mockResolvedValue({ job: { ...job("preparing"), id: nextId } });
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: { ...job("ready"), id: nextId } });
    fireEvent.click(screen.getByRole("button", { name: "Update & restart" }));
    await waitFor(() => expect(api.executeUpdate).toHaveBeenCalledWith(client, nextId));
    expect(api.executeUpdate).toHaveBeenCalledOnce();
  });
  it("keeps a refused settlement recoverable and Check again strictly read-only", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("handoff_failed", "previous") });
    vi.mocked(api.settleUpdate).mockRejectedValue(new api.ApiError(409, "Worker still active"));
    render(view());
    fireEvent.click(await screen.findByRole("button", { name: "Review update" }));
    await screen.findByText(/previous update could not be cleared safely/);
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByRole("button", { name: "Review update" });
    expect(api.readUpdateJob).toHaveBeenCalledTimes(2);
    expect(api.settleUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("can leave an expired READY review without bypassing gateway settlement", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateReview).mockResolvedValue({ ...review, execution_available: false,
      plan: { ...review.plan, validity: "expired", execution_blocked_reason: "review_changed" } });
    vi.mocked(api.settleUpdate).mockResolvedValue({ job: job("cancelled") });
    render(view());
    fireEvent.click(await screen.findByRole("button", { name: "Review update" }));
    await screen.findByRole("button", { name: "Update & restart" });
    expect(api.settleUpdate).toHaveBeenCalledWith(client, id);
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("recovers a lost settlement response after reload without restoring consent", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("cancelled", "previous") });
    vi.mocked(api.settleUpdate).mockResolvedValue({ job: job("cancelled", "previous") });
    render(view());
    fireEvent.click(await screen.findByRole("button", { name: "Review update" }));
    await screen.findByRole("button", { name: "Update & restart" });
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("does not retry execution or send unsupported settlement to older hosts", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("handoff_failed", "previous") });
    render(view("gateway-a", true, false));
    fireEvent.click(await screen.findByRole("button", { name: "Check again" }));
    await waitFor(() => expect(api.readUpdateJob).toHaveBeenCalledTimes(2));
    expect(api.executeUpdate).not.toHaveBeenCalled();
    expect(api.settleUpdate).not.toHaveBeenCalled();
  });
  it("reviews on open and stages/executes the same exact plan only after confirmation", async () => {
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    expect(await screen.findByText(/Updating to v0.3.6/)).toBeVisible();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Update & restart" }));
    await waitFor(() => expect(api.executeUpdate).toHaveBeenCalledOnce());
    expect(api.executeUpdate).toHaveBeenCalledWith(client, id);
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.prepareUpdate).toHaveBeenCalledWith(client, id);
  });
  it("reads a restored READY job but never restores installation consent", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    render(view());
    await screen.findByText(/Updating to v0.3.6/);
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Update & restart" }));
    await waitFor(() => expect(api.executeUpdate).toHaveBeenCalledOnce());
  });
  it("waits for the restored review before enabling confirmation", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    let resolveReview!: (value: api.UpdateReviewResponse) => void;
    vi.mocked(api.readUpdateReview).mockImplementation(() => new Promise(resolve => { resolveReview = resolve; }));
    render(view());
    await waitFor(() => expect(api.readUpdateReview).toHaveBeenCalledWith("gateway-a", id));
    expect(screen.queryByRole("button", { name: "Update & restart" })).toBeNull();
    expect(screen.getByRole("button", { name: "Please wait" })).toBeDisabled();
    expect(screen.getByText("Checking the update…")).toBeVisible();
    await act(async () => resolveReview(review));
    expect(screen.getByRole("button", { name: "Update & restart" })).toBeEnabled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("allows a fresh review after a rejected stale preparation has no saved job", async () => {
    // Another tab changed the channel after this plan was reviewed. The gateway
    // rejects preparation before creating a job; a 404 alone is not that proof.
    vi.mocked(api.prepareUpdate).mockRejectedValue(new api.ApiError(409, "Preparation refused"));
    vi.mocked(api.readUpdateJob).mockRejectedValue(new api.ApiError(404, "No saved update"));
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    fireEvent.click(await screen.findByRole("button", { name: "Update & restart" }));
    await screen.findByText(/No package files were changed. Review the update again/);
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBeNull();
    const nextId = "81c91a73-842e-42e9-aeb4-61a5bfe51135";
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, plan: { ...review.plan, id: nextId } });
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await screen.findByRole("button", { name: "Update & restart" });
    expect(api.createUpdateReview).toHaveBeenCalledTimes(2);
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("retains an unknown preparation outcome even if the job is not visible yet", async () => {
    vi.mocked(api.prepareUpdate).mockRejectedValue(new api.ApiError(504, "Request timed out"));
    vi.mocked(api.readUpdateJob).mockRejectedValue(new api.ApiError(404, "No saved update"));
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    fireEvent.click(await screen.findByRole("button", { name: "Update & restart" }));
    await screen.findByText(/Could not read the saved update/);
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(api.readUpdateJob).toHaveBeenCalledTimes(2));
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("preserves a durable job after a preparation error instead of granting new consent", async () => {
    vi.mocked(api.prepareUpdate).mockRejectedValue(new api.ApiError(409, "Read the saved state"));
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    fireEvent.click(await screen.findByRole("button", { name: "Update & restart" }));
    await waitFor(() => expect(api.readUpdateJob).toHaveBeenCalled());
    await screen.findByRole("button", { name: "Update & restart" });
    expect(sessionStorage.getItem("nanobot.pending-update.v1")).toBe(id);
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("never creates or executes a second job after a lost execution response", async () => {
    vi.mocked(api.executeUpdate).mockRejectedValue(new Error("connection closed"));
    vi.mocked(api.readUpdateJob).mockResolvedValueOnce({ job: job("ready") }).mockResolvedValue({ job: job("ready", "confirmed") });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    fireEvent.click(await screen.findByRole("button", { name: "Update & restart" }));
    await screen.findByText(/request may have been accepted/);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(api.readUpdateJob).toHaveBeenCalledTimes(2));
    expect(api.executeUpdate).toHaveBeenCalledOnce();
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Checking..." })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Please wait" })).toBeDisabled();
  });
  it("does not report completion until the actual running version matches", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("succeeded", "confirmed") });
    const mounted = render(view());
    await screen.findByText("Reconnecting…");
    expect(screen.queryByText("Update complete")).toBeNull();
    mounted.unmount();
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: { ...job("succeeded", "confirmed"), running_version: "0.3.6" } });
    render(view());
    expect(await screen.findByText("Update complete")).toBeVisible();
    expect(screen.getByText("Now running v0.3.6.")).toBeVisible();
    expect(screen.getAllByRole("button").filter(button => button.textContent === "Done")).toHaveLength(1);
  });
  it("waits for authenticated reconnect when a restart invalidates an in-flight journal read", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    let rejectRead!: (reason: unknown) => void;
    vi.mocked(api.readUpdateJob).mockImplementationOnce(() => new Promise((_, reject) => { rejectRead = reject; }));
    const mounted = render(view());
    await act(async () => {
      connectionStatus = "reconnecting";
      rejectRead(new api.ApiError(401, "Unauthorized"));
    });
    expect(screen.getByText("Reconnecting…")).toBeVisible();
    expect(screen.queryByText(/Could not read the saved update/)).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(api.readUpdateJob).toHaveBeenCalledTimes(1);

    // Bootstrap renews the API token before the socket finishes reconnecting.
    mounted.rerender(view("renewed-gateway-a"));
    expect(api.readUpdateJob).toHaveBeenCalledTimes(1);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("succeeded", "confirmed"), mutation_started: true, running_version: "0.3.6",
    } });
    connectionStatus = "open";
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(api.readUpdateJob).toHaveBeenLastCalledWith("renewed-gateway-a", id);
    expect(screen.getByText("Update complete")).toBeVisible();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("still reports rejected journal access on an authenticated connection", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockRejectedValue(new api.ApiError(401, "Unauthorized"));
    render(view());
    expect(await screen.findByText(/Could not read the saved update/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("replaces a prolonged reconnect with the actual journal error and allows a read-only retry", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    connectionStatus = "reconnecting";
    render(view());
    await act(async () => { await vi.advanceTimersByTimeAsync(123_000); });
    expect(screen.getByText("Reconnecting…")).toBeVisible();
    connectionStatus = "open";
    vi.mocked(api.readUpdateJob).mockRejectedValue(new api.ApiError(403, "Forbidden"));
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(screen.getByText(/Could not read the saved update/)).toBeVisible();
    expect(screen.queryByText("Reconnecting…")).toBeNull();
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("succeeded", "confirmed"), running_version: "0.3.6",
    } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Check again" })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(screen.getByText("Update complete")).toBeVisible();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("keeps one preparation when double-clicked, hidden and reopened", async () => {
    let resolve!: (value: { job: api.UpdateJob }) => void;
    vi.useFakeTimers();
    vi.mocked(api.prepareUpdate).mockImplementation(() => new Promise(done => { resolve = done; }));
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("preparing") });
    render(view("gateway-a", true, false));
    fireEvent.click(screen.getByText("Update entry"));
    await act(async () => {});
    const button = screen.getByRole("button", { name: "Update & restart" });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Hide" }));
    fireEvent.click(screen.getByText("Update entry"));
    await act(async () => resolve({ job: job("preparing") }));
    await act(async () => { await vi.advanceTimersByTimeAsync(123_000); });
    expect(screen.getByRole("button", { name: "Please wait" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Review update" })).not.toBeInTheDocument();
    expect(api.settleUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: job("ready") });
    await act(async () => { await vi.advanceTimersByTimeAsync(1500); });
    expect(api.executeUpdate).toHaveBeenCalledOnce();
    expect(api.createUpdateReview).toHaveBeenCalledOnce();
    expect(api.prepareUpdate).toHaveBeenCalledOnce();
    expect(api.executeUpdate).toHaveBeenCalledWith(client, id);
  });
  it("acknowledges a read-only retry even when the same failure returns immediately", async () => {
    vi.useFakeTimers();
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("restart_failed", "confirmed"), mutation_started: true,
    } });
    render(view());
    await act(async () => {});
    const retry = screen.getByRole("button", { name: "Check again" });
    fireEvent.click(retry);
    fireEvent.click(retry);
    await act(async () => { await vi.advanceTimersByTimeAsync(599); });
    expect(screen.getByRole("button", { name: "Checking..." })).toBeDisabled();
    expect(api.readUpdateJob).toHaveBeenCalledTimes(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
    expect(screen.getByText("Update did not finish")).toBeVisible();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("can reopen a hidden saved update from About even after the new version is installed", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("restart_failed", "confirmed"), mutation_started: true, running_version: "0.3.6",
    } });
    render(<ClientProvider client={client} token="gateway-a" webuiCapabilities={["webui.update-flow.v1"]}>
      <AboutSettings settings={settingsPayload()} />
    </ClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(screen.getByText("You're up to date")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "View details" }));
    expect(screen.getByRole("alertdialog", { name: "Update did not finish" })).toBeVisible();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
  it("ignores an old gateway's late review without starting an installation", async () => {
    let resolve!: (value: api.UpdateReviewResponse) => void;
    vi.mocked(api.createUpdateReview).mockImplementation(() => new Promise(done => { resolve = done; }));
    const mounted = render(view());
    fireEvent.click(screen.getByText("Update entry"));
    mounted.rerender(view("gateway-b"));
    await act(async () => resolve(review));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
  });
  it("keeps unsupported or unauthorized installations read-only", async () => {
    vi.mocked(api.createUpdateReview).mockResolvedValue({ ...review, installation_allowed: false });
    render(view());
    fireEvent.click(screen.getByText("Update entry"));
    expect(await screen.findByText(/Open this gateway on localhost/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Update & restart" })).toBeNull();
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
  });
  it("does not offer the flow to older hosts without its optional capability", () => {
    render(view("gateway-a", false));
    expect(screen.getByText("Update entry")).toBeDisabled();
    expect(api.createUpdateReview).not.toHaveBeenCalled();
  });
  it("shows the saved host recovery command after mutation failure without executing it", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    const command = `python3 -I -S ~/.nanobot/updates/recover.py ${id} --repair`;
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("failed", "confirmed"), mutation_started: true, recovery_command: command,
    } });
    render(view());
    expect(await screen.findByDisplayValue(command)).toBeVisible();
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("succeeded", "confirmed"), running_version: "0.3.6", mutation_started: true,
    } });
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Update complete")).toBeVisible();
    expect(api.executeUpdate).not.toHaveBeenCalled();
    expect(JSON.parse(sessionStorage.getItem("nanobot.pending-update-recovery.v1") || "{}").command).toBe(command);
  });
  it("shows recovery after an admitted job fails during backup before package mutation", async () => {
    sessionStorage.setItem("nanobot.pending-update.v1", id);
    const command = `python3 -I -S /private/update/recover.py ${id} --repair`;
    vi.mocked(api.readUpdateJob).mockResolvedValue({ job: {
      ...job("failed", "confirmed"), recovery_command: command,
    } });
    render(view());
    expect(await screen.findByDisplayValue(command)).toBeVisible();
    expect(screen.getByText(/The update stopped before installation. No package files were changed/)).toBeVisible();
    expect(screen.getAllByText(/Run this command in a terminal/)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(api.readUpdateJob).toHaveBeenCalledTimes(2));
    expect(api.createUpdateReview).not.toHaveBeenCalled();
    expect(api.prepareUpdate).not.toHaveBeenCalled();
    expect(api.executeUpdate).not.toHaveBeenCalled();
  });
});
