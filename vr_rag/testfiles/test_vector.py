from src.data_loader import load_all_documents
from src.vector_store import VectorStore

if __name__ == "__main__":
    print("Loading documents...")

    docs = load_all_documents("data")

    print("Building vector store...")

    store = VectorStore("faiss_store")

    store.build_from_documents(docs)

    print("Testing query...")

    results = store.query("patient John Doe", top_k=3)

    for r in results:
        print(r)