/** Check client imports without loading application or channel modules. */
import { Glob } from "bun";
import { readFileSync, readdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const REPO_ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const UI_PACKAGES = ["react", "react-dom", "react-i18next", "@radix-ui", "lucide-react", "@opentui"];
const WEBUI_VIEWS = ["webui/src/components", "webui/src/hooks", "webui/src/providers"];
const TUI_VIEWS = ["tui/src/app", "tui/src/views", "tui/src/rendering", "tui/src/composer", "tui/src/menus"];
const CHANNEL_CONTRACTS = ["webui/src/channel-plugins/types.ts", "webui/src/channel-plugins/catalog.ts"];

function slash(value) {
  return value.replaceAll("\\", "/");
}

function within(value, prefix) {
  if (process.platform === "win32") {
    value = value.toLowerCase();
    prefix = prefix.toLowerCase();
  }
  return value === prefix || value.startsWith(`${prefix}/`);
}

function channelUi(value) {
  return /^nanobot\/channels\/[^/]+\/webui\//.test(process.platform === "win32" ? value.toLowerCase() : value);
}

function sourcePath(root, file) {
  return slash(path.relative(root, file));
}

function uiPackage(specifier) {
  return UI_PACKAGES.some((prefix) => within(specifier, prefix));
}

export function loadCompiler(project) {
  return createRequire(path.join(REPO_ROOT, project, "package.json"))("typescript");
}

function projectOptions(compiler, root, project) {
  const configPath = path.join(root, project, "tsconfig.json");
  const config = compiler.readConfigFile(configPath, compiler.sys.readFile);
  if (config.error) throw new Error(compiler.flattenDiagnosticMessageText(config.error.messageText, "\n"));
  const parsed = compiler.parseJsonConfigFileContent(config.config, compiler.sys, path.dirname(configPath));
  if (parsed.errors.length) {
    throw new Error(parsed.errors.map((error) => compiler.flattenDiagnosticMessageText(error.messageText, "\n")).join("\n"));
  }
  return parsed.options;
}

function targets(root, file, specifier, options, project) {
  if (specifier.startsWith(".")) return [path.resolve(path.dirname(file), specifier)];
  if (specifier.startsWith("/")) return [path.resolve(root, project, specifier.slice(1))];
  for (const [pattern, replacements] of Object.entries(options.paths ?? {})) {
    const wildcard = pattern.indexOf("*");
    const prefix = wildcard < 0 ? pattern : pattern.slice(0, wildcard);
    const suffix = wildcard < 0 ? "" : pattern.slice(wildcard + 1);
    if (wildcard < 0 ? specifier !== pattern : !specifier.startsWith(prefix) || !specifier.endsWith(suffix)) continue;
    const capture = wildcard < 0 ? "" : specifier.slice(prefix.length, specifier.length - suffix.length);
    const base = options.baseUrl ?? path.join(root, project);
    return replacements.map((replacement) => path.resolve(base, replacement.replace("*", capture)));
  }
  return [];
}

function stringValue(compiler, node) {
  return node && (compiler.isStringLiteral(node) || compiler.isNoSubstitutionTemplateLiteral(node))
    ? node.text
    : null;
}

function globTargets(compiler, argument, root, file, options, project) {
  const nodes = compiler.isArrayLiteralExpression(argument) ? argument.elements : [argument];
  const patterns = nodes.map((node) => stringValue(compiler, node));
  if (patterns.some((pattern) => pattern === null)) return [];
  const positive = [];
  const negative = [];
  for (const pattern of patterns) {
    const excluded = pattern.startsWith("!");
    for (const target of targets(root, file, excluded ? pattern.slice(1) : pattern, options, project)) {
      const relative = sourcePath(root, target);
      if (relative.startsWith("../")) throw new Error(`${sourcePath(root, file)}: glob resolves outside the repository`);
      (excluded ? negative : positive).push(new Glob(relative));
    }
  }
  const matches = new Set();
  for (const pattern of positive) {
    for (const match of pattern.scanSync({ cwd: root, onlyFiles: true })) {
      const relative = slash(match);
      if (!negative.some((excluded) => excluded.match(relative))) matches.add(relative);
    }
  }
  return [...matches];
}

export function findViolations(compiler, root, file, source, options, project) {
  const relative = sourcePath(root, file);
  const tree = compiler.createSourceFile(file, source, compiler.ScriptTarget.Latest, true);
  if (tree.parseDiagnostics.length) {
    const error = tree.parseDiagnostics[0];
    const line = tree.getLineAndCharacterOfPosition(error.start).line + 1;
    throw new Error(`${relative}:${line}: ${compiler.flattenDiagnosticMessageText(error.messageText, "\n")}`);
  }
  const violations = [];
  const reported = new Set();

  function check(specifier, target, node) {
    const rules = [];
    const targetPath = target === null ? null : sourcePath(root, target);
    if (within(relative, "packages/client-events")) {
      if ((targetPath !== null && !within(targetPath, "packages/client-events")) || uiPackage(specifier)) {
        rules.push("shared-client-contracts");
      }
    }
    if (within(relative, "tui/src/client")) {
      if (TUI_VIEWS.some((prefix) => targetPath !== null && within(targetPath, prefix)) || uiPackage(specifier)) {
        rules.push("tui-client");
      }
    }
    if (within(relative, "webui/src") && within(specifier, "pele")
      && relative !== "webui/src/components/markdown-diagrams/pele.worker.ts") {
      rules.push("diagram-worker-engine");
    }
    if (within(relative, "webui/src") && ["saxes", "css-tree"].some((name) => within(specifier, name))
      && relative !== "webui/src/components/markdown-diagrams/svg-image.ts") {
      rules.push("diagram-worker-output");
    }
    if (within(relative, "webui/src/lib") && WEBUI_VIEWS.some((prefix) => targetPath !== null && within(targetPath, prefix))) {
      rules.push("webui-lib");
    }
    const comparableTarget = process.platform === "win32" ? targetPath?.toLowerCase() : targetPath;
    if (within(relative, "webui/src/lib")
      && /^webui\/src\/i18n(?:\/index(?:\.[cm]?[jt]sx?)?)?$/.test(comparableTarget ?? "")) {
      rules.push("webui-lib-bootstrap");
    }
    if (within(relative, "webui/src/lib/format.ts") && ["i18next", "react-i18next"].includes(specifier)) {
      rules.push("pure-format-utils");
    }
    if (CHANNEL_CONTRACTS.includes(relative) && WEBUI_VIEWS.some((prefix) => targetPath !== null && within(targetPath, prefix))) {
      rules.push("channel-ui-contracts");
    }
    if (targetPath !== null) {
      const webuiSource = within(relative, "webui/src") || channelUi(relative);
      const tuiSource = within(relative, "tui/src");
      if ((webuiSource && within(targetPath, "tui"))
        || (tuiSource && (within(targetPath, "webui") || channelUi(targetPath)))) {
        rules.push("client-app-isolation");
      }
    }
    const line = tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1;
    for (const rule of rules) {
      const message = `${relative}:${line}: [${rule}] must not import ${targetPath ?? specifier}`;
      if (!reported.has(message)) {
        reported.add(message);
        violations.push(message);
      }
    }
  }

  function add(specifier, node) {
    if (specifier === null) return;
    const resolved = targets(root, file, specifier, options, project);
    if (resolved.length) {
      for (const target of resolved) check(specifier, target, node);
    } else {
      check(specifier, null, node);
    }
  }

  function visit(node) {
    if (compiler.isImportDeclaration(node) || compiler.isExportDeclaration(node)) {
      add(stringValue(compiler, node.moduleSpecifier), node);
    } else if (compiler.isImportTypeNode(node) && compiler.isLiteralTypeNode(node.argument)) {
      add(stringValue(compiler, node.argument.literal), node);
    } else if (compiler.isImportEqualsDeclaration(node) && compiler.isExternalModuleReference(node.moduleReference)) {
      add(stringValue(compiler, node.moduleReference.expression), node);
    } else if (compiler.isCallExpression(node) && node.arguments.length) {
      if (node.expression.kind === compiler.SyntaxKind.ImportKeyword
        || (compiler.isIdentifier(node.expression) && node.expression.text === "require")) {
        add(stringValue(compiler, node.arguments[0]), node);
      } else if (compiler.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === "glob"
        && compiler.isMetaProperty(node.expression.expression)
        && node.expression.expression.keywordToken === compiler.SyntaxKind.ImportKeyword) {
        for (const target of globTargets(compiler, node.arguments[0], root, file, options, project)) {
          check(target, path.join(root, target), node);
        }
      }
    }
    compiler.forEachChild(node, visit);
  }

  visit(tree);
  return violations;
}

function productionSources(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && !["tests", "__tests__"].includes(entry.name)) {
      files.push(...productionSources(path.join(directory, entry.name)));
    } else if (entry.isFile() && /\.(?:[cm]?[jt]s|[jt]sx)$/.test(entry.name) && !/\.(?:test|spec)\./.test(entry.name)) {
      files.push(path.join(directory, entry.name));
    }
  }
  return files;
}

