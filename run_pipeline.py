"""
run_pipeline.py — Launch the full 3-node pipeline in a single process.

Starts Node C, Node B, and Node A as subprocesses on localhost for testing.
Optionally inserts the UDP proxy between hops.

Usage:
    python run_pipeline.py                              # direct, FP32, noise input
    python run_pipeline.py --wav test_audio.wav         # with real audio
    python run_pipeline.py --precision fp16             # FP16 mode
    python run_pipeline.py --proxy --proxy-mode moderate  # with network impairment
    python run_pipeline.py --duration 15                # run for 15 seconds
"""

import argparse
import subprocess
import sys
import time
import os

from results_logging import create_run_dir


def main():
    parser = argparse.ArgumentParser(description="Run 3-node pipeline locally")
    parser.add_argument("--wav", type=str, default=None,
                        help="WAV file for Node A (16kHz, 16-bit, mono)")
    parser.add_argument("--precision", choices=["fp32", "fp16"], default="fp32",
                        help="Node B model precision")
    parser.add_argument("--duration", type=int, default=30,
                        help="Run duration in seconds (default: 30)")
    parser.add_argument("--log-file", type=str, default=None,
                        help="CSV log file for Node B timing data")
    parser.add_argument("--proxy", action="store_true",
                        help="Run with UDP proxy between hops")
    parser.add_argument("--proxy-mode", choices=["baseline", "moderate", "heavy", "partition"],
                        default="baseline",
                        help="Proxy impairment profile (default: baseline)")
    parser.add_argument("--confidence-threshold", type=float, default=0.85,
                        help="Node B confidence threshold (default: 0.85)")
    parser.add_argument("--results-dir", default="results",
                        help="Directory for generated results (default: results)")
    parser.add_argument("--run-id", default=None,
                        help="Run folder name shared across nodes")
    parser.add_argument("--no-results", action="store_true",
                        help="Disable generated CSV/JSON result files")
    args = parser.parse_args()

    python = sys.executable
    # Force unbuffered output from subprocesses
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["HF_HUB_DISABLE_XET"] = "1"
    procs = []
    popen_kwargs = {"env": env}

    result_args = ["--no-results"]
    if not args.no_results:
        run_dir = create_run_dir(args.results_dir, args.run_id)
        result_args = ["--results-dir", args.results_dir, "--run-id", run_dir.name]
        print(f"[pipeline] Results -> {run_dir}")

    planned_stop_at = time.time() + 0.5 + (0.3 if args.proxy else 0.0) + 15 + args.duration
    stop_args = ["--stop-at", f"{planned_stop_at:.6f}"]
    interrupted = False

    try:
        # 1. Start Node C first (receiver)
        print("[pipeline] Starting Node C ...")
        cmd_c = [python, "nodeC_host.py", "--local", *result_args, *stop_args]
        proc_c = subprocess.Popen(cmd_c, **popen_kwargs)
        procs.append(("Node C", proc_c))
        time.sleep(0.5)

        # 2. Optionally start UDP proxy
        if args.proxy:
            print(f"[pipeline] Starting UDP proxy (mode={args.proxy_mode}) ...")
            cmd_proxy = [python, "udp_proxy.py", "--mode", args.proxy_mode]
            proc_proxy = subprocess.Popen(cmd_proxy, **popen_kwargs)
            procs.append(("Proxy", proc_proxy))
            time.sleep(0.3)

        # 3. Start Node B
        print(f"[pipeline] Starting Node B (precision={args.precision}) ...")
        cmd_b = [python, "nodeB.py", "--local", "--precision", args.precision,
                 "--confidence-threshold", str(args.confidence_threshold),
                 *result_args, *stop_args]
        if args.log_file:
            cmd_b += ["--log-file", args.log_file]
        if args.proxy:
            cmd_b += ["--target-port", "6002"]  # send to proxy instead of Node C directly
        proc_b = subprocess.Popen(cmd_b, **popen_kwargs)
        procs.append(("Node B", proc_b))

        # Wait for model to load (Node B takes a while on first run)
        print("[pipeline] Waiting for Node B model to load ...")
        time.sleep(15)

        # 4. Start Node A
        print("[pipeline] Starting Node A ...")
        cmd_a = [python, "nodeA_host.py", "--local", *result_args, *stop_args]
        if args.wav:
            cmd_a += ["--wav", args.wav]
        if args.proxy:
            cmd_a += ["--target-port", "6001"]  # send to proxy instead of Node B directly
        proc_a = subprocess.Popen(cmd_a, **popen_kwargs)
        procs.append(("Node A", proc_a))

        # Run for duration
        print(f"\n[pipeline] All nodes running. Will stop in {args.duration}s ...\n")
        time.sleep(args.duration)

    except KeyboardInterrupt:
        interrupted = True
        print("\n[pipeline] Interrupted by user.")
    finally:
        # Shutdown in reverse order
        print("\n[pipeline] Shutting down all nodes ...")
        if interrupted:
            for name, proc in reversed(procs):
                if proc.poll() is None:
                    proc.terminate()
                    print(f"  Terminated {name} (pid={proc.pid})")
        else:
            for name, proc in reversed(procs):
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        pass

        for name, proc in procs:
            if proc.poll() is None:
                proc.terminate()
                print(f"  Terminated {name} (pid={proc.pid})")

        time.sleep(1)

        for name, proc in procs:
            if proc.poll() is None:
                proc.kill()

        print("[pipeline] Done.")


if __name__ == "__main__":
    main()
