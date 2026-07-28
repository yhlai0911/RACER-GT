# Issue tracker

Issues for this repository live as **local markdown** in `review/TICKETS.md`.

`review/` is gitignored. That is deliberate: the ticket list carries candidate
journals, positioning trade-offs, and findings such as "this method is not more
accurate than a simple mean" that should not appear in a public repository's
GitHub Issues before the manuscript is settled. Move them to GitHub Issues once
the paper's claims are fixed.

Skills that read or write issues (`to-tickets`, `triage`, `to-spec`, `qa`) should
append to and update `review/TICKETS.md` rather than calling `gh issue`.

Related documents in the same directory:

- `review/PLAN-<date>-<slug>.md` — the research programme and its ordering
- `review/SPEC-<slug>.md` — module specifications
- `review/PILOT-<slug>.md` — data-collection protocols
- `review/HANDOFF-<slug>.md` — session handovers

PRs as a request surface: off.
