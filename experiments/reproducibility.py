"""Shared provenance metadata for Buckaroo experiment artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from importlib import metadata
from pathlib import Path
import platform
import subprocess
from typing import Iterable


TRACKED_PACKAGES = ("pandas", "numpy", "scipy", "scikit-learn", "datasketch")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(repo_root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def capture_reproducibility(
    repo_root: Path,
    dataset_paths: Iterable[Path] = (),
) -> dict[str, object]:
    """Capture enough metadata to reproduce and audit one experiment run."""
    package_versions: dict[str, str | None] = {}
    for package in TRACKED_PACKAGES:
        try:
            package_versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            package_versions[package] = None

    datasets = []
    for raw_path in sorted({Path(path).resolve() for path in dataset_paths}, key=str):
        entry: dict[str, object] = {"path": str(raw_path), "exists": raw_path.is_file()}
        if raw_path.is_file():
            entry.update(
                {
                    "size_bytes": raw_path.stat().st_size,
                    "sha256": sha256_file(raw_path),
                }
            )
        datasets.append(entry)

    status = _git_value(repo_root, "status", "--porcelain")
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_value(repo_root, "rev-parse", "HEAD"),
        "git_branch": _git_value(repo_root, "branch", "--show-current"),
        "git_worktree_dirty": bool(status),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "package_versions": package_versions,
        "datasets": datasets,
    }
