using UnityEngine;
using TMPro;
using System;
using System.Collections;
using System.Text;
using UnityEngine.Networking;

public class RagClient : MonoBehaviour
{
    public event Action OnRequestStarted;
    public event Action<string> OnAnswerReceived;
    public event Action<string, string> OnAnswerReceivedWithContext;
    public event Action<string> OnTranscriptReceived;

    public string currentSceneRole = "general_assistant";
    public string currentSceneMode = "default";
    public TMP_InputField inputField;
    private string sessionId;
    public string LastAnswer { get; private set; }
    public string LastRetrievedPatient { get; private set; }

    [Header("Backend Settings")]
    public string apiUrl = "http://127.0.0.1:8000/ask";
    public string transcribeUrl = "http://127.0.0.1:8000/transcribe";
    public string ttsUrl = "http://127.0.0.1:8000/tts";

    [Header("UI")]
    public InfoCanvasDisplay infoCanvas;

    [Header("Audio Output")]
    public AudioSource audioSource;

    [Header("Avatar")]
    [Tooltip("Behavior controller on the doctor avatar. Owns all visual state transitions.")]
    public DoctorBehaviorController doctorBehavior;

    [Header("Quiz")]
    [Tooltip("Quiz panel that appears after each ISBAR briefing. Optional — leave empty to disable quizzes.")]
    public QuizPanel quizPanel;

    [Header("Recording Settings")]
    public int recordingLength = 5;
    public int sampleRate = 16000;

    private AudioClip recordedClip;
    private bool isRecording = false;
    private string microphoneDevice;
    private float recordStartTime;
    private bool isBusy = false;     // true only during API call
    private bool isPlaying = false;  // true during TTS playback
    private int consecutiveSpeechFrames = 0;

    [Header("Auto Voice Detection")]
    public bool autoVoiceDetection = true;
    public float silenceThreshold = 0.012f;
    public float silenceStopSeconds = 1.5f;
    public float maxRecordingSeconds = 10f;
    public float checkInterval = 0.1f;
    public float postPlaybackListenDelay = 2.5f;
    public float echoIgnoreSeconds = 12f;
    public float echoSimilarityThreshold = 0.35f;

    private float nextListenAllowedAt = 0f;
    private string lastAssistantAnswer = "";
    private float lastAssistantAnswerAt = -999f;

    [Header("Mic Gating")]
    [SerializeField] private float ttsCooldownSeconds = 0.6f;
    private bool isMicGated = false;

    [Header("VAD")]
    [SerializeField] private float speechThreshold = 0.015f;
    [SerializeField] private int speechStartFramesRequired = 6;

    [Serializable]
    private class AskRequest
    {
        public string query;
        public string session_id;
        public int top_k;
        public string scene_role;
        public string scene_mode;
    }

    [Serializable]
    public class QuizQuestion
    {
        public string id;
        public string field;
        public string question;
        public string[] options;
        public int correct_index;
    }

    [Serializable]
    private class AskResponse
    {
        public string answer;
        public string retrieved_patient;
        public bool ignored;
        public QuizQuestion[] quiz;
    }

    [Serializable]
    private class TranscribeResponse
    {
        public string text;
    }

    [Serializable]
    private class TTSRequest
    {
        public string text;
        public string session_id;
    }

