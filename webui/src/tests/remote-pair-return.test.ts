import { afterEach, describe, expect, it, vi } from "vitest";
import { clearPairReturn, initializePairReturn, parsePairReturn, readPairReturn, subscribePairReturn } from "@/lib/remote-pair-return";

const id = "c6f4f0b0-99d2-4b90-883e-903353a4a0dc";
const code = `nbpc1.${btoa(JSON.stringify({ id, data: "encrypted" })).replace(/=+$/, "")}`;
afterEach(() => { clearPairReturn(); vi.unstubAllGlobals(); });

describe("pairing return link", () => {
  it("parses only a bounded return receipt, never a hostname or executable action", () => {
    expect(parsePairReturn(`#/remote?pairing=${code}`)).toEqual({ id, code });
    expect(parsePairReturn(`#/new?pairing=${code}`)).toBeNull();
    expect(parsePairReturn("#/remote")).toBeNull();
    for (const invalid of ["bad", "nbpc1." + "A".repeat(32769), "nbpc1.e30", code + "&pairing=" + code]) {
      expect(parsePairReturn(`#/remote?pairing=${invalid}`)).toEqual({ id: "", code: "" });
    }
  });
  it("removes fragment data before notifying the UI, without persisting it", () => {
    const replaceState = vi.fn();
    const win = { top: null as unknown, location: { hash: `#/remote?pairing=${code}`, hostname: "127.0.0.1", protocol: "http:", pathname: "/", search: "" }, history: { replaceState } };
    win.top = win;
    vi.stubGlobal("window", win);
    const listener = vi.fn(() => expect(replaceState).toHaveBeenCalledWith(null, "", "/#/remote"));
    const unsubscribe = subscribePairReturn(listener);
    initializePairReturn();
    expect(readPairReturn()).toEqual({ id, code });
    expect(listener).toHaveBeenCalledOnce();
    unsubscribe();
  });
  it.each([true, false])("rejects a non-local controller (embedded=%s)", (embedded) => {
    const win = { top: null as unknown, location: { hash: `#/remote?pairing=${code}`, hostname: embedded ? "localhost" : "example.com", protocol: "http:", pathname: "/", search: "" }, history: { replaceState: vi.fn() } };
    win.top = embedded ? {} : win;
    vi.stubGlobal("window", win);
    initializePairReturn();
    expect(win.history.replaceState).toHaveBeenCalled();
    expect(readPairReturn()).toBeNull();
  });
});
