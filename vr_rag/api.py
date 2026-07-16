from contextlib import asynccontextmanager
from pathlib import Path
import os
import tempfile
import time
from typing import Optional, List
import re
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from src.data_loader import load_all_documents
from src.vector_store import VectorStore
from src.retriever import HybridRetriever
from src.search import RagSearch
from src.stt import SpeechToText
from uuid import uuid4
from src.gtts import textToSpeech
from src.query_processor import QueryProcessor
from src.quizgenerator import generate_quiz_from_sections
from src.report_generator import generate_report_pdf
from fastapi.responses import FileResponse




# Loggin
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rag-api")

state = {}
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
STORE_DIR = BASE_DIR / "faiss_store"

### storing chat sessions temporarily
chat_sessions = {}
# Startup and Shutdown Events
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting server...")
    docs = load_all_documents(str(DATA_DIR))
    store = VectorStore(str(STORE_DIR))
    if (STORE_DIR / "faiss.index").exists() and (STORE_DIR / "metadata.pkl").exists():
        store.load()
    else:
        store.build_from_documents(docs)
    retriever = HybridRetriever(store)
    rag = RagSearch(persist_dir=str(STORE_DIR))
    rag.retriever = retriever
    tts = textToSpeech()
    stt = SpeechToText(
        model_size=os.getenv("WHISPER_MODEL_SIZE", "base.en"),
        device=os.getenv("WHISPER_DEVICE", "cpu"),
        compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        beam_size=int(os.getenv("WHISPER_BEAM_SIZE", "1")),
        vad_filter=os.getenv("WHISPER_VAD_FILTER", "false").lower() == "true",
    )
    query_processor = QueryProcessor(store)
    state.update({
    "store": store,
    "retriever": retriever,
    "rag": rag,
    "stt": stt,
    "tts": tts,
    "query_processor": query_processor
    })
    logger.info("Server ready.")
    yield
    state.clear()
    logger.info("Shutdown complete.")

