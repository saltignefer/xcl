---
name: repo-correct
description: Find mistakes agents keep repeating in this repository and eliminate each class structurally (architecture -> types/preflight/CI -> behavioral tests -> docs last). Use when a mistake has occurred twice or after a postmortem.
disable-model-invocation: true
---

# Repo correct

Assume every future contributor is an agent that opens only two files, copies the nearest pattern, and stops as soon as it compiles. Design the repo so what looks right locally is right globally.

## Process

1. **Find repeated mistake classes:** inspect recent commits, reverts, PR comments, and workaround comments. A class qualifies once it has happened twice.
2. **Fix at the highest level that holds:**
   1. **Architecture:** one owner per state, one supported API, delete legacy patterns agents might copy.
   2. **Types, preflight, or CI:** make invalid state uncompilable, or fail `scripts/preflight_macos.py` / `.github/workflows/fork-hygiene.yml` with an error message naming the exact fix.
   3. **Behavioral tests:** add a test that fails when the bug returns and keeps passing across internal refactors.
   4. **Docs / `AGENTS.md` last:** only for judgment calls. Nothing fails when an agent skips prose.
3. **Prove the new gate:** verify the check actually fails on a real past mistake before landing it.
4. **Keep `Rule -> Enforcer` current in `AGENTS.md`:** every rule names what enforces it. If a rule was violated despite being written down, escalate it to a higher level instead of rewording the prose. Drop a rule once the mistake is structurally impossible.
