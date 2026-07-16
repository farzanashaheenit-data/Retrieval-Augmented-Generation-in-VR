import os
import faiss
import numpy as np
import pickle
from typing import List, Any, Optional
from sentence_transformers import SentenceTransformer
from .data_loader import load_all_documents
from .embedding import EmbeddingPipeline


class VectorStore:
    """Handles document embedding generation using sentence transformer"""

    def __init__(
        self,
        persist_directory: str = "faiss_store",
        embedding_model: str = "all-MiniLM-L6-v2",
        chunk_size: int = 500,
        chunk_overlap: int = 200
    ):
        self.persist_directory = persist_directory
        os.makedirs(self.persist_directory, exist_ok=True)
        self.metadata = []
        self.embedding_model = embedding_model
        self.model = SentenceTransformer(embedding_model)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.chunks = []
        self.index = None
        print(f"Info: Loaded embedding model: {embedding_model}")

    def build_from_documents(self, documents: List[Any]):
        print(f"Info: Building from {len(documents)} documents")
        self.index = None
        self.metadata = []
        self.chunks = []

        emb_pipeline = EmbeddingPipeline(
            model_name=self.embedding_model,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )

        # Chunk - returns LangChain Documents
        chunked = emb_pipeline.chunk_documents(documents)
        print(f"Info: Got {len(chunked)} chunks")

        # Embed before converting to dicts
        embeddings = emb_pipeline.embed_documents(chunked)

        # Convert to dicts WITH metadata
        self.chunks = [
            {
                "text": chunk.page_content,
                "metadata": chunk.metadata
            }
            for chunk in chunked
        ]
        # Store metadata with text and metadata
        self.add_embeddings(
            np.array(embeddings).astype('float32'),
            self.chunks
        )
        self.save()
        print(f"Info: Vector store built and saved to: {self.persist_directory}")

    def add_embeddings(self, embeddings: np.ndarray, metadatas: List[Any] = None):
        """Add embeddings and their metadata to the vector store"""
        dim = embeddings.shape[1]
        if self.index is None:
            self.index = faiss.IndexFlatL2(dim)
        self.index.add(embeddings)
        if metadatas:
            self.metadata.extend(metadatas)
        print(f"Info: Added {embeddings.shape[0]} embeddings. Total: {len(self.metadata)}")

    def save(self):
        """Save the vector store to disk"""
        faiss_path = os.path.join(self.persist_directory, "faiss.index")
        meta_path = os.path.join(self.persist_directory, "metadata.pkl")
        faiss.write_index(self.index, faiss_path)
        with open(meta_path, "wb") as f:
            pickle.dump(self.metadata, f)
        print(f"Info: Saved FAISS index to {self.persist_directory}")

    def load(self):
        """Load the vector store from disk"""
        faiss_path = os.path.join(self.persist_directory, "faiss.index")
        meta_path = os.path.join(self.persist_directory, "metadata.pkl")
        self.index = faiss.read_index(faiss_path)
        with open(meta_path, "rb") as f:
            self.metadata = pickle.load(f)
        self.chunks = self.metadata
        print(f"Info: Loaded {len(self.metadata)} entries from {self.persist_directory}")

        # Debug: show first chunk structure
        if self.chunks:
            print(f"Info: Sample chunk keys: {list(self.chunks[0].keys())}")
            print(f"Info: Sample metadata: {self.chunks[0].get('metadata', {})}")

    def search(self, query_embedding: np.ndarray, top_k: int = 5):
        """Search for similar embeddings"""
        if self.index is None:
            raise ValueError("FAISS index not initialized.")
        D, I = self.index.search(query_embedding, top_k)
        results = []
        for idx, dist in zip(I[0], D[0]):
            if idx < len(self.metadata):
                meta = self.metadata[idx]
                results.append({
                    "index": idx,
                    "distance": dist,
                    "text": meta.get("text", ""),
                    "metadata": meta.get("metadata", {})
                })
        return results

    def query(self, query_text: str, top_k: int = 5):
        """Query the vector store with text"""
        if self.index is None:
            raise ValueError("FAISS index not initialized.")
        print(f"Info: Querying with: {query_text}")
        query_embedding = self.model.encode(
            [query_text],
            show_progress_bar=False
        ).astype('float32')
        return self.search(query_embedding, top_k)
