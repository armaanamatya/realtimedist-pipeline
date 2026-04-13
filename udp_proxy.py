"""
udp_proxy.py — UDP Proxy with Network Impairment Injection

Sits between nodes in the distributed pipeline, forwarding UDP packets with
configurable jitter, packet loss, and bandwidth throttling. Supports two hops:

  Node A -> [Proxy Hop 1] -> Node B -> [Proxy Hop 2] -> Node C

Usage:
    # Baseline (no impairment, just forwarding):
    python udp_proxy.py --mode baseline

    # Moderate stress (5ms jitter, 2% loss):
    python udp_proxy.py --mode moderate

    # Heavy stress (10ms jitter, 10% loss):
    python udp_proxy.py --mode heavy

    # Custom:
    python udp_proxy.py --jitter-mean 5 --jitter-std 3 --loss-pct 2.0

    # Single hop only (e.g., just between A->B):
    python udp_proxy.py --hop1-only --mode moderate

Architecture (full proxy, local mode):
    Node A  ->  :6001 [proxy hop1] -> :5001  Node B
    Node B  ->  :6002 [proxy hop2] -> :5002  Node C

    Node A sends to proxy port 6001 instead of 5001.
    Node B sends to proxy port 6002 instead of 5002.
"""

import argparse
import random
import socket
import struct
import threading
import time
from collections import deque

import numpy as np


# ============================================================
# IMPAIRMENT PROFILES
# ============================================================

PROFILES = {
    "baseline": {"jitter_mean": 0, "jitter_std": 0, "loss_pct": 0.0, "bw_limit_kbps": 0},
    "moderate": {"jitter_mean": 5, "jitter_std": 3, "loss_pct": 2.0, "bw_limit_kbps": 0},
    "heavy":    {"jitter_mean": 10, "jitter_std": 5, "loss_pct": 10.0, "bw_limit_kbps": 0},
    "partition": {"jitter_mean": 0, "jitter_std": 0, "loss_pct": 100.0, "bw_limit_kbps": 0},
}


# ============================================================
# PROXY HOP
# ============================================================

