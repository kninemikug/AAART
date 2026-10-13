"""Task 11 Slice 1 answer.py 단위 및 회귀 테스트."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
from urllib.parse import unquote, urlparse
import pytest

from artagent.answer import (
    DEFAULT_QUERY_SET_PATH,
    DEFAULT_REFERENCE_PATH,
    DEFAULT_SOURCE_ROOT,
    NORMALIZATION_RULE_VERSION,
    SYSTEM_INSTRUCTION,
    GenerationError,
    _validate_llm_json_obj,
    build_codex_execution_policy,
    build_prompt_and_citations,
    check_input_matched,
    generate_llm_response,
    main,
    normalize_query,
    run_pipeline,
    validate_and_format_citations,
    validate_codex_execution,
    validate_record_path,
    validate_saved_trace,
    verify_store_ready,
)
from artagent.retrieval.types import SearchHit


@pytest.fixture(autouse=True)
def isolate_external_dependencies(tmp_path, monkeypatch):
    """단위 테스트가 실제 모델·Chroma·생성 서비스에 접근하면 실패한다."""
    blocked_calls = []

    def forbidden(*args, **kwargs):
        blocked_calls.append("외부 의존성")
        raise AssertionError("단위 테스트에서 실제 외부 의존성을 호출했습니다")

    monkeypatch.setattr("artagent.retrieval.embedding.SentenceTransformer", forbidden)
    monkeypatch.setattr("artagent.retrieval.embedding.AutoTokenizer.from_pretrained", forbidden)
    monkeypatch.setattr("artagent.retrieval.store.chromadb.PersistentClient", forbidden)
    monkeypatch.setattr("urllib.request.urlopen", forbidden)

    connect = sqlite3.connect

    def connect_test_db(database, *args, **kwargs):
        if str(database) != ":memory:":
            value = str(database)
            path = Path(unquote(urlparse(value).path) if value.startswith("file:") else value)
            if not path.resolve().is_relative_to(tmp_path.resolve()):
                blocked_calls.append("실제 DB")
                raise AssertionError("합성 테스트 DB만 열 수 있습니다")
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect_test_db)
    run = subprocess.run

    def run_local_command(command, *args, **kwargs):
        executable = command[0] if isinstance(command, (list, tuple)) else command.split()[0]
        if Path(executable).name == "codex":
            blocked_calls.append("Codex")
            raise AssertionError("Codex 실행은 테스트 내부에서 모의 처리해야 합니다")
        return run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_local_command)
    yield
    assert blocked_calls == [], f"차단 예외가 흡수된 외부 호출 시도: {blocked_calls}"


class MockSpec:
    reference_sha256 = "ref_sha"
    protocol_sha256 = "proto_sha"
    collection_name = "col"
    model_id = "mod"
    dimension = 384
    space = "cosine"
    rawpedia_rule = "rr"
    github_rule = "gr"


class MockHit:
    rank = 1
    chunk_id = "c1"
    source_type = "rawpedia"
    doc_id = "doc1"
    source_group_id = "doc1"
    section_title = "Sec"
    content = "Content"
    content_sha256 = "sha"
    source_segments = [{"doc_id": "doc1", "target_url": "http://doc1"}]
    original_metadata = {}
    distance = 0.1
    distance_text = "0.1"


class MockStore:
    class collection:
        @staticmethod
        def count():
            return 10

    @staticmethod
    def search(q, sess):
        return [MockHit()]


def create_synthetic_store_db(
    db_path: Path,
    collection_name: str = "col",
    store_state: str = "ready",
    rawpedia_active: int = 141,
    rawpedia_excluded: int = 0,
    github_active: int = 13,
    github_excluded: int = 0,
    create_collection: bool = True,
) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    import sqlite3
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("CREATE TABLE collections (id TEXT PRIMARY KEY, name TEXT);")
    cur.execute("CREATE TABLE collection_metadata (collection_id TEXT, key TEXT, str_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER);")
    cur.execute("CREATE TABLE segments (id TEXT PRIMARY KEY, type TEXT, scope TEXT, collection TEXT);")
    cur.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY, segment_id TEXT, embedding_id TEXT, seq_id BLOB);")
    cur.execute("CREATE TABLE embedding_metadata (id INTEGER, key TEXT, string_value TEXT, int_value INTEGER, float_value REAL, bool_value INTEGER);")

    if not create_collection:
        conn.commit()
        conn.close()
        return

    col_id = "col_test_1"
    cur.execute("INSERT INTO collections (id, name) VALUES (?, ?);", (col_id, collection_name))
    if store_state is not None:
        cur.execute("INSERT INTO collection_metadata (collection_id, key, str_value) VALUES (?, 'store_state', ?);", (col_id, store_state))

    seg_id = "seg_test_1"
    cur.execute("INSERT INTO segments (id, type, scope, collection) VALUES (?, 'urn:chroma:segment/metadata/sqlite', 'METADATA', ?);", (seg_id, col_id))

    current_id = 1
    for _ in range(rawpedia_active):
        cur.execute("INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?);", (current_id, seg_id, f"chunk_{current_id}"))
        cur.execute("INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, 'source_type', 'rawpedia');", (current_id,))
        cur.execute("INSERT INTO embedding_metadata (id, key, bool_value) VALUES (?, 'excluded', 0);", (current_id,))
        current_id += 1

    for _ in range(rawpedia_excluded):
        cur.execute("INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?);", (current_id, seg_id, f"chunk_{current_id}"))
        cur.execute("INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, 'source_type', 'rawpedia');", (current_id,))
        cur.execute("INSERT INTO embedding_metadata (id, key, bool_value) VALUES (?, 'excluded', 1);", (current_id,))
        current_id += 1

    for _ in range(github_active):
        cur.execute("INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?);", (current_id, seg_id, f"chunk_{current_id}"))
        cur.execute("INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, 'source_type', 'github');", (current_id,))
        cur.execute("INSERT INTO embedding_metadata (id, key, bool_value) VALUES (?, 'excluded', 0);", (current_id,))
        current_id += 1

    for _ in range(github_excluded):
        cur.execute("INSERT INTO embeddings (id, segment_id, embedding_id) VALUES (?, ?, ?);", (current_id, seg_id, f"chunk_{current_id}"))
        cur.execute("INSERT INTO embedding_metadata (id, key, string_value) VALUES (?, 'source_type', 'github');", (current_id,))
        cur.execute("INSERT INTO embedding_metadata (id, key, bool_value) VALUES (?, 'excluded', 1);", (current_id,))
        current_id += 1

    conn.commit()
    conn.close()


def test_normalize_query_success():
    raw = "  RawPedia\t설명에서   Auto Levels는  무엇을 \n분석하나요?  "
    normalized = normalize_query(raw)
    assert normalized == "RawPedia 설명에서 Auto Levels는 무엇을 분석하나요?"


def test_normalize_query_empty_fails():
    with pytest.raises(ValueError, match="질문이 비어 있습니다"):
        normalize_query("")
    with pytest.raises(ValueError, match="질문이 비어 있습니다"):
        normalize_query("   \t\n  ")


def test_build_prompt_and_citations():
    hit1 = SearchHit(
        rank=1,
        chunk_id="chk1",
        source_type="rawpedia",
        doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure",
        section_title="Exposure",
        content="Auto Levels analyzes the histogram to adjust exposure.",
        content_sha256="abc",
        source_segments=[
            {
                "doc_id": "rawpedia:Exposure",
                "target_url": "https://rawpedia.es/Exposure",
                "content_char_start": 0,
                "content_char_end": 50,
            }
        ],
        original_metadata={"page_title": "Exposure"},
        distance=0.1,
        distance_text="0.100000",
    )
    user_prompt, citations, cids = build_prompt_and_citations("Auto Levels 질문", [hit1])
    assert "C1S1" in citations
    assert cids == ["C1S1"]
    assert citations["C1S1"]["display_name"] == "Exposure"
    assert citations["C1S1"]["target_url"] == "https://rawpedia.es/Exposure"
    assert "Auto Levels 질문" in user_prompt


def test_validate_and_format_citations_success():
    context_citations = {
        "C1S1": {
            "citation_id": "C1S1",
            "display_name": "Exposure",
            "target_url": "https://rawpedia.es/Exposure",
            "chunk_id": "chk1",
            "source_segment": {"doc_id": "rawpedia:Exposure"},
        }
    }
    raw_answer = "히스토그램을 분석합니다 [C1S1]."
    parsed_ids = ["C1S1"]
    final_ans, stdout_text, used = validate_and_format_citations(raw_answer, parsed_ids, context_citations)
    assert "[출처: Exposure·https://rawpedia.es/Exposure]" in final_ans
    assert "[인용 목록]" in stdout_text
    assert "- C1S1: Exposure (https://rawpedia.es/Exposure)" in stdout_text
    assert len(used) == 1


def test_validate_and_format_citations_empty_answer_fails():
    context_citations = {"C1S1": {"display_name": "A", "target_url": "http://a"}}
    with pytest.raises(ValueError, match="답변 문자열이 비어 있습니다"):
        validate_and_format_citations("", ["C1S1"], context_citations)
    with pytest.raises(ValueError, match="답변 문자열이 비어 있습니다"):
        validate_and_format_citations("   ", ["C1S1"], context_citations)


def test_validate_and_format_citations_marker_mismatch_fails():
    context_citations = {
        "C1S1": {"display_name": "A", "target_url": "http://a"},
        "C1S2": {"display_name": "B", "target_url": "http://b"},
    }
    # Marker has C1S1, but parsed_ids has C1S2
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        validate_and_format_citations("답변입니다 [C1S1].", ["C1S2"], context_citations)

    # Marker omitted in text
    with pytest.raises(ValueError, match="일치하지 않습니다"):
        validate_and_format_citations("답변입니다.", ["C1S1"], context_citations)


def test_validate_and_format_citations_unknown_id_fails():
    context_citations = {"C1S1": {"display_name": "A", "target_url": "http://a"}}
    with pytest.raises(ValueError, match="문맥에 없는 인용 ID"):
        validate_and_format_citations("답변입니다 [C2S1].", ["C2S1"], context_citations)


def test_validate_and_format_citations_missing_metadata_fails():
    context_citations = {"C1S1": {"display_name": "", "target_url": ""}}
    with pytest.raises(ValueError, match="필수 정보"):
        validate_and_format_citations("답변입니다 [C1S1].", ["C1S1"], context_citations)


def test_run_pipeline_generation_failure_recording():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store/t09").resolve()

    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value=None), \
         patch("artagent.answer.open_store", return_value=MockStore()), \
         patch("artagent.answer.generate_llm_response", side_effect=RuntimeError("API connection timeout")):
        record = run_pipeline(
            query_original="Auto Levels",
            reference_path=ref_path,
            persist_dir=persist_dir,
            query_id="Q_TEST",
        )
        assert record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "generation"
        assert "API connection timeout" in record["execution"]["error_message"]
        assert record["output"]["exit_code"] == 1
        assert record["verification"]["citations_valid"] is False
        assert record["verification"]["manual_review"] == "pending"


def test_record_isolation():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store/t09").resolve()

    with tempfile.NamedTemporaryFile("w+", suffix=".jsonl") as tmp_file:
        tmp_record_path = Path(tmp_file.name)
        # Mocking generation to return a valid grounded JSON response
        mock_response = json.dumps({"answer": "결과 [C1S1]", "citation_ids": ["C1S1"]})
        with patch("artagent.answer.load_spec", return_value=MockSpec()), \
             patch("artagent.answer.verify_store_ready", return_value=154), \
             patch("artagent.answer.load_encoder", return_value=None), \
             patch("artagent.answer.open_store", return_value=MockStore()), \
             patch("artagent.answer.generate_llm_response", return_value=(mock_response, None, {"llm_provider": "mock"})):
            record = run_pipeline(
                query_original="Exposure compensation",
                reference_path=ref_path,
                persist_dir=persist_dir,
                query_id="Q_ISOLATION",
            )
            assert record["execution"]["status"] == "success"
            # Write to tmp_record_path
            tmp_record_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            assert tmp_record_path.is_file()
            lines = tmp_record_path.read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            loaded = json.loads(lines[0])
            assert loaded["query_id"] == "Q_ISOLATION"


def test_validate_record_path_rejections():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    query_set_path = Path("docs/search_eval_queries.json").resolve()
    persist_dir = Path("data/vector-store").resolve()

    # 1. Reference file rejection
    with pytest.raises(ValueError, match="보호된 파일"):
        validate_record_path(ref_path, ref_path, persist_dir, query_set_path)

    # 2. Query set file rejection
    with pytest.raises(ValueError, match="보호된 파일"):
        validate_record_path(query_set_path, ref_path, persist_dir, query_set_path)

    # 3. Corpus directory & subpath rejection
    rawpedia_file = Path("data/rawpedia/sample.jsonl")
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(rawpedia_file, ref_path, persist_dir, query_set_path)

    issues_file = Path("data/issues/comments.json")
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(issues_file, ref_path, persist_dir, query_set_path)

    # 4. DB directory & subpath rejection
    db_file = persist_dir / "chroma.sqlite3"
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(db_file, ref_path, persist_dir, query_set_path)

    # 5. Allowed record path
    valid_record_path = Path("docs/T11_execution_records.jsonl")
    validate_record_path(valid_record_path, ref_path, persist_dir, query_set_path)


def test_cli_record_path_rejection(capsys):
    test_argv = [
        "answer.py",
        "Test query",
        "--record", "data/rawpedia/forbidden.jsonl",
    ]
    with patch("sys.argv", test_argv):
        ret = main()
        assert ret == 2
        captured = capsys.readouterr()
        assert "[validation]" in captured.err
        assert "보호된 디렉터리" in captured.err


def test_llm_provider_selection_errors():
    # 1. Invalid provider -> ValueError
    with patch.dict("os.environ", {"LLM_PROVIDER": "unsupported_ai"}):
        with pytest.raises(ValueError, match="지원되지 않는 LLM_PROVIDER"):
            generate_llm_response("sys", "user", {}, "q")

    # 2. Codex missing on PATH -> RuntimeError (no fallback to openai)
    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="PATH에서 찾을 수 없습니다"):
                generate_llm_response("sys", "user", {}, "q")

    # 3. OpenAI missing API key & base URL -> RuntimeError (no fallback to codex)
    with patch.dict("os.environ", {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "", "LLM_API_KEY": "", "LLM_BASE_URL": ""}, clear=True):
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY 또는 LLM_BASE_URL이 설정되지 않았습니다"):
            generate_llm_response("sys", "user", {}, "q")


def test_check_input_matched():
    query_set_path = DEFAULT_QUERY_SET_PATH
    assert query_set_path.is_file()

    q_data = json.loads(query_set_path.read_bytes())
    first_q = q_data["queries"][0]
    qid = first_q["query_id"]
    qtext = first_q["query"]

    # Exactly matching
    assert check_input_matched(qid, qtext, query_set_path) is True

    # Modified query text
    assert check_input_matched(qid, qtext + " modified", query_set_path) is False

    # Non-existent query id
    assert check_input_matched("Q_DOES_NOT_EXIST", qtext, query_set_path) is False


def test_codex_runner_metadata_null():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store/t09").resolve()

    mock_resp = json.dumps({"answer": "Auto Levels 설명 [C1S1]", "citation_ids": ["C1S1"]})
    mock_meta = {
        "llm_provider": "codex-cli",
        "model_id": "gpt-5.6-sol",
        "endpoint": "codex exec",
        "generation_config": {"temperature": None, "prompt_version": 1},
        "_finish_reason": None,
    }

    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value=None), \
         patch("artagent.answer.open_store", return_value=MockStore()), \
         patch("artagent.answer.generate_llm_response", return_value=(mock_resp, {"total_tokens": 120}, mock_meta)):
        record = run_pipeline(
            query_original="Auto Levels",
            reference_path=ref_path,
            persist_dir=persist_dir,
            query_id="Q001",
        )
        assert record["execution"]["status"] == "success"
        # Confirm temperature and finish_reason are null / None
        assert record["runtime"]["generation_config"]["temperature"] is None
        assert record["generation"]["finish_reason"] is None
        assert record["generation"]["usage"] == {"total_tokens": 120}


def test_record_path_external_source_root_without_env_var_rejected():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    with patch.dict("os.environ", {}, clear=True):
        # 1. External rawpedia file without T09_SOURCE_ROOT env var
        ext_rawpedia = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_rawpedia, ref_path, persist_dir, query_set_path)

        # 2. External issues existing or non-existing file
        ext_issues_nonexist = DEFAULT_SOURCE_ROOT / "data/issues/comments_99999.jsonl"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_issues_nonexist, ref_path, persist_dir, query_set_path)


def test_record_path_custom_t09_source_root_both_protected(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    custom_root = tmp_path / "custom_root"
    custom_root.mkdir()
    (custom_root / "data" / "rawpedia").mkdir(parents=True)

    with patch.dict("os.environ", {"T09_SOURCE_ROOT": str(custom_root)}):
        # Default external root still protected
        ext_rawpedia = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(ext_rawpedia, ref_path, persist_dir, query_set_path)

        # Custom root also protected
        custom_rawpedia = custom_root / "data/rawpedia/NewDoc.md"
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            validate_record_path(custom_rawpedia, ref_path, persist_dir, query_set_path)


def test_record_path_inputs_and_custom_persist_rejected(tmp_path):
    custom_ref = tmp_path / "my_ref.json"
    custom_ref.write_text("{}", encoding="utf-8")
    custom_persist = tmp_path / "my_persist_db"
    custom_persist.mkdir()
    custom_qset = tmp_path / "my_qset.json"
    custom_qset.write_text("{}", encoding="utf-8")

    # Default external reference & query set rejected
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(DEFAULT_REFERENCE_PATH, custom_ref, custom_persist, custom_qset)
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(DEFAULT_QUERY_SET_PATH, custom_ref, custom_persist, custom_qset)

    # Custom inputs rejected
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(custom_ref, custom_ref, custom_persist, custom_qset)
    with pytest.raises(ValueError, match="보호된"):
        validate_record_path(custom_qset, custom_ref, custom_persist, custom_qset)

    # File inside custom persist dir rejected
    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(custom_persist / "sqlite3.db", custom_ref, custom_persist, custom_qset)


def test_record_path_symlink_to_protected_rejected(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    symlink_file = tmp_path / "sneaky_symlink.jsonl"
    target_prohibited = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"
    symlink_file.symlink_to(target_prohibited)

    with pytest.raises(ValueError, match="보호된 디렉터리"):
        validate_record_path(symlink_file, ref_path, persist_dir, query_set_path)


def test_safe_temporary_record_path_allowed(tmp_path):
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    query_set_path = DEFAULT_QUERY_SET_PATH

    safe_path = tmp_path / "safe_record.jsonl"
    validate_record_path(safe_path, ref_path, persist_dir, query_set_path)


def test_prohibited_record_path_stops_before_calls_in_run_pipeline_and_cli():
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("data/vector-store").resolve()
    prohibited = DEFAULT_SOURCE_ROOT / "data/rawpedia/Exposure.md"

    with patch("artagent.answer.load_spec") as mock_load_spec, \
         patch("artagent.answer.open_store") as mock_open_store, \
         patch("artagent.answer.generate_llm_response") as mock_gen:

        # 1. run_pipeline direct call
        with pytest.raises(ValueError, match="보호된 디렉터리"):
            run_pipeline("test query", ref_path, persist_dir, record_path=prohibited)
        assert mock_load_spec.call_count == 0
        assert mock_open_store.call_count == 0
        assert mock_gen.call_count == 0

        # 2. main() CLI call
        with patch("sys.argv", ["artagent-answer", "test query", "--record", str(prohibited)]):
            ret = main()
            assert ret == 2
        assert mock_load_spec.call_count == 0
        assert mock_open_store.call_count == 0
        assert mock_gen.call_count == 0


def _make_mock_completed_proc(stdout: str, stderr: str = "", returncode: int = 0):
    class MockProc:
        pass
    p = MockProc()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


def test_codex_empty_stdout_rejected(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout="", returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "이벤트 로그가 비어 있습니다" in str(err)
                assert err.trace is not None
                assert err.trace["trace_schema"] in ("t11-codex-trace-v1", "t11-codex-trace-v2")
                assert err.trace["validation"]["status"] == "rejected"


def test_codex_broken_json_and_non_json_lines_rejected(tmp_path):
    events = [
        json.dumps({"type": "thread.started"}),
        "THIS IS NOT JSON",
        json.dumps({"type": "turn.completed"}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "JSON 파싱 실패" in str(err)
                assert err.trace["validation"]["status"] == "rejected"
                assert "THIS IS NOT JSON" in err.trace["stdout_jsonl"]


def test_codex_lifecycle_incomplete_or_failed_rejected(tmp_path):
    # Missing turn.completed
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ans", "citation_ids": []})}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "이벤트 생명주기 불일치" in str(exc_info.value)


def test_codex_tool_item_in_item_updated_rejected(tmp_path):
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "ans", "citation_ids": []})}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "web_search" in str(exc_info.value)
                assert exc_info.value.trace["validation"]["additional_tool_count"] == 1


def test_codex_content_mismatch_with_output_file_rejected(tmp_path):
    event_payload = {"answer": "Event Answer [C1S1]", "citation_ids": ["C1S1"]}
    file_payload = {"answer": "Different File Answer [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(event_payload)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(file_payload), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                assert "일치하지 않습니다" in str(exc_info.value)


def test_codex_process_failure_and_partial_trace_preserved(tmp_path):
    partial_stdout = json.dumps({"type": "thread.started"}) + "\n"
    partial_stderr = "Fatal error in codex exec"

    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(stdout=partial_stdout, stderr=partial_stderr, returncode=1)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "비정상 종료" in str(err)
                assert err.trace["process_returncode"] == 1
                assert err.trace["stderr"] == partial_stderr
                assert err.trace["validation"]["status"] == "rejected"


def test_codex_success_trace_verified(tmp_path):
    ans_obj = {"answer": "정상 답변 [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-123"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(ans_obj)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(ans_obj), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                raw_resp, usage, meta = generate_llm_response(
                    "sys", "user", {"C1S1": {"display_name": "Doc", "target_url": "http://doc"}}, "q"
                )
                trace = meta["_trace"]
                assert trace is not None
                assert trace["trace_schema"] in ("t11-codex-trace-v1", "t11-codex-trace-v2")
                assert trace["validation"]["status"] == "verified"
                assert trace["validation"]["summary_status"] == "complete"
                assert trace["validation"]["summary_error"] is None
                assert trace["validation"]["thread_id"] == "th-123"
                assert trace["validation"]["additional_tool_count"] == 0
                assert trace["validation"]["turn_started_count"] == 1
                assert trace["validation"]["turn_completed_count"] == 1
                assert trace["execution_policy"]["application_status"] == "confirmed"
                assert trace["execution_policy"]["tools_enabled"] is False


def test_cli_failure_event_recorded_in_safe_jsonl_with_trace(tmp_path):
    record_file = tmp_path / "cli_fail_run.jsonl"
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "whoami"}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps({"answer": "ans", "citation_ids": []}), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    class MockSpec:
        reference_sha256 = "ref_sha"
        protocol_sha256 = "proto_sha"
        collection_name = "col"
        model_id = "mod"
        dimension = 384
        space = "cosine"
        rawpedia_rule = "rr"
        github_rule = "gr"

    class MockHit:
        rank = 1
        chunk_id = "c1"
        source_type = "rawpedia"
        doc_id = "doc1"
        source_group_id = "doc1"
        section_title = "Sec"
        content = "Content"
        content_sha256 = "sha"
        source_segments = [{"doc_id": "doc1", "target_url": "http://doc1"}]
        original_metadata = {}
        distance = 0.1
        distance_text = "0.1"

    class MockStore:
        class collection:
            @staticmethod
            def count():
                return 10
        @staticmethod
        def search(q, sess):
            return [MockHit()]

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(record_file)]):
                        ret = main()
                        assert ret == 1

    assert record_file.is_file()
    rec = json.loads(record_file.read_text(encoding="utf-8").strip())
    assert rec["execution"]["status"] == "error"
    assert rec["execution"]["failed_step"] == "generation"
    assert rec["output"]["stdout"] == ""
    assert rec["generation"]["trace"]["validation"]["status"] == "rejected"
    assert rec["generation"]["trace"]["validation"]["additional_tool_count"] == 1


def test_codex_command_args_and_policy_match(tmp_path):
    captured_cmd = []
    ans_obj = {"answer": "정상 답변 [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-args"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(ans_obj)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_content = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        captured_cmd.extend(cmd)
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(ans_obj), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_content, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                raw_resp, usage, meta = generate_llm_response(
                    "sys", "user", {"C1S1": {"display_name": "Doc", "target_url": "http://doc"}}, "q"
                )
                trace = meta["_trace"]
                # 1. Verify actual command arguments
                assert "-c" in captured_cmd
                assert "features.shell_tool=false" in captured_cmd
                assert "features.unified_exec=false" in captured_cmd
                assert 'web_search="disabled"' in captured_cmd

                # 2. Verify policy matches command
                assert trace["trace_schema"] == "t11-codex-trace-v2"
                policy = trace["execution_policy"]
                assert policy["application_status"] == "confirmed"
                assert policy["tools_enabled"] is False
                assert policy["config_source"] == "cli_args"
                assert policy["config_overrides"]["features.shell_tool"] == "false"
                assert policy["config_overrides"]["features.unified_exec"] == "false"
                assert policy["config_overrides"]["web_search"] == '"disabled"'
                assert trace["validation"]["status"] == "verified"
                assert trace["validation"]["summary_status"] == "complete"
                assert trace["validation"]["summary_error"] is None


def test_codex_unsupported_option_failure_preserved(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(
            stdout="",
            stderr="error: unsupported configuration option 'features.shell_tool'",
            returncode=2,
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "비정상 종료" in str(err)
                assert err.trace["process_returncode"] == 2
                assert "unsupported configuration option" in err.trace["stderr"]
                assert err.trace["validation"]["status"] == "rejected"
                assert err.trace["validation"]["summary_status"] == "unavailable"
                assert err.trace["validation"]["additional_tool_count"] is None
                assert err.trace["execution_policy"]["tools_enabled"] is None
                assert err.trace["execution_policy"]["application_status"] == "unconfirmed"


def test_codex_timeout_with_bytes_output_preserved(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output=b'{"type": "thread.started", "thread_id": "th-to"}\n',
            stderr=b"process timed out after 120 seconds\n",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert err.trace["process_returncode"] is None
                assert err.trace["process_error"] == {"kind": "timeout", "timeout_seconds": 120}
                assert err.trace["stdout_jsonl"] == '{"type": "thread.started", "thread_id": "th-to"}\n'
                assert err.trace["stderr"] == "process timed out after 120 seconds\n"
                assert err.trace["validation"]["status"] == "rejected"
                assert "시간 초과" in err.trace["validation"]["error_reason"]


def test_codex_timeout_with_none_output(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120, output=None, stderr=None)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert err.trace["process_returncode"] is None
                assert err.trace["process_error"] == {"kind": "timeout", "timeout_seconds": 120}
                assert err.trace["stdout_jsonl"] == ""
                assert err.trace["stderr"] == ""
                assert err.trace["validation"]["status"] == "unavailable"
                assert "시간 초과" in err.trace["validation"]["error_reason"]


def test_codex_timeout_with_truncated_utf8_bytes(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        # Truncated UTF-8 in stdout and invalid byte in stderr
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output=b'{"type": "turn.started", "text": "\xed\x95\x9c\xea',
            stderr=b"bad byte: \xff",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert "\ufffd" in err.trace["stdout_jsonl"]
                assert "\ufffd" in err.trace["stderr"]
                assert err.trace["validation"]["status"] == "rejected"


def test_codex_timeout_with_str_and_empty_bytes_output(tmp_path):
    """B17 / R17: TimeoutExpired의 str 그대로 유지 및 빈 bytes('') 미수신 처리(unavailable) 확인."""
    # 1. str 출력 시간초과
    def mock_subprocess_str(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output='{"type": "thread.started", "thread_id": "th-str"}\n',
            stderr="process timed out\n",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_str):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert err.trace["process_returncode"] is None
                assert err.trace["stdout_jsonl"] == '{"type": "thread.started", "thread_id": "th-str"}\n'
                assert err.trace["stderr"] == "process timed out\n"
                assert err.trace["validation"]["status"] == "rejected"

    # 2. 빈 bytes (b'') 시간초과 -> 미수신 처리 (unavailable)
    def mock_subprocess_empty_bytes(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120, output=b"", stderr=b"")

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_empty_bytes):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert err.trace["stdout_jsonl"] == ""
                assert err.trace["stderr"] == ""
                assert err.trace["validation"]["status"] == "unavailable"


def test_codex_timeout_with_completed_events_and_file_still_fails(tmp_path):
    ans_obj = {"answer": "정상 답변 [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(ans_obj)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_bytes = "\n".join(events).encode("utf-8")

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(ans_obj), encoding="utf-8")
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=120, output=stdout_bytes, stderr=b"")

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                assert err.trace["process_returncode"] is None
                assert err.trace["process_error"]["kind"] == "timeout"
                assert err.trace["validation"]["status"] == "rejected"
                assert "시간 초과" in err.trace["validation"]["error_reason"]


def test_cli_timeout_bytes_recorded_in_safe_jsonl_with_trace(tmp_path):
    record_file = tmp_path / "cli_timeout_run.jsonl"

    def mock_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output=b'{"type": "thread.started"}\n{"type": "turn.started"}\n',
            stderr=b"timeout after 120s\n",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(record_file)]):
                        ret = main()
                        assert ret == 1

    assert record_file.is_file()
    rec = json.loads(record_file.read_text(encoding="utf-8").strip())
    assert rec["execution"]["status"] == "error"
    assert rec["execution"]["failed_step"] == "generation"
    assert rec["generation"]["call_count"] == 1
    assert rec["output"]["stdout"] == ""
    trace = rec["generation"]["trace"]
    assert trace["process_returncode"] is None
    assert trace["process_error"] == {"kind": "timeout", "timeout_seconds": 120}
    assert trace["stdout_jsonl"] == '{"type": "thread.started"}\n{"type": "turn.started"}\n'
    assert trace["stderr"] == "timeout after 120s\n"
    assert trace["validation"]["status"] == "rejected"
    assert "시간 초과" in trace["validation"]["error_reason"]


@pytest.mark.parametrize("case", ["str", "bytes", "none", "empty-bytes", "truncated-utf8"])
def test_c04_cli_timeout_stream_types(tmp_path, capsys, case):
    """B17·B20: 스트림 타입별 시간 초과를 실제 생성 함수부터 CLI JSONL까지 보존한다."""
    event = '{"type":"thread.started","thread_id":"timeout-thread"}\n'
    diagnostic = "시간 초과 진단\n"
    if case == "str":
        stdout, stderr = event, diagnostic
        expected_stdout, expected_stderr = event, diagnostic
    elif case == "bytes":
        stdout, stderr = event.encode(), diagnostic.encode()
        expected_stdout, expected_stderr = event, diagnostic
    elif case == "truncated-utf8":
        stdout, stderr = event.encode() + b"\xeb\x9c", b"diagnostic \xeb\x9c"
        expected_stdout, expected_stderr = event + "\ufffd", "diagnostic \ufffd"
    else:
        stdout = stderr = None if case == "none" else b""
        expected_stdout = expected_stderr = ""
    response = json.dumps({"answer": "이미 완료된 답변 [C1S1]", "citation_ids": ["C1S1"]})
    attempts = []
    def mock_run(command, **kwargs):
        if "-o" not in command:
            return _make_mock_completed_proc("test-version")
        attempts.append(command)
        assert kwargs["timeout"] == 120
        Path(command[command.index("-o") + 1]).write_text(response, encoding="utf-8")
        raise subprocess.TimeoutExpired(command, 120, output=stdout, stderr=stderr)

    record_path = tmp_path / "timeout.jsonl"
    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value="session"), \
         patch("artagent.answer.open_store", return_value=MockStore()), \
         patch.dict("os.environ", {"LLM_PROVIDER": "codex"}), \
         patch("shutil.which", return_value="/usr/bin/codex"), \
         patch("subprocess.run", side_effect=mock_run), \
         patch("sys.argv", ["answer", "질문", "--record", str(record_path)]):
        assert main() == 1
    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and len(attempts) == 1
    saved = json.loads(lines[0])
    assert saved["execution"]["failed_step"] == "generation"
    assert saved["generation"]["call_count"] == 1
    assert saved["generation"]["raw_response"] == response
    assert saved["output"]["stdout"] == capsys.readouterr().out == ""
    trace = saved["generation"]["trace"]
    assert trace["stdout_jsonl"] == expected_stdout and trace["stderr"] == expected_stderr
    assert trace["process_returncode"] is None
    assert trace["process_error"] == {"kind": "timeout", "timeout_seconds": 120}
    assert "시간 초과" in saved["execution"]["error_message"]
    assert trace["execution_policy"]["application_status"] == "unconfirmed"
    assert trace["execution_policy"]["tools_enabled"] is None
    assert trace["validation"]["status"] == ("rejected" if expected_stdout else "unavailable")
    expected_summary = "partial" if case == "truncated-utf8" else "complete" if expected_stdout else "unavailable"
    assert trace["validation"]["summary_status"] == expected_summary


def test_codex_failure_aggregation_with_timeout(tmp_path):
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-to-3"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
    ]
    stdout_bytes = "\n".join(events).encode("utf-8")

    def mock_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output=stdout_bytes,
            stderr=b"timeout 120s\n",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "시간 초과" in str(err)
                val = err.trace["validation"]
                assert val["status"] == "rejected"
                assert val["summary_status"] == "complete"
                assert val["summary_error"] is None
                assert val["event_count"] == 3
                assert val["thread_id"] == "th-to-3"
                assert val["turn_started_count"] == 1
                assert val["turn_completed_count"] == 0
                assert val["additional_tool_count"] == 1
                assert val["observed_item_types"] == ["web_search"]
                assert err.trace["process_returncode"] is None
                assert err.trace["process_error"] == {"kind": "timeout", "timeout_seconds": 120}
                assert err.trace["execution_policy"]["application_status"] == "unconfirmed"
                assert err.trace["execution_policy"]["tools_enabled"] is None


def test_codex_failure_aggregation_with_exit_code_2(tmp_path):
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-exit-3"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
    ]
    stdout_str = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(stdout=stdout_str, stderr="fatal error", returncode=2)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "비정상 종료" in str(err)
                val = err.trace["validation"]
                assert val["status"] == "rejected"
                assert val["summary_status"] == "complete"
                assert val["summary_error"] is None
                assert val["event_count"] == 3
                assert val["thread_id"] == "th-exit-3"
                assert val["turn_started_count"] == 1
                assert val["turn_completed_count"] == 0
                assert val["additional_tool_count"] == 1
                assert val["observed_item_types"] == ["web_search"]
                assert err.trace["process_returncode"] == 2
                assert err.trace["execution_policy"]["application_status"] == "unconfirmed"
                assert err.trace["execution_policy"]["tools_enabled"] is None


def test_codex_partial_summary_with_corrupted_line_and_timeout(tmp_path):
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-corrupt"}),
        "MALFORMED_JSON_LINE_HERE",
    ]
    stdout_bytes = "\n".join(events).encode("utf-8")

    def mock_subprocess_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=cmd,
            timeout=120,
            output=stdout_bytes,
            stderr=b"timeout\n",
        )

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                val = err.trace["validation"]
                assert val["status"] == "rejected"
                assert val["summary_status"] == "partial"
                assert val["summary_error"] is not None
                assert "JSON 파싱 실패" in val["summary_error"]
                assert val["event_count"] is None
                assert val["additional_tool_count"] is None
                assert val["turn_started_count"] is None
                assert err.trace["process_error"]["kind"] == "timeout"
                assert err.trace["execution_policy"]["application_status"] == "unconfirmed"
                assert err.trace["execution_policy"]["tools_enabled"] is None


def test_codex_stderr_only_unavailable_summary(tmp_path):
    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(stdout="", stderr="some warning on stderr", returncode=2)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                val = err.trace["validation"]
                assert val["status"] == "rejected"
                assert val["summary_status"] == "unavailable"
                assert val["summary_error"] is None
                assert val["event_count"] is None
                assert val["additional_tool_count"] is None
                assert err.trace["stderr"] == "some warning on stderr"


def test_codex_completed_events_with_exit_code_2_fails(tmp_path):
    ans_obj = {"answer": "답변 [C1S1]", "citation_ids": ["C1S1"]}
    events = [
        json.dumps({"type": "thread.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(ans_obj)}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
    ]
    stdout_str = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(json.dumps(ans_obj), encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_str, stderr="segfault after finish", returncode=2)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with pytest.raises(GenerationError) as exc_info:
                    generate_llm_response("sys", "user", {}, "q")
                err = exc_info.value
                assert "비정상 종료" in str(err)
                val = err.trace["validation"]
                assert val["summary_status"] == "complete"
                assert err.trace["process_returncode"] == 2
                assert err.trace["execution_policy"]["application_status"] == "unconfirmed"
                assert err.trace["execution_policy"]["tools_enabled"] is None


def test_cli_unsupported_option_and_tool_event_saved_in_record(tmp_path):
    # 1. Unsupported option CLI record
    rec_file1 = tmp_path / "cli_unsupported.jsonl"
    def mock_subprocess_run1(cmd, **kwargs):
        return _make_mock_completed_proc(stdout="", stderr="unknown option", returncode=2)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run1):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(rec_file1)]):
                        ret = main()
                        assert ret == 1

    rec1 = json.loads(rec_file1.read_text(encoding="utf-8").strip())
    assert rec1["execution"]["status"] == "error"
    trace1 = rec1["generation"]["trace"]
    assert trace1["execution_policy"]["application_status"] == "unconfirmed"
    assert trace1["execution_policy"]["tools_enabled"] is None
    assert trace1["validation"]["summary_status"] == "unavailable"
    assert trace1["validation"]["additional_tool_count"] is None

    # 2. Tool event CLI record
    rec_file2 = tmp_path / "cli_tool_event.jsonl"
    events2 = [
        json.dumps({"type": "thread.started", "thread_id": "th-cli"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
    ]
    def mock_subprocess_run2(cmd, **kwargs):
        return _make_mock_completed_proc(stdout="\n".join(events2), stderr="", returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run2):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(rec_file2)]):
                        ret = main()
                        assert ret == 1

    rec2 = json.loads(rec_file2.read_text(encoding="utf-8").strip())
    assert rec2["execution"]["status"] == "error"
    trace2 = rec2["generation"]["trace"]
    assert trace2["execution_policy"]["application_status"] == "unconfirmed"
    assert trace2["execution_policy"]["tools_enabled"] is None
    assert trace2["validation"]["summary_status"] == "complete"
    assert trace2["validation"]["additional_tool_count"] == 1
    assert trace2["validation"]["observed_item_types"] == ["web_search"]


def test_validate_saved_trace_v1_and_v2_compatibility():
    records_path = Path("docs/T11_execution_records.jsonl")
    assert records_path.is_file()
    lines = records_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 15

    for line in lines:
        r = json.loads(line)
        trace = r["generation"]["trace"]
        summary = validate_saved_trace(trace)
        assert summary["trace_schema"] == "t11-codex-trace-v1"
        assert summary["status"] == "verified"
        assert summary["additional_tool_count"] == 0
        assert summary["application_status"] == "unconfirmed"
        assert summary["tools_enabled"] is False

    synth_v2 = {
        "trace_schema": "t11-codex-trace-v2",
        "cli_version": "1.0",
        "process_returncode": 0,
        "execution_policy": {
            "application_status": "confirmed",
            "tools_enabled": False,
        },
        "validation": {
            "status": "verified",
            "summary_status": "complete",
            "summary_error": None,
            "event_count": 4,
            "additional_tool_count": 0,
        },
    }
    summary_v2 = validate_saved_trace(synth_v2)
    assert summary_v2["trace_schema"] == "t11-codex-trace-v2"
    assert summary_v2["application_status"] == "confirmed"
    assert summary_v2["tools_enabled"] is False
    assert summary_v2["summary_status"] == "complete"


# ==============================================================================
# §8.2 검증 묶음 (C01 ~ C09) 및 고정 요구사항 (R01 ~ R29) 회귀 테스트
# ==============================================================================


def test_c01_policy_application_status_and_offline_immutability():
    """C01 / R10, R11, R24: 초기 unconfirmed 정책, 오프라인 검증 시 정책 보존(subprocess 0), 실제 생성 성공 시에만 confirmed."""
    # 1. 초기 정책 검증
    init_policy = build_codex_execution_policy("gpt-5.6-sol")
    assert init_policy["application_status"] == "unconfirmed"
    assert init_policy["tools_enabled"] is None
    assert init_policy["config_source"] == "cli_args"
    assert init_policy["config_overrides"]["features.shell_tool"] == "false"
    assert init_policy["config_overrides"]["features.unified_exec"] == "false"
    assert init_policy["config_overrides"]["web_search"] == '"disabled"'

    # 2. 오프라인 검증 - unconfirmed 정책 전달
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-off"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps({"answer": "정상답변 [C1S1]", "citation_ids": ["C1S1"]})}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}}),
    ]
    stdout_raw = "\n".join(events)
    file_content = json.dumps({"answer": "정상답변 [C1S1]", "citation_ids": ["C1S1"]})

    with patch("subprocess.run") as mock_subproc:
        parsed, usage, trace_unconfirmed = validate_codex_execution(
            stdout_raw=stdout_raw,
            stderr_raw="",
            process_returncode=0,
            out_file_content=file_content,
            execution_policy=init_policy,
            cli_version="1.0.0",
        )
        assert mock_subproc.call_count == 0  # subprocess 호출 0
        assert trace_unconfirmed["execution_policy"]["application_status"] == "unconfirmed"
        assert trace_unconfirmed["execution_policy"]["tools_enabled"] is None
        assert init_policy["application_status"] == "unconfirmed"  # 원본 불변

    # 3. 오프라인 검증 - confirmed 정책 전달
    confirmed_policy = dict(init_policy)
    confirmed_policy["application_status"] = "confirmed"
    confirmed_policy["tools_enabled"] = False
    with patch("subprocess.run") as mock_subproc:
        _, _, trace_confirmed = validate_codex_execution(
            stdout_raw=stdout_raw,
            stderr_raw="",
            process_returncode=0,
            out_file_content=file_content,
            execution_policy=confirmed_policy,
            cli_version="1.0.0",
        )
        assert mock_subproc.call_count == 0
        assert trace_confirmed["execution_policy"]["application_status"] == "confirmed"
        assert trace_confirmed["execution_policy"]["tools_enabled"] is False

    # 4. 실제 생성 함수(generate_llm_response)에서 정상 실행 성공 시 confirmed / False 확정
    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(file_content, encoding="utf-8")
        return _make_mock_completed_proc(stdout=stdout_raw, returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                resp_str, usage, meta = generate_llm_response("sys", "user", {}, "q")
                trace = meta["_trace"]
                assert trace["execution_policy"]["application_status"] == "confirmed"
                assert trace["execution_policy"]["tools_enabled"] is False


@pytest.mark.parametrize(
    "malformed_event_line",
    [
        json.dumps({"type": []}),
        json.dumps({"type": {}}),
        json.dumps({"type": None}),
        json.dumps({"type": 123}),
        "not_a_json_object",
        "12345",
        json.dumps({"type": "unknown_event_type"}),
        json.dumps({"type": "item.started", "item": {"type": []}}),
        json.dumps({"type": "item.started", "item": {"type": {}}}),
        json.dumps({"type": "item.started", "item": {"type": None}}),
        json.dumps({"type": "item.started", "item": {"type": 123}}),
        json.dumps({"type": "item.started", "item": "not_a_dict"}),
        '{"type": "thread.started"',
        "[ERROR] failed to connect",
    ],
)
@pytest.mark.parametrize(
    "proc_condition",
    [
        ("normal", 0, None),
        ("timeout", None, {"kind": "timeout", "timeout_seconds": 120}),
        ("exit_code_2", 2, None),
    ],
)
def test_c02_structural_event_and_item_errors_safe_trace_parameterized(malformed_event_line, proc_condition):
    """C02 / R14, R19, R20: 이벤트/아이템 구조 오류 시 TypeError 없이 안전하게 partial 및 줄 번호/원인 보존."""
    cond_name, returncode, process_error = proc_condition
    stdout_raw = f'{json.dumps({"type": "thread.started", "thread_id": "th-c02"})}\n{malformed_event_line}\n'
    policy = build_codex_execution_policy("gpt-5.6-sol")

    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw=stdout_raw,
            stderr_raw="diagnostic message\n",
            process_returncode=returncode,
            out_file_content=None,
            execution_policy=policy,
            cli_version="1.0.0",
            process_error=process_error,
        )

    err = exc_info.value
    trace = err.trace
    assert trace is not None
    val = trace["validation"]
    assert val["status"] == "rejected"
    assert val["summary_status"] == "partial"
    assert val["summary_error"] is not None
    # 2번째 줄에서 오류가 발생했으므로 줄 번호가 반드시 포함되어야 함
    assert "2번째 줄" in val["summary_error"]
    # 집계 확정 불가 필드는 모두 None
    assert val["event_count"] is None
    assert val["turn_started_count"] is None
    assert val["turn_completed_count"] is None
    assert val["additional_tool_count"] is None

    # 주된 원인 보존 확인
    if cond_name == "timeout":
        assert "시간 초과" in val["error_reason"]
    elif cond_name == "exit_code_2":
        assert "비정상 종료 (종료 코드 2)" in val["error_reason"]
    else:
        assert val["error_reason"] == val["summary_error"]


def test_c02_array_type_event_and_item_preserved_through_cli_record(tmp_path):
    """C02 / R14, R20: 배열형 event.type 및 item.type이 CLI --record에서도 TypeError 없이 JSONL에 온전히 보존."""
    rec_file = tmp_path / "c02_array_type.jsonl"
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-arr"}),
        json.dumps({"type": []}),  # 배열형 type
    ]
    stdout_raw = "\n".join(events)

    def mock_subprocess_run(cmd, **kwargs):
        return _make_mock_completed_proc(stdout=stdout_raw, stderr="err diagnostics", returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(rec_file)]):
                        ret = main()
                        assert ret == 1

    assert rec_file.is_file()
    rec = json.loads(rec_file.read_text(encoding="utf-8").strip())
    assert rec["execution"]["status"] == "error"
    trace = rec["generation"]["trace"]
    assert trace["validation"]["summary_status"] == "partial"
    assert "2번째 줄" in trace["validation"]["summary_error"]
    assert "문자열이 아님" in trace["validation"]["summary_error"]
    assert trace["stdout_jsonl"] == stdout_raw


def test_c03_turn_lifecycle_and_forbidden_tool_detection():
    """C03 / R13~R16: 생명주기 검증 및 금지된 도구 항목 위치별 검출."""
    policy = build_codex_execution_policy("gpt-5.6-sol")
    valid_file = json.dumps({"answer": "답변 [C1S1]", "citation_ids": ["C1S1"]})

    # 1. 정상 생명주기 (1 turn + reasoning)
    valid_events = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.started", "item": {"type": "reasoning"}}),
        json.dumps({"type": "item.completed", "item": {"type": "reasoning"}}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
        json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}}),
    ]
    parsed, _, trace = validate_codex_execution(
        stdout_raw="\n".join(valid_events),
        stderr_raw="",
        process_returncode=0,
        out_file_content=valid_file,
        execution_policy=policy,
        cli_version="1.0.0",
    )
    assert trace["validation"]["status"] == "verified"

    # 2. turn 순서 변경 (turn.completed 가 turn.started 보다 먼저 옴)
    swapped_events = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.completed"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(swapped_events),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert "이벤트 생명주기 불일치" in str(exc_info.value)

    # 3. 금지된 도구 이벤트 항목 검출 (command_execution, file_change, mcp_tool_call, web_search)
    forbidden_types = ["command_execution", "file_change", "mcp_tool_call", "web_search", "custom_mcp_tool"]
    for ftype in forbidden_types:
        for phase in ("item.started", "item.updated", "item.completed"):
            test_evs = [
                json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
                json.dumps({"type": "turn.started"}),
                json.dumps({"type": phase, "item": {"type": ftype}}),
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
                json.dumps({"type": "turn.completed"}),
            ]
            with pytest.raises(GenerationError) as exc_info:
                validate_codex_execution(
                    stdout_raw="\n".join(test_evs),
                    stderr_raw="",
                    process_returncode=0,
                    out_file_content=valid_file,
                    execution_policy=policy,
                    cli_version="1.0.0",
                )
            assert exc_info.value.trace["validation"]["additional_tool_count"] == 1
            assert ftype in exc_info.value.trace["validation"]["observed_item_types"]

    # 4. 완료 turn 누락 (missing turn.completed)
    missing_completed_evs = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(missing_completed_evs),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert "이벤트 생명주기 불일치" in str(exc_info.value)

    # 5. 시작 turn 중복 (duplicate turn.started)
    dup_started_evs = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
        json.dumps({"type": "turn.completed"}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(dup_started_evs),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert "이벤트 생명주기 불일치" in str(exc_info.value)

    # 6. 완료 turn 중복 (duplicate turn.completed)
    dup_completed_evs = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": valid_file}}),
        json.dumps({"type": "turn.completed"}),
        json.dumps({"type": "turn.completed"}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(dup_completed_evs),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert "이벤트 생명주기 불일치" in str(exc_info.value)

    # 7. 별도 error 이벤트 (B14)
    error_evs = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "error", "message": "codex internal error"}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(error_evs),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert "오류 이벤트" in str(exc_info.value)

    # 8. 별도 turn.failed 이벤트 (B14)
    turn_failed_evs = [
        json.dumps({"type": "thread.started", "thread_id": "th-c03"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.failed", "error": {"message": "turn failed"}}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(turn_failed_evs),
            stderr_raw="",
            process_returncode=0,
            out_file_content=valid_file,
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert "turn.failed" in str(exc_info.value)


@pytest.mark.parametrize("case", [
    "missing-agent", "invalid-agent-text", "missing-file", "empty-file",
    "invalid-file-json", "answer-mismatch", "citation-mismatch",
])
def test_c03_final_message_and_output_file_rejections(case):
    """B16: 정상 생명주기에서 최종 메시지와 출력 파일만 바꾸어 각각 거부한다."""
    response = json.dumps({"answer": "답변 [C1S1]", "citation_ids": ["C1S1"]})
    events = [{"type": "thread.started"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"type": "agent_message", "text": response}},
              {"type": "turn.completed"}]
    output = response
    if case == "missing-agent":
        del events[2]
    elif case == "invalid-agent-text":
        events[2]["item"]["text"] = None
    elif case == "missing-file":
        output = None
    elif case == "empty-file":
        output = ""
    elif case == "invalid-file-json":
        output = "not JSON"
    elif case == "answer-mismatch":
        output = json.dumps({"answer": "다른 답변 [C1S1]", "citation_ids": ["C1S1"]})
    else:
        output = json.dumps({"answer": "답변 [C1S1]", "citation_ids": ["C1S2"]})
    stream = "\n".join(json.dumps(event) for event in events)
    with pytest.raises(GenerationError) as error:
        validate_codex_execution(stream, "", 0, output, build_codex_execution_policy("gpt-5.6-sol"), "test-version")
    assert error.value.trace["validation"]["status"] == "rejected"
    assert error.value.trace["stdout_jsonl"] == stream
    assert error.value.raw_response == (output or "")


def test_c04_aggregation_and_output_preservation():
    """C04 / R15, R17~R20, R23: 3개 이벤트+시간초과/종료코드 집계, 시작/갱신/완료 3개 누적, 스트림/바이트 정규화."""
    policy = build_codex_execution_policy("gpt-5.6-sol")

    # 1. 같은 금지 항목(web_search)의 started, updated, completed 3개 -> additional_tool_count == 3
    evs_3_tool = [
        json.dumps({"type": "thread.started", "thread_id": "th-c04"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.started", "item": {"type": "web_search"}}),
        json.dumps({"type": "item.updated", "item": {"type": "web_search"}}),
        json.dumps({"type": "item.completed", "item": {"type": "web_search"}}),
        json.dumps({"type": "turn.completed"}),
    ]
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="\n".join(evs_3_tool),
            stderr_raw="",
            process_returncode=0,
            out_file_content="",
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["additional_tool_count"] == 3

    # 2. 프로세스 실패 시 정상 답변 파일이 있어도 성공으로 승격되지 않음
    with pytest.raises(GenerationError) as exc_info:
        validate_codex_execution(
            stdout_raw="",
            stderr_raw="exit code 2 error",
            process_returncode=2,
            out_file_content=json.dumps({"answer": "정상답변 [C1S1]", "citation_ids": ["C1S1"]}),
            execution_policy=policy,
            cli_version="1.0.0",
        )
    assert exc_info.value.trace["validation"]["status"] == "rejected"
    assert exc_info.value.trace["process_returncode"] == 2


@pytest.mark.parametrize("fail_fn", ["load_spec", "load_encoder", "open_store"])
def test_c05_storage_readiness_and_prep_isolation(tmp_path, fail_fn, capsys):
    """C05 / R05, R06, R23: 미존재 persist 경로/미준비 컬렉션/준비 예외의 완전한 격리와 retrieval 단계 오류 보존."""
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    non_existent_dir = tmp_path / "no_such_persist_dir_123"

    # 1. 미존재 persist 경로 -> open_store 호출 0, 디렉터리 생성 0, retrieval 오류 반환
    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.open_store") as mock_open_store:
        record = run_pipeline(
            query_original="test query",
            reference_path=ref_path,
            persist_dir=non_existent_dir,
        )
        assert mock_open_store.call_count == 0
        assert not non_existent_dir.exists()  # 새 디렉터리가 생성되지 않아야 함
        assert record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "retrieval"
        assert record["retrieval"]["call_count"] == 0
        assert "Chroma persist 디렉터리가 존재하지 않습니다" in record["execution"]["error_message"]

    # 2. 기대 컬렉션 미확인 -> verify_store_ready에서 예외, open_store 호출 0 (합성 DB로 완전 격리)
    p_synthetic = tmp_path / "valid_sqlite_wrong_col"
    create_synthetic_store_db(p_synthetic / "chroma.sqlite3", collection_name="real_col")
    class WrongSpec(MockSpec):
        collection_name = "unconfirmed_wrong_collection"

    with patch("artagent.answer.load_spec", return_value=WrongSpec()), \
         patch("artagent.answer.open_store") as mock_open_store:
        record = run_pipeline(
            query_original="test query",
            reference_path=ref_path,
            persist_dir=p_synthetic,
        )
        assert mock_open_store.call_count == 0
        assert record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "retrieval"
        assert "기대 컬렉션 'unconfirmed_wrong_collection'이 저장소에 존재하지 않습니다" in record["execution"]["error_message"]

    # 3. 준비 단계(load_spec / load_encoder / open_store) 모의 예외 시 CLI --record JSONL에 오류 보존
    rec_err_file = tmp_path / f"prep_err_{fail_fn}.jsonl"
    store = MockStore()
    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value="session"), \
         patch("artagent.answer.open_store", return_value=store), \
         patch.object(store, "search", wraps=store.search) as search, \
         patch("artagent.answer.generate_llm_response") as generate:
        with patch(f"artagent.answer.{fail_fn}", side_effect=RuntimeError(f"mocked {fail_fn} failure")):
            with patch("sys.argv", ["artagent-answer", "test query", "--record", str(rec_err_file)]):
                ret = main()
                assert ret == 1

        search.assert_not_called()
        generate.assert_not_called()

    assert rec_err_file.is_file()
    lines = rec_err_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    saved = json.loads(lines[0])
    assert saved["execution"]["status"] == "error"
    assert saved["execution"]["failed_step"] == "retrieval"
    assert f"mocked {fail_fn} failure" in saved["execution"]["error_message"]
    assert saved["retrieval"]["call_count"] == 0
    assert saved["generation"] is None
    assert saved["output"]["exit_code"] == 1
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("case, config, active_count, error", [
    ("mixed", {}, 154, None),
    ("rawpedia-only", {"rawpedia_active": 154, "github_active": 0}, None, "GitHub"),
    ("github-only", {"rawpedia_active": 0, "github_active": 154}, None, "RawPedia"),
    ("all-excluded", {"rawpedia_active": 0, "rawpedia_excluded": 141,
                      "github_active": 0, "github_excluded": 13}, None, "활성 건수 0"),
    ("github-excluded", {"github_active": 0, "github_excluded": 13}, None, "GitHub"),
    ("rawpedia-excluded", {"rawpedia_active": 0, "rawpedia_excluded": 141}, None, "RawPedia"),
    ("partly-excluded", {"rawpedia_active": 139, "rawpedia_excluded": 2}, 152, None),
    ("missing-directory", None, None, "디렉터리가 존재하지 않습니다"),
    ("missing-db", None, None, "DB 파일이 존재하지 않습니다"),
    ("missing-collection", {"create_collection": False}, None, "컬렉션.*존재하지 않습니다"),
    ("unready", {"store_state": "indexing"}, None, "ready"),
    ("empty", {"rawpedia_active": 0, "github_active": 0}, None, "물리 건수 0"),
], ids=lambda value: value if isinstance(value, str) else None)
def test_c05_storage_readiness_counterexamples(tmp_path, capsys, case, config, active_count, error):
    """B05: 실제 준비 검사부터 CLI 기록까지 사례별 판정·호출·DB 보존을 확인한다."""
    from artagent.retrieval.provenance import sha256_bytes

    persist = tmp_path / case
    if config is not None:
        create_synthetic_store_db(persist / "chroma.sqlite3", **config)
    elif case == "missing-db":
        persist.mkdir()
    before = {p.name: sha256_bytes(p.read_bytes()) for p in persist.glob("*") if p.is_file()}
    spec = MockSpec()
    if error is None:
        assert verify_store_ready(persist, spec) == active_count
    else:
        with pytest.raises((FileNotFoundError, ValueError), match=error):
            verify_store_ready(persist, spec)

    record_path = tmp_path / f"{case}.jsonl"
    store = MockStore()
    response = json.dumps({"answer": "검색 문맥으로 확인할 수 없습니다.", "citation_ids": []})
    with patch("artagent.answer.load_spec", return_value=spec), \
         patch("artagent.answer.load_encoder", return_value="session") as encoder, \
         patch("artagent.answer.open_store", return_value=store) as open_mock, \
         patch.object(store, "search", wraps=store.search) as search, \
         patch("artagent.answer.generate_llm_response", return_value=(response, None, {"llm_provider": "mock"})) as generate, \
         patch("sys.argv", ["answer", "질문", "--persist-dir", str(persist), "--record", str(record_path)]):
        exit_code = main()
        calls = [encoder.call_count, open_mock.call_count, search.call_count, generate.call_count]

    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    captured = capsys.readouterr()
    assert record["output"]["exit_code"] == exit_code
    if error is None:
        assert exit_code == 0 and record["execution"]["status"] == "success"
        assert record["retrieval_config"]["active_count"] == active_count
        assert calls == [1, 1, 1, 1]
        assert record["retrieval"]["call_count"] == record["generation"]["call_count"] == 1
        assert captured.out == record["output"]["stdout"] + "\n"
        assert captured.err == ""
    else:
        assert exit_code == 1 and record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "retrieval"
        assert record["retrieval"]["call_count"] == 0 and record["generation"] is None
        assert calls == [0, 0, 0, 0]
        assert captured.out == "" and record["output"]["stderr"] in captured.err
    after = {p.name: sha256_bytes(p.read_bytes()) for p in persist.glob("*") if p.is_file()}
    assert after == before
    if case == "missing-directory":
        assert not persist.exists()


def test_c06_answer_json_type_contracts_and_rejections(tmp_path):
    """C06 / R12, R16: answer 문자열 및 citation_ids 원소 타입 검사 (타입 변환 수용 금지, generation 오류 trace 보존)."""
    # 1. _validate_llm_json_obj 단위 검증
    # 정상
    _validate_llm_json_obj({"answer": "valid string", "citation_ids": ["C1S1"]})
    _validate_llm_json_obj({"answer": "valid string", "citation_ids": []})

    # 비정상 answer
    for bad_answer in (None, 12345, ["ans"], {"text": "ans"}, "", "   "):
        with pytest.raises(ValueError):
            _validate_llm_json_obj({"answer": bad_answer, "citation_ids": []})

    # 비정상 citation_ids
    for bad_cids in ("C1S1", None, 123, [123], [None], [{"id": "C1S1"}]):
        with pytest.raises(ValueError):
            _validate_llm_json_obj({"answer": "valid answer", "citation_ids": bad_cids})

    # 2. CLI --record 에서 answer=null 인 경우 generation 오류로 안전하게 기록
    rec_c06 = tmp_path / "c06_bad_type.jsonl"
    bad_payload = json.dumps({"answer": None, "citation_ids": []})
    events = [
        json.dumps({"type": "thread.started", "thread_id": "th-c06"}),
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": bad_payload}}),
        json.dumps({"type": "turn.completed"}),
    ]
    def mock_subprocess_run(cmd, **kwargs):
        if "-o" in cmd:
            out_p = Path(cmd[cmd.index("-o") + 1])
            out_p.write_text(bad_payload, encoding="utf-8")
        return _make_mock_completed_proc(stdout="\n".join(events), returncode=0)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}):
        with patch("shutil.which", return_value="/usr/bin/codex"):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                with patch("artagent.answer.load_spec", return_value=MockSpec()), \
                     patch("artagent.answer.verify_store_ready", return_value=154), \
                     patch("artagent.answer.load_encoder", return_value=None), \
                     patch("artagent.answer.open_store", return_value=MockStore()):
                    with patch("sys.argv", ["artagent-answer", "test query", "--record", str(rec_c06)]):
                        ret = main()
                        assert ret == 1

    assert rec_c06.is_file()
    saved = json.loads(rec_c06.read_text(encoding="utf-8").strip())
    assert saved["execution"]["status"] == "error"
    assert saved["execution"]["failed_step"] == "generation"
    assert "문자열이 아닙니다" in saved["execution"]["error_message"]


@pytest.mark.parametrize("phase", ["agent", "file"])
@pytest.mark.parametrize("bad_obj", [
    {"answer": value, "citation_ids": []} for value in (None, 12345, ["ans"], {"text": "ans"}, "", "   ")
] + [
    {"answer": "valid answer", "citation_ids": value} for value in ("C1S1", None, 123, [123], [None], [{"id": "C1S1"}])
] + [{"citation_ids": []}, {"answer": "valid answer"}])
def test_c06_schema_rejected_in_agent_and_output_file(phase, bad_obj):
    """B12: 잘못된 답변 계약을 메시지·출력 파일 양쪽의 생성 경계에서 거부한다."""
    valid = {"answer": "정상 답변", "citation_ids": []}
    agent_text = json.dumps(bad_obj if phase == "agent" else valid)
    output = json.dumps(bad_obj if phase == "file" else valid)
    events = [{"type": "thread.started"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"type": "agent_message", "text": agent_text}},
              {"type": "turn.completed"}]
    stream = "\n".join(json.dumps(event) for event in events)
    attempts = []
    def mock_run(command, **kwargs):
        if "-o" not in command:
            return _make_mock_completed_proc("test-version")
        attempts.append(command)
        Path(command[command.index("-o") + 1]).write_text(output, encoding="utf-8")
        return _make_mock_completed_proc(stream)

    with patch.dict("os.environ", {"LLM_PROVIDER": "codex"}), \
         patch("shutil.which", return_value="/usr/bin/codex"), \
         patch("subprocess.run", side_effect=mock_run):
        with pytest.raises(GenerationError) as error:
            generate_llm_response("system", "user", {}, "질문")
    assert len(attempts) == 1
    assert error.value.raw_response == output
    trace = error.value.trace
    assert trace["stdout_jsonl"] == stream
    assert trace["validation"]["status"] == "rejected"
    assert trace["validation"]["summary_status"] == "complete"
    assert trace["execution_policy"]["application_status"] == "unconfirmed"


def test_c07_citation_deduplication_and_multiple_segments_preserved(tmp_path, capsys):
    """C07 / R21, R22: 동일 인용 ID 반복은 1회 표시, 같은 chunk/doc의 서로 다른 세그먼트(C1S1, C1S2)는 각각 보존."""
    # 같은 doc_id, 같은 chunk_id의 서로 다른 세그먼트 2개 정의
    context_citations = {
        "C1S1": {
            "citation_id": "C1S1",
            "display_name": "Exposure",
            "target_url": "https://rawpedia.es/Exposure#part1",
            "chunk_id": "chunk_common",
            "source_segment": {"doc_id": "rawpedia:Exposure", "ref_id": None, "char_start": 0, "char_end": 50},
        },
        "C1S2": {
            "citation_id": "C1S2",
            "display_name": "Exposure",
            "target_url": "https://rawpedia.es/Exposure#part2",
            "chunk_id": "chunk_common",
            "source_segment": {"doc_id": "rawpedia:Exposure", "ref_id": None, "char_start": 100, "char_end": 150},
        },
    }

    # 1. 동일 인용 ID 반복 (C1S1 2회) -> stdout [인용 목록]에는 1회만 표시
    raw_ans_repeat = "내용 1 [C1S1] 내용 2 [C1S1]"
    final_ans, stdout_text, used = validate_and_format_citations(raw_ans_repeat, ["C1S1", "C1S1"], context_citations)
    assert len(used) == 1
    assert stdout_text.count("- C1S1: Exposure") == 1

    # 2. 같은 doc_id/chunk_id이지만 서로 다른 세그먼트 (C1S1, C1S2) -> 둘 다 보존
    raw_ans_diff = "첫번째 세그먼트 [C1S1] 두번째 세그먼트 [C1S2]"
    final_ans, stdout_text, used = validate_and_format_citations(raw_ans_diff, ["C1S1", "C1S2"], context_citations)
    assert len(used) == 2
    assert "- C1S1: Exposure (https://rawpedia.es/Exposure#part1)" in stdout_text
    assert "- C1S2: Exposure (https://rawpedia.es/Exposure#part2)" in stdout_text

    hit = SearchHit(
        rank=1, chunk_id="chunk_common", source_type="rawpedia", doc_id="rawpedia:Exposure",
        source_group_id="rawpedia:Exposure", section_title="Exposure", content="검색 문맥",
        content_sha256="test-sha", original_metadata={"page_title": "Exposure"},
        source_segments=[dict(c["source_segment"], target_url=c["target_url"]) for c in context_citations.values()],
        distance=0.1, distance_text="0.100000",
    )
    for name, answer, cids, count in [
        ("repeated", raw_ans_repeat, ["C1S1", "C1S1"], 1),
        ("segments", raw_ans_diff, ["C1S1", "C1S2"], 2),
        ("mismatch", raw_ans_repeat, ["C1S2"], 0),
    ]:
        record_path = tmp_path / f"{name}.jsonl"
        response = json.dumps({"answer": answer, "citation_ids": cids})
        store = MockStore()
        with patch("artagent.answer.load_spec", return_value=MockSpec()), \
             patch("artagent.answer.verify_store_ready", return_value=154), \
             patch("artagent.answer.load_encoder", return_value="session"), \
             patch("artagent.answer.open_store", return_value=store), \
             patch.object(store, "search", return_value=[hit]), \
             patch("artagent.answer.generate_llm_response", return_value=(response, None, {"llm_provider": "mock"})), \
             patch("sys.argv", ["answer", "질문", "--record", str(record_path)]):
            assert main() == (1 if name == "mismatch" else 0)
        lines = record_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        saved = json.loads(lines[0])
        assert saved["generation"]["raw_response"] == response
        assert len(saved["citations"]) == count
        captured = capsys.readouterr()
        if name == "mismatch":
            assert saved["execution"]["failed_step"] == "citation_validation"
            assert captured.out == saved["output"]["stdout"] == ""
        else:
            assert captured.out == saved["output"]["stdout"] + "\n"
            assert saved["output"]["stdout"].count("- C1S1: Exposure") == 1
            assert saved["output"]["stdout"].count("- C1S2: Exposure") == (1 if count == 2 else 0)


def test_c08_existing_15_records_and_fingerprints_immutability():
    """C08 / R02, R09, R21, R23~R29: 15개 기존 성공 기록의 SHA-256 지문, 질문셋 SHA, 원응답/인용 100% 재현."""
    from artagent.retrieval.provenance import sha256_bytes

    records_path = Path("docs/T11_execution_records.jsonl")
    assert records_path.is_file()
    expected_records_sha = "5d3d9a7df432cbfac741d479c554aae69a6dfbc8039ed166331d7f5a8d1b64b7"
    actual_records_sha = sha256_bytes(records_path.read_bytes())
    assert actual_records_sha == expected_records_sha, f"기록 파일 지문 불일치: {actual_records_sha}"

    # 외부 질문셋 지문 확인
    query_set_path = DEFAULT_QUERY_SET_PATH
    expected_qs_sha = "91b7fb50b23c0514d3e3d24579cad32a07dc6dcc3c8a40774b9e2e9da0fa14e8"
    actual_qs_sha = sha256_bytes(query_set_path.read_bytes())
    assert actual_qs_sha == expected_qs_sha
    questions = {q["query_id"]: q for q in json.loads(query_set_path.read_bytes())["queries"]}

    records = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(records) == 15

    expected_qids = [
        "Q001", "Q004", "Q014", "Q021", "Q033",
        "Q044", "Q054", "Q063", "Q072", "Q080",
        "Q084", "Q086", "Q092", "Q093", "Q096",
    ]
    actual_qids = [r["query_id"] for r in records]
    assert actual_qids == expected_qids
    assert len({r["run_id"] for r in records}) == 15
    source_cache = {}
    hit_count = segment_count = citation_count = 0
    manual_qids = {"Q001", "Q004", "Q014", "Q054", "Q063", "Q086", "Q096"}

    for r in records:
        query = questions[r["query_id"]]
        assert r["query_set"]["path"] == str(query_set_path)
        assert r["query_set"]["sha256"] == expected_qs_sha
        assert r["input"]["query_original"] == query["query"]
        assert r["input"]["query_normalized"] == normalize_query(query["query"])
        assert r["runtime"]["llm_provider"] == "codex-cli"
        assert r["runtime"]["model_id"] == "gpt-5.6-sol"
        assert r["execution"]["status"] == "success" and r["output"]["exit_code"] == 0
        assert r["retrieval"]["call_count"] == r["generation"]["call_count"] == 1
        hits = [SearchHit(**h) for h in r["retrieval"]["hits"]]
        assert len(hits) == r["retrieval"]["hits_count"] == 5
        assert [(round(h.distance, 6), h.chunk_id) for h in hits] == sorted(
            (round(h.distance, 6), h.chunk_id) for h in hits)
        for hit in hits:
            hit_count += 1
            assert sha256_bytes(hit.content.encode()) == hit.content_sha256
            for segment in hit.source_segments:
                segment_count += 1
                path = DEFAULT_SOURCE_ROOT / segment["source_path"]
                if path not in source_cache:
                    source_cache[path] = path.read_bytes()
                raw = source_cache[path]
                assert sha256_bytes(raw) == segment["source_file_sha256"]
                pointer = segment.get("json_pointer")
                if pointer:
                    body = json.loads(raw)
                    for part in pointer.lstrip("/").split("/"):
                        part = part.replace("~1", "/").replace("~0", "~")
                        body = body[int(part)] if isinstance(body, list) else body[part]
                    assert sha256_bytes(body.encode()) == segment["body_sha256"]
                else:
                    body = raw.decode("utf-8")
                span = body[segment["char_start"]:segment["char_end"]]
                assert sha256_bytes(span.encode()) == segment["segment_sha256"]
                assert body.encode()[segment["byte_start"]:segment["byte_end"]] == span.encode()
                assert hit.content[segment["content_char_start"]:segment["content_char_end"]] == span

        user_prompt, context_citations, context_ids = build_prompt_and_citations(r["input"]["query_normalized"], hits)
        assert user_prompt == r["prompt"]["user_prompt"]
        assert r["prompt"]["system_instruction"] == SYSTEM_INSTRUCTION
        assert context_ids == r["prompt"]["context_citation_ids"]
        # prompt, answer, citations, stdout 일치 검증
        raw_ans = r["generation"]["parsed_answer"]
        cids = r["generation"]["parsed_citation_ids"]
        final_answer, stdout_rebuilt, used = validate_and_format_citations(raw_ans, cids, context_citations)
        assert final_answer == r["output"]["final_answer"]
        assert stdout_rebuilt == r["output"]["stdout"]
        assert used == r["citations"]
        citation_count += len(used)

        # 원본 stdout_jsonl 독립 재검증
        trace = r["generation"]["trace"]
        ev_lines = trace["stdout_jsonl"]
        policy = trace["execution_policy"]
        file_content = r["generation"]["raw_response"]
        parsed, usage, val_trace = validate_codex_execution(
            stdout_raw=ev_lines,
            stderr_raw=trace["stderr"],
            process_returncode=trace["process_returncode"],
            out_file_content=file_content,
            execution_policy=policy,
            cli_version=trace["cli_version"],
            process_error=trace.get("process_error"),
        )
        assert val_trace["validation"]["status"] == "verified"
        assert val_trace["validation"]["additional_tool_count"] == 0
        assert parsed == {"answer": raw_ans, "citation_ids": cids}
        assert usage == r["generation"]["usage"]
        for key, value in trace["validation"].items():
            assert val_trace["validation"][key] == value
        assert val_trace["execution_policy"] == policy
        assert validate_saved_trace(trace)["application_status"] == "unconfirmed"
        if query["expected_behavior"] == "grounded_answer":
            segments = [s for h in hits for s in h.source_segments]
            reached = all(any(
                s["source_path"] == e["source_path"] and s.get("json_pointer") == e.get("json_pointer")
                and s["byte_start"] <= e["byte_start"] and s["byte_end"] >= e["byte_end"]
                for s in segments) for e in query["evidence"] if e["role"] == "support")
            assert reached == r["verification"]["gold_reached"]
        if r["query_id"] in manual_qids:
            assert r["verification"]["manual_review"] == "verified"
            assert r["run_id"] in r["verification"]["notes"]

    assert (hit_count, segment_count, len(source_cache), citation_count) == (75, 93, 62, 17)
    assert sha256_bytes(records_path.read_bytes()) == expected_records_sha
    assert sha256_bytes(query_set_path.read_bytes()) == expected_qs_sha

    # 수동 검토 표본 확인
    q044 = next(r for r in records if r["query_id"] == "Q044")
    assert len(q044["citations"]) == 0
    assert q044["verification"]["gold_reached"] is False
    assert "근거 부족" in q044["verification"]["notes"]

    q086 = next(r for r in records if r["query_id"] == "Q086")
    assert q086["verification"]["gold_reached"] is False
    assert len(q086["citations"]) == 1

    q096 = next(r for r in records if r["query_id"] == "Q096")
    assert "슬라이더" in q096["output"]["stdout"] or "절차" in q096["output"]["stdout"]


def test_c09_normalization_and_retrieval_boundaries(tmp_path):
    """C09 / R01, R04, R07~R09: 정규화 및 검색 경계(빈 입력, 0/1/5개 hit 보존, 길이 초과 오류)."""
    # 1. 정규화 보존: 도구명, 숫자, 부정 표현, Unicode NFC
    raw = "  \u1100\u1161  Auto Levels 50%가   아닌가요?  "
    norm = normalize_query(raw)
    assert norm == "가 Auto Levels 50%가 아닌가요?"

    # 2. 빈 입력 시 검색/생성 0회
    with patch("artagent.answer.load_spec") as mock_spec, \
         patch("artagent.answer.generate_llm_response") as mock_gen:
        record = run_pipeline("", Path("ref"), Path("persist"))
        assert record["execution"]["status"] == "error"
        assert record["execution"]["failed_step"] == "normalization"
        assert mock_spec.call_count == 0
        assert mock_gen.call_count == 0

    # 3. 검색 0개 반환 시 다음 단계로 1회 전달
    class ZeroHitsStore:
        class collection:
            @staticmethod
            def count():
                return 10
        @staticmethod
        def search(q, sess):
            return []

    mock_resp = json.dumps({"answer": "근거가 없습니다.", "citation_ids": []})
    ref_path = Path("docs/T08_2_t9_handoff_reference.json").resolve()
    persist_dir = Path("dummy_persist")

    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value=None), \
         patch("artagent.answer.open_store", return_value=ZeroHitsStore()), \
         patch.object(ZeroHitsStore, "search", wraps=ZeroHitsStore.search) as search_zero, \
         patch("artagent.answer.generate_llm_response", return_value=(mock_resp, None, {"llm_provider": "mock"})) as generate_zero:
        record = run_pipeline("질문", ref_path, persist_dir)
        assert record["execution"]["status"] == "success"
        assert record["retrieval"]["hits_count"] == 0
        assert "(검색된 문맥이 없습니다.)" in record["prompt"]["user_prompt"]
        assert record["generation"]["call_count"] == 1
        search_zero.assert_called_once_with("질문", None)
        assert generate_zero.call_count == 1
        assert record["citations"] == []

    # 4. B07 / R07: 1개 및 5개 hit 반환 시 search 1회 호출, 순서 및 전체 필드 보존 (추가 k/source_key 인자 없음)
    recorded_search_args = []
    class MultiHitsStore:
        def __init__(self, hits):
            self.hits = hits
        def search(self, *args, **kwargs):
            recorded_search_args.append((args, kwargs))
            return self.hits

    hits_5 = [
        SearchHit(
            rank=i,
            chunk_id=f"c_{i}",
            source_type="rawpedia" if i % 2 == 0 else "github",
            doc_id=f"doc_{i}",
            source_group_id=f"doc_{i}",
            section_title=f"Sec {i}",
            content=f"Content {i}",
            content_sha256=f"sha_{i}",
            source_segments=[{"doc_id": f"doc_{i}", "ref_id": f"ref_{i}",
                              "target_url": f"http://doc_{i}#comment-{i}",
                              "char_start": 100 * i, "char_end": 100 * i + 9,
                              "content_char_start": 0, "content_char_end": 9}],
            original_metadata={"meta_key": f"val_{i}"},
            distance=0.05 * i,
            distance_text=f"{0.05 * i:.2f}",
        )
        for i in range(1, 6)
    ]
    query_set = tmp_path / "synthetic_queries.json"
    query_set.write_text(json.dumps({"queries": [{
        "query_id": "SYNTHETIC", "query": "질문 5개",
        "gold_support_doc_ids": ["GOLD_ONLY"], "expected_behavior": "LABEL_ONLY",
    }]}), encoding="utf-8")
    store_5 = MultiHitsStore(hits_5)
    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value="mock_sess"), \
         patch("artagent.answer.open_store", return_value=store_5), \
         patch("artagent.answer.generate_llm_response", return_value=(mock_resp, None, {"llm_provider": "mock"})) as generate_five:
        rec5 = run_pipeline("질문 5개", Path("ref"), Path("persist"),
                            query_id="SYNTHETIC", query_set_path=query_set)
        assert rec5["execution"]["status"] == "success"
        assert rec5["retrieval"]["hits_count"] == 5
        assert len(recorded_search_args) == 1
        args, kwargs = recorded_search_args[0]
        assert args == ("질문 5개", "mock_sess")
        assert kwargs == {}  # k/source_key 추가 인자 없음
        assert rec5["retrieval"]["hits"] == [asdict(hit) for hit in hits_5]
        assert generate_five.call_count == 1
        generation_args = generate_five.call_args.args
        assert generation_args[1] == rec5["prompt"]["user_prompt"]
        assert generation_args[3] == "질문 5개"
        for forbidden_label in ("GOLD_ONLY", "LABEL_ONLY", "SYNTHETIC"):
            assert forbidden_label not in json.dumps(generation_args)
        for hit in hits_5:
            assert hit.content in generation_args[1]
            assert hit.source_segments[0]["target_url"] in generation_args[1]
        for i, hit_dict in enumerate(rec5["retrieval"]["hits"]):
            assert hit_dict["chunk_id"] == f"c_{i+1}"
            assert hit_dict["content"] == f"Content {i+1}"
            assert hit_dict["original_metadata"] == {"meta_key": f"val_{i+1}"}

    # 1개 hit 대조
    recorded_search_args.clear()
    store_1 = MultiHitsStore([hits_5[0]])
    with patch("artagent.answer.load_spec", return_value=MockSpec()), \
         patch("artagent.answer.verify_store_ready", return_value=154), \
         patch("artagent.answer.load_encoder", return_value="mock_sess"), \
         patch("artagent.answer.open_store", return_value=store_1), \
         patch("artagent.answer.generate_llm_response", return_value=(mock_resp, None, {"llm_provider": "mock"})):
        rec1 = run_pipeline("질문 1개", Path("ref"), Path("persist"))
        assert rec1["execution"]["status"] == "success"
        assert rec1["retrieval"]["hits_count"] == 1
        assert len(recorded_search_args) == 1
        assert recorded_search_args[0] == (("질문 1개", "mock_sess"), {})
        assert rec1["retrieval"]["hits"] == [asdict(hits_5[0])]
        assert rec1["retrieval"]["hits"][0]["chunk_id"] == "c_1"

    # 5. B08 / R08: search 중 query 길이 초과 등 오류 발생 시 retrieval 단계 실패, 생성 0회, 전달 질문 미절단
    class ErrorStore:
        def __init__(self, error):
            self.error = error

        def search(self, q, sess):
            recorded_search_args.append(((q, sess), {}))
            raise ValueError(self.error)

    long_query = "아주 긴 질문 " * 50
    for error in ("Query string length exceeds limit", "Retrieved chunk integrity mismatch"):
        recorded_search_args.clear()
        with patch("artagent.answer.load_spec", return_value=MockSpec()), \
             patch("artagent.answer.verify_store_ready", return_value=154), \
             patch("artagent.answer.load_encoder", return_value="mock_sess"), \
             patch("artagent.answer.open_store", return_value=ErrorStore(error)), \
             patch("artagent.answer.generate_llm_response") as mock_gen_fail:
            rec_err = run_pipeline(long_query, Path("ref"), Path("persist"))
            assert rec_err["execution"]["status"] == "error"
            assert rec_err["execution"]["failed_step"] == "retrieval"
            assert error in rec_err["execution"]["error_message"]
            assert rec_err["input"]["query_original"] == long_query
            assert recorded_search_args == [((normalize_query(long_query), "mock_sess"), {})]
            assert rec_err["retrieval"]["call_count"] == 1
            assert rec_err["generation"] is None
            assert mock_gen_fail.call_count == 0

    # 6. B04 / R04: CLI 빈 입력 시 normalization 오류로 종료 1, 후속 T09 로드/검색/생성 호출 0회
    with patch("artagent.answer.load_spec") as mock_spec_cli, \
         patch("artagent.answer.generate_llm_response") as mock_gen_cli:
        with patch("sys.argv", ["artagent-answer", "   "]):
            ret_empty = main()
            assert ret_empty == 1
            assert mock_spec_cli.call_count == 0
            assert mock_gen_cli.call_count == 0
