"""
scheduler.py — Non-preemptive cooperative periodic task scheduler.

Supports RMS (fixed priority), EDF (earliest deadline first), and
LLF (least laxity first) scheduling policies.

Since Python threads cannot preempt each other mid-execution (GIL),
this is a cooperative scheduler: tasks run to completion, then the
policy selects the next ready task. This is disclosed in the paper.
"""

import ctypes
import ctypes.wintypes
import os
import platform
import time
import threading
from typing import Callable, Dict, List, Optional

_IS_WINDOWS = platform.system() == "Windows"
if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _DUPLICATE_SAME_ACCESS = 0x00000002
    _ABOVE_NORMAL_PRIORITY_CLASS = 0x00008000
    # Correct restype so 64-bit pseudo-handles aren't truncated to 32-bit
    _kernel32.GetCurrentProcess.restype = ctypes.wintypes.HANDLE
    _kernel32.GetCurrentThread.restype = ctypes.wintypes.HANDLE
    _kernel32.DuplicateHandle.restype = ctypes.wintypes.BOOL
    _kernel32.DuplicateHandle.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE, ctypes.wintypes.HANDLE,
        ctypes.POINTER(ctypes.wintypes.HANDLE), ctypes.wintypes.DWORD,
        ctypes.wintypes.BOOL, ctypes.wintypes.DWORD,
    ]
    _kernel32.SetPriorityClass.restype = ctypes.wintypes.BOOL
    _kernel32.SetPriorityClass.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
    _kernel32.SetThreadPriority.restype = ctypes.wintypes.BOOL
    _kernel32.SetThreadPriority.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_int]
    _kernel32.SetThreadAffinityMask.restype = ctypes.c_size_t
    _kernel32.SetThreadAffinityMask.argtypes = [ctypes.wintypes.HANDLE, ctypes.c_size_t]


class ScheduledTask:
    """A periodic task managed by CooperativeScheduler."""

    def __init__(self, name: str, period: float, wcet_estimate: float,
                 func: Callable, priority: int = 99):
        """
        Args:
            name:          Human-readable task name.
            period:        Nominal period in seconds.
            wcet_estimate: Conservative WCET estimate in seconds (used by LLF
                           to compute laxity = deadline - now - wcet_estimate).
            func:          Callable executed each release.
            priority:      Static priority for RMS (lower integer = runs first).
        """
        self.name = name
        self.period = period
        self.wcet_estimate = wcet_estimate
        self.func = func
        self.priority = priority

        now = time.perf_counter()
        self.next_release: float = now
        self.absolute_deadline: float = now + period

        self.exec_times_ms: List[float] = []
        self.overruns: List[tuple] = []  # (name, elapsed_ms, period_ms)

    def is_ready(self, now: float) -> bool:
        return now >= self.next_release

    def laxity(self, now: float) -> float:
        """Remaining slack = deadline - now - estimated remaining execution."""
        return self.absolute_deadline - now - self.wcet_estimate

    def advance(self) -> None:
        """Advance release time and absolute deadline by one period."""
        self.next_release += self.period
        self.absolute_deadline += self.period


