"""
run_impairment_sweep.py - Sequential ablation sweep over (precision x impairment).

Matrix: {fp32, fp16} x {baseline, moderate, heavy, partition} = 8 runs.
Each run uses run_pipeline.py in --local mode with the UDP proxy inserted.
Output goes to finalresults/impairment_sweep/<precision>_<mode>/ alongside a
sweep_manifest.json (per-run status, written incrementally) and a final
sweep_summary.md aggregating key metrics for analysis.
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
SWEEP_DIR = ROOT / "finalresults" / "impairment_sweep"
SWEEP_DIR.mkdir(parents=True, exist_ok=True)

# Use the project venv explicitly so torch/transformers are importable.
VENV_PY = ROOT / "venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PY) if VENV_PY.exists() else sys.executable

PRECISIONS = ["fp32", "fp16"]
MODES = ["baseline", "moderate", "heavy", "partition"]
WAV = "stop_clean.wav"
DURATION = 30
CONFIDENCE = 0.85

manifest_path = SWEEP_DIR / "sweep_manifest.json"
log_path = SWEEP_DIR / "sweep_progress.log"

manifest = {
    "started_at": datetime.now().isoformat(timespec="seconds"),
    "wav": WAV,
    "duration_s": DURATION,
    "confidence_threshold": CONFIDENCE,
    "matrix": {"precisions": PRECISIONS, "modes": MODES},
    "runs": [],
}

def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def write_manifest():
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

def safe_load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

write_manifest()
log(f"Sweep started: {len(PRECISIONS) * len(MODES)} runs.")

total = len(PRECISIONS) * len(MODES)
idx = 0
sweep_t0 = time.time()

for precision in PRECISIONS:
    for mode in MODES:
        idx += 1
        run_id = f"{precision}_{mode}"
        run_dir = SWEEP_DIR / run_id
        log(f"[{idx}/{total}] {run_id} starting...")
        cmd = [
            PYTHON, "run_pipeline.py",
            "--wav", WAV,
            "--precision", precision,
            "--proxy", "--proxy-mode", mode,
            "--duration", str(DURATION),
            "--confidence-threshold", str(CONFIDENCE),
            "--results-dir", str(SWEEP_DIR),
            "--run-id", run_id,
        ]
        t0 = time.time()
        run_log = run_dir / "pipeline_stdout.log"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_log, "w", encoding="utf-8") as logf:
            proc = subprocess.run(cmd, cwd=ROOT, stdout=logf,
                                  stderr=subprocess.STDOUT, text=True)
        wall = time.time() - t0

        nodeB = safe_load_json(run_dir / "nodeB_summary.json")
        nodeC = safe_load_json(run_dir / "nodeC_summary.json")

        manifest["runs"].append({
            "run_id": run_id,
            "precision": precision,
            "mode": mode,
            "exit_code": proc.returncode,
            "wall_seconds": round(wall, 2),
            "run_dir": str(run_dir.relative_to(ROOT)),
            "nodeB_summary_present": nodeB is not None,
            "nodeC_summary_present": nodeC is not None,
        })
        write_manifest()
        log(f"[{idx}/{total}] {run_id} done (exit={proc.returncode}, {wall:.1f}s)")
        time.sleep(2)  # let ports release

manifest["finished_at"] = datetime.now().isoformat(timespec="seconds")
manifest["total_wall_seconds"] = round(time.time() - sweep_t0, 2)
write_manifest()
log(f"Sweep complete in {manifest['total_wall_seconds']}s. Building summary...")

# ---------- summary ----------
def fmt(x, n=2):
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{n}f}"
    return str(x)

def _g(d, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

rows = []
for r in manifest["runs"]:
    rd = ROOT / r["run_dir"]
    nb = safe_load_json(rd / "nodeB_summary.json") or {}
    nc = safe_load_json(rd / "nodeC_summary.json") or {}
    na = safe_load_json(rd / "nodeA_summary.json") or {}
    rows.append({
        "run_id": r["run_id"],
        "precision": r["precision"],
        "mode": r["mode"],
        "exit": r["exit_code"],
        "A_chunks_sent": _g(na, "stats", "chunks_sent"),
        "B_packets_recv": _g(nb, "stats", "packets_recv"),
        "B_inferences": _g(nb, "stats", "inferences_run"),
        "B_cmds_forwarded": _g(nb, "stats", "commands_forwarded"),
        "B_infer_avg_ms": _g(nb, "timing", "inference", "avg_ms"),
        "B_infer_p99_ms": _g(nb, "timing", "inference", "p99_ms"),
        "B_infer_max_ms": _g(nb, "timing", "inference", "max_ms"),
        "B_e2e_avg_ms": _g(nb, "timing", "e2e", "avg_ms"),
        "B_e2e_p99_ms": _g(nb, "timing", "e2e", "p99_ms"),
        "B_e2e_max_ms": _g(nb, "timing", "e2e", "max_ms"),
        "B_overruns": nb.get("overrun_count"),
        "C_packets_recv": _g(nc, "stats", "packets_recv"),
        "C_actuator_triggers": _g(nc, "stats", "actuator_triggers"),
        "C_watchdog": _g(nc, "stats", "watchdog_failsafes"),
        "C_final_state": _g(nc, "stats", "final_actuator_state"),
        "C_overruns": nc.get("overrun_count"),
    })

summary_path = SWEEP_DIR / "sweep_summary.md"
with open(summary_path, "w", encoding="utf-8") as f:
    f.write(f"# Impairment Sweep Summary\n\n")
    f.write(f"- Started: {manifest['started_at']}\n")
    f.write(f"- Finished: {manifest['finished_at']}\n")
    f.write(f"- Total wall: {manifest['total_wall_seconds']}s\n")
    f.write(f"- WAV: {WAV} | duration={DURATION}s | conf>={CONFIDENCE}\n\n")
    f.write("## Per-run metrics\n\n")
    cols = ["run_id", "exit", "A_chunks_sent", "B_packets_recv", "B_inferences",
            "B_cmds_forwarded", "B_infer_avg_ms", "B_infer_p99_ms", "B_infer_max_ms",
            "B_e2e_avg_ms", "B_e2e_p99_ms", "B_e2e_max_ms", "B_overruns",
            "C_packets_recv", "C_actuator_triggers", "C_watchdog",
            "C_final_state", "C_overruns"]
    f.write("| " + " | ".join(cols) + " |\n")
    f.write("|" + "|".join(["---"] * len(cols)) + "|\n")
    for r in rows:
        f.write("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |\n")
    f.write("\n## Notes\n\n")
    f.write("- `partition` mode = 100% loss; expect 0 commands at Node C and watchdog failsafes.\n")
    f.write("- `heavy` = 10+/-5ms jitter, 10% loss. `moderate` = 5+/-3ms, 2% loss.\n")
    f.write("- Compare `infer_max_ms` (FP32 vs FP16) against the 150ms end-to-end deadline once network jitter is added.\n")

log(f"Summary written: {summary_path}")
log("DONE.")
