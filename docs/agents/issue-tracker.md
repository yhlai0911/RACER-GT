# Issue tracker

Issues for this repository live as **local markdown**, one file per ticket, in
`review/tickets/<NN>-<slug>.md`. Files are numbered from `01` in dependency
order, blockers first. `review/TICKETS.md` is an index and legacy-ID mapping
only — it holds no ticket content.

`review/` is gitignored. That is deliberate: the ticket list carries candidate
journals, positioning trade-offs, and findings such as "this method is not more
accurate than a simple mean" that should not appear in a public repository's
GitHub Issues before the manuscript is settled. Move them to GitHub Issues once
the paper's claims are fixed.

Skills that read or write issues (`to-tickets`, `triage`, `to-spec`, `qa`) should
add and update files under `review/tickets/` rather than calling `gh issue`, and
append a row to the index in `review/TICKETS.md`.

Each ticket file carries a `Blocked by` line naming the tickets that gate it,
and a `Status` line using the triage label vocabulary below. Tickets that
predate the one-file-per-ticket layout also carry a `Legacy ID` line (`T-001`
and up); cross-session handoff documents may still refer to those.

## Triage labels

- `ready-for-agent` — blockers cleared, brief is complete enough to start
- `blocked` — waiting on another ticket, named in `Blocked by`
- `in-progress` — being worked; note in the ticket which session owns it
- `done` — acceptance criteria met

A ticket owned by a dedicated session says so at the top of its file. Do not
schedule work for it from another session.

## Acceptance criteria carry the project's three standing rules

Every ticket's acceptance criteria must reflect the discipline adopted on
2026-07-28, after five errors of the same shape landed on one branch and every
one of them was biased in the direction that favoured the conclusion:

- **(a)** List each simplifying assumption and ask, for each, whether its bias
  runs in the direction that favours the conclusion.
- **(b)** Label "measured" and "extrapolated" as separate columns in any table;
  never mix them in one figure.
- **(c)** Before a diagnostic is reported, inject a known perturbation and
  confirm it can fail. A diagnostic that passes is worth nothing until it has
  been shown capable of failing. This applies beyond statistics: a grep that is
  written wrong reports a clean tree either way, so it must first be shown to
  catch a planted violation.

Rule (c) landed in 1.4.0 as `tests/test_diagnostic_power.py`, which caught a
diagnostic with zero power — a uniform rescale is absorbed entirely into the
estimated log scale, so a 2% error and a 20% one produced bit-identical numbers.

Related documents in the same directory:

- `review/PLAN-<date>-<slug>.md` — the research programme and its ordering
- `review/SPEC-<slug>.md` — module specifications
- `review/PILOT-<slug>.md` — data-collection protocols
- `review/HANDOFF-<slug>.md` — session handovers

PRs as a request surface: off.
