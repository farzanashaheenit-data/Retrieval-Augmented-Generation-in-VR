using UnityEngine;
using UnityEngine.UI;
using TMPro;
using System;
using System.Text;
using System.Text.RegularExpressions;

public class InfoCanvasDisplay : MonoBehaviour
{
    public RagClient ragClient;
    public TextMeshProUGUI titleText;
    public TextMeshProUGUI answerText;
    public TextMeshProUGUI statusText;
    public TMP_InputField inputField;
    public TextMeshProUGUI introductionText;
    public TextMeshProUGUI situationText;
    public TextMeshProUGUI backgroundText;
    public TextMeshProUGUI assessmentText;
    public TextMeshProUGUI recommendationText;
    public TextMeshProUGUI scoreText;
    public TextMeshProUGUI suggestedText;
    public int score;

    [Header("Clinical Card")]
    public TextMeshProUGUI subtitleText;
    public TextMeshProUGUI patientNameText;
    public TextMeshProUGUI patientIdText;
    public TextMeshProUGUI patientDemographicsText;
    public bool showStatusText = false;
    public string assistantTitle = "DR. RAGGY";
    public string assistantSubtitle = "clinical assistant";

    [Serializable]
    public class ISBARFeedbackResponse
    {
        public string patientId;
        public FeedbackSections feedback;
        public string improvedISBAR;
    }

    [Serializable]
    public class FeedbackSections
    {
        public FeedbackItem introduction;
        public FeedbackItem situation;
        public FeedbackItem background;
        public FeedbackItem assessment;
        public FeedbackItem recommendation;
    }

    [Serializable]
    public class FeedbackItem
    {
        public string status;
        public string comment;
    }

    [Serializable]
    private class AssistantTextPayload
    {
        public string answer;
        public string response;
        public string message;
        public string text;
        public string improvedISBAR;
    }

    [Serializable]
    private class PatientPayload
    {
        public string name;
        public string patientName;
        public string patient_name;
        public string id;
        public string patientId;
        public string patient_id;
        public string age;
        public string gender;
        public string sex;
        public string department;
        public string specialty;
        public string ward;
        public string diagnosis;
    }

    private class PatientInfo
    {
        public string name;
        public string id;
        public string age;
        public string gender;
        public string specialty;

        public bool HasAnyValue()
        {
            return !string.IsNullOrWhiteSpace(name)
                || !string.IsNullOrWhiteSpace(id)
                || !string.IsNullOrWhiteSpace(age)
                || !string.IsNullOrWhiteSpace(gender)
                || !string.IsNullOrWhiteSpace(specialty);
        }
    }

    private Transform panelRoot;
    private Image panelImage;
    private Image statusPillImage;
    private Image statusIndicatorImage;

    private static readonly Color32 TextColor = new Color32(83, 81, 78, 255);
    private static readonly Color32 MutedTextColor = new Color32(136, 135, 128, 255);
    private static readonly Color32 ReadyColor = new Color32(78, 176, 87, 255);
    private static readonly Color32 ThinkingColor = new Color32(186, 117, 23, 255);
    private static readonly Color32 SpeakingColor = new Color32(24, 95, 165, 255);
    private static readonly Vector2 AnswerAnchor = new Vector2(0.5f, 0.5f);
    private static readonly Vector2 AnswerBoxSize = new Vector2(142f, 182f);
    private static readonly Vector2 AnswerBoxPosition = new Vector2(-13f, -83f);

    private void Awake()
    {
        if (ragClient == null)
            ragClient = UnityEngine.Object.FindAnyObjectByType<RagClient>();

        if (ragClient != null)
            ragClient.infoCanvas = this;
        else
            Debug.LogError("[InfoCanvas] RagClient not found.");

        AutoWireSceneReferences();
       // ApplyClinicalCardStyle();
        SetStatus("ready");

        if (answerText != null &&
            (string.IsNullOrWhiteSpace(answerText.text) || answerText.text.Trim() == "Response"))
            answerText.text = "";
    }

