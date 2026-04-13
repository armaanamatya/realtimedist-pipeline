"""
generate_test_wav.py — Generate test WAV files for pipeline testing.

Creates 16kHz, 16-bit mono WAV files suitable for the distributed pipeline.
"""

import struct
import wave
import numpy as np

SAMPLE_RATE = 16000


def generate_wav(filename, duration_s=3.0, freq_hz=440.0, amplitude=0.5):
    """Generate a sine wave WAV file."""
    n_samples = int(SAMPLE_RATE * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    signal = (amplitude * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)

    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(signal.tobytes())

    print(f"Generated {filename}: {duration_s}s, {freq_hz}Hz, {n_samples} samples")


def generate_noise_wav(filename, duration_s=3.0, amplitude=0.3):
    """Generate a noise WAV file (useful for triggering 'unknown'/'silence')."""
    n_samples = int(SAMPLE_RATE * duration_s)
    signal = (amplitude * 32767 * np.random.randn(n_samples)).astype(np.int16)

    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(signal.tobytes())

    print(f"Generated {filename}: {duration_s}s, noise, {n_samples} samples")


def download_speech_commands_sample(keyword="stop", output_path=None):
    """Download a sample from Google Speech Commands via HuggingFace datasets."""
    try:
        from datasets import load_dataset
    except ImportError:
        print("Installing 'datasets' library...")
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "datasets", "soundfile"])
        from datasets import load_dataset

    import soundfile as sf

    print(f"Downloading Speech Commands sample for '{keyword}'...")
    ds = load_dataset("google/speech_commands", "v0.01", split="test", streaming=True)

    # Find a sample matching the keyword
    for sample in ds:
        if sample["label"] == keyword or \
           (hasattr(sample, "get") and sample.get("text", "") == keyword):
            # The label field is an int; check the actual label name
            pass

    # Non-streaming approach: filter by label
    ds = load_dataset("google/speech_commands", "v0.01", split="test", trust_remote_code=True)
    # Find label index for keyword
    label_names = ds.features["label"].names
    if keyword not in label_names:
        print(f"Keyword '{keyword}' not found. Available: {label_names}")
        return None

    label_idx = label_names.index(keyword)
    filtered = ds.filter(lambda x: x["label"] == label_idx)

    if len(filtered) == 0:
        print(f"No samples found for '{keyword}'")
        return None

    sample = filtered[0]
    audio = np.array(sample["audio"]["array"], dtype=np.float32)
    sr = sample["audio"]["sampling_rate"]

    if output_path is None:
        output_path = f"test_{keyword}.wav"

    # Convert to 16-bit PCM
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_int16.tobytes())

    print(f"Saved {output_path}: {len(audio)/sr:.2f}s at {sr}Hz, '{keyword}' sample")
    return output_path


if __name__ == "__main__":
    generate_wav("test_audio.wav", duration_s=3.0, freq_hz=440.0)
    generate_noise_wav("test_noise.wav", duration_s=3.0)

    # Download real speech samples
    for kw in ["stop", "go"]:
        try:
            download_speech_commands_sample(kw)
        except Exception as e:
            print(f"Could not download '{kw}' sample: {e}")

    print("\nDone. Use with: python nodeA_host.py --local --wav test_stop.wav")
