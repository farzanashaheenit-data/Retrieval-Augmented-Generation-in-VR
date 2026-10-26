# Dr. Raggy Voice-Driven Clinical Handover Training Simulator

A Unity-based clinical training simulator that lets users practice receiving ISBAR patient handovers from an AI-driven virtual doctor, then tests their recall through an interactive quiz.

**Speak naturally → receive a structured briefing → get quizzed on what you remember → download a performance report.**

<!-- Add a demo GIF here when you have one -->
<!-- ![Demo](docs/demo.gif) -->

## Table of Contents

- [What It Does](#what-it-does)
- [System Architecture](#system-architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Setup](#setup)
- [Running the Simulator](#running-the-simulator)
- [Features](#features)
- [How the Pipeline Works](#how-the-pipeline-works)
- [Key Design Decisions](#key-design-decisions)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Future Work](#future-work)
- [Acknowledgments](#acknowledgments)

## What It Does

Clinical handovers — the moment one clinician briefs another on a patient's status — are where much information is either preserved or lost. The ISBAR protocol (Introduction, Situation, Background, Assessment, Recommendation) exists to make handovers consistent, but training junior clinicians requires supervised role-play that's hard to scale.

Dr. Raggy is a proof-of-concept that explores whether an AI-driven simulator can provide that practice on demand. The user speaks to a virtual doctor named "Dr. Raggy," who delivers structured ISBAR briefings on patients drawn from a database. When the user is done reviewing patients, a recall quiz appears and a PDF performance report is generated.

**Example interaction:**

> **User:** "Dr. Raggy, brief me about patient P1101."
> **Dr. Raggy:** *"Emma Wilson, a 65-year-old female, admitted to neurology under Dr. Smith, has been with us since admission with sudden weakness on one side. She's a chronic smoker, so we need to keep that in mind. Her vitals are stable, but her labs are showing mild dehydration, which we're managing. I'd suggest we schedule a specialist review to further assess her condition."*
>
> **User:** *(later)* "Dr. Raggy, brief me about patient P1102..."
>
> **User:** *"Dr. Raggy, end handover."*
> **Quiz appears** with questions about each patient reviewed.
> **PDF report generated** with per-patient recall scores.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Unity Client (VR-ready)                 │
│  ┌───────────────────┐  ┌────────────────────────────────┐  │
│  │   RagClient.cs    │  │  DoctorBehaviorController.cs   │  │
│  │  (orchestrator)   │  │  (avatar state machine)        │  │
│  └───────────────────┘  └────────────────────────────────┘  │
│  ┌───────────────────┐  ┌────────────────────────────────┐  │
│  │   QuizPanel.cs    │  │  InfoCanvasDisplay.cs          │  │
│  │   (quiz UI)       │  │  (status pill + response text) │  │
│  └───────────────────┘  └────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │  HTTP (localhost:8000)
┌───────────────────────────▼─────────────────────────────────┐
│                    Python Backend (FastAPI)                 │
│  ┌───────────────┐  ┌────────────────┐  ┌────────────────┐  │
│  │  /transcribe  │  │     /ask       │  │     /tts       │  │
│  │  (Whisper)    │  │  (RAG + LLM)   │  │   (Piper)      │  │
│  └───────────────┘  └────────────────┘  └────────────────┘  │
│  ┌───────────────┐  ┌────────────────┐                      │
│  │   /report     │  │ /report/       │                      │
│  │ (PDF export)  │  │  download      │                      │
│  └───────────────┘  └────────────────┘                      │
│         ┌───────────────────────────────────┐               │
│         │  FAISS Vector Store (55K records) │               │
│         └───────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

## Tech Stack

**Backend (Python)**
- **FastAPI** : HTTP API
- **faster-whisper** : Speech recognition
- **FAISS** : Vector similarity search over patient records
- **sentence-transformers** : Text embedding
- **Groq (LLaMA)** : LLM humanization layer
- **Piper** : Neural text-to-speech (runs locally, low-latency)
- **ReportLab** : PDF report generation

**Unity Client (C#)**
- **Unity 6.3 LTS** with URP
- **uLipSync** : Real-time viseme-based lip synchronization
- **Reallusion CC4 Character** : Avatar rig
- **Mixamo** : Body animations (idle, talking)
- **TextMeshPro** : UI text rendering

## Repository Structure

```
dr-raggy/
├── README.md                    ← You are here
├── LICENSE
├── .gitignore
├── docs/                        ← Screenshots, diagrams
├── backend/
│   ├── requirements.txt
│   ├── api.py                   ← FastAPI endpoints
│   ├── src/
│   │   ├── search.py            ← RAG + ISBAR humanization
│   │   ├── query_processor.py   ← Query type detection, patient resolution
│   │   ├── data_loader.py       ← CSV parsing, FAISS indexing
│   │   ├── quiz_generator.py    ← MCQ generation from patient data
│   │   ├── report_generator.py  ← PDF report builder
│   │   ├── stt.py               ← Whisper wrapper
│   │   └── gtts.py              ← Piper wrapper (persistent daemon)
│   └── models/                  ← Whisper/Piper models (download separately)
└── unity/
    ├── Assets/
    │   ├── Scenes/
    │   │   └── DoctorHandoverScene.unity
    │   └── Scenes/scripts/
    │       ├── ragClient.cs                  ← Main Unity orchestrator
    │       ├── DoctorBehaviorController.cs   ← Avatar state machine
    │       ├── QuizPanel.cs                  ← Quiz UI controller
    │       └── InfoCanvasDisplay.cs          ← Status pill + response panel
    ├── ProjectSettings/
    └── Packages/
```

## Setup

### Prerequisites

- Python 3.10 or later
- Unity 6.3 LTS or later
- A microphone
- A Groq API key (free tier is fine) — https://console.groq.com

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/dr-raggy.git
cd dr-raggy
```

### 2. Backend setup

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/Mac
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Download the patient dataset

The project uses a synthetic patient dataset from Kaggle:

- **Dataset:** https://www.kaggle.com/datasets/prasad22/healthcare-dataset
- Download `healthcare_dataset.csv`
- Place it in `backend/data/healthcare_dataset.csv`

### 4. Download Piper (local TTS)

- **Piper:** https://github.com/rhasspy/piper/releases
  - Download the binary for your OS
  - Extract to `backend/piper/`
- **Piper voice model:**
  - Download `en_US-lessac-medium.onnx` and `en_US-lessac-medium.onnx.json`
  - Place both in `backend/models/`

### 5. Set your Groq API key

Create `backend/.env`:

```
GROQ_API_KEY=gsk_your_actual_key_here
```

### 6. Unity setup

- Open Unity Hub
- Add the `unity/` folder as an existing project
- Open with Unity 6.3 LTS (or the version noted in `unity/ProjectSettings/ProjectVersion.txt`)
- Open scene: `Assets/Scenes/DoctorHandoverScene.unity`

**Missing packages:** if Unity flags missing packages, install via Package Manager:
- uLipSync (via Git URL: `https://github.com/hecomi/uLipSync.git#upm`)
- TextMeshPro (usually built-in)

## Running the Simulator

### 1. Start the backend

```bash
cd backend
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Wait for `Application startup complete` — the first launch takes ~30 seconds to load Whisper, build the FAISS index, and start the Piper daemon.

Verify by visiting http://127.0.0.1:8000/docs — you should see all API endpoints.

### 2. Press Play in Unity

Wait for the "Ready" status pill to appear.

### 3. Have a conversation

Sample flow:

- **"Dr. Raggy, brief me about patient P1101"** → she gives an ISBAR briefing
- **"Dr. Raggy, brief me about patient P1102"** → another briefing
- **"Dr. Raggy, end handover"** → quiz appears with questions about both patients
- Click through the multiple-choice questions
- **PDF report generated** at `backend/reports/handover_report_*.pdf`

## Features

### Voice interaction
- **Wake-word gating** — only requests addressed to "Dr. Raggy" are sent to the backend
- **Voice activity detection** — automatically starts and stops recording based on speech
- **Echo prevention** — filters out the doctor's own voice when it leaks through the mic

### ISBAR structuring
- Deterministic field extraction from patient records
- LLM humanization layer for natural-sounding delivery
- The LLM never sees raw records — only verified structured fields, reducing hallucination risk

### Interactive quiz
- 4 multiple-choice questions per briefing (age, admission type, background, recommendation)
- Programmatic distractor generation (no LLM cost per question)
- Per-patient tracking across multiple briefings
- Voice-triggered final quiz ("end handover", "quiz me", "that's all")

### Downloadable PDF report
- Overall performance summary
- Per-patient breakdown with Pass/Review verdicts
- Timestamp and session identifier

### Animated avatar
- Reallusion CC4 character with full face rig
- Real-time lip-sync from TTS audio (uLipSync + MFCC phoneme detection)
- Idle animation, hand gestures during speech
- Natural eye blinks and brow raises
- Subtle head tilt during listening

## How the Pipeline Works

1. **User speaks** — Unity captures audio via a VAD-gated microphone loop
2. **Audio sent to `/transcribe`** — Whisper converts speech to text
3. **Client-side wake-word check** — If "Dr. Raggy" isn't in the transcript, the utterance is dropped without a backend call (saves latency)
4. **Text sent to `/ask`** — the backend:
   - Detects the query type (patient briefing, follow-up, protocol question)
   - Resolves the patient ID (with fuzzy matching to handle STT mishearings like "P1101" → "B1101")
   - Retrieves the top-k matching records from the FAISS vector store
   - Extracts ISBAR fields via regex on structured record text
   - Humanizes the response through an LLM with a strict prompt (never sees raw records, only structured fields)
   - Generates a 4-question quiz from the same structured fields
5. **Text sent to `/tts`** — Piper synthesizes speech, streamed back as WAV audio
6. **Unity plays the audio** — while the DoctorBehaviorController activates the speaking state
   - uLipSync analyzes audio in real-time, detecting phonemes
   - Blendshapes on the character mesh animate the mouth
   - Animator plays a talking-with-hands clip
   - Brow raises fire occasionally during speech
7. **Quiz accumulates** — questions are pooled across briefings
8. **On "end handover"** — the pooled quiz appears; user answers each MCQ
9. **Results submitted to `/report`** — backend generates a PDF via ReportLab
10. **Report path displayed** — user opens the PDF from the local filesystem

## Key Design Decisions

**Safety via grounding.** The LLM never receives raw patient records. Structured ISBAR fields are extracted deterministically via regex; the LLM's only role is to convert them into natural spoken language. This reduces hallucination risk to near-zero — the model can rephrase but cannot invent facts.

**Local-first speech.** Both STT (Whisper) and TTS (Piper) run locally. No patient data leaves the machine except through the LLM humanization call. The LLM call only receives already-structured ISBAR fields, not raw records.

**Persistent Piper daemon.** A subprocess of Piper is kept alive between requests to avoid the ~1s cold-start of spawning `piper.exe` per synthesis. Falls back gracefully to one-shot Piper if the daemon fails.

**Wake-word gating on both sides.** The Unity client filters out utterances lacking "Dr. Raggy" before any backend call, saving a full network round-trip. The backend also filters as a safety net.

**Behavior state machine decoupled from voice logic.** All avatar visual state (lip-sync, animation, blinks, brow raises) is owned by `DoctorBehaviorController.cs`, which exposes a simple `SetState(Idle | Listening | Thinking | Speaking)` API. The voice orchestrator (`RagClient.cs`) doesn't know about blendshapes or bones.

**Programmatic quiz generation.** Quiz questions are built deterministically from patient data with curated distractor banks. No LLM call per question — fast, free, and reliable. Distractors are seeded by patient ID so the same patient always yields consistent distractors, while option order still shuffles.

## Configuration

Most settings are exposed via the Unity Inspector on the `RagManager` GameObject's RagClient component:

| Setting | Purpose | Default |
|---|---|---|
| API URLs | Backend endpoint URLs | `http://127.0.0.1:8000/*` |
| Silence Stop Seconds | How long silence must last to end recording | 0.8 |
| Max Recording Seconds | Cap on recording length | 7 |
| Post Playback Listen Delay | Cooldown after TTS before re-opening mic | 0.8 |
| TTS Cooldown Seconds | Additional mic gating after playback | 0.3 |
| Speech Threshold | Volume threshold for VAD | 0.015 |

Backend settings live in `backend/src/*.py` files — mostly self-documented.

## Troubleshooting

**Backend fails to start with "Piper daemon failed":**
- Check `backend/piper/piper.exe` exists
- Check `backend/models/en_US-lessac-medium.onnx` exists
- On Windows, ensure the Piper binary and DLLs are all present

**Unity says "no microphone found":**
- Ensure your OS grants Unity microphone permission
- The code prefers "Logitech" mics; edit `ragClient.cs` if you use a different brand

**Character in T-pose during Play:**
- Assign an Animator Controller to the character's Animator component
- Ensure the Controller has a valid Idle state with an animation clip

**Mouth doesn't move during speech:**
- The Doctor Behavior slot on RagClient must reference the character GameObject
- The character must have uLipSync + uLipSync Blend Shape components
- The uLipSync Profile must be populated with MFCC data (use `uLipSync-Profile-Sample-Female`)

**No quiz appears after handover:**
- Say "Dr Raggy end handover" (or "that's all", "quiz me")
- Check console for `[QUIZ] Accumulated N questions` — if it's 0, briefings didn't generate quizzes
- Ensure the Quiz Panel is wired in the RagClient Inspector

**"Missing Prefab" error on the character:**
- Delete the broken character from Hierarchy
- Drag a fresh copy of the character `.fbx` from Project pane
- Re-wire all Inspector references

## Future Work

- Multi-turn clinical reasoning (probing questions, differential diagnosis)
- Expanded question types (free-text answers, drag-and-drop diagnosis matching)
- Instructor dashboard for reviewing student performance
- Multi-language support (Piper supports many voices; Whisper is multilingual)
- Full VR headset deployment (currently runs in flat-screen VR mode)
- Real-time facial expression driven by conversation sentiment
- Adaptive difficulty based on user performance history

## Acknowledgments

- **[uLipSync](https://github.com/hecomi/uLipSync)** by hecomi — real-time lip-sync
- **[Piper](https://github.com/rhasspy/piper)** — neural TTS
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — Whisper inference
- **[Kaggle Healthcare Dataset](https://www.kaggle.com/datasets/prasad22/healthcare-dataset)** by Prasad — synthetic patient records
- **Groq** — LLM inference
- **Reallusion Character Creator 4** — avatar rig
- **Mixamo** — body animations

## License

MIT — see `LICENSE` file.

---

*Built as a proof-of-concept for AI-driven clinical training. Not a clinical tool; not for use with real patient data.*
