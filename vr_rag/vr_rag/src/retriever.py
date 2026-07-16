from rank_bm25 import BM25Okapi ### highly recommended for lexical search: query is compared against colllection of text documents
import numpy as np
from typing import List, Any,Optional
from .vector_store import VectorStore


class HybridRetriever:
    """Combines BM25 and vector search for retrieval"""
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self._build_bm25()

    # BM25 BUILD
    def _build_bm25(self):
        self.chunks = self.vector_store.chunks
        self.tokenized_chunks = [
            c["text"].lower().split()
            for c in self.chunks
        ]
        self.bm25 = BM25Okapi(self.tokenized_chunks)

    def refresh(self):
        """"""##call after load
        self._build_bm25()

    # NORMALIZATION
    @staticmethod
    def _min_max(scores: np.ndarray) -> np.ndarray:
        if len(scores) == 0:
            return scores
        lo, hi = scores.min(), scores.max()
        if hi - lo < 1e-9:
            return np.zeros_like(scores)
        return (scores - lo) / (hi - lo)
    
    # RETRIEVAL
    def retrieve(
        self, 
        query: str, 
        top_k: int = 5, 
        alpha: float = 0.5,
        patient_id: Optional[str] = None, 
        patient_name: Optional[str] = None,
        mode: str = "general" 
    ):

        # --- Vector search ---
        sem_results = self.vector_store.query(query, top_k=top_k * 3)
        sem_scores = np.zeros(len(self.chunks))
        for r in sem_results:
            idx = r["index"]
            sem_scores[idx] = 1.0 / (1.0 + r["distance"])
        sem_scores = self._min_max(sem_scores)

        # --- BM25 search ---
        bm25_scores = self.bm25.get_scores(query.lower().split())
        bm25_scores = self._min_max(np.array(bm25_scores))
        # --- Combine scores ---
        
        combined = []
        for i in range(len(self.chunks)):
            score = alpha * sem_scores[i] + (1 - alpha) * bm25_scores[i]
            if score > 0:
                combined.append((i, score, sem_scores[i], bm25_scores[i]))
        combined.sort(key=lambda x: -x[1])
        
        results = []
        for idx, score, sem, kw in combined:
            chunk = self.chunks[idx]
            metadata = chunk.get("metadata", {}) or {}
            doc_type = metadata.get("doc_type", "")

            # Filter by mode
            if mode == "protocol":
                # Only return protocol/reference docs
                if doc_type.startswith("patient"):
                    continue
            elif mode == "patient":
                # Patient filters must be strict. Names are not enough when IDs exist.
                if patient_id:
                    chunk_id = str(metadata.get("patient_id") or "").upper().strip()
                    if chunk_id != str(patient_id).upper().strip():
                       continue  
                elif patient_name:
                    chunk_name = (metadata.get("patient_name") or "").lower().strip()
                    matched_name = (patient_name or "").lower().strip()
                    if chunk_name != matched_name:
                        continue

            # include metadata in results
            results.append({
                "chunk": chunk["text"],
                "metadata": metadata,        
                "patient_id": metadata.get("patient_id"),  
                "patient_name": metadata.get("patient_name"),  
                "doc_type": doc_type,        
                "score": score,
                "semantic_score": sem,
                "keyword_score": kw,
            })
            if len(results) >= top_k:
                break
        # Fallback only for broad non-patient searches. Patient searches must not leak
        # records from another patient when the filter misses.
        if not results:
            if mode == "patient" and (patient_id or patient_name):
                print(f"[Retriever] No patient results for "
                      f"patient_id={patient_id} patient_name={patient_name}")
                return []

            print(f"[Retriever] No results with filter "
                  f"mode={mode}, trying without patient filter...")
            for idx, score, sem, kw in combined[:top_k]:
                chunk = self.chunks[idx]
                metadata = chunk.get("metadata", {}) or {}
                doc_type = metadata.get("doc_type", "")
                if mode == "protocol" and doc_type.startswith("patient"):
                    continue
                results.append({
                    "chunk": chunk["text"],
                    "metadata": metadata,
                    "patient_id": metadata.get("patient_id"),
                    "patient_name": metadata.get("patient_name"),
                    "doc_type": doc_type,
                    "score": score,
                    "semantic_score": sem,
                    "keyword_score": kw,
                })

        print(f"[Retriever] Found {len(results)} results "
              f"for mode={mode} patient_id={patient_id}")
        return results
        
    
    