##API CALL
app = FastAPI(
    title="ISBAR RAG API",
    version="0.1",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# unity classes 
class AskRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    patient_id: Optional[str] = None
    top_k: int = 3
    scene_role: Optional[str] = "general_assistant"
    scene_mode: Optional[str] = "default"

class TTSRequest(BaseModel):
    text: str
    session_id: Optional[str] = None

class RetrievedSource(BaseModel):
    patient_id: Optional[str] = None
    patient_name: Optional[str] = None
    snippet: str
    score: float

class QuizOption(BaseModel):
    text: str

class QuizQuestion(BaseModel):
    id: str
    field: str
    question: str
    options: List[str]
    correct_index: int

class AskResponse(BaseModel):
    answer: str
    retrieved_patient: Optional[str] = None
    sources: List[RetrievedSource] = Field(default_factory=list)
    ignored: bool = False
    quiz: List[QuizQuestion] = Field(default_factory=list)

class HealthResponse(BaseModel):
    status: str
    ready: bool
    indexed_chunks: int
class PatientResult(BaseModel):
    patientId: str
    correct: int
    total: int

class ReportRequest(BaseModel):
    session_id: Optional[str] = None
    results: List[PatientResult] = Field(default_factory=list)

class ReportResponse(BaseModel):
    report_path: str
    total_correct: int
    total_questions: int
    percentage: float
class TranscribeResponse(BaseModel):
    text: str
##`HELPER FUNCTIONS
def get_health():
    return HealthResponse(
        status="ok",
        ready="rag" in state,
        indexed_chunks=len(state["store"].chunks) if "store" in state else 0
    )

# Routes for API to handle retrieval, transcription and text to speech
@app.get("/", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
def health():
    return get_health()


def detect_patient_id_from_text(text: str) -> Optional[str]:
    match = re.search(r"\b([A-Z])[\s\-\.]*(\d[\d\s\-\.]{1,8}\d)\b", text.upper())
    if match:
        digits = re.sub(r"\D", "", match.group(2))
        return f"{match.group(1)}{digits}"
    return None


def format_patient_choices_short(matches, limit: int = 5) -> str:
    choices = []
    for patient in matches[:limit]:
        patient_id = patient.get("patient_id") or "unknown ID"
        ward = patient.get("ward")
        label = f"{patient_id}"
        if ward:
            label += f" {ward}"
        choices.append(label)

    extra = len(matches) - limit
    if extra > 0:
        choices.append(f"{extra} more")
    return "; ".join(choices)


def edit_distance_at_most_one(a: str, b: str) -> bool:
    a = (a or "").upper().strip()
    b = (b or "").upper().strip()
    if abs(len(a) - len(b)) > 1:
        return False

    if len(a) == len(b):
        return sum(left != right for left, right in zip(a, b)) <= 1

    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = 0
    j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def resolve_near_pending_id(spoken_patient_ids, pending_ids) -> Optional[str]:
    near_matches = []
    for spoken_id in spoken_patient_ids:
        for pending_id in pending_ids:
            if edit_distance_at_most_one(spoken_id, pending_id):
                near_matches.append(pending_id)

    unique_matches = sorted(set(near_matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def infer_audio_suffix(file: UploadFile) -> str:
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac"}:
        return suffix

    content_type = (file.content_type or "").lower()
    if "mpeg" in content_type or "mp3" in content_type:
        return ".mp3"
    if "ogg" in content_type:
        return ".ogg"
    if "webm" in content_type:
        return ".webm"
    if "mp4" in content_type or "m4a" in content_type:
        return ".m4a"
    return ".wav"

def cleanup_temp_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Could not remove temp audio file: %s", path)
FOLLOWUP_KEYWORDS = [
    "situation", "background", "assessment", "recommendation",
    "history", "condition", "status", "symptom", "symptoms",
    "medication", "medicine", "drug", "prescribed", "treatment",
    "vital", "vitals", "blood pressure", "bp", "test", "result",
    "allergy", "allergic", "care plan", "next step", "plan",
    "management", "what about", "what did", "what was", "what should",
    "what do we do", "is there", "dose", "dosage", "discharge", "when",
    "her", "his", "their", "him", "he", "she", "they", "them"
]

def is_followup_question(query: str) -> bool:
    q = query.lower()
    return any(k in q for k in FOLLOWUP_KEYWORDS)


def is_repeated_filler_noise(query: str) -> bool:
    tokens = re.findall(r"[a-z0-9']+", (query or "").lower())
    if len(tokens) < 3:
        return False

    filler = {
        "ok", "okay", "yeah", "yes", "no", "um", "uh", "hmm",
        "thank", "thanks", "you"
    }
    if all(token in filler for token in tokens) and len(set(tokens)) <= 2:
        return True

    most_common = max(tokens.count(token) for token in set(tokens))
    return most_common >= 5 and most_common / len(tokens) >= 0.75

##Main Function@@@@@@@@@@@
@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if "rag" not in state:
        raise HTTPException(503, "RAG not ready")

    if not req.query.strip():
        raise HTTPException(400, "Query is empty")

    session_id = req.session_id or "default"

    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "history": [],
            "active_patient": None,
            "pending_patient_choices": [],
            "awaiting_patient_id": False
        }

    session_data = chat_sessions[session_id]
    history = session_data["history"]

    normalized_query = req.query.strip().lower()
    normalized_query = normalized_query.replace(",", "").replace(".", "")
    normalized_query = normalized_query.replace("!", "").replace("?", "")
    normalized_query = " ".join(normalized_query.split())
    ## for Dr.Raggy Key word
    def extract_wake_word_command(query: str):
        """
        Returns (matched, command_text):
        - matched=True if the query starts with a wake word (Dr. Raggy / mishearings)
        - command_text = whatever follows the wake word (empty string = bare wake word)
        - matched=False if no wake word found anywhere at the start
        """
        q = query.lower().strip()
        # Strip leading filler words Whisper often substitutes for greetings
        q = re.sub(r"^(and|um|uh|so|well|ok|okay|yeah|aye|i)\s+", "", q)

        # Wake word patterns: optional greeting + optional "dr/doctor" + rag/reg variant
        wake_prefix_pattern = (
            r"^(?:(?:hi|hello|hey|good morning|good afternoon|good evening)\s+)?"
            r"(?:(?:dr|doctor)\s*)?(?:rag\w*|reg\w*|rege)\b"
        )
        match = re.match(wake_prefix_pattern, q)
        if match:
            command = q[match.end():].strip()
            # Remove leading punctuation/connectives between wake word and command
            command = re.sub(r"^[,.\-:;\s]*(?:please|um|uh|so|well|now|then)?\s*", "", command)
            return True, command
        return False, ""
    def is_greeting(query: str) -> bool:
        q = query.lower().strip()
        wake_pattern = (
            r"(?:(hi|hello|hey|good morning|good afternoon|good evening)\s+)?"
            r"(?:(dr|doctor)\s*)?(?:rag\w*|reg\w*|rege)"
        )
        greetings = {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}
        wake_mishearings = {
            "can you talk to her again",
            "can you talk to rag again",
            "can you talk to raggy again",
            "can you talk to dr raggy",
            "can you talk to doctor raggy",
        }
        return (
            bool(re.fullmatch(wake_pattern, q))
            or q in greetings
            or q in wake_mishearings
        )

    wake_matched, command_text = extract_wake_word_command(normalized_query)
    if not wake_matched:
        # No "Dr. Raggy" prefix — silently ignore this utterance
        logger.info("Ignored (no wake word): %r", req.query)
        return AskResponse(
            answer="",
            retrieved_patient=session_data.get("active_patient"),
            ignored=True
        )
    if not command_text:
        # Bare wake word like "Hello Dr. Raggy" — return greeting
        logger.info("Wake word only, returning greeting")
        return AskResponse(
            answer="Hello! I'm Dr.Raggy. How can I assist you today?",
            retrieved_patient=session_data.get("active_patient")
        )

    # Wake word followed by a real command — rewrite the query to just the command
    # so the rest of /ask processes the actual question without the wake word noise.
    req.query = command_text
    normalized_query = command_text

    if is_repeated_filler_noise(normalized_query):
        logger.info("Ignored repeated filler transcript: %r", req.query)
        return AskResponse(
            answer="",
            retrieved_patient=session_data.get("active_patient")
        )

    casual_patterns = [
        r"i'?m doing good.*",
        r"i'?m good.*",
        r"i am good.*",
        r"how are you.*",
        r"i'?m fine.*",
        r"i am fine.*",
    ]

    if any(re.fullmatch(p, normalized_query) for p in casual_patterns):
        return AskResponse(
            answer="I'm doing well, thank you. How can I help you with a patient or ISBAR?",
            retrieved_patient=session_data.get("active_patient")
        )

    conversational = {
        "thank you": "You're welcome! Feel free to ask about any patient or the ISBAR protocol.",
        "thanks": "Happy to help! Let me know if you need anything else.",
        "okay thank you": "You're welcome.",
        "ok thank you": "You're welcome.",
        "okay thanks": "You're welcome.",
        "ok thanks": "You're welcome.",
        "ok": "Got it! What would you like to know?",
        "okay": "Sure! What can I help you with?",
        "got it": "Great! Let me know if you have any questions.",
        "alright": "Alright! What would you like to know?",
    }

    if normalized_query in conversational:
        return AskResponse(
            answer=conversational[normalized_query],
            retrieved_patient=session_data.get("active_patient")
        )

    try:
        qp = state["query_processor"]
        spoken_patient_ids = qp.detect_patient_ids(req.query)
        numeric_patient_ids = qp.detect_spoken_numeric_patient_ids(req.query)
        pending_choices = session_data.get("pending_patient_choices") or []
        pending_ids = {
            str(patient.get("patient_id") or "").upper()
            for patient in pending_choices
            if patient.get("patient_id")
        }
        if not spoken_patient_ids and numeric_patient_ids:
            bare_matches = qp.resolve_bare_numeric_patient_ids(req.query)
            if pending_choices:
                spoken_patient_ids = [
                    patient_id for patient_id in numeric_patient_ids
                    if patient_id in pending_ids
                ]
            elif len(bare_matches) == 1:
                req.patient_id = bare_matches[0]
                session_data["awaiting_patient_id"] = False
            elif len(bare_matches) > 1:
                return AskResponse(
                    answer=(
                        "I heard the number, but more than one patient ID matches it. "
                        "Please say the full patient ID including the letter prefix."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )
            elif session_data.get("awaiting_patient_id"):
                return AskResponse(
                    answer=(
                        "I heard only numbers. Please say the full patient ID "
                        "including the letter prefix, for example P one one zero one."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )
            else:
                return AskResponse(
                    answer=(
                        "I heard only numbers. Please say the full patient ID "
                        "including the letter prefix, for example P one one zero one."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )

        if pending_choices and spoken_patient_ids:
            matching_pending_ids = [
                patient_id for patient_id in spoken_patient_ids
                if patient_id in pending_ids
            ]
            if len(matching_pending_ids) == 1:
                req.patient_id = matching_pending_ids[0]
                session_data["awaiting_patient_id"] = False
            elif len(matching_pending_ids) > 1:
                return AskResponse(
                    answer=(
                        "I heard more than one ID. Please say just one: "
                        f"{format_patient_choices_short(pending_choices)}."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )
            else:
                near_pending_id = resolve_near_pending_id(
                    spoken_patient_ids,
                    pending_ids
                )
                if near_pending_id:
                    logger.info(
                        "Corrected spoken pending patient ID %s to %s",
                        spoken_patient_ids,
                        near_pending_id
                    )
                    req.patient_id = near_pending_id
                    session_data["awaiting_patient_id"] = False
                else:
                    return AskResponse(
                        answer=(
                            "That ID was not in the current choices. Please say one of: "
                            f"{format_patient_choices_short(pending_choices)}."
                        ),
                        retrieved_patient=session_data.get("active_patient")
                    )
        elif pending_choices and not spoken_patient_ids:
            query_type_for_pending = qp.classify_query(
                req.query,
                active_patient=session_data.get("active_patient")
            )
            if query_type_for_pending == "general":
                return AskResponse(
                    answer=(
                        "Please say the patient ID only: "
                        f"{format_patient_choices_short(pending_choices)}."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )

        elif session_data.get("awaiting_patient_id") and spoken_patient_ids:
            if len(spoken_patient_ids) == 1:
                req.patient_id = spoken_patient_ids[0]
                session_data["awaiting_patient_id"] = False
            else:
                return AskResponse(
                    answer="I heard more than one possible ID. Please say one patient ID only.",
                    retrieved_patient=session_data.get("active_patient")
                )

        query_type = qp.classify_query(
            req.query,
            active_patient=session_data.get("active_patient")
        )

        explicit_patient = qp.detect_explicit_patient(req.query)
        explicit_patient_id = req.patient_id or qp.detect_patient_id(req.query) or detect_patient_id_from_text(req.query)
        if explicit_patient_id:
            explicit_patient_id = qp.resolve_patient_id(explicit_patient_id)

        if explicit_patient_id:
            explicit_patient_id = explicit_patient_id.upper()
            explicit_patient = explicit_patient_id
            query_type = "patient"

        logger.info(f"Query type: {query_type}")
        logger.info(f"Explicit patient detected: {explicit_patient}")

        history_text = "\n".join(
            [f"{m['role']}: {m['content']}" for m in history[-4:]]
        )

        if query_type == "protocol":
            result = state["rag"].search_and_summarize(
                query=req.query,
                top_k=req.top_k,
                patient_id=None,
                session_id=session_id,
                mode="protocol",
                history_text=history_text,
                scene_role=req.scene_role,
                scene_mode=req.scene_mode
            )

            history.append({"role": "user", "content": req.query})
            history.append({"role": "assistant", "content": result})
            session_data["history"] = history[-6:]

            return AskResponse(
                answer=result,
                retrieved_patient=session_data.get("active_patient")
            )

        matched_patient = None
        matched_id = None
        matched_name_for_filter = None

        if explicit_patient_id:
            patient = qp.get_patient_by_id(explicit_patient_id)
            if not patient:
                return AskResponse(
                    answer=(
                        f"I could not find patient '{explicit_patient}'. Please check the ID or provide the full name."
                    ),
                    retrieved_patient=None
                )

            matched_id = explicit_patient_id
            matched_name_for_filter = patient.get("full_name")
            matched_patient = matched_id
            session_data["active_patient"] = matched_id
            session_data["pending_patient_choices"] = []
            session_data["awaiting_patient_id"] = False

        elif explicit_patient:
            name_matches = qp.find_patient_matches(req.query)

            if len(name_matches) > 1:
                session_data["pending_patient_choices"] = name_matches
                session_data["awaiting_patient_id"] = True
                return AskResponse(
                    answer=(
                        "I found more than one matching patient. Say one ID only: "
                        f"{format_patient_choices_short(name_matches)}."
                    ),
                    retrieved_patient=session_data.get("active_patient")
                )

            if not name_matches:
                return AskResponse(
                    answer=f"I could not find patient '{explicit_patient}' in records.",
                    retrieved_patient=None
                )

            patient = name_matches[0]
            matched_id = patient.get("patient_id")
            matched_name_for_filter = patient.get("full_name")
            matched_patient = matched_id or matched_name_for_filter
            session_data["active_patient"] = matched_patient
            session_data["pending_patient_choices"] = []
            session_data["awaiting_patient_id"] = False

        elif query_type == "patient" and session_data["active_patient"]:
            matched_patient = session_data["active_patient"]

            if detect_patient_id_from_text(matched_patient):
                matched_id = matched_patient.upper()
                _, matched_name_for_filter = qp.get_patient_filter(matched_id)
            else:
                matched_id, matched_name_for_filter = qp.get_patient_filter(matched_patient)

        elif query_type == "patient" and not session_data["active_patient"]:
            session_data["awaiting_patient_id"] = True
            return AskResponse(
                answer="Which patient are you asking about?",
                retrieved_patient=None
            )
        if query_type == "definitional":
            # User asked something like "what is elective?" or "explain X".
            # Pass to the LLM with patient context if available, so a
            # mid-conversation follow-up can be answered naturally.
            active = session_data.get("active_patient")
            definitional_query = req.query
            if active:
                # Give the LLM context about the active patient without
                # forcing patient-mode RAG retrieval.
                definitional_query = (
                    f"In the context of patient {active}, {req.query}"
                )

            result = state["rag"].search_and_summarize(
                query=definitional_query,
                top_k=req.top_k,
                patient_id=None,
                session_id=session_id,
                mode="protocol",  # free-form LLM answer, no patient ISBAR template
                history_text=history_text,
                scene_role=req.scene_role,
                scene_mode=req.scene_mode
            )

            history.append({"role": "user", "content": req.query})
            history.append({"role": "assistant", "content": result})
            session_data["history"] = history[-6:]

            return AskResponse(
                answer=result,
                retrieved_patient=active
            )

        if query_type == "general":
            active = session_data.get("active_patient")
            if active:
                # Don't drop the conversation — the user is mid-flow about
                # this patient. Try to answer in their context.
                result = state["rag"].search_and_summarize(
                    query=f"For patient {active}, {req.query}",
                    top_k=req.top_k,
                    patient_id=active if detect_patient_id_from_text(active) else None,
                    session_id=session_id,
                    mode="patient",
                    history_text=history_text,
                    scene_role=req.scene_role,
                    scene_mode=req.scene_mode,
                    answer_style="followup"
                )
                history.append({"role": "user", "content": req.query})
                history.append({"role": "assistant", "content": result})
                session_data["history"] = history[-6:]
                return AskResponse(
                    answer=result,
                    retrieved_patient=active
                )
            return AskResponse(
                answer="Please ask about a specific patient or the ISBAR protocol.",
                retrieved_patient=None
            )

        resolved_query = qp.resolve_query_with_patient(
            req.query,
            session_data["active_patient"]
        )
        
        answer_style = "followup" if is_followup_question(req.query) else "isbar"
        logger.info(
            f"Matched patient ID: {matched_id}, name: {matched_name_for_filter}, "
            f"answer_style={answer_style}"
        )

        result = state["rag"].search_and_summarize(
            query=resolved_query,
            top_k=req.top_k,
            patient_id=matched_id,
            patient_name=matched_name_for_filter,
            session_id=session_id,
            mode="patient",
            history_text=history_text,
            scene_role=req.scene_role,
            scene_mode=req.scene_mode,
            answer_style=answer_style
        )

        history.append({"role": "user", "content": req.query})
        history.append({"role": "assistant", "content": result})
        session_data["history"] = history[-6:]

        # Generate a quiz ONLY for full ISBAR briefings, not for follow-up Q&A.
        # The quiz tests recall of what Dr. Raggy just said.
        quiz_questions = []
        if answer_style == "isbar" and matched_id:
            try:
                sections = state["rag"].get_patient_sections(
                    patient_id=matched_id,
                    patient_name=matched_name_for_filter,
                )
                if sections:
                    # Seed by patient ID so same patient produces stable distractors
                    # while option order still shuffles per-call.
                    quiz_questions = generate_quiz_from_sections(
                        sections,
                        seed=hash(matched_id) % (2**31),
                    )
                    logger.info(f"Generated {len(quiz_questions)} quiz questions for {matched_id}")
            except Exception:
                logger.exception("Quiz generation failed")
                quiz_questions = []  # Quiz is optional — failure shouldn't break /ask

        return AskResponse(
            answer=result,
            retrieved_patient=session_data["active_patient"],
            quiz=quiz_questions,
        )
    except Exception as e:
        logger.exception("Ask failed")
        raise HTTPException(500, str(e))
@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(file: UploadFile = File(...)):
    if "stt" not in state:
        raise HTTPException(503, "STT not ready")
    try:
        start = time.time()
        audio = await file.read()
        if not audio:
            raise HTTPException(400, "Empty audio upload")
        
        suffix = infer_audio_suffix(file)
        logger.info(f"Received audio bytes: {len(audio)}, suffix={suffix}")
        text = await run_in_threadpool(state["stt"].transcribe, audio, "en", suffix)
        elapsed = time.time() - start
        logger.info(f"Transcription took {elapsed:.2f}s")
        logger.info(f"Transcript: {text!r}")

        if text is None:
            text = ""
        return TranscribeResponse(text=text.strip())
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(500, str(e))

###google text to speech
@app.post("/tts")
def tts(req: TTSRequest):
    if "tts" not in state:
        raise HTTPException(503, "TTS not ready")
    if not req.text.strip():
        raise HTTPException(400, "Text is empty")
    try:
        # Generate UNIQUE file every request
        tts_engine = state["tts"]
        output_file = os.path.join(
            tempfile.gettempdir(),
            f"{uuid4()}{tts_engine.file_extension}"
        )

        logger.info(
            f"TTS request text={req.text!r} output_file={output_file}"
        )

        tts_engine.synthesize(req.text, output_file)

        if not os.path.exists(output_file):
            raise HTTPException(500, "TTS file was not created")

        size = os.path.getsize(output_file)

        logger.info(f"Generated audio size={size}")

        return FileResponse(
            path=output_file,
            media_type=tts_engine.media_type,
            filename=f"speech{tts_engine.file_extension}",
            background=BackgroundTask(cleanup_temp_file, output_file),
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            })
     
    except Exception as e:
        logger.exception("TTS failed")
        raise HTTPException(500, str(e))
##Quiz and Report Generation
@app.post("/report", response_model=ReportResponse)
async def make_report(req: ReportRequest):
    """Generate a PDF report from end-of-session quiz results."""
    try:
        results = [r.dict() for r in req.results]
        total_correct = sum(r["correct"] for r in results)
        total_questions = sum(r["total"] for r in results)
        pct = (100.0 * total_correct / total_questions) if total_questions else 0.0

        path = generate_report_pdf(results, session_id=req.session_id)
        logger.info(f"Report generated: {path}")

        return ReportResponse(
            report_path=path,
            total_correct=total_correct,
            total_questions=total_questions,
            percentage=round(pct, 1),
        )
    except Exception:
        logger.exception("Report generation failed")
        raise HTTPException(status_code=500, detail="Report generation failed")
@app.get("/report/download")
async def download_report(path: str):
    """Serve a generated PDF report file for download."""
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=os.path.basename(path),
    )
@app.post("/reindex")
def reindex():
    if "store" not in state:
        raise HTTPException(503, "Store not ready")
    docs = load_all_documents(str(DATA_DIR))
    state["store"].build_from_documents(docs)
    retriever = HybridRetriever(state["store"])
    state["retriever"] = retriever
    state["rag"].retriever = retriever
    state["query_processor"] = QueryProcessor(state["store"])
    return {"status": "ok", "indexed_chunks": len(state["store"].chunks)}
