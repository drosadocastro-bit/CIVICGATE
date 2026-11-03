"use strict";
// Explicit synthetic execution only. No POST retry, provider fallback or raw HTML injection.
const scenario = document.querySelector("#demo-scenario");
const button = document.querySelector("#run-demo");
const description = document.querySelector("#scenario-description");
const badge = document.querySelector("#demo-status");
const message = document.querySelector("#execution-message");
const errorBox = document.querySelector("#job-error");
const evidenceLink = document.querySelector("#open-fresh-evidence");
const csrf = document.querySelector('meta[name="civicgate-csrf"]').content;
const explanations = {
  permit: "A compatible synthetic read should receive deterministic PERMIT, one issued and consumed binding, and one synthetic backend invocation.",
  deny: "The consequential request should be denied deterministically, with no binding issuance or backend dispatch.",
  review: "The unresolved FAA request should remain REVIEW_REQUIRED despite permissive synthetic Judge advice, with no binding or backend dispatch."
};
let pending = false;
function evidenceURL(value) {
  return typeof value === "string" && value.length <= 512 && /^\/runs\/[A-Za-z0-9_-]+\/observations\/[A-Za-z0-9_-]+$/.test(value);
}
function setStatus(value, text) {
  badge.textContent = value;
  message.textContent = text;
}
function showJob(job) {
  document.querySelector("#job-id").textContent = job.id || "UNKNOWN";
  document.querySelector("#job-run").textContent = job.run_id || "Not yet admitted";
  document.querySelector("#job-observation").textContent = job.observation_id || "Not yet admitted";
  document.querySelector("#job-started").textContent = job.started_at_utc || "Not started";
  badge.textContent = job.status || "UNKNOWN";
  if (job.status === "COMPLETE" && evidenceURL(job.evidence_url)) {
    evidenceLink.href = job.evidence_url;
    evidenceLink.hidden = false;
  }
}
async function readJobs() {
  const response = await fetch("/api/demo/executions", {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!response.ok) throw new Error("STATUS_UNAVAILABLE");
  const data = await response.json();
  const capabilityResponse = await fetch("/api/demo/capabilities", {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!capabilityResponse.ok) throw new Error("CAPABILITY_UNAVAILABLE");
  const capability = await capabilityResponse.json();
  document.querySelector("#remaining-jobs").textContent = Number.isInteger(capability.remaining_jobs)
    ? String(capability.remaining_jobs) + " explicit requests remaining in this session"
    : "Session capacity UNKNOWN";
  const held = capability.enabled !== true || !Number.isInteger(capability.remaining_jobs) || capability.remaining_jobs <= 0;
  button.dataset.controllerHeld = held ? "true" : "false";
  if (held) {
    button.disabled = true;
    scenario.disabled = true;
  }
  const list = document.querySelector("#recent-jobs");
  list.replaceChildren();
  if (!Array.isArray(data.jobs) || data.jobs.length === 0) {
    const empty = document.createElement("div");
    empty.className = "panel empty";
    empty.textContent = "No execution requests recorded in this session.";
    list.append(empty);
    return [];
  }
  for (const job of data.jobs.slice(-8).reverse()) {
    const row = document.createElement("div");
    row.className = "observation-row";
    const content = document.createElement("div");
    content.className = "observation-copy";
    const title = document.createElement("h3");
    title.textContent = (job.scenario || "UNKNOWN") + " · " + (job.status || "UNKNOWN");
    const id = document.createElement("code");
    id.textContent = job.id || "UNKNOWN";
    content.append(title, id);
    row.append(content);
    if (job.status === "COMPLETE" && evidenceURL(job.evidence_url)) {
      const link = document.createElement("a");
      link.className = "back-link";
      link.href = job.evidence_url;
      link.textContent = "Inspect evidence →";
      row.append(link);
    }
    list.append(row);
  }
  return data.jobs;
}
async function observe(job) {
  const stopAt = performance.now() + 150000;
  while (true) {
    showJob(job);
    if (job.status === "COMPLETE") {
      setStatus("COMPLETE", "Fresh execution completed and evidence was admitted for inspection.");
      pending = false;
      button.disabled = false;
      scenario.disabled = false;
      await readJobs();
      return;
    }
    if (job.status === "HOLD" || job.status === "UNKNOWN") {
      setStatus(job.status, "Execution or custody needs review. No automatic retry will occur.");
      errorBox.textContent = job.error_code || "Execution outcome or evidence custody is not confirmed.";
      errorBox.hidden = false;
      await readJobs();
      return;
    }
    if (!["RESERVED", "RUNNING"].includes(job.status) || performance.now() > stopAt) {
      throw new Error("OUTCOME_UNKNOWN");
    }
    setStatus(job.status, "The actual synthetic pipeline is running. Evidence will appear after completion checks.");
    await new Promise(resolve => setTimeout(resolve, 500));
    if (typeof job.id !== "string" || !/^[A-Za-z0-9_-]{1,96}$/.test(job.id)) throw new Error("OUTCOME_UNKNOWN");
    const response = await fetch("/api/demo/executions/" + job.id, {credentials: "same-origin", redirect: "error", cache: "no-store"});
    if (!response.ok) throw new Error("OUTCOME_UNKNOWN");
    job = await response.json();
  }
}
scenario.addEventListener("change", () => { description.textContent = explanations[scenario.value]; });
button.addEventListener("click", async () => {
  if (pending) return;
  pending = true;
  button.disabled = true;
  scenario.disabled = true;
  evidenceLink.hidden = true;
  errorBox.hidden = true;
  setStatus("REQUESTING", "Submitting one explicit synthetic demonstration request.");
  try {
    const key = crypto.randomUUID();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    let response;
    try {
      response = await fetch("/api/demo/executions", {
        method: "POST",
        credentials: "same-origin",
        redirect: "error",
        headers: {"Content-Type": "application/json", "X-CivicGate-CSRF": csrf, "Idempotency-Key": key},
        body: JSON.stringify({scenario: scenario.value}),
        signal: controller.signal
      });
    } finally { clearTimeout(timer); }
    const value = await response.json();
    if (!response.ok) {
      setStatus("NOT_ACKNOWLEDGED", "The service did not acknowledge a new execution. Inspect existing request records before deciding what to do next.");
      errorBox.textContent = value.error || "Request not acknowledged.";
      errorBox.hidden = false;
      await readJobs();
      return;
    }
    await observe(value);
  } catch (_) {
    setStatus("UNKNOWN", "The response or status could not be established. Do not automatically retry; inspect request records.");
    errorBox.textContent = "No retry, fallback, refund or second POST was performed.";
    errorBox.hidden = false;
  }
});
readJobs().then(jobs => {
  const unresolved = jobs.find(job => ["HOLD", "UNKNOWN"].includes(job.status));
  if (unresolved) {
    pending = true;
    button.disabled = true;
    scenario.disabled = true;
    showJob(unresolved);
    setStatus(unresolved.status, "An unresolved execution requires review. No new demonstration is enabled.");
    return;
  }
  const active = jobs.find(job => ["RESERVED", "RUNNING"].includes(job.status));
  if (active) {
    pending = true;
    button.disabled = true;
    scenario.disabled = true;
    observe(active).catch(() => setStatus("UNKNOWN", "Status unavailable. No retry was performed."));
  } else {
    button.disabled = button.dataset.controllerHeld === "true";
    if (button.disabled) setStatus("HOLD", "The controller is on HOLD or the session request limit has been reached.");
  }
}).catch(() => setStatus("UNKNOWN", "Request history is unavailable. No execution was initiated."));
