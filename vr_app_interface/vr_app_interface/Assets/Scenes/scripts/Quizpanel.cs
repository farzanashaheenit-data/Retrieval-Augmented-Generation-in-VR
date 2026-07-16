using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

/// <summary>
/// Renders a multiple-choice recall quiz after each ISBAR briefing.
///
/// Lifecycle per quiz:
///   1. StartQuiz(questions) — called by RagClient after TTS finishes
///   2. Panel fades in, shows question 1 of N
///   3. User clicks one of four option buttons
///   4. Button turns green (correct) or red (wrong); others fade
///   5. After 1.5s, advance to next question
///   6. After last question, summary line appears ("3 / 4 correct"),
///      panel hides itself after 3s
///
/// Session-level totals (across multiple briefings) are tracked in
/// `totalCorrect` / `totalAnswered` for an end-of-session report.
///
/// Inspector wiring (see attached prefab guide):
///   - questionText: TMP_Text for the question
///   - optionButtons: 4 Buttons (Option 0..3)
///   - optionLabels:  4 TMP_Text on each button
///   - progressText:  TMP_Text like "Question 2 of 4"
///   - feedbackText:  TMP_Text for end-of-quiz score
///   - rootPanel:     the GameObject we activate/deactivate
///   - canvasGroup:   for fade in/out (optional)
/// </summary>
public class QuizPanel : MonoBehaviour
{
    [Header("UI References")]
    [Tooltip("The root panel GameObject to show/hide. Usually this same GameObject.")]
    public GameObject rootPanel;

    [Tooltip("Question text, e.g. 'How old is the patient?'")]
    public TMP_Text questionText;

    [Tooltip("'Question 2 of 4' style indicator.")]
    public TMP_Text progressText;

    [Tooltip("End-of-quiz score line, e.g. '3 / 4 correct'.")]
    public TMP_Text feedbackText;

    [Tooltip("Exactly 4 buttons, ordered 0..3 to match the options array.")]
    public Button[] optionButtons = new Button[4];

    [Tooltip("Text component on each of the 4 buttons.")]
    public TMP_Text[] optionLabels = new TMP_Text[4];

    [Header("Colors")]
    public Color normalColor = new Color(0.95f, 0.95f, 0.95f, 1f);
    public Color correctColor = new Color(0.4f, 0.8f, 0.4f, 1f);
    public Color wrongColor = new Color(0.85f, 0.4f, 0.4f, 1f);
    public Color fadedColor = new Color(0.75f, 0.75f, 0.75f, 0.45f);

    [Header("Timing")]
    [Tooltip("How long the green/red feedback shows before advancing to next question.")]
    public float feedbackPauseSeconds = 1.5f;

    [Tooltip("How long the final score line stays on screen before the panel hides.")]
    public float summaryDisplaySeconds = 3.5f;

    // ----- Session totals (across multiple briefings) -----
    public int totalCorrect = 0;
    public int totalAnswered = 0;
    public List<PerPatientResult> patientResults = new List<PerPatientResult>();

    [System.Serializable]
    public class PerPatientResult
    {
        public string patientId;
        public int correct;
        public int total;
    }

    // A pooled question carries its source patient so the report can break
    // results down per patient even though all questions run as one quiz.
    private class PooledQuestion
    {
        public RagClient.QuizQuestion question;
        public string patientId;
    }

    // ----- Accumulated pool (filled across briefings) -----
    private readonly List<PooledQuestion> questionPool = new List<PooledQuestion>();

    /// <summary>Number of questions currently accumulated and waiting to be quizzed.</summary>
    public int PooledQuestionCount => questionPool.Count;

    // ----- Active quiz run state -----
    private List<PooledQuestion> activeRun;
    private int currentIndex = 0;
    private bool isAcceptingInput = false;

    // Per-patient tally for the active run, keyed by patient ID
    private Dictionary<string, int[]> runTally;  // patientId -> [correct, total]

    [Header("Backend")]
    [Tooltip("Base URL of the report endpoint, e.g. http://127.0.0.1:8000")]
    public string reportBaseUrl = "http://127.0.0.1:8000";

    private void Awake()
    {
        // Hide panel at startup
        if (rootPanel != null)
            rootPanel.SetActive(false);
    }

    /// <summary>
    /// Accumulate a briefing's questions into the session pool. Called by
    /// RagClient after each ISBAR briefing. Does NOT show the quiz — that
    /// happens when the user says "end handover".
    /// </summary>
    public void AddQuestions(RagClient.QuizQuestion[] questions, string patientId)
    {
        if (questions == null || questions.Length == 0)
            return;

        string pid = patientId ?? "(unknown)";
        foreach (RagClient.QuizQuestion q in questions)
        {
            questionPool.Add(new PooledQuestion { question = q, patientId = pid });
        }
    }

