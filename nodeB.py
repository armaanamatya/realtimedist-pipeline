"""
nodeB.py — Node B: NLP Inference Host Process (Narrow Scope: FP32 vs FP16)

Receives UDP audio packets from Node A (VxSim), runs wav2vec2 keyword spotting
inference on GPU, and forwards classified commands to Node C via UDP.

Usage:
    python nodeB.py --precision fp32              # production mode, FP32
    python nodeB.py --precision fp16              # production mode, FP16
    python nodeB.py --test --precision fp32       # test mode with mock packets
    python nodeB.py --test --test-wav stop.wav    # test with real audio file
"""

import argparse
import csv
import io
import socket
import struct
import sys
import threading
import time
from queue import Queue, Empty

import numpy as np

# ============================================================
# CONFIGURATION
# ============================================================

# Network
NODE_B_IP = "192.168.200.2"
NODE_B_PORT = 5001
NODE_C_IP = "192.168.200.3"
NODE_C_PORT = 5002

# Audio
SAMPLE_RATE = 16000
CLIP_SAMPLES = 16000  # 1 second at 16kHz

# Model
MODEL_NAME = "superb/wav2vec2-base-superb-ks"
CONFIDENCE_THRESHOLD = 0.85
COMMAND_LABELS = {"stop", "go"}

# Task periods (seconds)
RECV_PERIOD = 0.020   # 20ms
INFER_PERIOD = 0.050  # 50ms
SEND_PERIOD = 0.020   # 20ms


# ============================================================
# AUDIO BUFFER
# ============================================================

class AudioBuffer:
    """Thread-safe sliding buffer that accumulates chunks until 1s of audio."""

    def __init__(self, clip_samples=CLIP_SAMPLES):
        self._clip_samples = clip_samples
        self._buffer = np.zeros(clip_samples, dtype=np.float32)
        self._write_pos = 0
        self._lock = threading.Lock()
        self._latest_seq = 0
        self._latest_ts = 0

    def append(self, samples, seq_num, timestamp_us):
        """Append float32 audio samples to the buffer."""
        with self._lock:
            n = len(samples)
            space = self._clip_samples - self._write_pos
            if n <= space:
                self._buffer[self._write_pos:self._write_pos + n] = samples
                self._write_pos += n
            else:
                # Fill remaining space, discard oldest
                self._buffer[self._write_pos:] = samples[:space]
                self._write_pos = self._clip_samples
            self._latest_seq = seq_num
            self._latest_ts = timestamp_us

    def get_clip(self):
        """Return (waveform, seq_num, timestamp) if full clip available, else None."""
        with self._lock:
            if self._write_pos < self._clip_samples:
                return None
            clip = self._buffer.copy()
            self._write_pos = 0
            return clip, self._latest_seq, self._latest_ts


# ============================================================
# NODE B
# ============================================================

