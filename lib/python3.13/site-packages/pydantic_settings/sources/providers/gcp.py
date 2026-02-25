from __future__ import annotations as _annotations

import warnings
from collections.abc import Iterator, Mapping
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic.fields import FieldInfo

from ..types import SecretVersion
from .env import EnvSettingsSource

if TYPE_CHECKING:
    from google.auth import default as google_auth_default
    from google.auth.credentials import Credentials
    from google.cloud.secretmanager import SecretManagerServiceClient

    from pydantic_settings.main import BaseSettings
else:
    Credentials = None
    SecretManagerServiceClient = None
    google_auth_default = None


def import_gcp_secret_manager() -> None:
    global Credentials
    global SecretManagerServiceClient
    global google_auth_default

    try:
        from google.auth import default as google_auth_default
        from google.auth.credentials import Credentials

        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=FutureWarning)
            from google.cloud.secretmanager import SecretManagerServiceClient
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            'GCP Secret Manager dependencies are not installed, run `pip install pydantic-settings[gcp-secret-manager]`'
        ) from e


class GoogleSecretManagerMapping(Mapping[str, str | None]):
    _loaded_secrets: dict[str, str | None]
    _secret_client: SecretManagerServiceClient

    def __init__(self, secret_client: SecretManagerServiceClient, project_id: str, case_sensitive: bool) -> None:
        self._loaded_secrets = {}
        self._secret_client = secret_client
        self._project_id = project_id
        self._case_sensitive = case_sensitive

    @property
    def _gcp_project_path(self) -> str:
        return self._secret_client.common_project_path(self._project_id)

    def _select_case_insensitive_secret(self, lower_name: str, candidates: list[str]) -> str:
        if len(candidates) == 1:
            return candidates[0]

        # Sort to ensure deterministic selection (prefer lowercase / ASCII last)
        candidates.sort()
        winner = candidates[-1]
        warnings.warn(
            f"Secret collision: Found multiple secrets {candidates} normalizing to '{lower_name}'. "
            f"Using '{winner}' for case-insensitive lookup.",
            UserWarning,
            stacklevel=2,
        )
        return winner

    @cached_property
    def _secret_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        # Group secrets by normalized name to detect collisions
        normalized_groups: dict[str, list[str]] = {}

        secrets = self._secret_client.list_secrets(parent=self._gcp_project_path)
        for secret in secrets:
            name = self._secret_client.parse_secret_path(secret.name).get('secret', '')
            mapping[name] = name

            if not self._case_sensitive:
                lower_name = name.lower()
                if lower_name not in normalized_groups:
                    normalized_groups[lower_name] = []
                normalized_groups[lower_name].append(name)

        if not self._case_sensitive:
            for lower_name, candidates in normalized_groups.items():
                mapping[lower_name] = self._select_case_insensitive_secret(lower_name, candidates)

        return mapping

    @property
    def _secret_names(self) -> list[str]:
        return list(self._secret_name_map.keys())

    def _secret_version_path(self, key: str, version: str = 'latest') -> str:
        return self._secret_client.secret_version_path(self._project_id, key, version)

    def _get_secret_value(self, gcp_secret_name: str, version: str = 'latest') -> str | None:
        try:
            return self._secret_client.access_secret_version(
                name=self._secret_version_path(gcp_secret_name, version)
            ).payload.data.decode('UTF-8')
        except Exception:
            return None

    def __getitem__(self, key: str) -> str | None:
        if key in self._loaded_secrets:
            return self._loaded_secrets[key]

        gcp_secret_name = self._secret_name_map.get(key)
        if gcp_secret_name is None and not self._case_sensitive:
            gcp_secret_name = self._secret_name_map.get(key.lower())

        if gcp_secret_name:
            self._loaded_secrets[key] = self._get_secret_value(gcp_secret_name)
        else:
            raise KeyError(key)

        return self._loaded_secrets[key]

    def __len__(self) -> int:
        return len(self._secret_names)

    def __iter__(self) -> Iterator[str]:
        return iter(self._secret_names)