    private void OnEnable()
    {
        if (ragClient == null)
            ragClient = UnityEngine.Object.FindAnyObjectByType<RagClient>();

        if (ragClient != null)
        {
            ragClient.OnRequestStarted += ShowThinking;
            ragClient.OnAnswerReceivedWithContext += ShowAnswerWithContext;
        }
        else
        {
            Debug.LogError("[InfoCanvas] RagClient not assigned.");
        }
    }

    private void OnDisable()
    {
        if (ragClient != null)
        {
            ragClient.OnRequestStarted -= ShowThinking;
            ragClient.OnAnswerReceivedWithContext -= ShowAnswerWithContext;
        }
    }

    public void ShowThinking()
    {
        SetStatus("thinking");

        if (answerText != null)
            answerText.text = "";

        ClearSectionFields();
    }

    public void ShowAnswer(string text)
    {
        string patientContext = ragClient != null ? ragClient.LastRetrievedPatient : "";
        ShowAnswer(text, patientContext);
    }

    public void ShowAnswer(string text, string patientContext)
    {
        AutoWireSceneReferences();
        //ApplyClinicalCardStyle();
        ClearSectionFields();

        string formatted = FormatAssistantText(ExtractAssistantText(text));
        if (answerText != null)
            answerText.text = formatted;

        UpdatePatientContext(patientContext, formatted);
    }

    private void ShowAnswerWithContext(string text, string patientContext)
    {
        ShowAnswer(text, patientContext);
    }

    private void AutoWireSceneReferences()
    {
        if (answerText == null)
            answerText = GetComponent<TextMeshProUGUI>();

        panelRoot = ResolvePanelRoot();

        if (answerText == null)
            answerText = FindText("ragtext");

        if (titleText == null)
            titleText = FindText("DR. RAGGY");

        if (subtitleText == null)
            subtitleText = FindText("Clinical Assistant");

        if (statusText == null)
            statusText = FindText("Listening");

        if (patientNameText == null)
            patientNameText = FindText("Patient Name");

        if (patientIdText == null)
            patientIdText = FindText("Patient ID");

        if (patientDemographicsText == null)
            patientDemographicsText = FindText("Demographics");

        if (panelRoot != null)
            panelImage = panelRoot.GetComponent<Image>();

        Transform statusPill = FindChildTransform("Status Pill");
        if (statusPill != null)
        {
            statusPillImage = statusPill.GetComponent<Image>();
            Image[] images = statusPill.GetComponentsInChildren<Image>(true);
            foreach (Image image in images)
            {
                if (image != statusPillImage)
                {
                    statusIndicatorImage = image;
                    break;
                }
            }
        }
    }

    private Transform ResolvePanelRoot()
    {
        Transform start = answerText != null ? answerText.transform : transform;
        Transform current = start;
        while (current != null)
        {
            if (string.Equals(current.name, "ragPanel", StringComparison.OrdinalIgnoreCase))
                return current;

            current = current.parent;
        }

        if (start.parent != null)
            return start.parent;

        return start;
    }

    private TextMeshProUGUI FindText(string objectName)
    {
        Transform root = panelRoot != null ? panelRoot : transform.root;
        if (root == null)
            return null;

        TextMeshProUGUI[] texts = root.GetComponentsInChildren<TextMeshProUGUI>(true);
        foreach (TextMeshProUGUI text in texts)
        {
            if (string.Equals(text.gameObject.name, objectName, StringComparison.OrdinalIgnoreCase))
                return text;
        }

        return null;
    }

    private Transform FindChildTransform(string objectName)
    {
        Transform root = panelRoot != null ? panelRoot : transform.root;
        if (root == null)
            return null;

        Transform[] children = root.GetComponentsInChildren<Transform>(true);
        foreach (Transform child in children)
        {
            if (string.Equals(child.gameObject.name, objectName, StringComparison.OrdinalIgnoreCase))
                return child;
        }

        return null;
    }

