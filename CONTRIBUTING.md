# Contributing to Nanobot

First off, thank you for wanting to help! Nanobot is growing fast. To keep development sustainable, we prioritize small, incremental, and well-tested changes. Our maintainers have limited bandwidth; help us help you by following these guidelines.

---

## Table of Contents
- [How to Contribute](#how-to-contribute)
- [Coding Standards](#coding-standards)
- [Testing Instructions](#testing-instructions)
- [Infrastructure Note](#infrastructure-note)
- [Suggested PR Template](#suggested-pr-template)
- [Environment Setup](#environment-setup)
- [Contribution Checklist](#contribution-checklist)
- [Review & Merge Process](#review--merge-process)
- [Communication Etiquette](#communication-etiquette)
- [Issue Reporting Guidelines](#issue-reporting-guidelines)
- [Style Guide](#style-guide)
- [Localization / Translation](#localization--translation)
- [Release Process](#release-process)
- [Code of Conduct](#code-of-conduct)
- [Getting Help](#getting-help)
- [Acknowledgements](#acknowledgements)
- [License](#license)
- [Contact](#contact)

---

## How to Contribute

### 1. Small is Beautiful
We prefer five small Pull Requests (PRs) over one massive "megabranch."
- **Focus:** One PR should solve one specific problem or add one specific feature (e.g., "Add support for X provider" or "Fix CSS alignment in Web UI").
- **Scope:** If your PR changes more than 10 files or 200 lines of code, consider breaking it up.

### 2. Asking Questions
Don't guess — ask! If you aren't sure where a new piece of infrastructure should live:
- **Open a Discussion:** Use the GitHub Discussions tab for "How do I..." or "What if..." questions.
- **Issue First:** For feature ideas, open an Issue titled `[RFC] Feature Name` (Request for Comments) before writing code. This ensures you don't build something that doesn't fit the roadmap.

### 3. Submitting Bug Fixes
When fixing a bug, use "The Scientific Method":
- **Isolate:** Provide a minimal reproduction case.
- **Test:** If possible, add a failing test case that your PR then makes pass.
- **Explain:** Tell us why the fix is necessary, not just what you changed.

---

## Do's and Don'ts

### Do's
- DO follow the existing code style (especially for the new OpenAI API channels).
- DO update the `README.md` if you add a new configuration option or environment variable.
- DO use descriptive PR titles (e.g., `feat: add MCP tool logging` or `fix: cors timeout on login`).
- DO mention if your change requires a new dependency. We want to keep Nanobot lightweight.

### Don'ts
- DON'T submit "Refactor everything" PRs. Massive structural changes are hard to review and prone to breaking things.
- DON'T include sensitive info (like API keys) in test files or logs.
- DON'T ignore the "Default Providers." If you add a feature, ensure it works with the default text and vision providers mentioned in the docs.
- DON'T push directly to the `main` branch. Always work from a fork or a feature branch.

---

## Coding Standards
- For Python code, follow [PEP8](https://peps.python.org/pep-0008/) guidelines. Use `black` for formatting.
- For TypeScript/Node code, use Prettier and ESLint as configured in the project.
- Keep code readable and well-documented. Add docstrings and comments where necessary.

---

## Testing Instructions
- Run all tests before submitting a PR.
  - Python: `pytest` or `python -m unittest`
  - Node: `npm test`
- Add new tests for new features or bug fixes when possible.
- Ensure your changes do not break existing tests.

---

## Infrastructure Note
Nanobot is still building its core "piping" (especially around the Web UI and MCP integration). If you find that the infrastructure is missing to support your idea:
- Document the missing "hook" or "endpoint."
- Submit a PR to add the infrastructure first.
- Submit a follow-up PR for the feature itself.

---

## Suggested PR Template
When you open a PR, please include:
- **Summary:** What does this change?
- **Why:** Why is this needed?
- **Testing:** How did you verify this works? (e.g., "Tested with Qwen 2-VL locally")
- **Breaking Changes:** Does this change any existing config files or APIs?

---

## Environment Setup

### 1. The "Fork and Clone" Strategy
You don't need to name your fork "PR repo." GitHub handles the relationship between your copy and the original automatically.

- **Fork the Repo:** Click the **Fork** button on the Nanobot repository. This creates a copy under your username (e.g., `your-user/nanobot`).
- **Clone Locally:**
  ```bash
  git clone https://github.com/your-user/nanobot.git
  cd nanobot
  ```
- **Add the "Upstream" Remote:** This allows you to pull in updates from the original project.
  ```bash
  git remote add upstream https://github.com/HKUDS/nanobot.git
  ```

### 2. Managing Your Branches
Never work directly on your `main` branch.
- **Keep `main` clean:** Your local `main` should only ever be a mirror of the original project's `main`.
- **Create Feature Branches:** Every time you start a new fix or feature:
  ```bash
  git checkout -b fix-mcp-connection-bug
  ```
- **Sync before a PR:** Make sure you have the latest code before submitting:
  ```bash
  git checkout main
  git pull upstream main
  git checkout fix-mcp-connection-bug
  git merge main
  ```

### 3. Local Environment Setup
- **Virtual Environments:** If Python-based, use `venv` or `conda`. If Node-based, use `nvm`.
- **Separate API Keys:** Use a "development" API key if your provider allows it, or use a local provider like [Ollama](https://ollama.com) or [LM Studio](https://lmstudio.ai) to test for free.
- **The `.env` File:** Ensure this is in your `.gitignore` so you don't accidentally upload your keys to your public fork.

---

## Contribution Checklist
Before you hit "Create Pull Request," run through this:

| Step          | Action                               | Why?                                                                                          |
|---------------|--------------------------------------|-----------------------------------------------------------------------------------------------|
| Lint/Format   | Run `npm run lint` or `black .`      | Keeps code style consistent with the maintainer's vision.                                     |
| Test          | Run the local test suite             | Ensures your "small fix" didn't break a "large feature."                                      |
| Commits       | Use "Atomic Commits"                 | Instead of one commit called "updates," use: "add login UI," "fix cors header," "update docs."|
| Screenshots   | Take a UI screenshot (if applicable) | If you changed the Web UI, maintainers love seeing it before they download it.                |

---

## Review & Merge Process
- All PRs require review by a maintainer before merging.
- Automated CI checks must pass before a PR is merged.
- PRs should be atomic and focused; large changes may be asked to be split.
- Maintainers aim to review PRs within a week, but response times may vary.

---

## Communication Etiquette
- **Draft PRs:** If working on something complex, open it as a **Draft PR**. This signals "I'm working on this, don't review it yet, but feel free to look if curious."
- **Ready for Review Ping:** Once you convert it to a real PR, leave a polite comment summarizing the impact.

---

## Issue Reporting Guidelines
Before opening a new issue:
- Search for existing issues to avoid duplicates.
- **For bug reports, include:**
  - Steps to reproduce
  - Your environment (OS, Python/Node version, etc.)
  - Relevant logs or error messages
- **For feature requests:** Explain the use case and any possible alternatives.

---

## Style Guide
- Follow [PEP8](https://peps.python.org/pep-0008/) for Python and project ESLint/Prettier rules for TypeScript/Node.
- See any additional style conventions in the `README.md` or inline documentation.

---

## Localization / Translation
If you want to help translate Nanobot:
- Check for existing translation files or documentation.
- Open an issue or PR to discuss adding new language support.

---

## Release Process
Releases are managed by maintainers. Contributors can help by:
- Testing release candidates.
- Updating documentation for new releases.
- Reporting issues found in pre-releases.

---

## Code of Conduct
Please review and follow our [Security & Conduct Policy](SECURITY.md) to ensure a welcoming and respectful environment for all contributors.

---

## Getting Help
If you need help, you can:
- Open a [GitHub Discussion](https://github.com/HKUDS/nanobot/discussions)
- Open a [GitHub Issue](https://github.com/HKUDS/nanobot/issues)
- Contact maintainers via email (see repository profile)
- Join the community chat (see [README.md](README.md) for details)

---

## Acknowledgements
Thank you to all contributors, maintainers, and sponsors who help make Nanobot better! Every contribution — large or small — is appreciated.

---

## License
This project is licensed under the terms of the [LICENSE](LICENSE) file.

---

## Contact
For questions or support, open a [GitHub Issue](https://github.com/HKUDS/nanobot/issues) or [Discussion](https://github.com/HKUDS/nanobot/discussions). You may also contact maintainers via email (see repository profile) or join our community chat (see [README.md](README.md) for details).
