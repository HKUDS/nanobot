import { afterEach, beforeEach, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { findViolations, loadCompiler } from "./check_client_import_boundaries.mjs";

const project = path.basename(process.cwd());
const compiler = loadCompiler(project);
const script = fileURLToPath(new URL("./check_client_import_boundaries.mjs", import.meta.url));
const temporaryPrefix = path.resolve(os.tmpdir(), "nanobot-client-imports-");
let root;

function write(relative, source = "export {};\n") {
  const file = path.join(root, relative);
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, source);
  return file;
}

beforeEach(() => {
  root = path.resolve(mkdtempSync(temporaryPrefix));
  for (const name of ["webui", "tui"]) {
    write(`${name}/tsconfig.json`, JSON.stringify({
      compilerOptions: { baseUrl: ".", paths: { "@/*": ["src/*"] } },
      include: ["src"],
    }));
  }
  for (const file of [
    "webui/src/lib/model.ts", "webui/src/components/View.tsx",
    "webui/src/channel-plugins/types.ts", "webui/src/channel-plugins/registry.ts",
    "tui/src/client/api.ts", "tui/src/app/app.ts",
    "packages/client-events/notifications.ts", "packages/client-events/delivery.ts",
    "nanobot/channels/example/webui/index.ts",
  ]) write(file);
});

afterEach(() => {
  if (!root.startsWith(temporaryPrefix)) throw new Error("Fixture root is outside the allocated temporary directory");
  rmSync(root, { recursive: true });
});

function inspect(relative, source) {
  return findViolations(compiler, root, path.join(root, relative), source, {
    baseUrl: path.join(root, "webui"), paths: { "@/*": ["src/*"] },
  }, relative.startsWith("tui/") ? "tui" : "webui");
}

test.each([
  'import { View } from "@/components/View";',
  'import type { View } from "../components/View";',
  'import "@/components/View";',
  'export { View } from "@/components/View";',
  'export type { View } from "@/components/View";',
  'export * from "@/components/View";',
  'type View = import("@/components/View").View;',
  'function load() { return import("@/components/View"); }',
  'const load = () => import(`@/components/View`);',
  'const view = require("@/components/View");',
])("WebUI library rejects a view dependency: %s", (source) => {
  expect(inspect("webui/src/lib/model.ts", source)).toEqual([
    "webui/src/lib/model.ts:1: [webui-lib] must not import webui/src/components/View",
  ]);
});

test.skipIf(process.platform !== "win32")("checks Windows imports that differ in directory casing", () => {
  expect(existsSync(path.join(root, "webui/src/Components/View.tsx"))).toBe(true);
  expect(inspect("webui/src/lib/model.ts", 'import type { View } from "../Components/View";')).toEqual([
    "webui/src/lib/model.ts:1: [webui-lib] must not import webui/src/Components/View",
  ]);
});

test.each([
  ["packages/client-events/notifications.ts", 'import "../../webui/src/components/View";', "shared-client-contracts"],
  ["packages/client-events/notifications.ts", 'import type { ReactNode } from "react";', "shared-client-contracts"],
  ["tui/src/client/api.ts", 'export * from "../app/app";', "tui-client"],
  ["tui/src/client/api.ts", 'import type { TextRenderable } from "@opentui/core";', "tui-client"],
  ["webui/src/channel-plugins/types.ts", 'import type { View } from "@/components/View";', "channel-ui-contracts"],
  ["webui/src/lib/model.ts", 'import "../../../tui/src/client/api";', "client-app-isolation"],
  ["tui/src/client/api.ts", 'import "../../../webui/src/lib/model";', "client-app-isolation"],
  ["webui/src/lib/model.ts", 'import "../i18n";', "webui-lib-bootstrap"],
  ["webui/src/lib/model.ts", 'import "../i18n/index.ts";', "webui-lib-bootstrap"],
  ["webui/src/lib/format.ts", 'import i18n from "i18next";', "pure-format-utils"],
])("rejects the owning boundary in %s", (relative, source, rule) => {
  expect(inspect(relative, source)).toHaveLength(1);
  expect(inspect(relative, source)[0]).toContain(`[${rule}] must not import`);
});

test.each([
  ["packages/client-events/notifications.ts", 'import "./delivery";'],
  ["tui/src/client/api.ts", 'import "../../../packages/client-events/notifications";'],
  ["webui/src/lib/model.ts", 'import "../../../packages/client-events/notifications";'],
  ["webui/src/channel-plugins/types.ts", 'import type { ComponentType } from "react";'],
])("permits the shared contract or contribution interface in %s", (relative, source) => {
  expect(inspect(relative, source)).toEqual([]);
});

test("checks Vite glob dependencies using configured aliases and extension alternatives", () => {
  expect(inspect("webui/src/lib/model.ts", 'import.meta.glob("@/components/*.{ts,tsx}", { eager: true });')).toEqual([
    "webui/src/lib/model.ts:1: [webui-lib] must not import webui/src/components/View.tsx",
  ]);
});

test("respects Vite glob exclusions", () => {
  expect(inspect("webui/src/lib/model.ts", 'import.meta.glob(["../components/*.{ts,tsx}", "!../components/**"]);')).toEqual([]);
});