    private void ApplyClinicalCardStyle()
    {
        if (panelImage != null)
            panelImage.color = new Color32(248, 250, 252, 245);

        if (titleText != null)
        {
            titleText.text = assistantTitle;
            titleText.color = TextColor;
            titleText.fontSize = 14f;
            titleText.fontStyle = FontStyles.Normal;
            titleText.alignment = TextAlignmentOptions.Left;
        }

        if (subtitleText != null)
        {
            subtitleText.text = assistantSubtitle;
            subtitleText.color = MutedTextColor;
            subtitleText.fontSize = 10f;
            subtitleText.fontStyle = FontStyles.Normal;
            subtitleText.alignment = TextAlignmentOptions.Left;
        }

        if (answerText != null)
        {
            answerText.color = new Color32(96, 93, 90, 255);
            answerText.fontSize = 13f;
            answerText.enableAutoSizing = true;
            answerText.fontSizeMin = 10f;
            answerText.fontSizeMax = 13f;
            answerText.fontStyle = FontStyles.Normal;
            answerText.alignment = TextAlignmentOptions.Center;
            answerText.textWrappingMode = TextWrappingModes.Normal;
            answerText.overflowMode = TextOverflowModes.Truncate;
            answerText.margin = Vector4.zero;
            answerText.characterSpacing = 0f;
            answerText.wordSpacing = 0f;
            answerText.lineSpacing = -3f;
            answerText.paragraphSpacing = 0f;

            RectTransform rect = answerText.rectTransform;
            rect.anchorMin = AnswerAnchor;
            rect.anchorMax = AnswerAnchor;
            rect.pivot = new Vector2(0.5f, 0.5f);
            rect.sizeDelta = AnswerBoxSize;
            rect.anchoredPosition = AnswerBoxPosition;
            rect.localScale = Vector3.one;
        }

        if (statusPillImage != null)
            statusPillImage.color = new Color32(233, 243, 222, 255);

        Transform statusPill = statusPillImage != null ? statusPillImage.transform : FindChildTransform("Status Pill");
        if (statusPill != null)
        {
            RectTransform rect = statusPill.GetComponent<RectTransform>();
            if (rect != null)
                rect.sizeDelta = new Vector2(80f, 56f);

            LayoutElement layout = statusPill.GetComponent<LayoutElement>();
            if (layout == null)
                layout = statusPill.gameObject.AddComponent<LayoutElement>();
            layout.preferredWidth = 80f;
            layout.preferredHeight = 56f;
        }

        if (statusIndicatorImage != null)
        {
            RectTransform rect = statusIndicatorImage.rectTransform;
            rect.sizeDelta = new Vector2(12f, 12f);

            LayoutElement layout = statusIndicatorImage.GetComponent<LayoutElement>();
            if (layout == null)
                layout = statusIndicatorImage.gameObject.AddComponent<LayoutElement>();
            layout.preferredWidth = 12f;
            layout.preferredHeight = 12f;
        }

        if (statusText != null)
        {
            statusText.fontSize = 10f;
            statusText.alignment = TextAlignmentOptions.Center;
            statusText.textWrappingMode = TextWrappingModes.NoWrap;
        }
    }

    private string ExtractAssistantText(string rawText)
    {
        if (string.IsNullOrWhiteSpace(rawText))
            return "";

        string trimmed = rawText.Trim();
        if (!trimmed.StartsWith("{"))
            return trimmed;

        try
        {
            AssistantTextPayload payload = JsonUtility.FromJson<AssistantTextPayload>(trimmed);
            if (payload != null)
            {
                if (!string.IsNullOrWhiteSpace(payload.answer)) return payload.answer;
                if (!string.IsNullOrWhiteSpace(payload.response)) return payload.response;
                if (!string.IsNullOrWhiteSpace(payload.message)) return payload.message;
                if (!string.IsNullOrWhiteSpace(payload.text)) return payload.text;
                if (!string.IsNullOrWhiteSpace(payload.improvedISBAR)) return payload.improvedISBAR;
            }
        }
        catch
        {
            Debug.LogWarning("[InfoCanvas] Could not parse assistant JSON, showing cleaned text.");
        }

        return trimmed;
    }

