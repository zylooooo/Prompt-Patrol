// PP-533 load test. One script, behaviour selected by PHASE (see the design spec,
// docs/superpowers/specs/2026-10-22-pp533-load-test-design.md, "Experiment phases").
// run.sh greps the raw-log lines (T0, STEP, BATCH_SUBMIT, BATCH_STATE, CAL_S,
// SUMMARY) and render.py reads the CSV output, so keep their formats stable.
import http from "k6/http";
import exec from "k6/execution";
import { check, fail, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";
import { SharedArray } from "k6/data";

const PHASE = __ENV.PHASE || "smoke";
const BASE_URL = __ENV.BASE_URL || "http://api:8000";
const SESSION_TOKEN = __ENV.SESSION_TOKEN || "";
const RATE_PER_MIN = Number(__ENV.RATE_PER_MIN || 0);
const SERVICE_TIME_S = Number(__ENV.SERVICE_TIME_S || 0);
const BATCHES = Number(__ENV.BATCHES || 0);
const DURATION_S = Number(__ENV.DURATION_S || 0);
// QUICK=1 shrinks everything after the 60 s warm-up window by 10x (harness dry-runs).
const Q = __ENV.QUICK === "1" ? 10 : 1;
const WARMUP_S = 60;

const answers = new SharedArray("answers", () => JSON.parse(open("/results/answers.json")));
const batchCsv = open("/results/batch.csv", "b"); // bytes as-is, same file for every batch

const checks504 = new Counter("checks_504");
const checkOk = new Rate("check_ok");
// Latency of good checks only; CAL_S comes from this so fast errors can't shrink S.
const checkOkDuration = new Trend("check_ok_duration", true);

// ---- phase -> scenarios -------------------------------------------------------

const RAMP_FRACTIONS = [0.1, 0.25, 0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.25];
const RAMP_S = 10 / Q;
const HOLD_S = 120 / Q;
const STEP_S = RAMP_S + HOLD_S;
const IS_RAMP = PHASE === "ramp-idle" || PHASE === "ramp-batch";
// Per-minute integers so fractional req/s work; capacity C = 60/S per minute.
const STEP_RATES = IS_RAMP
  ? RAMP_FRACTIONS.map((f) => Math.max(1, Math.round((f * 60) / SERVICE_TIME_S)))
  : [];

// Sized for 12 s of in-flight work per arrival (10 s API timeout + slack). When the
// pool runs out k6 records dropped_iterations, which is a breaking-point signal.
const vusFor = (perMin: number) => Math.max(1, Math.ceil((perMin / 60) * 12));
const s = (sec: number) => `${sec}s`;

const warmup = {
  executor: "per-vu-iterations",
  vus: 1,
  iterations: 20,
  maxDuration: s(WARMUP_S),
  exec: "singleCheck",
};

function constantChecks(durationS: number) {
  return {
    executor: "constant-arrival-rate",
    rate: RATE_PER_MIN,
    timeUnit: "1m",
    duration: s(durationS),
    preAllocatedVUs: vusFor(RATE_PER_MIN),
    maxVUs: vusFor(RATE_PER_MIN),
    startTime: s(WARMUP_S),
    exec: "singleCheck",
  };
}

function serialChecks(iterations: number) {
  return {
    executor: "shared-iterations",
    vus: 1,
    iterations,
    maxDuration: "30m",
    startTime: s(WARMUP_S),
    exec: "singleCheck",
  };
}

// One long iteration that polls every batch every 5 s until its deadline.
function poll(durationS: number) {
  return {
    executor: "per-vu-iterations",
    vus: 1,
    iterations: 1,
    maxDuration: s(durationS + 30),
    exec: "pollBatches",
  };
}

function rampChecks() {
  const stages = STEP_RATES.flatMap((r) => [
    { duration: s(RAMP_S), target: r },
    { duration: s(HOLD_S), target: r },
  ]);
  const vus = vusFor(Math.max(...STEP_RATES));
  return {
    executor: "ramping-arrival-rate",
    startRate: STEP_RATES[0],
    timeUnit: "1m",
    stages,
    preAllocatedVUs: vus,
    maxVUs: vus,
    startTime: s(WARMUP_S),
    exec: "singleCheck",
  };
}

const RAMP_TOTAL_S = STEP_S * RAMP_FRACTIONS.length;
const HEADLINE_IDLE_S = 600 / Q;
// freeze: offsets relative to the 60 s warm-up window, scaled by QUICK.
const FREEZE = { checksS: 240 / Q, batchAtS: 60 / Q, healthAtS: 55 / Q, healthS: 60 / Q };

// Every phase reports the checks submetrics (SUMMARY reads them, CAL_S reads
// check_ok_duration); k6 only emits a
// tagged submetric when a threshold names it, hence the no-op thresholds.
const SUBMETRICS = {
  "http_req_duration{scenario:checks}": ["max>=0"],
  "check_ok{scenario:checks}": ["rate>=0"],
  "checks_504{scenario:checks}": ["count>=0"],
  "check_ok_duration{scenario:checks}": ["max>=0"],
};
// Safety abort only: a dead stack shouldn't burn the rest of the ramp. Scoped to
// checks so warm-up samples don't dilute it (replaces the no-op entry above).
const RAMP_THRESHOLDS = {
  "check_ok{scenario:checks}": [{ threshold: "rate>0.5", abortOnFail: true, delayAbortEval: "30s" }],
};
const HEADLINE_THRESHOLDS = {
  "http_req_duration{scenario:checks}": ["p(95)<10000"],
  "checks_504{scenario:checks}": ["count==0"],
  "checks{scenario:checks}": ["rate>0.99"],
  dropped_iterations: ["count==0"],
};

type PhaseConfig = {
  batches: number; // submitted in setup()
  scenarios: Record<string, object>;
  thresholds?: Record<string, unknown[]>;
  pollS?: number; // batch_poll deadline
  pollUntilDrained?: boolean;
};

const PHASES: Record<string, () => PhaseConfig> = {
  smoke: () => ({
    batches: 1,
    scenarios: { warmup, checks: serialChecks(10), batch_poll: poll(120) },
    pollS: 120,
    pollUntilDrained: true,
  }),
  calibrate: () => ({ batches: 0, scenarios: { warmup, checks: serialChecks(100) } }),
  "ramp-idle": () => ({
    batches: 0,
    scenarios: { warmup, checks: rampChecks() },
    thresholds: RAMP_THRESHOLDS,
  }),
  "ramp-batch": () => ({
    batches: BATCHES,
    scenarios: { warmup, checks: rampChecks(), batch_poll: poll(WARMUP_S + RAMP_TOTAL_S) },
    thresholds: RAMP_THRESHOLDS,
    pollS: WARMUP_S + RAMP_TOTAL_S,
  }),
  "headline-idle": () => ({
    batches: 0,
    scenarios: { warmup, checks: constantChecks(HEADLINE_IDLE_S) },
    thresholds: HEADLINE_THRESHOLDS,
  }),
  "headline-loaded": () => ({
    batches: 1,
    scenarios: {
      warmup,
      checks: constantChecks(DURATION_S), // run.sh passes DURATION_S already scaled
      batch_poll: poll(WARMUP_S + DURATION_S),
    },
    thresholds: HEADLINE_THRESHOLDS,
    pollS: WARMUP_S + DURATION_S,
  }),
  freeze: () => ({
    batches: 0,
    scenarios: {
      warmup,
      checks: constantChecks(FREEZE.checksS),
      batch_submit: {
        executor: "per-vu-iterations",
        vus: 1,
        iterations: 1,
        startTime: s(WARMUP_S + FREEZE.batchAtS),
        maxDuration: "10m",
        exec: "batchSubmit",
      },
      // Event-loop probe: if create_batch blocks the loop, /health stalls too.
      health: {
        executor: "constant-arrival-rate",
        rate: 4,
        timeUnit: "1s",
        duration: s(FREEZE.healthS),
        preAllocatedVUs: 20,
        maxVUs: 20,
        startTime: s(WARMUP_S + FREEZE.healthAtS),
        exec: "health",
      },
    },
  }),
};

if (!PHASES[PHASE]) throw new Error(`unknown PHASE ${PHASE}`);
if (IS_RAMP && !(SERVICE_TIME_S > 0)) throw new Error("ramp phases need SERVICE_TIME_S");
const CFG = PHASES[PHASE]();

export const options = {
  scenarios: CFG.scenarios,
  thresholds: { ...SUBMETRICS, ...(CFG.thresholds || {}) },
  summaryTrendStats: ["avg", "min", "med", "max", "p(90)", "p(95)", "p(99)"],
  // setup() may submit several 500-row batches; create_batch is slow by design.
  setupTimeout: "10m",
};

// ---- requests -------------------------------------------------------------------

function api(kind: string, name?: string) {
  return {
    headers: {
      "Content-Type": "application/json",
      Cookie: `__Host-session=${SESSION_TOKEN}`,
      "Sec-Fetch-Site": "same-origin",
    },
    tags: name ? { kind, name } : { kind },
  };
}

// Shared by setup() and the freeze batch_submit scenario.
function submitBatch(): string {
  const fileName = "loadtest.csv";
  const u = http.post(`${BASE_URL}/api/batches/upload-url`, JSON.stringify({ file_name: fileName }), api("upload_url"));
  if (u.status !== 200) fail(`upload-url ${u.status}`);
  const { upload_url, upload_key } = u.json() as { upload_url: string; upload_key: string };

  // Presigned URL is signed with this exact Content-Type; no cookie/CSRF to S3.
  const put = http.put(upload_url, batchCsv, {
    headers: { "Content-Type": "text/csv" },
    tags: { kind: "put", name: "presigned_put" },
  });
  if (put.status !== 200) fail(`presigned PUT ${put.status}`);

  const startedAt = Date.now();
  const c = http.post(
    `${BASE_URL}/api/batches`,
    JSON.stringify({ upload_key, file_name: fileName, strictness: "standard", retain_answer: false }),
    api("create_batch"),
  );
  if (c.status !== 202) fail(`create_batch ${c.status}`);
  const id = (c.json() as { batch_id: string }).batch_id;
  // post_duration_ms is the freeze length: the event loop is blocked for this call.
  console.log(`BATCH_SUBMIT,${id},${startedAt},${c.timings.duration.toFixed(1)}`);
  return id;
}

export function setup() {
  const batchIds: string[] = [];
  for (let i = 0; i < CFG.batches; i++) batchIds.push(submitBatch());
  STEP_RATES.forEach((r, i) => console.log(`STEP,${i},${r}`));
  console.log(`T0,${Date.now()}`);
  return { batchIds };
}

export function singleCheck() {
  if (IS_RAMP && exec.scenario.name === "checks") {
    // progress (0..1) runs on the executor's clock, the same one driving the
    // stages; wall-clock time drifts from it under Docker Desktop.
    const step = Math.floor(exec.scenario.progress * STEP_RATES.length);
    exec.vu.metrics.tags.step = String(Math.min(Math.max(step, 0), STEP_RATES.length - 1));
  }
  const a = answers[Math.floor(Math.random() * answers.length)];
  const r = http.post(
    `${BASE_URL}/api/checks`,
    JSON.stringify({
      answer_text: a.answer_text,
      question_text: a.question_text || null,
      strictness: "standard",
      retain_answer: false,
    }),
    api("check"),
  );
  // A fast error must never look like good latency: 201 alone isn't enough.
  let ok = false;
  if (r.status === 201) {
    try {
      ok = (r.json() as { verdict?: string }).verdict != null;
    } catch (_) {
      ok = false;
    }
  }
  check(r, { "201 with verdict": () => ok });
  checkOk.add(ok);
  if (ok) checkOkDuration.add(r.timings.duration);
  if (r.status === 504) checks504.add(1);
}

export function batchSubmit() {
  submitBatch();
}

export function pollBatches(data: { batchIds: string[] }) {
  const deadline = exec.scenario.startTime + (CFG.pollS || 0) * 1000;
  for (;;) {
    let drained = true;
    for (const id of data.batchIds) {
      const r = http.get(`${BASE_URL}/api/batches/${id}`, api("poll", "batch_poll"));
      if (r.status !== 200) {
        drained = false;
        continue;
      }
      const b = r.json() as { completed: number; failed: number; pending: number };
      console.log(`BATCH_STATE,${id},${Date.now()},${b.completed},${b.failed},${b.pending}`);
      if (b.pending > 0) drained = false;
    }
    if ((CFG.pollUntilDrained && drained) || Date.now() + 5000 > deadline) return;
    sleep(5);
  }
}

export function health() {
  http.get(`${BASE_URL}/health`, { tags: { kind: "health" } });
}

// ---- summary --------------------------------------------------------------------

type Metric = { values: Record<string, number> } | undefined;

export function handleSummary(data: { metrics: Record<string, Metric> }) {
  const m = data.metrics;
  // Fields stay empty when the checks scenario produced no samples.
  const dur = m["http_req_duration{scenario:checks}"]?.values;
  const ok = m["check_ok{scenario:checks}"]?.values;
  const f1 = (v: number | undefined) => (v === undefined || Number.isNaN(v) ? "" : v.toFixed(1));

  // Every checks request adds one check_ok sample, so its count says whether
  // the scenario ran at all (an empty trend reports 0s, not "no data").
  const n = ok ? ok.passes + ok.fails : 0;
  const p50 = n > 0 && dur ? dur.med : undefined;
  const p95 = n > 0 && dur ? dur["p(95)"] : undefined;
  const p99 = n > 0 && dur ? dur["p(99)"] : undefined;
  const errPct = n > 0 ? 100 * (1 - ok!.rate) : undefined;
  const c504 = m["checks_504{scenario:checks}"]?.values.count ?? 0;

  // S drives every later rate, so only an error-free calibrate yields one; a
  // missing CAL_S makes run.sh abort the run.
  const okMed = m["check_ok_duration{scenario:checks}"]?.values.med;
  if (PHASE === "calibrate" && n > 0 && errPct === 0 && okMed !== undefined) {
    console.log(`CAL_S,${(okMed / 1000).toFixed(3)}`);
  }
  console.log(`SUMMARY,${f1(p50)},${f1(p95)},${f1(p99)},${f1(errPct)},${c504}`);

  return {
    "/results/summary.json": JSON.stringify(data, null, 2),
    stdout: `${PHASE}: checks p50=${f1(p50)}ms p95=${f1(p95)}ms p99=${f1(p99)}ms err=${f1(errPct)}% 504=${c504}\n`,
  };
}
