import { describe, expect, it, vi } from "vitest";
import { createWorkspaceDirectoryCache } from "@/lib/workspace-directory-cache";
import type { WorkspaceDirectoriesPayload } from "@/lib/types";

const directory: WorkspaceDirectoriesPayload = {
  path: "/srv/workspace", parent: "/srv", entries: [], truncated: false,
  host: "dev-server", platform: "Linux",
};

describe("workspace directory cache", () => {
  it("reuses revisited directories while separating filters and hidden-folder modes", async () => {
    const browse = vi.fn().mockResolvedValue(directory);
    const cache = createWorkspaceDirectoryCache(browse);
    await cache.load("/srv/workspace/", "", false, true);
    expect(cache.peek("/srv/workspace", "", false, true)).toBe(directory);
    await cache.load("/srv/workspace", "", false, true);
    expect(browse).toHaveBeenCalledTimes(1);
    await cache.load("/srv/workspace", "alpha", false, true);
    await cache.load("/srv/workspace", "", true, true);
    await cache.load("/srv/workspace", "", false, false);
    expect(browse).toHaveBeenCalledTimes(4);
  });

  it("evicts least recently used results and refreshes expired directory listings", async () => {
    const clock = vi.spyOn(Date, "now").mockReturnValue(1000);
    try {
      const browse = vi.fn().mockResolvedValue(directory);
      const cache = createWorkspaceDirectoryCache(browse);
      for (let i = 0; i < 64; i++) await cache.load(`/srv/${i}`, "", false);
      expect(cache.peek("/srv/0", "", false)).toBe(directory);
      await cache.load("/srv/64", "", false);
      expect(cache.peek("/srv/1", "", false)).toBeUndefined();
      expect(cache.peek("/srv/0", "", false)).toBe(directory);
      clock.mockReturnValue(31_001);
      expect(cache.peek("/srv/0", "", false)).toBeUndefined();
      await cache.load("/srv/0", "", false);
      expect(browse).toHaveBeenCalledTimes(66);
    } finally { clock.mockRestore(); }
  });

  it("shares simultaneous requests and lets failed requests be retried", async () => {
    let reject!: (reason: Error) => void;
    const browse = vi.fn().mockImplementationOnce(() => new Promise<WorkspaceDirectoriesPayload>((_resolve, fail) => { reject = fail; }))
      .mockResolvedValue(directory);
    const cache = createWorkspaceDirectoryCache(browse);
    const first = cache.load("/srv/workspace", "", false);
    expect(cache.load("/srv/workspace", "", false)).toBe(first);
    const failed = expect(first).rejects.toThrow("permission denied");
    reject(new Error("permission denied"));
    await failed;
    expect(cache.peek("/srv/workspace", "", false)).toBeUndefined();
    await expect(cache.load("/srv/workspace", "", false)).resolves.toBe(directory);
    expect(browse).toHaveBeenCalledTimes(2);
  });
});