    private string FormatAssistantText(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";

        text = text.Trim();
        text = text.Replace("\\n", "\n");
        text = text.Replace("\\\"", "\"");
        text = text.Replace("**", "");
        text = text.Replace("###", "");
        text = text.Replace("##", "");
        text = text.Replace("#", "");
        text = text.Replace("*", "");
        text = text.Replace("__", "");
        text = Regex.Replace(text, @"\s+", " ");

        if (text.Length >= 2 && text[0] == '"' && text[text.Length - 1] == '"')
            text = text.Substring(1, text.Length - 2);

        return text.Trim();
    }

    private void UpdatePatientContext(string patientContext, string answer)
    {
        PatientInfo patient = ParsePatientInfo(patientContext);
        if (!patient.HasAnyValue())
            patient = ParsePatientInfo(answer);

        if (!patient.HasAnyValue())
            return;

        if (patientNameText != null && !string.IsNullOrWhiteSpace(patient.name))
            patientNameText.text = patient.name;

        if (patientIdText != null && !string.IsNullOrWhiteSpace(patient.id))
            patientIdText.text = patient.id;

        string demographics = BuildDemographics(patient);
        if (patientDemographicsText != null && !string.IsNullOrWhiteSpace(demographics))
            patientDemographicsText.text = demographics;
    }

    private PatientInfo ParsePatientInfo(string text)
    {
        PatientInfo patient = new PatientInfo();
        if (string.IsNullOrWhiteSpace(text))
            return patient;

        string normalized = text.Replace("\\n", " ").Replace("\\\"", "\"");

        if (normalized.TrimStart().StartsWith("{"))
            ApplyJsonPatientInfo(normalized, patient);

        patient.id = FirstNonEmpty(
            patient.id,
            MatchValue(normalized, @"\b(?:patient[_\s-]*id|patientId|id)\s*[:=]\s*[""']?([A-Za-z]\d{2,})"),
            MatchValue(normalized, @"\b([A-Za-z]\d{3,})\b"));

        patient.name = FirstNonEmpty(
            patient.name,
            MatchValue(normalized, @"\b(?:patient[_\s-]*name|patientName|name)\s*[:=]\s*[""']?([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)"),
            MatchValue(normalized, @"(?:^|,\s*)([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+),\s*[A-Za-z]\d{3,}"));

        patient.age = FirstNonEmpty(
            patient.age,
            MatchValue(normalized, @"\b(?:age)\s*[:=]\s*[""']?(\d{1,3})"),
            MatchValue(normalized, @"\b(\d{1,3})\s*(?:yrs?|years?\s*old|year-old)\b"));

        patient.gender = FirstNonEmpty(
            patient.gender,
            MatchValue(normalized, @"\b(?:gender|sex)\s*[:=]\s*[""']?(male|female|man|woman)\b"),
            MatchValue(normalized, @"\b(male|female)\b"));

        patient.specialty = FirstNonEmpty(
            patient.specialty,
            MatchValue(normalized, @"\b(?:department|specialty|ward|diagnosis)\s*[:=]\s*[""']?([A-Z][A-Za-z ]+)"),
            MatchValue(normalized, @"\b(Oncology|Cardiology|Neurology|Emergency|ICU|Surgery|Pediatrics|Orthopedics)\b"));

        patient.name = CleanPatientValue(patient.name);
        patient.id = CleanPatientValue(patient.id);
        patient.age = CleanPatientValue(patient.age);
        patient.gender = CleanPatientValue(patient.gender);
        patient.specialty = CleanPatientValue(patient.specialty);

        return patient;
    }

