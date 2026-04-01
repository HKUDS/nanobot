"""
nanobot Gradio 聊天界面封装

使用方法：
    1. 安装依赖：uv pip install gradio
    2. 运行：uv run python nanobot_gradio.py
    3. 打开浏览器访问 http://localhost:7860
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import gradio as gr
from loguru import logger

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import load_config, set_config_path
from nanobot.config.schema import Config
from nanobot.cron.service import CronService
from nanobot.utils.helpers import sync_workspace_templates


# 全局状态
_global: dict[str, Any] = {}


def _make_provider(config: Config):
    """Create the appropriate LLM provider from config."""
    from nanobot.providers.base import GenerationSettings
    from nanobot.providers.registry import find_by_name

    model = config.agents.defaults.model
    provider_name = config.get_provider_name(model)
    p = config.get_provider(model)
    spec = find_by_name(provider_name) if provider_name else None
    backend = spec.backend if spec else "openai_compat"

    # --- instantiation by backend ---
    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider
        provider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
        provider = AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider
        provider = OpenAICompatProvider(
            api_key=p.api_key if p else None,
            api_base=config.get_api_base(model),
            default_model=model,
            extra_headers=p.extra_headers if p else None,
            spec=spec,
        )

    defaults = config.agents.defaults
    provider.generation = GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )
    return provider


def init_nanobot_sync(config_path: str | None = None):
    """同步初始化 nanobot 核心组件"""
    logger.info("正在初始化 nanobot...")

    # 1. 加载配置
    if config_path:
        cfg_path = Path(config_path).expanduser().resolve()
        set_config_path(cfg_path)
    config = load_config()
    workspace = config.workspace_path

    # 2. 同步工作区模板
    sync_workspace_templates(workspace)

    # 3. 初始化消息总线
    bus = MessageBus()

    # 4. 创建 Provider
    provider = _make_provider(config)

    # 5. 创建 Cron 服务
    cron_store_path = workspace / "cron" / "jobs.json"
    cron = CronService(cron_store_path)

    # 6. 创建 AgentLoop
    agent_loop = AgentLoop(
        bus=bus,
        provider=provider,
        workspace=workspace,
        model=config.agents.defaults.model,
        max_iterations=config.agents.defaults.max_tool_iterations,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        web_search_config=config.tools.web.search,
        web_proxy=config.tools.web.proxy or None,
        exec_config=config.tools.exec,
        cron_service=cron,
        restrict_to_workspace=config.tools.restrict_to_workspace,
        mcp_servers=config.tools.mcp_servers,
        channels_config=config.channels,
        timezone=config.agents.defaults.timezone,
    )

    # 存储全局状态
    _global["config"] = config
    _global["workspace"] = workspace
    _global["bus"] = bus
    _global["provider"] = provider
    _global["agent_loop"] = agent_loop
    _global["session_id"] = "gradio:direct"

    logger.info("nanobot 初始化完成！")
    return agent_loop


def save_uploaded_file(file: Any) -> str:
    """保存上传的文件到 workspace"""
    if file is None:
        return "❌ 请先选择文件"

    workspace = _global["workspace"]

    # 处理不同类型的文件对象
    if hasattr(file, 'name'):
        # Gradio 旧版本返回的是对象
        src_path = file.name
    elif isinstance(file, str):
        # Gradio 新版本返回的是路径
        src_path = file
    else:
        return "❌ 无法识别的文件格式"

    filename = Path(src_path).name
    dest_path = workspace / filename

    # 复制文件
    shutil.copy2(src_path, dest_path)
    logger.info(f"文件已保存到: {dest_path}")

    return f"✅ 文件已上传: {filename}\n📁 保存位置: {dest_path}"


def list_workspace_files() -> list[str]:
    """列出 workspace 中的文件"""
    workspace = _global["workspace"]
    files = []
    for f in workspace.iterdir():
        if f.is_file() and not f.name.startswith("."):
            files.append(f.name)
    logger.info(f"找到 {len(files)} 个文件: {files}")
    return files


def download_file(filename: str | list) -> str | None:
    """下载文件 - 复制到临时目录以避免 Gradio 路径限制"""
    # 处理可能的 list 输入
    if isinstance(filename, list):
        if len(filename) == 0:
            logger.warning("没有选择文件")
            return None
        filename = filename[0]

    if not filename:
        logger.warning("没有选择文件")
        return None

    workspace = _global["workspace"]
    src_path = workspace / filename

    if not src_path.exists():
        logger.warning(f"文件不存在: {src_path}")
        return None

    # 复制到临时目录，这样 Gradio 可以访问
    import tempfile
    temp_dir = Path(tempfile.gettempdir())
    dest_path = temp_dir / filename

    try:
        shutil.copy2(src_path, dest_path)
        logger.info(f"已复制文件到临时目录: {dest_path}")
        return str(dest_path)
    except Exception as e:
        logger.error(f"复制文件失败: {e}")
        return None


def create_demo():
    """创建 Gradio 界面 - 使用 ChatInterface"""

    def chat_fn(message: str, history: Any):
        """聊天函数"""
        agent_loop = _global["agent_loop"]
        session_id = _global["session_id"]

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            response = loop.run_until_complete(
                agent_loop.process_direct(message, session_id)
            )
            return response.content if response else "(没有回复)"
        except Exception as e:
            logger.exception("Chat failed")
            return f"❌ 错误: {str(e)}"

    with gr.Blocks(title="🚨舆情预警个人助手", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# 🚨舆情预警个人助手")
        gr.Markdown("一个舆情预警自动化处理的个人AI助手🤖")

        with gr.Row():
            # 左侧：聊天界面
            with gr.Column(scale=3):
                gr.ChatInterface(
                    fn=chat_fn,
                    title="",
                    description="",
                    examples=["你好！", "帮我写个 Python 脚本"],
                    cache_examples=False,
                )

            # 右侧：文件上传/下载
            with gr.Column(scale=1):
                gr.Markdown("## 📁 文件管理")

                # 文件上传
                gr.Markdown("### 上传文件")
                file_upload = gr.File(
                    label="上传 Excel/Word 文档",
                    file_types=[".xlsx", ".xls", ".docx", ".doc", ".csv", ".pdf", ".txt"],
                )
                upload_output = gr.Textbox(
                    label="上传状态",
                    interactive=False,
                )
                upload_btn = gr.Button("上传文件", variant="secondary")

                # 文件下载
                gr.Markdown("### 下载文件")
                filename_input = gr.Textbox(
                    label="输入文件名",
                    placeholder="例如：测试案例.xlsx",
                    interactive=True,
                )
                download_btn = gr.Button("下载文件", variant="primary")
                file_download = gr.File(
                    label="下载",
                )

        # 文件上传事件
        upload_btn.click(
            save_uploaded_file,
            inputs=[file_upload],
            outputs=[upload_output],
        )

        # 文件下载事件
        download_btn.click(
            download_file,
            inputs=[filename_input],
            outputs=[file_download],
        )

    return demo


def main():
    """主函数 - 使用同步初始化"""
    # 同步初始化
    init_nanobot_sync()

    # 获取 workspace 路径和临时目录并添加到 allowed_paths
    import tempfile
    workspace = str(_global["workspace"])
    temp_dir = tempfile.gettempdir()

    # 创建并启动 Gradio
    demo = create_demo()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        allowed_paths=[workspace, temp_dir],
    )


if __name__ == "__main__":
    main()
