"""
Download clean Speech Commands v1.0 test samples.

Streams speech_commands_test_set_v0.01.tar.gz from tensorflow.org and
extracts only the stop/ and go/ WAV files — stops the connection as soon
as we have what we need, so we don't download the whole archive.

Saves (in project root):
  stop_clean.wav  — isolated "stop" keyword (expected model confidence > 0.90)
  go_clean.wav    — isolated "go"   keyword (expected top class = "go", not "stop")

Then does a quick inference check to confirm the downloaded audio gives
high confidence scores before re-running the sweep.
"""

import io
import tarfile
import urllib.request
import struct
import wave
import numpy as np
import soundfile as sf
from pathlib import Path

BASE_DIR   = Path(__file__).parent
SAMPLE_RATE = 16000

# Official Google Speech Commands v0.01 test set (~35-150 MB — we stop early)
TEST_URL = "http://download.tensorflow.org/data/speech_commands_test_set_v0.01.tar.gz"

# ---------------------------------------------------------------------------
# 1. Stream the tar.gz and pull out what we need
# ---------------------------------------------------------------------------
print(f"Streaming {TEST_URL}")
print("(Will stop download as soon as stop/ and go/ samples are found)\n")

stop_wavs: list[bytes] = []
go_wavs:   list[bytes] = []
NEED_STOP, NEED_GO = 2, 1

bytes_downloaded = 0

class CountingReader:
    """Wraps an HTTP response to count bytes and enable early exit."""
    def __init__(self, resp):
        self._resp = resp

    def read(self, n=-1):
        global bytes_downloaded
        data = self._resp.read(n)
        bytes_downloaded += len(data)
        if bytes_downloaded % (1024 * 1024) < n:   # print every ~1 MB
            print(f"\r  Downloaded {bytes_downloaded / 1024 / 1024:.1f} MB  "
                  f"(stop={len(stop_wavs)}/{NEED_STOP}  go={len(go_wavs)}/{NEED_GO})",
                  end="", flush=True)
        return data

try:
    with urllib.request.urlopen(TEST_URL, timeout=60) as resp:
        reader = CountingReader(resp)
        with tarfile.open(fileobj=reader, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith(".wav"):
                    continue
                parts = member.name.replace("\\", "/").split("/")
                # parts[-2] is the word folder, parts[-1] is the filename
                if len(parts) < 2:
                    continue
                word = parts[-2]
                if word == "stop" and len(stop_wavs) < NEED_STOP:
                    f = tar.extractfile(member)
                    if f:
                        stop_wavs.append(f.read())
                        print(f"\n  + stop sample {len(stop_wavs)}: {member.name}")
                elif word == "go" and len(go_wavs) < NEED_GO:
                    f = tar.extractfile(member)
                    if f:
                        go_wavs.append(f.read())
                        print(f"\n  + go   sample {len(go_wavs)}: {member.name}")

                if len(stop_wavs) >= NEED_STOP and len(go_wavs) >= NEED_GO:
                    print(f"\n  Done — stopping download at "
                          f"{bytes_downloaded / 1024 / 1024:.1f} MB")
                    break

except Exception as exc:
    # Non-fatal: we may have partial results if the connection was cut
    print(f"\n  (connection closed early: {exc})")

print(f"\nCollected: {len(stop_wavs)} stop, {len(go_wavs)} go")

if not stop_wavs:
    raise RuntimeError(
        "No 'stop' samples found. The archive structure may differ from expected.\n"
        "Check the archive manually: "
        "python -c \"import tarfile,urllib.request; "
        "[print(m.name) for m in tarfile.open(fileobj=urllib.request.urlopen("
        f"'{TEST_URL}'), mode='r|gz') if '.wav' in m.name][:10]\""
    )

# ---------------------------------------------------------------------------
# 2. Convert raw WAV bytes → normalised 16kHz mono float32 → save as PCM_16
#    VxWorks nodeA skips the first 44 bytes (standard WAV header) and reads
#    int16 PCM samples directly, so soundfile's PCM_16 output is perfect.
# ---------------------------------------------------------------------------
def raw_wav_to_array(wav_bytes: bytes) -> np.ndarray:
    """Read WAV bytes → float32 array at 16kHz."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        sr    = w.getframerate()
        nch   = w.getnchannels()
        samp  = w.getsampwidth()
        nfrm  = w.getnframes()
        raw   = w.readframes(nfrm)
    dtype = np.int16 if samp == 2 else np.int8
    arr = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if nch > 1:                    # stereo → mono
        arr = arr.reshape(-1, nch).mean(axis=1)
    arr /= (32768.0 if samp == 2 else 128.0)
    if sr != SAMPLE_RATE:
        raise ValueError(f"Unexpected sample rate {sr}Hz (expected {SAMPLE_RATE})")
    return arr

def save_wav(dest: Path, audio: np.ndarray) -> None:
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak * 0.95
    if len(audio) < SAMPLE_RATE:
        audio = np.pad(audio, (0, SAMPLE_RATE - len(audio)))
    else:
        audio = audio[:SAMPLE_RATE]
    sf.write(str(dest), audio, SAMPLE_RATE, subtype="PCM_16")
    print(f"  Saved {dest.name}: {len(audio)} samples, {dest.stat().st_size} bytes")

print("\nSaving WAV files...")
stop_path  = BASE_DIR / "stop_clean.wav"
stop2_path = BASE_DIR / "stop_clean2.wav"
go_path    = BASE_DIR / "go_clean.wav"

save_wav(stop_path,  raw_wav_to_array(stop_wavs[0]))
if len(stop_wavs) > 1:
    save_wav(stop2_path, raw_wav_to_array(stop_wavs[1]))
if go_wavs:
    save_wav(go_path, raw_wav_to_array(go_wavs[0]))

# ---------------------------------------------------------------------------
# 3. Quick inference check — confirm confidence is high before re-sweeping
# ---------------------------------------------------------------------------
print("\nVerifying with superb/wav2vec2-base-superb-ks ...")
from transformers import pipeline
import torch

device = 0 if torch.cuda.is_available() else -1
clf = pipeline("audio-classification", model="superb/wav2vec2-base-superb-ks", device=device)

def check(wav_path: Path) -> None:
    if not wav_path.exists():
        return
    results = clf(str(wav_path))
    top = results[0]
    ok = "OK" if top["score"] > 0.50 else "LOW"
    print(f"  [{ok}] {wav_path.name}: "
          f"top={top['label']:8s} conf={top['score']:.4f}  "
          f"(2nd={results[1]['label']:8s} {results[1]['score']:.4f})")

check(stop_path)
if stop2_path.exists():
    check(stop2_path)
if go_path.exists():
    check(go_path)

# ---------------------------------------------------------------------------
# 4. Print instructions
# ---------------------------------------------------------------------------
print("\n" + "="*60)
print("NEXT STEPS")
print("="*60)
print("1. In VxWorks shell — restart Node A with the clean audio:")
print('   -> nodeA_stop')
print('   -> nodeA_start "/host.host/C:/Users/Armaan/Desktop/4331project/stop_clean.wav"')
print()
print("2. Re-run the VxSim sweep:")
print("   venv\\Scripts\\python.exe sweep.py --use-vxsim --verbose")
print()
print("   Expected result: ALL confidence thresholds (0.10, 0.30, 0.50, 0.85)")
print("   should now forward commands, giving complete data across all 72 runs.")
