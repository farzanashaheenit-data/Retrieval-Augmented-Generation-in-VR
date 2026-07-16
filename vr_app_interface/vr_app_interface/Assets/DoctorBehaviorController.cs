
using System.Collections;
using UnityEngine;
using uLipSync;

/// <summary>
/// AI has been used to generate this code based on the following description:
/// Drives the doctor avatar's behavior in coordination with the voice agent's state.
///
/// The voice agent (RagClient) tells this controller what state the conversation is in;
/// the controller handles all visual responses:
///
///   Idle        → relaxed posture, natural breathing, occasional blinks
///   Listening   → subtle forward head tilt, attentive blinks
///   Thinking    → brief processing pose (uses idle animation by default)
///   Speaking    → lip-sync active, hand gestures, brow raises on speech
///
/// Lip-sync (uLipSync) is only enabled during the Speaking state. This is the
/// fundamental fix for "mouth animates from mic input during Listening state."
/// In every non-Speaking state, the analyzer is OFF and the mouth blendshapes
/// are explicitly reset to 0.
///
/// Wire this script on the avatar root (e.g. mycharacter). Inspector references:
///   - animator: the Animator on the same GameObject
///   - faceMesh: the SkinnedMeshRenderer with the viseme blendshapes (CC_Base_Body)
///   - lipSyncAnalyzer: the uLipSync component on the face mesh
///   - lipSyncBlendShape: the uLipSyncBlendShape on the face mesh
///   - headBone: the Bip01/CC_Base_Head transform (for listening tilt) — optional
/// </summary>
[DisallowMultipleComponent]
public class DoctorBehaviorController : MonoBehaviour
{
    public enum BehaviorState
    {
        Idle,
        Listening,
        Thinking,
        Speaking,
    }

    [Header("Avatar References")]
    [Tooltip("Animator on the avatar root. Must have Bool parameters: IsListening, IsThinking, IsSpeaking.")]
    public Animator animator;

    [Tooltip("Skinned mesh that has the viseme + facial expression blendshapes (typically CC_Base_Body).")]
    public SkinnedMeshRenderer faceMesh;

    [Tooltip("Head bone for subtle tilt animation during Listening state. Optional. CC4: usually CC_Base_Head.")]
    public Transform headBone;

    [Header("Lip Sync Coupling")]
    [Tooltip("uLipSync analyzer component. Kept always-on (toggling at runtime crashes). " +
             "Reference is optional — kept for inspection / future use.")]
    public uLipSync.uLipSync lipSyncAnalyzer;

    [Tooltip("uLipSync blend shape driver component. ENABLED only during Speaking — " +
             "this is what gates the mouth animation. Reset to zero when leaving Speaking state.")]
    public uLipSyncBlendShape lipSyncBlendShape;

    [Header("Eye Behavior")]
    [Tooltip("Natural blinks fire at random intervals within this range, in seconds.")]
    public Vector2 blinkIntervalRange = new Vector2(3f, 6f);

    [Tooltip("How quickly the eye closes during a blink. Lower = snappier.")]
    public float blinkSpeed = 0.08f;

    [Range(0f, 100f)]
    [Tooltip("How tightly the eyes close on a blink. 100 = fully closed.")]
    public float blinkClosedWeight = 100f;

    [Header("Brow Behavior")]
    [Tooltip("Probability per spoken second that a brow raise will fire.")]
    [Range(0f, 1f)]
    public float browRaiseProbabilityPerSec = 0.4f;

    [Tooltip("How high to raise the brows. 0-100.")]
    [Range(0f, 100f)]
    public float browRaiseWeight = 40f;

    [Tooltip("Duration of a brow raise from rise to fall, in seconds.")]
    public float browRaiseDuration = 0.6f;

    [Header("Listening Head Tilt")]
    [Tooltip("Degrees of head tilt forward when entering Listening state. 0 disables.")]
    public float listeningTiltDegrees = 8f;

    [Tooltip("How quickly the head moves into and out of the listening tilt.")]
    public float headTiltSpeed = 2.0f;

