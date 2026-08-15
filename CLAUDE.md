# CLAUDE.md — Prompt Patrol

This file is loaded automatically by Claude Code at the start of every session
in this repo. It exists so you don't have to re-explain the project, the
contract, or the ground rules every time.

---

## 0. Non-negotiable ground rules

- **Never run `git commit`, `git push`, `git merge --no-ff` into shared
  branches, or anything that rewrites history (`rebase -i`, `commit --amend`,
  `push --force`).** This applies even if I ask for it mid-session — if I
  actually want a commit made, I will do it myself. Your job stops at leaving
  a clean, reviewable working tree.
- Do not open PRs, tag releases, or push branches to remote.
- You may freely: create/edit files, run builds, run tests, run linters, run
  migrations locally, install dependencies, use `git diff` / `git status` /
  `git log` for your own context.
- If a task seems to require a commit to proceed (e.g. a tool wants a clean
  tree), stop and tell me instead of committing around it.

## 1. What this project is

**Prompt Patrol** — a university capstone project. An **instructor-facing
triage tool** (explicitly not a verdict system) that flags potentially
AI-generated short student answers in software-engineering courses for human
review.

- Sponsor: a faculty member acting as project sponsor/client
- Team: backend/DevOps lead (primary owner of this repo), a frontend
  developer, 1 PM, 3 ML developers
- Known resourcing skew: 3 ML devs vs. 1 backend engineer, while the web app
  (E4) is a Must deliverable at every milestone. Don't assume backend has
  ML-dev-equivalent bandwidth.
- Full requirements/scope live in `Proposal.md` and the sponsor Q&A doc in
  the repo — read those before assuming scope.

## 2. Tech stack

| Layer            | Choice                                                                                                                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Frontend         | React + TypeScript + Tailwind                                                                                                                                                   |
| Backend          | Python + FastAPI                                                                                                                                                                |
| Persistence      | PostgreSQL + SQLAlchemy                                                                                                                                                         |
| Async decoupling | SQS (batch job submission)                                                                                                                                                      |
| Auth             | Entra ID (OIDC), BFF pattern, httpOnly session cookie — **not** a token-based SPA auth flow                                                                                     |
| Deploy           | Docker → ECS Fargate                                                                                                                                                            |
| Frontend hosting | CloudFront + S3 (SPA)                                                                                                                                                           |
| Ingress          | API Gateway (hard-enforced, security-group restricted)                                                                                                                          |
| Secrets          | Secrets Manager                                                                                                                                                                 |
| Observability    | CloudWatch                                                                                                                                                                      |
| Images           | ECR                                                                                                                                                                             |
| Mocking          | Prism (mocks `openapi.yaml` for frontend dev before real endpoints exist)                                                                                                       |
| ML               | PyTorch, HuggingFace, LoRA fine-tuning (DeBERTa/RoBERTa), MLflow tracking — owned by ML subteam, backend does not implement this but must respect the service boundary (see §5) |

## 3. The contract: `openapi.yaml` — current, not final

