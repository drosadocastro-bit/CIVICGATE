"use strict";
// Separate advisory action. No automatic POST, retry, model fallback or executable model output.
(() => {
  const panel = document.querySelector("#evidence-advisor");
  const button = document.querySelector("#analyze-evidence");
  const badge = document.querySelector("#advisor-status");
  const message = document.querySelector("#advisor-message");
  const error = document.querySelector("#advisor-error");
  const report = document.querySelector("#advisor-report");
  const csrf = document.querySelector('meta[name="civicgate-advisor-csrf"]').content;
  let busy = false;
  function node(tag, text, parent) {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.append(element);
    return element;
  }
  function fail(code) {
    badge.textContent = "FAILED";
    message.textContent = "Analysis is unavailable or incomplete. No automatic retry will occur.";
    error.textContent = code;
    error.hidden = false;
    button.disabled = true;
  }
  function display(job) {
    badge.textContent = job.status || "FAILED";
    if (job.status !== "COMPLETE") return;
    report.replaceChildren();
    node("p", "Advisory interpretation only. Citations resolved locally; narrative is not independently verified.", report);
    node("h3", job.report.summary, report);
    for (const finding of job.report.findings) {
      const box = node("article", "", report);
      box.className = "advisor-finding";
      node("h4", finding.id + " · " + finding.category + " · " + finding.severity, box);
      node("p", "Provider-claimed kind: " + finding.kind + " · Supporting observation: " + job.observation_id, box);
      node("p", finding.explanation, box);
      node("p", "Remaining uncertainty: " + finding.uncertainty, box);
      if (finding.investigation) node("p", "Suggested investigation: " + finding.investigation, box);
      const details = node("details", "", box);
      node("summary", "Supporting evidence references", details);
      node("p", "Facts: " + finding.fact_ids.join(", ") + " · Sources: " + finding.source_ids.join(", "), details);
      for (const fact of job.facts || []) {
        if (finding.fact_ids.includes(fact.id)) {
          node("p", fact.id + " · " + fact.name + " = " + (fact.value === null ? "UNKNOWN" : String(fact.value)), details);
        }
      }
      for (const source of job.sources || []) {
        if (finding.source_ids.includes(source.id)) {
          node("p", source.id + " · " + source.path + " · SHA-256 " + source.sha256, details);
        }
      }
    }
    const limits = node("div", "", report);
    node("h3", "Limitations", limits);
    const list = node("ul", "", limits);
    for (const limitation of job.report.limitations) node("li", limitation, list);
    node("p", "Sanitized request SHA-256: " + job.request_sha256, report);
    report.hidden = false;
    message.textContent = "Mock analysis complete. Original evidence and authority state are unchanged.";
  }
  async function capabilities() {
    const response = await fetch("/api/advisor/capabilities", {credentials: "same-origin", redirect: "error", cache: "no-store"});
    if (!response.ok) throw new Error("ADVISOR_UNAVAILABLE");
    const value = await response.json();
    return value.enabled === true && value.active === false && value.remaining_jobs > 0;
  }
  button.addEventListener("click", async () => {
    if (busy || button.disabled) return;
    busy = true;
    button.disabled = true;
    badge.textContent = "RUNNING";
    message.textContent = "Submitting one explicit advisory request. No MCP execution is requested.";
    try {
      const response = await fetch("/api/advisor/analyses", {
        method: "POST", credentials: "same-origin", redirect: "error", cache: "no-store",
        headers: {"Content-Type": "application/json", "X-CivicGate-CSRF": csrf, "Idempotency-Key": crypto.randomUUID()},
        body: JSON.stringify({run_id: panel.dataset.runId, observation_id: panel.dataset.observationId})
      });
      if (response.status !== 202) throw new Error("ANALYSIS_NOT_ACCEPTED");
      let job = await response.json();
      if (typeof job.id !== "string" || !/^[A-Za-z0-9_-]{1,128}$/.test(job.id)) throw new Error("INVALID_ADVISOR_STATUS");
      const deadline = performance.now() + 65000;
      while (job.status === "RUNNING" || job.status === "IDLE") {
        if (performance.now() > deadline) throw new Error("ANALYSIS_STATUS_UNKNOWN");
        await new Promise(resolve => setTimeout(resolve, 350));
        const status = await fetch("/api/advisor/analyses/" + job.id, {credentials: "same-origin", redirect: "error", cache: "no-store"});
        if (!status.ok) throw new Error("ANALYSIS_STATUS_UNKNOWN");
        job = await status.json();
      }
      if (job.status !== "COMPLETE") throw new Error(job.error_code || "ANALYSIS_FAILED");
      display(job);
      // An explicit completed observation is displayed once; refresh is GET only.
    } catch (_) {
      fail("ADVISOR_FAILED_OR_OUTCOME_UNKNOWN");
    }
  });
  capabilities().then(available => {
    button.disabled = !available;
    message.textContent = available ? "Ready for one manual mock analysis of this observation." : "Advisor unavailable or session capacity exhausted.";
  }).catch(() => fail("ADVISOR_CONFIGURATION_UNAVAILABLE"));
})();
