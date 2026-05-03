# Real-Time Distributed NLP Inference Pipeline

Three-node emergency-command pipeline for COSC 4331.
Targets a **150 ms hard end-to-end deadline** for spoken keyword detection.

| Node | Role | Runtime |
|------|------|---------|
| A | Audio acquisition + feature extraction | VxWorks VxSim **or** `nodeA_host.py` |
| B | Wav2Vec2 keyword inference (GPU) | Python + PyTorch |
| C | Command validation + actuator control | Python (`nodeC_host.py`) |

---

## Installation

```powershell
pip install -r requirements.txt
```

Requires Python 3.10+, PyTorch with CUDA, and an NVIDIA GPU for Node B.
The Wav2Vec2 model (`superb/wav2vec2-base-superb-ks`) is downloaded automatically on first run.

---

## Running the pipeline

### Option 1 — All nodes on one host (no VxSim)

Open three terminals:

```powershell
# Terminal 1 — Node A (Python fallback)
python nodeA_host.py --local --wav test_audio.wav

# Terminal 2 — Node B
python nodeB.py --local --precision fp32

# Terminal 3 — Node C
python nodeC_host.py --local
```

Or use the convenience wrapper (single terminal, auto-shuts down after `--duration` seconds):

```powershell
python run_pipeline.py --wav test_audio.wav --precision fp32 --duration 30 --confidence-threshold 0.30
```

### Option 2 — Node B test mode (no Node A needed)

Node B embeds a mock audio sender (`MockNodeA`) when `--test` is passed.
Useful for inference and scheduling benchmarks without any other node running.

```powershell
# Terminal 1 — Node B (self-contained)
python nodeB.py --test --local --precision fp32

# Terminal 2 — Node C (optional, receives forwarded commands)
python nodeC_host.py --local
```

### Option 3 — VxSim Node A + host Nodes B and C

Start Node A in the VxWorks shell, then run Nodes B and C on the host:

```powershell
# In VxWorks shell (VxSim):
nodeA_setTarget "192.168.200.2", 5001
nodeA_start "/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav"

# On the host:
python nodeB.py --precision fp32
python nodeC_host.py
```

---

## Node B options

| Flag | Default | Description |
|------|---------|-------------|
| `--precision fp32\|fp16` | `fp32` | Model precision |
| `--scheduler rms\|edf\|llf` | `rms` | Scheduling policy |
| `--preemptive` | off | Use Windows OS thread priorities (real preemption) |
| `--partitioned` | off | Pin each task to a dedicated CPU core (requires `--preemptive`) |
| `--infer-period N` | `0.050` | Override inference task period in seconds (e.g. `0.020` for stress test) |
| `--confidence-threshold N` | `0.85` | Forward commands above this confidence |
| `--test` | off | Embed MockNodeA (no external Node A needed) |
| `--local` | off | Use `127.0.0.1` instead of simnet IPs |
| `--duration N` | — | Auto-shutdown after N seconds |
| `--results-dir DIR` | `results` | Output directory |
| `--run-id NAME` | auto | Subdirectory name for this run's results |
| `--no-results` | off | Disable CSV/JSON output |

## Node C options

Same `--scheduler`, `--preemptive`, `--partitioned`, `--local`, `--duration`, `--results-dir`, `--run-id`, `--no-results` flags as Node B.

---

## Scheduling modes

Three scheduling policies are available for Nodes B and C, in two execution modes:

| Mode | Flag | Preemptive? | Description |
|------|------|-------------|-------------|
| Cooperative | *(default)* | No | Single thread; tasks run to completion before next selection |
| OS-thread | `--preemptive` | Approx. yes | One thread per task; Windows `SetThreadPriority` preempts lower-priority tasks |
| Partitioned | `--preemptive --partitioned` | Approx. yes | Each task pinned to a dedicated CPU core via `SetThreadAffinityMask` |

Node A (VxWorks) is always preemptive RMS via `taskSpawn` — this cannot be changed from the host.

