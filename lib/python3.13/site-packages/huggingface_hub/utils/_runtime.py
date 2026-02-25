# coding=utf-8
# Copyright 2022-present, the HuggingFace Inc. team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Check presence of installed packages at runtime."""

import importlib.metadata
import os
import platform
import sys
import warnings
from pathlib import Path
from typing import Any, Literal

from .. import __version__, constants


_PY_VERSION: str = sys.version.split()[0].rstrip("+")

_package_versions = {}

_CANDIDATES = {
    "aiohttp": {"aiohttp"},
    "fastai": {"fastai"},
    "fastapi": {"fastapi"},
    "fastcore": {"fastcore"},
    "gradio": {"gradio"},
    "graphviz": {"graphviz"},
    "hf_xet": {"hf_xet"},
    "jinja": {"Jinja2"},
    "httpx": {"httpx"},
    "keras": {"keras"},
    "numpy": {"numpy"},
    "pillow": {"Pillow"},
    "pydantic": {"pydantic"},
    "pydot": {"pydot"},
    "safetensors": {"safetensors"},
    "tensorboard": {"tensorboardX"},
    "tensorflow": (
        "tensorflow",
        "tensorflow-cpu",
        "tensorflow-gpu",
        "tf-nightly",
        "tf-nightly-cpu",
        "tf-nightly-gpu",
        "intel-tensorflow",
        "intel-tensorflow-avx512",
        "tensorflow-rocm",
        "tensorflow-macos",
    ),
    "torch": {"torch"},
}

# Check once at runtime
for candidate_name, package_names in _CANDIDATES.items():
    _package_versions[candidate_name] = "N/A"
    for name in package_names:
        try:
            _package_versions[candidate_name] = importlib.metadata.version(name)
            break
        except importlib.metadata.PackageNotFoundError:
            pass


def _get_version(package_name: str) -> str:
    return _package_versions.get(package_name, "N/A")


def is_package_available(package_name: str) -> bool:
    return _get_version(package_name) != "N/A"


# Python
def get_python_version() -> str:
    return _PY_VERSION


# Huggingface Hub
def get_hf_hub_version() -> str:
    return __version__


# aiohttp
def is_aiohttp_available() -> bool:
    return is_package_available("aiohttp")


def get_aiohttp_version() -> str:
    return _get_version("aiohttp")


# FastAI
def is_fastai_available() -> bool:
    return is_package_available("fastai")


def get_fastai_version() -> str:
    return _get_version("fastai")


# FastAPI
def is_fastapi_available() -> bool:
    return is_package_available("fastapi")


def get_fastapi_version() -> str:
    return _get_version("fastapi")


# Fastcore
def is_fastcore_available() -> bool:
    return is_package_available("fastcore")


def get_fastcore_version() -> str:
    return _get_version("fastcore")


# FastAI
def is_gradio_available() -> bool:
    return is_package_available("gradio")


def get_gradio_version() -> str:
    return _get_version("gradio")


# Graphviz
def is_graphviz_available() -> bool:
    return is_package_available("graphviz")


def get_graphviz_version() -> str:
    return _get_version("graphviz")


# httpx
def is_httpx_available() -> bool:
    return is_package_available("httpx")


def get_httpx_version() -> str:
    return _get_version("httpx")


# xet
def is_xet_available() -> bool:
    # since hf_xet is automatically used if available, allow explicit disabling via environment variable
    if constants.HF_HUB_DISABLE_XET:
        return False

    return is_package_available("hf_xet")


def get_xet_version() -> str:
    return _get_version("hf_xet")


# keras
def is_keras_available() -> bool:
    return is_package_available("keras")


def get_keras_version() -> str:
    return _get_version("keras")


# Numpy
def is_numpy_available() -> bool:
    return is_package_available("numpy")


def get_numpy_version() -> str:
    return _get_version("numpy")


# Jinja
def is_jinja_available() -> bool:
    return is_package_available("jinja")


def get_jinja_version() -> str:
    return _get_version("jinja")


# Pillow
def is_pillow_available() -> bool:
    return is_package_available("pillow")


def get_pillow_version() -> str:
    return _get_version("pillow")


