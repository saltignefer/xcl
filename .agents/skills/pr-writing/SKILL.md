---
name: pr-writing
description: Concise, unslopped technical writing rules for PR descriptions, commit messages, issue comments, and docs in XCL. Strips AI filler and enforces verifiable factual claims.
disable-model-invocation: true
---

# PR and technical writing

Write so a tired maintainer understands on the first read. Every claim must be backed by a run or a `file:line`.

## Rules

- **Lead with the concrete result or root cause.** Cut openers, praise, and chatbot sign-offs.
- **One thought per sentence.** Keep sentences short and active; name the exact file, symbol, flag, or command.
- **No AI filler or decorative formatting:** avoid em dashes, decorative emoji, abstract buzzwords (substrate, paradigm, leverage, enhance, crucial, underscore), trailing `-ing` filler clauses, and restating a heading in its first sentence.
- **Label uncertainty honestly:** separate `measured` facts from `inferred` hypotheses. Never report test counts or smoke blocks you did not run.
- **PR body stays under a one-minute read:** what and why, **What is in it**, **Tested** (exact hardware, driver commit, command, `ok / SKIPPED / FAILED / ABORT / ignored` counts), **Not tested**, **AI use** (exact tool and model name). Link large logs instead of pasting walls of output.
- **Privacy check:** confirm zero personal emails, usernames, or local home paths (`/Users/...`, `C:\Users\...`) appear anywhere in the text.
