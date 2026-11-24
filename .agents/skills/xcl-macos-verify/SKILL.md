---
name: xcl-macos-verify
description: Cross-compile XCL on macOS (x86_64-pc-windows-msvc) and verify GPU tests under CrossOver + vkd3d-proton 3.1 + KosmicKrisp. Use when editing crates/xcl/src/gpu/, crates/xcl/src/hle/d3d12x/, or diagnosing macOS/Wine/Metal/vkd3d-proton failures.
---

# XCL macOS GPU Verification

Verify every runtime or recompiler change against real Metal execution via `scripts/preflight_macos.py`. Compiling without running the test binary is not verification.

## 1. Hygiene gate

Run before building or committing:

```sh
python3 scripts/preflight_macos.py --check-hygiene --base origin/main
```

Completion criterion: `hygiene ok` (clean `saltis` noreply identity, no forbidden dumps/binaries, no new `#[ignore]`, branch within 25 commits of base).

## 2. Red-to-green targeted check

Before editing an existing workaround in `real.rs`, `sparse.rs`, `list_x.rs`, or `recomp/`, check why it exists (`git log -S <symbol> -p -n 3`) so you do not re-introduce a retail-game regression.

Build and run the exact failing test(s) first:

```sh
python3 scripts/preflight_macos.py --build --no-cache \
  --test gpu::recomp::tests::<test_name>
```

When diagnosing a shader, COM vtable, or Metal failure:
- Dump generated MSL with `MESA_KK_DEBUG=msl` and `MESA_SHADER_CACHE_DISABLE=1 VKD3D_SHADER_CACHE_PATH=0`.
- Inspect `d3d12core.dll` directly (`strings` / `llvm-symbolizer`) instead of guessing which `iface->lpVtbl` assertions exist.
- **Attack the premise:** when two fixes sharing one premise fail the same gate, stop. Write down the shared premise in one sentence and run a 15-line standalone probe (`arch -x86_64` or plain D3D12) to test that premise directly before writing a third fix.

Completion criterion: target test reproduces red before the fix and passes green (`ok`, not `SKIPPED`) after.

## 3. Full GPU suite and regression diff

Run all `gpu_` tests with crash isolation and compare against the saved baseline:

```sh
python3 scripts/preflight_macos.py --suite --out /tmp/xcl-kk-after.json --baseline /tmp/xcl-kk-before.json
```

Completion criterion: zero regressions vs baseline, and report exact `ok / SKIPPED / FAILED / ABORT / ignored` counts (never count `SKIPPED` as `ok`).
