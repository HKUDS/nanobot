"""Realistic autocompact test: simulate a code-exploration session going idle.

The scenario:
- User is debugging a Flask API, asks agent to explore the codebase
- Agent reads multiple files, runs shell commands
- User makes corrections, agent adapts
- Session goes idle (user leaves for 20 min)
- autocompact triggers: splits prefix/suffix, LLM-summarizes the prefix
- User comes back: summary is injected into context

We compare: prefix summary quality with vs without tool-result compression.

Requires: DEEPSEEK_API_KEY env var
Run: DEEPSEEK_API_KEY=sk-xxx .venv/bin/python tests/agent/test_tool_result_compression.py
"""

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from nanobot.agent.memory import Consolidator, MemoryStore
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.utils.prompt_templates import render_template


def _build_big_file_read(path: str, lines: int) -> str:
    """Simulate a read-tool result for a large source file."""
    content = [
        f"# File: {path}",
        f"# Size: {lines} lines",
        "",
        "import os",
        "import json",
        "from datetime import datetime",
        "from typing import Any, Optional",
        "",
    ]
    for i in range(1, lines - 6):
        # Mix of realistic code lines and data definitions
        if i % 30 == 0:
            content.append(f"# Section {i//30} — database configuration block")
        elif i % 15 == 0:
            content.append(f"DB_CONFIG_{i} = {{'host': '10.0.0.{i%255}', "
                           f"'port': 5432, 'name': 'app_db_{i}', "
                           f"'pool_size': {10 + i % 20}}}")
        elif i % 10 == 0:
            content.append(f"@app.route('/api/v{i%5}/items', methods=['GET'])")
        elif i % 7 == 0:
            content.append(f"def handler_{i}(request_id: str) -> Optional[dict]:")
        else:
            content.append(f"    # processing logic for iteration {i}")
    return "\n".join(content)


def _build_shell_output(cmd: str, records: int, *, with_errors: bool = False) -> str:
    """Simulate a shell-exec result like grep/find/log-tail output."""
    lines = [f"$ {cmd}", f"# {records} matching results", ""]
    for i in range(records):
        if with_errors and i % 20 == 19:
            lines.append(
                f"[2026-05-17 {10 + i//60:02d}:{i%60:02d}:{i%60:02d}] "
                f"ERROR worker-{i%8} Request timeout after 30s: "
                f"endpoint=/api/items/{1000+i}, client=192.168.0.{i%255}"
            )
        else:
            lines.append(
                f"[2026-05-17 {10 + i//60:02d}:{i%60:02d}:{i%60:02d}] "
                f"INFO worker-{i%8} Completed request: "
                f"status=200, duration={10 + i % 50}ms"
            )
    return "\n".join(lines)


