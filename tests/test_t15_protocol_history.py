"""봉인 기록의 과거 코드 검증과 현재 실행 게이트 분리 회귀."""

import json
from pathlib import Path
import subprocess
from argparse import Namespace
from unittest.mock import MagicMock

import pytest

from scripts.t15_evaluation import verify_protocol
from scripts import t15_evaluation as evaluation
from scripts import eval_t15_rerank as runner

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "data/eval/t15-rerank/plan_v5/protocol.json"


def test_sealed_protocol_verifies_against_its_original_git_tree():
    protocol = verify_protocol(PROTOCOL, historical=True)
    assert protocol["code_commit"] == "7c78e7893199ca5dcd6bbbc898597ed7e618f12a"
    assert "src/artagent/graph/research.py" not in protocol["code_sha256"]


@pytest.mark.parametrize("mutation,expected", [
    ("missing", "지문 목록"), ("extra", "지문 목록"),
    ("hash", "실행 코드 불일치"), ("commit", "커밋"), ("absent_commit", "커밋"),
])
def test_historical_verification_rejects_modified_provenance(tmp_path, mutation, expected):
    data = json.loads(PROTOCOL.read_text())
    if mutation == "missing":
        data["code_sha256"].pop("src/artagent/graph/state.py")
    elif mutation == "extra":
        data["code_sha256"]["src/artagent/graph/research.py"] = "0" * 64
    elif mutation == "hash":
        data["code_sha256"]["src/artagent/graph/state.py"] = "0" * 64
    elif mutation == "commit":
        data["code_commit"] = "--all"
    else:
        data["code_commit"] = "0" * 40
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=expected):
        verify_protocol(path, historical=True)


def test_historical_protocol_cannot_authorize_current_code_execution():
    with pytest.raises(ValueError, match="지문 목록|실행 코드 불일치"):
        verify_protocol(PROTOCOL)


@pytest.fixture
def code_repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    paths = ["runner.py", "src/artagent/graph/node.py", "src/artagent/retrieval/store.py"]
    for name in paths:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True, capture_output=True)
    subprocess.run([
        "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
        "commit", "-qm", "실행 코드 고정",
    ], cwd=root, check=True, capture_output=True)
    monkeypatch.setattr(evaluation, "ROOT", root)
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(evaluation, "FIXED_CODE_PATHS", ["runner.py"])
    monkeypatch.setattr(evaluation, "CODE_PATHS", paths)
    return root, paths


@pytest.mark.parametrize("change", ["modified", "added", "deleted"])
def test_dirty_code_is_rejected_before_preparation_creates_output(code_repo, tmp_path, monkeypatch, change):
    root, paths = code_repo
    if change == "modified":
        (root / "runner.py").write_text("changed = True\n")
    elif change == "added":
        added = "src/artagent/graph/extra.py"
        (root / added).write_text("pass\n")
        paths.append(added)
    else:
        removed = "src/artagent/graph/node.py"
        (root / removed).unlink()
        paths.remove(removed)
    model_identity = MagicMock()
    monkeypatch.setattr(runner, "model_identity", model_identity)
    output = tmp_path / "new-run"
    with pytest.raises(ValueError, match="커밋"):
        runner.cmd_prepare(Namespace(output_dir=str(output)))
    assert not output.exists()
    model_identity.assert_not_called()


def test_prepared_code_identity_has_same_live_and_historical_verification(code_repo, tmp_path):
    root, paths = code_repo
    (root / "notes.md").write_text("실행 코드와 무관한 메모", encoding="utf-8")
    commit, hashes = evaluation.capture_code_identity()
    protocol = json.loads(PROTOCOL.read_text())
    # 고정 평가 입력은 기존 읽기 전용 파일을 가리킨다.
    for entry in protocol["inputs"].values():
        entry["path"] = str(ROOT / entry["path"])
    for name in evaluation.EXPECTED_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    protocol.update(code_commit=commit, code_sha256=hashes)
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol))
    assert set(hashes) == set(paths)
    assert evaluation.verify_protocol(path)["code_sha256"] == hashes
    assert evaluation.verify_protocol(path, historical=True)["code_sha256"] == hashes
    # 작업 파일의 새 지문만 등록해 현재 실행 검사를 우회할 수 없다.
    (root / "runner.py").write_text("changed = True\n")
    protocol["code_sha256"]["runner.py"] = evaluation.sha256_file(root / "runner.py")
    path.write_text(json.dumps(protocol))
    with pytest.raises(ValueError, match="커밋|실행 코드 불일치"):
        evaluation.verify_protocol(path)
