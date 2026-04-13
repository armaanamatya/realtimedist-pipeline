"""
nodeC_host.py — Node C Fallback: Actuator Control as Python Host Process

Replaces VxSim Node C when VxWorks is unavailable. Receives classified
commands from Node B via UDP, applies safety validation (debounce),
runs a watchdog timer, and logs actuator triggers.

Usage:
    python nodeC_host.py                  # default simnet IPs
    python nodeC_host.py --local          # use 127.0.0.1 (all on one host)
"""

import argparse
import socket
import struct
import threading
import time

import numpy as np

# ============================================================
# CONFIGURATION
# ============================================================

NODE_C_IP = "192.168.200.3"
NODE_C_PORT = 5002

# Safety parameters (from project spec)
DEBOUNCE_COUNT = 2            # consecutive "stop" commands required
DEBOUNCE_WINDOW_MS = 2000     # within this time window (accounts for 1s inference cadence)
WATCHDOG_TIMEOUT_MS = 3000    # failsafe if no packet in this time (>2x inference cadence)

# Task periods (seconds)
RECV_PERIOD = 0.020           # 20ms — tUdpReceive (sporadic, but we poll)
VALIDATE_PERIOD = 0.020       # 20ms — tSafetyValidate
WATCHDOG_PERIOD = 0.100       # 100ms — tWatchdog


# ============================================================
# NODE C HOST
# ============================================================

