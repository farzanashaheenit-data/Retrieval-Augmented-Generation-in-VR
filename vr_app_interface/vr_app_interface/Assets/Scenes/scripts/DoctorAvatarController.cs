using System;
using UnityEngine;
// this is avatar-controller code that is specific to the doctor avatar, 
//and not part of the more general-purpose avatar controller that can be used across different characters. 
//It handles things like the doctor's 
[DisallowMultipleComponent]
public class DoctorAvatarController : MonoBehaviour
{
    [Header("Animation")]
    public Animator animator;
    public string speakingParameter = "IsSpeaking";
    public string idleStateName = "Idle";
    public string speakingStateName = "Talking";
    public float transitionDuration = 0.15f;

    [Header("Simple Lip Sync")]
    public AudioSource speechAudioSource;
    public SkinnedMeshRenderer faceRenderer;
    public string[] mouthBlendShapeNames =
    {
        "AA_VI_10_aa",
        "AK_25_JawOpen",
        "AU_26_JawDrop",
        "SR_21_Jaw_Open",
        "AA_VI_13_O",
        "AA_VI_14_U",
        "viseme_aa",
        "viseme_AA",
        "mouthOpen",
        "Mouth_Open",
        "JawOpen",
        "jawOpen"
    };
    public float maxMouthWeight = 70f;
    public float mouthSensitivity = 1400f;
    public float mouthSmoothing = 14f;
    public Transform jawBone;
    public float jawOpenDegrees = 10f;

    [Header("Doctor Look")]
    public bool recolorClothing = false;
    public bool buildDoctorAccessories = false;
    public Color coatColor = new Color(0.93f, 0.94f, 0.92f, 1f);
    public Color scrubColor = new Color(0.07f, 0.22f, 0.32f, 1f);
    public Color stethoscopeColor = new Color(0.02f, 0.025f, 0.03f, 1f);

    private const string AccessoriesRootName = "RuntimeDoctorAccessories";
    private Transform chest;
    private bool isSpeaking;
    private Material coatMaterial;
    private Material badgeMaterial;
    private Material stethoscopeMaterial;
    private int mouthBlendShapeIndex = -1;
    private float currentMouthWeight;
    private float[] audioSamples = new float[256];
    private Quaternion jawClosedRotation;

    private void Awake()
    {
        if (IsConvaiAvatar())
        {
            recolorClothing = false;
            buildDoctorAccessories = false;
        }

        if (animator == null)
            animator = GetComponentInChildren<Animator>();

        chest = FindChildContaining(transform, "Spine2");
        if (chest == null)
            chest = FindChildContaining(transform, "Chest");
        if (jawBone == null)
            jawBone = FindChildContaining(transform, "Jaw");
        if (jawBone != null)
            jawClosedRotation = jawBone.localRotation;

        ResolveMouthBlendShape();

        if (recolorClothing)
            ApplyDoctorColors();

        if (buildDoctorAccessories)
            BuildDoctorAccessories();

        SetSpeaking(false);
    }

    public void RebindAvatar()
    {
        if (animator == null)
            animator = GetComponentInChildren<Animator>(true);

        if (faceRenderer != null && !faceRenderer.transform.IsChildOf(transform))
            faceRenderer = null;

        if (jawBone == null || !jawBone.IsChildOf(transform))
            jawBone = FindChildContaining(transform, "Jaw");
        if (jawBone != null)
            jawClosedRotation = jawBone.localRotation;

        mouthBlendShapeIndex = -1;
        ResolveMouthBlendShape();
        ApplyMouthWeight(0f);
    }

    private bool IsConvaiAvatar()
    {
        Transform current = transform;
        while (current != null)
        {
            if (current.name.IndexOf("convai", StringComparison.OrdinalIgnoreCase) >= 0)
                return true;
            current = current.parent;
        }
        return false;
    }

    private void Update()
    {
        UpdateMouthFromAudio();
    }

