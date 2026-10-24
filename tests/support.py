"""Portable configuration and process fixtures for real OMP regression tests."""
import os
from pathlib import Path
import shutil

import yaml

SRC = Path(__file__).resolve().parent.parent / "src"
OMP_BIN = shutil.which(os.environ.get("OMP_BIN", "omp"))


def write_yaml(path, data):
    if Path(path).name == "config.yml":
        data = {"memory": {"backend": "off"},
                "disabledProviders": ["ollama", "llama.cpp", "lm-studio", "apple", "local", "web"], **data}
    Path(path).write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def read_yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def isolated_env(directory):
    """Keep executable discovery, but never inherit agent/profile or user config."""
    root = Path(directory)
    home = root / "fixture-home"
    home.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items()
           if key not in ("NO_COLOR", "CI", "COLORFGBG", "OLLAMA_HOST")
           and not key.startswith(("SUPER_ENGINEERING_", "SUPERCONDUCTOR_", "ZMX_", "PI_", "OMP_", "XDG_"))
           and not any(word in key.upper() for word in ("TOKEN", "SECRET", "API_KEY", "PASSWORD", "BASE_URL"))
           and not key.upper().endswith("_KEY")}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "config"),
               XDG_DATA_HOME=str(home / "data"), XDG_CACHE_HOME=str(home / "cache"))
    return env