class NodeC:
    def __init__(self, local=False):
        self.local = local
        self.bind_ip = "0.0.0.0" if local else NODE_C_IP
        self._running = threading.Event()

        # Received commands queue
        self._recv_lock = threading.Lock()
        self._pending_commands = []

        # Debounce state
        self._stop_times = []       # timestamps of recent "STOP" commands
        self._actuator_state = "IDLE"
        self._last_trigger_time = 0

        # Watchdog
        self._last_packet_time = time.perf_counter()
        self._watchdog_triggered = False

        # Timing & stats
        self.timing = {"recv": [], "validate": [], "watchdog": [], "overruns": []}
        self.stats = {
            "packets_recv": 0,
            "stop_commands": 0,
            "go_commands": 0,
            "actuator_triggers": 0,
            "watchdog_failsafes": 0,
        }

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

    # ---- Task 1: tUdpReceive (sporadic, polled at 20ms) ----
    def _udp_receive(self):
        try:
            data, addr = self.sock.recvfrom(1024)
        except socket.timeout:
            return

        t_start = time.perf_counter()
        self._last_packet_time = t_start
        self._watchdog_triggered = False

        # Parse: [seq:4][ts:8][cmd:16][conf:4] = 32 bytes
        if len(data) < 32:
            print(f"  nodeC: WARNING — short packet ({len(data)} bytes)")
            return

        seq_num = struct.unpack("<I", data[0:4])[0]
        timestamp_us = struct.unpack("<Q", data[4:12])[0]
        command = data[12:28].rstrip(b"\x00").decode("utf-8", errors="replace")
        confidence = struct.unpack("<f", data[28:32])[0]

        self.stats["packets_recv"] += 1

        with self._recv_lock:
            self._pending_commands.append({
                "seq": seq_num,
                "ts": timestamp_us,
                "cmd": command,
                "conf": confidence,
                "recv_time": t_start,
            })

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        self.timing["recv"].append(elapsed_ms)

        print(f"  nodeC: recv #{seq_num} cmd={command} conf={confidence:.3f}")

    # ---- Task 2: tSafetyValidate (20ms) ----
    def _safety_validate(self):
        t_start = time.perf_counter()

        with self._recv_lock:
            commands = self._pending_commands[:]
            self._pending_commands.clear()

        now = time.perf_counter()

        for cmd_info in commands:
            command = cmd_info["cmd"]

            if command == "STOP":
                self.stats["stop_commands"] += 1
                self._stop_times.append(cmd_info["recv_time"])

                # Debounce: need DEBOUNCE_COUNT "STOP" within DEBOUNCE_WINDOW_MS
                window_start = now - (DEBOUNCE_WINDOW_MS / 1000.0)
                recent = [t for t in self._stop_times if t >= window_start]
                self._stop_times = recent  # prune old entries

                if len(recent) >= DEBOUNCE_COUNT:
                    self._trigger_actuator("EMERGENCY_STOP", cmd_info)
                    self._stop_times.clear()

            elif command == "GO":
                self.stats["go_commands"] += 1
                self._trigger_actuator("GO", cmd_info)

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        self.timing["validate"].append(elapsed_ms)

    def _trigger_actuator(self, action, cmd_info):
        """Log actuator trigger (VxSim has no physical GPIO — we log it)."""
        now = time.perf_counter()
        self._actuator_state = action
        self._last_trigger_time = now
        self.stats["actuator_triggers"] += 1

        # Calculate latency from Node A timestamp
        e2e_note = ""
        if cmd_info.get("ts"):
            # Note: cross-clock-domain, approximate
            recv_delay_ms = (cmd_info["recv_time"] - now) * 1000  # will be negative
            e2e_note = f" (processing={abs(recv_delay_ms):.1f}ms)"

        print(f"\n  *** ACTUATOR: {action} *** "
              f"(seq={cmd_info['seq']} conf={cmd_info['conf']:.3f}){e2e_note}\n")

    # ---- Task 3: tWatchdog (100ms) ----
    def _watchdog(self):
        t_start = time.perf_counter()
        elapsed_since_last = (t_start - self._last_packet_time) * 1000

        if elapsed_since_last > WATCHDOG_TIMEOUT_MS and not self._watchdog_triggered:
            self._watchdog_triggered = True
            self.stats["watchdog_failsafes"] += 1
            self._actuator_state = "FAILSAFE_STOP"
            print(f"\n  *** WATCHDOG FAILSAFE *** "
                  f"No packet in {elapsed_since_last:.0f}ms — triggering emergency stop\n")

        self.timing["watchdog"].append((time.perf_counter() - t_start) * 1000)

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, NODE_C_PORT))
        self.sock.settimeout(0.01)

        print(f"\n{'='*50}")
        print(f"  Node C — Actuator Control (Host Fallback)")
        print(f"{'='*50}")
        print(f"  Listening: {self.bind_ip}:{NODE_C_PORT}")
        print(f"  Debounce: {DEBOUNCE_COUNT} consecutive STOP within {DEBOUNCE_WINDOW_MS}ms")
        print(f"  Watchdog: failsafe after {WATCHDOG_TIMEOUT_MS}ms silence")
        print(f"  Press Ctrl+C to stop.\n")

        self._running.set()
        self._last_packet_time = time.perf_counter()

        threads = [
            threading.Thread(target=self._periodic_loop,
                             args=("recv", self._udp_receive, RECV_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("validate", self._safety_validate, VALIDATE_PERIOD),
                             daemon=True),
            threading.Thread(target=self._periodic_loop,
                             args=("watchdog", self._watchdog, WATCHDOG_PERIOD),
                             daemon=True),
        ]
        for t in threads:
            t.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nnodeC: Shutting down ...")

        self._running.clear()
        time.sleep(0.2)
        self.sock.close()
        self.print_summary()

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  Node C Summary (Host Fallback)")
        print(f"{'='*60}")
        print(f"  Packets received:     {self.stats['packets_recv']}")
        print(f"  STOP commands:        {self.stats['stop_commands']}")
        print(f"  GO commands:          {self.stats['go_commands']}")
        print(f"  Actuator triggers:    {self.stats['actuator_triggers']}")
        print(f"  Watchdog failsafes:   {self.stats['watchdog_failsafes']}")
        print(f"  Final actuator state: {self._actuator_state}")

        for name in ["recv", "validate", "watchdog"]:
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
    parser = argparse.ArgumentParser(description="Node C — Actuator Control (Host Fallback)")
    parser.add_argument("--local", action="store_true",
                        help="Use 0.0.0.0 instead of simnet IP (all nodes on one host)")
    args = parser.parse_args()

    node = NodeC(local=args.local)
    node.run()


if __name__ == "__main__":
    main()
