import subprocess
import sys


def _run_import_probe(source: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", source],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def test_feishu_module_import_does_not_import_lark_oapi():
    out = _run_import_probe(
        "import sys; import blackcat.channels.feishu; print('lark_oapi' in sys.modules)"
    )

    assert out == "False"


def test_feishu_channel_constructor_does_not_import_lark_oapi():
    out = _run_import_probe(
        "import sys; "
        "from blackcat.bus.queue import MessageBus; "
        "from blackcat.channels.feishu import FeishuChannel; "
        "FeishuChannel({'enabled': True}, MessageBus()); "
        "print('lark_oapi' in sys.modules)"
    )

    assert out == "False"


def test_lark_runtime_thread_import_clears_sdk_import_loop():
    out = _run_import_probe(
        "import asyncio\n"
        "from blackcat.channels.feishu import _load_lark_runtime\n"
        "async def main():\n"
        "    await asyncio.to_thread(_load_lark_runtime)\n"
        "    import lark_oapi.ws.client as ws\n"
        "    print(getattr(ws, 'loop', 'sentinel') is None)\n"
        "asyncio.run(main())"
    )

    assert out == "True"