export function findRuntimeCycles(compiler, root, project, files, options) {
  files = files.filter((file) => !/\.d\.[cm]?ts$/.test(file));
  const key = (file) => process.platform === "win32" ? path.resolve(file).toLowerCase() : path.resolve(file);
  const sources = new Map(files.map((file) => [key(file), file]));
  const graph = new Map(files.map((file) => [key(file), new Set()]));

  for (const file of files) {
    // TypeScript's emitter removes type-only dependencies, including value-spelled type imports.
    const { outputText } = compiler.transpileModule(readFileSync(file, "utf8"), {
      fileName: file,
      compilerOptions: { ...options, noEmit: false, module: compiler.ModuleKind.ESNext },
    });
    const tree = compiler.createSourceFile(file, outputText, compiler.ScriptTarget.Latest, true);
    const outgoing = graph.get(key(file));
    function add(specifier) {
      if (specifier === null) return;
      const resolved = compiler.resolveModuleName(specifier, file, options, compiler.sys).resolvedModule;
      if (resolved && sources.has(key(resolved.resolvedFileName))) outgoing.add(key(resolved.resolvedFileName));
    }
    function visit(node, deferred = false) {
      if (compiler.isImportDeclaration(node) || compiler.isExportDeclaration(node)) {
        add(stringValue(compiler, node.moduleSpecifier));
      } else if (!deferred && compiler.isCallExpression(node) && node.arguments.length
        && compiler.isIdentifier(node.expression) && node.expression.text === "require") {
        add(stringValue(compiler, node.arguments[0]));
      } else if (compiler.isCallExpression(node) && node.arguments.length > 1
        && compiler.isPropertyAccessExpression(node.expression) && node.expression.name.text === "glob"
        && compiler.isMetaProperty(node.expression.expression)
        && node.expression.expression.keywordToken === compiler.SyntaxKind.ImportKeyword) {
        const settings = node.arguments[1];
        const eager = compiler.isObjectLiteralExpression(settings) && settings.properties.some((property) =>
          compiler.isPropertyAssignment(property)
          && (compiler.isIdentifier(property.name) ? property.name.text : stringValue(compiler, property.name)) === "eager"
          && property.initializer.kind === compiler.SyntaxKind.TrueKeyword);
        if (eager) {
          for (const target of globTargets(compiler, node.arguments[0], root, file, options, project)) {
            const resolved = key(path.join(root, target));
            if (sources.has(resolved)) outgoing.add(resolved);
          }
        }
      }
      compiler.forEachChild(node, (child) => visit(child, deferred || compiler.isFunctionLike(node)));
    }
    visit(tree);
  }

  const visited = new Set();
  const active = new Map();
  const stack = [];
  const violations = [];
  function visit(file) {
    if (active.has(file)) {
      const cycle = [...stack.slice(active.get(file)), file].map((node) => sourcePath(root, sources.get(node)));
      violations.push(`${cycle[0]}: [client-runtime-cycle] eager dependencies form a cycle: ${cycle.join(" -> ")}`);
      return;
    }
    if (visited.has(file)) return;
    active.set(file, stack.length);
    stack.push(file);
    for (const target of [...graph.get(file)].sort()) visit(target);
    stack.pop();
    active.delete(file);
    visited.add(file);
  }
  for (const file of [...graph.keys()].sort()) visit(file);
  return violations;
}

