import os
import langchain
import json
from langchain_community.document_loaders import PyPDFLoader,PyPDFium2Loader,PyMuPDFLoader,TextLoader,CSVLoader
from langchain_community.document_loaders import Docx2txtLoader
from langchain_community.document_loaders.excel import UnstructuredExcelLoader
from langchain_community.document_loaders import JSONLoader
from pathlib import Path
from typing import List,Any
from langchain_core.documents import Document
import csv

class documentsloader:
    
    """Handles loading of documents from various formats and converting to langchain document structure"""
    def __init__(self,data_dir:str):
        self.data_dir=data_dir

def load_patient_json(file_path: Path) -> List[Document]:
    """Load each patient as a separate, structured document."""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    documents = []
    for patient in data.get("patients", []):
        intro = patient["ISBAR"]["introduction"]

        #  semantically rich text 
        text = (
            f"Patient ID: {patient['id']}\n"
            f"Name: {intro['name'].lower()}\n"
            f"Age: {intro['age']}\n"
            f"Gender: {intro['gender']}\n"
            f"Ward: {intro['ward']}\n"
            f"Attending Doctor: {intro['doctor']}\n\n"
            f"ISBAR Report for {intro['name']}:\n"
            f"Introduction: {intro['name']}, {intro['age']}-year-old {intro['gender']}, "
            f"admitted to {intro['ward'] } under {intro['doctor']}.\n"
            f"Situation: {patient['ISBAR']['situation']}\n"
            f"Background: {patient['ISBAR']['background']}\n"
            f"Assessment: {patient['ISBAR']['assessment']}\n"
            f"Recommendation: {patient['ISBAR']['recommendation']}"
        )
        documents.append(Document(
            page_content=text,
            metadata={
                "patient_id": patient["id"],
                "patient_name": intro["name"],
                "ward": intro["ward"],
                "source": str(file_path),
                "doc_type": "patient_isbar"
            }
        ))
    return documents

def load_patient_csv(file_path: Path) -> List[Document]:
    """Load each patient as a separate, structured document."""
    documents = []
    with open(file_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        print(f"Debug csv columns:{reader.fieldnames}")
        
        for i, patient in enumerate(reader):
            # find name flexibly
            name = (
                patient.get("name") or
                patient.get("Name") or
                patient.get("First Name") or
                patient.get("Fullname") or ""
            ).strip()
            
            if i < 3:  # show first 5 rows
                print(f"[DEBUG] Row {i}: name='{name}' id='{patient.get('id')}'")

            if not name:
                print("Skipping row with no name")
                continue

            # semantically rich text
            text_lines = [f"Patient Name: {name}"]
            label_overrides = {
                "ackground": "Background",
                "background": "Background",
                "situation": "Situation",
                "recommendation": "Recommendation",
                "doctor": "Attending Doctor",
                "ward": "Ward",
            }
            for key, value in patient.items():
                if key.lower() not in ("name", "patient_name") and value:
                    label = label_overrides.get(key.lower(), key)
                    text_lines.append(f"{label}: {value}")
            text = "\n".join(text_lines)

            documents.append(Document(
                page_content=text,
                metadata={
                    "patient_name": name,
                    "patient_id": patient.get("id") or patient.get("ID") or patient.get("patient_id") or None,
                    "ward": patient.get("ward") or patient.get("Ward") or None,
                    "doctor": patient.get("doctor") or patient.get("Doctor") or None,
                    "source": str(file_path),
                    "doc_type": "patient_csv"
                }
            ))
    print(f"[DEBUG] Loaded {len(documents)} patients froms {file_path}")
    return documents


def load_text_file(file_path: Path) -> List[Document]:
    """Load protocol/reference text files."""
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read().strip()

    if not text:
        return []

    return [
        Document(
            page_content=text,
            metadata={
                "source": str(file_path),
                "doc_type": "protocol_text"
            }
        )
    ]


def load_all_documents(data_dir:str)->List[Any]:
    """load all documents  fromk the data directory and convert to Langchain document strcuture
    Supported :PDF,JSON,CSV,EXCEL ,Word """

    ## use  project root folder to access data
    data_path=Path(data_dir).resolve()
    print(f"[DEBUG]Data Path:{data_path}")
    documents=[]

    #find all PDF files in loop
    pdf_files=list(data_path.glob("**/*.pdf"))
    print(f"[DEBUG] found :{len(pdf_files)} PDF Files : {[str(f) for f in pdf_files]}")
    for pdf in pdf_files:
        print (f"processing of : {pdf.name}")
        try:
            loader=PyPDFLoader(str(pdf))
            loaded=loader.load()
            for doc in loaded:
                doc.metadata["doc_type"] = doc.metadata.get("doc_type", "protocol_pdf")
            print(f"[DEBUG] Loaded :{len(loaded)} PDF doc from {pdf}")
            documents.extend(loaded) ## appending the documents
        except Exception as e:
            print (f"[Error] FAILED TO LOAD PDF FILE {pdf}:{e}")

    for txt_file in data_path.glob("text_files/**/*.txt"):
        print(f"Processing text file: {txt_file.name}")
        try:
            loaded_docs = load_text_file(txt_file)
            print(f"[DEBUG] Loaded {len(loaded_docs)} text documents from {txt_file}")
            documents.extend(loaded_docs)
        except Exception as e:
            print(f"[Error] Failed to load text file {txt_file}: {e}")
    
    for json_file in data_path.glob("**/*.json"):
        print(f"Processing JSON file: {json_file.name}")
        try:
            loaded_docs = load_patient_json(json_file)
            print(f"[DEBUG] Loaded {len(loaded_docs)} documents from {json_file}")
            documents.extend(loaded_docs)
        except Exception as e:
            print(f"[Error] Failed to load JSON file {json_file}: {e}")

    for csv_file in data_path.glob("**/*.csv"):
        print(f"Processing csv file: {csv_file.name}")
        try:
            loaded_docs=load_patient_csv(csv_file)
            print(f"[DEBUG] Loaded {len(loaded_docs)} documents from {csv_file}")
            documents.extend(loaded_docs)
        except Exception as e:
            print(f"[Error] Failed to load csv file {csv_file}: {e}")
    
    print(f"[DEBUG] Total documents loaded before indexing: {len(documents)}")
    for doc in documents[:10]:  # show first 10
      print(f"  - type={doc.metadata.get('doc_type')} name={doc.metadata.get('patient_name')} id={doc.metadata.get('patient_id')}")
    return documents  
