"""봉인 기록의 과거 코드 검증과 현재 실행 게이트 분리 회귀."""

import json
from pathlib import Path

import pytest

from scripts.t15_evaluation import verify_protocol

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
