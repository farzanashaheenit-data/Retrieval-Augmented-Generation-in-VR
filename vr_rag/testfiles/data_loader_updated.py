import json

from pathlib import Path

from typing import List, Tuple, Any

from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document

FIELD_TO_STAGE = {

    "introduction":   "I",

    "situation":      "S",

    "background":     "B",

    "assessment":     "A",

    "recommendation": "R",

}

def _format_introduction(intro: dict) -> str:

    """Turn the introduction dict into a readable sentence for embedding."""

    return (

        f"Patient: {intro.get('name','Unknown')}, "

        f"Age: {intro.get('age','?')}, "

        f"Gender: {intro.get('gender','?')}, "

        f"Ward: {intro.get('ward','?')}, "

        f"Doctor: {intro.get('doctor','?')}."

    )


def load_patient_json(file_path: Path) -> List[Document]:

    """

    Parse json LangChain Documents.

    Each ISBAR field of each patient becomes one Document chunk,

    tagged with patient_id and stage in metadata.

    """

    docs = []

    with open(file_path, "r", encoding="utf-8") as f:

        data = json.load(f)
    patients = data.get("patients", [])

    print(f"[INFO] Found {len(patients)} patients in {file_path.name}")

    for patient in patients:

        patient_id = patient.get("id", "unknown")

        isbar      = patient.get("ISBAR", {})

        for field, stage in FIELD_TO_STAGE.items():

            value = isbar.get(field)

            if not value:

                continue

            # Introduction is a dict — flatten it to text

            if isinstance(value, dict):

                text = _format_introduction(value)

            else:

                text = str(value)

            doc = Document(

                page_content=text,

                metadata={

                    "patient_id": patient_id,   # "P001"

                    "stage":      stage,         # "S"

                    "data_type":  "patient",

                    "field":      field,         # "situation"

                    "source":     file_path.name,

                }

            )

            docs.append(doc)

            print(f"  [CHUNK] {patient_id} · stage={stage} → \"{text[:60]}...\"")


    return docs

def load_protocol_pdfs(protocols_dir: Path) -> List[Document]:

    """Load ISBAR protocol PDFs and tag them with stage from filename prefix."""

    docs = []

    ISBAR_STAGES = {"I", "S", "B", "A", "R"}

    for pdf in protocols_dir.glob("**/*.pdf"):

        stage = pdf.name[0].upper() if pdf.name[0].upper() in ISBAR_STAGES else "unknown"

        try:

            loaded = PyPDFLoader(str(pdf)).load()

            for doc in loaded:

                doc.metadata["stage"]     = stage

                doc.metadata["data_type"] = "protocol"

                doc.metadata["patient_id"]= "protocol"

            docs.extend(loaded)

            print(f"[PDF] {pdf.name} → {len(loaded)} pages, stage={stage}")

        except Exception as e:

            print(f"[ERROR] {pdf.name}: {e}")

    return docs

 
def load_all_documents(data_dir: str) -> Tuple[List[Document], List[Document]]:

    """

    Returns:

        protocol_docs: list of Documents from PDFs  (for faiss_protocol store)

        patient_docs :list of Documents from JSON  (for faiss_patient store)

    """

    data_path  = Path(data_dir).resolve()

    protocols_root = data_path / "protocols"

    patients_root  = data_path / "patients"

    protocol_docs: List[Document] = []

    patient_docs:  List[Document] = []

  ###PDF proctocols for ISBAR stages I,S,B,A,R

    if protocols_root.exists():

        protocol_docs = load_protocol_pdfs(protocols_root)

    else:

        print(f"[WARN] No protocols/ folder found at {protocols_root}")

   ###PATIENTS

    if patients_root.exists():

        for jf in patients_root.glob("**/*.json"):

            patient_docs.extend(load_patient_json(jf))

    else:

        for jf in data_path.glob("**/*.json"):

            patient_docs.extend(load_patient_json(jf))

    print(f"\n[DONE] Protocol chunks : {len(protocol_docs)}")

    print(f"[DONE] Patient chunks  : {len(patient_docs)}")

    return protocol_docs, patient_docs

print("[INFO] Data loader module loaded. Call load_all_documents(data_dir) to get protocol and patient documents.")