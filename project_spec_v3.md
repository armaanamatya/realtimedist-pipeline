# Real-Time Distributed NLP Inference System — Project Spec v3

## 1. Project Overview

A three-node distributed system that detects spoken emergency commands (e.g. "EMERGENCY STOP") and triggers an actuator within a **150ms hard end-to-end deadline**. Each node handles a distinct pipeline stage, communicates over UDP, and runs its own real-time scheduler. The system runs entirely on a single host machine using VxWorks VxSim for the embedded nodes and a native GPU-accelerated process for inference.

---

## 2. Emulation Architecture

| Node | Platform | Role |
|------|----------|------|
| **Node A** | VxSim instance 0 | Audio acquisition + feature extraction |
| **Node B** | Host process (Python/C++ with RTX 5060Ti) | Pre-trained keyword spotting inference |
| **Node C** | VxSim instance 1 | Command validation + actuator control |

### Why This Setup

**VxSim for Nodes A and C:** VxSim runs VxWorks natively on the host. The VxWorks preemptive priority scheduler maps directly to Rate Monotonic analysis. `simnet` networking between VxSim instances works out of the box. Tasks are created with `taskSpawn()` and we get real RTOS scheduling behavior.

**Host process for Node B:** The inference node needs GPU access to benchmark FP32 vs INT8 model variants on the RTX 5060Ti. Running inference inside VxSim would restrict to CPU-only, making the model comparison meaningless.

**Networking:** VxSim instances use `simnet` for IP connectivity. Network impairments (jitter, packet loss) are injected via a Python UDP proxy between nodes.

---

## 3. Node Specifications

### Node A — Audio Acquisition (VxSim Instance 0)

| Task | Type | Period | WCET | Deadline | VxWorks Priority |
|------|------|--------|------|----------|-----------------|
| `tAudioSample` | Periodic | 10 ms | 3 ms | 10 ms | 100 (highest) |
| `tFeatureExtract` | Periodic | 20 ms | 12 ms | 20 ms | 110 |
| `tUdpTransmit` | Periodic | 20 ms | 3 ms | 20 ms | 120 |

**Details:**
- Reads from a pre-recorded `.wav` file (16kHz, 16-bit mono) via VxSim `passFs`.
- Ring buffer holds 512 samples (~32ms of audio).
- Feature extraction: raw waveform chunks (1 second at 16kHz = 16,000 samples) prepared for the Wav2Vec2 feature extractor. Alternatively, MFCC features can be extracted locally for a lighter variant.
- UDP datagram: `[seq_num (4B) | timestamp (8B) | audio_chunk (variable)]`

**RMS Utilization:** U_A = 3/10 + 12/20 + 3/20 = 1.05 (exceeds 3-task RMS bound of 0.780). This motivates the RMS vs EDF comparison.

### Node B — NLP Inference (Host Process + RTX 5060Ti)

| Task | Type | Period | WCET (FP32) | WCET (INT8) | Deadline |
|------|------|--------|-------------|-------------|----------|
| `recv_features` | Periodic | 20 ms | 2 ms | 2 ms | 20 ms |
| `kws_inference` | Periodic | 50 ms | 40 ms | 18 ms | 50 ms |
| `send_result` | Periodic | 20 ms | 2 ms | 2 ms | 20 ms |

**Model: `superb/wav2vec2-base-superb-ks`**

A pre-trained Wav2Vec2 model fine-tuned for keyword spotting on the Google Speech Commands dataset. No training required — the model is loaded directly from HuggingFace and used for classification.

- **Architecture:** Wav2Vec2 base (~95M params) with a classification head
- **Input:** Raw 16kHz waveform (1-second clips)
- **Output classes (12):** "yes", "no", "up", "down", "go", "stop", "left", "right", "on", "off", "unknown", "silence"
- **Accuracy:** ~96% on Speech Commands v1 test set (published SUPERB benchmark)

For our project, "stop" and "go" map directly to actuator commands. "unknown" and "silence" map to NONE.

**Usage (3 lines):**
```python
from transformers import pipeline
classifier = pipeline("audio-classification", model="superb/wav2vec2-base-superb-ks")
result = classifier("audio_clip.wav")  # returns [{label: "stop", score: 0.97}, ...]
```

**Model variants to benchmark:**

| Variant | How | Expected Latency | Notes |
|---------|-----|-------------------|-------|
| FP32 | PyTorch default | ~35–50ms | Baseline |
| FP16 | `model.half()` | ~20–30ms | Simple cast |
| INT8 | ONNX export + TensorRT quantization | ~15–25ms | Best perf |

**Export pipeline:**
```
PyTorch (FP32) → ONNX (torch.onnx.export) → TensorRT (INT8 calibration) → Inference
```

