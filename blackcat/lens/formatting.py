"""Lens formatting utilities."""


def format_diagnostics(diagnostics: list[dict], max_items: int = 10) -> str:
    """Format diagnostics for LLM consumption."""
    if not diagnostics:
        return "No issues found."

    severity_names = {0: "Error", 1: "Warning", 2: "Info", 3: "Hint"}

    lines = []
    for d in diagnostics[:max_items]:
        severity = d.get("severity", 0)
        severity_name = severity_names.get(severity, "Unknown")
        msg = d.get("message", "").replace("\n", " ")
        range_info = d.get("range", {})
        start = range_info.get("start", {})
        line_num = start.get("line", 0) + 1  # 1-indexed
        char_num = start.get("character", 0) + 1
        lines.append(f"- {severity_name}: line {line_num}, col {char_num}: {msg}")

    if len(diagnostics) > max_items:
        lines.append(f"- ... and {len(diagnostics) - max_items} more issues")

    return "\n".join(lines)
