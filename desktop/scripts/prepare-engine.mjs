#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import {
  cp,
  lstat,
  mkdir,
  readdir,
  readFile,
  readlink,
  rm,
  stat,
  symlink,
  unlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..", "..");
const desktopRoot = path.resolve(__dirname, "..");
const engineDest = path.resolve(
  process.env.NANOBOT_ENGINE_DEST ?? path.join(desktopRoot, "resources", "nanobot-engine"),
);
const pythonVersion = process.env.NANOBOT_DESKTOP_PYTHON_VERSION ?? "3.12";
const githubBase = "https://github.com/astral-sh/python-build-standalone";

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed`);
  }
}

async function download(url, destination) {
  const response = await fetch(url, {
    headers: {
      "User-Agent": "nanobot/desktop-build",
    },
  });
  if (!response.ok) {
    throw new Error(`failed to download ${url}: HTTP ${response.status}`);
  }
  await writeFile(destination, Buffer.from(await response.arrayBuffer()));
}

async function fetchText(url) {
  const response = await fetch(url, {
    headers: {
      "User-Agent": "nanobot/desktop-build",
      "Accept": "text/html",
    },
  });
  if (!response.ok) {
    throw new Error(`failed to fetch ${url}: HTTP ${response.status}`);
  }
  return await response.text();
}

function targetTriple() {
  const requested = process.env.NANOBOT_DESKTOP_ARCH ?? process.arch;
  if (requested === "arm64" || requested === "aarch64") return "aarch64-apple-darwin";
  if (requested === "x64" || requested === "x86_64") return "x86_64-apple-darwin";
  throw new Error(`unsupported desktop engine arch: ${requested}`);
}

function latestReleaseTag(html) {
  const match = html.match(/\/astral-sh\/python-build-standalone\/releases\/tag\/(\d{8})/);
  if (!match) {
    throw new Error("could not find latest python-build-standalone release tag");
  }
  return match[1];
}

async function defaultStandaloneUrl() {
  const release =
    process.env.PYTHON_STANDALONE_RELEASE
    ?? latestReleaseTag(await fetchText(`${githubBase}/releases`));
  const triple = targetTriple();
  const assetHtml = await fetchText(`${githubBase}/releases/expanded_assets/${release}`);
  const escapedVersion = pythonVersion.replace(".", "\\.");
  const assetPattern = new RegExp(
    `cpython-${escapedVersion}\\.\\d+\\+${release}-${triple}-install_only\\.tar\\.gz`,
  );
  const asset = assetHtml.match(assetPattern)?.[0];
  if (!asset) {
    throw new Error(
      `could not find a CPython ${pythonVersion} install_only asset for ${triple} in ${release}`,
    );
  }
  return `${githubBase}/releases/download/${release}/${asset}`;
}

async function walk(dir, matches = []) {
  for (const entry of await readdir(dir)) {
    const fullPath = path.join(dir, entry);
    const info = await stat(fullPath);
    if (info.isDirectory()) {
      await walk(fullPath, matches);
    } else if (entry === "python3" || entry === "python") {
      matches.push(fullPath);
    }
  }
  return matches;
}

async function findStandaloneRoot(extractDir) {
  const candidates = await walk(extractDir);
  for (const candidate of candidates) {
    const normalized = candidate.split(path.sep).join("/");
    if (normalized.endsWith("/install/bin/python3")) {
      return path.dirname(path.dirname(candidate));
    }
  }
  for (const candidate of candidates) {
    const parent = path.dirname(candidate);
    if (path.basename(parent) === "bin") {
      return path.dirname(parent);
    }
  }
  throw new Error("could not find python-build-standalone bin/python3 in extracted archive");
}

function isInside(parent, child) {
  const relative = path.relative(parent, child);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

async function rewriteInternalSymlinks(root, sourceRoot) {
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(root, entry.name);
    const info = await lstat(fullPath);
    if (info.isSymbolicLink()) {
      const target = await readlink(fullPath);
      if (!path.isAbsolute(target) || !isInside(sourceRoot, target)) {
        continue;
      }
      const targetInBundle = path.join(engineDest, path.relative(sourceRoot, target));
      const relativeTarget = path.relative(path.dirname(fullPath), targetInBundle);
      await unlink(fullPath);
      await symlink(relativeTarget, fullPath);
    } else if (entry.isDirectory()) {
      await rewriteInternalSymlinks(fullPath, sourceRoot);
    }
  }
}

async function assertNoExternalSymlinks(root) {
  const entries = await readdir(root, { withFileTypes: true });
  for (const entry of entries) {
    const fullPath = path.join(root, entry.name);
    const info = await lstat(fullPath);
    if (info.isSymbolicLink()) {
      const target = await readlink(fullPath);
      if (path.isAbsolute(target) && !isInside(engineDest, target)) {
        throw new Error(`external symlink left in engine bundle: ${fullPath} -> ${target}`);
      }
    } else if (entry.isDirectory()) {
      await assertNoExternalSymlinks(fullPath);
    }
  }
}

async function tarSupportsZstd() {
  const result = spawnSync("tar", ["--help"], { encoding: "utf8" });
  return `${result.stdout}\n${result.stderr}`.includes("zstd");
}

async function extractArchive(archive, destination) {
  await mkdir(destination, { recursive: true });
  if (archive.endsWith(".tar.zst") && !(await tarSupportsZstd())) {
    throw new Error("tar.zst archives require a tar build with zstd support");
  }
  run("tar", ["-xf", archive, "-C", destination]);
}

async function resolveArchive() {
  const localArchive = process.env.PYTHON_STANDALONE_TARBALL;
  if (localArchive) {
    return { archive: path.resolve(localArchive), cleanupArchive: false };
  }

  const url = process.env.PYTHON_STANDALONE_URL ?? await defaultStandaloneUrl();
  const suffix = url.endsWith(".tar.gz") ? ".tar.gz" : path.extname(url);
  const downloadPath = path.join(tmpdir(), `nanobot-python-${Date.now()}${suffix}`);
  console.log(`Downloading Python runtime from ${url}`);
  await download(url, downloadPath);
  return { archive: downloadPath, cleanupArchive: true };
}

async function installNanobot(pythonPath) {
  run(pythonPath, ["-m", "ensurepip", "--upgrade"]);
  run(pythonPath, ["-m", "pip", "install", "--upgrade", "pip"]);

  const installArgs = ["-m", "pip", "install", "--upgrade"];
  const wheelhouse = process.env.NANOBOT_WHEELHOUSE;
  if (wheelhouse) {
    installArgs.push("--no-index", "--find-links", path.resolve(wheelhouse));
  }
  installArgs.push(`${repoRoot}[api]`);
  run(pythonPath, installArgs);
}

async function writeManifest(pythonPath) {
  const version = spawnSync(pythonPath, ["--version"], { encoding: "utf8" });
  const pyproject = await readFile(path.join(repoRoot, "pyproject.toml"), "utf8");
  const match = pyproject.match(/^version\s*=\s*"([^"]+)"/m);
  await writeFile(
    path.join(engineDest, "nanobot-engine.json"),
    JSON.stringify(
      {
        python: version.stdout.trim() || version.stderr.trim(),
        nanobot_version: match?.[1] ?? "unknown",
        prepared_at: new Date().toISOString(),
        source: "python-build-standalone",
      },
      null,
      2,
    ),
    "utf8",
  );
}

async function main() {
  if (process.argv.includes("--print-runtime-url")) {
    console.log(await defaultStandaloneUrl());
    return;
  }

  const { archive, cleanupArchive } = await resolveArchive();
  const extractDir = path.join(tmpdir(), `nanobot-engine-${Date.now()}`);
  try {
    await rm(extractDir, { recursive: true, force: true });
    await extractArchive(archive, extractDir);

    const standaloneRoot = await findStandaloneRoot(extractDir);
    await rm(engineDest, { recursive: true, force: true });
    await mkdir(path.dirname(engineDest), { recursive: true });
    await cp(standaloneRoot, engineDest, { recursive: true });
    await rewriteInternalSymlinks(engineDest, standaloneRoot);
    await assertNoExternalSymlinks(engineDest);

    const pythonPath = path.join(engineDest, "bin", "python3");
    await installNanobot(pythonPath);
    await writeManifest(pythonPath);
    await writeFile(path.join(engineDest, ".gitkeep"), "", "utf8");
    console.log(`Prepared nanobot desktop engine at ${engineDest}`);
  } finally {
    await rm(extractDir, { recursive: true, force: true });
    if (cleanupArchive) {
      await rm(archive, { force: true });
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
