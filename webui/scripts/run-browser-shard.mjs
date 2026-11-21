import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { parseArgs } from "node:util";
import { loadDurations, partitionFiles } from "./test-shards.mjs";
import { browserTests, verifyBrowserShard } from "./browser-report.mjs";

const cli = path.resolve("node_modules/@playwright/test/cli.js");

function collectFiles() {
  const env = { ...process.env };
  delete env.PLAYWRIGHT_JSON_OUTPUT_NAME;
  delete env.PLAYWRIGHT_JSON_OUTPUT_DIR;
  const collected = spawnSync("node", [cli, "test", "--list", "--reporter=json"], {
    env,
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
  });
  if (collected.error) throw collected.error;
  if (collected.status !== 0) {
    process.stderr.write(collected.stderr);
    process.stderr.write(collected.stdout);
    throw new Error("Playwright test discovery failed");
  }
  const report = JSON.parse(collected.stdout);
  const tests = browserTests(report, process.cwd());
  return { rootDir: report.config.rootDir, files: [...new Set(tests.map((test) => test.file))], tests };
}

const { values } = parseArgs({
  options: {
    shard: { type: "string" },
    list: { type: "boolean", default: false },
    trace: { type: "string", default: "retain-on-failure" },
  },
});
const match = /^([1-9]\d*)\/([1-9]\d*)$/.exec(values.shard ?? "");
if (!match) throw new Error("Use --shard=index/count, for example --shard=1/4");
const [, indexText, countText] = match;
const index = Number(indexText);
const count = Number(countText);
if (index > count) throw new Error("Shard index exceeds shard count");

const { rootDir, files, tests } = collectFiles();
const shards = partitionFiles(files, count, loadDurations());
const selected = shards[index - 1];
if (!selected.length) throw new Error("Browser shard is empty");
if (values.list) {
  console.log(JSON.stringify({ shard: index, count, files: selected }, null, 2));
} else {
  const directory = mkdtempSync(path.join(tmpdir(), "nanobot-browser-shard-"));
  try {
    const list = path.join(directory, "tests.txt");
    writeFileSync(list, selected.map((file) => path.relative(rootDir, path.resolve(file)).replaceAll("\\", "/")).join("\n"));
    console.log(`Browser shard ${index}/${count}: ${selected.length}/${files.length} files`);
    const reportFile = path.resolve(`test-results/browser/results-${index}-of-${count}.json`);
    rmSync(reportFile, { force: true });
    const result = spawnSync("node", [
      cli, "test", `--test-list=${list}`, `--trace=${values.trace}`, "--reporter=list,json",
    ], {
      stdio: "inherit",
      env: {
        ...process.env,
        PLAYWRIGHT_JSON_OUTPUT_NAME: reportFile,
      },
    });
    if (result.error) throw result.error;
    process.exitCode = result.status ?? 1;
    if (result.status === 0) {
      const selectedFiles = new Set(selected);
      verifyBrowserShard(JSON.parse(readFileSync(reportFile, "utf8")), tests.filter((test) => selectedFiles.has(test.file)), process.cwd());
    }
  } finally {
    rmSync(directory, { recursive: true });
  }
}
