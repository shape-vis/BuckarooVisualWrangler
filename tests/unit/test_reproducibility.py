"""Provenance capture works independently of Flask and profiling drivers."""

import subprocess

from experiments.reproducibility import capture_reproducibility


def test_dataset_hash_records_exact_input_bytes(tmp_path):
    dataset = tmp_path / "data.csv"
    dataset.write_bytes(b"value\n1\n")

    result = capture_reproducibility(tmp_path, [dataset])

    assert result["python_version"]
    assert result["datasets"][0]["path"] == str(dataset.resolve())
    assert result["datasets"][0]["size_bytes"] == 8
    assert result["datasets"][0]["sha256"] == (
        "1a80986111952a11d02e84dbed98ae00f279469aad0615d17fa81911f8a6b428"
    )


def test_duplicate_inputs_are_deduplicated_and_missing_inputs_are_reported(tmp_path):
    existing = tmp_path / "existing.csv"
    existing.write_bytes(b"value\n1\n")
    missing = tmp_path / "missing.csv"

    result = capture_reproducibility(tmp_path, [missing, existing, existing])

    assert len(result["datasets"]) == 2
    assert result["datasets"][0]["exists"] is True
    assert result["datasets"][1] == {"path": str(missing.resolve()), "exists": False}


def test_git_metadata_records_clean_and_dirty_worktrees(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "--initial-branch=main")
    git("-c", "user.name=Provenance Test", "-c", "user.email=test@example.com",
        "commit", "--allow-empty", "-m", "Initial test commit")
    clean = capture_reproducibility(tmp_path)
    assert clean["git_commit"] == git("rev-parse", "HEAD")
    assert clean["git_branch"] == "main"
    assert clean["git_worktree_dirty"] is False

    (tmp_path / "untracked.csv").write_text("value\n1\n", encoding="utf-8")
    dirty = capture_reproducibility(tmp_path)
    assert dirty["git_commit"] == clean["git_commit"]
    assert dirty["git_worktree_dirty"] is True


def test_non_git_directory_still_returns_environment_metadata(tmp_path):
    result = capture_reproducibility(tmp_path)

    assert result["git_commit"] is None
    assert result["git_branch"] is None
    assert result["python_version"]
    assert result["platform"]
    assert result["generated_at_utc"].endswith("+00:00")
    assert "pandas" in result["package_versions"]
