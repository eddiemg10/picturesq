"""Benchmark batch exports with different workers x threads splits (Linux).

Usage:
    uv run python scripts/bench_workers.py samples                # CC0 samples (default)
    uv run python scripts/bench_workers.py reference --count 6    # the private reference set
    uv run python scripts/bench_workers.py samples --splits 1x4 2x2 4x1 --repeat 2
    uv run python scripts/bench_workers.py reference --splits auto 1x4   # the default policy

Each run is a fresh ``picturesq export --json`` of the same originals with
``--workers W --threads T`` (``auto``: neither, so the memory budget and cores decide),
into a temporary folder outside the repo (deleted afterwards; nothing is written into the
repo). Splits are interleaved across repeats, so a busy
moment on the machine doesn't land on one split only. Reported per split (median over
repeats): wall time, seconds per photo, and the peak memory of the whole process tree
(the CLI plus its workers, summed resident memory sampled every 50 ms).

Run it on a quiet machine: other work skews the times more than the splits differ.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCES = {"samples": REPO / "reference" / "samples", "reference": REPO / "reference" / "raw"}
RAW_SUFFIXES = {".dng", ".raf", ".arw", ".nef", ".cr2", ".cr3"}


def _children(pid: int) -> list[int]:
    found = []
    for stat in Path("/proc").glob("[0-9]*/stat"):
        try:
            fields = stat.read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        if int(fields[1]) == pid:  # field 4, ppid, after the ")" of the command name
            found.append(int(stat.parent.name))
    return found


def _rss(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


def _tree_rss(root: int) -> int:
    total, queue = 0, [root]
    while queue:
        pid = queue.pop()
        total += _rss(pid)
        queue.extend(_children(pid))
    return total


def _split_options(split: str) -> list[str]:
    if split == "auto":
        return []
    workers, threads = split.split("x")
    return ["--workers", workers, "--threads", threads]


def run_once(originals: list[Path], split: str, budget: str | None) -> dict[str, float]:
    with tempfile.TemporaryDirectory(prefix="picturesq-bench-") as tmp:
        project, out = Path(tmp) / "project", Path(tmp) / "out"
        project.mkdir()
        for original in originals:
            (project / original.name).symlink_to(original.resolve())
        command = [
            sys.executable,
            "-c",
            "from picturesq.cli import app; app()",
            *_split_options(split),
            *(["--memory-budget", budget] if budget else []),
            "export",
            str(project),
            "--out",
            str(out),
            "--json",
        ]
        started = time.perf_counter()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        peak = 0
        done = threading.Event()

        def sample() -> None:
            nonlocal peak
            while not done.is_set():
                peak = max(peak, _tree_rss(process.pid))
                done.wait(0.05)

        sampler = threading.Thread(target=sample)
        sampler.start()
        stdout, stderr = process.communicate()
        seconds = time.perf_counter() - started
        done.set()
        sampler.join()
        if process.returncode != 0:
            raise SystemExit(f"export failed ({split}):\n{stderr.decode()}")
        summary = json.loads(stdout)["summary"]
        return {"seconds": seconds, "peak": peak, "workers": summary["workers"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("source", nargs="?", default="samples", choices=sorted(SOURCES))
    parser.add_argument("--count", type=int, default=6, help="originals to export (default 6)")
    parser.add_argument(
        "--splits", nargs="+", default=["1x4", "2x2"], help="WORKERSxTHREADS, or auto"
    )
    parser.add_argument("--memory-budget", help="passed on (default: picturesq's own)")
    parser.add_argument("--repeat", type=int, default=1)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("reads memory from /proc: Linux only")

    folder = SOURCES[args.source]
    originals = sorted(p for p in folder.iterdir() if p.suffix.lower() in RAW_SUFFIXES)
    originals = originals[: args.count]
    if not originals:
        raise SystemExit(f"no originals in {folder}")
    for original in originals:  # warm the file cache so the first split isn't penalised
        original.read_bytes()
    splits: list[str] = args.splits
    print(f"{len(originals)} originals from {args.source}, {args.repeat} repeat(s)")

    runs: dict[str, list[dict[str, float]]] = {split: [] for split in splits}
    for repeat in range(args.repeat):
        for split in splits:
            measured = run_once(originals, split, args.memory_budget)
            runs[split].append(measured)
            print(
                f"  run {repeat + 1}: {split}: {measured['seconds']:.1f} s, "
                f"peak {measured['peak'] / 2**20:.0f} MiB, {measured['workers']} worker(s)",
                flush=True,
            )
    print("\n| Workers x threads | Wall time | s/photo | Peak memory |\n|---|---|---|---|")
    for split, measured in runs.items():
        seconds = statistics.median(run["seconds"] for run in measured)
        peak = statistics.median(run["peak"] for run in measured)
        print(
            f"| {split} | {seconds:.1f} s | {seconds / len(originals):.1f} | "
            f"{peak / 2**20:.0f} MiB |"
        )


if __name__ == "__main__":
    main()
