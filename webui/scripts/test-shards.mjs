import { readFileSync } from "node:fs";

const timingsFile = new URL("../test-timings.json", import.meta.url);

/**
 * Assign every discovered file exactly once using longest-processing-time first.
 * Equal durations use path order; equal loads use file count, then shard index.
 * @param {Array<string>} files Normalized paths relative to webui/.
 * @param {number} count
 * @param {Record<string, number>} durations Durations in milliseconds.
 * @returns {Array<Array<string>>}
 */
export function partitionFiles(files, count, durations) {
  if (!Number.isInteger(count) || count < 1) {
    throw new Error("Shard count must be a positive integer");
  }
  if (new Set(files).size !== files.length) {
    throw new Error("Discovered test files contain duplicates");
  }
  const weight = (file) => {
    // New files are never selected out by a stale timing manifest.
    const duration = Object.hasOwn(durations, file) ? durations[file] : 1;
    if (!Number.isFinite(duration) || duration < 0) {
      throw new Error(`Invalid test duration for ${file}`);
    }
    return duration;
  };
  const ordered = files.map((file) => ({ file, duration: weight(file) })).sort((a, b) =>
    b.duration - a.duration || (a.file < b.file ? -1 : a.file > b.file ? 1 : 0),
  );
  const shards = Array.from({ length: count }, () => []);
  const loads = Array(count).fill(0);
  for (const { file, duration } of ordered) {
    let selected = 0;
    for (let index = 1; index < count; index += 1) {
      if (loads[index] < loads[selected]
        || (loads[index] === loads[selected] && shards[index].length < shards[selected].length)) {
        selected = index;
      }
    }
    shards[selected].push(file);
    loads[selected] += duration;
  }
  return shards;
}

/** @returns {Record<string, number>} */
export function loadDurations() {
  return JSON.parse(readFileSync(timingsFile, "utf8")).browser;
}