**Confidence thresholding:** Commands forwarded to Node C only if top-class confidence > 0.85.

**RMS Utilization:**
```
U_B(FP32) = 2/20 + 40/50 + 2/20 = 1.00 → FAILS RMS bound (0.780)
U_B(INT8) = 2/20 + 18/50 + 2/20 = 0.56 → PASSES
```

### Node C — Actuator Control (VxSim Instance 1)

| Task | Type | Period | WCET | Deadline | VxWorks Priority |
|------|------|--------|------|----------|-----------------|
| `tUdpReceive` | Sporadic | — | 3 ms | 50 ms | 100 (highest) |
| `tSafetyValidate` | Periodic | 20 ms | 5 ms | 20 ms | 110 |
| `tActuatorTrigger` | Sporadic | — | 8 ms | 50 ms | 120 |
| `tWatchdog` | Periodic | 100 ms | 2 ms | 100 ms | 130 |

**Safety logic:**
- "stop" requires 2 consecutive commands within 200ms (debounce)
- Watchdog: no packet from Node B in 500ms → failsafe STOP
- Actuator trigger is a logged state change (VxSim has no physical GPIO)

---

## 4. End-to-End Timing Budget

```
D_total = D_sample + D_feature + D_net1 + D_inference + D_net2 + D_actuate
```

| Stage | Best | Nominal | Worst |
|-------|------|---------|-------|
| Audio sampling | 3 ms | 5 ms | 10 ms |
| Feature extraction | 8 ms | 12 ms | 15 ms |
| Network hop 1 | 1 ms | 5 ms | 15 ms |
| Inference (FP32) | 30 ms | 40 ms | 50 ms |
| Inference (INT8) | 12 ms | 18 ms | 25 ms |
| Network hop 2 | 1 ms | 5 ms | 15 ms |
| Safety + actuation | 8 ms | 12 ms | 15 ms |
| **Total (FP32)** | **51 ms** | **79 ms** | **120 ms** |
| **Total (INT8)** | **33 ms** | **57 ms** | **95 ms** |

Both fit within 150ms. Under combined stress, FP32 may violate — that is the experiment.

---

## 5. Scheduling Experiments

### RMS vs EDF
- Run both on each node
- VxWorks preemptive priority = RMS when priorities follow period ordering
- EDF requires custom wrapper with dynamic priority adjustment

**Metrics:** deadline miss ratio, avg/p99 jitter, CPU utilization, WCRT distribution

### Adaptive Scheduling (Extension)
When Node B CPU > 90%: switch FP32 → INT8, increase inference period 50ms → 75ms, signal Node A to reduce feature rate.

---

## 6. Network Impairment

Python UDP proxy injects: jitter (0–15ms), packet loss (0–20%), bandwidth throttling.

| Scenario | Jitter | Loss | Expected |
|----------|--------|------|----------|
| Baseline | 0 ms | 0% | All deadlines met |
| Moderate | 5±3 ms | 2% | Occasional FP32 misses |
| Heavy | 10±5 ms | 10% | FP32 fails, INT8 survives |
| Partition | ∞ | 100% | Watchdog → failsafe |

---

## 7. Fault Tolerance

- **Audio noise:** Gaussian noise at SNR sweep (clean → 0dB). Measure accuracy + latency.
- **Node B crash:** Kill process, measure watchdog detection time + failsafe response.
- **Packet corruption:** Bit flips in UDP payload, measure frames lost.
- **CPU overload:** 30% background load on Node B, measure WCET impact.

---

## 8. Timeline

| Week | Milestones |
|------|-----------|
| 1 | Configure VxSim × 2 with simnet, create Node B process, UDP round-trip |
| 2 | Load wav2vec2-base-superb-ks, export ONNX/TensorRT, wire pipeline, build proxy |
| 3 | Configure RMS/EDF, add instrumentation, run baseline measurements |
| 4 | Full experiment matrix, fault injection, plots, write paper |

---

## 9. Metrics

| Metric | Target |
|--------|--------|
| End-to-end latency | < 150 ms (hard) |
| Deadline miss ratio | < 1% normal load |
| Jitter (p99) | < 5 ms |
| Inference latency | FP32 < 50 ms, INT8 < 25 ms |
| Recovery latency | < 500 ms |
| Detection accuracy | > 96% (pre-trained baseline) |

---

## 10. References

- SUPERB Benchmark — wav2vec2-base-superb-ks (HuggingFace)
- Liu & Layland (1973) — RMS/EDF scheduling theory
- Google Speech Commands v1 dataset
- Wind River VxSim User Guide
- NVIDIA TensorRT INT8 quantization documentation
