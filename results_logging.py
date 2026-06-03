"""Shared results logging helpers for the three-node pipeline."""

import csv
import json
import re
import threading
from datetime import datetime
from pathlib import Path


def sanitize_run_id(run_id):
    """Return a filesystem-safe run identifier."""
    if not run_id:
        return datetime.now().strftime("run_%Y%m%d_%H%M%S")
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id.strip())
    return safe or datetime.now().strftime("run_%Y%m%d_%H%M%S")


def create_run_dir(results_dir="results", run_id=None):
    """Create and return the run directory path."""
    root = Path(results_dir)
    name = sanitize_run_id(run_id)
    run_dir = root / name

    if run_id is None:
        base = run_dir
        suffix = 1
        while run_dir.exists():
            suffix += 1
            run_dir = Path(f"{base}_{suffix:02d}")

    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def percentile(values, pct):
    if not values:
        return None

    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]

    position = (len(ordered) - 1) * pct / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def timing_stats(values):
    """Summarize a sequence of millisecond timing values."""
    vals = [float(v) for v in values]
    if not vals:
        return {
            "count": 0,
            "min_ms": None,
            "avg_ms": None,
            "max_ms": None,
            "p99_ms": None,
        }

    return {
        "count": len(vals),
        "min_ms": min(vals),
        "avg_ms": sum(vals) / len(vals),
        "max_ms": max(vals),
        "p99_ms": percentile(vals, 99),
    }


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


class CsvTable:
    """Small thread-safe CSV writer wrapper."""

    def __init__(self, path, fieldnames):
        self.path = Path(path)
        self.fieldnames = list(fieldnames)
        self._lock = threading.Lock()
        self._file = self.path.open("w", newline="")
        self._writer = csv.DictWriter(
            self._file, fieldnames=self.fieldnames, extrasaction="ignore"
        )
        self._writer.writeheader()

    def writerow(self, row):
        with self._lock:
            safe_row = {name: row.get(name, "") for name in self.fieldnames}
            self._writer.writerow(safe_row)
            self._file.flush()

    def close(self):
        with self._lock:
            self._file.close()


class ResultsLogger:
    """Owns all generated files for one node in one run directory."""

    def __init__(self, node_name, results_dir="results", run_id=None, enabled=True):
        self.node_name = node_name
        self.enabled = enabled
        self.run_dir = create_run_dir(results_dir, run_id) if enabled else None
        self._tables = []

    def csv_table(self, filename, fieldnames):
        if not self.enabled:
            return None
        table = CsvTable(self.run_dir / filename, fieldnames)
        self._tables.append(table)
        return table

    def write_summary(self, filename, data):
        if not self.enabled:
            return
        path = self.run_dir / filename
        with path.open("w") as handle:
            json.dump(data, handle, indent=2, default=_json_default)
            handle.write("\n")

    def close(self):
        for table in self._tables:
            table.close()
        self._tables.clear()
