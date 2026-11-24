---
name: xcl-interrogate
description: Adversarial code review for XCL changes where only findings proven by running real code survive. Drops style nits and unproven speculation. Use for adversarial review or stress-testing a PR before merge.
disable-model-invocation: true
---

# XCL interrogate (adversarial review)

Try to break the change. Only findings proven by a real run survive. Report findings; do not silently patch them during review.

## Scope

Review the diff from merge base with `origin/main` through the working tree (or the user-specified commit/PR). Restate the intent in one paragraph before attacking it.

## Rules of attack

1. **Prove every finding with a run:** a failing test, a standalone repro script, a `strings`/`objdump` inspection of `d3d12core.dll`, a `MESA_KK_DEBUG=msl` shader dump, or a failing `scripts/preflight_macos.py` run.
2. **Drop everything you did not run:** style nits, naming preferences, speculative future risks, and unverified code-reading guesses do not appear in Findings.
3. **Verify each finding twice:** rerun the exact repro command to confirm it reproduces the wrong behavior and actually violates the stated intent.
4. **"No verified findings" is a valid outcome.** Never invent nits to look thorough.

## Output

- **Intent:** one-paragraph restatement.
- **Verified findings:** for each finding, include title, `file:line`, exact command, actual output, and expected behavior per intent.
- **Dropped:** count of unproven ideas discarded and why.
