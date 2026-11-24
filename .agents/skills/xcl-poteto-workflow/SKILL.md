---
name: xcl-poteto-workflow
description: Poteto-mode engineering workflow and Leonida-hardened structural rules for saltignefer/xcl + kosmickrisp.
disable-model-invocation: true
---

# XCL Poteto Workflow

Workflow for shipping verified, minimal changes across `saltignefer/xcl` and `saltignefer/kosmickrisp` without repeating failure modes measured in large multi-agent emulator repos.

## 1. Scope and claim check

1. Restate the goal and the smallest change that meets it.
2. Check upstream PRs/issues (`gh pr list -R ivall/xcl --search "<keywords>"`) so work is not duplicated.
3. Keep `HANDOFF.md` and `docs/specs/` untouched during feature/fix PRs to avoid multi-PR merge contention on monolith docs.

## 2. Structural rules (encoded from Leonida C1-C5)

| Failure class | Structural rule | Enforcer |
|---|---|---|
| Stale-base batch merges (C1) | Rebase onto latest `main` before PR; flag branches >25 commits behind | `scripts/preflight_macos.py --check-hygiene` + `.github/workflows/fork-hygiene.yml` |
| Shared monolith doc contention (C2) | Never edit `HANDOFF.md` or `docs/specs/` during code PRs; note updates in PR body | `scripts/preflight_macos.py --check-hygiene` + `.github/workflows/fork-hygiene.yml` |
| Fake / weakened tests (C3) | Count `SKIPPED` separately from `ok`; block new `#[ignore]` in `crates/`; test observable behavior, not internals | `scripts/preflight_macos.py --suite` + `--check-hygiene` |
| Skipped local invariants (C4) | Run one fast preflight lever covering privacy, forbidden files, build, and GPU suite | `scripts/preflight_macos.py` |
| Unverified hardware premises (C5) | Test every Metal / Rosetta / vkd3d-proton premise directly on hardware (`MESA_KK_DEBUG=msl` or standalone probe) | `xcl-macos-verify` + `xcl-blast-radius` |

## 3. Behavioral test gate

Judge every new or edited test against two edits:
1. Break the observable GPU/COM behavior -> the test must fail.
2. Refactor internals while preserving observable output -> the test must keep passing.

## 4. Verifiable delivery sequence

1. **Architect before coding** large changes (`xcl-architect`): pick the simplest shape with single state ownership.
2. **Sequence into atomic units**: failing test or minimal repro -> root-cause fix -> verification -> clean commit (<400 LOC per PR).
3. **Fix root causes**: trace symptoms back to the first wrong decision; reject silent error swallowing or speculative guards.
4. **Check blast radius and interrogate** risky runtime/shader diffs (`xcl-blast-radius`, `xcl-interrogate`) and vet any perf numbers (`gpu-benchmark`).
5. **Deslop and privacy audit** (`pr-writing`): inspect `git diff`, run `scripts/preflight_macos.py --check-hygiene`, verify zero personal paths/emails or game data before pushing.
6. **Prove it works**: paste exact command, hardware, driver commit, and `ok / SKIPPED / FAILED / ABORT / ignored` counts.
7. **Encode repeated mistakes** (`repo-correct`): if an agent mistake happens twice, promote the fix to architecture, types, or `preflight_macos.py` instead of rewording docs.
