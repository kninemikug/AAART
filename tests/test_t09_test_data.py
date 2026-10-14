"""Failure contracts for disposable T09 baseline preparation."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

from t09_test_data import verify_reproduction


@pytest.mark.parametrize("mutation", ["missing", "changed"])
@pytest.mark.parametrize("field", [None, "status", "reference_sha256", "protocol_sha256",
                                   "chunks", "vectors", "metrics", "query_log"])
def test_reproduction_evidence_must_match_fixed_inputs(tmp_path, field, mutation):
    reference_path = Path(__file__).resolve().parents[1] / "docs/T08_2_t9_handoff_reference.json"
    reference_bytes = reference_path.read_bytes()
    reference = json.loads(reference_bytes)
    proof = {
        "status": "passed",
        "reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "selected_experiment_id": reference["selected"]["experiment_id"],
        **{key: copy.deepcopy(reference[key]) for key in (
            "protocol_sha256", "chunks", "vectors", "metrics", "query_log",
        )},
    }
    if field is not None:
        if mutation == "missing":
            proof.pop(field)
        else:
            proof[field] = "changed"
    (tmp_path / "reproduction.json").write_text(json.dumps(proof), encoding="utf-8")
    if field is None:
        verify_reproduction(tmp_path, reference_path)
    else:
        with pytest.raises(ValueError, match=field):
            verify_reproduction(tmp_path, reference_path)
