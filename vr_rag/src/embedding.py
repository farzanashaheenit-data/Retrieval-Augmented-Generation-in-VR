import numpy as np
import langchain
from langchain_text_splitters import RecursiveCharacterTextSplitter
from typing import List,Any   
from sentence_transformers import SentenceTransformer # embedding model will be available inside this
import uuid #everyrecord inserted to db will have an id will use this library
from uuid import uuid4
from .data_loader import load_all_documents
import os


class EmbeddingPipeline:
    """Handles document embedding generation using sentence transformer"""

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2", ### 384 dimensional dense
        chunk_size: int = 500,
        chunk_overlap: int = 200
    ):
        """Initialize the embedding manager
        Args:
            model_name: HuggingFace model name for sentence embeddings
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.model = SentenceTransformer(model_name)
        print(f"Loaded model: {model_name}")

    def chunk_documents(self,documents:list[Any])->list[Any]:
        """Chunk documents into smaller pieces for embedding generation
        Args:
            documents:List of langchain document objects"""
        splitter=RecursiveCharacterTextSplitter(chunk_size=self.chunk_size,
                                                chunk_overlap=self.chunk_overlap,
                                                separators=["\n\n","\n",".","!","?"," ", ""])
        chunks=splitter.split_documents(documents)
        print(f"Chunked {len(documents)} documents into {len(chunks)} chunks")
        return chunks
   
    def embed_documents(self, chunks: list[Any]) -> np.ndarray:
      """Generate embeddings for chunks - handles both
       LangChain Documents and plain dicts"""
    
      texts = []
      for chunk in chunks:
        if isinstance(chunk, dict):
            texts.append(chunk["text"])        
        else:
            texts.append(chunk.page_content)  
      print(f"Info: Generating embeddings for {len(texts)} chunks")
      embeddings = self.model.encode(
        texts, show_progress_bar=True)
      print(f"Info: Created {len(embeddings)} embeddings")
      return embeddings



     
     