from src.embedding import EmbeddingPipeline
from src.data_loader import load_all_documents

docs = load_all_documents("data")

emb = EmbeddingPipeline()
chunks = emb.chunk_documents(docs)
vectors = emb.embed_documents(chunks)

print(len(chunks), len(vectors))