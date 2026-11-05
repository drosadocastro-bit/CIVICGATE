"use strict";
// One explicit POST per turn. Status polling uses GET and never retries execution.
const prompt = document.querySelector("#chat-prompt");
const submit = document.querySelector("#submit-chat");
const badge = document.querySelector("#chat-status");
const message = document.querySelector("#chat-message");
const errorBox = document.querySelector("#chat-error");
const evidence = document.querySelector("#chat-evidence");
const csrf = document.querySelector('meta[name="civicgate-csrf"]').content;
let pending = false;
function safeEvidenceURL(value) {
  return typeof value === "string" && value.length <= 512 && /^\/runs\/[A-Za-z0-9_-]+\/observations\/[A-Za-z0-9_-]+$/.test(value);
}
function pretty(value, fallback) {
  return value === null || value === undefined ? fallback : JSON.stringify(value, null, 2);
}
function showTurn(turn) {
  document.querySelector("#chat-request-sha").textContent = turn.request_sha256 || "UNKNOWN";
  document.querySelector("#chat-tool").textContent = turn.selected_tool || "Not proposed";
  document.querySelector("#chat-arguments").textContent = pretty(turn.canonical_arguments, "Not proposed");
  document.querySelector("#chat-decision").textContent = turn.decision || "Not evaluated";
  document.querySelector("#chat-reasons").textContent = pretty(turn.policy_reasons, "Not evaluated");
  document.querySelector("#chat-execution").textContent =
    Number.isInteger(turn.binding_issuances) && Number.isInteger(turn.binding_consumptions) && Number.isInteger(turn.backend_attempts)
      ? `${turn.binding_issuances} issued / ${turn.binding_consumptions} consumed · ${turn.backend_attempts} backend attempts`
      : "Not evaluated";
  document.querySelector("#chat-result-state").textContent = turn.result_state || "Not observed";
  document.querySelector("#chat-result").textContent = pretty(turn.result, "Result withheld");
  document.querySelector("#chat-latency").textContent = pretty(turn.stage_entry_deltas_ms, "Not measured");
  badge.textContent = turn.status || "UNKNOWN";
  if (turn.status === "COMPLETE" && safeEvidenceURL(turn.evidence_url)) {
    evidence.href = turn.evidence_url;
    evidence.hidden = false;
  }
}
async function capabilities() {
  const response = await fetch("/api/chat/capabilities", {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!response.ok) throw new Error("CAPABILITY_UNAVAILABLE");
  const value = await response.json();
  const held = value.enabled !== true || value.active === true || !Number.isInteger(value.remaining_turns) || value.remaining_turns <= 0;
  document.querySelector("#chat-capacity").textContent = Number.isInteger(value.remaining_turns)
    ? `${value.remaining_turns} explicit turns remaining in this session`
    : "Session capacity UNKNOWN";
  submit.dataset.controllerHeld = held ? "true" : "false";
  submit.disabled = held || !prompt.value.trim();
  prompt.disabled = held;
}
async function observe(turn) {
  const stopAt = performance.now() + 150000;
  while (true) {
    showTurn(turn);
    if (turn.status === "COMPLETE") {
      message.textContent = "The governed synthetic turn completed and its evidence was admitted.";
      pending = false;
      prompt.disabled = false;
      await capabilities();
      return;
    }
    if (["HOLD", "UNKNOWN"].includes(turn.status)) {
      message.textContent = "Execution or custody is unresolved. No automatic retry will occur.";
      errorBox.textContent = turn.error_code || "Outcome unknown.";
      errorBox.hidden = false;
      return;
    }
    if (!["RESERVED", "RUNNING"].includes(turn.status) || performance.now() > stopAt) throw new Error("OUTCOME_UNKNOWN");
    message.textContent = "A2, MCP and the Gateway are processing the single synthetic proposal.";
    await new Promise(resolve => setTimeout(resolve, 500));
    if (typeof turn.id !== "string" || !/^chat-[a-f0-9]{32}$/.test(turn.id)) throw new Error("OUTCOME_UNKNOWN");
    const response = await fetch(`/api/chat/turns/${turn.id}`, {credentials: "same-origin", redirect: "error", cache: "no-store"});
    if (!response.ok) throw new Error("OUTCOME_UNKNOWN");
    turn = await response.json();
  }
}
async function loadTurns() {
  const response = await fetch("/api/chat/turns", {credentials: "same-origin", redirect: "error", cache: "no-store"});
  if (!response.ok) throw new Error("TURN_HISTORY_UNAVAILABLE");
  const value = await response.json();
  if (!value || !Array.isArray(value.turns)) throw new Error("TURN_HISTORY_INVALID");
  return value.turns;
}
async function recoverExistingTurn() {
  const turns = await loadTurns();
  if (turns.length === 0) {
    await capabilities();
    return;
  }
  const unresolved = turns.find(turn => ["HOLD", "UNKNOWN"].includes(turn.status));
  if (unresolved) {
    pending = true;
    showTurn(unresolved);
    message.textContent = "A prior turn has unresolved execution or custody. New submission is blocked.";
    errorBox.textContent = unresolved.error_code || "Outcome unknown.";
    errorBox.hidden = false;
    prompt.disabled = true;
    submit.disabled = true;
    return;
  }
  const active = turns.find(turn => ["RESERVED", "RUNNING"].includes(turn.status));
  if (active) {
    pending = true;
    prompt.disabled = true;
    submit.disabled = true;
    await observe(active);
    return;
  }
  const latest = turns[turns.length - 1];
  showTurn(latest);
  message.textContent = "The last governed synthetic turn is shown below.";
  await capabilities();
}
prompt.addEventListener("input", () => {
  submit.disabled = pending || submit.dataset.controllerHeld === "true" || !prompt.value.trim();
});
for (const example of document.querySelectorAll("[data-prompt]")) {
  example.addEventListener("click", () => {
    prompt.value = example.dataset.prompt;
    prompt.dispatchEvent(new Event("input"));
    prompt.focus();
  });
}
submit.addEventListener("click", async () => {
  if (pending || !prompt.value.trim()) return;
  pending = true;
  submit.disabled = true;
  prompt.disabled = true;
  evidence.hidden = true;
  errorBox.hidden = true;
  badge.textContent = "REQUESTING";
  message.textContent = "Persisting the original request before planner execution.";
  try {
    const key = crypto.randomUUID();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    let response;
    try {
      response = await fetch("/api/chat/turns", {
        method: "POST",
        credentials: "same-origin",
        redirect: "error",
        headers: {"Content-Type": "application/json", "X-CivicGate-CSRF": csrf, "Idempotency-Key": key},
        body: JSON.stringify({prompt: prompt.value}),
        signal: controller.signal
      });
    } finally { clearTimeout(timer); }
    const value = await response.json();
    if (!response.ok) {
      badge.textContent = "NOT_ACKNOWLEDGED";
      message.textContent = "No new turn was acknowledged. Inspect existing records before any new request.";
      errorBox.textContent = value.error || "Request not acknowledged.";
      errorBox.hidden = false;
      return;
    }
    await observe(value);
  } catch (_) {
    badge.textContent = "UNKNOWN";
    message.textContent = "The response or status could not be established.";
    errorBox.textContent = "No retry, fallback or second POST was performed.";
    errorBox.hidden = false;
    try {
      await recoverExistingTurn();
    } catch (_) {
      prompt.disabled = true;
      submit.disabled = true;
    }
  }
});
recoverExistingTurn().catch(() => {
  badge.textContent = "UNKNOWN";
  message.textContent = "Chat capability status is unavailable. No request was initiated.";
  submit.disabled = true;
  prompt.disabled = true;
});
