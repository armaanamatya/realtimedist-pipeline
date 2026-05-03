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

from results_logging import ResultsLogger, timing_stats
from scheduler import CooperativeScheduler, ScheduledTask, WindowsThreadScheduler

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
    def __init__(self, local=False, results_dir="results", run_id=None,
                 no_results=False, duration=None, stop_at=None,
                 scheduler="rms", preemptive=False):
        self.local = local
        self.bind_ip = "0.0.0.0" if local else NODE_C_IP
        self.duration = duration
        self.stop_at = stop_at
        self.scheduler_policy = scheduler
        self.preemptive = preemptive
        self._scheduler = None
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
        self._results = ResultsLogger(
            "nodeC", results_dir=results_dir, run_id=run_id, enabled=not no_results
        )
        self._events_csv = self._results.csv_table(
            "nodeC_events.csv",
            [
                "event",
                "seq_num",
                "command",
                "confidence",
                "action",
                "elapsed_ms",
                "since_last_ms",
                "actuator_state",
                "timestamp_perf",
                "note",
            ],
        )

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
            if self._events_csv:
                self._events_csv.writerow({
                    "event": "receive",
                    "action": "short_packet",
                    "elapsed_ms": "0.000",
                    "actuator_state": self._actuator_state,
                    "timestamp_perf": f"{time.perf_counter():.6f}",
                    "note": f"{len(data)} bytes from {addr}",
                })
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
        if self._events_csv:
            self._events_csv.writerow({
                "event": "receive",
                "seq_num": seq_num,
                "command": command,
                "confidence": f"{confidence:.4f}",
                "action": "queued",
                "elapsed_ms": f"{elapsed_ms:.3f}",
                "actuator_state": self._actuator_state,
                "timestamp_perf": f"{time.perf_counter():.6f}",
                "note": f"from {addr[0]}:{addr[1]} ts={timestamp_us}",
            })

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
            processing_ms = (now - cmd_info["recv_time"]) * 1000
            e2e_note = f" (processing={processing_ms:.1f}ms)"

        if self._events_csv:
            self._events_csv.writerow({
                "event": "actuator",
                "seq_num": cmd_info["seq"],
                "command": cmd_info["cmd"],
                "confidence": f"{cmd_info['conf']:.4f}",
                "action": action,
                "elapsed_ms": f"{(now - cmd_info['recv_time']) * 1000:.3f}",
                "actuator_state": self._actuator_state,
                "timestamp_perf": f"{now:.6f}",
            })

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
            if self._events_csv:
                self._events_csv.writerow({
                    "event": "watchdog",
                    "action": "FAILSAFE_STOP",
                    "since_last_ms": f"{elapsed_since_last:.3f}",
                    "actuator_state": self._actuator_state,
                    "timestamp_perf": f"{t_start:.6f}",
                    "note": "no packet before watchdog deadline",
                })
            print(f"\n  *** WATCHDOG FAILSAFE *** "
                  f"No packet in {elapsed_since_last:.0f}ms — triggering emergency stop\n")

        self.timing["watchdog"].append((time.perf_counter() - t_start) * 1000)

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.bind_ip, NODE_C_PORT))
        self.sock.settimeout(0.005)  # 5ms — keeps cooperative scheduler responsive

        print(f"\n{'='*50}")
        print(f"  Node C — Actuator Control (Host Fallback)")
        print(f"{'='*50}")
        print(f"  Listening: {self.bind_ip}:{NODE_C_PORT}")
        mode_str = "preemptive/OS threads" if self.preemptive else "cooperative"
        print(f"  Scheduler: {self.scheduler_policy.upper()} ({mode_str})")
        print(f"  Debounce: {DEBOUNCE_COUNT} consecutive STOP within {DEBOUNCE_WINDOW_MS}ms")
        print(f"  Watchdog: failsafe after {WATCHDOG_TIMEOUT_MS}ms silence")
        if self._results.enabled:
            print(f"  Results: {self._results.run_dir}")
        print(f"  Press Ctrl+C to stop.\n")

        self._running.set()
        self._last_packet_time = time.perf_counter()

        # WCET estimates for LLF laxity: conservative measured maxima (seconds)
        sched_tasks = [
            ScheduledTask("recv",     RECV_PERIOD,     0.003, self._udp_receive,    priority=1),
            ScheduledTask("validate", VALIDATE_PERIOD, 0.005, self._safety_validate, priority=2),
            ScheduledTask("watchdog", WATCHDOG_PERIOD, 0.002, self._watchdog,        priority=3),
        ]
        if self.preemptive:
            self._scheduler = WindowsThreadScheduler(
                sched_tasks, policy=self.scheduler_policy,
                partitioned=self.partitioned,
            )
        else:
            self._scheduler = CooperativeScheduler(sched_tasks, policy=self.scheduler_policy)
        sched_thread = threading.Thread(
            target=self._scheduler.run, args=(self._running,), daemon=True
        )
        sched_thread.start()

        completed = False
        deadline = time.perf_counter() + self.duration if self.duration is not None else None
        try:
            while True:
                now_perf = time.perf_counter()
                now_wall = time.time()
                if deadline is not None and now_perf >= deadline:
                    completed = True
                    break
                if self.stop_at is not None and now_wall >= self.stop_at:
                    completed = True
                    break

                sleep_time = 1.0
                if deadline is not None:
                    sleep_time = min(sleep_time, max(0.01, deadline - now_perf))
                if self.stop_at is not None:
                    sleep_time = min(sleep_time, max(0.01, self.stop_at - now_wall))
                time.sleep(sleep_time)
        except KeyboardInterrupt:
            print("\nnodeC: Shutting down ...")
        if completed:
            print("\nnodeC: Duration complete; shutting down ...")

        self._running.clear()
        time.sleep(0.2)
        self.sock.close()

        # Collect overruns recorded by the cooperative scheduler
        if self._scheduler is not None:
            for name, elapsed_ms, period_ms in self._scheduler.all_overruns():
                self.timing["overruns"].append((name, elapsed_ms, period_ms))
                if self._events_csv:
                    self._events_csv.writerow({
                        "event": "overrun",
                        "action": name,
                        "elapsed_ms": f"{elapsed_ms:.3f}",
                        "since_last_ms": f"{period_ms:.3f}",
                        "actuator_state": self._actuator_state,
                        "timestamp_perf": f"{time.perf_counter():.6f}",
                    })

        self.print_summary()
        self._results.close()

    def print_summary(self):
        mode_str = "preemptive" if self.preemptive else "cooperative"
        print(f"\n{'='*60}")
        print(f"  Node C Summary | Scheduler: {self.scheduler_policy.upper()} ({mode_str})")
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

        overruns_by_task = {}
        for task_name, _elapsed_ms, _period_ms in overruns:
            overruns_by_task[task_name] = overruns_by_task.get(task_name, 0) + 1

        self._results.write_summary("nodeC_summary.json", {
            "node": "nodeC",
            "mode": "host_fallback",
            "scheduler_policy": self.scheduler_policy,
            "scheduler_preemptive": self.preemptive,
            "local": self.local,
            "bind_ip": self.bind_ip,
            "bind_port": NODE_C_PORT,
            "debounce_count": DEBOUNCE_COUNT,
            "debounce_window_ms": DEBOUNCE_WINDOW_MS,
            "watchdog_timeout_ms": WATCHDOG_TIMEOUT_MS,
            "stats": {
                **self.stats,
                "final_actuator_state": self._actuator_state,
            },
            "timing": {
                "recv": timing_stats(self.timing["recv"]),
                "validate": timing_stats(self.timing["validate"]),
                "watchdog": timing_stats(self.timing["watchdog"]),
            },
            "overrun_count": len(overruns),
            "overruns_by_task": overruns_by_task,
            "overruns": [
                {"task": name, "elapsed_ms": elapsed, "period_ms": period}
                for name, elapsed, period in overruns
            ],
        })


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Node C — Actuator Control (Host Fallback)")
    parser.add_argument("--local", action="store_true",
                        help="Use 0.0.0.0 instead of simnet IP (all nodes on one host)")
    parser.add_argument("--results-dir", default="results",
                        help="Directory for generated results (default: results)")
    parser.add_argument("--run-id", default=None,
                        help="Run folder name shared across nodes")
    parser.add_argument("--no-results", action="store_true",
                        help="Disable generated CSV/JSON result files")
    parser.add_argument("--duration", type=float, default=None,
                        help="Run duration in seconds before clean shutdown")
    parser.add_argument("--stop-at", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--scheduler", choices=["rms", "edf", "llf"], default="rms",
                        help="Scheduling policy: rms (default), edf, or llf")
    parser.add_argument("--preemptive", action="store_true",
                        help="Use Windows OS thread priorities for real preemption "
                             "(Windows only; cooperative mode used otherwise)")
    parser.add_argument("--partitioned", action="store_true",
                        help="Pin each task thread to a dedicated CPU core "
                             "(partitioned multiprocessor scheduling; requires --preemptive)")
    args = parser.parse_args()

    node = NodeC(
        local=args.local,
        results_dir=args.results_dir,
        run_id=args.run_id,
        no_results=args.no_results,
        duration=args.duration,
        stop_at=args.stop_at,
        scheduler=args.scheduler,
        preemptive=args.preemptive,
        partitioned=args.partitioned,
    )
    node.run()


if __name__ == "__main__":
    main()