class GoogleSecretManagerSettingsSource(EnvSettingsSource):
    _credentials: Credentials
    _secret_client: SecretManagerServiceClient
    _project_id: str

    def __init__(
        self,
        settings_cls: type[BaseSettings],
        credentials: Credentials | None = None,
        project_id: str | None = None,
        env_prefix: str | None = None,
        env_parse_none_str: str | None = None,
        env_parse_enums: bool | None = None,
        secret_client: SecretManagerServiceClient | None = None,
        case_sensitive: bool | None = True,
    ) -> None:
        # Import Google Packages if they haven't already been imported
        if SecretManagerServiceClient is None or Credentials is None or google_auth_default is None:
            import_gcp_secret_manager()

        # If credentials or project_id are not passed, then
        # try to get them from the default function
        if not credentials or not project_id:
            _creds, _project_id = google_auth_default()

        # Set the credentials and/or project id if they weren't specified
        if credentials is None:
            credentials = _creds

        if project_id is None:
            if isinstance(_project_id, str):
                project_id = _project_id
            else:
                raise AttributeError(
                    'project_id is required to be specified either as an argument or from the google.auth.default. See https://google-auth.readthedocs.io/en/master/reference/google.auth.html#google.auth.default'
                )

        self._credentials: Credentials = credentials
        self._project_id: str = project_id

        if secret_client:
            self._secret_client = secret_client
        else:
            self._secret_client = SecretManagerServiceClient(credentials=self._credentials)

        super().__init__(
            settings_cls,
            case_sensitive=case_sensitive,
            env_prefix=env_prefix,
            env_ignore_empty=False,
            env_parse_none_str=env_parse_none_str,
            env_parse_enums=env_parse_enums,
        )

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        """Override get_field_value to get the secret value from GCP Secret Manager.
        Look for a SecretVersion metadata field to specify a particular SecretVersion.

        Args:
            field: The field to get the value for
            field_name: The declared name of the field

        Returns:
            A tuple of (value, key, value_is_complex), where `key` is the identifier used
            to populate the model (either the field name or an alias, depending on
            configuration).
        """

        secret_version = next((m.version for m in field.metadata if isinstance(m, SecretVersion)), None)

        # If a secret version is specified, try to get that specific version of the secret from
        # GCP Secret Manager via the GoogleSecretManagerMapping. This allows different versions
        # of the same secret name to be retrieved independently and cached in the GoogleSecretManagerMapping
        if secret_version and isinstance(self.env_vars, GoogleSecretManagerMapping):
            for field_key, env_name, value_is_complex in self._extract_field_info(field, field_name):
                gcp_secret_name = self.env_vars._secret_name_map.get(env_name)
                if gcp_secret_name is None and not self.case_sensitive:
                    gcp_secret_name = self.env_vars._secret_name_map.get(env_name.lower())

                if gcp_secret_name:
                    env_val = self.env_vars._get_secret_value(gcp_secret_name, secret_version)
                    if env_val is not None:
                        # If populate_by_name is enabled, return field_name to allow multiple fields
                        # with the same alias but different versions to be distinguished
                        if self.settings_cls.model_config.get('populate_by_name'):
                            return env_val, field_name, value_is_complex
                        return env_val, field_key, value_is_complex

            # If a secret version is specified but not found, we should not fall back to "latest" (default behavior)
            # as that would be incorrect. We return None to indicate the value was not found.
            return None, field_name, False

        val, key, is_complex = super().get_field_value(field, field_name)

        # If populate_by_name is enabled, we need to return the field_name as the key
        # without this being enabled, you cannot load two secrets with the same name but different versions
        if self.settings_cls.model_config.get('populate_by_name') and val is not None:
            return val, field_name, is_complex
        return val, key, is_complex

    def _load_env_vars(self) -> Mapping[str, str | None]:
        return GoogleSecretManagerMapping(
            self._secret_client, project_id=self._project_id, case_sensitive=self.case_sensitive
        )

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(project_id={self._project_id!r}, env_nested_delimiter={self.env_nested_delimiter!r})'


__all__ = ['GoogleSecretManagerSettingsSource', 'GoogleSecretManagerMapping']