    /// <summary>
    /// Start the quiz over all accumulated questions. Called by RagClient when
    /// the user says "end handover" / "quiz me" / etc.
    /// </summary>
    public void StartPooledQuiz()
    {
        if (questionPool.Count == 0)
        {
            Debug.LogWarning("[QuizPanel] StartPooledQuiz called with empty pool");
            return;
        }

        activeRun = new List<PooledQuestion>(questionPool);
        currentIndex = 0;
        runTally = new Dictionary<string, int[]>();

        if (rootPanel != null)
            rootPanel.SetActive(true);

        if (feedbackText != null)
            feedbackText.text = "";

        ShowCurrentQuestion();
    }

    /// <summary>
    /// Start a quiz immediately with the given questions, bypassing the pool. This is useful for testing or if you want to trigger a quiz on demand for a specific set of questions
    /// a quiz immediately after one briefing rather than pooling. Not used in
    /// the end-handover flow.
    /// </summary>
    public void StartQuiz(RagClient.QuizQuestion[] questions, string patientId)
    {
        questionPool.Clear();
        AddQuestions(questions, patientId);
        StartPooledQuiz();
    }

    private void ShowCurrentQuestion()
    {
        if (currentIndex >= activeRun.Count)
        {
            FinishQuiz();
            return;
        }

        RagClient.QuizQuestion q = activeRun[currentIndex].question;

        if (questionText != null)
            questionText.text = q.question;

        if (progressText != null)
            progressText.text = $"Question {currentIndex + 1} of {activeRun.Count}";

        // Reset button states
        for (int i = 0; i < optionButtons.Length; i++)
        {
            if (i >= q.options.Length)
            {
                // Hide extra buttons if quiz has fewer options than buttons
                if (optionButtons[i] != null) optionButtons[i].gameObject.SetActive(false);
                continue;
            }

            if (optionButtons[i] != null)
            {
                optionButtons[i].gameObject.SetActive(true);
                SetButtonColor(optionButtons[i], normalColor);
                int capturedIndex = i;  // capture for closure
                optionButtons[i].onClick.RemoveAllListeners();
                optionButtons[i].onClick.AddListener(() => OnOptionClicked(capturedIndex));
            }

            if (i < optionLabels.Length && optionLabels[i] != null)
                optionLabels[i].text = q.options[i];
        }

        isAcceptingInput = true;
    }

    private void OnOptionClicked(int clickedIndex)
    {
        if (!isAcceptingInput)
            return;
        isAcceptingInput = false;

        PooledQuestion pq = activeRun[currentIndex];
        RagClient.QuizQuestion q = pq.question;
        bool isCorrect = (clickedIndex == q.correct_index);

        // Color all buttons
        for (int i = 0; i < optionButtons.Length; i++)
        {
            if (optionButtons[i] == null) continue;
            if (i == q.correct_index)
                SetButtonColor(optionButtons[i], correctColor);
            else if (i == clickedIndex)
                SetButtonColor(optionButtons[i], wrongColor);
            else
                SetButtonColor(optionButtons[i], fadedColor);
        }

        // Tally per patient: runTally[pid] = [correct, total]
        if (!runTally.ContainsKey(pq.patientId))
            runTally[pq.patientId] = new int[] { 0, 0 };
        runTally[pq.patientId][1] += 1;            // total
        if (isCorrect)
            runTally[pq.patientId][0] += 1;        // correct

        StartCoroutine(AdvanceAfterPause());
    }

    private System.Collections.IEnumerator AdvanceAfterPause()
    {
        yield return new WaitForSeconds(feedbackPauseSeconds);
        currentIndex++;
        ShowCurrentQuestion();
    }

    private void FinishQuiz()
    {
        int runCorrect = 0;
        int runTotal = 0;

        // Roll the per-patient tally into the session results
        patientResults.Clear();
        foreach (var kvp in runTally)
        {
            int correct = kvp.Value[0];
            int total = kvp.Value[1];
            runCorrect += correct;
            runTotal += total;

            patientResults.Add(new PerPatientResult
            {
                patientId = kvp.Key,
                correct = correct,
                total = total,
            });
        }

        totalCorrect = runCorrect;
        totalAnswered = runTotal;

        float pct = runTotal > 0 ? (100f * runCorrect / runTotal) : 0f;

        if (feedbackText != null)
            feedbackText.text = $"Final score: {runCorrect} / {runTotal}  ({pct:F0}%)\nGenerating report...";

        if (questionText != null)
            questionText.text = "Handover complete!";

        if (progressText != null)
            progressText.text = "";

        // Hide option buttons for the summary screen
        foreach (Button b in optionButtons)
            if (b != null) b.gameObject.SetActive(false);

        Debug.Log($"[QuizPanel] Quiz finished: {runCorrect}/{runTotal} ({pct:F0}%) across {patientResults.Count} patients");

        // Clear the pool so a fresh session starts clean next time
        questionPool.Clear();

        // Request the PDF report from the backend
        StartCoroutine(SubmitReport(runCorrect, runTotal, pct));
    }

