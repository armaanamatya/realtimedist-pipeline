"""
sweep.py — Automated experiment sweep across scheduling policies, precisions,
confidence thresholds, and multiprocessor modes.

Experiment matrix
-----------------
  precision     : fp32, fp16
  scheduler     : rms, edf, llf
  threshold     : 0.10, 0.30, 0.50, 0.85
  execution mode: cooperative | preemptive-global | preemptive-partitioned

Total runs: 3 modes × 3 policies × 2 precisions × 4 thresholds = 72

Each run launches nodeB (--test mode, embeds MockNodeA) and nodeC as
subprocesses, waits for them to complete, then reads their JSON summaries.
Results are written incrementally to results/sweep/sweep_summary.csv.

Usage
-----
  python sweep.py                    # full matrix
  python sweep.py --quick            # 1 precision, 1 threshold, all policies/modes
  python sweep.py --stress           # also run with infer-period=0.020 (stress test)
  python sweep.py --dry-run          # print experiment list without running
  python sweep.py --precision fp32   # filter to one precision
  python sweep.py --scheduler rms    # filter to one scheduler
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from itertools import product
from pathlib import Path

# ── Defaults ─────────────────────────────────────────────────────────────────

PRECISIONS  = ["fp32", "fp16"]
SCHEDULERS  = ["rms", "edf", "llf"]
THRESHOLDS  = [0.10, 0.30, 0.50, 0.85]

# Normal inference period (matches nodeB.py INFER_PERIOD)
INFER_PERIOD_NORMAL = 0.050   # 50 ms
# Stress period: pushes U_inference from 0.154 toward 0.40+ to expose RMS/EDF/LLF differences
INFER_PERIOD_STRESS = 0.020   # 20 ms

RUN_DURATION   = 30    # seconds of data collection per run
MODEL_LOAD_PAD = 65    # seconds added to stop_at so the model finishes loading
                       # before the 30-second window closes
NODEC_START_DELAY = 2  # seconds nodeC gets to bind its socket before nodeB starts

RESULTS_BASE = Path("results/sweep")

# ── CSV columns ───────────────────────────────────────────────────────────────

CSV_FIELDS = [
    "run_id", "precision", "scheduler", "threshold",
    "execution_mode",         # cooperative | preemptive | partitioned
    "infer_period_ms",
    # Node B timing
    "infer_avg_ms", "infer_max_ms", "infer_p99_ms",
    "recv_avg_ms",  "recv_max_ms",
    "send_avg_ms",  "send_max_ms",
    "e2e_avg_ms",   "e2e_p99_ms",
    # Node B counts
    "infer_count", "commands_sent",
    "nodeB_overruns", "nodeB_overruns_recv", "nodeB_overruns_infer", "nodeB_overruns_send",
    # Empirical utilisation
    "U_recv", "U_infer", "U_send", "U_total",
    # Node C
    "nodeC_overruns", "actuator_triggers", "watchdog_failsafes",
    # Meta
    "audio_source",   # mock | vxsim
    "status",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def run_id_for(precision, scheduler, threshold, mode, infer_period, use_vxsim=False):
    period_tag = "stress" if infer_period == INFER_PERIOD_STRESS else "normal"
    src_tag = "vxsim" if use_vxsim else "mock"
    return f"{precision}_{scheduler}_t{threshold:.2f}_{mode}_{period_tag}_{src_tag}"


def build_commands(precision, scheduler, threshold, mode, infer_period, run_id, stop_at,
                   use_vxsim=False):
    base_b = [
        sys.executable, "nodeB.py",
        "--precision",            precision,
        "--scheduler",            scheduler,
        "--confidence-threshold", str(threshold),
        "--results-dir",          str(RESULTS_BASE),
        "--run-id",               run_id,
        "--stop-at",              str(stop_at),
        "--infer-period",         str(infer_period),
    ]
    base_c = [
        sys.executable, "nodeC_host.py",
        "--scheduler",    scheduler,
        "--results-dir",  str(RESULTS_BASE),
        "--run-id",       run_id,
        "--stop-at",      str(stop_at),
    ]

    if use_vxsim:
        # VxSim sends at ~3-4s intervals; extend watchdog to avoid false failsafes
        base_c += ["--watchdog-timeout", "10000"]
    else:
        # MockNodeA mode: loopback only
        base_b += ["--test", "--local"]
        base_c += ["--local"]

    if mode in ("preemptive", "partitioned"):
        base_b.append("--preemptive")
        base_c.append("--preemptive")
    if mode == "partitioned":
        base_b.append("--partitioned")
        base_c.append("--partitioned")

    return base_b, base_c


def collect_results(run_id, precision, scheduler, threshold, mode, infer_period,
                    use_vxsim=False):
    row = {f: "" for f in CSV_FIELDS}
    row.update({
        "run_id":         run_id,
        "precision":      precision,
        "scheduler":      scheduler,
        "threshold":      threshold,
        "execution_mode": mode,
        "infer_period_ms": infer_period * 1000,
        "audio_source":   "vxsim" if use_vxsim else "mock",
        "status":         "ok",
    })

    run_dir = RESULTS_BASE / run_id

    # ── Node B summary ──────────────────────────────────────────────────────
    b_path = run_dir / "nodeB_summary.json"
    if b_path.exists():
        b = json.loads(b_path.read_text())
        t = b.get("timing", {})

        def g(section, key, default=""):
            return t.get(section, {}).get(key, default)

        row.update({
            "infer_avg_ms": g("inference", "avg_ms"),
            "infer_max_ms": g("inference", "max_ms"),
            "infer_p99_ms": g("inference", "p99_ms"),
            "recv_avg_ms":  g("recv",      "avg_ms"),
            "recv_max_ms":  g("recv",      "max_ms"),
            "send_avg_ms":  g("send",      "avg_ms"),
            "send_max_ms":  g("send",      "max_ms"),
            "e2e_avg_ms":   g("e2e",       "avg_ms"),
            "e2e_p99_ms":   g("e2e",       "p99_ms"),
            "infer_count":  b.get("stats", {}).get("inferences_run", ""),
            "commands_sent": b.get("stats", {}).get("commands_sent", ""),
            "nodeB_overruns": b.get("overrun_count", ""),
        })

        # Per-task overrun breakdown
        by_task = b.get("overruns_by_task", {})
        row["nodeB_overruns_recv"]  = by_task.get("recv",      0)
        row["nodeB_overruns_infer"] = by_task.get("inference", 0)
        row["nodeB_overruns_send"]  = by_task.get("send",      0)

        # Empirical utilisation: avg_exec / period
        RECV_P, SEND_P = 0.020, 0.020
        try:
            u_recv  = float(g("recv",      "avg_ms", 0)) / 1000 / RECV_P
            u_infer = float(g("inference", "avg_ms", 0)) / 1000 / infer_period
            u_send  = float(g("send",      "avg_ms", 0)) / 1000 / SEND_P
            row["U_recv"]  = f"{u_recv:.4f}"
            row["U_infer"] = f"{u_infer:.4f}"
            row["U_send"]  = f"{u_send:.4f}"
            row["U_total"] = f"{u_recv + u_infer + u_send:.4f}"
        except (TypeError, ValueError):
            pass
    else:
        row["status"] = "missing_nodeB_summary"

    # ── Node C summary ──────────────────────────────────────────────────────
    c_path = run_dir / "nodeC_summary.json"
    if c_path.exists():
        c = json.loads(c_path.read_text())
        row.update({
            "nodeC_overruns":    c.get("overrun_count", ""),
            "actuator_triggers": c.get("stats", {}).get("actuator_triggers", ""),
            "watchdog_failsafes": c.get("stats", {}).get("watchdog_failsafes", ""),
        })
    else:
        if row["status"] == "ok":
            row["status"] = "missing_nodeC_summary"

    return row


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


# ── Main sweep logic ──────────────────────────────────────────────────────────

def build_matrix(args):
    precisions  = [args.precision]  if args.precision  else PRECISIONS
    schedulers  = [args.scheduler]  if args.scheduler  else SCHEDULERS
    thresholds  = [THRESHOLDS[1]]   if args.quick      else THRESHOLDS
    if args.quick:
        precisions = [precisions[0]]

    modes = ["cooperative", "preemptive", "partitioned"]
    infer_periods = [INFER_PERIOD_NORMAL]
    if args.stress:
        infer_periods.append(INFER_PERIOD_STRESS)

    experiments = []
    for precision, scheduler, threshold, mode, infer_period in product(
        precisions, schedulers, thresholds, modes, infer_periods
    ):
        experiments.append((precision, scheduler, threshold, mode, infer_period))
    return experiments


def run_experiment(precision, scheduler, threshold, mode, infer_period,
                   dry_run, verbose, use_vxsim=False):
    rid = run_id_for(precision, scheduler, threshold, mode, infer_period, use_vxsim)
    stop_at = time.time() + MODEL_LOAD_PAD + RUN_DURATION

    cmd_b, cmd_c = build_commands(
        precision, scheduler, threshold, mode, infer_period, rid, stop_at, use_vxsim
    )

    if dry_run:
        print(f"  [dry] {rid}")
        print(f"        nodeB: {' '.join(cmd_b[2:])}")
        return None

    print(f"  nodeB: {' '.join(cmd_b[2:])}")

    stdout_b = None if verbose else subprocess.DEVNULL
    stdout_c = None if verbose else subprocess.DEVNULL

    # nodeC binds its socket first, then nodeB starts (or VxSim Node A resumes)
    proc_c = subprocess.Popen(cmd_c, stdout=stdout_c, stderr=subprocess.STDOUT)
    time.sleep(NODEC_START_DELAY)
    proc_b = subprocess.Popen(cmd_b, stdout=stdout_b, stderr=subprocess.STDOUT)

    proc_b.wait()
    proc_c.wait()

    return collect_results(rid, precision, scheduler, threshold, mode, infer_period,
                           use_vxsim)


def main():
    parser = argparse.ArgumentParser(
        description="Automated sweep: scheduling policy × precision × threshold × mode"
    )
    parser.add_argument("--precision", choices=["fp32", "fp16"], default=None,
                        help="Run only this precision (default: both)")
    parser.add_argument("--scheduler", choices=["rms", "edf", "llf"], default=None,
                        help="Run only this scheduler (default: all)")
    parser.add_argument("--quick", action="store_true",
                        help="One precision, one threshold — useful for testing the sweep itself")
    parser.add_argument("--stress", action="store_true",
                        help="Also run with --infer-period 0.020 (stress test mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print experiment list without launching any processes")
    parser.add_argument("--verbose", action="store_true",
                        help="Show nodeB/nodeC stdout in the terminal")
    parser.add_argument("--use-vxsim", action="store_true",
                        help="Use real VxSim Node A instead of MockNodeA. "
                             "nodeB listens on simnet (192.168.200.2:5001); "
                             "you must start Node A in the VxWorks shell before running: "
                             "nodeA_setTarget \"<HOST_IP>\", 5001 ; nodeA_start \"/path/to.wav\"")
    args = parser.parse_args()

    if args.use_vxsim:
        print("[sweep] VxSim mode -- nodeB will listen on simnet for real UDP packets.")
        print("[sweep] Make sure Node A is already running in VxWorks shell before proceeding.")
        print()

    experiments = build_matrix(args)
    total = len(experiments)
    est_min = total * (MODEL_LOAD_PAD + RUN_DURATION + NODEC_START_DELAY) / 60

    print(f"[sweep] {total} experiments x ~{MODEL_LOAD_PAD + RUN_DURATION}s each "
          f"~= {est_min:.0f} min total")
    print(f"[sweep] Results -> {RESULTS_BASE.resolve()}\n")

    csv_path = RESULTS_BASE / "sweep_summary.csv"
    rows = []

    for i, (precision, scheduler, threshold, mode, infer_period) in enumerate(experiments):
        period_tag = f" [stress {infer_period*1000:.0f}ms]" if infer_period == INFER_PERIOD_STRESS else ""
        print(f"[{i+1:>3}/{total}] {precision} | {scheduler.upper()} | "
              f"t={threshold:.2f} | {mode}{period_tag}")

        row = run_experiment(precision, scheduler, threshold, mode, infer_period,
                             dry_run=args.dry_run, verbose=args.verbose,
                             use_vxsim=args.use_vxsim)
        if row is not None:
            rows.append(row)
            write_csv(rows, csv_path)  # incremental write
            status = row.get("status", "?")
            print(f"        -> infer_avg={row.get('infer_avg_ms','?')}ms  "
                  f"nodeB_overruns={row.get('nodeB_overruns','?')}  "
                  f"nodeC_overruns={row.get('nodeC_overruns','?')}  "
                  f"U_total={row.get('U_total','?')}  [{status}]")

    if not args.dry_run:
        print(f"\n[sweep] Done. CSV -> {csv_path.resolve()}")


if __name__ == "__main__":
    main()
