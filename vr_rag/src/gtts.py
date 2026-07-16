import os
import subprocess
import threading
import time
import json
import wave
from pathlib import Path


class textToSpeech:
    """
    Text-to-speech with a persistent Piper subprocess for low-latency synthesis.
    Piper is launched once at construction time with --json-input. Each call to
    synthesize() pipes a single JSON line to Piper's stdin and reads the resulting
    raw audio from stdout, eliminating the ~1s subprocess + model-load cold-start
    that occurs when spawning piper.exe per request.
    Falls back to gTTS when Piper isn't available (model file missing, etc).
    """

    def __init__(self, language: str = "en", use_piper: bool = True):
        self.language = language
        self.use_piper = use_piper
        self.project_root = Path(__file__).resolve().parents[1]
        self.piper_exe = self.project_root / "piper" / "piper.exe"
        self.piper_model = self.project_root / "models" / "en_US-lessac-medium.onnx"

        self._piper_proc = None
        self._piper_lock = threading.Lock()
        self._piper_sample_rate = None

        self._win_reader_thread = None
        self._win_reader_queue = None

        self.use_persistent_piper = self._piper_available()
        self.file_extension = ".wav" if self.use_persistent_piper else ".mp3"
        self.media_type = "audio/wav" if self.file_extension == ".wav" else "audio/mpeg"

        if self.use_persistent_piper:
            self._start_piper_daemon()

        engine = "piper-persistent" if self.use_persistent_piper else "gtts"
        print(f"[INFO] TextToSpeech initialized with language={language}, engine={engine}")

    def _piper_available(self) -> bool:
        return self.use_piper and self.piper_exe.exists() and self.piper_model.exists()

    def _read_piper_sample_rate(self) -> int:
        config_path = self.piper_model.with_suffix(self.piper_model.suffix + ".json")
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            return int(config.get("audio", {}).get("sample_rate", 22050))
        except Exception as exc:
            print(f"[WARN] Could not read Piper sample rate, defaulting to 22050: {exc}")
            return 22050

    def _start_piper_daemon(self):
        self._piper_sample_rate = self._read_piper_sample_rate()
        command = [
            str(self.piper_exe),
            "--model", str(self.piper_model),
            "--json-input",
            "--output-raw",
        ]
        try:
            self._piper_proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.project_root / "piper"),
                bufsize=0,
            )
            print(f"[INFO] Piper daemon started, pid={self._piper_proc.pid}, "
                  f"sample_rate={self._piper_sample_rate}")
            self._start_reader_thread()
            time.sleep(0.5)
        except Exception as exc:
            print(f"[ERROR] Failed to start Piper daemon: {exc}. Falling back to per-call mode.")
            self._piper_proc = None
            self.use_persistent_piper = False

    def _start_reader_thread(self):
        import queue
        self._win_reader_queue = queue.Queue()
        self._win_reader_thread = threading.Thread(
            target=self._reader_loop,
            daemon=True,
        )
        self._win_reader_thread.start()

    def _reader_loop(self):
        while self._piper_daemon_alive():
            try:
                chunk = self._piper_proc.stdout.read(4096)
                if not chunk:
                    break
                self._win_reader_queue.put(chunk)
            except Exception:
                break

    def _piper_daemon_alive(self) -> bool:
        return (
            self._piper_proc is not None
            and self._piper_proc.poll() is None
        )

    def _drain_stale_bytes(self):
        if self._win_reader_queue is None:
            return
        drained = 0
        while True:
            try:
                stale = self._win_reader_queue.get_nowait()
                drained += len(stale)
            except Exception:
                break
        if drained:
            print(f"[WARN] Drained {drained} stale bytes from Piper pipe before new request")

    def synthesize(self, text: str, output_file: str = "response.wav"):
        if not text or not text.strip():
            raise ValueError("Input text is empty")
        if os.path.exists(output_file):
            os.remove(output_file)

        t0 = time.time()
        if self.use_persistent_piper and self._piper_daemon_alive():
            try:
                self._synthesize_with_persistent_piper(text, output_file)
                engine = "piper-persistent"
            except Exception as exc:
                #print(f"[WARN] Persistent Piper failed ({exc}), falling back to one-shot")
                #self._synthesize_with_piper_oneshot(text, output_file)
                #engine = "piper-oneshot"
                print(f"[WARN] Persistent Piper failed ({exc}), falling back to one-shot")
                self._synthesize_with_piper_oneshot(text, output_file)
                engine = "piper-oneshot"
                # Try to recover the daemon for next time
                try:
                    self.shutdown()
                    self._start_piper_daemon()
                    print("[INFO] Piper daemon restarted after failure")
                except Exception as restart_exc:
                    print(f"[WARN] Could not restart Piper daemon: {restart_exc}")
                    self.use_persistent_piper = False
                    
        elif self._piper_available():
            self._synthesize_with_piper_oneshot(text, output_file)
            engine = "piper-oneshot"
        else:
            self._synthesize_with_gtts(text, output_file)
            engine = "gtts"
        t1 = time.time()

        if not os.path.exists(output_file):
            raise IOError(f"Failed to create audio file: {output_file}")
        size = os.path.getsize(output_file)
        expected_seconds = (
            size / (self._piper_sample_rate * 2) if self._piper_sample_rate else 0
        )
        print(f"[INFO] TTS engine={engine} chars={len(text)} "
              f"synth_time={t1 - t0:.2f}s size={size} bytes "
              f"audio={expected_seconds:.1f}s")
        if size == 0:
            os.remove(output_file)
            raise RuntimeError(f"Generated audio file is empty: {output_file}")

    def _synthesize_with_persistent_piper(self, text: str, output_file: str):
        with self._piper_lock:
            self._drain_stale_bytes()

            payload = json.dumps({"text": text.strip()}) + "\n"
            try:
                self._piper_proc.stdin.write(payload.encode("utf-8"))
                self._piper_proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise RuntimeError(f"Piper stdin write failed: {exc}")

            audio_bytes = self._read_piper_response(text_length=len(text.strip()))

            if not audio_bytes:
                raise RuntimeError("Piper produced no audio")

            self._write_wav(output_file, audio_bytes, self._piper_sample_rate)

    def _read_piper_response(self, text_length: int) -> bytes:
        """Read from Piper's queued stdout until the response is complete.

        Two timeouts:
        - first_byte_timeout: how long we wait for the FIRST chunk of audio.
          Windows pipe buffering can delay this significantly, especially on
          the 2nd+ request after the daemon has been idle. Set generously
          (12s) to avoid spurious fallback to one-shot mode.
        - idle_threshold: once audio has started, how long we tolerate silence
          before assuming synthesis is complete.
        """
        import queue

        first_byte_timeout = 12.0   # was 5.0 — bumped for Windows pipe buffering
        idle_threshold = 0.7

        # Piper synthesizes ~150-200 chars/sec of natural speech.
        min_wait = 0.2
        max_wait = max(8.0, text_length / 25.0 + 3.0)

        buf = bytearray()
        start_time = time.time()
        waiting_for_first_byte = True

        while True:
            elapsed = time.time() - start_time
            timeout = first_byte_timeout if waiting_for_first_byte else idle_threshold

            try:
                chunk = self._win_reader_queue.get(timeout=timeout)
                buf.extend(chunk)
                waiting_for_first_byte = False
            except queue.Empty:
                if buf and elapsed >= min_wait:
                    return bytes(buf)
                if elapsed >= max_wait:
                    if buf:
                        return bytes(buf)
                    raise TimeoutError(
                        f"Piper produced no audio within {max_wait:.1f}s"
                    )

    @staticmethod
    def _write_wav(path: str, pcm_bytes: bytes, sample_rate: int):
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)

    def _synthesize_with_piper_oneshot(self, text: str, output_file: str):
        command = [
            str(self.piper_exe),
            "--model", str(self.piper_model),
            "--output_file", output_file,
        ]
        result = subprocess.run(
            command,
            input=text.strip(),
            text=True,
            capture_output=True,
            cwd=str(self.project_root / "piper"),
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Piper TTS failed: " + (result.stderr.strip() or result.stdout.strip())
            )

    def _synthesize_with_gtts(self, text: str, output_file: str):
        from gtts import gTTS
        tts = gTTS(text=text.strip(), lang=self.language, slow=False)
        tts.save(output_file)

    def shutdown(self):
        if self._piper_proc is not None:
            try:
                self._piper_proc.stdin.close()
                self._piper_proc.terminate()
                self._piper_proc.wait(timeout=2)
            except Exception:
                try:
                    self._piper_proc.kill()
                except Exception:
                    pass
            self._piper_proc = None
            print("[INFO] Piper daemon stopped")