    [Header("Jaw Lock")]
    [Tooltip("Jaw bone (e.g. CC_Base_JawRoot). When assigned, its rotation is forced " +
             "to neutral every frame outside the Speaking state. This compensates for " +
             "the Animator's humanoid jaw muscle opening the mouth at runtime.")]
    public Transform jawBone;

    // ---- internal state ----
    private BehaviorState currentState = BehaviorState.Idle;
    private Coroutine blinkRoutine;
    private Coroutine browRoutine;
    private Coroutine headTiltRoutine;

    // Animator parameter names (must match the Animator Controller)
    private const string PARAM_IS_LISTENING = "IsListening";
    private const string PARAM_IS_THINKING  = "IsThinking";
    private const string PARAM_IS_SPEAKING  = "IsSpeaking";

    // Blendshape names (CC4 standard)
    private const string BLEND_EYE_BLINK_L = "Eye_Blink_L";
    private const string BLEND_EYE_BLINK_R = "Eye_Blink_R";
    private const string BLEND_BROW_RAISE_INNER_L = "Brow_Raise_Inner_L";
    private const string BLEND_BROW_RAISE_INNER_R = "Brow_Raise_Inner_R";
    private const string BLEND_BROW_RAISE_OUTER_L = "Brow_Raise_Outer_L";
    private const string BLEND_BROW_RAISE_OUTER_R = "Brow_Raise_Outer_R";

    // Cached blendshape indices (resolved once, used many times)
    private int idxBlinkL = -1, idxBlinkR = -1;
    private int idxBrowInnerL = -1, idxBrowInnerR = -1;
    private int idxBrowOuterL = -1, idxBrowOuterR = -1;

    // Head rotation cache
    private Quaternion headBoneRestRotation;
    private bool headBoneCached = false;

    // Jaw rotation cache — keeps jaw at neutral when not speaking
    private Quaternion jawBoneRestRotation;
    private bool jawBoneCached = false;

    private void Start()
    {
        ResolveBlendShapeIndices();
        CacheHeadBoneRotation();
        CacheJawBoneRotation();

        // Ensure mouth starts closed and BlendShape driver is initially disabled.
        // SetState below covers ongoing transitions; this covers the first frame.
        if (lipSyncBlendShape != null)
            lipSyncBlendShape.enabled = false;
        ResetMouthClosed();

        SetState(BehaviorState.Idle);

        // Blinks run continuously regardless of state — natural across the board.
        blinkRoutine = StartCoroutine(BlinkLoop());
    }

    /// <summary>
    /// Called by RagClient (or other systems) to change the avatar's behavior.
    /// Idempotent — calling with the current state is a no-op.
    /// </summary>
    public void SetState(BehaviorState newState)
    {
        if (newState == currentState)
            return;

        BehaviorState previous = currentState;
        currentState = newState;

        // 1) Animator parameters
        if (animator != null)
        {
            animator.SetBool(PARAM_IS_LISTENING, newState == BehaviorState.Listening);
            animator.SetBool(PARAM_IS_THINKING,  newState == BehaviorState.Thinking);
            animator.SetBool(PARAM_IS_SPEAKING,  newState == BehaviorState.Speaking);
        }

        // 2) Lip-sync application — disable the BlendShape component outside Speaking.
        //    The analyzer (uLipSync) keeps running and fires its event continuously,
        //    but with the BlendShape component disabled, nothing applies the result
        //    to the mesh, so the mouth stays where we last set it (zeroed below).
        //
        //    We deliberately do NOT disable lipSyncAnalyzer itself. Toggling its
        //    `enabled` property mid-frame deallocates native arrays that an
        //    in-flight audio thread job may still be using, causing
        //    ObjectDisposedException in OnDataReceived. The analyzer is cheap to
        //    keep running — only the BlendShape application needs gating.
        bool isSpeaking = newState == BehaviorState.Speaking;
        if (lipSyncBlendShape != null)
            lipSyncBlendShape.enabled = isSpeaking;

        // 3) When leaving Speaking, force every viseme blendshape back to 0.
        //    Without this the mouth stays at whatever pose it last had.
        if (previous == BehaviorState.Speaking && !isSpeaking)
            ResetMouthClosed();

        // 4) Brow raises run only during Speaking
        if (isSpeaking)
            browRoutine = StartCoroutine(BrowRaiseLoop());
        else if (browRoutine != null)
        {
            StopCoroutine(browRoutine);
            browRoutine = null;
            ResetBrows();
        }

        // 5) Head tilt runs only during Listening
        bool isListening = newState == BehaviorState.Listening;
        if (headTiltRoutine != null)
            StopCoroutine(headTiltRoutine);

        if (headBone != null)
        {
            float targetTilt = isListening ? listeningTiltDegrees : 0f;
            headTiltRoutine = StartCoroutine(InterpolateHeadTilt(targetTilt));
        }
    }