    private System.Collections.IEnumerator SubmitReport(int correct, int total, float pct)
    {
        // Build JSON: {"session_id":"unity","results":[{"patientId":..,"correct":..,"total":..}]}
        System.Text.StringBuilder sb = new System.Text.StringBuilder();
        sb.Append("{\"session_id\":\"unity\",\"results\":[");
        for (int i = 0; i < patientResults.Count; i++)
        {
            PerPatientResult r = patientResults[i];
            sb.Append($"{{\"patientId\":\"{EscapeJson(r.patientId)}\",\"correct\":{r.correct},\"total\":{r.total}}}");
            if (i < patientResults.Count - 1)
                sb.Append(",");
        }
        sb.Append("]}");
        string payload = sb.ToString();

        string url = reportBaseUrl.TrimEnd('/') + "/report";
        using (UnityEngine.Networking.UnityWebRequest req =
               new UnityEngine.Networking.UnityWebRequest(url, "POST"))
        {
            req.uploadHandler = new UnityEngine.Networking.UploadHandlerRaw(
                System.Text.Encoding.UTF8.GetBytes(payload));
            req.downloadHandler = new UnityEngine.Networking.DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = 30;

            yield return req.SendWebRequest();

            if (req.result == UnityEngine.Networking.UnityWebRequest.Result.Success)
            {
                Debug.Log("[QuizPanel] Report response: " + req.downloadHandler.text);
                string reportPath = ExtractJsonString(req.downloadHandler.text, "report_path");

                if (feedbackText != null)
                {
                    feedbackText.text =
                        $"Final score: {correct} / {total}  ({pct:F0}%)\n" +
                        (string.IsNullOrEmpty(reportPath)
                            ? "Report generated."
                            : $"Report saved:\n{reportPath}");
                }
                Debug.Log($"[QuizPanel] Report saved at: {reportPath}");
            }
            else
            {
                Debug.LogWarning("[QuizPanel] Report request failed: " + req.error);
                if (feedbackText != null)
                    feedbackText.text =
                        $"Final score: {correct} / {total}  ({pct:F0}%)\n(Report unavailable)";
            }
        }

        StartCoroutine(HideAfterSummary());
    }

    // Minimal JSON string extractor for a top-level "key":"value" pair.
    private string ExtractJsonString(string json, string key)
    {
        if (string.IsNullOrEmpty(json)) return "";
        string token = "\"" + key + "\"";
        int k = json.IndexOf(token);
        if (k < 0) return "";
        int colon = json.IndexOf(':', k + token.Length);
        if (colon < 0) return "";
        int firstQuote = json.IndexOf('"', colon + 1);
        if (firstQuote < 0) return "";
        int secondQuote = json.IndexOf('"', firstQuote + 1);
        // handle escaped backslashes in Windows paths: keep scanning
        while (secondQuote > 0 && json[secondQuote - 1] == '\\')
            secondQuote = json.IndexOf('"', secondQuote + 1);
        if (secondQuote < 0) return "";
        string raw = json.Substring(firstQuote + 1, secondQuote - firstQuote - 1);
        return raw.Replace("\\\\", "\\").Replace("\\/", "/");
    }

    private string EscapeJson(string s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    private System.Collections.IEnumerator HideAfterSummary()
    {
        yield return new WaitForSeconds(summaryDisplaySeconds);
        if (rootPanel != null)
            rootPanel.SetActive(false);
    }

    // -----------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------
    private void SetButtonColor(Button button, Color color)
    {
        ColorBlock cb = button.colors;
        cb.normalColor = color;
        cb.highlightedColor = color;
        cb.pressedColor = color;
        cb.selectedColor = color;
        cb.disabledColor = color;
        button.colors = cb;

        // Also recolor the background image directly so the change is visible
        // even when the button is not interactable.
        Image img = button.GetComponent<Image>();
        if (img != null)
            img.color = color;
    }
}