class CooperativeScheduler:
    """
    Non-preemptive cooperative scheduler for a fixed set of periodic tasks.

    At each scheduling point the scheduler picks one ready task based on policy:
      'rms' — static priority (lower priority integer runs first; assign by
               Liu-Layland rule: shorter period = lower integer)
      'edf' — earliest absolute deadline first
      'llf' — least laxity first (laxity = deadline - now - wcet_estimate)

    Tasks run to completion before the next scheduling decision is made.
    Overruns are recorded when a task's elapsed time exceeds its period.
    All timing uses time.perf_counter() for sub-millisecond resolution.
    """

    IDLE_SLEEP = 0.0005  # 0.5 ms poll interval when no task is ready

    def __init__(self, tasks: List[ScheduledTask], policy: str = "rms"):
        if policy not in ("rms", "edf", "llf"):
            raise ValueError(
                f"Unknown scheduling policy {policy!r}. Choose: rms, edf, llf"
            )
        self.policy = policy
        self._tasks = tasks

    @property
    def tasks(self) -> List[ScheduledTask]:
        return self._tasks

    def _select(self, ready: List[ScheduledTask], now: float) -> ScheduledTask:
        if self.policy == "rms":
            return min(ready, key=lambda t: t.priority)
        elif self.policy == "edf":
            return min(ready, key=lambda t: t.absolute_deadline)
        else:  # llf
            return min(ready, key=lambda t: t.laxity(now))

    def run(self, running: threading.Event) -> None:
        """
        Main scheduler loop. Blocks until running is cleared.
        Intended to run in a single dedicated daemon thread.
        """
        while running.is_set():
            now = time.perf_counter()
            ready = [t for t in self._tasks if t.is_ready(now)]

            if not ready:
                next_wake = min(t.next_release for t in self._tasks)
                sleep_s = next_wake - now
                time.sleep(max(0.0, min(sleep_s, self.IDLE_SLEEP)))
                continue

            task = self._select(ready, now)
            t_start = time.perf_counter()
            task.func()
            elapsed_s = time.perf_counter() - t_start
            elapsed_ms = elapsed_s * 1000

            task.exec_times_ms.append(elapsed_ms)
            if elapsed_s > task.period:
                task.overruns.append((task.name, elapsed_ms, task.period * 1000))

            task.advance()

    def all_overruns(self) -> List[tuple]:
        """Collect all overrun records across all tasks."""
        result = []
        for t in self._tasks:
            result.extend(t.overruns)
        return result


