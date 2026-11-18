import { expect, test } from "bun:test";
import path from "node:path";
import { browserTests, verifyBrowserShard } from "./browser-report.mjs";

const root = path.resolve("webui-fixture");
const spec = (id, file) => ({ id, file, tests: [{ projectId: "chromium" }] });
function report(specs) {
  return { config: { rootDir: path.join(root, "browser") }, suites: [{ suites: [{ specs }] }] };
}

const specs = [spec("first", "nested/first.spec.ts"), spec("second", "second.spec.ts")];
const expected = [
  { file: "browser/nested/first.spec.ts", id: "first:chromium" },
  { file: "browser/second.spec.ts", id: "second:chromium" },
];

test("native nested reports retain file and project identities in discovery and execution", () => {
  expect(browserTests(report(specs), root)).toEqual(expected);
  expect(() => verifyBrowserShard(report([...specs].reverse()), expected, root)).not.toThrow();
});

test("an empty or partially filtered browser shard cannot pass", () => {
  expect(() => verifyBrowserShard(report([]), expected, root)).toThrow("differs");
  expect(() => verifyBrowserShard(report(specs.slice(0, 1)), expected, root)).toThrow("differs");
});

test("running a test twice cannot replace another planned test", () => {
  expect(() => verifyBrowserShard(report([specs[0], specs[0]]), expected, root)).toThrow("differs");
});