test("permits channel registry composition through a Vite glob", () => {
  expect(inspect("webui/src/channel-plugins/registry.ts", 'import.meta.glob("../../../nanobot/channels/*/webui/index.{ts,tsx}", { eager: true });')).toEqual([]);
});

test("includes nested dynamic import locations in diagnostics", () => {
  expect(inspect("webui/src/lib/model.ts", 'export async function load() {\n  return import("@/components/View");\n}')).toEqual([
    "webui/src/lib/model.ts:2: [webui-lib] must not import webui/src/components/View",
  ]);
});

function run() {
  return Bun.spawnSync([process.execPath, script, "--project", project, "--root", root], {
    cwd: process.cwd(), stdout: "pipe", stderr: "pipe",
  });
}

test("CLI accepts a repository with valid client and shared dependencies", () => {
  const result = run();
  expect(result.exitCode).toBe(0);
  expect(new TextDecoder().decode(result.stdout)).toContain(`Client import boundaries passed (${project},`);
});

test("CLI rejects a client violation with its source location", () => {
  const relative = project === "webui" ? "webui/src/lib/model.ts" : "tui/src/client/api.ts";
  const target = project === "webui" ? "@/components/View" : "../app/app";
  write(relative, `export async function load() {\n  return import("${target}");\n}\n`);
  const result = run();
  expect(result.exitCode).toBe(1);
  expect(new TextDecoder().decode(result.stderr)).toContain(`${relative}:2:`);
});

test("CLI rejects a shared contract that acquires a UI dependency", () => {
  write("packages/client-events/notifications.ts", 'import type { ReactNode } from "react";\n');
  const result = run();
  expect(result.exitCode).toBe(1);
  expect(new TextDecoder().decode(result.stderr)).toContain("packages/client-events/notifications.ts:1: [shared-client-contracts] must not import react");
});

test("ignores test modules in production source scans", () => {
  const relative = project === "webui" ? "webui/src/lib/model.test.ts" : "tui/src/client/api.test.ts";
  write(relative, 'import "../../../webui/src/components/View";\n');
  const result = run();
  expect(result.exitCode).toBe(0);
});

test("checks the actual shared source directory rather than a fixture inventory", () => {
  write("packages/client-events/new-event.ts", 'export * from "../../tui/src/app/app";\n');
  const result = run();
  expect(result.exitCode).toBe(1);
  expect(new TextDecoder().decode(result.stderr)).toContain("new-event.ts:1: [shared-client-contracts]");
});

test("CLI detects a runtime cycle through a barrel re-export", () => {
  const directory = `${project}/src/${project === "webui" ? "components" : "app"}`;
  write(`${directory}/a.ts`, 'import { value } from "./barrel"; export const first = () => value;\n');
  write(`${directory}/barrel.ts`, 'export { value } from "./b";\n');
  write(`${directory}/b.ts`, 'import { first } from "./a"; export const value = () => first;\n');
  const result = run();
  expect(result.exitCode).toBe(1);
  const diagnostic = new TextDecoder().decode(result.stderr);
  expect(diagnostic).toContain("[client-runtime-cycle]");
  for (const file of ["a.ts", "barrel.ts", "b.ts"]) expect(diagnostic).toContain(`${directory}/${file}`);
});

test("CLI permits erased type imports and deferred dynamic imports", () => {
  const directory = `${project}/src/${project === "webui" ? "components" : "app"}`;
  write(`${directory}/a.ts`, 'import { Item } from "./b"; export const first = (item: Item) => item;\n');
  write(`${directory}/b.ts`, 'import { first } from "./a"; export type Item = string; export const second = first;\n');
  write(`${directory}/lazy.ts`, 'export const load = () => import("./owner");\n');
  write(`${directory}/owner.ts`, 'import { load } from "./lazy"; export const owner = load;\n');
  write(`${project}/src/vite-env.d.ts`, 'declare module "virtual:example" { export const value: string; }\n');
  expect(run().exitCode).toBe(0);
});

test("CLI detects eager literal require cycles and permits function-local require", () => {
  const directory = `${project}/src/${project === "webui" ? "components" : "app"}`;
  write(`${directory}/a.ts`, 'export const first = require("./b");\n');
  write(`${directory}/b.ts`, 'export const second = require("./a");\n');
  const result = run();
  expect(result.exitCode).toBe(1);
  expect(new TextDecoder().decode(result.stderr)).toContain("[client-runtime-cycle]");
  write(`${directory}/a.ts`, 'export const first = () => require("./b");\n');
  expect(run().exitCode).toBe(0);
});

test.skipIf(project !== "webui")("CLI detects an eager Vite registry cycle and permits its lazy form", () => {
  write("webui/src/channel-plugins/registry.ts", 'export const plugins = import.meta.glob("../../../nanobot/channels/*/webui/index.ts", { "eager": true });\n');
  write("nanobot/channels/example/webui/index.ts", 'import { plugins } from "../../../../webui/src/channel-plugins/registry"; export default plugins;\n');
  const result = run();
  expect(result.exitCode).toBe(1);
  expect(new TextDecoder().decode(result.stderr)).toContain("[client-runtime-cycle]");
  write("webui/src/channel-plugins/registry.ts", 'export const plugins = import.meta.glob("../../../nanobot/channels/*/webui/index.ts");\n');
  expect(run().exitCode).toBe(0);
});
