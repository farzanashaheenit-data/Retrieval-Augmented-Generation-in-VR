from src.data_loader import load_all_documents

docs = load_all_documents("data")
print(len(docs))