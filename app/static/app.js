const healthBtn = document.querySelector("#healthBtn");
const healthOut = document.querySelector("#healthOut");
const ingestForm = document.querySelector("#ingestForm");
const ingestBtn = document.querySelector("#ingestBtn");
const ingestOut = document.querySelector("#ingestOut");
const filesForm = document.querySelector("#filesForm");
const filesBtn = document.querySelector("#filesBtn");
const filesOut = document.querySelector("#filesOut");
const analyzeForm = document.querySelector("#analyzeForm");
const analyzeBtn = document.querySelector("#analyzeBtn");
const analyzeOut = document.querySelector("#analyzeOut");
const auditReport = document.querySelector("#auditReport");
const toastHost = document.querySelector("#toastHost");

const CONTEXT_MAX = 6000;

function setBusy(button, busy, busyLabel) {
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = button.textContent;
  }
  button.disabled = busy;
  button.textContent = busy ? busyLabel : button.dataset.defaultLabel;
}

function showToast(message, kind = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  toastHost.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 2600);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function truncateQuote(text, max = 220) {
  const clean = String(text || "").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max)}...`;
}

function friendlyMessage(operation, status, detail) {
  const lower = String(detail || "").toLowerCase();

  if (operation === "ingest" && status === 401) {
    return "Invalid ingest token. Update the token and try again.";
  }
  if (lower.includes("openai_api_key")) {
    return "Missing OPENAI_API_KEY on the backend. Configure it and retry.";
  }
  if (operation === "analyze" && status === 404) {
    return "No context found for this collection or file filter. Ingest a file or adjust filter settings.";
  }
  if (operation === "files" && status >= 500) {
    return "Could not load collection files due to a server issue. Please retry.";
  }
  if (status >= 500) {
    return "The server returned an internal error. Please retry in a moment.";
  }
  if (status === 408) {
    return "The request timed out. Please retry.";
  }
  return detail || `Request failed (HTTP ${status}).`;
}

function statusPanel(target, message, kind = "muted") {
  target.className = `status-panel ${kind}`;
  target.textContent = message;
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 180000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    return response;
  } finally {
    clearTimeout(timer);
  }
}

async function parseResponse(res) {
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return {
    status: res.status,
    ok: res.ok,
    text,
    json,
    detail: (json && json.detail) || text,
    requestId: res.headers.get("x-request-id") || "n/a",
  };
}

function scoreToPercent(score) {
  const n = Number(score || 0);
  if (!Number.isFinite(n)) return 0;
  return n <= 10 ? Math.round(n * 10) : Math.round(n);
}

function deriveRiskLabel(score) {
  const pct = scoreToPercent(score);
  if (pct >= 80) return "LOW";
  if (pct >= 50) return "MED";
  return "HIGH";
}

function confidencePercent(confidence) {
  const n = Number(confidence || 0);
  if (!Number.isFinite(n)) return 0;
  return n <= 1 ? Math.round(n * 100) : Math.round(n);
}

function extractRetryCount(data) {
  const meta = (data && data.meta) || {};
  const values = [
    data && data.retry_count,
    data && data.retries,
    data && data.json_retry_count,
    data && data.llm_retry_count,
    meta.retry_count,
    meta.retries,
    meta.json_retry_count,
    meta.llm_retry_count,
  ];
  for (const value of values) {
    if (typeof value === "number" && value > 0) return value;
  }
  if (data?.json_repaired || meta.json_repaired) return 1;
  return 0;
}

function estimateContextChars(modules) {
  const unique = new Set();
  Object.values(modules || {}).forEach((module) => {
    (module.findings || []).forEach((finding) => {
      (finding.evidence || []).forEach((ev) => {
        unique.add(`${ev.source_file || "unknown"}|${ev.page || 0}|${ev.quote || ""}`);
      });
    });
    (module.recommendations || []).forEach((rec) => {
      (rec.evidence || []).forEach((ev) => {
        unique.add(`${ev.source_file || "unknown"}|${ev.page || 0}|${ev.quote || ""}`);
      });
    });
  });
  let total = 0;
  unique.forEach((entry) => {
    const quote = entry.split("|").slice(2).join("|");
    total += quote.length;
  });
  return total;
}

function renderFilesPanel(data) {
  const files = data.files || [];
  if (!files.length) {
    filesOut.innerHTML = '<div class="status-panel warn">No files in this collection yet.</div>';
    return;
  }

  const rows = files
    .map(
      (file) =>
        `<li><strong>${escapeHtml(file.source_file || "unknown")}</strong> <span class="tiny">${escapeHtml(file.chunks || 0)} chunks</span></li>`
    )
    .join("");

  filesOut.className = "status-panel";
  filesOut.innerHTML = `<ul>${rows}</ul>`;
}

function renderRunSummary(payload, data, requestId, latencyMs) {
  const contextUsed =
    data?.context_chars_used || data?.meta?.context_chars_used || data?.overall?.context_chars_used || estimateContextChars(data?.modules || {});

  return `
    <div class="info-strip">
      <div class="info-grid">
        <div><strong>Request ID:</strong> <code>${escapeHtml(requestId)}</code> <button class="btn-mini" data-copy="${escapeHtml(requestId)}">Copy</button></div>
        <div><strong>Collection:</strong> ${escapeHtml(payload.collection)}</div>
        <div><strong>Mode:</strong> ${escapeHtml(payload.mode)}</div>
        <div><strong>Top K:</strong> ${escapeHtml(payload.top_k)}</div>
        <div><strong>Budget Modules:</strong> ${escapeHtml(payload.budget_modules)}</div>
        <div><strong>Context:</strong> ${escapeHtml(contextUsed)} / ${CONTEXT_MAX} chars</div>
      </div>
    </div>
    <div class="summary-row">
      <article class="metric-card">
        <p class="metric-label">Overall Score</p>
        <p class="metric-value">${scoreToPercent(data?.overall?.score)}%</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">Confidence</p>
        <p class="metric-value">${confidencePercent(data?.overall?.confidence)}%</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">Risk Level</p>
        <p class="metric-value">${deriveRiskLabel(data?.overall?.score)}</p>
      </article>
      <article class="metric-card">
        <p class="metric-label">Latency</p>
        <p class="metric-value">${latencyMs >= 1000 ? `${(latencyMs / 1000).toFixed(1)}s` : `${Math.round(latencyMs)}ms`}</p>
      </article>
    </div>
  `;
}

function renderModulesChips(modules) {
  const names = Object.keys(modules || {});
  if (!names.length) {
    return '<p class="tiny">No modules executed for this run.</p>';
  }
  return `<div class="chips">${names.map((name) => `<span class="chip">${escapeHtml(name)}</span>`).join("")}</div>`;
}

function renderEvidence(evidence) {
  if (!evidence || !evidence.length) {
    return '<p class="tiny">No evidence cited.</p>';
  }

  return evidence
    .map((ev) => {
      const quote = truncateQuote(ev.quote || "", 220);
      return `
        <article class="evidence-item">
          <div class="evidence-meta">
            <span>${escapeHtml(ev.source_file || "unknown")} · p.${escapeHtml(ev.page ?? 0)}</span>
            <button class="btn-mini" data-copy="${escapeHtml(quote)}">Copy</button>
          </div>
          <p class="evidence-quote">${escapeHtml(quote)}</p>
        </article>
      `;
    })
    .join("");
}

function mapSeverity(severity) {
  const raw = String(severity || "low").toLowerCase();
  if (raw === "high") return { label: "HIGH", cls: "high" };
  if (raw === "medium") return { label: "MED", cls: "medium" };
  return { label: "LOW", cls: "low" };
}

function renderFindingsByModule(modules) {
  const moduleEntries = Object.entries(modules || {});
  if (!moduleEntries.length) {
    return '<div class="status-panel warn">No module findings were generated for this mode.</div>';
  }

  return moduleEntries
    .map(([moduleName, module]) => {
      const findings = module.findings || [];
      const recommendations = module.recommendations || [];
      const cards = findings.length
        ? findings
            .map((finding, idx) => {
              const sev = mapSeverity(finding.severity);
              const rec = recommendations[idx] || recommendations[0] || {};
              const issue = finding.title || finding.details || "Issue";
              const issueDetail = finding.details || finding.impact || "No details provided.";
              const recommendation = rec.title || (Array.isArray(rec.steps) && rec.steps[0]) || "No recommendation provided.";
              const evidence = (finding.evidence && finding.evidence.length ? finding.evidence : rec.evidence) || [];
              return `
                <article class="finding-card">
                  <div class="finding-head">
                    <strong>${escapeHtml(issue)}</strong>
                    <span class="badge ${sev.cls}">${sev.label}</span>
                  </div>
                  <p class="finding-issue clamp"><strong>Issue:</strong> ${escapeHtml(issueDetail)}</p>
                  <p class="finding-rec clamp"><strong>Recommendation:</strong> ${escapeHtml(recommendation)}</p>
                  <div class="evidence">
                    <details>
                      <summary>Evidence (${evidence.length})</summary>
                      ${renderEvidence(evidence)}
                    </details>
                  </div>
                </article>
              `;
            })
            .join("")
        : '<p class="tiny">No findings for this module.</p>';

      return `
        <section class="module-group">
          <h3 class="module-title">${escapeHtml(moduleName)}</h3>
          ${cards}
        </section>
      `;
    })
    .join("");
}

function renderErrorCard(title, message, raw, causes = []) {
  return `
    <section class="error-card">
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
      ${causes.length ? `<ul>${causes.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>` : ""}
      <details>
        <summary>Show raw response</summary>
        <pre class="raw-box">${escapeHtml(raw || "No response body")}</pre>
      </details>
    </section>
  `;
}

function renderAuditReport(payload, data, requestId, latencyMs) {
  const retryCount = extractRetryCount(data);
  const retryBadge = retryCount > 0 ? '<p class="tiny"><span class="chip">JSON repaired (1 retry)</span></p>' : "";

  auditReport.className = "audit-report";
  auditReport.innerHTML = `
    ${renderRunSummary(payload, data, requestId, latencyMs)}
    ${retryBadge}
    <h3 class="section-title">Modules Reviewed</h3>
    ${renderModulesChips(data.modules || {})}
    <h3 class="section-title">Findings</h3>
    ${renderFindingsByModule(data.modules || {})}
  `;
}

function commonAnalyzeCauses(detail) {
  const lower = String(detail || "").toLowerCase();
  const causes = [];
  if (lower.includes("openai_api_key")) causes.push("OPENAI_API_KEY is missing on backend.");
  if (lower.includes("no context found")) causes.push("Collection is empty or file_filter excludes all chunks.");
  causes.push("Model output format failed validation.");
  causes.push("Temporary model or network issue.");
  return causes;
}

healthBtn.addEventListener("click", async () => {
  setBusy(healthBtn, true, "Checking...");
  healthOut.textContent = "Checking API status...";
  try {
    const res = await fetchWithTimeout("/health", {}, 10000);
    const parsed = await parseResponse(res);
    if (parsed.ok) {
      healthOut.textContent = "API status: ok";
    } else {
      healthOut.textContent = `Health check failed: ${friendlyMessage("health", parsed.status, parsed.detail)}`;
    }
  } catch {
    healthOut.textContent = "Health check failed: could not reach API.";
  } finally {
    setBusy(healthBtn, false, "Checking...");
  }
});

ingestForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(ingestBtn, true, "Ingesting...");
  statusPanel(ingestOut, "Ingesting file...", "muted");

  try {
    const formData = new FormData();
    const file = ingestForm.file.files[0];
    if (!file) {
      statusPanel(ingestOut, "Select a PDF file before ingesting.", "warn");
      return;
    }

    formData.append("file", file);
    const collection = encodeURIComponent(ingestForm.collection.value);
    const token = ingestForm.token.value;

    const res = await fetchWithTimeout(
      `/ingest?collection=${collection}`,
      {
        method: "POST",
        headers: { "x-ingest-token": token },
        body: formData,
      },
      120000
    );

    const parsed = await parseResponse(res);
    if (!parsed.ok) {
      statusPanel(ingestOut, friendlyMessage("ingest", parsed.status, parsed.detail), "error");
      return;
    }

    const chunks = parsed.json?.chunks || 0;
    const fileName = parsed.json?.source_file || file.name;
    statusPanel(ingestOut, `Ingest complete: ${fileName} (${chunks} chunks).`, "success");
    showToast("Ingested 1 file", "success");
  } catch (err) {
    if (err && err.name === "AbortError") {
      statusPanel(ingestOut, "Ingest timed out. Try a smaller file or retry.", "warn");
    } else {
      statusPanel(ingestOut, "Could not reach API while ingesting. Verify server and URL.", "error");
    }
  } finally {
    setBusy(ingestBtn, false, "Ingesting...");
  }
});

filesForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(filesBtn, true, "Loading...");
  statusPanel(filesOut, "Loading collection files...", "muted");

  try {
    const collection = encodeURIComponent(filesForm.collection.value);
    const res = await fetchWithTimeout(`/files?collection=${collection}`, {}, 30000);
    const parsed = await parseResponse(res);
    if (!parsed.ok) {
      statusPanel(filesOut, friendlyMessage("files", parsed.status, parsed.detail), "error");
      return;
    }
    renderFilesPanel(parsed.json || {});
  } catch {
    statusPanel(filesOut, "Could not load files. Check API connectivity.", "error");
  } finally {
    setBusy(filesBtn, false, "Loading...");
  }
});

analyzeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(analyzeBtn, true, "Analyzing...");
  statusPanel(analyzeOut, "Analyzing architecture document...", "muted");

  const payload = {
    collection: analyzeForm.collection.value,
    query: analyzeForm.query.value,
    mode: analyzeForm.mode.value,
    top_k: Number(analyzeForm.top_k.value),
    budget_modules: Number(analyzeForm.budget_modules.value),
    file_filter: analyzeForm.file_filter.value.trim() || null,
  };

  const start = performance.now();

  try {
    const res = await fetchWithTimeout(
      "/analyze",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
      180000
    );

    const parsed = await parseResponse(res);
    const latencyMs = Math.round(performance.now() - start);

    if (!parsed.ok) {
      const message = friendlyMessage("analyze", parsed.status, parsed.detail);
      const title = parsed.status >= 500 ? "Analysis Failed" : "Analysis Error";
      auditReport.className = "audit-report";
      auditReport.innerHTML = renderErrorCard(title, message, parsed.text, commonAnalyzeCauses(parsed.detail));
      statusPanel(analyzeOut, message, "error");
      return;
    }

    if (!parsed.json || typeof parsed.json !== "object") {
      auditReport.className = "audit-report";
      auditReport.innerHTML = renderErrorCard(
        "Analysis Failed",
        "The model returned invalid structured output. Please retry or inspect the raw response.",
        parsed.text,
        ["Model output format failed validation."]
      );
      statusPanel(analyzeOut, "Analysis failed due to invalid structured output.", "error");
      return;
    }

    renderAuditReport(payload, parsed.json, parsed.requestId, latencyMs);
    statusPanel(analyzeOut, "Analysis complete.", "success");
    showToast("Analysis complete", "success");
  } catch (err) {
    const isTimeout = err && err.name === "AbortError";
    const message = isTimeout
      ? "Analysis timed out. Try reducing top_k, narrowing file_filter, or retrying."
      : "Could not reach API during analysis. Verify server and URL.";
    auditReport.className = "audit-report";
    auditReport.innerHTML = renderErrorCard("Analysis Error", message, String(err || ""), [
      "Collection may be empty.",
      "Backend may be missing OPENAI_API_KEY.",
    ]);
    statusPanel(analyzeOut, message, "error");
  } finally {
    setBusy(analyzeBtn, false, "Analyzing...");
  }
});

auditReport.addEventListener("click", async (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  const copyText = target.dataset.copy;
  if (!copyText) return;

  try {
    await navigator.clipboard.writeText(copyText);
    showToast("Copied", "success");
  } catch {
    showToast("Copy failed", "error");
  }
});
