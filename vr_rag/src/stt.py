from faster_whisper import WhisperModel
import tempfile
import os
import re
import wave


class SpeechToText:
    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
        vad_filter: bool = False,
        min_clip_seconds: float = 0.8,
    ):
        print(f"[INFO] Loading Whisper model: {model_size}")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.min_clip_seconds = min_clip_seconds
        print(
            f"[INFO] Whisper model loaded successfully. "
            f"beam_size={beam_size}, vad_filter={vad_filter}, "
            f"min_clip_seconds={min_clip_seconds}"
        )

    def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "en",
        suffix: str = ".wav"
    ) -> str:
        if not suffix.startswith("."):
            suffix = f".{suffix}"

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_audio_file:
            temp_audio_file.write(audio_bytes)
            temp_audio_file.flush()
            audio_path = temp_audio_file.name

        try:
            # Reject clips too short to plausibly contain a question.
            # Catches TTS bleed-through and false-positive VAD triggers.
            duration = self._wav_duration_seconds(audio_path)
            if duration is not None and duration < self.min_clip_seconds:
                print(f"[STT] Clip too short ({duration:.2f}s < {self.min_clip_seconds}s), skipping.")
                return ""

            text = self._transcribe_file(audio_path, language, self.vad_filter)
            if not text and self.vad_filter:
                print("[WARN] VAD produced empty transcript; retrying without VAD.")
                text = self._transcribe_file(audio_path, language, False)
            return self._clean_hallucinated_repetition(text)
        finally:
            os.unlink(audio_path)

    @staticmethod
    def _wav_duration_seconds(audio_path: str):
        """Return WAV duration in seconds, or None if the file isn't readable as WAV."""
        try:
            with wave.open(audio_path, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate <= 0:
                    return None
                return frames / float(rate)
        except (wave.Error, EOFError, FileNotFoundError) as exc:
            print(f"[STT] Could not read WAV duration: {exc}")
            return None

    def _transcribe_file(self, audio_path: str, language: str, vad_filter: bool) -> str:
        segments, info = self.model.transcribe(
            audio_path,
            language=language,
            beam_size=self.beam_size,
            best_of=1,
            temperature=0.0,
            compression_ratio_threshold=2.4,   # was 1.8
            log_prob_threshold=-1.0,           # was -0.8
            no_speech_threshold=0.6,           # was 0.35
            repetition_penalty=1.2,
            no_repeat_ngram_size=3,
            hallucination_silence_threshold=1.0,
            vad_filter=vad_filter,
            vad_parameters={
                "threshold": 0.3,
                "min_speech_duration_ms": 150,
                "min_silence_duration_ms": 300,
                "speech_pad_ms": 400,
            },
            initial_prompt=(
                "The user may say: Hello Dr Raggy. Dr Raggy is the medical assistant. "
                "The user always says Dr. Raggy before each command. Examples: 'Dr. Raggy brief me about P1101', 'Dr. Raggy what is elective'."
                "Patient IDs include a letter prefix, usually P or D, followed by digits. "
                "Keep the full prefix and all digits when a patient ID is spoken. "
                "Medical patient ID, ward, ISBAR, doctor, situation, "
                "background, assessment, recommendation."
            ),
            hotwords=(
                "Hello Dr Raggy. Dr Raggy. ISBAR. patient ID. "
                "Emma Wilson."
            ),
            condition_on_previous_text=False,
        )

        # Materialize segments so we can log diagnostics even when result is empty
        segment_list = list(segments)
        text = " ".join(s.text for s in segment_list).strip()

        print(
            f"[STT] duration={info.duration:.2f}s "
            f"lang={info.language} lang_prob={info.language_probability:.2f} "
            f"segments={len(segment_list)} "
            f"text_chars={len(text)}"
        )

        return text

    def _clean_hallucinated_repetition(self, text: str) -> str:
        if not text:
            return ""

        tokens = re.findall(r"[a-z0-9']+", text.lower())
        if len(tokens) < 3:
            return text

        filler = {
            "ok", "okay", "yeah", "yes", "no", "um", "uh", "hmm",
            "thank", "thanks", "you"
        }
        if all(token in filler for token in tokens) and len(set(tokens)) <= 2:
            print(f"[WARN] Suppressed repeated filler transcript: {text!r}")
            return ""

        most_common = max(tokens.count(token) for token in set(tokens))
        if most_common >= 5 and most_common / len(tokens) >= 0.75:
            repeated_word = max(set(tokens), key=tokens.count)
            if repeated_word in filler:
                print(f"Suppressed repeated filler transcript: {text!r}")
                return ""

        return text
