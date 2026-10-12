import subprocess
import sys


def test_config_base_import_does_not_load_config_schema():
    code = """
import sys
from nanobot.config_base import Base
print("nanobot.config.schema" in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "False"
