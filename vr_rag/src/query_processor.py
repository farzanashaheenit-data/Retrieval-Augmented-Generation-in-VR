import logging
import re

logger = logging.getLogger("rag-api")

PATIENT_ID_RE = re.compile(r"\b([A-Z])[\s\-\.]*(\d[\d\s\-\.]{1,8}\d)\b", re.IGNORECASE)


class QueryProcessor:
    def __init__(self, store):
        self.store = store
        self._patients_cache = None

    def normalize_text(self, text: str) -> str:
        text = text or ""
        text = text.replace("-", " ").replace("_", " ")
        text = re.sub(r"[^\w]+", " ", text.lower(), flags=re.UNICODE)
        return re.sub(r"\s+", " ", text).strip()

    def _metadata_from_chunk(self, chunk):
        if isinstance(chunk, dict):
            return chunk.get("metadata", {}) or {}
        if hasattr(chunk, "metadata"):
            return chunk.metadata or {}
        return {}

    def _apply_stt_name_corrections(self, text: str) -> str:
        text = text or ""
        replacements = {
            r"\band more\b": "emma",
            r"\ba more\b": "emma",
            r"\bem a\b": "emma",
        }
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def detect_patient_id(self, query: str):
        ids = self.detect_patient_ids(query)
        return ids[0] if ids else None

    def detect_patient_ids(self, query: str):
        text = query or ""
        ids = []
        seen = set()

        for prefix, digits_text in PATIENT_ID_RE.findall(text):
            digits = re.sub(r"\D", "", digits_text)
            if 3 <= len(digits) <= 6:
                patient_id = f"{prefix.upper()}{digits}"
                if patient_id not in seen:
                    ids.append(patient_id)
                    seen.add(patient_id)

        spoken_text = self.normalize_text(text)
        spoken_text = spoken_text.replace("dee zero", "d zero")
        spoken_text = spoken_text.replace("dee oh", "d zero")
        spoken_text = spoken_text.replace("deezer", "d zero")

        digit_words = {
            "zero": "0", "oh": "0", "o": "0",
            "one": "1", "won": "1",
            "two": "2", "to": "2", "too": "2",
            "three": "3", "tree": "3",
            "four": "4", "for": "4",
            "five": "5",
            "six": "6",
            "seven": "7",
            "eight": "8", "ate": "8", "a": "8",
            "nine": "9",
        }
        tens_words = {
            "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
            "fourteen": "14", "fifteen": "15", "sixteen": "16",
            "seventeen": "17", "eighteen": "18", "nineteen": "19",
            "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
            "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
        }

        tokens = spoken_text.split()
        prefix_words = {
            "d": "D", "dee": "D",
            "p": "P", "pee": "P", "pea": "P",
        }
        for i, token in enumerate(tokens):
            if token not in prefix_words:
                continue

            digits = ""
            for next_token in tokens[i + 1:i + 6]:
                if next_token.isdigit():
                    digits += next_token
                elif re.fullmatch(r"[a-z]\d+", next_token) and next_token[0] in digit_words:
                    digits += digit_words[next_token[0]] + next_token[1:]
                elif next_token in digit_words:
                    digits += digit_words[next_token]
                elif next_token in tens_words:
                    digits += tens_words[next_token]
                else:
                    break

            if 3 <= len(digits) <= 6:
                patient_id = f"{prefix_words[token]}{digits}"
                if patient_id not in seen:
                    ids.append(patient_id)
                    seen.add(patient_id)

        return ids

    def _edit_distance_at_most_one(self, a: str, b: str) -> bool:
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

    def resolve_patient_id(self, patient_id: str):
        if not patient_id:
            return None

        candidate = str(patient_id).upper().strip()
        if self.get_patient_by_id(candidate):
            return candidate

        short_id_match = re.fullmatch(r"([A-Z])(\d{3})", candidate)
        if short_id_match:
            prefix, digits = short_id_match.groups()
            expanded = f"{prefix}{digits[0]}{digits}"
            if self.get_patient_by_id(expanded):
                logger.info(
                    "Expanded likely omitted-digit patient ID %s to %s",
                    candidate,
                    expanded,
                )
                return expanded

        prefix = candidate[:1]
        matches = []
        for patient in self.get_known_patients():
            known_id = patient.get("patient_id")
            if not known_id or not known_id.startswith(prefix):
                continue
            if self._edit_distance_at_most_one(candidate, known_id):
                matches.append(known_id)

        unique_matches = sorted(set(matches))
        if len(unique_matches) == 1:
            logger.info("Corrected patient ID %s to %s", candidate, unique_matches[0])
            return unique_matches[0]

        return candidate

    def classify_query(self, query: str, active_patient: str = None) -> str:
        q = self.normalize_text(query)
        if self.detect_explicit_patient(query):
            return "patient"

        direct_protocol_keywords = [
            "isbar", "sbar", "protocol", "handoff", "framework",
            "what is isbar", "handover", "communication", "steps",
            "explain isbar", "what does isbar", "define isbar"
        ]
        patient_keywords = [
            "history", "diagnosis", "symptom", "symptoms", "treatment",
            "would like", "would like to know", "know about",
            "about patient", "medication", "vitals", "blood pressure", "bp", "case",
            "condition", "actions", "situation", "patient", "ward",
            "admitted", "assessment", "recommendation","medication", "vitals", "history", 
            "status", "lab results", "imaging", "test results", 
            "patient id", "id", "tell me about", "brief me about", "brief",
            "background", "status", "his", "her", "their", "him", "he",
            "she", "they", "them", "treat", "care plan", "next step",
            "what should we do", "what do we do", "management"
        ]
        followup_patient_keywords = [
            "his", "her", "their", "him", "he", "she", "they", "them",
            "background", "condition", "medication", "vitals", "history",
            "treatment", "status", "assessment", "recommendation",
            "situation", "what about", "what should", "care plan",
            "next step", "treat", "management", "doctor", "attending",
            # Generic continuation phrases — only meaningful when active_patient exists
            "tell me more", "more about", "anything else", "go on",
            "and then", "what else", "elaborate","expand on", "continue", "keep going"
        ]

        if any(k in q for k in direct_protocol_keywords):
            return "protocol"
        if active_patient and any(k in q for k in followup_patient_keywords):
            return "patient"
        if any(k in q for k in patient_keywords):
            return "patient"
        if "how to" in q:
            return "protocol"
        # Definitional / open questions get their own class so the API can route
        # them to a free-form LLM answer instead of refusing them.
        if self.is_definitional(q):
            return "definitional"
        return "general"

    def is_definitional(self, query_normalized: str) -> bool:
        """Detect 'what is X', 'what does X mean', 'define X', 'explain X' style questions."""
        patterns = [
            r"^what (is|are|does|do|was|were|means)\b",
            r"^(define|explain|describe|clarify|meaning of)\b",
            r"\bwhat (does|do) .* mean\b",
            r"\bmeaning of\b",
        ]
        return any(re.search(p, query_normalized) for p in patterns)

    def detect_spoken_numeric_patient_ids(self, query: str, default_prefix: str = "D"):
        digit_strings = self.detect_spoken_number_strings(query)
        ids = []
        seen = set()
        for digits in digit_strings:
            if len(digits) == 2:
                digits = digits.zfill(3)
            if 3 <= len(digits) <= 6:
                patient_id = f"{default_prefix.upper()}{digits}"
                if patient_id not in seen:
                    ids.append(patient_id)
                    seen.add(patient_id)

        return ids

    def detect_spoken_number_strings(self, query: str):
        digit_words = {
            "zero": "0", "oh": "0", "o": "0",
            "one": "1", "won": "1",
            "two": "2", "to": "2", "too": "2",
            "three": "3", "tree": "3",
            "four": "4", "for": "4",
            "five": "5",
            "six": "6",
            "seven": "7",
            "eight": "8", "ate": "8", "a": "8",
            "nine": "9",
        }
        tens_words = {
            "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
            "fourteen": "14", "fifteen": "15", "sixteen": "16",
            "seventeen": "17", "eighteen": "18", "nineteen": "19",
            "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
            "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
        }
        filler = {"patient", "id", "number", "the", "is", "it", "and"}
        tokens = [
            token for token in self.normalize_text(query).split()
            if token not in filler
        ]

        numbers = []
        seen = set()
        for start in range(len(tokens)):
            digits = ""
            consumed = 0
            for token in tokens[start:start + 5]:
                if token.isdigit():
                    digits += token
                elif token in digit_words:
                    digits += digit_words[token]
                elif token in tens_words:
                    digits += tens_words[token]
                else:
                    break
                consumed += 1

            if consumed == 0:
                continue
            if 3 <= len(digits) <= 6:
                if digits not in seen:
                    numbers.append(digits)
                    seen.add(digits)

        return numbers

    def resolve_bare_numeric_patient_ids(self, query: str):
        numeric_strings = self.detect_spoken_number_strings(query)
        if not numeric_strings:
            return []

        normalized = self.normalize_text(query)
        allowed_words = {
            "patient", "id", "number", "the", "is", "it", "and",
            "zero", "oh", "o", "one", "won", "two", "to", "too",
            "three", "tree", "four", "for", "five", "six", "seven",
            "eight", "ate", "a", "nine", "ten", "eleven", "twelve",
            "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
            "eighteen", "nineteen", "twenty", "thirty", "forty",
            "fifty", "sixty", "seventy", "eighty", "ninety"
        }
        if any(
            not token.isdigit() and token not in allowed_words
            for token in normalized.split()
        ):
            return []

        candidate_numbers = set()
        for digits in numeric_strings:
            candidate_numbers.add(digits)
            if len(digits) == 2:
                candidate_numbers.add(digits.zfill(3))

        matches = []
        for patient in self.get_known_patients():
            known_id = patient.get("patient_id") or ""
            known_digits = re.sub(r"\D", "", known_id)
            if known_digits in candidate_numbers:
                matches.append(known_id)

        return sorted(set(matches))

    def get_known_patients(self):
        if self._patients_cache is not None:
            return self._patients_cache

        patients = []
        seen = set()

        for chunk in self.store.chunks:
            metadata = self._metadata_from_chunk(chunk)
            name = metadata.get("patient_name")
            if not name or not isinstance(name, str):
                continue

            full_name = self.normalize_text(name)
            parts = full_name.split()
            patient_id = str(metadata.get("patient_id") or "").upper().strip() or None
            key = (patient_id, full_name)

            if key in seen:
                continue
            seen.add(key)

            patients.append({
                "patient_id": patient_id,
                "full_name": full_name,
                "display_name": name.strip(),
                "first_name": parts[0] if parts else "",
                "last_name": parts[-1] if parts else "",
                "ward": metadata.get("ward"),
                "doctor": metadata.get("doctor"),
                "age": metadata.get("age")
            })

        self._patients_cache = patients
        logger.info("Known patient records count: %s", len(patients))
        return patients

    def get_patient_by_id(self, patient_id: str):
        if not patient_id:
            return None

        target_id = str(patient_id).upper().strip()
        for patient in self.get_known_patients():
            if patient.get("patient_id") == target_id:
                return patient
        return None

    def find_patient_matches(self, text: str):
        query_norm = self.normalize_text(self._apply_stt_name_corrections(text))
        if not query_norm:
            return []

        patient_id = self.detect_patient_id(text)
        if patient_id:
            patient = self.get_patient_by_id(patient_id)
            return [patient] if patient else []

        stop_words = {
             "on", "please", "tell",
            "about", "patient", "the", "a", "an", "is", "of", "i",
            "would", "like", "know", "ward", "in", "what", "situation",
            "having", "id", "for", "with", "show", "give", "hi", "hey",
            "hello", "dr", "rag", "rags", "my", "mom"
        }
        useful_words = [w for w in query_norm.split() if w not in stop_words]

        exact_matches = []
        seen = set()
        for patient in self.get_known_patients():
            full_name = patient["full_name"]
            if full_name and full_name in query_norm:
                key = (patient.get("patient_id"), full_name)
                if key not in seen:
                    exact_matches.append(patient)
                    seen.add(key)

        if exact_matches:
            return exact_matches

        matches = []
        seen = set()
        for patient in self.get_known_patients():
            full_name = patient["full_name"]
            first = patient["first_name"]
            last = patient["last_name"]

            matched = False
            if first and last and first in useful_words and last in useful_words:
                matched = True
            elif last and last in useful_words:
                matched = True
            elif query_norm in {first, last}:
                matched = True

            if matched:
                key = (patient.get("patient_id"), full_name)
                if key not in seen:
                    matches.append(patient)
                    seen.add(key)

        return matches

    def format_patient_choices(self, matches, limit: int = 6) -> str:
        choices = []
        for patient in matches[:limit]:
            patient_id = patient.get("patient_id") or "unknown ID"
            name = patient.get("display_name") or patient.get("full_name") or "unknown name"
            ward = patient.get("ward")
            suffix = f", ward: {ward}" if ward else ""
            choices.append(f"{patient_id} - {name}{suffix}")

        extra = len(matches) - limit
        if extra > 0:
            choices.append(f"...and {extra} more")
        return "; ".join(choices)

    def detect_explicit_patient(self, query: str):
        logger.info("Detecting patient in: %r", query)

        patient_id = self.detect_patient_id(query)
        if patient_id:
            logger.info("Detected patient ID: %s", patient_id)
            return patient_id

        matches = self.find_patient_matches(query)
        if len(matches) == 1:
            return matches[0]["full_name"]
        if len(matches) > 1:
            logger.info("Detected ambiguous patient name with %s matches", len(matches))
            return matches[0]["full_name"]
        return None

    def resolve_patient_name(self, explicit_patient: str):
        matches = self.find_patient_matches(explicit_patient)
        if len(matches) == 1:
            return matches[0]["full_name"]
        return None

    def get_patient_filter(self, matched_patient: str):
        patient_id = self.detect_patient_id(matched_patient or "")
        if patient_id:
            patient = self.get_patient_by_id(patient_id)
            patient_name = patient["full_name"] if patient else None
            return patient_id, patient_name

        matches = self.find_patient_matches(matched_patient)
        if len(matches) == 1:
            patient = matches[0]
            return patient.get("patient_id"), patient.get("full_name")

        logger.info("Patient filter is ambiguous or missing for %r", matched_patient)
        return None, None

    def resolve_query_with_patient(self, query: str, active_patient: str):
        if not active_patient:
            return query

        active_id = self.detect_patient_id(active_patient)
        query_id = self.detect_patient_id(query)
        if active_id and query_id == active_id:
            return query

        q = query.lower()
        followup_terms = [
            "her", "his", "their", "background", "condition", "id",
            "medication", "vitals", "history", "treatment", "status",
            "assessment", "recommendation", "situation", "what about",
            "him", "he", "she", "they", "them", "care plan", "next step",
            "treat", "management", "what should", "what do we do"
        ]
        if any(term in q for term in followup_terms):
            return f"For patient {active_patient}, {query}"
        return query