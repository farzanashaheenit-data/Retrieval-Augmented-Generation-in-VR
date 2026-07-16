import os
import langchain
from langchain_community.document_loaders import PyPDFLoader,PyPDFium2Loader,PyMuPDFLoader,TextLoader,CSVLoader
from langchain_community.document_loaders import Docx2txtLoader
from langchain_community.document_loaders.excel import UnstructuredExcelLoader
from langchain_community.document_loaders import json_loader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pathlib import Path
from typing import List,Any

def load_all_documents(data_dir:str)->List[Any]:
    """load all documents  fromk the data directory and convert to Lanchain document strcuture
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
            print(f"[DEBUG] Loaded :{len(loaded)} PDF doc from {pdf}")
            documents.extend(loaded) ## appending the documents
        except Exception as e:
            print (f"[Error] FAILED TO LOAD PDF FILE {pdf}:{e}")


    ### json files
    json_files=list(data_path.glob("**/*.json"))
    print(f"[DEBUG] found :{len(json_files)} JSON Files : {[str(f) for f in json_files]}")
    for json in json_files:
        print (f"processing of : {json.name}")
        try:
            loader=json_loader(str(json))
            loaded=loader.load()
            print(f"[DEBUG] Loaded :{len(loaded)} jSON doc from {json}")
            documents.extend(loaded) ## appending the documents
        except Exception as e:
            print (f"[Error] FAILED TO LOAD JSON FILE {json}:{e}")
    
    return documents