"""
nodeA_host.py — Node A Fallback: Audio Sensor as Python Host Process

Replaces VxSim Node A when VxWorks is unavailable. Reads a WAV file,
chunks audio into 1-second clips, and sends them over UDP to Node B.
Same protocol and packet format as the VxWorks version.

Usage:
    python nodeA_host.py                           # random noise, default IPs
    python nodeA_host.py --wav test_audio.wav      # real audio file
    python nodeA_host.py --local                   # use 127.0.0.1 (all on one host)
"""

import argparse
import socket
import struct
import threading
import time
import wave

import numpy as np

# ============================================================
# CONFIGURATION
# ============================================================

NODE_A_IP = "192.168.200.1"
NODE_B_IP = "192.168.200.2"
NODE_B_PORT = 5001

SAMPLE_RATE = 16000
SAMPLES_PER_READ = 160        # 10ms worth at 16kHz
RING_BUF_SIZE = 16000         # 1 second
CHUNK_SIZE = 16000            # 1 second chunk for Wav2Vec2

# Task periods (seconds) — matches VxWorks spec
AUDIO_SAMPLE_PERIOD = 0.010   # 10ms
FEATURE_EXTRACT_PERIOD = 0.020  # 20ms
UDP_TRANSMIT_PERIOD = 0.020   # 20ms

# Task priorities (for logging; Python threads don't have real priorities)
PRIO_AUDIO_SAMPLE = 100
PRIO_FEATURE_EXTRACT = 110
PRIO_UDP_TRANSMIT = 120


# ============================================================
# RING BUFFER
# ============================================================

class RingBuffer:
    """Thread-safe ring buffer for 16-bit audio samples."""

    def __init__(self, capacity=RING_BUF_SIZE):
        self.capacity = capacity
        self.buf = np.zeros(capacity, dtype=np.int16)
        self.head = 0
        self.tail = 0
        self.count = 0
        self.lock = threading.Lock()

    def write(self, samples):
        with self.lock:
            for s in samples:
                self.buf[self.head] = s
                self.head = (self.head + 1) % self.capacity
                if self.count < self.capacity:
                    self.count += 1
                else:
                    self.tail = (self.tail + 1) % self.capacity

    def read_chunk(self, size):
        """Read `size` samples if available, else return None."""
        with self.lock:
            if self.count < size:
                return None
            chunk = np.empty(size, dtype=np.int16)
            for i in range(size):
                chunk[i] = self.buf[(self.tail + i) % self.capacity]
            self.tail = (self.tail + size) % self.capacity
            self.count -= size
            return chunk


# ============================================================
# WAV FILE READER
# ============================================================

class WavReader:
    """Reads 16kHz 16-bit mono WAV, loops on EOF."""

    def __init__(self, path):
        self.path = path
        wf = wave.open(path, "rb")
        assert wf.getsampwidth() == 2, "Expected 16-bit audio"
        assert wf.getnchannels() == 1, "Expected mono audio"
        raw = wf.readframes(wf.getnframes())
        wf.close()
        self.data = np.frombuffer(raw, dtype=np.int16)
        self.pos = 0
        print(f"nodeA: Loaded {path} — {len(self.data)} samples "
              f"({len(self.data)/SAMPLE_RATE:.2f}s)")

    def read(self, num_samples):
        out = np.empty(num_samples, dtype=np.int16)
        remaining = num_samples
        offset = 0
        while remaining > 0:
            avail = min(remaining, len(self.data) - self.pos)
            out[offset:offset + avail] = self.data[self.pos:self.pos + avail]
            self.pos += avail
            offset += avail
            remaining -= avail
            if self.pos >= len(self.data):
                self.pos = 0  # loop
        return out


class NoiseReader:
    """Generates random noise as a fallback when no WAV is provided."""

    def read(self, num_samples):
        return (np.random.randn(num_samples) * 3000).astype(np.int16)


# ============================================================
# NODE A HOST
# ============================================================

