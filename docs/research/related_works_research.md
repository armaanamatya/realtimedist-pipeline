# Related Works — Research Summary

This document organizes the relevant literature into four areas that map directly to your project's contributions. Use this as a reference when writing the Related Work section of your paper.

---

## 1. Embedded Keyword Spotting (KWS) and Edge Inference

This is the NLP/ML side of your project — running speech classification models on resource-constrained platforms.

### Key Papers

**Liu & Layland (1973)** — "Scheduling Algorithms for Multiprogramming in a Hard Real-Time Environment." The foundational paper for RMS and EDF. You cite this for the utilization bound test (U ≤ n(2^(1/n)-1) for RMS) and the EDF optimality result (U ≤ 1.0). Every RT systems paper cites this.

**Warden (2018)** — "Speech Commands: A Dataset for Limited-Vocabulary Speech Recognition." This is the Google Speech Commands dataset your wav2vec2 model was trained on. Cite it to establish the benchmark.

**Zhang et al. (2017)** — "Hello Edge: Keyword Spotting on Microcontrollers" (DS-CNN paper from ARM). This introduced depthwise separable CNNs (DS-CNNs) for on-device KWS, achieving 95.4% accuracy on Speech Commands. Important because it established the standard architecture family for embedded KWS. Your project extends this line of work by examining how model precision (FP32 vs INT8) affects real-time schedulability, not just accuracy.

**Paissan et al. (2023)** — "Improving latency performance trade-off in keyword spotting applications at the edge." Published at IEEE ICASSP 2023. They used hardware-aware scaling (HAS) to optimize KWS networks for microcontrollers, achieving 94.5% accuracy with 70ms latency. Directly relevant because they tackle the same latency-accuracy tradeoff you're measuring, but they focus on single-node optimization while you examine the distributed pipeline.

**Cioflan et al. (2024)** — "On-Device Domain Learning for Keyword Spotting on Low-Power Extreme Edge Embedded Systems." Published at IEEE, 2024. They implement on-device domain adaptation for KWS on GAP9 MCU using DS-CNN models with INT8 quantization. Relevant for the quantization angle — they show INT8 KWS models can achieve accuracy within 3% of FP32 while dramatically reducing latency.

**Alhashimi & Aliedani (2025)** — "Embedded Device Keyword Spotting Model with Quantized ConvNets." Published in IJETT, 2025. They compare a custom quantized CNN (QCoNet, 96.7% accuracy) against MobileNet v4 (99.2%) for Arabic KWS on microcontrollers. Useful for citing the accuracy-vs-resource tradeoff in quantized KWS models.

**Capotondi et al. (2025)** — "End-to-End Efficiency in Keyword Spotting: A System-Level Approach for Embedded Microcontrollers." ArXiv 2025. They evaluate the *entire pipeline* (MFCC extraction + CNN inference) across three STM32 platforms, not just model inference in isolation. Their TKWS-3 model achieves 92.4% F1 with only 14.4K parameters. Highly relevant because they take the same system-level perspective you do, but on a single node rather than distributed.

### How Your Project Extends This Literature

Most KWS papers focus on single-node optimization (smaller models, lower latency, less memory). Your project is novel because it examines KWS within a distributed real-time pipeline where the scheduling feasibility — not just model accuracy — determines whether the system meets its deadline. The key insight (FP32 fails RMS bound, INT8 passes) bridges the ML and RT scheduling communities.

---

## 2. Real-Time Scheduling in Distributed Systems

This is the core RT theory behind your project.

### Key Papers

**Liu & Layland (1973)** — (Same as above.) RMS and EDF foundations. The utilization bounds you compute for each node come directly from this paper.

**Buttazzo (2011)** — "Hard Real-Time Computing Systems: Predictable Scheduling Algorithms and Applications" (3rd edition, Springer). The standard textbook. Chapters on response time analysis, jitter analysis, and distributed scheduling are directly applicable. Cite for WCRT analysis methodology.

**Hong & Shin (2015)** — "Local-Deadline Assignment for Distributed Real-Time Systems." Published in IEEE Transactions on Parallel and Distributed Systems. They address the problem of decomposing an end-to-end deadline into per-node local deadlines in a distributed pipeline — exactly your D_total = D_sample + D_feature + D_net + D_inference + D_net + D_actuate decomposition. Their WLDA algorithm outperforms existing methods by 51-313% in feasible jobs.

**Park et al. (2014)** — "Effective Real-Time Scheduling Algorithm for Cyber Physical Systems Society." Published in Future Generation Computer Systems. They propose ELST and H-ELST scheduling algorithms for CPS with distributed nodes, reducing deadline miss ratio by up to 50% compared to FIFO. Relevant because they model the same class of distributed CPS you're building, though they focus on mobile servicing nodes rather than pipelined inference.

**Saifullah et al. (2021)** — "DistributedHART: A Distributed Real-Time Scheduling System for WirelessHART Networks." Published in ACM TECS. They address real-time scheduling in industrial wireless IoT networks with redundancy for reliability. Relevant for the distributed scheduling + fault tolerance combination.

**Kopetz (2011)** — "Real-Time Systems: Design Principles for Distributed Embedded Applications" (Springer). The time-triggered architecture (TTA) book. Useful for citing the theoretical framework of distributed real-time communication and clock synchronization.

### How Your Project Extends This Literature

