using System;
using System.IO;
using UnityEngine;

public static class wavUtility
{
    public static byte[] FromAudioClip(AudioClip clip, out string fileName)
    {
        fileName = "recording.wav";

        using (MemoryStream stream = new MemoryStream())
        {
            int frequency = clip.frequency;
            int channels = clip.channels;
            int samples = clip.samples;

            float[] data = new float[samples * channels];
            clip.GetData(data, 0);

            byte[] pcmData = ConvertToPCM16(data);

            WriteWavHeader(stream, pcmData.Length, frequency, channels);
            stream.Write(pcmData, 0, pcmData.Length);

            return stream.ToArray();
        }
    }

    private static byte[] ConvertToPCM16(float[] data)
    {
        MemoryStream stream = new MemoryStream();

        foreach (float sample in data)
        {
            short intSample = (short)Mathf.Clamp(sample * short.MaxValue, short.MinValue, short.MaxValue);
            byte[] bytes = BitConverter.GetBytes(intSample);
            stream.Write(bytes, 0, bytes.Length);
        }

        return stream.ToArray();
    }

    private static void WriteWavHeader(Stream stream, int dataLength, int sampleRate, int channels)
    {
        int byteRate = sampleRate * channels * 2;

        stream.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"), 0, 4);
        stream.Write(BitConverter.GetBytes(36 + dataLength), 0, 4);
        stream.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"), 0, 4);
        stream.Write(System.Text.Encoding.ASCII.GetBytes("fmt "), 0, 4);
        stream.Write(BitConverter.GetBytes(16), 0, 4);
        stream.Write(BitConverter.GetBytes((short)1), 0, 2);
        stream.Write(BitConverter.GetBytes((short)channels), 0, 2);
        stream.Write(BitConverter.GetBytes(sampleRate), 0, 4);
        stream.Write(BitConverter.GetBytes(byteRate), 0, 4);
        stream.Write(BitConverter.GetBytes((short)(channels * 2)), 0, 2);
        stream.Write(BitConverter.GetBytes((short)16), 0, 2);
        stream.Write(System.Text.Encoding.ASCII.GetBytes("data"), 0, 4);
        stream.Write(BitConverter.GetBytes(dataLength), 0, 4);
    }
}