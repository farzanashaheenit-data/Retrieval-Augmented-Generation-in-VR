from src.data_loader import documentsloader
from src.embedding import EmbeddingPipeline


text = documentsloader()
embed=EmbeddingPipeline
print (embed)