class WindowsThreadScheduler:
    """
    Preemptive scheduler using Windows OS thread priorities.

    Each periodic task runs in its own OS thread. Windows genuinely preempts
    a lower-priority thread when a higher-priority thread becomes runnable —
    unlike CooperativeScheduler where tasks run to completion before
    scheduling decisions are made.

    Policy mapping:
      'rms' — static priority assigned at thread start (shorter period = higher
               Windows priority). No manager thread needed.
      'edf' — a priority-manager thread re-ranks task threads every 1 ms by
               ascending absolute deadline.  Nearest deadline → TIME_CRITICAL.
      'llf' — same manager, ranked by ascending laxity
               (laxity = deadline − now − wcet_estimate).

    Partitioned mode (partitioned=True):
      Each task thread is pinned to a dedicated CPU core via SetThreadAffinityMask.
      Task with priority=1 → core 1, priority=2 → core 2, etc.  This implements
      Partitioned RMS/EDF/LLF: each processor runs its own single-task sub-schedule,
      eliminating inter-task CPU contention entirely.

    Limitation: Windows is not a hard RTOS.  Interrupt latency and DPC
    jitter are unbounded, so worst-case guarantees are softer than VxWorks.
    However, thread preemption IS real: the OS will context-switch away from
    a running lower-priority thread when a higher-priority thread unblocks.

    Only available on Windows.  Raises RuntimeError on other platforms.
    """

    # Windows THREAD_PRIORITY_* constants, index 0 = highest
    _WIN_PRIORITIES: List[int] = [
        15,   # THREAD_PRIORITY_TIME_CRITICAL
         2,   # THREAD_PRIORITY_HIGHEST
         0,   # THREAD_PRIORITY_NORMAL
        -2,   # THREAD_PRIORITY_LOWEST
    ]
    _MANAGER_INTERVAL = 0.001  # 1 ms priority-update cycle

    def __init__(self, tasks: List[ScheduledTask], policy: str = "rms",
                 partitioned: bool = False):
        if not _IS_WINDOWS:
            raise RuntimeError(
                "WindowsThreadScheduler is only available on Windows. "
                "Use CooperativeScheduler on other platforms."
            )
        if policy not in ("rms", "edf", "llf"):
            raise ValueError(f"Unknown policy {policy!r}. Choose: rms, edf, llf")
        self.policy = policy
        self.partitioned = partitioned
        self._tasks = tasks
        self._num_cpus = os.cpu_count() or 4
        # Maps task name → duplicated real HANDLE (cross-thread usable)
        self._handles: Dict[str, ctypes.wintypes.HANDLE] = {}

    # ------------------------------------------------------------------
    # Handle helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _duplicate_current_thread_handle() -> ctypes.wintypes.HANDLE:
        """
        GetCurrentThread() returns a pseudo-handle valid only in the calling
        thread.  DuplicateHandle() produces a real handle the priority manager
        can use from a different thread.
        """
        proc = _kernel32.GetCurrentProcess()
        pseudo = _kernel32.GetCurrentThread()
        real = ctypes.wintypes.HANDLE()
        ok = _kernel32.DuplicateHandle(
            proc, pseudo, proc,
            ctypes.byref(real),
            0, False, _DUPLICATE_SAME_ACCESS,
        )
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())
        return real

    @staticmethod
    def _set_thread_priority(handle: ctypes.wintypes.HANDLE, win_priority: int) -> None:
        _kernel32.SetThreadPriority(handle, win_priority)

    # ------------------------------------------------------------------
    # Per-task thread
    # ------------------------------------------------------------------

    def _task_loop(self, task: ScheduledTask, running: threading.Event) -> None:
        try:
            real_handle = self._duplicate_current_thread_handle()
            self._handles[task.name] = real_handle
        except OSError:
            real_handle = None

        if real_handle is not None:
            # RMS: fixed priority set once here; EDF/LLF: manager overrides later
            if self.policy == "rms":
                idx = min(task.priority - 1, len(self._WIN_PRIORITIES) - 1)
                self._set_thread_priority(real_handle, self._WIN_PRIORITIES[idx])

            # Partitioned: pin this thread to a dedicated core
            if self.partitioned:
                core = min(task.priority, self._num_cpus - 1)
                mask = ctypes.c_size_t(1 << core)
                if not _kernel32.SetThreadAffinityMask(real_handle, mask):
                    print(f"  WARNING: SetThreadAffinityMask failed for {task.name} "
                          f"(core {core})")

        next_release = time.perf_counter()
        task.next_release = next_release
        task.absolute_deadline = next_release + task.period

        while running.is_set():
            now = time.perf_counter()
            wait = next_release - now
            if wait > 0:
                time.sleep(wait)

            t_start = time.perf_counter()
            task.func()
            elapsed_s = time.perf_counter() - t_start
            elapsed_ms = elapsed_s * 1000

            task.exec_times_ms.append(elapsed_ms)
            if elapsed_s > task.period:
                task.overruns.append((task.name, elapsed_ms, task.period * 1000))

            next_release += task.period
            task.next_release = next_release
            task.absolute_deadline = next_release + task.period

        _kernel32.CloseHandle(real_handle)
        self._handles.pop(task.name, None)

    # ------------------------------------------------------------------
    # Priority manager (EDF / LLF only)
    # ------------------------------------------------------------------

    def _priority_manager(self, running: threading.Event) -> None:
        """
        Runs every _MANAGER_INTERVAL seconds.  Ranks live task threads by
        EDF or LLF ordering and updates their OS priorities accordingly so
        that Windows preempts in the right order.
        """
        while running.is_set():
            now = time.perf_counter()
            if self.policy == "edf":
                ranked = sorted(self._tasks, key=lambda t: t.absolute_deadline)
            else:  # llf
                ranked = sorted(self._tasks, key=lambda t: t.laxity(now))

            for rank, task in enumerate(ranked):
                handle = self._handles.get(task.name)
                if handle is not None and rank < len(self._WIN_PRIORITIES):
                    self._set_thread_priority(handle, self._WIN_PRIORITIES[rank])

            time.sleep(self._MANAGER_INTERVAL)

    # ------------------------------------------------------------------
    # Public interface (mirrors CooperativeScheduler)
    # ------------------------------------------------------------------

    def run(self, running: threading.Event) -> None:
        """Launch task threads (+ manager if needed). Blocks until running clears."""
        # Boost process priority so OS scheduler favours our threads
        _kernel32.SetPriorityClass(
            _kernel32.GetCurrentProcess(), _ABOVE_NORMAL_PRIORITY_CLASS
        )

        threads = [
            threading.Thread(
                target=self._task_loop, args=(task, running), daemon=True
            )
            for task in self._tasks
        ]
        if self.policy in ("edf", "llf"):
            threads.append(
                threading.Thread(
                    target=self._priority_manager, args=(running,), daemon=True
                )
            )

        for t in threads:
            t.start()

        running.wait()          # block until NodeB/C clears the event
        time.sleep(0.05)        # grace period for threads to finish current tick

    @property
    def tasks(self) -> List[ScheduledTask]:
        return self._tasks

    def all_overruns(self) -> List[tuple]:
        result = []
        for t in self._tasks:
            result.extend(t.overruns)
        return result