class ProxyHop:
    """Single-direction UDP proxy with impairment injection."""

    def __init__(self, name, listen_port, forward_ip, forward_port,
                 jitter_mean=0, jitter_std=0, loss_pct=0.0, bw_limit_kbps=0):
        self.name = name
        self.listen_port = listen_port
        self.forward_ip = forward_ip
        self.forward_port = forward_port
        self.jitter_mean = jitter_mean
        self.jitter_std = jitter_std
        self.loss_pct = loss_pct
        self.bw_limit_kbps = bw_limit_kbps

        self._running = threading.Event()
        self._thread = None

        # Stats
        self.stats = {
            "forwarded": 0,
            "dropped": 0,
            "total": 0,
            "jitter_applied": [],
        }

    def start(self):
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running.clear()

    def _apply_jitter(self):
        """Return delay in seconds based on jitter config."""
        if self.jitter_mean <= 0 and self.jitter_std <= 0:
            return 0
        delay_ms = max(0, random.gauss(self.jitter_mean, self.jitter_std))
        self.stats["jitter_applied"].append(delay_ms)
        return delay_ms / 1000.0

    def _should_drop(self):
        """Return True if this packet should be dropped."""
        if self.loss_pct <= 0:
            return False
        return random.random() * 100 < self.loss_pct

    def _run(self):
        recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        recv_sock.bind(("0.0.0.0", self.listen_port))
        recv_sock.settimeout(0.1)

        send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        print(f"  proxy/{self.name}: :{self.listen_port} -> "
              f"{self.forward_ip}:{self.forward_port} "
              f"[jitter={self.jitter_mean}±{self.jitter_std}ms, "
              f"loss={self.loss_pct}%]")

        while self._running.is_set():
            try:
                data, addr = recv_sock.recvfrom(65536)
            except socket.timeout:
                continue

            self.stats["total"] += 1

            # Drop?
            if self._should_drop():
                self.stats["dropped"] += 1
                if self.stats["dropped"] % 10 == 1:
                    print(f"  proxy/{self.name}: DROPPED packet "
                          f"(total dropped: {self.stats['dropped']})")
                continue

            # Jitter delay
            delay = self._apply_jitter()
            if delay > 0:
                time.sleep(delay)

            # Forward
            try:
                send_sock.sendto(data, (self.forward_ip, self.forward_port))
                self.stats["forwarded"] += 1
            except OSError as e:
                print(f"  proxy/{self.name}: forward error: {e}")

            if self.stats["forwarded"] % 50 == 0 and self.stats["forwarded"] > 0:
                print(f"  proxy/{self.name}: forwarded {self.stats['forwarded']} "
                      f"(dropped {self.stats['dropped']})")

        recv_sock.close()
        send_sock.close()

    def print_summary(self):
        print(f"\n  {self.name}:")
        print(f"    Total packets:    {self.stats['total']}")
        print(f"    Forwarded:        {self.stats['forwarded']}")
        print(f"    Dropped:          {self.stats['dropped']}")
        if self.stats["jitter_applied"]:
            arr = np.array(self.stats["jitter_applied"])
            print(f"    Jitter applied:   mean={arr.mean():.1f}ms  "
                  f"max={arr.max():.1f}ms  p99={np.percentile(arr, 99):.1f}ms")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="UDP Proxy with network impairment injection")
    parser.add_argument("--mode", choices=list(PROFILES.keys()), default=None,
                        help="Preset impairment profile")
    parser.add_argument("--jitter-mean", type=float, default=None,
                        help="Mean jitter in ms")
    parser.add_argument("--jitter-std", type=float, default=None,
                        help="Jitter std deviation in ms")
    parser.add_argument("--loss-pct", type=float, default=None,
                        help="Packet loss percentage (0-100)")
    parser.add_argument("--hop1-only", action="store_true",
                        help="Only proxy hop 1 (Node A -> Node B)")
    parser.add_argument("--hop2-only", action="store_true",
                        help="Only proxy hop 2 (Node B -> Node C)")

    # Port overrides for flexibility
    parser.add_argument("--hop1-listen", type=int, default=6001,
                        help="Proxy listen port for hop 1 (default: 6001)")
    parser.add_argument("--hop1-forward-port", type=int, default=5001,
                        help="Forward port for hop 1 (default: 5001, Node B)")
    parser.add_argument("--hop2-listen", type=int, default=6002,
                        help="Proxy listen port for hop 2 (default: 6002)")
    parser.add_argument("--hop2-forward-port", type=int, default=5002,
                        help="Forward port for hop 2 (default: 5002, Node C)")

    args = parser.parse_args()

    # Resolve impairment config
    if args.mode:
        profile = PROFILES[args.mode]
    else:
        profile = PROFILES["baseline"]

    # Custom overrides take precedence
    jitter_mean = args.jitter_mean if args.jitter_mean is not None else profile["jitter_mean"]
    jitter_std = args.jitter_std if args.jitter_std is not None else profile["jitter_std"]
    loss_pct = args.loss_pct if args.loss_pct is not None else profile["loss_pct"]

    print(f"\n{'='*50}")
    print(f"  UDP Proxy — Network Impairment Injector")
    print(f"{'='*50}")
    print(f"  Profile:     {args.mode or 'custom'}")
    print(f"  Jitter:      {jitter_mean}±{jitter_std} ms")
    print(f"  Packet loss: {loss_pct}%")
    print()

    hops = []

    if not args.hop2_only:
        hop1 = ProxyHop(
            name="hop1 (A->B)",
            listen_port=args.hop1_listen,
            forward_ip="127.0.0.1",
            forward_port=args.hop1_forward_port,
            jitter_mean=jitter_mean,
            jitter_std=jitter_std,
            loss_pct=loss_pct,
        )
        hops.append(hop1)

    if not args.hop1_only:
        hop2 = ProxyHop(
            name="hop2 (B->C)",
            listen_port=args.hop2_listen,
            forward_ip="127.0.0.1",
            forward_port=args.hop2_forward_port,
            jitter_mean=jitter_mean,
            jitter_std=jitter_std,
            loss_pct=loss_pct,
        )
        hops.append(hop2)

    for h in hops:
        h.start()

    print(f"\n  Proxy running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nProxy: Shutting down ...")

    for h in hops:
        h.stop()
    time.sleep(0.2)

    print(f"\n{'='*60}")
    print(f"  Proxy Summary")
    print(f"{'='*60}")
    for h in hops:
        h.print_summary()
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