    // -----------------------------------------------------------------
    // Mouth reset — called every time we leave Speaking state.
    // This is the actual fix for "mouth stuck open in idle."
    // -----------------------------------------------------------------
    private void ResetMouthClosed()
    {
        if (lipSyncBlendShape == null || lipSyncBlendShape.skinnedMeshRenderer == null)
            return;
        if (lipSyncBlendShape.blendShapes == null)
            return;

        foreach (uLipSyncBlendShape.BlendShapeInfo info in lipSyncBlendShape.blendShapes)
        {
            info.weight = 0f;
            info.weightVelocity = 0f;
            if (info.index >= 0)
                lipSyncBlendShape.skinnedMeshRenderer.SetBlendShapeWeight(info.index, 0f);
        }
    }

    // -----------------------------------------------------------------
    // Eye behavior — natural blinks at random intervals.
    // -----------------------------------------------------------------
    private IEnumerator BlinkLoop()
    {
        while (true)
        {
            float wait = Random.Range(blinkIntervalRange.x, blinkIntervalRange.y);
            yield return new WaitForSeconds(wait);
            yield return Blink();
        }
    }

    private IEnumerator Blink()
    {
        if (faceMesh == null || idxBlinkL < 0 || idxBlinkR < 0)
            yield break;

        // Close
        float t = 0f;
        while (t < blinkSpeed)
        {
            t += Time.deltaTime;
            float w = Mathf.Lerp(0f, blinkClosedWeight, t / blinkSpeed);
            faceMesh.SetBlendShapeWeight(idxBlinkL, w);
            faceMesh.SetBlendShapeWeight(idxBlinkR, w);
            yield return null;
        }

        // Hold closed for a single frame
        yield return null;

        // Open
        t = 0f;
        while (t < blinkSpeed)
        {
            t += Time.deltaTime;
            float w = Mathf.Lerp(blinkClosedWeight, 0f, t / blinkSpeed);
            faceMesh.SetBlendShapeWeight(idxBlinkL, w);
            faceMesh.SetBlendShapeWeight(idxBlinkR, w);
            yield return null;
        }

        faceMesh.SetBlendShapeWeight(idxBlinkL, 0f);
        faceMesh.SetBlendShapeWeight(idxBlinkR, 0f);
    }

    // -----------------------------------------------------------------
    // Brow raises — fire occasionally during Speaking, simulate emphasis.
    // -----------------------------------------------------------------
    private IEnumerator BrowRaiseLoop()
    {
        while (currentState == BehaviorState.Speaking)
        {
            // Roughly Poisson process — every second, chance to fire
            yield return new WaitForSeconds(1f);
            if (Random.value < browRaiseProbabilityPerSec)
                yield return BrowRaise();
        }
    }

    private IEnumerator BrowRaise()
    {
        if (faceMesh == null)
            yield break;

        float half = browRaiseDuration * 0.5f;

        // Rise
        float t = 0f;
        while (t < half)
        {
            t += Time.deltaTime;
            float w = Mathf.Lerp(0f, browRaiseWeight, t / half);
            SetBrowWeight(w);
            yield return null;
        }

        // Fall
        t = 0f;
        while (t < half)
        {
            t += Time.deltaTime;
            float w = Mathf.Lerp(browRaiseWeight, 0f, t / half);
            SetBrowWeight(w);
            yield return null;
        }

        SetBrowWeight(0f);
    }