class NodeB:
    def __init__(self, precision="fp32", test_mode=False, test_wav=None, log_file=None, local=False):
        self.precision = precision
        self.test_mode = test_mode
        self.test_wav = test_wav
        self.log_file = log_file
        self.local = local

        self.audio_buffer = AudioBuffer()
        self.result_queue = Queue()
        self._running = threading.Event()

        # Timing logs
        self.timing = {
            "recv": [],
            "inference": [],
            "send": [],
            "e2e": [],
            "overruns": [],
        }
        self.stats = {
            "packets_recv": 0,
            "inferences_run": 0,
            "commands_sent": 0,
        }

        # CSV writer
        self._csv_file = None
        self._csv_writer = None

        # Model (loaded in load_model)
        self.model = None
        self.feature_extractor = None
        self.device = None

    def load_model(self):
        """Load wav2vec2 model and warm up GPU."""
        import torch
        from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForSequenceClassification

        print(f"nodeB: Loading model {MODEL_NAME} ...")
        print(f"nodeB: Precision = {self.precision.upper()}")

        self.feature_extractor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_NAME)
        self.model = Wav2Vec2ForSequenceClassification.from_pretrained(MODEL_NAME)

        # Device selection
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            print(f"nodeB: Using GPU — {torch.cuda.get_device_name(0)}")
        else:
            self.device = torch.device("cpu")
            print("nodeB: WARNING — CUDA not available, using CPU")

        # Apply precision
        if self.precision == "fp16":
            try:
                self.model = self.model.half()
                print("nodeB: Model converted to FP16")
            except Exception as e:
                print(f"nodeB: WARNING — .half() failed ({e}), will use autocast")
                self.precision = "fp16-autocast"

        self.model = self.model.to(self.device).eval()

        # Warm-up inference to avoid cold-start skew
        print("nodeB: Running warm-up inference ...")
        dummy = np.zeros(CLIP_SAMPLES, dtype=np.float32)
        self._run_inference(dummy)
        print("nodeB: Warm-up complete.\n")

    def _run_inference(self, waveform):
        """Run inference on a 1-second float32 waveform. Returns (label, confidence)."""
        import torch

        inputs = self.feature_extractor(
            waveform, sampling_rate=SAMPLE_RATE, return_tensors="pt"
        )
        input_values = inputs.input_values.to(self.device)

        if self.precision == "fp16":
            input_values = input_values.half()

        with torch.no_grad():
            if self.precision == "fp16-autocast":
                with torch.cuda.amp.autocast():
                    logits = self.model(input_values).logits
            else:
                logits = self.model(input_values).logits

        probs = torch.nn.functional.softmax(logits, dim=-1)
        top_prob, top_idx = probs.topk(1)
        label = self.model.config.id2label[top_idx.item()]
        confidence = top_prob.item()
        return label, confidence

    # ---- Periodic task helper ----

    def _periodic_loop(self, name, func, period):
        """Run func() every `period` seconds, logging overruns."""
        while self._running.is_set():
            t_start = time.perf_counter()
            func()
            elapsed = time.perf_counter() - t_start
            sleep_time = period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                self.timing["overruns"].append((name, elapsed * 1000, period * 1000))

    # ---- Task 1: recv_features (20ms) ----

    def _recv_features(self):
        try:
            data, addr = self._recv_sock.recvfrom(65536)
        except socket.timeout:
            return

        t_start = time.perf_counter()

        if len(data) < 12:
            return

        seq_num = struct.unpack("<I", data[0:4])[0]
        timestamp_us = struct.unpack("<Q", data[4:12])[0]
        audio_bytes = data[12:]
        samples = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        self.audio_buffer.append(samples, seq_num, timestamp_us)
        self.stats["packets_recv"] += 1

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        self.timing["recv"].append(elapsed_ms)

    # ---- Task 2: kws_inference (50ms) ----

    def _kws_inference(self):
        clip_data = self.audio_buffer.get_clip()
        if clip_data is None:
            return

        waveform, seq_num, origin_ts = clip_data

        t_start = time.perf_counter()
        label, confidence = self._run_inference(waveform)
        infer_ms = (time.perf_counter() - t_start) * 1000

        self.timing["inference"].append(infer_ms)
        self.stats["inferences_run"] += 1

        # Map label to command
        if label in COMMAND_LABELS and confidence > CONFIDENCE_THRESHOLD:
            command = label.upper()
            forward = True
        else:
            command = "NONE"
            forward = False

        print(f"  inference: {label:<10s} conf={confidence:.3f} "
              f"time={infer_ms:.1f}ms cmd={command} fwd={forward}")

        if forward:
            self.result_queue.put((seq_num, origin_ts, command, confidence, infer_ms))

    # ---- Task 3: send_result (20ms) ----

    def _send_result(self):
        try:
            seq_num, origin_ts, command, confidence, infer_ms = \
                self.result_queue.get(timeout=0.005)
        except Empty:
            return

        t_start = time.perf_counter()

        # Pack outbound packet: [seq:4][ts:8][cmd:16][conf:4] = 32 bytes
        cmd_bytes = command.encode("utf-8").ljust(16, b"\x00")
        packet = struct.pack("<IQ", seq_num, origin_ts) + cmd_bytes + \
                 struct.pack("<f", confidence)

        try:
            target_ip = "127.0.0.1" if self.local else NODE_C_IP
            self._send_sock.sendto(packet, (target_ip, NODE_C_PORT))
        except OSError:
            pass  # Node C may not be running yet

        send_ms = (time.perf_counter() - t_start) * 1000
        self.timing["send"].append(send_ms)
        self.stats["commands_sent"] += 1

        # End-to-end: from original Node A timestamp to now
        now_us = int(time.perf_counter() * 1_000_000)
        # Note: e2e across clock domains is approximate
        self.timing["e2e"].append(infer_ms + send_ms)

        # CSV log
        if self._csv_writer:
            self._csv_writer.writerow([
                seq_num, f"{infer_ms:.2f}", f"{send_ms:.2f}",
                f"{infer_ms + send_ms:.2f}", command, f"{confidence:.4f}",
                self.precision
            ])

    # ---- Main run loop ----

    def run(self):
        """Start all threads and run until KeyboardInterrupt."""
        # Setup sockets
        bind_ip = "0.0.0.0" if (self.test_mode or self.local) else NODE_B_IP
        send_ip = "127.0.0.1" if self.local else NODE_C_IP
        self._recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._recv_sock.bind((bind_ip, NODE_B_PORT))
        self._recv_sock.settimeout(0.1)

        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print(f"nodeB: Listening on {bind_ip}:{NODE_B_PORT}")
        print(f"nodeB: Sending to {send_ip}:{NODE_C_PORT}")

        # CSV log file
        if self.log_file:
            self._csv_file = open(self.log_file, "w", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            self._csv_writer.writerow([
                "seq_num", "infer_ms", "send_ms", "total_ms",
                "command", "confidence", "precision"
            ])

        # Start mock sender if test mode
        mock = None
        if self.test_mode:
            mock = MockNodeA(
                target_ip="127.0.0.1",
                target_port=NODE_B_PORT,
                wav_path=self.test_wav,
            )
            mock.start()

        self._running.set()

        threads = [
            threading.Thread(target=self._periodic_loop,
                             args=("recv", self._recv_features, RECV_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("inference", self._kws_inference, INFER_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("send", self._send_result, SEND_PERIOD),
                             daemon=True),
        ]

        for t in threads:
            t.start()

        print("nodeB: All tasks running. Press Ctrl+C to stop.\n")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nnodeB: Shutting down ...")

        self._running.clear()
        if mock:
            mock.stop()
        time.sleep(0.2)

        self._recv_sock.close()
        self._send_sock.close()
        if self._csv_file:
            self._csv_file.close()

        self.print_summary()

    def print_summary(self):
        """Print timing statistics."""
        print("\n" + "=" * 60)
        print(f"  Node B Summary — Precision: {self.precision.upper()}")
        print("=" * 60)
        print(f"  Packets received:    {self.stats['packets_recv']}")
        print(f"  Inferences run:      {self.stats['inferences_run']}")
        print(f"  Commands forwarded:  {self.stats['commands_sent']}")
        print()

        for name in ["recv", "inference", "send"]:
            vals = self.timing[name]
            if not vals:
                print(f"  {name:<12s}  (no data)")
                continue
            arr = np.array(vals)
            print(f"  {name:<12s}  min={arr.min():.2f}ms  "
                  f"avg={arr.mean():.2f}ms  max={arr.max():.2f}ms  "
                  f"p99={np.percentile(arr, 99):.2f}ms  n={len(arr)}")

        overruns = self.timing["overruns"]
        if overruns:
            print(f"\n  Overruns: {len(overruns)} total")
            for task_name in ["recv", "inference", "send"]:
                count = sum(1 for o in overruns if o[0] == task_name)
                if count:
                    print(f"    {task_name}: {count}")
        else:
            print("\n  Overruns: 0")
        print("=" * 60)


# ============================================================
# MOCK NODE A (test mode)
# ============================================================

class MockNodeA:
    """Sends fake audio packets on loopback for testing without VxSim."""

    def __init__(self, target_ip="127.0.0.1", target_port=NODE_B_PORT,
                 wav_path=None, chunk_ms=20):
        self.target_ip = target_ip
        self.target_port = target_port
        self.chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)  # 320 samples
        self._running = threading.Event()
        self._thread = None

        # Load audio source
        if wav_path:
            self._load_wav(wav_path)
        else:
            # Generate 1s of random noise repeated
            self.audio_data = np.random.randn(SAMPLE_RATE).astype(np.float32) * 0.1
            print(f"mockNodeA: Using random noise (no --test-wav provided)")

    def _load_wav(self, path):
        """Load a WAV file as float32 samples."""
        try:
            import wave
            with wave.open(path, "rb") as wf:
                assert wf.getsampwidth() == 2, "Expected 16-bit audio"
                assert wf.getnchannels() == 1, "Expected mono audio"
                raw = wf.readframes(wf.getnframes())
                self.audio_data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                print(f"mockNodeA: Loaded {path} — {len(self.audio_data)} samples "
                      f"({len(self.audio_data)/SAMPLE_RATE:.2f}s)")
        except Exception as e:
            print(f"mockNodeA: WARNING — failed to load {path}: {e}")
            print(f"mockNodeA: Falling back to random noise")
            self.audio_data = np.random.randn(SAMPLE_RATE).astype(np.float32) * 0.1

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        seq = 0
        pos = 0
        period = self.chunk_samples / SAMPLE_RATE  # 0.02s = 20ms

        print(f"mockNodeA: Sending to {self.target_ip}:{self.target_port} "
              f"every {period*1000:.0f}ms")

        while self._running.is_set():
            t_start = time.perf_counter()

            # Get chunk, wrap around
            end = pos + self.chunk_samples
            if end <= len(self.audio_data):
                chunk = self.audio_data[pos:end]
            else:
                chunk = np.concatenate([
                    self.audio_data[pos:],
                    self.audio_data[:end - len(self.audio_data)]
                ])
            pos = end % len(self.audio_data)

            # Convert to 16-bit PCM bytes (matching Node A format)
            pcm = (chunk * 32768.0).clip(-32768, 32767).astype(np.int16)
            ts_us = int(time.perf_counter() * 1_000_000)

            # Pack: [seq:4][ts:8][audio:variable]
            header = struct.pack("<IQ", seq, ts_us)
            packet = header + pcm.tobytes()

            try:
                sock.sendto(packet, (self.target_ip, self.target_port))
            except OSError:
                pass

            seq += 1
            if seq % 50 == 0:
                print(f"  mockNodeA: sent {seq} packets")

            elapsed = time.perf_counter() - t_start
            sleep_time = period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        sock.close()
        print("mockNodeA: Stopped.")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Node B — NLP Inference Host")
    parser.add_argument("--precision", choices=["fp32", "fp16"], default="fp32",
                        help="Model precision (default: fp32)")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: use mock packets on loopback")
    parser.add_argument("--test-wav", type=str, default=None,
                        help="WAV file for test mode (16kHz, 16-bit, mono)")
    parser.add_argument("--log-file", type=str, default=None,
                        help="CSV log file path for timing data")
    parser.add_argument("--local", action="store_true",
                        help="Use 127.0.0.1 instead of simnet IPs (all nodes on one host)")
    args = parser.parse_args()

    node = NodeB(
        precision=args.precision,
        test_mode=args.test,
        test_wav=args.test_wav,
        log_file=args.log_file,
        local=args.local,
    )
    node.load_model()
    node.run()


if __name__ == "__main__":
    main()
