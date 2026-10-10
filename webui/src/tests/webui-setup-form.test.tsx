import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WebuiSetupForm } from "@/components/WebuiSetupForm";

describe("WebUI access setup", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("validates passwords and reveals both fields without sending a request", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<WebuiSetupForm onInitialized={vi.fn()} onAlreadyInitialized={vi.fn()} />);
    const password = screen.getByLabelText("WebUI password");
    const confirmation = screen.getByLabelText("Confirm password");
    const submit = screen.getByRole("button", { name: "Set password and continue" });
    fireEvent.click(submit);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter an access password");
    fireEvent.change(password, { target: { value: "password" } });
    fireEvent.change(confirmation, { target: { value: "different" } });
    fireEvent.click(submit);
    expect(screen.getByRole("alert")).toHaveTextContent("The passwords do not match");
    expect(confirmation).toHaveFocus();
    fireEvent.change(password, { target: { value: "🔐".repeat(1025) } });
    fireEvent.click(submit);
    expect(screen.getByRole("alert")).toHaveTextContent("1–1024 characters");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(confirmation).toHaveAttribute("type", "text");
    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(confirmation).toHaveAttribute("type", "password");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the draft after a save failure and retries the same JSON request", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: "save_failed" }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    const initialized = vi.fn();
    render(<WebuiSetupForm onInitialized={initialized} onAlreadyInitialized={vi.fn()} />);
    const secret = "🔐".repeat(1024);
    fireEvent.change(screen.getByLabelText("WebUI password"), { target: { value: secret } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: secret } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and continue" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save the password. Try again.");
    expect(screen.getByLabelText("WebUI password")).toHaveValue(secret);
    expect(initialized).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Set password and continue" }));
    await waitFor(() => expect(initialized).toHaveBeenCalledWith(secret));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenLastCalledWith("/webui/setup", expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: secret }),
    }));
  });

  it("rejects passwords that would be interpreted as config environment references", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const initialized = vi.fn();
    render(<WebuiSetupForm onInitialized={initialized} onAlreadyInitialized={vi.fn()} />);
    const password = screen.getByLabelText("WebUI password");
    fireEvent.change(password, { target: { value: "prefix-${PASSWORD}" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "prefix-${PASSWORD}" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and continue" }));

    expect(screen.getByRole("alert")).toHaveTextContent("It must not contain ${.");
    expect(password).toHaveAttribute("aria-invalid", "true");
    expect(password).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(initialized).not.toHaveBeenCalled();
  });

  it("shows the local setup requirement when the server rejects the request origin", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 403 })));
    const initialized = vi.fn();
    render(<WebuiSetupForm onInitialized={initialized} onAlreadyInitialized={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("WebUI password"), { target: { value: "secret" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Set password and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Open the localhost address");
    expect(initialized).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Set password and continue" })).toBeEnabled();
  });
});