def build_realistic_session() -> list[dict]:
    """Build a realistic multi-turn debugging session.

    Timeline:
      10:00 - User asks to debug a slow API endpoint
      10:01 - Agent reads app.py (large file)
      10:02 - Agent reads models.py (large file)
      10:03 - User corrects: "不是 model 的问题，查路由"
      10:04 - Agent reads routes.py (large file)
      10:05 - Agent runs grep on logs (large output)
      10:06 - User corrects again: "看 Nginx 日志不是应用日志"
      10:07 - Agent runs tail on nginx access.log (large output)
      10:08 - Agent finds the issue, reports back
      10:09 - User confirms solution
    """
    return [
        # Turn 1
        {"role": "user", "content": "/api/items 接口最近很慢，帮我排查一下",
         "timestamp": "2026-05-17T10:00:00"},
        {"role": "assistant", "content": "好的，让我先看一下主入口文件 app.py，了解路由挂载情况。",
         "timestamp": "2026-05-17T10:00:10", "tools_used": ["read"]},
        {"role": "tool", "content": _build_big_file_read("app.py", 200),
         "timestamp": "2026-05-17T10:00:12"},

        # Turn 2
        {"role": "assistant", "content": "app.py 中挂载了 items_bp 蓝图。让我看看 models.py，"
         "检查一下数据库查询有没有 N+1 问题。",
         "timestamp": "2026-05-17T10:01:00", "tools_used": ["read"]},
        {"role": "tool", "content": _build_big_file_read("models.py", 180),
         "timestamp": "2026-05-17T10:01:02"},

        # Turn 3 — user correction
        {"role": "user", "content": "不是 model 的问题，之前已经优化过了。问题应该出在路由层，"
         "看看 routes.py。",
         "timestamp": "2026-05-17T10:02:00"},
        {"role": "assistant", "content": "明白了，让我读 routes.py。",
         "timestamp": "2026-05-17T10:02:05", "tools_used": ["read"]},
        {"role": "tool", "content": _build_big_file_read("routes.py", 250),
         "timestamp": "2026-05-17T10:02:07"},

        # Turn 4
        {"role": "assistant", "content": "routes.py 里有 pagination 逻辑，但看起来还好。"
         "让我检查最近的请求日志，看看有没有异常。",
         "timestamp": "2026-05-17T10:03:00", "tools_used": ["shell"]},
        {"role": "tool", "content": _build_shell_output(
            "grep '/api/items' /var/log/app.log | tail -200", 150),
         "timestamp": "2026-05-17T10:03:02"},

        # Turn 5 — another user correction
        {"role": "user", "content": "不对，要看 Nginx 的 access.log，应用日志看不出延迟。",
         "timestamp": "2026-05-17T10:04:00"},
        {"role": "assistant", "content": "好的，让我查 Nginx 访问日志，重点看 /api/items 的请求耗时。",
         "timestamp": "2026-05-17T10:04:10", "tools_used": ["shell"]},
        {"role": "tool", "content": _build_shell_output(
            "tail -300 /var/log/nginx/access.log | grep '/api/items'", 200,
            with_errors=True),
         "timestamp": "2026-05-17T10:04:12"},

        # Turn 6 — agent finds the issue
        {"role": "assistant", "content": "Nginx 日志显示有几个请求耗时超过 30 秒，而且都集中在 "
         "/api/items?page=large 这种大分页请求上。routes.py 里对大 page 参数没有上限校验，"
         "导致一次查询可能扫描数万行。建议给 page 参数加个上限（比如 100）。",
         "timestamp": "2026-05-17T10:05:00"},

        # Turn 7 — user confirms
        {"role": "user", "content": "对，就是这个原因。帮我给 page 加上 100 的上限。",
         "timestamp": "2026-05-17T10:06:00"},
        {"role": "assistant", "content": "已在 routes.py 的 items_list 视图中添加 page 参数校验："
         "`page = min(int(request.args.get('page', 1)), 100)`。这样大分页请求会被自动限制。",
         "timestamp": "2026-05-17T10:06:30"},
    ]


