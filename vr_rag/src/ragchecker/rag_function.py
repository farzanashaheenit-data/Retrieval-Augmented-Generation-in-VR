import argparse
import json
import sys
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_loader import load_all_documents
from src.query_processor import QueryProcessor
from src.retriever import HybridRetriever
from src.search import RagSearch
from src.vector_store import VectorStore


DEFAULT_BENCHMARK_PATH = Path(__file__).with_name("checking_inputs.json")
DEFAULT_RAG_OUTPUT_PATH = Path(__file__).with_name("checking_inputs_with_rag.json")


def load_pipeline():
    data_dir = PROJECT_ROOT / "data"
    store_dir = PROJECT_ROOT / "faiss_store"

    store = VectorStore(str(store_dir))
    if (store_dir / "faiss.index").exists() and (store_dir / "metadata.pkl").exists():
        store.load()
    else:
        docs = load_all_documents(str(data_dir))
        store.build_from_documents(docs)

    retriever = HybridRetriever(store)
    rag = RagSearch(persist_dir=str(store_dir))
    rag.retriever = retriever
    query_processor = QueryProcessor(store)
    return rag, retriever, query_processor


def resolve_query(query: str, query_processor: QueryProcessor):
    query_type = query_processor.classify_query(query)
    if query_type == "protocol":
        return "protocol", None, None

    patient_id = query_processor.detect_patient_id(query)
    if patient_id:
        patient = query_processor.get_patient_by_id(patient_id)
        if not patient:
            raise ValueError(f"Patient ID {patient_id} was not found in the indexed records.")
        return "patient", patient_id, patient.get("full_name")

    matches = query_processor.find_patient_matches(query)
    if len(matches) > 1:
        choices = query_processor.format_patient_choices(matches)
        raise ValueError(
            "Patient name is ambiguous. Add the patient ID to the benchmark query. "
            f"Matches: {choices}"
        )
    if len(matches) == 1:
        patient = matches[0]
        return "patient", patient.get("patient_id"), patient.get("full_name")

    return query_type, None, None


def build_retrieved_context(results):
    context = []
    for index, result in enumerate(results):
        metadata = result.get("metadata", {}) or {}
        doc_id = (
            metadata.get("patient_id")
            or metadata.get("source")
            or result.get("doc_id")
            or f"chunk-{index}"
        )
        text = result.get("chunk") or result.get("text") or result.get("content") or ""
        if text:
            context.append({
                "doc_id": str(doc_id),
                "text": text
            })
    return context


def run_rag_for_query(
    query: str,
    rag: RagSearch,
    retriever: HybridRetriever,
    query_processor: QueryProcessor,
    top_k: int = 3,
):
    mode, patient_id, patient_name = resolve_query(query, query_processor)
    retrieved = retriever.retrieve(
        query=query,
        top_k=top_k,
        patient_id=patient_id,
        patient_name=patient_name,
        mode=mode,
    )
    response = rag.search_and_summarize(
        query=query,
        top_k=top_k,
        patient_id=patient_id,
        patient_name=patient_name,
        mode=mode,
    )
    return response, build_retrieved_context(retrieved)


def build_ragchecker_input(
    benchmark_path: Path = DEFAULT_BENCHMARK_PATH,
    output_path: Path = DEFAULT_RAG_OUTPUT_PATH,
    top_k: int = 3,
):
    rag, retriever, query_processor = load_pipeline()

    with open(benchmark_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data.get("results", []):
        response, retrieved_context = run_rag_for_query(
            query=item["query"],
            rag=rag,
            retriever=retriever,
            query_processor=query_processor,
            top_k=top_k,
        )
        item["response"] = response
        item["retrieved_context"] = retrieved_context

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return output_path


def main(argv: Optional[list[str]] = None):
    parser = argparse.ArgumentParser(
        description="Generate RAGChecker input by running the VR RAG pipeline on benchmark questions."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RAG_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args(argv)

    output_path = build_ragchecker_input(args.input, args.output, args.top_k)
    print(f"Wrote RAGChecker input with RAG outputs to: {output_path}")


if __name__ == "__main__":
    main()
