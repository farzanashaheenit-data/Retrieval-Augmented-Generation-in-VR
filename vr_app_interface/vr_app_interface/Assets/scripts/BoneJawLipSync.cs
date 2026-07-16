using UnityEngine;

public class BoneJawLipSync : MonoBehaviour
{
    [Header("References")]
    [Tooltip("The jaw bone to rotate. For Rocketbox avatars: Bip01 MJaw")]
    public Transform jawBone;

    [Tooltip("AudioSource to read volume from")]
    public AudioSource audioSource;

    [Header("Tuning")]
    [Tooltip("Max angle the jaw opens (degrees). Try 12-20.")]
    [Range(0f, 45f)]
    public float maxJawAngle = 15f;

    [Tooltip("Which axis the jaw rotates around. Usually X.")]
    public enum JawAxis { X, Y, Z }
    public JawAxis rotationAxis = JawAxis.X;

    [Tooltip("Flip direction if jaw opens the wrong way.")]
    public bool invertDirection = false;

    [Tooltip("Audio volume scaling. Higher = mouth opens more easily.")]
    [Range(1f, 30f)]
    public float volumeMultiplier = 10f;

    [Tooltip("Smoothing factor. Higher = smoother but more lag.")]
    [Range(0f, 30f)]
    public float smoothing = 15f;

    [Header("Sampling")]
    [Tooltip("Audio samples to read per frame. 256 is fine.")]
    public int sampleSize = 256;

    private Quaternion closedRotation;
    private bool hasClosedRotation = false;
    private float currentOpenAmount = 0f;
    private float[] audioSamples;

    private void Awake()
    {
        if (audioSource == null)
            audioSource = GetComponent<AudioSource>();

        EnsureSampleBuffer();
        CaptureClosedRotation();
    }

    private void Start()
    {
        EnsureSampleBuffer();
        CaptureClosedRotation();
    }

    private void LateUpdate()
    {
        if (jawBone == null || audioSource == null)
            return;

        EnsureSampleBuffer();
        CaptureClosedRotation();

        float targetOpen = 0f;

        if (audioSource.isPlaying && audioSource.clip != null)
        {
            audioSource.GetOutputData(audioSamples, 0);
            float sum = 0f;
            for (int i = 0; i < audioSamples.Length; i++)
            {
                sum += audioSamples[i] * audioSamples[i];
            }
            float rms = Mathf.Sqrt(sum / audioSamples.Length);
            targetOpen = Mathf.Clamp01(rms * volumeMultiplier);
        }

        currentOpenAmount = Mathf.Lerp(currentOpenAmount, targetOpen, Time.deltaTime * smoothing);

        float angle = currentOpenAmount * maxJawAngle * (invertDirection ? -1f : 1f);

        Vector3 axis = Vector3.zero;
        switch (rotationAxis)
        {
            case JawAxis.X: axis = Vector3.right; break;
            case JawAxis.Y: axis = Vector3.up; break;
            case JawAxis.Z: axis = Vector3.forward; break;
        }

        jawBone.localRotation = closedRotation * Quaternion.AngleAxis(angle, axis);
    }

    private void OnDisable()
    {
        ResetJaw();
    }

    public void ResetJaw()
    {
        currentOpenAmount = 0f;
        if (jawBone == null || !hasClosedRotation)
            return;

        jawBone.localRotation = closedRotation;
    }

    private void EnsureSampleBuffer()
    {
        int safeSampleSize = Mathf.Max(32, sampleSize);
        if (audioSamples == null || audioSamples.Length != safeSampleSize)
            audioSamples = new float[safeSampleSize];
    }

    private void CaptureClosedRotation()
    {
        if (hasClosedRotation || jawBone == null)
            return;

        closedRotation = jawBone.localRotation;
        hasClosedRotation = true;
    }
}
