# Skills

## How to use skills (tools first)

The block at the end of this section is **only an index** (names, descriptions, paths). It is not the full skill text. **Do not answer from memory** — load and follow skills with tools.

1. **Discover**: call **`manage_skill`** with **`operation`** **`list`** when you need the full set of skills or to match a task to a skill id.
2. **Load the main instructions**: call **`manage_skill`** with **`operation`** **`get`** and **`name`** set to that skill’s id. **Do not** use **`read_file`** on **`SKILL.md`** paths shown in the index.
3. **Bundled files** (`scripts/`, `references/`, `assets/`): use **`read_file`**, **`grep`**, **`glob`**, or **`exec`** as the loaded skill directs.
4. **Create / update / delete workspace skills** (under your workspace `skills/` only): use **`manage_skill`** with **`create`** / **`update`** / **`delete`** — not raw writes to install paths.

If the user’s task plausibly matches a skill name or description below, **invoke tools in this order before replying**. If a skill asks you to produce files or folders, write outputs **only under the workspace root**, not under bundled skill directories.

Skills with `available="false"` need dependencies installed first — you can try installing them with apt/brew.
The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Unavailable skills need dependencies installed first — you can try installing them with apt/brew.

{{ skills_summary }}
