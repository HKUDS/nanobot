import path from "node:path";

// Use native discovery and execution reports so test-list filtering cannot turn
// a nonempty planned shard into a successful empty or incomplete execution.
export function browserTests(report, root) {
  const tests = [];
  function visit(suite) {
    for (const spec of suite.specs ?? []) {
      const file = path.relative(root, path.resolve(report.config.rootDir, spec.file)).replaceAll("\\", "/");
      for (const test of spec.tests) {
        tests.push({ file, id: `${spec.id}:${test.projectId}` });
      }
    }
    suite.suites?.forEach(visit);
  }
  report.suites.forEach(visit);
  return tests;
}

export function verifyBrowserShard(report, expected, root) {
  const actual = browserTests(report, root).map((test) => test.id).sort();
  const wanted = expected.map((test) => test.id).sort();
  if (actual.join("\n") !== wanted.join("\n")) {
    throw new Error("Browser shard execution differs from full Playwright discovery");
  }
  console.log(`Verified all ${wanted.length} planned browser tests executed exactly once`);
}
