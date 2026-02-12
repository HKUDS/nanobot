#!/usr/bin/env python3
"""Update README.md with current line counts."""

import subprocess
import re


def get_line_counts():
    result = subprocess.run(
        ["bash", "core_agent_lines.sh"], capture_output=True, text=True, cwd="."
    )
    output = result.stdout

    counts = {}
    for line in output.split("\n"):
        if match := re.search(
            r"^\s+(agent/tools/|agent/|bus/|config/|cron/|heartbeat/|session/|utils/|\(root\))\s+(\d+)",
            line,
        ):
            key = match.group(1).rstrip("/")
            counts[key] = int(match.group(2))
        elif match := re.search(r"Core total:\s+(\d+)", line):
            counts["total"] = int(match.group(1))

    return counts


def format_num(n):
    return f"{n:,}"


def update_readme(counts):
    with open("README.md", "r") as f:
        content = f.read()

    content = re.sub(
        r"<!-- LINE_COUNT_START -->.*?<!-- LINE_COUNT_END -->",
        f"""<!-- LINE_COUNT_START -->
📏 Real-time line count: **{format_num(counts["total"])} lines** (run `bash core_agent_lines.sh` to verify anytime)

<details>
<summary>📊 Line count breakdown</summary>

| Module | Lines |
|--------|-------|
| agent/ | {format_num(counts["agent"])} |
| agent/tools/ | {format_num(counts["agent/tools"])} |
| config/ | {format_num(counts["config"])} |
| cron/ | {format_num(counts["cron"])} |
| session/ | {format_num(counts["session"])} |
| heartbeat/ | {format_num(counts["heartbeat"])} |
| bus/ | {format_num(counts["bus"])} |
| utils/ | {format_num(counts["utils"])} |
| (root) | {counts["(root)"]} |
| **Core total** | **{format_num(counts["total"])}** |

*(excludes: channels/, cli/, providers/)*

</details>
<!-- LINE_COUNT_END -->""",
        content,
        flags=re.DOTALL,
    )

    with open("README.md", "w") as f:
        f.write(content)


if __name__ == "__main__":
    counts = get_line_counts()
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    update_readme(counts)
    subprocess.run(["git", "add", "README.md"])
