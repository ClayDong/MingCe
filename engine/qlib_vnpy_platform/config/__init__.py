import os
import re
import yaml
from pathlib import Path
from dotenv import load_dotenv

_CONFIG = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
CACHE_DIR = DATA_DIR / "cache"

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")


def _load_env_file():
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


def _resolve_env_vars(obj):
    if isinstance(obj, str):
        def _replace(match):
            var_name = match.group(1)
            default = match.group(2)
            return os.environ.get(var_name, default or match.group(0))
        return _ENV_VAR_PATTERN.sub(_replace, obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_vars(item) for item in obj]
    return obj


def load_config(config_path: str = None) -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    _load_env_file()

    if config_path is None:
        config_path = str(CONFIG_DIR / "settings.yaml")

    with open(config_path, "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f)

    _CONFIG = _resolve_env_vars(_CONFIG)

    for d in [DATA_DIR, LOGS_DIR, CACHE_DIR]:
        d.mkdir(parents=True, exist_ok=True)

    return _CONFIG


def get_config() -> dict:
    if _CONFIG is None:
        return load_config()
    return _CONFIG


def reload_config(config_path: str = None) -> dict:
    global _CONFIG
    _CONFIG = None
    return load_config(config_path)