    public void SetSpeaking(bool speaking)
    {
        isSpeaking = speaking;
        if (!speaking)
            ApplyMouthWeight(0f);

        if (animator == null)
            return;

        if (HasAnimatorParameter(speakingParameter))
        {
            animator.SetBool(speakingParameter, speaking);
            return;
        }

        string stateName = speaking ? speakingStateName : idleStateName;
        TryCrossFadeAnimatorState(stateName);
    }

    private void ResolveMouthBlendShape()
    {
        if (faceRenderer != null && TryResolveBlendShape(faceRenderer))
            return;

        SkinnedMeshRenderer[] renderers = GetComponentsInChildren<SkinnedMeshRenderer>(true);
        foreach (SkinnedMeshRenderer renderer in renderers)
        {
            if (TryResolveBlendShape(renderer))
                return;
        }
    }

    private bool TryResolveBlendShape(SkinnedMeshRenderer renderer)
    {
        Mesh mesh = renderer.sharedMesh;
        if (mesh == null)
            return false;

        foreach (string preferredName in mouthBlendShapeNames)
        {
            int index = mesh.GetBlendShapeIndex(preferredName);
            if (index >= 0)
            {
                faceRenderer = renderer;
                mouthBlendShapeIndex = index;
                return true;
            }
        }

        for (int i = 0; i < mesh.blendShapeCount; i++)
        {
            string shapeName = mesh.GetBlendShapeName(i);
            string normalizedShapeName = shapeName.Replace("_", "").Replace("-", "");
            if (normalizedShapeName.IndexOf("jawopen", StringComparison.OrdinalIgnoreCase) >= 0 ||
                normalizedShapeName.IndexOf("jawdrop", StringComparison.OrdinalIgnoreCase) >= 0 ||
                normalizedShapeName.IndexOf("mouthopen", StringComparison.OrdinalIgnoreCase) >= 0 ||
                normalizedShapeName.IndexOf("mouthstretch", StringComparison.OrdinalIgnoreCase) >= 0 ||
                normalizedShapeName.IndexOf("visemeaa", StringComparison.OrdinalIgnoreCase) >= 0 ||
                normalizedShapeName.IndexOf("vi10aa", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                faceRenderer = renderer;
                mouthBlendShapeIndex = i;
                return true;
            }
        }

        for (int i = 0; i < mesh.blendShapeCount; i++)
        {
            string shapeName = mesh.GetBlendShapeName(i);
            if ((shapeName.IndexOf("mouth", StringComparison.OrdinalIgnoreCase) >= 0 ||
                shapeName.IndexOf("jaw", StringComparison.OrdinalIgnoreCase) >= 0 ||
                shapeName.IndexOf("viseme", StringComparison.OrdinalIgnoreCase) >= 0) &&
                shapeName.IndexOf("sil", StringComparison.OrdinalIgnoreCase) < 0)
            {
                faceRenderer = renderer;
                mouthBlendShapeIndex = i;
                return true;
            }
        }
        return false;
    }

    private void UpdateMouthFromAudio()
    {
        float targetWeight = 0f;
        bool hasLiveAudio = speechAudioSource != null && speechAudioSource.isPlaying;

        if (isSpeaking && hasLiveAudio)
        {
            speechAudioSource.GetOutputData(audioSamples, 0);
            float sum = 0f;
            for (int i = 0; i < audioSamples.Length; i++)
                sum += audioSamples[i] * audioSamples[i];
            float rms = Mathf.Sqrt(sum / audioSamples.Length);
            targetWeight = Mathf.Clamp(rms * mouthSensitivity, 0f, maxMouthWeight);
        }
        else if (isSpeaking)
        {
            targetWeight = (Mathf.Sin(Time.time * 18f) * 0.5f + 0.5f) * maxMouthWeight * 0.35f;
        }

        float blend = 1f - Mathf.Exp(-mouthSmoothing * Time.deltaTime);
        currentMouthWeight = Mathf.Lerp(currentMouthWeight, targetWeight, blend);
        ApplyMouthWeight(currentMouthWeight);
    }

    private void ApplyMouthWeight(float weight)
    {
        if (faceRenderer != null && mouthBlendShapeIndex >= 0)
            faceRenderer.SetBlendShapeWeight(mouthBlendShapeIndex, weight);

        if (jawBone != null)
        {
            float jawAmount = Mathf.Clamp01(weight / Mathf.Max(maxMouthWeight, 1f));
            jawBone.localRotation = jawClosedRotation * Quaternion.Euler(-jawOpenDegrees * jawAmount, 0f, 0f);
        }
    }

    private bool HasAnimatorParameter(string parameterName)
    {
        if (animator == null || animator.runtimeAnimatorController == null || string.IsNullOrWhiteSpace(parameterName))
            return false;

        foreach (AnimatorControllerParameter parameter in animator.parameters)
        {
            if (parameter.name == parameterName)
                return true;
        }
        return false;
    }

    private bool TryCrossFadeAnimatorState(string stateName)
    {
        if (!TryGetAnimatorStateHash(stateName, out int layerIndex, out int stateHash))
            return false;

        animator.CrossFade(stateHash, transitionDuration, layerIndex);
        return true;
    }

    private bool HasAnimatorState(string stateName)
    {
        return TryGetAnimatorStateHash(stateName, out _, out _);
    }

    private bool TryGetAnimatorStateHash(string stateName, out int layerIndex, out int stateHash)
    {
        layerIndex = -1;
        stateHash = 0;

        if (animator == null || animator.runtimeAnimatorController == null || string.IsNullOrWhiteSpace(stateName))
            return false;

        int shortStateHash = Animator.StringToHash(stateName);
        for (int i = 0; i < animator.layerCount; i++)
        {
            if (animator.HasState(i, shortStateHash))
            {
                layerIndex = i;
                stateHash = shortStateHash;
                return true;
            }

            string fullStateName = animator.GetLayerName(i) + "." + stateName;
            int fullStateHash = Animator.StringToHash(fullStateName);
            if (animator.HasState(i, fullStateHash))
            {
                layerIndex = i;
                stateHash = fullStateHash;
                return true;
            }
        }

        return false;
    }

    private void ApplyDoctorColors()
    {
        Renderer[] renderers = GetComponentsInChildren<Renderer>(true);
        foreach (Renderer renderer in renderers)
        {
            string objectName = renderer.gameObject.name.ToLowerInvariant();
            if (objectName.Contains("shirt") || objectName.Contains("outfit"))
            {
                SetRendererColor(renderer, coatColor);
            }
            else if (objectName.Contains("pants"))
            {
                SetRendererColor(renderer, scrubColor);
            }
            else if (objectName.Contains("shoe") || objectName.Contains("sneaker"))
            {
                SetRendererColor(renderer, Color.black);
            }
        }
    }

    private void SetRendererColor(Renderer renderer, Color color)
    {
        Material[] materials = renderer.materials;
        for (int i = 0; i < materials.Length; i++)
        {
            if (materials[i].HasProperty("_BaseColor"))
                materials[i].SetColor("_BaseColor", color);
            if (materials[i].HasProperty("_Color"))
                materials[i].SetColor("_Color", color);
        }
    }

    private void BuildDoctorAccessories()
    {
        Transform anchor = chest != null ? chest : transform;
        if (anchor.Find(AccessoriesRootName) != null)
            return;

        GameObject root = new GameObject(AccessoriesRootName);
        root.transform.SetParent(anchor, false);
        root.transform.localPosition = Vector3.zero;
        root.transform.localRotation = Quaternion.identity;
        root.transform.localScale = Vector3.one;

        coatMaterial = CreateMaterial("Runtime Doctor Coat", coatColor);
        badgeMaterial = CreateMaterial("Runtime Doctor Badge", new Color(0.15f, 0.45f, 0.75f, 1f));
        stethoscopeMaterial = CreateMaterial("Runtime Stethoscope", stethoscopeColor);

        CreateCube(root.transform, "LeftCoatPanel", new Vector3(-0.075f, -0.12f, 0.055f), new Vector3(0.12f, 0.34f, 0.018f), coatMaterial);
        CreateCube(root.transform, "RightCoatPanel", new Vector3(0.075f, -0.12f, 0.055f), new Vector3(0.12f, 0.34f, 0.018f), coatMaterial);
        CreateCube(root.transform, "Collar", new Vector3(0f, 0.055f, 0.06f), new Vector3(0.27f, 0.045f, 0.018f), coatMaterial);
        CreateCube(root.transform, "IdBadge", new Vector3(0.095f, -0.035f, 0.073f), new Vector3(0.055f, 0.038f, 0.01f), badgeMaterial);

        CreateStethoscope(root.transform);
    }

    private void CreateStethoscope(Transform parent)
    {
        GameObject tubeObject = new GameObject("StethoscopeTube");
        tubeObject.transform.SetParent(parent, false);

        LineRenderer line = tubeObject.AddComponent<LineRenderer>();
        line.useWorldSpace = false;
        line.positionCount = 5;
        line.startWidth = 0.012f;
        line.endWidth = 0.012f;
        line.material = stethoscopeMaterial;
        line.startColor = stethoscopeColor;
        line.endColor = stethoscopeColor;
        line.SetPosition(0, new Vector3(-0.11f, 0.055f, 0.08f));
        line.SetPosition(1, new Vector3(-0.055f, -0.03f, 0.082f));
        line.SetPosition(2, new Vector3(0f, -0.145f, 0.085f));
        line.SetPosition(3, new Vector3(0.055f, -0.03f, 0.082f));
        line.SetPosition(4, new Vector3(0.11f, 0.055f, 0.08f));

        CreateSphere(parent, "StethoscopeBell", new Vector3(0f, -0.16f, 0.088f), new Vector3(0.045f, 0.045f, 0.015f), stethoscopeMaterial);
        CreateSphere(parent, "LeftEarpiece", new Vector3(-0.11f, 0.06f, 0.08f), Vector3.one * 0.018f, stethoscopeMaterial);
        CreateSphere(parent, "RightEarpiece", new Vector3(0.11f, 0.06f, 0.08f), Vector3.one * 0.018f, stethoscopeMaterial);
    }

    private GameObject CreateCube(Transform parent, string objectName, Vector3 localPosition, Vector3 localScale, Material material)
    {
        GameObject cube = GameObject.CreatePrimitive(PrimitiveType.Cube);
        cube.name = objectName;
        cube.transform.SetParent(parent, false);
        cube.transform.localPosition = localPosition;
        cube.transform.localRotation = Quaternion.identity;
        cube.transform.localScale = localScale;
        RemoveCollider(cube);
        cube.GetComponent<Renderer>().material = material;
        return cube;
    }

    private GameObject CreateSphere(Transform parent, string objectName, Vector3 localPosition, Vector3 localScale, Material material)
    {
        GameObject sphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        sphere.name = objectName;
        sphere.transform.SetParent(parent, false);
        sphere.transform.localPosition = localPosition;
        sphere.transform.localRotation = Quaternion.identity;
        sphere.transform.localScale = localScale;
        RemoveCollider(sphere);
        sphere.GetComponent<Renderer>().material = material;
        return sphere;
    }

    private void RemoveCollider(GameObject obj)
    {
        Collider collider = obj.GetComponent<Collider>();
        if (collider != null)
            Destroy(collider);
    }

    private Material CreateMaterial(string materialName, Color color)
    {
        Shader shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null)
            shader = Shader.Find("Standard");
        if (shader == null)
            shader = Shader.Find("Sprites/Default");

        Material material = new Material(shader);
        material.name = materialName;
        if (material.HasProperty("_BaseColor"))
            material.SetColor("_BaseColor", color);
        if (material.HasProperty("_Color"))
            material.SetColor("_Color", color);
        return material;
    }

    private Transform FindChildContaining(Transform parent, string namePart)
    {
        if (parent.name.IndexOf(namePart, StringComparison.OrdinalIgnoreCase) >= 0)
            return parent;

        for (int i = 0; i < parent.childCount; i++)
        {
            Transform result = FindChildContaining(parent.GetChild(i), namePart);
            if (result != null)
                return result;
        }
        return null;
    }
}
