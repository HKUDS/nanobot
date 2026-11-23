import { expect, test } from "bun:test";
import { partitionFiles } from "./test-shards.mjs";

const files = ["browser/a.spec.ts", "browser/b.spec.ts", "browser/c.spec.ts", "browser/nested/d.spec.ts"];
const durations = { [files[0]]: 9, [files[1]]: 8, [files[2]]: 7, [files[3]]: 6 };

test("LPT balances measured durations without changing the inputs", () => {
  const input = Object.freeze([...files]);
  expect(partitionFiles(input, 2, Object.freeze(durations))).toEqual([
    [files[0], files[3]], [files[1], files[2]],
  ]);
  expect(input).toEqual(files);
});

test("equal loads and durations are deterministic across discovery order", () => {
  const input = ["e", "b", "d", "a", "c"];
  expect(partitionFiles(input, 2, {})).toEqual([["a", "c", "e"], ["b", "d"]]);
  expect(partitionFiles([...input].reverse(), 2, {})).toEqual(partitionFiles(input, 2, {}));
  expect(partitionFiles(input, 2, Object.fromEntries(input.map((file) => [file, 0]))))
    .toEqual([["a", "c", "e"], ["b", "d"]]);
});

test("stale timings cannot omit newly discovered tests", () => {
  const discovered = [...files, "browser/new.spec.ts", "browser/nested/new.spec.ts"];
  const shards = partitionFiles(discovered, 3, { ...durations, "browser/deleted.spec.ts": 100_000 });
  expect(shards.flat().sort()).toEqual([...discovered].sort());
  expect(new Set(shards.flat()).size).toBe(discovered.length);
  expect(partitionFiles([], 2, {})).toEqual([[], []]);
});

test("invalid counts and duplicate discovery fail explicitly", () => {
  expect(() => partitionFiles(files, 0, durations)).toThrow("positive integer");
  expect(() => partitionFiles([files[0], files[0]], 2, {})).toThrow("duplicates");
});
