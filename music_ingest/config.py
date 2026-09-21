"""Runtime configuration, named profiles, and environment overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib


BASE_DIR = Path(__file__).resolve().parent.parent
LIBRARY_DIR = BASE_DIR / "library"
STAGING_DIR = BASE_DIR / "staging"
DB_PATH = BASE_DIR / "state" / "ingest.db"
DEFAULT_CONFIG_PATH = BASE_DIR / "music-ingest.toml"

ENV_PREFIX = "MUSIC_INGEST_"
PROFILE_FIELDS = {
    "library_dir", "staging_dir", "db_path", "reference_libraries", "download_timeout",
}


class ConfigurationError(ValueError):
    """Raised when a configuration file or override is invalid."""


@dataclass(frozen=True)
class Config:
    library_dir: Path = LIBRARY_DIR
    staging_dir: Path = STAGING_DIR
    db_path: Path = DB_PATH
    reference_libraries: tuple[Path, ...] = ()
    download_timeout: float = 900


def _resolve_path(value: str | os.PathLike[str], base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _profile_values(document: Mapping[str, Any], profile: str) -> Mapping[str, Any]:
    profiles = document.get("profiles", {})
    if not isinstance(profiles, dict):
        raise ConfigurationError("'profiles' must be a TOML table")
    if profile not in profiles:
        available = ", ".join(sorted(profiles)) or "none"
        raise ConfigurationError(
            f"profile {profile!r} was not found (available profiles: {available})"
        )
    values = profiles[profile]
    if not isinstance(values, dict):
        raise ConfigurationError(f"profile {profile!r} must be a TOML table")
    unknown = set(values) - PROFILE_FIELDS
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigurationError(f"profile {profile!r} has unknown settings: {names}")
    return values


def load_document(path: Path) -> dict[str, Any]:
    """Load TOML when present; a missing default file is a valid empty setup."""
    if not path.exists():
        return {}
    if not path.is_file():
        raise ConfigurationError(f"configuration path is not a file: {path}")
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"cannot read configuration {path}: {exc}") from exc


def default_profile(document: Mapping[str, Any]) -> str:
    settings = document.get("settings", {})
    if not isinstance(settings, dict):
        raise ConfigurationError("'settings' must be a TOML table")
    profile = settings.get("default_profile", "default")
    if not isinstance(profile, str) or not profile.strip():
        raise ConfigurationError("settings.default_profile must be a non-empty string")
    return profile


def build_config(
    *,
    document: Mapping[str, Any],
    profile: str,
    config_path: Path,
    environment: Mapping[str, str] | None = None,
    cli_values: Mapping[str, Any] | None = None,
) -> Config:
    """Merge defaults, profile, environment, and CLI values in that order."""
    environment = os.environ if environment is None else environment
    cli_values = {} if cli_values is None else cli_values
    values: dict[str, Any] = {
        "library_dir": LIBRARY_DIR,
        "staging_dir": STAGING_DIR,
        "db_path": DB_PATH,
        "reference_libraries": (),
        "download_timeout": 900,
    }
    if document:
        values.update(_profile_values(document, profile))

    profile_base = config_path.parent
    for name in ("library_dir", "staging_dir", "db_path"):
        values[name] = _resolve_path(values[name], profile_base)
    references = values["reference_libraries"]
    if not isinstance(references, (list, tuple)) or not all(
        isinstance(path, (str, os.PathLike)) for path in references
    ):
        raise ConfigurationError("reference_libraries must be an array of paths")
    values["reference_libraries"] = tuple(
        _resolve_path(path, profile_base) for path in references
    )

    # Environment and CLI paths are relative to the caller's working directory.
    cwd = Path.cwd()
    for name in ("library_dir", "staging_dir", "db_path"):
        env_value = environment.get(f"{ENV_PREFIX}{name.upper()}")
        if env_value:
            values[name] = _resolve_path(env_value, cwd)
    env_references = environment.get(f"{ENV_PREFIX}REFERENCE_LIBRARIES")
    if env_references is not None:
        values["reference_libraries"] = tuple(
            _resolve_path(path, cwd)
            for path in env_references.split(os.pathsep)
            if path
        )
    env_timeout = environment.get(f"{ENV_PREFIX}DOWNLOAD_TIMEOUT")
    if env_timeout is not None:
        values["download_timeout"] = env_timeout

    for name in ("library_dir", "staging_dir", "db_path"):
        if cli_values.get(name) is not None:
            values[name] = _resolve_path(cli_values[name], cwd)
    if cli_values.get("reference_libraries") is not None:
        values["reference_libraries"] = tuple(
            _resolve_path(path, cwd) for path in cli_values["reference_libraries"]
        )
    if cli_values.get("download_timeout") is not None:
        values["download_timeout"] = cli_values["download_timeout"]

    try:
        values["download_timeout"] = float(values["download_timeout"])
    except (TypeError, ValueError) as exc:
        raise ConfigurationError("download_timeout must be a number") from exc
    if not 0 < values["download_timeout"] < float("inf"):
        raise ConfigurationError("download_timeout must be finite and greater than zero")
    return Config(**values)
