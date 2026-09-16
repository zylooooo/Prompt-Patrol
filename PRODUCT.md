# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: instructors in university software-engineering courses, reviewing
short student answers they suspect may be AI-generated. Secondary: teaching
assistants, delegated review authority under an instructor (3-tier RBAC:
`root_admin → instructor → teaching_assistant`). Job-to-be-done: submit a
single answer or a CSV batch of answers, get a flagged-for-review result,
and decide for themselves — the tool surfaces signal, it does not adjudicate.

## Product Purpose

Prompt Patrol is an instructor-facing triage tool that flags potentially
AI-generated short student answers in software-engineering courses for
human review. It exists to speed up and calibrate an instructor's own
judgment call, not to replace it. Success is an instructor spending less
time scanning answers and more time reviewing the ones actually worth a
second look — with a defensible, auditable trail behind every flag.

## Positioning

Triage, not verdict. Every check resolves to one of three explicit states —
`ai_generated`, `human_written`, or `uncertain` — where `uncertain` is a
first-class abstention outcome, not an error path. Detection strictness is
a server-calibrated named tier (`lenient`/`standard`/`strict`), never a raw
client-supplied threshold. Built specifically for short SE-course answers
(not generic essay-length AI-detection), with a human-in-the-loop review
workflow and a full audit trail as the differentiator against a generic
plagiarism/AI-detector tool.

## Operating Context

- **Single check**: instructor pastes/enters one short answer, picks a
  strictness tier, gets back a verdict + score + (when available)
  confidence and explanation.
- **Batch check**: instructor uploads a CSV, maps its columns, and polls an
  async job (`202` + `job_id`) for per-row results — same `CheckResult`
  shape as a single check, rendered in one shared table/results renderer.
- **History**: instructors review past checks and batch results
  (`HistoryPage`, `HistoryDetailPage`).
- **User & TA management**: root_admin/instructor manage instructor and TA
  accounts, role changes, deactivation, and supervisor assignment
  (`UsersPage`, `TeachingAssistantsPage`, `ChangeRoleDialog`,
  `SupervisorDialog`).
- **Auth**: invite-only sign-in via Auth0 (Database email/password
  connection, no self-service signup, no third-party federation);
  session-cookie based (BFF pattern), 30 min idle / 4 h absolute timeout.
- Detector service is stateless and swappable behind a `GET /api/detector`
  capability-flag surface — the UI must degrade gracefully as detector
  capabilities (e.g. `confidence`, `explanation`, `requires_question_text`)
  come and go, not assume every field is always populated.

## Capabilities and Constraints

- `verdict` is always one of the 3-state enum; `uncertain` must be
  presented as a legitimate outcome in the UI, not styled as an error.
- `raw_score` is not a probability and must never be shown as a percentage;
  `confidence` (nullable) is the only display-safe number, and is null
  until E2 calibration lands.
- `CheckResult` fields have tiers the UI must respect: Tier 1 always
  present; Tier 2 nullable (confidence, abstain_reason, truncated); Tier 3
  a removable module that ships null until promoted (explanation, spans).
- Object-level auth asymmetry is intentional: list/filter endpoints
  silently scope to the caller; object-fetch of someone else's resource
  returns 404, not 403.
- PDPA / data-retention policy for stored student answers is unassigned
  and unresolved — `retain_answer` UI/behavior is provisional pending an
  owner; don't design as if this is settled.
- Abstention rule for `uncertain` (token-floor vs. score-band vs.
  confidence-floor) is not yet decided by ML — don't hardcode an
  explanation of *why* something is uncertain beyond what the API returns.
- GPTZero is evaluation-only and must never appear as a live/serving-path
  option in the UI.
- Full constraint set, decision log, and open questions live in
  `docs/openapi.yaml` and `CLAUDE.md` — treat those as authoritative and
  check them before assuming a constraint has changed.

## Evidence on Hand

- No sponsor-provided mockups, testimonials, or case studies exist yet —
  do not fabricate any.
- Real (non-fabricated) UI reference: the current implemented frontend
  under `apps/web/src` (AppShell, SingleCheckTab, BatchTab,
  BatchResultsTable, ResultPanel, ScoreGauge, SignalsList, VerdictChip,
  ModelStatusBadge, UsersPage, TeachingAssistantsPage) — treat as the
  incumbent visual/interaction baseline, not as approved final design.
- Sample data for smoke testing exists at a `trial-data.csv` fixture used
  during batch-upload manual testing (per project memory) — not committed
  product evidence, just a dev fixture.

## Product Principles

1. Never let the UI imply certainty the model doesn't have — `uncertain`
   and null Tier 2/3 fields are normal states, not degraded ones.
2. Speed of instructor triage over completeness of ML explanation — the
   explanation/spans module is a nice-to-have UI module, not the point.
3. Every action that touches another user's account or a review decision
   must be auditable and attributable — this is a compliance-adjacent tool
   handling student data, not just an internal utility.
4. Design for a detector that will change (capability flags, tiered
   fields) — don't build UI that assumes today's detector's shape is
   permanent.
5. Instructor and TA roles see meaningfully different surfaces
   (delegated authority, not identical permissions) — don't flatten the
   RBAC tiers into one generic "user" experience.

## Accessibility & Inclusion

No project-specific accessibility standard has been established yet beyond
general web accessibility practice. Not yet confirmed with the sponsor —
treat as an open gap, not a settled requirement.