**`openapi.yaml` is not a finished spec — it's the best current record of
what the team has discussed and agreed so far.** Modules are still being
added (`batches` and `audit` don't exist yet), and even the completed
modules carry open questions and provisional decisions — see the inline
`OPEN QUESTION` / `OPEN —` comments and the decision log at the bottom.

**Do not treat the contract as ground truth to blindly implement against —
but this is not a license to disagree with everything either.** Most of the
contract is already the product of real discussion with the team and holds
up fine. The bar for flagging something is that it's actually wrong,
underspecified, internally inconsistent, or impractical to build as
written — not "I would have designed it differently" or a minor style
preference. If it's a legitimate design tradeoff that's already been made
and documented, implement it as written.

**Do this check *before* writing implementation code for a module, not
partway through it** — go in already confident the section holds up, rather
than finding out as you go. That said, if a genuine problem only becomes
apparent once you're already implementing, raise it immediately at that
point rather than pushing through to avoid backtracking — "I already
started" is not a reason to implement around a real problem. Before
implementing a given endpoint or schema, read the relevant section of the
contract end to end (including its changelog/decision-log entries) and
confirm it actually holds up. If it doesn't:

1. **Stop before implementing and flag it explicitly** — don't start coding
   against an interpretation you're not confident in, and don't discover the
   problem three functions in and quietly work around it.
2. State what you found, why it's a genuine problem (not a preference), and
   — if you have a view — 1-2 concrete ways to resolve it.
3. Wait for a decision on the approach.
4. Only then update `openapi.yaml` first (new changelog entry + decision-log
   entry, matching the existing style in the file), and implement against
   the updated contract.

If the section checks out, just implement it — no need to narrate that you
reviewed it and found nothing wrong.

Read the changelog and decision log before assuming *why* something is
shaped the way it is — most "obvious simplifications" have already been
tried and rejected there for a documented reason. But "it's already
documented" is not the same as "it's correct" — if a documented decision
doesn't survive contact with real implementation, that's exactly the kind of
thing to raise, not defer to.

Conventions currently in the contract that backend code should follow
*unless you've flagged a problem with one and it's been discussed*:

- **`strictness` is a named enum (`lenient`/`standard`/`strict`), never a raw
  float threshold from the client.** Thresholds are a server-side calibration
  artifact tied to the currently served model. Do not add a code path that
  accepts a numeric threshold from a request body or query param.
- **`model_version` is server-selected, never client-settable.** Same for
  `actor_id` — it comes from the gateway authorizer context, never the
  request body. `CheckCreateRequest` uses `additionalProperties: false`
  specifically to make a client-supplied `actor_id`/`threshold`/
  `model_version` a hard `400`, not a silently ignored field.
- **`verdict` is a 3-state machine enum** (`ai_generated` / `human_written` /
  `uncertain`) — `uncertain` is a first-class outcome (abstention), not an
  error path. Display copy belongs in the frontend, not the API.
- **Object-level authorization asymmetry, intentional, don't "fix" it:**
  - On *filters* (e.g. `actor_id` query param on `GET /api/checks`): silently
    override to the caller's own `user_id` rather than reject. Rejecting
    would confirm the target id exists (an enumeration oracle).
  - On *creates* (`POST /api/checks` body): reject loudly (`400`) on unknown
    fields. Nothing to enumerate on a create, so fail fast instead.
  - On *object fetch* for another instructor's resource: `404`, not `403`.
    `403` would leak that the resource exists.
- **`CheckResult` field tiers** — the frontend degrades gracefully on null.
  Never make a Tier 2/3 field required in a migration without a version bump
  and frontend coordination:
  - Tier 1 (always present): `check_id`, `verdict`, `raw_score`, `detector`,
    `created_at`, `actor_id`
  - Tier 2 (nullable): `confidence`, `abstain_reason`, `truncated`
  - Tier 3 (removable UI module, ships null until promoted): `explanation`,
    `spans`
- **Soft-delete everywhere** (`deleted_at` timestamp, not a status enum) —
  users and sessions. Checks are immutable audit facts and are never
  soft-deleted; only `answer_text` is purgeable, `answer_char_len` survives
  the purge for E3 analysis.
- **`GET /api/detector` capability-flag pattern**: anything about the served
  model that ML hasn't decided yet (e.g. `requires_question_text`) is
  expressed as a runtime flag the client reads, not baked into the schema.
  If you're about to make a schema field required because "the model needs
  it", check whether it should be a capability flag instead.
- **`raw_score` is not a probability and must never be surfaced as a
  percentage.** `confidence` (nullable, null until E2 calibration lands) is
  the only display-safe number.

## 4. Schema design checklist (apply when designing new modules, e.g. `batches`/`audit`)

Before adding a new schema or endpoint to the contract, run it through the
same reasoning that shaped `checks`:

- **Tier every field before writing it down.** Tier 1 = always present /
  genuine invariant. Tier 2 = nullable, populated once some pipeline step
  exists (e.g. a calibration artifact). Tier 3 = a whole UI module that may
  not ship, declared nullable now so shipping it later isn't breaking.
  Don't make something required just because it's "supposed to" be there
  eventually.
- **Capability-flag test.** Before marking a field required, ask: *is this a
  genuine domain invariant, or a fact about the currently served model/
  pipeline that could change on the next deploy?* If it's the latter, it
  belongs on a capabilities endpoint (like `GET /api/detector`) as a runtime
  flag the client reads — not hardcoded into the schema.
- **Attribution never comes from the client.** Actor/owner identity on any
  create body is derived from the gateway authorizer context, same as
  `checks.actor_id`. If a new module needs to know "who did this," that's
  `additionalProperties: false` + server-side injection, not a client field.
- **Filter vs. create asymmetry.** Object-scoping *filters* (e.g. listing
  someone else's batches) silently override to the caller's own scope rather
  than reject, to avoid an existence-enumeration oracle. Object-scoping on
  *creates* rejects loudly on invalid/unknown fields — nothing to enumerate
  on a create.
- **Reuse shared shapes.** If a new resource's rows are conceptually the same
  object as an existing schema (e.g. a batch result row vs. `CheckResult`),
  reuse it rather than defining a near-duplicate — one frontend renderer,
  one place to fix bugs.
- **Batches are already decided as async**: `POST /api/batches` → `202` +
  `job_id` + polling (per the existing decision log precedent). Don't
  reinvent this pattern for a new async surface — extend it.
- **New shared schemas need the same sign-off `CheckResult` got** — flag if
  a schema crosses into ML or frontend territory (e.g. a batch summary
  shape) rather than deciding it solo and merging it straight into the
  contract.

## 5. Service boundary — backend vs. detector

```text
SPA → POST /api/checks → backend → detector service
                            │         (stateless, no DB, no user
                            │          identity, no threshold policy)
                            ├──> checks table
                            └──> audit table (unconditional)
```

The detector service does exactly one thing: text in, normalized `[0,1]`
score out, monotonically increasing in AI-likelihood. It never touches
Postgres, never sees `user_id`, never decides a verdict. Persistence,
instructor identity, authorization, audit, and threshold/calibration policy
all live in the backend monolith — do not let detector-adapter code creep
into owning any of those.

GPTZero is evaluation-only. Never wire it into the serving path, even
temporarily "for the PoC" — it's an overseas third-party API call on every
check, which is a PDPA exposure with no product benefit.

## 6. Auth architecture

- Prompt Patrol is an **OIDC Relying Party**, not an OAuth client. No access
  token, no refresh token, no JWT is ever stored — the ID token is validated
  at callback and discarded.
- Session = opaque 256-bit id in an `__Host-` cookie, `Secure` + `HttpOnly` +
  `SameSite=Strict`. It's a DB lookup key, not a bearer credential.
- Authority is **tenant-scoped**, never `/common`.
- **BFF pattern**: the security property that matters is that the token is
  structurally unreadable to JS — this is why the BFF complexity is worth it,
  not because it's "more validated."
- **NAT Gateway is scoped to exactly the callback handler's egress to Entra's
  token endpoint.** It has nothing to do with OIDC token acquisition
  generally (that's browser-side redirect). Everything else routes through
  VPC endpoints — zero-egress private tier is a deliberate property for a
  tool handling student data, don't widen the NAT scope casually.
- **RBAC**: 3-tier delegation chain, `root_admin → instructor →
  teaching_assistant`, `provisioned_by` tracks the grantor. No self-service
  signup — a `users` row must exist (allowlisted) before first login; Entra
  owns credentials, the `users` table owns all authorization state. Entra
  claims/groups are never read for role decisions.
- Session lifetime: 30 min sliding idle, 4 h absolute cap, never extended.
  Gateway authorizer runs with `result_ttl_seconds = 0` (no caching — caching
  would reintroduce a revocation window).

## 7. Development workflow

- **Design-first, contract-first sequencing**: Figma mockups → API contract
  (PR-reviewed, ML sign-off on shared schemas like `CheckResult`) →
  FastAPI stubs → frontend builds against Prism mock → swap one stub for a
  real detector = milestone deliverable.
- Expect the contract to take further breaking revisions before midterm —
  that's normal, not a sign something was designed wrong. Check the
  changelog/decision log in `openapi.yaml` before "fixing" something that
  looks inconsistent; it's probably a documented tradeoff.
- Uncertain features (e.g. the explanation module) get a time-boxed spike
  with a binary promote-or-kill outcome, not open-ended exploration.

## 8. Known open gaps (don't silently resolve these — flag them)

- PDPA / data retention policy for stored student answers: unassigned owner.
  `retain_answer` defaulting behavior is provisional pending this.
- Abstention rule for `uncertain` verdicts: token-floor vs. score-band vs.
  confidence-floor — not yet decided by ML, contract enum is written to
  accommodate any of them.
- Whether `instructor → teaching_assistant` delegation authority (already
  implemented per the 0.3.0 chain) should be *live* now vs. gated until E5
  actually has a TA-facing surface.
- Refresh/session-extension strategy beyond the 4h absolute cap: three
  options on the table, none chosen.
- Whether single-check detection stays synchronous depends on which detector
  wins E2 — if a zero-shot detector (Binoculars/Fast-DetectGPT) wins, this
  migrates to the existing `202 + job_id + polling` pattern already used by
  `/api/batches`. `CheckResult` itself is designed to survive that migration
  unchanged.

## 9. How I like to work (applies here too)

- Give me the reasoning, not just the change — call out tradeoffs, edge
  cases, and scalability concerns proactively, even if I didn't ask.
- Push back if something in a request conflicts with a documented decision
  above — don't just implement it and let the contract drift out of sync
  with the actual code.
- Match code-first, prose-second: show the diff/code, then a short "why."
