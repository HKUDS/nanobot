import { describe, expect, it } from "vitest";
import { mergeSessionReadState, parseSessionReadState, sessionReadObservation } from "../../../packages/client-events/read-state";

const state = { generation: "session-generation", latest: 8, read: 2 };

describe("session read state", () => {
  it.each([
    null, [], { ...state, generation: 1 }, { ...state, generation: " " },
    { ...state, latest: "8" }, { ...state, read: -1 }, { ...state, latest: 1.5 },
    { ...state, latest: Infinity }, { ...state, latest: Number.MAX_SAFE_INTEGER + 1 },
    { ...state, read: 9 },
  ])("rejects malformed wire progress %j", (value) => {
    expect(parseSessionReadState(value)).toBeNull();
  });

  it("accepts zero positions and safe integer positions", () => {
    expect(parseSessionReadState({ generation: "g", latest: 0, read: 0 })).toEqual({ generation: "g", latest: 0, read: 0 });
    expect(parseSessionReadState(state)).toEqual(state);
  });

  it("merges both progress positions without reverting either, and replaces a generation", () => {
    const newer = { ...state, latest: 10, read: 7 };
    expect(mergeSessionReadState(newer, state)).toBe(newer);
    expect(mergeSessionReadState(state, { ...state, latest: 7, read: 6 })).toEqual({ ...state, read: 6 });
    const reset = { generation: "new", latest: 0, read: 0 };
    expect(mergeSessionReadState(newer, reset)).toBe(reset);
  });

  it("observes only the supplied cursor, never the unrendered latest result", () => {
    expect(sessionReadObservation(state, 3)).toEqual({ generation: state.generation, cursor: 3 });
    for (const cursor of [undefined, 0, -1, 1.5, "3", 9]) expect(sessionReadObservation(state, cursor)).toBeNull();
    expect(sessionReadObservation(undefined, 3)).toBeNull();
  });
});