**Example combinations:**

```powershell
# Cooperative EDF
python nodeB.py --test --local --scheduler edf

# Preemptive LLF (OS thread priorities, global scheduling)
python nodeB.py --test --local --scheduler llf --preemptive

# Partitioned RMS (one core per task)
python nodeB.py --test --local --scheduler rms --preemptive --partitioned

# Stress test: 20 ms inference period (raises U_infer from 0.15 to ~0.40)
python nodeB.py --test --local --scheduler edf --preemptive --infer-period 0.020
```

---

## Automated sweep

`sweep.py` runs the full experiment matrix automatically and writes results to
`results/sweep/sweep_summary.csv`.

**Matrix:** 3 policies × 2 precisions × 4 thresholds × 3 execution modes = **72 runs**
(doubled with `--stress` for 144 total).

```powershell
# Preview all experiments without running:
python sweep.py --dry-run

# Quick smoke test (6 runs, ~10 min):
python sweep.py --quick

# Full sweep (~2 hours):
python sweep.py

# Full sweep + stress-test mode (20 ms inference period):
python sweep.py --stress

# Filter to one policy or precision:
python sweep.py --scheduler edf --precision fp32

# Show nodeB/nodeC output live:
python sweep.py --verbose
```

### Sweep with VxSim Node A

Node A must be running in VxWorks shell before starting the sweep.
It streams audio continuously; nodeB restarts between runs automatically.

```powershell
# In VxWorks shell — run once before the sweep:
nodeA_setTarget "192.168.200.2", 5001
nodeA_start "/host.host/C:/Users/Armaan/Desktop/4331project/test_audio.wav"

# On the host:
python sweep.py --use-vxsim --dry-run   # verify commands first
python sweep.py --use-vxsim --quick     # smoke test
python sweep.py --use-vxsim             # full sweep

# When done, in VxWorks shell:
nodeA_stop
```

Results are tagged `audio_source=vxsim` in the CSV and use `_vxsim` suffixed run IDs,
so they can be run alongside mock-mode results without collision.

---

## Results

Each run writes to `results/<run-id>/`:

| File | Contents |
|------|----------|
| `nodeB_summary.json` | Timing stats (avg/max/p99), overrun counts, empirical utilization per task |
| `nodeB_inference.csv` | Per-inference label, confidence, latency, precision |
| `nodeB_send.csv` | Per-send timing and target |
| `nodeC_summary.json` | Overruns, actuator triggers, watchdog events |
| `nodeC_events.csv` | Per-event log (receive, actuator, overrun, watchdog) |

The sweep aggregates all runs into `results/sweep/sweep_summary.csv` with columns for
every timing metric and empirical utilization value.

---

## Generating test audio

```powershell
python generate_test_wav.py          # creates test_audio.wav (16 kHz, mono, 16-bit)
```

---

## Layout

```text
.
├── nodeA_host.py          Node A Python fallback (replaces VxSim)
├── nodeB.py               Node B — Wav2Vec2 inference host
├── nodeC_host.py          Node C — actuator control + watchdog
├── scheduler.py           CooperativeScheduler + WindowsThreadScheduler (RMS/EDF/LLF)
├── sweep.py               Automated experiment matrix runner
├── run_pipeline.py        Single-command convenience wrapper
├── results_logging.py     CSV/JSON results helper
├── udp_proxy.py           Network impairment proxy (jitter, loss, throttle)
├── generate_test_wav.py   Test audio generator
├── test_listener.py       UDP listener for verifying Node A packets
├── paper.tex              IEEE conference paper
├── requirements.txt
└── docs/
    ├── project_spec_v3.md
    ├── three_node_diagram.mermaid
    └── setup/
        ├── node_a_setup_guide.md
        └── nodeAsetupchallenges.md
```

Generated files (`venv/`, `__pycache__/`, WAV files, `results/`) are ignored by Git.
