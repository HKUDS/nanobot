const LANGUAGE_ALIASES: Record<string, string> = {
  cjs: "javascript",
  dockerfile: "docker",
  htm: "markup",
  html: "markup",
  js: "javascript",
  md: "markdown",
  mts: "typescript",
  py: "python",
  rb: "ruby",
  sh: "bash",
  shell: "bash",
  svg: "markup",
  ts: "typescript",
  txt: "text",
  xml: "markup",
  yml: "yaml",
  zsh: "bash",
};

const FILE_NAME_LANGUAGES: Record<string, string> = {
  "cmakelists.txt": "cmake",
  dockerfile: "docker",
  gemfile: "ruby",
  makefile: "makefile",
  procfile: "ruby",
};

const EXTENSION_LANGUAGES: Record<string, string> = {
  bash: "bash",
  c: "c",
  cc: "cpp",
  cjs: "javascript",
  conf: "text",
  cpp: "cpp",
  cs: "csharp",
  css: "css",
  cts: "typescript",
  cxx: "cpp",
  env: "bash",
  go: "go",
  h: "c",
  hpp: "cpp",
  htm: "markup",
  html: "markup",
  ini: "ini",
  java: "java",
  js: "javascript",
  json: "json",
  jsonl: "json",
  jsx: "jsx",
  kt: "kotlin",
  kts: "kotlin",
  md: "markdown",
  mdx: "markdown",
  mjs: "javascript",
  mts: "typescript",
  php: "php",
  ps1: "powershell",
  py: "python",
  pyi: "python",
  rb: "ruby",
  rs: "rust",
  scss: "scss",
  sh: "bash",
  sql: "sql",
  svg: "markup",
  svelte: "svelte",
  toml: "toml",
  ts: "typescript",
  tsx: "tsx",
  vue: "vue",
  xml: "markup",
  yaml: "yaml",
  yml: "yaml",
  zsh: "bash",
};

export function normalizeCodeLanguage(language?: string | null): string {
  const normalized = language?.trim().toLowerCase();
  if (!normalized) return "text";
  return LANGUAGE_ALIASES[normalized] ?? normalized;
}

export function codeLanguageFromPath(path?: string | null): string {
  if (!path?.trim()) return "text";
  const normalizedPath = path
    .split("?", 1)[0]!
    .split("#", 1)[0]!
    .replace(/:\d+(?::\d+)?$/, "")
    .replace(/\\/g, "/");
  const name = normalizedPath.split("/").pop()?.toLowerCase() ?? "";
  if (!name) return "text";
  if (name.startsWith("dockerfile.")) return "docker";
  const namedLanguage = FILE_NAME_LANGUAGES[name];
  if (namedLanguage) return namedLanguage;
  const extension = name.includes(".") ? name.slice(name.lastIndexOf(".") + 1) : "";
  if (!extension) return "text";
  return normalizeCodeLanguage(EXTENSION_LANGUAGES[extension] ?? extension);
}
