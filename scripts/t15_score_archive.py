"""동결된 실제 채점 증거를 명시적으로 재사용한다. 새 추론으로 계측하지 않는다."""
from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import subprocess

from scripts import t15_evaluation as evaluation


class ScoreArchive:
    def __init__(self, protocol: dict, run_dir: Path, audit_path: Path):
        audit = json.loads(audit_path.read_bytes())
        manifest_path = run_dir / 'manifest.json'
        if evaluation.sha256_file(manifest_path) != audit['manifest_sha256']:
            raise ValueError('과거 채점 manifest 해시 불일치')
        manifest = json.loads(manifest_path.read_bytes())
        source_path = evaluation.ROOT / audit['protocol_path']
        if evaluation.sha256_file(source_path) != audit['protocol_sha256']:
            raise ValueError('과거 채점 protocol 해시 불일치')
        if manifest['protocol_sha256'] != audit['protocol_sha256']:
            raise ValueError('과거 채점 protocol 연결 불일치')
        source = json.loads(source_path.read_bytes())
        if source['models'] != protocol['models']:
            raise ValueError('재사용 채점의 모델 조건 불일치')
        if source['snapshot_fingerprint'] != protocol['snapshot_fingerprint']:
            raise ValueError('재사용 채점의 스냅샷 불일치')
        if source['code_sha256'] != audit['execution_code_sha256']:
            raise ValueError('과거 실행 코드 지문 불일치')
        for name, expected in audit['execution_code_sha256'].items():
            original = subprocess.check_output(['git', 'show', audit['frozen_execution_code_commit'] + ':' + name], cwd=evaluation.ROOT)
            if evaluation.hashlib.sha256(original).hexdigest() != expected:
                raise ValueError('과거 실행 코드 해시 불일치')
        path = 'src/artagent/retrieval/rerank.py'
        original = subprocess.check_output(['git', 'show', audit['frozen_execution_code_commit'] + ':' + path], cwd=evaluation.ROOT).decode()
        current = (evaluation.ROOT / path).read_text()
        def scorers(text):
            return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(text).body
                    if isinstance(node, ast.ClassDef) and node.name in ('CrossEncoderReranker', 'BM25Reranker')}
        if scorers(original) != scorers(current):
            raise ValueError('재사용 채점의 알고리즘 변경')
        actual = {p.name: evaluation.sha256_file(p) for p in run_dir.iterdir() if p.is_file() and p.name != 'manifest.json'}
        if actual != audit['artifacts'] or manifest['artifacts'] != actual:
            raise ValueError('과거 채점 산출물 해시 불일치')
        self.searches = evaluation.unique_rows(evaluation.read_rows(run_dir / 'search_records.jsonl.gz'),
                                                ('condition', 'query_id', 'candidate_k', 'repeat_index'))
        self.scores = evaluation.unique_rows(evaluation.read_rows(run_dir / 'score_records.jsonl.gz'),
                                             ('model', 'condition', 'query_id', 'candidate_k', 'repeat_index'))
        self.source_sha = actual['score_records.jsonl.gz']

    def score(self, model: str, search: dict) -> dict:
        key = tuple(search[k] for k in ('condition', 'query_id', 'candidate_k', 'repeat_index'))
        archived = self.searches[key]
        binding = ('condition', 'query_id', 'candidate_k', 'repeat_index', 'search_query',
                   'source_type', 'source_group_ids', 'query_vector', 'candidates')
        if any(search[k] != archived[k] for k in binding):
            raise ValueError('과거 채점과 현재 검색 입력·후보 불일치')
        row = copy.deepcopy(self.scores[(model, *key)])
        row.update(measurement='archived_inference', source_score_sha256=self.source_sha,
                   source_elapsed_ms=row['elapsed_ms'], elapsed_ms=None)
        return row
