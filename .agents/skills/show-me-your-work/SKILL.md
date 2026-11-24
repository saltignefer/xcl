---
name: show-me-your-work
description: Keep an append-only TSV decision log for long-running, multi-phase, or unattended agent work (e.g. debugging retail titles or sweeping GPU test failures) so a human can audit every fork and proof quickly.
disable-model-invocation: true
---

# Show me your work

Keep one canonical append-only TSV log (`decisions.tsv` locally, untracked by git unless a reviewer explicitly needs the trail committed).

## Columns (single-line cells, tab-separated)

```tsv
ts	phase	decision	why	evidence	result
```

- `ts`: ISO-8601 UTC timestamp.
- `phase`: workstream or stage (`start` reserved for the first row written by a new agent run).
- `decision`: concrete choice or action, plain words.
- `why`: plain reason, no jargon.
- `evidence`: pointer that proves it (commit SHA, `file:line`, test JSON path, shader dump path). Never a paragraph.
- `result`: concrete outcome (`ok: 88/93`, `reverted`, `INCONCLUSIVE`, `blocked`).

## Rules

1. **Log decision points, not every shell command:** chosen approach, verified unit, pivot/revert with trigger, blocker, or newly added gate.
2. **Append-only:** never edit or delete past rows. Supersede a wrong decision with a new row pointing to the evidence that overturned it.
3. **Audit before handback:** verify every row matches an actual action and every evidence pointer resolves. Strip local home paths and personal identifiers before committing or sharing publicly.
4. **Cross-model review when stakes are high:** have a second model scan the trail for weak evidence, skipped verification, or symptom-papering, and include an `Attention` section naming the reviewer model.
