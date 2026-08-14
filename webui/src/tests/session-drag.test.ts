import { describe, expect, it, vi } from "vitest";

import {
  clearDraggedSession,
  clearDraggedWorkbenchGroup,
  writeDraggedSession,
  writeDraggedWorkbenchGroup,
} from "@/lib/session-drag";

function createDataTransfer(): DataTransfer {
  return {
    effectAllowed: "none",
    setData: vi.fn(),
  } as unknown as DataTransfer;
}

describe("session drag protocol", () => {
  it("allows session copies while keeping workbench groups move-only", () => {
    const sessionTransfer = createDataTransfer();
    writeDraggedSession(sessionTransfer, "websocket:session");
    expect(sessionTransfer.effectAllowed).toBe("copyMove");
    clearDraggedSession();

    const groupTransfer = createDataTransfer();
    writeDraggedWorkbenchGroup(groupTransfer, "tab:group");
    expect(groupTransfer.effectAllowed).toBe("move");
    clearDraggedWorkbenchGroup();
  });
});
