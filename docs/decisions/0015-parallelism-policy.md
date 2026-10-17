# ADR-0015: Threads within a photo, photos scheduled by memory, and both as machine settings

**Status:** Accepted · 2026-10-18

## Context
An export of one 33 MP Pocket 4 photo takes ~28 s on a 4-core laptop (i5-8250U, 8 hardware threads, ~8 GB RAM) and peaks at ~1 GiB (§5). Batches are tens to hundreds of photos. Two ways to use more of the machine:

- **Threads within a photo** (#68, #70): numpy releases Python's GIL inside each operation, so threads working on separate blocks of one image run at once and share the image. No extra full-resolution copies.
- **Workers** (#22): separate processes, each exporting a different photo. Nothing in one photo waits on another, but every worker holds its own photo peak.

Memory decides how far workers can go: a laptop with ~6.5 GB available fits 3 photo peaks of a 33 MP photo, a 16 MP camera's peak is half that, and a batch can mix both. A fixed worker count sized by the largest photo would run small photos one at a time; one sized by the smallest would swap on the large ones.

## Decision
1. **Threads: one per physical core, over cache-sized blocks** (`picturesq.parallel`, #70). Hyperthreads share a core's arithmetic units and cache, so they add nothing to numpy's tight loops (measured: 8 threads were slower than 4).
2. **Photos are scheduled by memory** (`picturesq.pipeline.workers`):
   - Each photo's photo peak is predicted from its pixel count, read from the original's header (milliseconds, no decode), with the measured model in `pipeline/budget.py`.
   - A photo starts only when its peak fits beside the running ones within the **memory budget**. One photo always runs, even if it alone exceeds the budget (the CLI warns).
   - Memory is counted per process: each worker process pays the model's fixed part once (it holds the interpreter and libraries even when idle), and each running photo adds its per-pixel part. The pool has as many workers as the smallest photos could ever fill.
   - Largest photos start first, so a big photo doesn't run alone at the end. Photos start strictly in that order: a small photo never overtakes a waiting large one, which would delay it again.
   - Each photo's threads are chosen when it starts: physical cores ÷ photos running then. Example: six 33 MP and four 12 MP photos with room for one 33 MP photo at a time run the large ones one at a time on 4 threads, then the small ones two at a time on 2 threads each.
   - At most cores ÷ 2 photos run at once by default, from the measurement below. `--workers N` sets that cap and `--threads N` fixes the threads.
3. **Default budget: 60 % of available memory** (Linux `MemAvailable` and cgroup v2 `memory.max`, macOS `vm_stat`, Windows `GlobalMemoryStatusEx`; no new dependency). The rest is for the parent process, the file cache and everything else running. If available memory can't be read, photos run one at a time.
4. **Workers are spawned, not forked.** A fork copies the parent's thread pools without their threads, and numpy can then deadlock on a lock a vanished thread held. Spawning costs ~1 s of imports per worker, once per run.
5. **Machine settings stay out of project config.** `--threads`, `--block-pixels`, `--workers` and `--memory-budget` (and their `PICTURESQ_*` environment variables) describe the computer, not the photos. The same project exports on a laptop and a workstation, and a sidecar must not change with the machine. Output is byte-identical for any workers, threads and block size (tested: 1 vs 2 workers on two CC0 samples, every JPEG and sidecar).

## Measurement (preliminary)
`scripts/bench_workers.py`, 6 Pocket 4 originals (33 MP) and the 6 CC0 samples (12-26 MP), i5-8250U under WSL2, default config. Other jobs were running at the same time (load average 2-6), so these are relative numbers, each comparison run back to back:

| Batch | 1 photo × 4 threads | 2 × 2 | 4 × 1 |
|---|---|---|---|
| 6 × 33 MP, run 1 (2 repeats) | 17.6 s/photo · 1.0 GiB | 16.7 · 1.3 GiB | – |
| 6 × 33 MP, run 2 | 17.9 · 1.0 GiB | 14.9 · 1.5 GiB | 18.7 · 2.0 GiB |
| 6 × 33 MP, final scheduler (`auto` = 2 × 2), 2 repeats | 17.2 · 1.0 GiB | 15.3 · 1.5 GiB | – |
| 6 CC0 samples, 2 repeats | 14.7 · 0.9 GiB | 12.8 · 1.1 GiB | 12.8 · 1.4 GiB |

**2 photos × 2 threads is 5-17 % faster than 1 × 4 for batches on this laptop**, for ~50 % more memory. 4 × 1 is no faster than 2 × 2 and uses the most memory. Why: about a third of a photo's time is serial for its threads (LibRaw's decode, Pillow's JPEG encoding, Python between numpy calls), and a second photo fills those gaps. A third or fourth photo only competes for the same memory bandwidth and cache. The scheduler's measured peak for two 33 MP photos (~1.5 GiB) is well under its prediction (2.3 GiB): the model is an upper bound per photo, and two photos rarely peak at the same moment.

## Consequences
- + Batches on the 4-core laptop are ~11 % faster by default, and mixed batches use the budget fully: small photos pair up, large ones run alone with every core.
- + A machine with more memory or cores gets more photos at once without any config.
- + Byte-identical exports also fixed a reproducibility bug: the embedded sRGB ICC profile carried the time it was built, so two runs (or two workers) wrote different JPEG bytes. Its date is now fixed.
- − The cap of cores ÷ 2 is fitted to one laptop. Re-run `scripts/bench_workers.py` on other machines (an 8+ core desktop, Apple silicon) before trusting it there.
- − Memory is predicted, not observed: a photo the model underestimates could push the machine into swap. The slow memory test keeps the model an upper bound for the reference set and the samples.
- − Unverified: the macOS (`vm_stat`) and Windows (`GlobalMemoryStatusEx`) memory readers have only fake-input tests here. The Windows one runs in CI.