    private void SetBrowWeight(float w)
    {
        if (idxBrowInnerL >= 0) faceMesh.SetBlendShapeWeight(idxBrowInnerL, w);
        if (idxBrowInnerR >= 0) faceMesh.SetBlendShapeWeight(idxBrowInnerR, w);
        if (idxBrowOuterL >= 0) faceMesh.SetBlendShapeWeight(idxBrowOuterL, w * 0.6f);
        if (idxBrowOuterR >= 0) faceMesh.SetBlendShapeWeight(idxBrowOuterR, w * 0.6f);
    }

    private void ResetBrows()
    {
        SetBrowWeight(0f);
    }

    // -----------------------------------------------------------------
    // Head tilt — subtle forward lean when listening.
    // -----------------------------------------------------------------
    private IEnumerator InterpolateHeadTilt(float targetDegrees)
    {
        if (headBone == null || !headBoneCached)
            yield break;

        Quaternion startRotation = headBone.localRotation;
        // Tilt around the local X axis (forward/back nod)
        Quaternion targetRotation = headBoneRestRotation * Quaternion.Euler(targetDegrees, 0f, 0f);

        float duration = 1f / Mathf.Max(0.01f, headTiltSpeed);
        float elapsed = 0f;

        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0f, 1f, elapsed / duration);
            headBone.localRotation = Quaternion.Slerp(startRotation, targetRotation, t);
            yield return null;
        }

        headBone.localRotation = targetRotation;
    }

    // -----------------------------------------------------------------
    // Setup helpers
    // -----------------------------------------------------------------
    private void ResolveBlendShapeIndices()
    {
        if (faceMesh == null || faceMesh.sharedMesh == null)
        {
            Debug.LogWarning("[DoctorBehavior] No face mesh assigned. Eye/brow features disabled.");
            return;
        }

        Mesh mesh = faceMesh.sharedMesh;
        idxBlinkL = mesh.GetBlendShapeIndex(BLEND_EYE_BLINK_L);
        idxBlinkR = mesh.GetBlendShapeIndex(BLEND_EYE_BLINK_R);
        idxBrowInnerL = mesh.GetBlendShapeIndex(BLEND_BROW_RAISE_INNER_L);
        idxBrowInnerR = mesh.GetBlendShapeIndex(BLEND_BROW_RAISE_INNER_R);
        idxBrowOuterL = mesh.GetBlendShapeIndex(BLEND_BROW_RAISE_OUTER_L);
        idxBrowOuterR = mesh.GetBlendShapeIndex(BLEND_BROW_RAISE_OUTER_R);

        if (idxBlinkL < 0 || idxBlinkR < 0)
            Debug.LogWarning("[DoctorBehavior] Eye blink blendshapes not found. Blinks disabled.");
        if (idxBrowInnerL < 0 && idxBrowOuterL < 0)
            Debug.LogWarning("[DoctorBehavior] Brow blendshapes not found. Brow raises disabled.");
    }

    private void CacheHeadBoneRotation()
    {
        if (headBone == null)
            return;
        headBoneRestRotation = headBone.localRotation;
        headBoneCached = true;
    }

    private void CacheJawBoneRotation()
    {
        if (jawBone == null)
            return;
        jawBoneRestRotation = jawBone.localRotation;
        jawBoneCached = true;
    }

    /// <summary>
    /// Forces the jaw bone back to its rest rotation every frame, unless we're
    /// in Speaking state (in which case lip-sync owns the mouth).
    ///
    /// Background: when CC4 humanoid characters run through Unity's Mecanim
    /// retargeting, the humanoid jaw muscle can apply a non-zero default pose
    /// at runtime that opens the mouth — even without any explicit jaw keyframes
    /// in the active animation. LateUpdate runs AFTER the Animator each frame,
    /// so we can override its output here.
    /// </summary>
    private void LateUpdate()
    {
        if (!jawBoneCached || jawBone == null)
            return;

        if (currentState != BehaviorState.Speaking)
            jawBone.localRotation = jawBoneRestRotation;
    }

    private void OnDisable()
    {
        // Make sure the mouth is closed if this component is disabled mid-conversation.
        ResetMouthClosed();
        ResetBrows();
    }
}