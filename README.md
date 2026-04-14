# Real-Time Distributed NLP Inference Pipeline

Three-node emergency command pipeline for COSC 4331:

- Node A: VxWorks/VxSim or Python host fallback audio sender
- Node B: Python Wav2Vec2 keyword inference on the host GPU
- Node C: Python host fallback command validation and actuator logic

## Quick Start

```powershell
pip install -r requirements.txt
```

Local host-only pipeline:

```powershell
python nodeA_host.py --local --wav test_audio.wav
python nodeB.py --local --precision fp32
python nodeC_host.py --local
```

Single-command local run:

```powershell
python run_pipeline.py --wav test_audio.wav --precision fp32 --duration 20 --confidence-threshold 0.30
```

Each pipeline run writes measurement files under `results/run_YYYYMMDD_HHMMSS/` by default. Use `--run-id <name>` to reuse a known folder name or `--no-results` to disable generated CSV/JSON output.

VxWorks Node A to host Node B:

```powershell
python nodeB.py --local --precision fp32
```

## Layout

```text
.
|-- docs/
|   |-- project_spec_v3.md
|   |-- three_node_diagram.mermaid
|   |-- research/
|   |   |-- additional_sources.md
|   |   `-- related_works_research.md
|   |-- results/
|   |   `-- pipelineresults.md
|   `-- setup/
|       |-- node_a_setup_guide.md
|       `-- nodeAsetupchallenges.md
|-- nodeA_host.py
|-- nodeB.py
|-- nodeC_host.py
|-- results_logging.py
|-- run_pipeline.py
|-- udp_proxy.py
|-- generate_test_wav.py
|-- test_listener.py
`-- requirements.txt
```

Generated files such as `venv/`, `__pycache__/`, WAV test audio, and repo-root `results/` experiment logs are ignored by Git.
