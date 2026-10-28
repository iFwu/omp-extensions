"""Portable configuration and process fixtures for real OMP regression tests."""
import json
import os
from pathlib import Path
import shutil

import yaml

OMP_BIN = shutil.which(os.environ.get("OMP_BIN", "omp"))


def extension_path(package, module="index.ts"):
    return Path(__file__).resolve().parents[1] / "packages" / package / "src" / module


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


def set_grouping_time(directory, milliseconds):
    """Advance only the grouping clock, atomically across fixture processes."""
    root = Path(directory)
    pending = root / "grouping-clock.pending"
    pending.write_text(str(milliseconds), encoding="utf-8")
    pending.replace(root / "grouping-clock.json")


def write_grouping_clock(directory):
    """Load the real extension with a controllable clock; host timers stay real."""
    root = Path(directory).resolve()
    set_grouping_time(root, 0)
    wrapper = root / "grouping-clock.ts"
    # Relative imports keep the source inside OMP's SDK-shim module graph.
    source = "./" + Path(os.path.relpath(extension_path("transcript-grouping").resolve(), root)).as_posix()
    wrapper.write_text(
        'import { readFileSync, writeFileSync, renameSync } from "node:fs";\n'
        'import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";\n'
        f'import grouping from {json.dumps(source)};\n'
        'const clock = new URL("./grouping-clock.json", import.meta.url);\n'
        'export function setGroupingTime(milliseconds: number) {\n'
        '  const pending = new URL("./grouping-clock.pending", import.meta.url);\n'
        '  writeFileSync(pending, String(milliseconds));\n'
        '  renameSync(pending, clock);\n'
        '}\n'
        'export default function (pi: ExtensionAPI) {\n'
        '  grouping(pi, () => Number(readFileSync(clock, "utf8")));\n'
        '}\n', encoding="utf-8")
    return wrapper
