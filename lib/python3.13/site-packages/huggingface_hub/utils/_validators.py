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
"""Contains utilities to validate argument values in `huggingface_hub`."""

import inspect
import re
import warnings
from functools import wraps
from itertools import chain
from typing import Any

from huggingface_hub.errors import HFValidationError

from ._typing import CallableT


REPO_ID_REGEX = re.compile(
    r"""
    ^
    (\b[\w\-.]+\b/)? # optional namespace (username or organization)
    \b               # starts with a word boundary
    [\w\-.]{1,96}    # repo_name: alphanumeric + . _ -
    \b               # ends with a word boundary
    $
    """,
    flags=re.VERBOSE,
)


def validate_hf_hub_args(fn: CallableT) -> CallableT:
    """Validate values received as argument for any public method of `huggingface_hub`.

    The goal of this decorator is to harmonize validation of arguments reused
    everywhere. By default, all defined validators are tested.

    Validators:
        - [`~utils.validate_repo_id`]: `repo_id` must be `"repo_name"`
          or `"namespace/repo_name"`. Namespace is a username or an organization.
        - [`~utils.smoothly_deprecate_legacy_arguments`]: Ignore `proxies` when downloading files (should be set globally).

    Example:
    ```py
    >>> from huggingface_hub.utils import validate_hf_hub_args

    >>> @validate_hf_hub_args
    ... def my_cool_method(repo_id: str):
    ...     print(repo_id)

    >>> my_cool_method(repo_id="valid_repo_id")
    valid_repo_id

    >>> my_cool_method("other..repo..id")
    huggingface_hub.utils._validators.HFValidationError: Cannot have -- or .. in repo_id: 'other..repo..id'.

    >>> my_cool_method(repo_id="other..repo..id")
    huggingface_hub.utils._validators.HFValidationError: Cannot have -- or .. in repo_id: 'other..repo..id'.
    ```

    Raises:
        [`~utils.HFValidationError`]:
            If an input is not valid.
    """
    # TODO: add an argument to opt-out validation for specific argument?
    signature = inspect.signature(fn)

    @wraps(fn)
    def _inner_fn(*args, **kwargs):
        for arg_name, arg_value in chain(
            zip(signature.parameters, args),  # Args values
            kwargs.items(),  # Kwargs values
        ):
            if arg_name in ["repo_id", "from_id", "to_id"]:
                validate_repo_id(arg_value)

        kwargs = smoothly_deprecate_legacy_arguments(fn_name=fn.__name__, kwargs=kwargs)

        return fn(*args, **kwargs)

    return _inner_fn  # type: ignore


def validate_repo_id(repo_id: str) -> None:
    """Validate `repo_id` is valid.

    This is not meant to replace the proper validation made on the Hub but rather to
    avoid local inconsistencies whenever possible (example: passing `repo_type` in the
    `repo_id` is forbidden).

    Rules:
    - Between 1 and 96 characters.
    - Either "repo_name" or "namespace/repo_name"
    - [a-zA-Z0-9] or "-", "_", "."
    - "--" and ".." are forbidden

    Valid: `"foo"`, `"foo/bar"`, `"123"`, `"Foo-BAR_foo.bar123"`

    Not valid: `"datasets/foo/bar"`, `".repo_id"`, `"foo--bar"`, `"foo.git"`

    Example:
    ```py
    >>> from huggingface_hub.utils import validate_repo_id
    >>> validate_repo_id(repo_id="valid_repo_id")
    >>> validate_repo_id(repo_id="other..repo..id")
    huggingface_hub.utils._validators.HFValidationError: Cannot have -- or .. in repo_id: 'other..repo..id'.
    ```

    Discussed in https://github.com/huggingface/huggingface_hub/issues/1008.
    In moon-landing (internal repository):
    - https://github.com/huggingface/moon-landing/blob/main/server/lib/Names.ts#L27
    - https://github.com/huggingface/moon-landing/blob/main/server/views/components/NewRepoForm/NewRepoForm.svelte#L138
    """
    if not isinstance(repo_id, str):
        # Typically, a Path is not a repo_id
        raise HFValidationError(f"Repo id must be a string, not {type(repo_id)}: '{repo_id}'.")

    if repo_id.count("/") > 1:
        raise HFValidationError(
            "Repo id must be in the form 'repo_name' or 'namespace/repo_name':"
            f" '{repo_id}'. Use `repo_type` argument if needed."
        )

    if not REPO_ID_REGEX.match(repo_id):
        raise HFValidationError(
            "Repo id must use alphanumeric chars, '-', '_' or '.'."
            " The name cannot start or end with '-' or '.' and the maximum length is 96:"
            f" '{repo_id}'."
        )

    if "--" in repo_id or ".." in repo_id:
        raise HFValidationError(f"Cannot have -- or .. in repo_id: '{repo_id}'.")

    if repo_id.endswith(".git"):
        raise HFValidationError(f"Repo_id cannot end by '.git': '{repo_id}'.")


