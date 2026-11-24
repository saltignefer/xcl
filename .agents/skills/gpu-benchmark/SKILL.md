---
name: gpu-benchmark
description: Vet any GPU, recompiler, DXC, or Wine/Metal performance measurement before reporting or acting on it. Enforces limiter identification, cache/build parity, error counting, repeatability, and proof that GPU work actually ran.
disable-model-invocation: true
---

# GPU benchmark checklist

Use before publishing any speedup, FPS, latency, shader-compile, or memory-import number. Answer every question from a real run, not code inspection.

## Before running

- Write down the exact claim you intend to ship (metric, unit, workload, hardware).
- Inspect the harness to know what it times, counts, and skips.
- Check host load (`uptime`) and close competing GPU workloads.

## Seven mandatory checks

1. **Name the limiter.** Profile in a separate unmeasured run (CPU vs GPU vs DXC vs Wine/Rosetta vs fence wait). If a change did not move the number, the limiter explains why.
2. **Verify parity and tuning.** Compare release vs release, identical DXC/vkd3d/KosmicKrisp commits, and explicit cache state (`MESA_SHADER_CACHE_DISABLE=1 VKD3D_SHADER_CACHE_PATH=0` for cold-compile benchmarks; pre-warmed both sides for steady-state FPS).
3. **Check arithmetic limits.** Compare claimed speedup against the profiled share of the changed phase and hardware memory/compute bounds. Numbers past the limit usually mean a cache hit, skipped work, or a bug.
4. **Count errors and skips.** Record `ok / SKIPPED / FAILED / ABORT / TIMEOUT` and verify output bytes or rendered pixels are valid. Fast rejections and early returns produce fake speedups.
5. **Prove repeatability.** Run at least 5 alternating A/B trials (`A, B, A, B, ...`) and report median and min..max range. Gaps smaller than run-to-run variance are not measurable differences.
6. **Check end-to-end relevance.** Report a microbenchmark next to its share of total frame or test time.
7. **Prove the GPU work happened.** Confirm command lists submitted, fences waited for GPU completion, readback/render outputs matched expected values, and neither DXC nor Metal discarded dead code.

## Verdict format

Lead with `faster`, `slower`, `no measurable difference`, or `inconclusive` (mandatory whenever the limiter is unknown, caches were mismatched, or checks 4 and 7 were skipped). State metric, unit, median, range, trial count, hardware, and limiter.
