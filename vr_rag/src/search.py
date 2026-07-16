import os
import re
from pathlib import Path
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from .data_loader import load_all_documents
from .prompt_builder import build_system_prompt
from .vector_store import VectorStore


load_dotenv()


# ---------- Dr. Raggy persona prompts ----------

DR_RAGGY_PERSONA = (
    "You are Dr. Raggy, a calm, experienced clinical colleague briefing another "
    "clinician during a VR ward round. You speak naturally, like a doctor at the "
    "bedside, not like a form being read aloud."
)

ISBAR_HUMANIZE_RULES = (
    "Strict rules:\n"
    "- Use ONLY the verified facts provided. Do not invent, infer, or embellish "
    "any clinical detail (names, ages, conditions, medications, dosages, vitals).\n"
    "- Cover all five ISBAR elements (Introduction, Situation, Background, "
    "Assessment, Recommendation), but weave them into flowing sentences. "
    "Do NOT print the headers as labels.\n"
    "- Keep the response under 90 words. It will be spoken aloud, so it must "
    "sound natural and not run long.\n"
    "- Sound human: contractions, natural connectors (\"so\", \"his labs are\", "
    "\"I'd suggest\"), but stay professional.\n"
    "- If a field is marked unavailable, say briefly that you don't have that "
    "information. Never fabricate to fill a gap.\n"
    "- Do not use markdown, bullets, asterisks, or section labels."
)

FOLLOWUP_HUMANIZE_RULES = (
    "Strict rules:\n"
    "- Use ONLY the verified facts provided. Do not invent or embellish.\n"
    "- Answer the user's specific question directly and briefly. Do NOT recite "
    "the full ISBAR — only the part they asked about.\n"
    "- Keep it under 40 words. This is a quick spoken follow-up, not a briefing.\n"
    "- Sound like a colleague answering at the bedside: contractions, a natural "
    "opener (\"Yes, he's on...\", \"Her background is...\", \"I'd suggest...\"), "
    "professional tone.\n"
    "- If the field they asked about is unavailable, say so briefly.\n"
    "- Do not use markdown, bullets, asterisks, or section labels."
)


