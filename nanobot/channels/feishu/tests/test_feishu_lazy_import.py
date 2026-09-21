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
        "import sys; import nanobot.channels.feishu; print('lark_oapi' in sys.modules)"
    )

    assert out == "False"


def test_feishu_channel_constructor_does_not_import_lark_oapi():
    out = _run_import_probe(
        "import sys; "
        "from nanobot.bus.queue import MessageBus; "
        "from nanobot.channels.feishu.runtime import FeishuChannel; "
        "FeishuChannel({'enabled': True}, MessageBus()); "
        "print('lark_oapi' in sys.modules)"
    )

    assert out == "False"


def test_lark_runtime_thread_import_clears_sdk_import_loop():
    out = _run_import_probe(
        "import asyncio\n"
        "import sys\n"
        "import tempfile\n"
        "from pathlib import Path\n"
        "from nanobot.channels.feishu.runtime import _load_lark_runtime\n"
        "root = Path(tempfile.mkdtemp())\n"
        "pkg = root / 'lark_oapi'\n"
        "(pkg / 'ws').mkdir(parents=True)\n"
        "(pkg / 'core').mkdir(parents=True)\n"
        "(pkg / '__init__.py').write_text('class LogLevel:\\n    INFO = 20\\n')\n"
        "(pkg / 'ws' / '__init__.py').write_text('')\n"
        "(pkg / 'ws' / 'client.py').write_text('import asyncio\\nloop = asyncio.new_event_loop()\\n')\n"
        "(pkg / 'core' / '__init__.py').write_text('')\n"
        "(pkg / 'core' / 'const.py').write_text(\"FEISHU_DOMAIN = 'feishu'\\nLARK_DOMAIN = 'lark'\\n\")\n"
        "sys.path.insert(0, str(root))\n"
        "async def main():\n"
        "    await asyncio.to_thread(_load_lark_runtime)\n"
        "    import lark_oapi.ws.client as ws\n"
        "    print(getattr(ws, 'loop', 'sentinel') is None)\n"
        "asyncio.run(main())"
    )

    assert out == "True"


def test_lark_runtime_thread_import_is_serialized_for_multiple_instances():
    out = _run_import_probe(
        "import asyncio\n"
        "import sys\n"
        "import tempfile\n"
        "from pathlib import Path\n"
        "from nanobot.channels.feishu.runtime import _load_lark_runtime\n"
        "root = Path(tempfile.mkdtemp())\n"
        "pkg = root / 'lark_oapi'\n"
        "(pkg / 'ws').mkdir(parents=True)\n"
        "(pkg / 'core').mkdir(parents=True)\n"
        "(pkg / '__init__.py').write_text('class LogLevel:\\n    INFO = 20\\n')\n"
        "(pkg / 'ws' / '__init__.py').write_text('')\n"
        "(pkg / 'ws' / 'client.py').write_text(\n"
        "    'import time\\n'\n"
        "    'class ImportLoop:\\n'\n"
        "    '    closed = False\\n'\n"
        "    '    close_calls = 0\\n'\n"
        "    '    def is_running(self): return False\\n'\n"
        "    '    def is_closed(self): return self.closed\\n'\n"
        "    '    def close(self):\\n'\n"
        "    '        self.close_calls += 1\\n'\n"
        "    '        time.sleep(0.05)\\n'\n"
        "    '        if self.close_calls > 1: raise AttributeError(\"closed twice\")\\n'\n"
        "    '        self.closed = True\\n'\n"
        "    'loop = ImportLoop()\\n'\n"
        ")\n"
        "(pkg / 'core' / '__init__.py').write_text('')\n"
        "(pkg / 'core' / 'const.py').write_text(\"FEISHU_DOMAIN = 'feishu'\\nLARK_DOMAIN = 'lark'\\n\")\n"
        "sys.path.insert(0, str(root))\n"
        "async def main():\n"
        "    await asyncio.gather(*[asyncio.to_thread(_load_lark_runtime) for _ in range(8)])\n"
        "    import lark_oapi.ws.client as ws\n"
        "    print(ws.loop is None)\n"
        "asyncio.run(main())"
    )

    assert out == "True"
