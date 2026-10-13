"""Shared, reproducible test inputs; no dependency on a worktree's live DB."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _run_preparation(arguments: list[str], source_root: Path, log_path: Path) -> None:
    environment = dict(
        os.environ, PYTHONDONTWRITEBYTECODE="1", HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1", PYTHONPATH=str(ROOT / "src"),
    )
    try:
        with log_path.open("wb") as log:
            subprocess.run(arguments, cwd=source_root, env=environment,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
        raise RuntimeError(f"T09 test input preparation failed; log: {log_path}\n{tail}") from error


@pytest.fixture(scope="session")
def t09_reference_path() -> Path:
    return Path(os.getenv("T09_REFERENCE_PATH", str(ROOT / "docs/T08_2_t9_handoff_reference.json"))).resolve()


@pytest.fixture(scope="session")
def t09_source_root() -> Path:
    return Path(os.getenv("T09_SOURCE_ROOT", str(ROOT))).resolve()


@pytest.fixture(scope="session")
def t09_repro_dir(tmp_path_factory, t09_reference_path, t09_source_root) -> Path:
    from t09_test_data import verify_reproduction

    explicit = os.getenv("T09_REPRO_DIR")
    if explicit:
        reproduction_dir = Path(explicit).resolve()
    else:
        work = tmp_path_factory.mktemp("t09-reproduction")
        reproduction_dir = work / "reproduction"
        _run_preparation([
            sys.executable, str(t09_source_root / "scripts/reproduce_t08_2_selected.py"),
            "--reference", str(t09_reference_path), "--work-dir", str(reproduction_dir),
        ], t09_source_root, work / "reproduction.log")
    verify_reproduction(reproduction_dir, t09_reference_path)
    return reproduction_dir


@pytest.fixture(scope="session")
def t09_seed_store(tmp_path_factory, t09_repro_dir, t09_reference_path, t09_source_root) -> Path:
    work = tmp_path_factory.mktemp("t09-baseline")
    store_dir = work / "store"
    arguments = [
        "--reproduction-dir", str(t09_repro_dir), "--reference", str(t09_reference_path),
        "--source-root", str(t09_source_root), "--store-dir", str(store_dir),
    ]
    # Build and reopen in separate processes. No open Chroma handles remain
    # when individual tests copy the verified seed.
    for action in ("build", "verify"):
        _run_preparation([
            sys.executable, str(ROOT / "tests/t09_test_data.py"), action, *arguments,
        ], ROOT, work / f"{action}.log")
    return store_dir