    private void Start()
    {
        sessionId = Guid.NewGuid().ToString();

        if (audioSource == null)
            audioSource = GetComponent<AudioSource>();
        if (audioSource == null)
            audioSource = gameObject.AddComponent<AudioSource>();

        SetupInfoCanvas();

        microphoneDevice = null;
        foreach (var device in Microphone.devices)
        {
            if (device.Contains("Logitech"))
            {
                microphoneDevice = device;
                break;
            }
        }

        if (string.IsNullOrEmpty(microphoneDevice) && Microphone.devices.Length > 0)
            microphoneDevice = Microphone.devices[0];

        if (!string.IsNullOrEmpty(microphoneDevice))
            Debug.Log("Microphone ready: " + microphoneDevice);
        else
            Debug.LogError("No microphone found.");

        if (autoVoiceDetection && !string.IsNullOrEmpty(microphoneDevice))
            StartCoroutine(AutoRecord());

        // Initial avatar state. The behavior controller handles all mouth/eye/animator setup.
        if (doctorBehavior != null)
            doctorBehavior.SetState(DoctorBehaviorController.BehaviorState.Idle);

        NotifyCanvasStatus("ready");
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.Escape))
        {
            isBusy = false;
            isRecording = false;
            if (audioSource != null)
                audioSource.Stop();
            SetAgentSpeaking(false);
            NotifyCanvasStatus("ready");
            Debug.Log("System reset.");
        }

        if (Input.GetKeyDown(KeyCode.Space))
        {
            if (inputField != null && !string.IsNullOrWhiteSpace(inputField.text))
            {
                string typedQuery = inputField.text.Trim();
                inputField.text = "";

                if (isPlaying && audioSource != null)
                {
                    audioSource.Stop();
                    SetAgentSpeaking(false);
                }

                Ask(typedQuery);
            }
        }

        if (isPlaying && audioSource != null && !audioSource.isPlaying)
        {
            SetAgentSpeaking(false);
            Debug.Log("Ready for next question.");
        }
    }

    private void SetupInfoCanvas()
    {
        if (infoCanvas == null)
            infoCanvas = FindAnyObjectByType<InfoCanvasDisplay>();

        if (infoCanvas != null)
            infoCanvas.ragClient = this;
    }

    // ---------------------------------------------------------------------
    // Avatar state — all visual behavior delegated to DoctorBehaviorController
    // ---------------------------------------------------------------------
    private void SetAgentSpeaking(bool speaking)
    {
        isPlaying = speaking;

        if (doctorBehavior != null)
            doctorBehavior.SetState(speaking
                ? DoctorBehaviorController.BehaviorState.Speaking
                : DoctorBehaviorController.BehaviorState.Idle);

        NotifyCanvasStatus(speaking ? "speaking" : "ready");
    }

    private void NotifyCanvasStatus(string state)
    {
        if (infoCanvas == null)
            infoCanvas = FindAnyObjectByType<InfoCanvasDisplay>();

        if (infoCanvas != null)
            infoCanvas.SetStatus(state);

        // Mirror the conversation state onto the avatar.
        // "speaking" is handled by SetAgentSpeaking to ensure lip sync, but we also update the avatar for "listening", "thinking", and "ready" states here.
        if (doctorBehavior != null)
        {
            switch (state)
            {
                case "listening":
                    doctorBehavior.SetState(DoctorBehaviorController.BehaviorState.Listening);
                    break;
                case "thinking":
                    doctorBehavior.SetState(DoctorBehaviorController.BehaviorState.Thinking);
                    break;
                case "ready":
                    doctorBehavior.SetState(DoctorBehaviorController.BehaviorState.Idle);
                    break;
            }
        }
    }

    // ---------------------------------------------------------------------
    // Public entry point — text query (typed or programmatic)
    // ---------------------------------------------------------------------
    public void Ask(string query)
    {
        if (isBusy)
        {
            Debug.LogWarning("Still processing. Please wait.");
            return;
        }

        if (string.IsNullOrWhiteSpace(query))
        {
            Debug.LogWarning("Please type or speak a question.");
            return;
        }

        isBusy = true;
        OnRequestStarted?.Invoke();
        NotifyCanvasStatus("thinking");
        StartCoroutine(SendQueryCoroutine(query));
    }

    public void Speak(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return;
        if (audioSource != null && audioSource.isPlaying)
            audioSource.Stop();
        StartCoroutine(SendTTSRequest(text));
    }

    // ---------------------------------------------------------------------
    // Auto recording loop with VAD
    // ---------------------------------------------------------------------
    private IEnumerator AutoRecord()
    {  // AI help was taken to compile errors in this method, so it may look a bit rough.
    
        while (true)
        {
            if (!isBusy && !isPlaying && !isRecording && !string.IsNullOrEmpty(microphoneDevice) && Time.time >= nextListenAllowedAt)
            {
                recordedClip = Microphone.Start(
                    microphoneDevice,
                    false,
                    Mathf.CeilToInt(maxRecordingSeconds),
                    sampleRate
                );
                isRecording = true;
                recordStartTime = Time.time;

                yield return new WaitForSeconds(0.3f);

                while (isMicGated)
                    yield return null;

                Debug.Log(" Mic is ready please speak now......");
                NotifyCanvasStatus("listening");
                yield return new WaitForSeconds(0.3f);

                float lastSpeechTime = Time.time;
                bool speechStarted = false;
                float firstSpeechTime = 0f;
                int lastValidPosition = 0;
                int lastPosition = 0;

                while (Time.time - recordStartTime < maxRecordingSeconds)
                {
                    int position = Microphone.GetPosition(microphoneDevice);
                    if (position > 0)
                        lastValidPosition = position;
                    int newSamples = position - lastPosition;

                    if (newSamples > 0 && recordedClip != null)
                    {
                        float[] samples = new float[newSamples * recordedClip.channels];
                        recordedClip.GetData(samples, lastPosition);
                        lastPosition = position;
                        float maxAbs = 0f;
                        foreach (float s in samples)
                            maxAbs = Mathf.Max(maxAbs, Mathf.Abs(s));

                        if (maxAbs >= speechThreshold)
                        {
                            if (!speechStarted)
                            {
                                consecutiveSpeechFrames++;
                                if (consecutiveSpeechFrames >= speechStartFramesRequired)
                                {
                                    speechStarted = true;
                                    firstSpeechTime = Time.time;
                                    lastSpeechTime = Time.time;
                                    consecutiveSpeechFrames = 0;
                                    Debug.Log("[AutoVoice] Speech started");
                                }
                            }
                            else
                            {
                                lastSpeechTime = Time.time;
                            }
                        }
                        else
                        {
                            if (!speechStarted)
                                consecutiveSpeechFrames = 0;
                            else
                                Debug.Log("[AutoVoice] Silence Detected");
                        }

                        if (speechStarted && Time.time - lastSpeechTime >= silenceStopSeconds)
                        {
                            if (Time.time - firstSpeechTime < 1.0f)
                            {
                                Debug.Log("[AutoVoice] Too short, ignoring burst.");
                                speechStarted = false;
                                firstSpeechTime = 0f;
                                lastSpeechTime = Time.time;
                                continue;
                            }
                            Debug.Log("[AutoVoice] Speech ended - silence detected");
                            break;
                        }
                    }

                    yield return new WaitForSeconds(checkInterval);
                }

                int finalPosition = Microphone.GetPosition(microphoneDevice);
                if (finalPosition <= 0)
                    finalPosition = lastValidPosition;

                Microphone.End(microphoneDevice);
                isRecording = false;

                if (!speechStarted)
                {
                    Debug.Log("[AutoVoice] No speech detected.");
                    NotifyCanvasStatus("ready");
                    yield return new WaitForSeconds(0.5f);
                    continue;
                }

                if (recordedClip != null)
                    finalPosition = Mathf.Clamp(finalPosition, 0, recordedClip.samples);

                if (finalPosition <= sampleRate * 0.8f || recordedClip == null)
                {
                    Debug.LogWarning($"[AutoVoice] Audio too short or empty. finalPosition={finalPosition}");
                    yield return new WaitForSeconds(0.5f);
                    continue;
                }

                float[] finalSamples = new float[finalPosition];
                recordedClip.GetData(finalSamples, 0);

                AudioClip trimmedClip = AudioClip.Create(
                    "auto_recording",
                    finalPosition,
                    1,
                    recordedClip.frequency,
                    false
                );
                trimmedClip.SetData(finalSamples, 0);

                Debug.Log($"[AutoVoice] Sending clip: {trimmedClip.length}s to STT...");

                isBusy = true;
                OnRequestStarted?.Invoke();
                NotifyCanvasStatus("thinking");
                StartCoroutine(SendAudioForTranscription(trimmedClip));

                yield return new WaitUntil(() => !isBusy && !isPlaying);
                yield return new WaitForSeconds(0.5f);
            }
            else
            {
                yield return new WaitForSeconds(0.3f);
            }
        }
    }

    // ---------------------------------------------------------------------
    // STT
    // ---------------------------------------------------------------------
    private IEnumerator SendAudioForTranscription(AudioClip clip)
    {
        Debug.Log("sending audio for transcription");
        if (clip == null)
        {
            Debug.LogError("clip is null");
            isBusy = false;
            yield break;
        }

        byte[] wavData = WavUtility.FromAudioClip(clip, out string fileName);
        if (wavData == null || wavData.Length == 0)
        {
            Debug.LogError("Audio conversion failed.");
            isBusy = false;
            yield break;
        }

        WWWForm form = new WWWForm();
        form.AddBinaryData("file", wavData, fileName, "audio/wav");

        using (UnityWebRequest req = UnityWebRequest.Post(transcribeUrl, form))
        {
            req.timeout = 120;
            yield return req.SendWebRequest();

            Debug.Log($"[STT] Response result: {req.result}");
            Debug.Log($"[STT] Response code: {req.responseCode}");
            Debug.Log($"[STT] Response body: {req.downloadHandler?.text}");

            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Could not reach server.");
                isBusy = false;
                yield break;
            }

            TranscribeResponse response;
            try
            {
                response = JsonUtility.FromJson<TranscribeResponse>(req.downloadHandler.text);
                Debug.Log($"[STT] Transcribed: '{response?.text}'");
            }
            catch
            {
                Debug.LogError("Server response error.");
                isBusy = false;
                yield break;
            }

            if (response == null || string.IsNullOrWhiteSpace(response.text))
            {
                Debug.LogWarning("[STT] Empty transcript.");
                isBusy = false;
                nextListenAllowedAt = Time.time + 0.8f;
                yield break;
            }

            string trimmed = response.text.Trim();
            if (trimmed.Length < 4 && !IsAllowedShortUtterance(trimmed))
            {
                isBusy = false;
                nextListenAllowedAt = Time.time + 0.8f;
                yield break;
            }

            string[] words = trimmed.Split(' ');
            if (words.Length < 2 && trimmed.Length < 4 && !IsAllowedShortUtterance(trimmed))
            {
                Debug.Log($"[STT] Noise ignored: '{trimmed}'");
                isBusy = false;
                yield break;
            }
            Debug.Log("You said: " + response.text);

            // Check for the end-of-session command BEFORE other filters.
            // Phrases like "Dr Raggy end handover" / "that's all" / "show my quiz"
            // trigger the accumulated quiz instead of going to the LLM.
            if (IsEndHandoverCommand(response.text))
            {
                Debug.Log("[QUIZ] End-handover command detected. Launching final quiz.");
                isBusy = false;
                if (quizPanel != null && quizPanel.PooledQuestionCount > 0)
                {
                    quizPanel.StartPooledQuiz();
                }
                else
                {
                    Debug.LogWarning("[QUIZ] No questions pooled — brief at least one patient first.");
                    NotifyCanvasStatus("ready");
                }
                yield break;
            }

            if (LooksLikeAssistantEcho(response.text))
            {
                Debug.Log("[STT] Ignored likely assistant echo: " + response.text);
                isBusy = false;
                nextListenAllowedAt = Time.time + 1.0f;
                yield break;
            }

            if (!IsMeaningfulQuestion(response.text))
            {
                Debug.Log("[STT] Filtered as non-meaningful: " + response.text);
                isBusy = false;
                yield break;
            }

            // Wake-word gate (client-side). The backend also filters this, but
            // checking here saves a full /ask + /tts round-trip when the user
            // didn't address the doctor by name. Major UX speedup.
            if (!HasWakeWord(response.text))
            {
                Debug.Log("[STT] No wake word ('Dr. Raggy') — skipping API call: " + response.text);
                isBusy = false;
                NotifyCanvasStatus("ready");
                yield break;
            }

            OnTranscriptReceived?.Invoke(response.text);
            Debug.Log("[STT] Passing to query coroutine...");
            StartCoroutine(SendQueryCoroutine(response.text));
        }
    }

    /// <summary>
    /// Returns true if the transcript contains "Raggy" (or common Whisper
    /// mishearings of it) anywhere in the text. Substring matching is more
    /// forgiving than prefix matching: handles "Hello. Hello Dr Raggy",
    /// stutters, repeats, and any phrasing where the wake word appears.
    /// </summary>
    /// <summary>
    /// Detects the end-of-session command that triggers the accumulated quiz.
    /// Matches natural phrases the user might say to wrap up the handover.
    /// </summary>
    private bool IsEndHandoverCommand(string transcript)
    {
        if (string.IsNullOrWhiteSpace(transcript))
            return false;

        string q = transcript.ToLowerInvariant();

        // Any of these substrings signals "I'm done, quiz me".
        string[] endPhrases = {
            "end handover",
            "end the handover",
            "finish handover",
            "finish the handover",
            "end hand over",      // STT sometimes splits "handover"
            "complete handover",
            "that's all",
            "thats all",
            "that is all",
            "i'm done",
            "im done",
            "i am done",
            "we're done",
            "were done",
            "show my quiz",
            "show the quiz",
            "start the quiz",
            "start quiz",
            "quiz me",
            "test me",
            "show my results",
            "show results",
        };

        foreach (string phrase in endPhrases)
        {
            if (q.Contains(phrase))
                return true;
        }

        return false;
    }

    private bool HasWakeWord(string transcript)
    {
        if (string.IsNullOrWhiteSpace(transcript))
            return false;

        string q = transcript.ToLowerInvariant();

        // Match the name itself plus common Whisper mishearings.
        // We only need ONE of these to appear anywhere in the transcript.
        string[] wakeVariants = {
            "raggy",     // canonical
            "ragi",      // common mishearing
            "reggie",    // phonetic
            "reggy",     // phonetic
            "rage e",    // Whisper sometimes splits "Raggy" into two words
            "ragee",
            "raghi",
            "rogi",      // rare but seen in noisy audio
        };

        foreach (string variant in wakeVariants)
        {
            if (q.Contains(variant))
                return true;
        }

        return false;
    }

    // ---------------------------------------------------------------------
    // Filtering helpers
    // ---------------------------------------------------------------------
    private bool IsAllowedShortUtterance(string text)
    {
        string q = text.ToLower().Trim().Trim('.', '?', '!', ',');
        return q == "hi" || q == "hey";
    }

    private bool LooksLikeAssistantEcho(string transcript)
    {
        if (string.IsNullOrWhiteSpace(lastAssistantAnswer))
            return false;

        if (Time.time - lastAssistantAnswerAt > echoIgnoreSeconds)
            return false;

        string normalizedTranscript = NormalizeForSimilarity(transcript);
        string normalizedAnswer = NormalizeForSimilarity(lastAssistantAnswer);
        if (normalizedTranscript.Length < 8 || normalizedAnswer.Length < 8)
            return false;

        if (normalizedAnswer.Contains(normalizedTranscript))
            return true;

        string[] words = normalizedTranscript.Split(' ');
        int meaningful = 0;
        int overlap = 0;
        foreach (string word in words)
        {
            if (word.Length < 3)
                continue;
            meaningful++;
            if (normalizedAnswer.Contains(word))
                overlap++;
        }

        return meaningful > 0 && (float)overlap / meaningful >= echoSimilarityThreshold;
    }

    private string NormalizeForSimilarity(string text)
    {
        text = text.ToLowerInvariant();
        StringBuilder builder = new StringBuilder(text.Length);
        foreach (char c in text)
        {
            if (char.IsLetterOrDigit(c))
                builder.Append(c);
            else
                builder.Append(' ');
        }
        return string.Join(" ", builder.ToString().Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries));
    }

    private bool IsMeaningfulQuestion(string text)
    {
        Debug.Log("analyzing the question........");
        if (string.IsNullOrWhiteSpace(text))
            return false;

        string q = text.ToLower().Trim().Trim('.', '?', '!', ',');

        if (q.Length < 3)
            return false;

        if (IsRepeatedFillerNoise(q))
            return false;

        string[] ignored = { "ok", "okay", "okay now", "now", "um", "uh", "hmm", "one" };

        foreach (string phrase in ignored)
            if (q == phrase)
                return false;

        return true;
    }

    private bool IsRepeatedFillerNoise(string text)
    {
        string normalized = NormalizeForSimilarity(text);
        if (string.IsNullOrWhiteSpace(normalized))
            return true;

        string[] words = normalized.Split(' ');
        if (words.Length < 3)
            return false;

        string[] fillerWords = { "ok", "okay", "yeah", "yes", "no", "um", "uh", "hmm", "thank", "thanks", "you" };

        int fillerCount = 0;
        int mostRepeated = 0;

        foreach (string word in words)
        {
            bool isFiller = false;
            foreach (string filler in fillerWords)
            {
                if (word == filler)
                {
                    isFiller = true;
                    break;
                }
            }

            if (isFiller)
                fillerCount++;

            int repeated = 0;
            foreach (string other in words)
            {
                if (word == other)
                    repeated++;
            }
            mostRepeated = Mathf.Max(mostRepeated, repeated);
        }

        if (fillerCount == words.Length)
            return true;

        return mostRepeated >= 5 && (float)mostRepeated / words.Length >= 0.75f;
    }

    // ---------------------------------------------------------------------
    // /ask
    // ---------------------------------------------------------------------
    private IEnumerator SendQueryCoroutine(string query)
    {
        Debug.Log("[ASK] Sending query: " + query);
        NotifyCanvasStatus("thinking");

        string payload = JsonUtility.ToJson(new AskRequest
        {
            query = query,
            session_id = sessionId,
            top_k = 3,
            scene_role = currentSceneRole,
            scene_mode = currentSceneMode
        });

        using (UnityWebRequest req = new UnityWebRequest(apiUrl, "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(payload));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 30;

            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Server unreachable.");
                isBusy = false;
                NotifyCanvasStatus("ready");
                yield break;
            }

            AskResponse response;
            try
            {
                response = JsonUtility.FromJson<AskResponse>(req.downloadHandler.text);
            }
            catch
            {
                Debug.LogError("Response error.");
                isBusy = false;
                NotifyCanvasStatus("ready");
                yield break;
            }

            if (response == null || string.IsNullOrWhiteSpace(response.answer))
            {
                Debug.LogWarning("No answer received.");
                isBusy = false;
                NotifyCanvasStatus("ready");
                yield break;
            }

            Debug.Log("Answer received.");

            LastAnswer = response.answer;
            LastRetrievedPatient = response.retrieved_patient ?? "";
            lastAssistantAnswer = response.answer;
            lastAssistantAnswerAt = Time.time;

            if (response.ignored)
            {
                // Wake word missing — silently drop the utterance, re-arm mic
                Debug.Log("[ASK] Utterance ignored (no wake word). Re-arming mic.");
            }
            else
            {
                OnAnswerReceived?.Invoke(response.answer);
                OnAnswerReceivedWithContext?.Invoke(response.answer, LastRetrievedPatient);
                yield return StartCoroutine(SendTTSRequest(response.answer));

                // Accumulate quiz questions from this briefing into the session pool.
                // The full quiz is shown later when the user says "end handover".
                // Quizzes are only generated for ISBAR briefings (not follow-ups).
                if (quizPanel != null && response.quiz != null && response.quiz.Length > 0)
                {
                    quizPanel.AddQuestions(response.quiz, response.retrieved_patient);
                    Debug.Log($"[QUIZ] Accumulated {response.quiz.Length} questions " +
                              $"for {response.retrieved_patient}. " +
                              $"Pool now has {quizPanel.PooledQuestionCount} questions.");
                }
            }

            isBusy = false;
            NotifyCanvasStatus("ready");
        }
    }

    // ---------------------------------------------------------------------
    // /tts
    // ---------------------------------------------------------------------
    private IEnumerator SendTTSRequest(string text)
    {
        string payload = JsonUtility.ToJson(new TTSRequest
        {
            text = text,
            session_id = sessionId
        });

        using (UnityWebRequest req = new UnityWebRequest(ttsUrl, "POST"))
        {
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(payload));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 60;

            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError("Text-to-speech failed.");
                yield break;
            }

            byte[] audioBytes = req.downloadHandler.data;
            if (audioBytes == null || audioBytes.Length == 0)
            {
                Debug.LogError("No audio returned.");
                yield break;
            }

            AudioType audioType = DetectAudioType(req, audioBytes, out string extension);
            string tempPath = System.IO.Path.Combine(
                Application.persistentDataPath, "tts_response" + extension);
            System.IO.File.WriteAllBytes(tempPath, audioBytes);

            string fileUrl = "file://" + tempPath;

            using (UnityWebRequest audioReq = new UnityWebRequest(
                fileUrl, UnityWebRequest.kHttpVerbGET))
            {
                //audioReq.downloadHandler = new DownloadHandlerAudioClip(fileUrl, audioType);
                //yield return audioReq.SendWebRequest();
                DownloadHandlerAudioClip dh = new DownloadHandlerAudioClip(fileUrl, audioType);
                dh.streamAudio = false;  // Wait for the full file before allowing playback
                audioReq.downloadHandler = dh;
                yield return audioReq.SendWebRequest();

                if (audioReq.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogError("Audio playback error.");
                    yield break;
                }

                AudioClip clip = DownloadHandlerAudioClip.GetContent(audioReq);
                if (clip == null || audioSource == null)
                {
                    Debug.LogError("Audio source error.");
                    yield break;
                }

                audioSource.Stop();
                audioSource.clip = clip;

                SetAgentSpeaking(true);

                audioSource.Play();
                Debug.Log("Playing response...");
                //yield return new WaitWhile(() => audioSource != null && audioSource.isPlaying);
                // Wait for the clip to actually play through. Some Unity audio decode
                // quirks can make isPlaying flip to false before the clip is done, so
                // we use clip.length as a hard floor.
                float clipLength = clip.length;
                float playbackStart = Time.time;
                yield return new WaitUntil(() =>
                audioSource == null ||
                (!audioSource.isPlaying && Time.time - playbackStart > clipLength * 0.95f));

                SetAgentSpeaking(false);
                nextListenAllowedAt = Time.time + postPlaybackListenDelay;
                Debug.Log("TTS finished.");

                isMicGated = true;
                yield return new WaitForSeconds(ttsCooldownSeconds);
                isMicGated = false;
            }
        }
    }

    private AudioType DetectAudioType(UnityWebRequest request, byte[] bytes, out string extension)
    {
        string contentType = request.GetResponseHeader("Content-Type") ?? "";
        contentType = contentType.ToLowerInvariant();

        if (contentType.Contains("wav") || LooksLikeWav(bytes))
        {
            extension = ".wav";
            return AudioType.WAV;
        }

        extension = ".mp3";
        return AudioType.MPEG;
    }

    private bool LooksLikeWav(byte[] bytes)
    {
        return bytes.Length > 12
            && bytes[0] == (byte)'R'
            && bytes[1] == (byte)'I'
            && bytes[2] == (byte)'F'
            && bytes[3] == (byte)'F'
            && bytes[8] == (byte)'W'
            && bytes[9] == (byte)'A'
            && bytes[10] == (byte)'V'
            && bytes[11] == (byte)'E';
    }
}