    private void ApplyJsonPatientInfo(string json, PatientInfo patient)
    {
        try
        {
            PatientPayload payload = JsonUtility.FromJson<PatientPayload>(json);
            if (payload == null)
                return;

            patient.name = FirstNonEmpty(payload.name, payload.patientName, payload.patient_name);
            patient.id = FirstNonEmpty(payload.patientId, payload.patient_id, payload.id);
            patient.age = payload.age;
            patient.gender = FirstNonEmpty(payload.gender, payload.sex);
            patient.specialty = FirstNonEmpty(payload.specialty, payload.department, payload.ward, payload.diagnosis);
        }
        catch
        {
            Debug.LogWarning("[InfoCanvas] Could not parse patient JSON, trying text patterns.");
        }
    }

    private string BuildDemographics(PatientInfo patient)
    {
        StringBuilder builder = new StringBuilder();

        if (!string.IsNullOrWhiteSpace(patient.age))
            builder.Append(patient.age).Append(" yrs");

        AppendDemographic(builder, Capitalize(patient.gender));
        AppendDemographic(builder, patient.specialty);

        return builder.ToString();
    }

    private void AppendDemographic(StringBuilder builder, string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return;

        if (builder.Length > 0)
            builder.Append(" | ");

        builder.Append(value.Trim());
    }

    private string MatchValue(string text, string pattern)
    {
        Match match = Regex.Match(text, pattern, RegexOptions.IgnoreCase);
        if (!match.Success || match.Groups.Count < 2)
            return "";

        return match.Groups[1].Value;
    }

    private string FirstNonEmpty(params string[] values)
    {
        foreach (string value in values)
        {
            if (!string.IsNullOrWhiteSpace(value))
                return value.Trim();
        }

        return "";
    }

    private string CleanPatientValue(string value)
    {
        if (string.IsNullOrWhiteSpace(value))
            return "";

        return value.Trim().Trim('"', '\'', ',', '.', ';', ':');
    }

    private string Capitalize(string value)
    {
        value = CleanPatientValue(value);
        if (string.IsNullOrWhiteSpace(value))
            return "";

        if (value.Length == 1)
            return value.ToUpperInvariant();

        return char.ToUpperInvariant(value[0]) + value.Substring(1).ToLowerInvariant();
    }

    private void ClearSectionFields()
    {
        if (introductionText != null) introductionText.text = "";
        if (situationText != null) situationText.text = "";
        if (backgroundText != null) backgroundText.text = "";
        if (assessmentText != null) assessmentText.text = "";
        if (recommendationText != null) recommendationText.text = "";
        if (suggestedText != null) suggestedText.text = "";
        if (scoreText != null) scoreText.text = "";
    }

    public void SetStatus(string state)
    {
        string normalized = string.IsNullOrWhiteSpace(state) ? "ready" : state.ToLowerInvariant();
        string label;
        Color32 color;
        Color32 background;

        switch (normalized)
        {
            case "listening":
                label = "Listening";
                color = ReadyColor;
                background = new Color32(233, 243, 222, 255);
                break;
            case "thinking":
                label = "Thinking";
                color = ThinkingColor;
                background = new Color32(248, 236, 216, 255);
                break;
            case "speaking":
                label = "Speaking";
                color = SpeakingColor;
                background = new Color32(225, 237, 249, 255);
                break;
            case "ready":
            default:
                label = "Ready";
                color = ReadyColor;
                background = new Color32(233, 243, 222, 255);
                break;
        }

        if (statusText != null)
        {
            statusText.text = showStatusText ? label : "";
            statusText.color = color;
        }

        if (statusPillImage != null)
            statusPillImage.color = background;

        if (statusIndicatorImage != null)
            statusIndicatorImage.color = color;
    }
}