class RagSearch:
    def __init__(
        self,
        persist_dir: str = "faiss_store",
        embedding_model: str = "all-MiniLM-L6-v2",
        llm_model: str = "llama-3.1-8b-instant"
    ):
        self.vector_store = VectorStore(
            persist_directory=persist_dir,
            embedding_model=embedding_model
        )
        self.retriever = None
        faiss_path = os.path.join(persist_dir, "faiss.index")
        meta_path = os.path.join(persist_dir, "metadata.pkl")

        if os.path.exists(faiss_path) and os.path.exists(meta_path):
            print("Loading existing FAISS store...")
            self.vector_store.load()
        else:
            print("Building FAISS store...")
            data_dir = Path(persist_dir).resolve().parent / "data"
            docs = load_all_documents(str(data_dir))
            self.vector_store.build_from_documents(docs)

        groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.llm = ChatGroq(
            groq_api_key=groq_api_key,
            model_name=llm_model
        )
        # Toggle humanization off via env var if you ever need to debug raw output
        self.humanize_enabled = os.getenv("RAG_HUMANIZE", "true").lower() == "true"
        print(f"[INFO] Groq LLM initialized: {llm_model} humanize={self.humanize_enabled}")

    def _extract_text(self, result):
        metadata = result.get("metadata", {}) or {}
        return (
            result.get("text")
            or result.get("chunk")
            or result.get("page_content")
            or result.get("content")
            or metadata.get("text")
            or ""
        ).strip()

    def _matches_patient(self, result, patient_id=None, patient_name=None):
        metadata = result.get("metadata", {}) or {}
        if patient_id:
            chunk_id = str(metadata.get("patient_id") or "").upper().strip()
            target_id = str(patient_id).upper().strip()
            if chunk_id == target_id:
                return True

            text_upper = self._extract_text(result).upper()
            return (
                f"PATIENT ID: {target_id}" in text_upper
                or f"ID: {target_id}" in text_upper
                or f'"ID": "{target_id}"' in text_upper
                or f"'ID': '{target_id}'" in text_upper
            )

        if patient_name:
            chunk_name = (metadata.get("patient_name") or "").lower().strip()
            return chunk_name == patient_name.lower().strip()

        return True

    def _section_value(self, text: str, section: str):
        pattern = rf"(?ims)^\s*{re.escape(section)}\s*:\s*(.*?)(?=^\s*(?:Introduction|Situation|Background|Assessment|Recommendation)\s*:|\Z)"
        match = re.search(pattern, text)
        if not match:
            return None
        value = re.sub(r"\s+", " ", match.group(1)).strip()
        return value or None

    def _line_value(self, text: str, label: str):
        pattern = rf"(?im)^\s*{re.escape(label)}\s*:\s*(.+?)\s*$"
        match = re.search(pattern, text)
        if not match:
            return None
        value = match.group(1).strip()
        return value or None

    def _first_available(self, *values):
        for value in values:
            if value and str(value).strip():
                return str(value).strip()
        return "Not available in the provided record."

    def _build_patient_sections(self, texts, patient_id=None):
        combined = "\n\n".join(texts)
        source = texts[0] if texts else combined

        patient_line = self._first_available(
            self._line_value(source, "Patient ID"),
            self._line_value(source, "id"),
            patient_id,
        )
        name = self._first_available(
            self._line_value(source, "Name"),
            self._line_value(source, "Patient Name"),
        )
        age = self._line_value(source, "Age")
        gender = self._line_value(source, "Gender")
        ward = self._line_value(source, "Ward")
        doctor = self._first_available(
            self._line_value(source, "Attending Doctor"),
            self._line_value(source, "doctor"),
        )

        introduction = self._section_value(combined, "Introduction")
        if not introduction:
            intro_parts = []
            if patient_line != "Not available in the provided record.":
                intro_parts.append(f"Patient ID {patient_line}")
            if name != "Not available in the provided record.":
                intro_parts.append(name)
            if age:
                intro_parts.append(f"{age} years old")
            if gender:
                intro_parts.append(gender)
            if ward:
                intro_parts.append(f"ward {ward}")
            if doctor != "Not available in the provided record.":
                intro_parts.append(f"under {doctor}")
            introduction = ", ".join(intro_parts) if intro_parts else None

        situation = self._first_available(
            self._line_value(source, "Situation"),
            self._line_value(source, "situation"),
            self._section_value(combined, "Situation"),
        )
        background = self._first_available(
            self._line_value(source, "Background"),
            self._line_value(source, "ackground"),
            self._section_value(combined, "Background"),
        )
        assessment = self._first_available(
            self._line_value(source, "Assessment"),
            self._line_value(source, "Test_Results"),
            self._line_value(source, "Test Results"),
            self._section_value(combined, "Assessment"),
        )
        recommendation = self._first_available(
            self._line_value(source, "Recommendation"),
            self._line_value(source, "recommendation"),
            self._section_value(combined, "Recommendation"),
        )

        return {
            "Introduction": self._first_available(introduction),
            "Situation": situation,
            "Background": background,
            "Assessment": assessment,
            "Recommendation": recommendation,
        }

    # ---------- Deterministic templates (kept as fallback) ----------

    def _build_deterministic_isbar(self, texts, patient_id=None):
        sections = self._build_patient_sections(texts, patient_id=patient_id)
        return (
            f"Introduction:\n{sections['Introduction']}\n\n"
            f"Situation:\n{sections['Situation']}\n\n"
            f"Background:\n{sections['Background']}\n\n"
            f"Assessment:\n{sections['Assessment']}\n\n"
            f"Recommendation:\n{sections['Recommendation']}"
        )

    def _select_followup_sections(self, sections: dict, query: str) -> dict:
        q = (query or "").lower()
        wanted = []
        if any(t in q for t in [
            "who", "identify", "introduction", "name", "age", "gender",
            "ward", "doctor", "consultant", "attending"
        ]):
            wanted.append("Introduction")
        if any(t in q for t in [
            "situation", "happened", "presented", "presenting",
            "symptom", "symptoms", "condition", "status", "why admitted"
        ]):
            wanted.append("Situation")
        if any(t in q for t in [
            "background", "history", "medical history", "past",
            "chronic", "risk", "allergy", "allergies", "allergic"
        ]):
            wanted.append("Background")
        if any(t in q for t in [
            "assessment", "test", "result", "vital", "vitals",
            "blood", "exam", "finding", "findings"
        ]):
            wanted.append("Assessment")
        if any(t in q for t in [
            "recommendation", "recommend", "plan", "next", "should",
            "care plan", "management", "treat", "treatment", "action",
            "medication", "medicine", "drug", "dose", "dosage",
            "prescribed", "discharge", "give"
        ]):
            wanted.append("Recommendation")

        if not wanted:
            wanted = ["Situation"]

        deduped = []
        for s in wanted:
            if s not in deduped:
                deduped.append(s)
        return {s: sections[s] for s in deduped}

    def _build_patient_followup(self, texts, query, patient_id=None):
        sections = self._build_patient_sections(texts, patient_id=patient_id)
        selected = self._select_followup_sections(sections, query)
        return "\n\n".join(f"{k}:\n{v}" for k, v in selected.items())

    # ---------- Humanization layer ----------

    def _format_facts_for_llm(self, sections: dict) -> str:
        """Render verified facts as a compact bullet list for the LLM prompt."""
        lines = []
        for key, value in sections.items():
            if not value:
                continue
            if str(value).strip() == "Not available in the provided record.":
                lines.append(f"- {key}: (not available)")
            else:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines) if lines else "- (no facts available)"

    def _humanize(self, sections: dict, query: str, history_text: str, rules: str) -> str:
        """Run an LLM pass over verified facts to produce a natural spoken reply."""
        facts = self._format_facts_for_llm(sections)
        prompt = (
            f"{DR_RAGGY_PERSONA}\n\n"
            f"{rules}\n\n"
            f"Recent conversation (for context only, do not repeat):\n"
            f"{history_text or '(none)'}\n\n"
            f"User asked: {query}\n\n"
            f"Verified patient facts:\n{facts}\n\n"
            f"Your spoken reply:"
        )
        try:
            response = self.llm.invoke(prompt)
            text = (response.content or "").strip()
            if not text:
                raise ValueError("empty LLM response")
            return text
        except Exception as exc:
            # Fall back to deterministic template if LLM fails — never lose the answer
            print(f"[WARN] Humanization failed ({exc}), falling back to template")
            return "\n\n".join(f"{k}:\n{v}" for k, v in sections.items() if v)

    def _humanize_full_isbar(self, texts, query, history_text, patient_id=None):
        sections = self._build_patient_sections(texts, patient_id=patient_id)
        return self._humanize(sections, query, history_text, ISBAR_HUMANIZE_RULES)

    def _humanize_followup(self, texts, query, history_text, patient_id=None):
        sections = self._build_patient_sections(texts, patient_id=patient_id)
        relevant = self._select_followup_sections(sections, query)
        return self._humanize(relevant, query, history_text, FOLLOWUP_HUMANIZE_RULES)

    # ---------- Main entry point ----------

    def search_and_summarize(
        self,
        query: str,
        top_k: int = 5,
        patient_id: str = None,
        patient_name: str = None,
        session_id: str = None,
        mode: str = "general",
        history_text: str = "",
        scene_role: str = "general_assistant",
        scene_mode: str = "default",
        answer_style: str = "isbar"
    ) -> str:
        if self.retriever is not None:
            print(f"[RagSearch] Using HybridRetriever mode={mode} patient_id={patient_id}")
            results = self.retriever.retrieve(
                query=query,
                top_k=top_k,
                patient_id=patient_id,
                patient_name=patient_name,
                mode=mode
            )
        else:
            print("[RagSearch] Using direct vector store query")
            results = self.vector_store.query(query, top_k=top_k * 3)

        if patient_id or patient_name:
            results = [
                r for r in results
                if self._matches_patient(r, patient_id=patient_id, patient_name=patient_name)
            ]
            if not results:
                if patient_id:
                    return f"I could not find patient ID {patient_id} in the available records."
                return f"I could not find patient {patient_name} in the available records."

        texts = []
        for result in results[:top_k]:
            text = self._extract_text(result)
            if text:
                texts.append(text)
                print(f"[RagSearch] Retrieved text: {text[:100]}")
            else:
                print(f"[RagSearch] Empty result structure: {result}")

        if not texts:
            return "I could not find relevant information. Please try rephrasing your question."

        # Patient-mode: deterministic extraction, humanized presentation
        if mode == "patient" and (patient_id or patient_name):
            if not self.humanize_enabled:
                # Debug path — return raw template
                if answer_style == "followup":
                    print(f"[RagSearch] [debug] raw follow-up template patient_id={patient_id}")
                    return self._build_patient_followup(texts, query, patient_id=patient_id)
                print(f"[RagSearch] [debug] raw ISBAR template patient_id={patient_id}")
                return self._build_deterministic_isbar(texts, patient_id=patient_id)

            if answer_style == "followup":
                print(f"[RagSearch] Humanized follow-up patient_id={patient_id}")
                return self._humanize_followup(texts, query, history_text, patient_id=patient_id)
            print(f"[RagSearch] Humanized ISBAR patient_id={patient_id}")
            return self._humanize_full_isbar(texts, query, history_text, patient_id=patient_id)

        # Protocol / definitional / general modes — free-form LLM with retrieved context
        context = "\n\n".join(texts)
        system_role = build_system_prompt(scene_role, scene_mode)

        patient_rule = (
            f"The active patient ID is {patient_id}. Use only records for this exact patient ID."
            if patient_id
            else "No active patient ID was provided."
        )

        prompt = f"""
{system_role}

You are Dr. Raggy, a calm, experienced clinical colleague. You speak naturally,
like a doctor at the bedside.

Rules:
- Answer only using the provided context.
- {patient_rule}
- If a patient has multiple records with the same name, do not merge them. Use the patient ID as the source of truth.
- Sound conversational and human: contractions, natural openers. Keep it brief — under 80 words for spoken VR dialogue.
- Do not use markdown, bullets, asterisks, or section labels.
- If answering about ISBAR as a protocol, explain it concisely and clinically.
- Use recent conversation history for follow-up questions, but do not invent facts outside the context.
- If the requested patient is not in the context, say so clearly and ask for the patient ID.

Recent conversation:
{history_text}

User query:
{query}

Context:
{context}

Answer:
"""
        response = self.llm.invoke(prompt)
        return response.content

    # ------------------------------------------------------------------
    # Public helper for downstream features (quiz, reports).
    # Returns the verified ISBAR facts for a patient without invoking the LLM —
    # the same dict that the humanization pipeline starts from.
    # ------------------------------------------------------------------
    def get_patient_sections(self, patient_id: str = None, patient_name: str = None) -> dict:
        """
        Look up a patient and return their structured ISBAR sections:
          {
            "Introduction":  "...",
            "Situation":     "...",
            "Background":    "...",
            "Assessment":    "...",
            "Recommendation":"..."
          }

        Returns an empty dict if the patient cannot be found. No LLM call is
        made — this is pure retrieval + regex extraction, intended for callers
        like the quiz generator that need the raw facts.
        """
        if not patient_id and not patient_name:
            return {}

        if self.retriever is not None:
            results = self.retriever.retrieve(
                query=patient_id or patient_name,
                top_k=3,
                patient_id=patient_id,
                patient_name=patient_name,
                mode="patient",
            )
        else:
            results = self.vector_store.query(patient_id or patient_name, top_k=10)

        results = [
            r for r in results
            if self._matches_patient(r, patient_id=patient_id, patient_name=patient_name)
        ]
        if not results:
            return {}

        texts = []
        for result in results[:3]:
            text = self._extract_text(result)
            if text:
                texts.append(text)
        if not texts:
            return {}

        return self._build_patient_sections(texts, patient_id=patient_id)


if __name__ == "__main__":
    rag_search = RagSearch()
    query = "What is condition of patient D028?"
    summary = rag_search.search_and_summarize(query, top_k=3, patient_id="D028", mode="patient")
    print("Summary:", summary)