# Pydantic
def is_pydantic_available() -> bool:
    if not is_package_available("pydantic"):
        return False
    # For Pydantic, we add an extra check to test whether it is correctly installed or not. If both pydantic 2.x and
    # typing_extensions<=4.5.0 are installed, then pydantic will fail at import time. This should not happen when
    # it is installed with `pip install huggingface_hub[inference]` but it can happen when it is installed manually
    # by the user in an environment that we don't control.
    #
    # Usually we won't need to do this kind of check on optional dependencies. However, pydantic is a special case
    # as it is automatically imported when doing `from huggingface_hub import ...` even if the user doesn't use it.
    #
    # See https://github.com/huggingface/huggingface_hub/pull/1829 for more details.
    try:
        from pydantic import validator  # noqa: F401
    except ImportError:
        # Example: "ImportError: cannot import name 'TypeAliasType' from 'typing_extensions'"
        warnings.warn(
            "Pydantic is installed but cannot be imported. Please check your installation. `huggingface_hub` will "
            "default to not using Pydantic. Error message: '{e}'"
        )
        return False
    return True


def get_pydantic_version() -> str:
    return _get_version("pydantic")


# Pydot
def is_pydot_available() -> bool:
    return is_package_available("pydot")


def get_pydot_version() -> str:
    return _get_version("pydot")


# Tensorboard
def is_tensorboard_available() -> bool:
    return is_package_available("tensorboard")


def get_tensorboard_version() -> str:
    return _get_version("tensorboard")


# Tensorflow
def is_tf_available() -> bool:
    return is_package_available("tensorflow")


def get_tf_version() -> str:
    return _get_version("tensorflow")


# Torch
def is_torch_available() -> bool:
    return is_package_available("torch")


def get_torch_version() -> str:
    return _get_version("torch")


# Safetensors
def is_safetensors_available() -> bool:
    return is_package_available("safetensors")


# Shell-related helpers
try:
    # Set to `True` if script is running in a Google Colab notebook.
    # If running in Google Colab, git credential store is set globally which makes the
    # warning disappear. See https://github.com/huggingface/huggingface_hub/issues/1043
    #
    # Taken from https://stackoverflow.com/a/63519730.
    _is_google_colab = "google.colab" in str(get_ipython())  # type: ignore # noqa: F821
except NameError:
    _is_google_colab = False


def is_notebook() -> bool:
    """Return `True` if code is executed in a notebook (Jupyter, Colab, QTconsole).

    Taken from https://stackoverflow.com/a/39662359.
    Adapted to make it work with Google colab as well.
    """
    try:
        shell_class = get_ipython().__class__  # type: ignore # noqa: F821
        for parent_class in shell_class.__mro__:  # e.g. "is subclass of"
            if parent_class.__name__ == "ZMQInteractiveShell":
                return True  # Jupyter notebook, Google colab or qtconsole
        return False
    except NameError:
        return False  # Probably standard Python interpreter


def is_google_colab() -> bool:
    """Return `True` if code is executed in a Google colab.

    Taken from https://stackoverflow.com/a/63519730.
    """
    return _is_google_colab


def is_colab_enterprise() -> bool:
    """Return `True` if code is executed in a Google Colab Enterprise environment."""
    return os.environ.get("VERTEX_PRODUCT") == "COLAB_ENTERPRISE"


# Check how huggingface_hub has been installed


def installation_method() -> Literal["brew", "hf_installer", "unknown"]:
    """Return the installation method of the current environment.

    - "hf_installer" if installed via the official installer script
    - "brew" if installed via Homebrew
    - "unknown" otherwise
    """
    if _is_brew_installation():
        return "brew"
    elif _is_hf_installer_installation():
        return "hf_installer"
    else:
        return "unknown"


def _is_brew_installation() -> bool:
    """Check if running from a Homebrew installation.

    Note: AI-generated by Claude.
    """
    exe_path = Path(sys.executable).resolve()
    exe_str = str(exe_path)

    # Check common Homebrew paths
    # /opt/homebrew (Apple Silicon), /usr/local (Intel)
    return "/Cellar/" in exe_str or "/opt/homebrew/" in exe_str or exe_str.startswith("/usr/local/Cellar/")


