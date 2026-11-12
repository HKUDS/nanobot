import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import type { Plugin } from "vite";

import { foundationPath, type ComponentSource } from "./inventory";

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (["tests", "dev", "locales"].includes(entry.name)) return [];
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(file) : /\.tsx?$/.test(entry.name) ? [file] : [];
  });
}

function groupFor(file: string): string {
  if (file.startsWith("nanobot/channels/")) return `Channels / ${file.split("/")[2]}`;
  if (file.startsWith(foundationPath)) return "Foundations";
  if (file.includes("/settings/shared/")) return "Settings / shared";
  if (file.includes("/settings/")) return "Settings";
  if (file.includes("/thread/")) return "Conversation";
  if (file.includes("/remote/")) return "Hosts";
  if (file.includes("/workbench/")) return "Workbench";
  if (file.includes("/icons/")) return "Icons";
  return "Shared views & shell";
}

/** Index source modules and direct imports without executing application code. */
export function componentInventory(repo: string): ComponentSource[] {
  const frontend = path.join(repo, "webui/src");
  const channels = path.join(repo, "nanobot/channels");
  const channelRoots = readdirSync(channels, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .flatMap((entry) => {
      const directory = path.join(channels, entry.name);
      return readdirSync(directory, { withFileTypes: true })
        .filter((child) => child.isDirectory() && child.name === "webui")
        .map(() => path.join(directory, "webui"));
    });
  const files = [...sourceFiles(frontend), ...channelRoots.flatMap(sourceFiles)];
  const relative = (file: string) => path.relative(repo, file).split(path.sep).join("/");
  const sources = new Map(files.map((file) => [file, ts.createSourceFile(
    file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true,
  )]));
  const usedBy = new Map<string, Set<string>>();

  for (const [file, source] of sources) {
    const recordImport = (specifier: string) => {
      const target = specifier.startsWith("@/") ? path.join(frontend, specifier.slice(2))
        : specifier.startsWith(".") ? path.resolve(path.dirname(file), specifier) : undefined;
      if (!target) return;
      const resolved = [target, `${target}.tsx`, `${target}.ts`, path.join(target, "index.tsx"), path.join(target, "index.ts")]
        .find((candidate) => sources.has(candidate));
      if (!resolved) return;
      const consumers = usedBy.get(resolved) ?? new Set<string>();
      consumers.add(relative(file));
      usedBy.set(resolved, consumers);
    };
    const visit = (node: ts.Node) => {
      if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node))
        && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
        recordImport(node.moduleSpecifier.text);
      } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword
        && node.arguments[0] && ts.isStringLiteral(node.arguments[0])) {
        recordImport(node.arguments[0].text);
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
  }

  return [...sources].filter(([file]) =>
    (file.endsWith(".tsx") && file.startsWith(path.join(frontend, "components") + path.sep))
    || channelRoots.some((root) => file.startsWith(root + path.sep)
      && (file.endsWith(".tsx") || file === path.join(root, "index.ts"))))
    .map(([file, source]) => {
      const names = new Set<string>();
      for (const statement of source.statements) {
        if (ts.isExportAssignment(statement) && !statement.isExportEquals) names.add("default");
        if (ts.isExportDeclaration(statement) && !statement.isTypeOnly
          && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
          for (const item of statement.exportClause.elements) {
            if (!item.isTypeOnly) names.add(item.name.text);
          }
        }
        const modifiers = ts.canHaveModifiers(statement) ? ts.getModifiers(statement) : undefined;
        const exported = modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword);
        if (!exported) continue;
        if (modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.DefaultKeyword)) {
          names.add("default");
          continue;
        }
        if (ts.isFunctionDeclaration(statement) && statement.name) names.add(statement.name.text);
        if (ts.isVariableStatement(statement)) {
          for (const declaration of statement.declarationList.declarations) {
            if (ts.isIdentifier(declaration.name)) names.add(declaration.name.text);
          }
        }
      }
      const id = relative(file);
      return {
        path: id,
        name: path.basename(file).replace(/\.tsx?$/, ""),
        group: groupFor(id),
        exports: [...names].sort(),
        usedBy: [...(usedBy.get(file) ?? [])].sort(),
        source: source.text,
      };
    }).sort((a, b) => a.path.localeCompare(b.path));
}

/** Only Vite's development server exposes the source inventory. */
export function componentGallery(repo: string): Plugin {
  return {
    name: "nanobot-component-gallery",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use("/__nanobot_components", (_request, response) => {
        try {
          response.setHeader("Content-Type", "application/json; charset=utf-8");
          response.setHeader("Cache-Control", "no-store");
          response.end(JSON.stringify(componentInventory(repo)));
        } catch (error) {
          server.config.logger.error(String(error));
          response.statusCode = 500;
          response.end("Could not read the component inventory.");
        }
      });
    },
  };
}
