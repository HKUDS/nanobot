# AGENTS.md

This document provides guidelines for agentic coding agents operating in this repository.

---

## 1. Build, Lint, and Test Commands

- **Build:**
  ```bash
  npm run build
  ```
  Compiles TypeScript sources to JavaScript in the `dist/` directory using `tsc`.

- **Start:**
  ```bash
  npm start
  ```
  Starts the compiled server from `dist/index.js`.

- **Development:**
  ```bash
  npm run dev
  ```
  Builds then starts the server for development.

- **Test:**
  No test scripts are defined in `package.json`. To add testing, configure a test framework and add a `test` script.

  *If tests are added:* To run a single test, use your test framework's respective filter or focus command, e.g., for Jest:
  ```bash
  npx jest -t 'test name'
  ```

---

## 2. Code Style Guidelines

### Imports
- Use ES Modules syntax (import/export).
- Import from specific paths (e.g., `import { something } from './module.js'`).
- Always include file extensions in imports if using ESM (e.g., `.js`).

### Formatting
- Use TypeScript with strict options enabled (`strict: true` in tsconfig).
- Indent with 2 spaces.
- Keep line length reasonable (preferably under 120 characters).
- Use semicolons consistently.
- Use blank lines to separate blocks logically.

### Types
- Define explicit interfaces for data structures.
- Use explicit types for function parameters and return values.
- Avoid `any` except when explicitly disabled by eslint for special cases.
- Prefer `unknown` over `any` when appropriate and cast carefully.
- Use TypeScript enums or unions for fixed set values where applicable.

### Naming Conventions
- Use camelCase for variables and functions.
- Use PascalCase for classes and interfaces.
- Use UPPER_CASE for constants.
- Prefix private class fields with `private` keyword.

### Error Handling
- Catch errors explicitly with try/catch blocks.
- Log errors with descriptive messages.
- On external system errors (e.g., WebSocket), log and handle gracefully.
- Send error responses with clear error messages for client communication.

### Miscellaneous
- Use modern JS/TS features as allowed by target ES2022.
- Use async/await for asynchronous operations.
- Handle process signals (`SIGINT`, `SIGTERM`) to perform graceful shutdown.

---

## 3. Cursor and Copilot Rules

- No `.cursor/rules/` or `.cursorrules` found.
- No `.github/copilot-instructions.md` found.

Agents should follow this AGENTS.md as the primary guideline.

---

*End of AGENTS.md*