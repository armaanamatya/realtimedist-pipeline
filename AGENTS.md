# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Real-Time Distributed NLP Inference System — a three-node distributed pipeline that detects spoken emergency commands (e.g., "EMERGENCY STOP") and triggers an actuator within a **150ms hard end-to-end deadline**. This is a university course project (COSC 4331).

## Architecture

Three nodes communicate over UDP:

- **Node A** (VxSim instance 0): Audio acquisition + feature extraction. Reads 16kHz mono WAV files, extracts raw waveform chunks, sends via UDP. VxWorks RTOS tasks: `tAudioSample` (10ms), `tFeatureExtract` (20ms), `tUdpTransmit` (20ms).
- **Node B** (Host process, Python + RTX 5060Ti): NLP inference using `superb/wav2vec2-base-superb-ks` (HuggingFace). Currently narrow scope: FP32 vs FP16 comparison. Full scope adds INT8 via ONNX/TensorRT. Confidence threshold > 0.85 to forward commands.
- **Node C** (VxSim instance 1): Command validation + actuator control. Safety debounce (2 consecutive "stop" commands within 200ms), watchdog failsafe if no packet in 500ms.

**Networking:** VxSim instances use `simnet` for IP connectivity. A Python UDP proxy injects network impairments (jitter, packet loss, bandwidth throttling) between nodes.

**Scheduling experiments:** RMS vs EDF comparison on each node. Node A and Node B exceed the 3-task RMS utilization bound under FP32; INT8 brings Node B under the bound.

## Narrow Scope Fallback

The project has a deliberate fallback plan (`tmp/narrow_scope_fallback.txt`) for when time or tooling is tight. Key narrowings:

- **Inference:** FP32 vs FP16 only (no TensorRT/INT8). `nodeB.py` is built for this scope.
- **Scheduling:** RMS-style fixed priorities only (no EDF implementation required; compare in analysis/theory)
- **Network stress:** Baseline + one impaired scenario (not the full matrix)
- **Fault tolerance:** One mechanism (watchdog OR debounce, not both)
- **Deadline:** Can relax to 200-250ms if 150ms not achievable; keep relative FP32 vs FP16 comparison

**Technical fallbacks if blocked:**
- Two VxSims broken → single VxSim for Node A, Node C as Python on host
- No VxWorks at all → all three nodes on host (Python/POSIX threads), confirm with instructor
- Wav2Vec2 too slow → smaller model (e.g., DS-CNN), or report inference time with synthetic load

## Key Files

- `docs/project_spec_v3.md` — Authoritative project specification with task tables, timing budgets, and experiment matrix
- `tmp/project_proposal.md` — Original project proposal (COSC 4331, includes fallback table and timeline)
- `tmp/narrow_scope_fallback.txt` — Narrow scope fallback plan with minimum deliverables checklist
- `docs/setup/node_a_setup_guide.md` — Detailed VxSim setup guide for Node A (VxWorks 7, Wind River Workbench)
- `nodeA_host.py` — Node A Python fallback (replaces VxSim when unavailable)
- `nodeB.py` — Node B inference host (narrow scope: FP32 vs FP16, `--test` mode with mock packets)
- `nodeC_host.py` — Node C Python fallback (replaces VxSim when unavailable)
- `test_listener.py` — UDP listener to verify Node A packets on the host (run with `python test_listener.py`)
- `docs/three_node_diagram.mermaid` — Mermaid diagram of the full pipeline
- `docs/research/additional_sources.md` — Supplementary research sources
- `docs/research/related_works_research.md` — Related works analysis

## UDP Protocol

Packet format: `[seq_num: 4B uint32 LE][timestamp: 8B uint64 LE][audio_chunk: variable]`

Network addresses (simnet):
- Node A: `192.168.200.1`
- Node B: `192.168.200.2`, port `5001`
- Node C: on the second VxSim instance

## Commands

```bash
# Install Python dependencies
pip install -r requirements.txt

# Full pipeline on localhost (no VxSim needed) — open 3 terminals:
python nodeA_host.py --local --wav test_audio.wav   # Terminal 1
python nodeB.py --local --precision fp32             # Terminal 2
python nodeC_host.py --local                         # Terminal 3

# Node B test mode (built-in mock packets, single terminal):
python nodeB.py --test --precision fp32
python nodeB.py --test --precision fp16

# With VxSim (simnet IPs):
python nodeB.py --precision fp32

# Test UDP listener (verify Node A packets)
python test_listener.py
```

## Development Notes

- VxWorks is commercial software requiring a course license. VxWorks 7 vs 6.9 have different project workflows — confirm version with the professor first.
- The `files1/` and `files2/` directories are currently empty placeholders for node source code.
- Node A/C code is C targeting VxWorks (`taskSpawn()`, preemptive priority scheduler). Node B is Python with PyTorch/ONNX/TensorRT.
- "stop" and "go" map to actuator commands; "unknown" and "silence" map to NONE.
