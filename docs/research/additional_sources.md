# Additional Related Sources — Baselines, Benchmarks & Performance References

This document supplements `related_works_research.md` with additional sources focused on establishing baselines, benchmarking methodology, and the 150ms latency target justification.

---

## 1. Model Baseline & Accuracy Benchmarks

### wav2vec2-base-superb-ks Baseline
- **Source:** [superb/wav2vec2-base-superb-ks — Hugging Face](https://huggingface.co/superb/wav2vec2-base-superb-ks)
- **Baseline accuracy:** 96.43% on Speech Commands v1.0 (12-class: 10 keywords + silence + unknown)
- **Model:** wav2vec2-base (95M params), pretrained on 16kHz speech audio
- **Why cite:** This is your exact model. The 96.43% accuracy is the baseline you must report before quantization.

### Wav2Keyword (State-of-the-Art wav2vec2 KWS)
- **Source:** [Wav2Keyword — GitHub (qute012)](https://github.com/qute012/Wav2Keyword)
- KWS built on Wav2Vec 2.0, claims SOTA on Speech Commands V1 and V2
- **Why cite:** Shows wav2vec2 architecture is a recognized strong baseline for KWS tasks.

### Speech Commands Dataset
- **Source:** Warden (2018) — already in your related works
- **Additional reference:** [Papers With Code — Keyword Spotting](https://paperswithcode.com/task/keyword-spotting/latest) for leaderboard context

### Recent KWS Baselines (2024-2025)
| Source | Model | Accuracy | Params | Notes |
|--------|-------|----------|--------|-------|
| [Capotondi et al. (2025)](https://arxiv.org/html/2509.07051v1) | TKWS-3 | 92.4% F1 | 14.4K | Full pipeline on STM32 MCUs |
| [NPU-optimized KWS (2025)](https://arxiv.org/html/2506.08911v1) | Quantized CNN on MCUX947 | 97.06% | — | 59x speedup via NPU vs CPU |
| [Lightweight KWS for Robotics (2025)](https://publications.eai.eu/index.php/airo/article/view/7877) | Inter-domain attention | 93.70% | — | Google Commands v2-12 |
| [DNN-based KWS (2025)](https://link.springer.com/article/10.1007/s43674-025-00080-2) | Edge DNN | 94.48% clean / 86.38% noisy | — | Noise robustness benchmarks |
| [Few-shot KWS with wav2vec2 (2025)](https://arxiv.org/html/2506.17686) | Pre-trained SSL | — | — | Extends wav2vec2 to few-shot KWS |

---

## 2. Quantization & Inference Optimization Benchmarks

### ONNX Runtime + TensorRT INT8 Pipeline
- **Source:** [Microsoft — Optimizing Transformer INT8 Inference with ONNX Runtime-TensorRT](https://opensource.microsoft.com/blog/2022/05/02/optimizing-and-deploying-transformer-int8-inference-with-onnx-runtime-tensorrt-on-nvidia-gpus)
- INT8 quantization of transformer models via ONNX → TensorRT achieves **2-4x speedup** with minimal accuracy loss
- Calibration quality is critical — poor calibration can cause >5% accuracy degradation
- **Why cite:** Validates your ONNX export + TensorRT INT8 toolchain choice

### OpenVINO wav2vec2 Quantization Benchmark
- **Source:** [OpenVINO — Quantize Wav2Vec2 using NNCF PTQ API](https://docs.openvino.ai/2024/notebooks/speech-recognition-quantization-wav2vec2-with-output.html)
- Demonstrates INT8 post-training quantization specifically for wav2vec2
- Provides FP32 vs INT8 latency comparison methodology
- **Why cite:** Direct precedent for quantizing the exact model family you use

### TensorRT INT8 Best Practices
- **Source:** [NVIDIA TensorRT Best Practices](https://docs.nvidia.com/deeplearning/tensorrt/latest/performance/best-practices.html)
- Requires Tensor Core hardware (your RTX 5060Ti qualifies)
- `--stronglyTyped` flag ensures strict INT8 adherence
- Example benchmark: 811.74 qps, mean latency 1.23ms for optimized models
- **Why cite:** Establishes your inference engine configuration as following NVIDIA best practices

### ONNX Runtime Quantization Documentation
- **Source:** [ONNX Runtime — Quantize ONNX Models](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
- Documents static vs dynamic quantization, per-tensor vs per-channel
- INT8 typically achieves 2-4x model size reduction + inference speedup
- **Why cite:** Reference for your quantization methodology section

### 40x Faster Inference: ONNX to TensorRT
- **Source:** [GitHub — onnx-tensorrt-optimization](https://github.com/umitkacar/onnx-tensorrt-optimization)
- Reports up to 40x speedup with FP16/INT8 on NVIDIA GPUs
- **Why cite:** Upper-bound reference for what TensorRT optimization can achieve

---

## 3. Real-Time Scheduling for ML Inference (NEW — not in existing related works)

### ML Inference Scheduling with Predictable Latency (2025)
- **Source:** [Zhao et al. (2025) — ArXiv 2512.18725](https://arxiv.org/abs/2512.18725)
- Presented at Middleware for Autonomous AIoT Systems, December 2025
- Focuses on predicting kernel execution interference for GPU utilization while maintaining deadline satisfaction
- **Why cite:** Directly addresses the problem of meeting latency SLOs for ML inference — validates that scheduling for ML pipelines is an active research area

### Timing Guarantees for Inference of AI Models in Embedded Systems (2025)
- **Source:** [Real-Time Systems journal, 2025](https://link.springer.com/article/10.1007/s11241-025-09445-9)
- Published in the premier RT systems journal
- Addresses predictable DNN execution in real-time embedded systems
- Covers strict timing constraints for safety and reliability
- **Why cite:** Authoritative validation that your research question (timing guarantees for DNN inference) is recognized by the RT systems community

### Survey of Real-Time Scheduling on Accelerator-based Heterogeneous Architecture (2025)
- **Source:** [ArXiv 2505.11970](https://arxiv.org/html/2505.11970v1)
- Surveys RT scheduling for GPU/accelerator-based systems
- Covers DART pipeline decomposition for DNN inference tasks
- **Why cite:** Your Node B (GPU inference) fits this heterogeneous scheduling paradigm

### InferLine: Latency-Aware Provisioning for Prediction Serving Pipelines
- **Source:** [Crankshaw et al. — ResearchGate](https://www.researchgate.net/publication/346198787_InferLine_latency-aware_provisioning_and_scaling_for_prediction_serving_pipelines)
- Addresses end-to-end latency SLOs for multi-stage ML inference pipelines
- **Why cite:** Validates your pipeline decomposition approach (audio → inference → actuation)

### Latency Optimized Architectures for Real-Time Inference Pipeline for Control Tasks
- **Source:** [IEEE Xplore](https://ieeexplore.ieee.org/document/9672224/)
- Real-time inference pipeline specifically for control tasks
- **Why cite:** Closest architectural match — inference pipeline feeding a control/actuation stage, similar to your Node C

---

## 4. Fault Tolerance & Dependability (NEW supplements)

### Dependability in Embedded Systems: Survey of Fault Tolerance Methods (2024)
- **Source:** [ArXiv 2404.10509](https://arxiv.org/abs/2404.10509)
- Comprehensive 2024 survey covering watchdog timers, redundancy, hybrid approaches
- Focuses on resource-constrained real-time embedded systems
- **Why cite:** Most current survey of the fault tolerance techniques you implement (watchdog, failsafe)

### Software Fault Tolerance in Real-Time Systems (ACM Computing Surveys)
- **Source:** [ACM Computing Surveys, 2023](https://dl.acm.org/doi/full/10.1145/3589950)
- Identifies future research questions for SW fault tolerance in RT systems
- Covers fail-signal processors, error-detecting codes, watchdogs for timing violations
- **Why cite:** Positions your watchdog + failsafe approach within the broader taxonomy

### Dynamic Fault Tolerance in Distributed Embedded Systems
- **Source:** [PMC/IEEE](https://pmc.ncbi.nlm.nih.gov/articles/PMC9505247/)
- Infrastructure for dynamic fault tolerance in adaptive distributed embedded systems
- Based on switched Ethernet (similar to your UDP/simnet approach)
- **Why cite:** Validates network-based fault detection in distributed embedded architectures

---

## 5. Latency Budget & Pipeline Architecture References

### Voice-to-Voice Latency Pipeline Design
- **Source:** [Modal — One-Second Voice-to-Voice Latency](https://modal.com/blog/low-latency-voice-bot)
- Demonstrates latency budget decomposition across distributed audio pipeline components
- Serial processing exceeds 300ms; parallel streaming is required
- **Why cite:** Validates your timing budget decomposition methodology (D_total = sum of stages)

### Low-Latency Voice AI with Streaming ASR + Quantized Models (2025)
- **Source:** [ArXiv 2508.04721](https://arxiv.org/html/2508.04721v1)
- Combines streaming ASR, quantized LLMs, and real-time TTS for telecom
- Targets sub-300ms end-to-end latency through pipeline parallelism
- **Why cite:** Your 150ms target is even more aggressive — establishes that sub-second audio pipelines require the same techniques you use (quantization + pipelining)

### Real-Time Inference at the Edge
- **Source:** [NexaStack — Designing Low-Latency Pipelines for Real-Time Inference at the Edge](https://www.nexastack.ai/blog/real-time-inference-edge)
- Covers edge inference pipeline design, latency optimization strategies
- **Why cite:** General reference for edge inference pipeline best practices

---

## Summary: How These Sources Strengthen Your Paper

| Gap in Current Related Works | New Sources That Fill It |
|------------------------------|------------------------|
| No baseline accuracy number cited | wav2vec2-base-superb-ks HuggingFace card: **96.43%** |
| No ONNX/TensorRT quantization benchmarks | Microsoft ONNX-TRT blog, OpenVINO wav2vec2 notebook, NVIDIA best practices |
| No RT scheduling papers specific to ML inference | Zhao et al. (2025), RT Systems journal (2025), accelerator scheduling survey |
| No pipeline latency budget precedent | InferLine, IEEE control pipeline, Modal voice pipeline |
| Fault tolerance survey is thin | ArXiv 2024 survey, ACM Computing Surveys, dynamic FT on Ethernet |
| No recent (2024-2025) KWS baselines beyond existing | NPU-optimized KWS, DNN edge KWS, few-shot wav2vec2 KWS |