async def run_comparison(conversation: list[dict], provider, model: str) -> None:
    sys_prompt = render_template("agent/consolidator_archive.md", strip=True)

    # Simulate autocompact _split_unconsolidated:
    # Keep last 8 messages as suffix, archive the rest
    SUFFIX_MSGS = 8
    prefix = conversation[:-SUFFIX_MSGS]
    suffix = conversation[-SUFFIX_MSGS:]

    print(f"会话总消息: {len(conversation)} 条")
    print(f"归档前缀: {len(prefix)} 条 (将被 LLM 摘要)")
    print(f"保留后缀: {len(suffix)} 条 (保持原样)")
    print()

    # Show sizes
    for i, m in enumerate(conversation):
        role = m["role"]
        size = len(m.get("content", ""))
        marker = ""
        if i >= len(prefix):
            marker = " ← 保留"
        if role == "tool" and size > Consolidator._TOOL_RESULT_MAX_CHARS:
            marker += " [巨无霸]"
        print(f"  [{i}] {role:10s} {size:>6,} chars{marker}")

    # ── Before compression ──
    before_fmt = MemoryStore._format_messages(prefix)

    # ── After compression ──
    after_msgs = Consolidator._compress_tool_results(prefix)
    after_fmt = MemoryStore._format_messages(after_msgs)

    print(f"\n归档 LLM 输入对比:")
    print(f"  压缩前: {len(before_fmt):,} chars (~{len(before_fmt)//4:,} tokens)")
    print(f"  压缩后: {len(after_fmt):,} chars (~{len(after_fmt)//4:,} tokens)")
    print(f"  节省: {(1 - len(after_fmt) / len(before_fmt)) * 100:.0f}%")

    # ── Call LLM for both ──
    print(f"\n正在调用 {model} 生成摘要对比...\n")

    t0 = time.monotonic()
    before_resp = await provider.chat_with_retry(
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": before_fmt},
        ],
        tools=None, tool_choice=None,
    )
    before_time = time.monotonic() - t0
    before_summary = before_resp.content

    t0 = time.monotonic()
    after_resp = await provider.chat_with_retry(
        model=model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": after_fmt},
        ],
        tools=None, tool_choice=None,
    )
    after_time = time.monotonic() - t0
    after_summary = after_resp.content

    # ── Results ──
    print("=" * 70)
    print("压缩前 LLM 摘要")
    print(f"输入: {len(before_fmt):,} chars, 耗时: {before_time:.1f}s")
    print("-" * 70)
    print(before_summary)

    print()
    print("=" * 70)
    print("压缩后 LLM 摘要")
    print(f"输入: {len(after_fmt):,} chars, 耗时: {after_time:.1f}s")
    print("-" * 70)
    print(after_summary)

    # ── Token cost ──
    bu = before_resp.usage or {}
    au = after_resp.usage or {}
    print()
    print("=" * 70)
    print("Token 成本")
    print("=" * 70)
    bp, bc = bu.get("prompt_tokens", 0), bu.get("completion_tokens", 0)
    ap, ac = au.get("prompt_tokens", 0), au.get("completion_tokens", 0)
    print(f"  压缩前: prompt={bp:,}, completion={bc}, total={bp + bc:,}")
    print(f"  压缩后: prompt={ap:,}, completion={ac}, total={ap + ac:,}")
    total_saved = (bp + bc) - (ap + ac)
    print(f"  节省: {total_saved:,} tokens ({(total_saved / (bp + bc) * 100):.0f}%)")

    # ── Quality comparison ──
    print()
    print("=" * 70)
    print("摘要质量对比")
    print("=" * 70)
    if before_summary and before_summary.strip() == "(nothing)":
        print("  ❌ 压缩前: LLM 被噪音淹没，返回 (nothing) — 对话信息丢失!")
    else:
        print(f"  压缩前: {len(before_summary)} chars")
    if after_summary and after_summary.strip() != "(nothing)":
        print(f"  ✅ 压缩后: {len(after_summary)} chars — 正确提取了关键事实")
        # Check key facts
        checks = [
            ("分页性能问题", any(w in after_summary for w in ["page", "分页", "pagination"])),
            ("用户纠正了排查方向", any(w in after_summary for w in ["纠", "correct", "not", "routes", "Nginx", "路由"])),
            ("Nginx 日志分析", any(w in after_summary for w in ["Nginx", "nginx", "access.log", "access"])),
            ("解决方案: page 上限", any(w in after_summary for w in ["limit", "上限", "100", "min"])),
        ]
        for label, found in checks:
            print(f"    {'✅' if found else '❌'} {label}")
    else:
        print("  ❌ 压缩后也返回 (nothing)")


async def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    api_base = os.environ.get("DEEPSEEK_API_URL", "https://api.deepseek.com")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    if not api_key:
        print("请设置 DEEPSEEK_API_KEY 环境变量")
        return

    provider = OpenAICompatProvider(api_key=api_key, api_base=api_base, default_model=model)
    conversation = build_realistic_session()
    await run_comparison(conversation, provider, model)


if __name__ == "__main__":
    asyncio.run(main())
