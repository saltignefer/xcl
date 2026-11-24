---
name: xcl-architect
description: Sketch types, COM/memory ownership, and module boundaries before writing code on non-trivial XCL features or refactors. Use before large edits to d3d12x, sparse/UMA memory, or the RDNA2 recompiler.
disable-model-invocation: true
---

# XCL architect

Before writing code on a non-trivial change, trace every subsystem it touches and sketch **two materially different shapes** (types, function signatures, state ownership, and module boundaries).

## Checklist before picking a shape

1. **Single owner per state:** name which module owns each table, mutex, GPU resource, or lifetime (`real.rs`, `sparse.rs`, `title_textures.rs`, `late_release.rs`, `list_x.rs`). Avoid shared mutable singletons when ownership can stay local.
2. **One supported way per task:** if an old workaround exists alongside the new path, plan to migrate callers and delete the old path in the same wave.
3. **Boundary discipline:** enforce Wine/vkd3d-proton ABI and validation at the boundary (`guard.rs`, `real.rs`) rather than scattering guards across internal callers.
4. **Small caller surface:** prefer deep modules whose callers need minimal knowledge of vtables, sparse tiles, or Rosetta 4 KiB splits.
5. **Split into stackable units (<400 LOC per PR):** preparation (no behavior change) -> core logic + failing-first tests -> wiring/enablement -> diagnostics.

Pick the simpler shape, state the concrete tradeoff against the rejected shape in 3-5 lines, then implement one verifiable unit at a time.