def smoothly_deprecate_legacy_arguments(fn_name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Smoothly deprecate legacy arguments in the `huggingface_hub` codebase.

    This function ignores some deprecated arguments from the kwargs and warns the user they are ignored.
    The goal is to avoid breaking existing code while guiding the user to the new way of doing things.

    List of deprecated arguments:
        - `proxies`:
            To set up proxies, user must either use the HTTP_PROXY environment variable or configure the `httpx.Client`
            manually using the [`set_client_factory`] function.

            In huggingface_hub 0.x, `proxies` was a dictionary directly passed to `requests.request`.
            In huggingface_hub 1.x, we migrated to `httpx` which does not support `proxies` the same way.
            In particular, it is not possible to configure proxies on a per-request basis. The solution is to configure
            it globally using the [`set_client_factory`] function or using the HTTP_PROXY environment variable.

            For more details, see:
            - https://www.python-httpx.org/advanced/proxies/
            - https://www.python-httpx.org/compatibility/#proxy-keys.

        - `resume_download`: deprecated without replacement. `huggingface_hub` always resumes downloads whenever possible.
        - `force_filename`: deprecated without replacement. Filename is always the same as on the Hub.
        - `local_dir_use_symlinks`: deprecated without replacement. Downloading to a local directory does not use symlinks anymore.
    """
    new_kwargs = kwargs.copy()  # do not mutate input !

    # proxies
    proxies = new_kwargs.pop("proxies", None)  # remove from kwargs
    if proxies is not None:
        warnings.warn(
            f"The `proxies` argument is ignored in `{fn_name}`. To set up proxies, use the HTTP_PROXY / HTTPS_PROXY"
            " environment variables or configure the `httpx.Client` manually using `huggingface_hub.set_client_factory`."
            " See https://www.python-httpx.org/advanced/proxies/ for more details."
        )

    # resume_download
    resume_download = new_kwargs.pop("resume_download", None)  # remove from kwargs
    if resume_download is not None:
        warnings.warn(
            f"The `resume_download` argument is deprecated and ignored in `{fn_name}`. Downloads always resume"
            " whenever possible."
        )

    # force_filename
    force_filename = new_kwargs.pop("force_filename", None)  # remove from kwargs
    if force_filename is not None:
        warnings.warn(
            f"The `force_filename` argument is deprecated and ignored in `{fn_name}`. Filename is always the same "
            "as on the Hub."
        )

    # local_dir_use_symlinks
    local_dir_use_symlinks = new_kwargs.pop("local_dir_use_symlinks", None)  # remove from kwargs
    if local_dir_use_symlinks is not None:
        warnings.warn(
            f"The `local_dir_use_symlinks` argument is deprecated and ignored in `{fn_name}`. Downloading to a local"
            " directory does not use symlinks anymore."
        )

    return new_kwargs