Most distributed RT scheduling papers analyze abstract task sets. Your project grounds the analysis in a concrete NLP inference pipeline where the WCET of the inference task (Node B) depends on the model precision — a variable the traditional RT literature doesn't consider. The adaptive scheduling extension (dynamically switching FP32→INT8 when utilization exceeds a threshold) connects model compression to runtime schedulability in a way that hasn't been explored.

---

## 3. Model Quantization and Inference Optimization

This covers the FP32 vs INT8 comparison and its real-time implications.

### Key Papers

**NVIDIA TensorRT Documentation / Blog (2021-2023)** — "Achieving FP32 Accuracy for INT8 Inference Using Quantization Aware Training with TensorRT." Describes PTQ (post-training quantization) and QAT workflows. Cite for the toolchain you use to export and quantize the wav2vec2 model.

**van Baalen et al. (2023)** — "FP8 versus INT8 for Efficient Deep Learning Inference." ArXiv whitepaper from Qualcomm. Comprehensive comparison of number formats for inference. They show INT8 with QAT rarely fails to match FP32 accuracy, and that INT8 is at least 50% more hardware-efficient than FP8 in dedicated silicon. Useful for justifying your INT8 choice.

**Ghosh (2026)** — "Edge AI for Real-Time Robotic Systems." Published 2026. They demonstrate INT8 quantization achieving 3x speedup with under 2% accuracy loss on NVIDIA Jetson for robotic control, with total pipeline latencies under 20ms. Directly relevant because they measure the same kind of edge inference pipeline latency you do, in a safety-critical robotic context.

**Nagel et al. (2021)** — "A White Paper on Neural Network Quantization." ArXiv, Qualcomm AI Research. The go-to survey on quantization methods. Covers uniform vs non-uniform quantization, per-tensor vs per-channel scaling, and the accuracy-efficiency tradeoff. Cite for background.

### How Your Project Extends This Literature

Quantization papers typically measure latency and accuracy in isolation. Your project measures how quantization changes schedulability — whether a task set that fails RMS with FP32 passes with INT8. This reframes quantization as a real-time systems design decision, not just an ML optimization.

---

## 4. Fault Tolerance and Watchdog Mechanisms in Embedded Systems

This covers your watchdog timer, node crash recovery, and failsafe experiments.

### Key Papers

**Mehalaine et al. (2024)** — "Watchdog Timer for Fault Tolerance in Embedded Systems." Published in JESA (IIETA), 2024. They propose a fault-tolerant scheduling algorithm combining watchdog timers with EDF for hard real-time periodic tasks on distributed processors. Very directly relevant — they combine the same two mechanisms (watchdog + EDF) you use on Node C. Their approach handles processor faults and task rescheduling.

**Ramanathan & Shin (1992)** — "Delivery of Time-Critical Messages Using a Multiple Copy Approach." Published in ACM TOCS. They address delivering critical messages before deadlines in distributed RT systems with processor/link failures using active replication. Relevant for your packet loss experiments — the question of how many redundant transmissions you need to guarantee delivery within the deadline.

**Chevochot & Puaut (1999)** — "Scheduling Fault-Tolerant Distributed Hard Real-Time Tasks Independently of the Replication Strategies." Published at IEEE RTCSA. They developed HYDRA, a replication framework that integrates active, passive, or hybrid replication into RT scheduling. Relevant as a more sophisticated fault tolerance approach that your watchdog-based method could be compared against.

**Reghenzani et al. (cited in Mehalaine 2024)** — Work on Software-Implemented Fault Tolerance (SIFT) mechanisms and their interaction with real-time scheduling. They model failure probabilities per task and analyze impact on timing guarantees.

### How Your Project Extends This Literature

Your watchdog implementation is deliberately simple (heartbeat monitoring + failsafe actuation) because the focus is on measuring the detection-to-recovery latency and its interaction with the end-to-end deadline. The fault injection framework (packet loss, node crash, CPU overload, audio noise) provides empirical data on system behavior under stress, complementing the theoretical analyses in the papers above.

---

## Summary Table: Related Work → Your Contribution

| Area | What Literature Does | What You Add |
|------|---------------------|--------------|
| Embedded KWS | Optimizes single-node model size/latency/accuracy | Examines KWS in a distributed RT pipeline where scheduling feasibility depends on model precision |
| RT Scheduling | Analyzes abstract task sets with fixed WCETs | WCET varies with model quantization level; adaptive scheduling switches precision at runtime |
| Quantization | Measures latency/accuracy tradeoff in isolation | Measures impact on RMS/EDF schedulability bounds across a multi-node pipeline |
| Fault Tolerance | Theoretical frameworks for replication and recovery | Empirical fault injection (noise, packet loss, node crash) with measured recovery latencies |

---

## Suggested Citation Format for Paper

When writing the Related Work section, organize it into three subsections:

**2.1 Keyword Spotting on Embedded Platforms** — Zhang et al. (Hello Edge), Paissan et al. (HAS), Cioflan et al. (on-device adaptation), Capotondi et al. (end-to-end MCU pipeline), Warden (Speech Commands dataset), wav2vec2 SUPERB benchmark.

**2.2 Real-Time Scheduling for Distributed CPS** — Liu & Layland (RMS/EDF), Buttazzo (textbook), Hong & Shin (local deadline assignment), Park et al. (CPS scheduling), Saifullah et al. (DistributedHART).

**2.3 Fault Tolerance in Safety-Critical Embedded Systems** — Mehalaine et al. (watchdog + EDF), Ramanathan & Shin (message replication), Chevochot & Puaut (HYDRA replication framework).

Keep it to ~0.75 pages. Each citation should say what the paper does and how your work differs or extends it in one sentence.