export function checkRepository(compiler, root, project) {
  const options = projectOptions(compiler, root, project);
  const files = [
    ...productionSources(path.join(root, project, "src")),
    ...productionSources(path.join(root, "packages/client-events")),
  ];
  if (project === "webui") {
    const channels = path.join(root, "nanobot/channels");
    for (const entry of readdirSync(channels, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      const channelRoot = path.join(channels, entry.name);
      if (readdirSync(channelRoot).includes("webui")) files.push(...productionSources(path.join(channelRoot, "webui")));
    }
  }
  const violations = files.sort().flatMap((file) => findViolations(
    compiler, root, file, readFileSync(file, "utf8"), options, project,
  ));
  violations.push(...findRuntimeCycles(compiler, root, project, files, options));
  return { checked: files.length, violations };
}

export function main() {
  const { values } = parseArgs({
    options: { project: { type: "string" }, root: { type: "string", default: REPO_ROOT } },
  });
  if (!["webui", "tui"].includes(values.project)) throw new Error("--project must be webui or tui");
  const root = path.resolve(values.root);
  const result = checkRepository(loadCompiler(values.project), root, values.project);
  if (result.violations.length) {
    for (const violation of result.violations) console.error(violation);
    return 1;
  }
  console.log(`Client import boundaries passed (${values.project}, ${result.checked} files).`);
  return 0;
}

if (import.meta.main) {
  try {
    process.exitCode = main();
  } catch (error) {
    console.error(error.message);
    process.exitCode = 2;
  }
}
