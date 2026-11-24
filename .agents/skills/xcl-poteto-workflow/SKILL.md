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
| Stale-base batch merges (C1) | Rebase onto latest `main` before PR; flag branches >25 commits behind | `scripts/preflight_macos.py --check-hygiene` |
| Shared monolith doc contention (C2) | Never append to `HANDOFF.md` during code PRs; put design notes in dedicated files or PR body | `AGENTS.md` + PR review |
| Fake / weakened tests (C3) | Count `SKIPPED` separately from `ok`; block new `#[ignore]` in `crates/`; assert real GPU output | `scripts/preflight_macos.py --suite` + `--check-hygiene` |
| Skipped local invariants (C4) | Run one fast preflight lever covering privacy, forbidden files, build, and GPU suite | `scripts/preflight_macos.py` |
| Unverified hardware premises (C5) | Test every Metal / Rosetta / vkd3d-proton premise directly on hardware (`MESA_KK_DEBUG=msl` or standalone probe) | `xcl-macos-verify` + `kk-xcl-verify` |

## 3. Verifiable delivery sequence

1. **Sequence into atomic units**: failing test or minimal repro -> root-cause fix -> verification -> clean commit.
2. **Name the data shape first** before editing COM vtables, memory mappings, or NIR passes.
3. **Fix root causes**: trace symptoms back to the first wrong decision; reject silent error swallowing or speculative guards.
4. **Deslop and privacy audit**: inspect `git diff`, verify `saltis <127887626+saltignefer@users.noreply.github.com>`, and verify zero personal paths/emails or game data before pushing.
5. **Prove it works**: paste exact command, hardware, driver commit, and `ok / SKIPPED / FAILED / ABORT / ignored` counts.
