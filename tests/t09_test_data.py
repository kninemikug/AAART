"""Build and verify a disposable T09 baseline from the fixed handoff inputs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def verify_reproduction(reproduction_dir: Path, reference_path: Path) -> None:
    """Reject incomplete, stale, or failed reproduction evidence."""
    reference_bytes = reference_path.read_bytes()
    reference = json.loads(reference_bytes)
    proof = json.loads((reproduction_dir / "reproduction.json").read_bytes())
    expected = {
        "status": "passed",
        "reference_sha256": hashlib.sha256(reference_bytes).hexdigest(),
        "selected_experiment_id": reference["selected"]["experiment_id"],
        **{key: reference[key] for key in (
            "protocol_sha256", "chunks", "vectors", "metrics", "query_log",
        )},
    }
    for key, value in expected.items():
        if proof.get(key) != value:
            raise ValueError(f"T09 reproduction evidence mismatch: {key}")


def prepare_store(
    action: str, reproduction_dir: Path, reference_path: Path,
    source_root: Path, store_dir: Path,
) -> None:
    """Use the production indexer, then check every stored baseline record."""
    import numpy as np

    from artagent.retrieval.embedding import embed_chunks, load_encoder
    from artagent.retrieval.provenance import load_selected_chunks, serialize_metadata
    from artagent.retrieval.store import open_store
    from artagent.retrieval.types import load_spec

    verify_reproduction(reproduction_dir, reference_path)
    spec = load_spec(reference_path)
    reference = json.loads(reference_path.read_bytes())
    chunks = load_selected_chunks(reproduction_dir / "chunks/manifest.json", spec, source_root)
    result = json.loads((reproduction_dir / "selected-results.json").read_bytes())["experiments"][0]
    expected_vectors = {}
    for source in ("rawpedia", "github"):
        vector_path = Path(result["document_inputs"][source]["vectors"]["path"])
        if not vector_path.resolve().is_relative_to(reproduction_dir.resolve()):
            raise ValueError(f"T09 vector artifact outside reproduction directory: {source}")
        if hashlib.sha256(vector_path.read_bytes()).hexdigest() != reference["vectors"][source]:
            raise ValueError(f"T09 reproduced vector file mismatch: {source}")
        expected_vectors[source] = np.load(vector_path, allow_pickle=False)
    if action == "build":
        if store_dir.exists() and any(store_dir.iterdir()):
            raise ValueError(f"Use an empty test store directory: {store_dir}")
        session = load_encoder(spec)
        computed = embed_chunks(chunks, session)
        for source in ("rawpedia", "github"):
            source_vectors = computed[[
                index for index, chunk in enumerate(chunks) if chunk.source_type == source
            ]]
            buffer = io.BytesIO()
            np.save(buffer, source_vectors)
            if hashlib.sha256(buffer.getvalue()).hexdigest() != reference["vectors"][source]:
                raise ValueError(f"T09 encoder vector fingerprint mismatch: {source}")
        store = open_store(store_dir, spec)
        report = store.index_all(chunks, session, source_root=source_root)
        if report.status != "success" or report.total_active != spec.total_expected_count:
            raise ValueError("T09 baseline indexing did not complete")
    else:
        if not (store_dir / "chroma.sqlite3").is_file():
            raise FileNotFoundError(f"Test store is missing: {store_dir}")
        store = open_store(store_dir, spec)

    collection = store.client.get_collection(spec.collection_name, embedding_function=None)
    metadata = collection.metadata or {}
    for key, expected in (
        ("store_state", "ready"), ("reference_sha256", spec.reference_sha256),
        ("protocol_sha256", spec.protocol_sha256),
    ):
        if metadata.get(key) != expected:
            raise ValueError(f"T09 baseline metadata mismatch: {key}")
    stored = collection.get(include=["documents", "metadatas", "embeddings"])
    positions = {chunk_id: index for index, chunk_id in enumerate(stored["ids"])}
    if set(positions) != {chunk.chunk_id for chunk in chunks}:
        raise ValueError("T09 baseline chunk ID set mismatch")
    for chunk in chunks:
        index = positions[chunk.chunk_id]
        if stored["documents"][index] != chunk.content:
            raise ValueError(f"T09 baseline document mismatch: {chunk.chunk_id}")
        if stored["metadatas"][index] != serialize_metadata(chunk, spec, excluded=False):
            raise ValueError(f"T09 baseline provenance mismatch: {chunk.chunk_id}")
    for source, expected_count in (
        ("rawpedia", spec.rawpedia_expected_count), ("github", spec.github_expected_count),
    ):
        source_chunks = [chunk for chunk in chunks if chunk.source_type == source]
        if len(source_chunks) != expected_count:
            raise ValueError(f"T09 baseline source count mismatch: {source}")
        vectors = np.asarray([
            stored["embeddings"][positions[chunk.chunk_id]] for chunk in source_chunks
        ], dtype=np.float32)
        # Chroma's returned float32 values can differ at the last bit. The
        # encoder/file fingerprints above are exact; persistence is checked
        # numerically at float32 precision, tighter than the handoff tolerance.
        if not np.allclose(vectors, expected_vectors[source], rtol=0, atol=np.finfo(np.float32).eps):
            raise ValueError(f"T09 persisted vector mismatch: {source}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--reproduction-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    args = parser.parse_args()
    prepare_store(args.action, args.reproduction_dir, args.reference, args.source_root, args.store_dir)


if __name__ == "__main__":
    main()
