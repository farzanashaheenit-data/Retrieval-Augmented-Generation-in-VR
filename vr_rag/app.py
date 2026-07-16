
import sys
from pathlib import Path
from src.data_loader import load_all_documents
from src.vector_store import VectorStore
from src.search import RagSearch
from fastapi import FastAPI
from src.embedding import EmbeddingPipeline
from src.retriever import HybridRetriever, RagRetriever


if __name__=="__main__":
    
    store=VectorStore("faiss_store")
    docs=load_all_documents("data")
    store.build_from_documents(docs)

   # #store.load()
    retriever =HybridRetriever(store,store.chunks)
    results= retriever.retrieve("What is situation of Maria?", top_k=3, alpha=0.5)


    print("Summary:", results)    





