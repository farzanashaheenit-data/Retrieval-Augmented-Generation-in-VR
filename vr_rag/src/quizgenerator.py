"""
Quiz generator for the Dr. Raggy clinical training simulator.
After an ISBAR briefing, this module produces 4 multiple-choice questions that
test the user's recall of the patient's key facts:

    1. Age
    2. Admission type (Situation)
    3. Background / history
    4. Recommended treatment

Each question has 4 options with one correct answer; the other 3 are
distractors drawn from a curated bank so they're plausible but wrong.

Generation is fully deterministic from the same input — no LLM call, no
randomness in the question content. Option ORDER is shuffled per-quiz so
the correct answer isn't always in the same slot.

Returns a list[dict] in this shape:
    [
      {
        "id": "q1",
        "field": "age",
        "question": "How old is the patient?",
        "options": ["28", "30", "35", "42"],
        "correct_index": 1
      },
      ...
    ]
"""
import random
import re
from typing import Optional

ADMISSION_TYPES = ["Urgent", "Elective", "Emergency", "Transfer", "Outpatient"]
BACKGROUND_CONDITIONS = [
    "Diabetes", "Hypertension", "Asthma", "Cancer", "Obesity",
    "Heart disease", "Stroke", "Kidney disease", "Arthritis",
    "Anxiety", "Depression", "COPD", "None reported",
]
RECOMMENDATIONS = [
    "Paracetamol", "Ibuprofen", "Aspirin", "Antibiotics", "Insulin",
    "Beta blockers", "Surgery", "Physical therapy", "Continue observation",
    "Discharge home", "Referral to specialist",
]

def _pick_distractors(correct: str, bank: list, n: int = 3) -> list:
    """Pick n distractors from bank, excluding any that match the correct answer."""
    correct_lower = correct.lower().strip() if correct else ""
    pool = [item for item in bank if item.lower().strip() != correct_lower]
    # Also exclude items the correct answer is a substring of (or vice versa)
    pool = [
        item for item in pool
        if correct_lower not in item.lower() and item.lower() not in correct_lower
    ]
    if len(pool) < n:
        # Pad with generic distractors if the bank is too small post-filtering
        pool = pool + ["Not specified", "Unknown", "Other"]
    return random.sample(pool, n)

def _build_question(field: str, question_text: str, correct: str, distractor_bank: list) -> dict:
    """Build a single MCQ with shuffled option order. Returns None if no correct answer."""
    if not correct or correct.strip() in ("", "Not available in the provided record."):
        return None

    correct = correct.strip()
    distractors = _pick_distractors(correct, distractor_bank, n=3)
    options = [correct] + distractors
    random.shuffle(options)
    correct_index = options.index(correct)

    return {
        "id": f"q_{field}",
        "field": field,
        "question": question_text,
        "options": options,
        "correct_index": correct_index,
    }

def _build_age_question(age_str: str) -> Optional[dict]:
    """Age questions have numeric distractors clustered around the correct value."""
    if not age_str:
        return None
    try:
        age = int(re.search(r"\d+", str(age_str)).group())
    except (ValueError, AttributeError):
        return None

    # Generate three plausible age distractors
    offsets = random.sample([-15, -10, -7, -5, 5, 7, 10, 15], 3)
    distractors = [max(0, age + offset) for offset in offsets]
    # Make sure none coincidentally match the real age
    distractors = [d if d != age else d + 5 for d in distractors]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for d in distractors:
        if d not in seen and d != age:
            unique.append(d)
            seen.add(d)
    # Top up if dedup removed any
    while len(unique) < 3:
        candidate = age + random.choice([-20, -12, 12, 20])
        if candidate > 0 and candidate != age and candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)

    options = [str(age)] + [str(d) for d in unique[:3]]
    random.shuffle(options)
    correct_index = options.index(str(age))

    return {
        "id": "q_age",
        "field": "age",
        "question": "How old is the patient?",
        "options": options,
        "correct_index": correct_index,
    }

def generate_quiz_from_sections(sections: dict, seed: Optional[int] = None) -> list:
    """
    Build a 4-question MCQ quiz from an ISBAR sections dict.

    `sections` is the same shape that search.py's _build_patient_sections() returns:
        {
          "Introduction": "Patient ID P1101, Bobby Jackson, 30 years old, Male, ward Oncology",
          "Situation":    "Urgent",
          "Background":   "Cancer",
          "Assessment":   "Normal",
          "Recommendation": "Paracetamol",
        }

    Returns a list of question dicts. Skips any question whose field is missing
    from the source data, so the quiz may have fewer than 4 questions if the
    patient record is incomplete.

    `seed` controls option shuffling deterministically — pass the patient ID
    string-hashed if you want the same patient to produce the same quiz.
    """
    if seed is not None:
        random.seed(seed)

    # Extract age from Introduction (it's embedded there, not a top-level key)
    age = _extract_age_from_intro(sections.get("Introduction") or "")

    questions = []

    age_q = _build_age_question(age)
    if age_q:
        questions.append(age_q)

    situation_q = _build_question(
        field="situation",
        question_text="What type of admission was this patient?",
        correct=sections.get("Situation") or "",
        distractor_bank=ADMISSION_TYPES,
    )
    if situation_q:
        questions.append(situation_q)

    background_q = _build_question(
        field="background",
        question_text="What is the patient's medical history?",
        correct=sections.get("Background") or "",
        distractor_bank=BACKGROUND_CONDITIONS,
    )
    if background_q:
        questions.append(background_q)

    recommendation_q = _build_question(
        field="recommendation",
        question_text="What treatment is recommended?",
        correct=sections.get("Recommendation") or "",
        distractor_bank=RECOMMENDATIONS,
    )
    if recommendation_q:
        questions.append(recommendation_q)

    return questions


def _extract_age_from_intro(intro: str) -> Optional[str]:
    """Pull a number followed by 'years' or 'year old' from the Introduction text."""
    if not intro:
        return None
    match = re.search(r"(\d+)\s*(?:years|year[s]?\s+old)", intro, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    # Fallback: any 1-3 digit number
    match = re.search(r"\b(\d{1,3})\b", intro)
    if match:
        return match.group(1)
    return None