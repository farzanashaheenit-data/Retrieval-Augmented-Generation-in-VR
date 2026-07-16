using UnityEngine;

public class MicTest : MonoBehaviour
{
    private AudioClip clip;
    private string micDevice;

    void Start()
    {
        // List all mics
        foreach (var device in Microphone.devices)
            Debug.Log("[MicTest] Found mic: " + device);

        micDevice = Microphone.devices[0];
        Debug.Log("[MicTest] Using: " + micDevice);
    }

    // Call this from a UI Button
    public void StartTest()
    {
        Debug.Log("[MicTest] Button pressed - starting recording");
        clip = Microphone.Start(micDevice, false, 5, 44100);
        Debug.Log("[MicTest] Recording started: " + (clip != null));
        Invoke("StopTest", 3f);
    }

    void StopTest()
    {
        Microphone.End(micDevice);
        Debug.Log("[MicTest] Recording stopped");

        if (clip == null)
        {
            Debug.LogError("[MicTest] Clip is NULL");
            return;
        }

        float[] samples = new float[clip.samples];
        clip.GetData(samples, 0);

        float maxAmp = 0f;
        foreach (var s in samples)
            maxAmp = Mathf.Max(maxAmp, Mathf.Abs(s));

        Debug.Log("[MicTest] Max amplitude: " + maxAmp);

        if (maxAmp > 0.01f)
            Debug.Log("[MicTest] ✅ Mic working!");
        else
            Debug.LogError("[MicTest] ❌ No audio captured");
    }
}