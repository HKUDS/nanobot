import { afterEach, describe, expect, it, vi } from "vitest";
import { createFilePreviewResource } from "@/lib/file-preview-resource";
import type { FilePreviewPayload } from "@/lib/types";

const payload: FilePreviewPayload = { path: "notes.txt", display_path: "notes.txt", content: "One", language: "text", truncated: false };

afterEach(() => vi.useRealTimers());

describe("session-scoped file previews", () => {
  it("shares hover and click requests, then immediately reuses a recently viewed file", async () => {
    const fetchPreview = vi.fn().mockResolvedValue(payload);
    const resource = createFilePreviewResource(fetchPreview);
    const hover = resource.load("notes.txt");
    expect(resource.load("notes.txt")).toBe(hover);
    await hover;
    expect(resource.peek("notes.txt")).toBe(payload);
    expect(await resource.load("notes.txt")).toBe(payload);
    expect(fetchPreview).toHaveBeenCalledTimes(1);
  });

  it("revalidates older content without losing the snapshot, but does not retain it forever", async () => {
    vi.useFakeTimers();
    const updated = { ...payload, content: "Two" };
    const fetchPreview = vi.fn().mockResolvedValueOnce(payload).mockResolvedValueOnce(updated);
    const resource = createFilePreviewResource(fetchPreview);
    await resource.load("notes.txt");
    vi.advanceTimersByTime(5_001);
    expect(resource.peek("notes.txt")).toBe(payload);
    expect(await resource.load("notes.txt")).toBe(updated);
    expect(fetchPreview).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(60_001);
    expect(resource.peek("notes.txt")).toBeUndefined();
  });

  it("does not hide authorization failures behind cached data and allows a retry", async () => {
    vi.useFakeTimers();
    const fetchPreview = vi.fn().mockResolvedValueOnce(payload).mockRejectedValueOnce(new Error("401")).mockResolvedValueOnce(payload);
    const resource = createFilePreviewResource(fetchPreview);
    await resource.load("notes.txt");
    vi.advanceTimersByTime(5_001);
    await expect(resource.load("notes.txt")).rejects.toThrow("401");
    expect(resource.peek("notes.txt")).toBeUndefined();
    expect(await resource.load("notes.txt")).toBe(payload);
  });

  it("bounds entries and payload bytes; late evicted requests cannot refill the cache", async () => {
    let resolve!: (value: FilePreviewPayload) => void;
    const fetchPreview = vi.fn().mockImplementationOnce(() => new Promise<FilePreviewPayload>(r => { resolve = r; })).mockResolvedValue(payload);
    const resource = createFilePreviewResource(fetchPreview);
    const late = resource.load("old.txt");
    for (let index = 0; index < 4; index++) await resource.load(`${index}.txt`);
    resolve(payload);
    await late;
    expect(resource.peek("old.txt")).toBeUndefined();
    fetchPreview.mockResolvedValueOnce({ ...payload, content: "x".repeat(4 * 1024 * 1024 + 1) });
    await resource.load("huge.txt");
    expect(resource.peek("huge.txt")).toBeUndefined();
  });

  it("never shares data between session resources or writes browser storage", async () => {
    const writes = vi.spyOn(Storage.prototype, "setItem");
    const first = createFilePreviewResource(vi.fn().mockResolvedValue(payload));
    const second = createFilePreviewResource(vi.fn().mockResolvedValue({ ...payload, content: "Second session" }));
    await first.load("notes.txt");
    expect(second.peek("notes.txt")).toBeUndefined();
    expect((await second.load("notes.txt"))).toMatchObject({ content: "Second session" });
    expect(first.peek("notes.txt")).toBe(payload);
    expect(writes).not.toHaveBeenCalled();
    writes.mockRestore();
  });
});