class NodeA:
    def __init__(self, wav_path=None, local=False, target_port_override=None):
        self.local = local
        self.target_ip = "127.0.0.1" if local else NODE_B_IP
        self.target_port = target_port_override or NODE_B_PORT
        self.ring = RingBuffer()
        self.chunk_ready = None
        self.chunk_lock = threading.Lock()
        self.seq_num = 0
        self._running = threading.Event()

        # Timing
        self.timing = {"sample": [], "extract": [], "transmit": [], "overruns": []}
        self.stats = {"samples_read": 0, "chunks_sent": 0}

        # Audio source
        if wav_path:
            self.reader = WavReader(wav_path)
        else:
            self.reader = NoiseReader()
            print("nodeA: No WAV file provided, using random noise")

    def _periodic_loop(self, name, func, period):
        while self._running.is_set():
            t_start = time.perf_counter()
            func()
            elapsed = time.perf_counter() - t_start
            sleep_time = period - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                self.timing["overruns"].append((name, elapsed * 1000, period * 1000))

    # ---- Task 1: tAudioSample (10ms) ----
    def _audio_sample(self):
        t_start = time.perf_counter()
        samples = self.reader.read(SAMPLES_PER_READ)
        self.ring.write(samples)
        self.stats["samples_read"] += SAMPLES_PER_READ
        self.timing["sample"].append((time.perf_counter() - t_start) * 1000)

    # ---- Task 2: tFeatureExtract (20ms) ----
    def _feature_extract(self):
        t_start = time.perf_counter()
        chunk = self.ring.read_chunk(CHUNK_SIZE)
        if chunk is not None:
            with self.chunk_lock:
                self.chunk_ready = chunk
        self.timing["extract"].append((time.perf_counter() - t_start) * 1000)

    # ---- Task 3: tUdpTransmit (20ms) ----
    def _udp_transmit(self):
        with self.chunk_lock:
            chunk = self.chunk_ready
            self.chunk_ready = None

        if chunk is None:
            return

        t_start = time.perf_counter()
        ts_us = int(time.perf_counter() * 1_000_000)
        header = struct.pack("<IQ", self.seq_num, ts_us)
        packet = header + chunk.tobytes()

        try:
            self.sock.sendto(packet, (self.target_ip, self.target_port))
        except OSError as e:
            print(f"  nodeA: sendto failed: {e}")

        self.seq_num += 1
        self.stats["chunks_sent"] += 1
        self.timing["transmit"].append((time.perf_counter() - t_start) * 1000)

        if self.seq_num % 10 == 0:
            print(f"  nodeA: sent packet #{self.seq_num} | "
                  f"ring={self.ring.count}/{RING_BUF_SIZE}")

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        print(f"\n{'='*50}")
        print(f"  Node A — Audio Sensor (Host Fallback)")
        print(f"{'='*50}")
        print(f"  Target: {self.target_ip}:{self.target_port}")
        print(f"  Tasks: tAudioSample(10ms) tFeatureExtract(20ms) tUdpTransmit(20ms)")
        print(f"  Press Ctrl+C to stop.\n")

        self._running.set()

        threads = [
            threading.Thread(target=self._periodic_loop,
                             args=("sample", self._audio_sample, AUDIO_SAMPLE_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("extract", self._feature_extract, FEATURE_EXTRACT_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("transmit", self._udp_transmit, UDP_TRANSMIT_PERIOD),
                             daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nnodeA: Shutting down ...")

        self._running.clear()
        time.sleep(0.2)
        self.sock.close()
        self.print_summary()

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  Node A Summary (Host Fallback)")
        print(f"{'='*60}")
        print(f"  Samples read:   {self.stats['samples_read']}")
        print(f"  Chunks sent:    {self.stats['chunks_sent']}")

        for name in ["sample", "extract", "transmit"]:
            vals = self.timing[name]
            if not vals:
                print(f"  {name:<12s}  (no data)")
                continue
            arr = np.array(vals)
            print(f"  {name:<12s}  min={arr.min():.2f}ms  "
                  f"avg={arr.mean():.2f}ms  max={arr.max():.2f}ms  "
                  f"p99={np.percentile(arr, 99):.2f}ms  n={len(arr)}")

        overruns = self.timing["overruns"]
        print(f"  Overruns: {len(overruns)}")
        print(f"{'='*60}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Node A — Audio Sensor (Host Fallback)")
    parser.add_argument("--wav", type=str, default=None,
                        help="WAV file path (16kHz, 16-bit, mono)")
    parser.add_argument("--local", action="store_true",
                        help="Use 127.0.0.1 instead of simnet IPs (all nodes on one host)")
    parser.add_argument("--target-port", type=int, default=None,
                        help="Override target port (e.g. 6001 to send through proxy)")
    args = parser.parse_args()

    node = NodeA(wav_path=args.wav, local=args.local,
                 target_port_override=args.target_port)
    node.run()


if __name__ == "__main__":
    main()