def _is_hf_installer_installation() -> bool:
    """Return `True` if the current environment was set up via the official hf installer script.

    i.e. using one of
        curl -LsSf https://hf.co/cli/install.sh | bash
        powershell -ExecutionPolicy ByPass -c "irm https://hf.co/cli/install.ps1 | iex"
    """
    venv = sys.prefix  # points to venv root if active
    marker = Path(venv) / ".hf_installer_marker"
    return marker.exists()


def dump_environment_info() -> dict[str, Any]:
    """Dump information about the machine to help debugging issues.

    Similar helper exist in:
    - `datasets` (https://github.com/huggingface/datasets/blob/main/src/datasets/commands/env.py)
    - `diffusers` (https://github.com/huggingface/diffusers/blob/main/src/diffusers/commands/env.py)
    - `transformers` (https://github.com/huggingface/transformers/blob/main/src/transformers/commands/env.py)
    """
    from huggingface_hub import get_token, whoami
    from huggingface_hub.utils import list_credential_helpers

    token = get_token()

    # Generic machine info
    info: dict[str, Any] = {
        "huggingface_hub version": get_hf_hub_version(),
        "Platform": platform.platform(),
        "Python version": get_python_version(),
    }

    # Interpreter info
    try:
        shell_class = get_ipython().__class__  # type: ignore # noqa: F821
        info["Running in iPython ?"] = "Yes"
        info["iPython shell"] = shell_class.__name__
    except NameError:
        info["Running in iPython ?"] = "No"
    info["Running in notebook ?"] = "Yes" if is_notebook() else "No"
    info["Running in Google Colab ?"] = "Yes" if is_google_colab() else "No"
    info["Running in Google Colab Enterprise ?"] = "Yes" if is_colab_enterprise() else "No"
    # Login info
    info["Token path ?"] = constants.HF_TOKEN_PATH
    info["Has saved token ?"] = token is not None
    if token is not None:
        try:
            info["Who am I ?"] = whoami()["name"]
        except Exception:
            pass

    try:
        info["Configured git credential helpers"] = ", ".join(list_credential_helpers())
    except Exception:
        pass

    # How huggingface_hub has been installed?
    info["Installation method"] = installation_method()

    # Installed dependencies
    info["httpx"] = get_httpx_version()
    info["hf_xet"] = get_xet_version()
    info["gradio"] = get_gradio_version()
    info["tensorboard"] = get_tensorboard_version()

    # Environment variables
    info["ENDPOINT"] = constants.ENDPOINT
    info["HF_HUB_CACHE"] = constants.HF_HUB_CACHE
    info["HF_ASSETS_CACHE"] = constants.HF_ASSETS_CACHE
    info["HF_TOKEN_PATH"] = constants.HF_TOKEN_PATH
    info["HF_STORED_TOKENS_PATH"] = constants.HF_STORED_TOKENS_PATH
    info["HF_HUB_OFFLINE"] = constants.HF_HUB_OFFLINE
    info["HF_HUB_DISABLE_TELEMETRY"] = constants.HF_HUB_DISABLE_TELEMETRY
    info["HF_HUB_DISABLE_PROGRESS_BARS"] = constants.HF_HUB_DISABLE_PROGRESS_BARS
    info["HF_HUB_DISABLE_SYMLINKS_WARNING"] = constants.HF_HUB_DISABLE_SYMLINKS_WARNING
    info["HF_HUB_DISABLE_EXPERIMENTAL_WARNING"] = constants.HF_HUB_DISABLE_EXPERIMENTAL_WARNING
    info["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = constants.HF_HUB_DISABLE_IMPLICIT_TOKEN
    info["HF_HUB_DISABLE_XET"] = constants.HF_HUB_DISABLE_XET
    info["HF_HUB_ETAG_TIMEOUT"] = constants.HF_HUB_ETAG_TIMEOUT
    info["HF_HUB_DOWNLOAD_TIMEOUT"] = constants.HF_HUB_DOWNLOAD_TIMEOUT
    info["HF_XET_HIGH_PERFORMANCE"] = constants.HF_XET_HIGH_PERFORMANCE

    print("\nCopy-and-paste the text below in your GitHub issue.\n")
    print("\n".join([f"- {prop}: {val}" for prop, val in info.items()]) + "\n")
    return info
