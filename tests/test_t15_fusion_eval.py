"""결합 정렬의 실행·감사 일치와 과거 채점 증거 연결 검사."""
import copy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from scripts import eval_t15_rerank as runner
from scripts import t15_evaluation as evaluation
from tests.test_rerank import _create_hit

ROOT = Path(__file__).resolve().parents[1]


def test_trial_and_offline_verifier_use_registered_fusion():
    protocol = json.loads((ROOT / 'data/eval/t15-rerank/plan_v3_rebuilt/protocol.json').read_bytes())
    verifier = evaluation.RecordVerifier(protocol)
    search = next(r for r in evaluation.read_rows(ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt/search_records.jsonl.gz')
                  if r['condition'] == 'B' and r['query_id'] == 'Q057' and r['candidate_k'] == 20)
    score = next(r for r in evaluation.read_rows(ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt/score_records.jsonl.gz')
                 if r['condition'] == 'B' and r['query_id'] == 'Q057' and r['candidate_k'] == 20 and r['model'] == 'R1')
    config = {'condition_id': 'fusion-test', 'model': 'R1', 'candidate_k': 20,
              'top_k': 5, 'min_score': None, 'rerank_weight': .1}
    row, bundle = runner.trial(search, score, verifier.search(search), config, protocol, verifier.questions['Q057'])
    chosen, metrics = verifier.selected(search, score, config)
    assert row['metrics']['first_gold_rank'] == 2
    assert metrics == row['metrics']
    assert [h.chunk_id for h in chosen] == row['selected_chunk_ids']
    assert evaluation.digest(asdict(bundle)) == row['bundle_digest']


def test_score_archive_replays_only_identical_search_and_model():
    from scripts.t15_score_archive import ScoreArchive
    protocol = json.loads((ROOT / 'data/eval/t15-rerank/plan_v3_rebuilt/protocol.json').read_bytes())
    archive = ScoreArchive(protocol, ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt',
                           ROOT / 'data/eval/t15-rerank/audit_v4/frozen_v3_integrity.json')
    search = evaluation.read_rows(ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt/search_records.jsonl.gz')[0]
    scored = archive.score('R3', search)
    assert scored['measurement'] == 'archived_inference'
    assert scored['elapsed_ms'] is None
    assert scored['source_score_sha256']
    for field in ('search_query', 'source_type', 'query_vector', 'candidates'):
        altered = copy.deepcopy(search)
        altered[field] = 'changed'
        with pytest.raises(ValueError, match='검색'):
            archive.score('R3', altered)
    altered = copy.deepcopy(protocol)
    altered['models']['R3']['k1'] += .1
    with pytest.raises(ValueError, match='모델'):
        ScoreArchive(altered, ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt',
                     ROOT / 'data/eval/t15-rerank/audit_v4/frozen_v3_integrity.json')


def test_score_archive_rejects_incorrect_frozen_hash(tmp_path):
    from scripts.t15_score_archive import ScoreArchive
    protocol = json.loads((ROOT / 'data/eval/t15-rerank/plan_v3_rebuilt/protocol.json').read_bytes())
    audit = json.loads((ROOT / 'data/eval/t15-rerank/audit_v4/frozen_v3_integrity.json').read_bytes())
    audit['artifacts']['score_records.jsonl.gz'] = '0' * 64
    path = tmp_path / 'audit.json'
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match='해시'):
        ScoreArchive(protocol, ROOT / 'data/eval/t15-rerank/grid_v3_rebuilt', path)
