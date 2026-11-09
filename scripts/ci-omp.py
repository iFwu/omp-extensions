"""Download or restore the pinned official OMP host used by CI."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess

REPO = Path(__file__).resolve().parents[1]


def host_asset():
    return {
        ("Linux", "x86_64"): "omp-linux-x64",
        ("Linux", "aarch64"): "omp-linux-arm64",
        ("Linux", "arm64"): "omp-linux-arm64",
        ("Darwin", "arm64"): "omp-darwin-arm64",
        ("Darwin", "x86_64"): "omp-darwin-x64",
    }[(platform.system(), platform.machine())]


def download(directory, asset, base):
    directory.mkdir(parents=True, exist_ok=True)
    for name in (asset, "SHA256SUMS.txt"):
        pending = directory / (name + ".download")
        try:
            subprocess.run([
                "curl", "--fail", "--location", "--silent", "--show-error",
                "--retry", "8", "--retry-all-errors", "--retry-delay", "10",
                "--retry-max-time", "180", "--connect-timeout", "15", "--max-time", "120",
                f"{base}/{name}", "--output", str(pending),
            ], check=True)
            pending.replace(directory / name)
        finally:
            pending.unlink(missing_ok=True)


def verify(directory, asset):
    sums = [line.split() for line in (directory / "SHA256SUMS.txt").read_text().splitlines() if line.strip()]
    matches = [digest for digest, name in sums if name.lstrip("*") == asset]
    if len(matches) != 1:
        raise ValueError(f"Missing or ambiguous checksum: {asset}")
    binary = directory / asset
    with binary.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != matches[0]:
        raise ValueError(f"Checksum mismatch: {asset}")
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    asset = host_asset()
    if args.download:
        version = json.loads((REPO / "package.json").read_text())["devDependencies"]["@oh-my-pi/pi-coding-agent"]
        download(args.directory, asset, f"https://github.com/can1357/oh-my-pi/releases/download/v{version}")
    binary = verify(args.directory, asset)
    binary.chmod(0o755)
    alias = args.directory / "omp"
    if alias.is_symlink():
        alias.unlink()
    alias.symlink_to(binary.name)
    subprocess.run([str(alias.resolve()), "--version"], check=True)


if __name__ == "__main__":
    main()
