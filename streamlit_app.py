import json
import os
from collections import Counter
from typing import Any

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="System Design Reviewer Demo", layout="wide")

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
DEFAULT_QUERY = "Review this design for production readiness"
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "6000"))


def risk_badge(risk: str) -> str:
    risk_lower = (risk or "unknown").lower()
    if risk_lower == "high":
        return "🔴 high"
    if risk_lower == "medium":
        return "🟠 medium"
    if risk_lower == "low":
        return "🟢 low"
    return f"⚪ {risk_lower}"


def render_evidence_list(evidence: list[dict[str, Any]]) -> None:
    if not evidence:
        st.caption("No citations provided")
        return
    for ev in evidence:
        source_file = ev.get("source_file", "unknown")
        page = ev.get("page", 0)
        quote = ev.get("quote", "")
        st.markdown(f"- `{source_file}` p.{page}: {quote}")


def _flatten_findings(modules: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for module_name, module_data in modules.items():
        for item in module_data.get("findings", []):
            evidence = item.get("evidence", [])
            rows.append(
                {
                    "module": module_name,
                    "title": item.get("title", "Untitled"),
                    "severity": (item.get("severity") or "unknown").lower(),
                    "details": item.get("details", ""),
                    "impact": item.get("impact", ""),
                    "evidence": evidence,
                    "evidence_count": len(evidence),
                }
            )
    rows.sort(key=lambda x: (SEVERITY_ORDER.get(x["severity"], 99), x["module"], x["title"]))
    return rows


def _flatten_recommendations(modules: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for module_name, module_data in modules.items():
        for item in module_data.get("recommendations", []):
            evidence = item.get("evidence", [])
            rows.append(
                {
                    "module": module_name,
                    "title": item.get("title", "Untitled"),
                    "effort": (item.get("effort") or "unknown").lower(),
                    "steps": item.get("steps", []),
                    "evidence": evidence,
                    "evidence_count": len(evidence),
                }
            )
    return rows


def render_module(module_name: str, module_data: dict[str, Any]) -> None:
    score = module_data.get("score", "n/a")
    risk = module_data.get("risk", "unknown")
    with st.expander(f"{module_name} - score: {score}/10 - risk: {risk_badge(risk)}", expanded=False):
        findings = module_data.get("findings", [])
        if findings:
            st.subheader("Findings")
            for item in findings:
                st.markdown(f"**{item.get('title', 'Untitled')}** ({item.get('severity', 'unknown')})")
                st.write(item.get("details", ""))
                st.caption(f"Impact: {item.get('impact', '')}")
                render_evidence_list(item.get("evidence", []))

        recommendations = module_data.get("recommendations", [])
        if recommendations:
            st.subheader("Recommendations")
            for item in recommendations:
                st.markdown(f"**{item.get('title', 'Untitled')}** (effort: {item.get('effort', 'unknown')})")
                for step in item.get("steps", []):
                    st.markdown(f"- {step}")
                render_evidence_list(item.get("evidence", []))

        for field in ["questions_for_author", "missing_info", "assumptions"]:
            values = module_data.get(field, [])
            if values:
                st.subheader(field.replace("_", " ").title())
                for v in values:
                    st.markdown(f"- {v}")


def _estimate_context_chars_from_evidence(modules: dict[str, dict[str, Any]]) -> int:
    quotes: set[tuple[str, int, str]] = set()
    for module_data in modules.values():
        for item in module_data.get("findings", []):
            for ev in item.get("evidence", []):
                quotes.add((ev.get("source_file", "unknown"), int(ev.get("page", 0)), ev.get("quote", "")))
        for item in module_data.get("recommendations", []):
            for ev in item.get("evidence", []):
                quotes.add((ev.get("source_file", "unknown"), int(ev.get("page", 0)), ev.get("quote", "")))
    return sum(len(q[2]) for q in quotes)


def build_analysis_summary(payload: dict[str, Any], response: requests.Response, data: dict[str, Any]) -> dict[str, Any]:
    context_used = (
        data.get("context_chars_used")
        or data.get("meta", {}).get("context_chars_used")
        or data.get("overall", {}).get("context_chars_used")
        or _estimate_context_chars_from_evidence(data.get("modules", {}))
    )
    return {
        "request_id": response.headers.get("x-request-id", "n/a"),
        "collection": payload.get("collection", "n/a"),
        "mode": payload.get("mode", "n/a"),
        "top_k": payload.get("top_k", "n/a"),
        "budget_modules": payload.get("budget_modules", "n/a"),
        "context_chars_used": int(context_used) if context_used is not None else 0,
        "context_chars_max": MAX_CONTEXT_CHARS,
        "latency_ms": round(response.elapsed.total_seconds() * 1000, 1),
    }


def render_analysis_summary(summary: dict[str, Any]) -> None:
    with st.container(border=True):
        st.subheader("Analysis Summary")
        st.markdown("---")
        st.markdown(f"**Request ID:** `{summary.get('request_id', 'n/a')}`")
        st.markdown(f"**Collection:** {summary.get('collection', 'n/a')}")
        st.markdown(f"**Mode:** {summary.get('mode', 'n/a')}")
        st.markdown(f"**Top K:** {summary.get('top_k', 'n/a')}")
        st.markdown(f"**Modules Budget:** {summary.get('budget_modules', 'n/a')}")
        st.markdown(
            f"**Context Size:** {summary.get('context_chars_used', 0)} / {summary.get('context_chars_max', MAX_CONTEXT_CHARS)} chars"
        )
        latency_ms = summary.get("latency_ms", 0.0)
        st.markdown(f"**Latency:** {latency_ms / 1000:.1f}s ({latency_ms} ms)")


def _extract_retry_count(data: dict[str, Any]) -> int:
    meta = data.get("meta", {})
    candidates = [
        data.get("retry_count"),
        data.get("retries"),
        data.get("json_retry_count"),
        data.get("llm_retry_count"),
        meta.get("retry_count"),
        meta.get("retries"),
        meta.get("json_retry_count"),
        meta.get("llm_retry_count"),
    ]
    for value in candidates:
        if isinstance(value, int) and value > 0:
            return value
    # Boolean fallback in case backend only sends repaired flag.
    repaired_flags = [
        data.get("json_repaired"),
        data.get("repaired_json"),
        meta.get("json_repaired"),
        meta.get("repaired_json"),
    ]
    if any(flag is True for flag in repaired_flags):
        return 1
    return 0


def _is_invalid_structured_output(detail: str, status_code: int) -> bool:
    detail_lower = (detail or "").lower()
    if "invalid structured output" in detail_lower:
        return True
    if "invalid json" in detail_lower or "json decode" in detail_lower:
        return True
    if status_code >= 500 and "structured output" in detail_lower:
        return True
    if status_code == 500 and detail_lower in {"internal server error", ""}:
        return True
    return False


def _friendly_error_message(status_code: int, detail: str, operation: str) -> str:
    detail_lower = (detail or "").lower()
    if status_code == 401 and "invalid ingest token" in detail_lower:
        return "The ingest token is incorrect. Update it in the sidebar and try again."
    if status_code == 400 and "openai_api_key" in detail_lower:
        return "Missing OPENAI_API_KEY on the backend. Add it to the API environment and retry."
    if status_code == 404 and "no context found" in detail_lower:
        return "No files are available in this collection yet. Ingest a PDF before running analysis."
    if operation == "analyze" and status_code >= 500:
        return "Analysis failed on the server. Please retry, then inspect the raw output below."
    if operation == "ingest" and status_code >= 500:
        return "Ingest failed on the server. Please verify API configuration and retry."
    if detail:
        return detail
    return f"{operation.capitalize()} failed with status {status_code}."


def render_findings_dashboard(data: dict[str, Any]) -> None:
    overall = data.get("overall", {})
    triage = data.get("triage", {})
    modules = data.get("modules", {})

    findings = _flatten_findings(modules)
    recommendations = _flatten_recommendations(modules)

    high_findings = sum(1 for f in findings if f["severity"] == "high")
    medium_findings = sum(1 for f in findings if f["severity"] == "medium")
    low_findings = sum(1 for f in findings if f["severity"] == "low")
    evidence_total = sum(f["evidence_count"] for f in findings) + sum(r["evidence_count"] for r in recommendations)

    risk_counts = Counter((m.get("risk") or "unknown").lower() for m in modules.values())

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Overall Score", overall.get("score", 0))
    m2.metric("Confidence", overall.get("confidence", 0))
    m3.metric("Modules", len(modules))
    m4.metric("Findings", len(findings))
    m5.metric("Recommendations", len(recommendations))
    m6.metric("Evidence", evidence_total)

    tabs = st.tabs(["Overview", "Findings", "Recommendations", "Module Reviews", "Raw JSON"])

    with tabs[0]:
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Severity Breakdown")
            st.bar_chart(
                pd.DataFrame(
                    {
                        "count": [high_findings, medium_findings, low_findings],
                    },
                    index=["high", "medium", "low"],
                )
            )
        with c2:
            st.subheader("Module Risk Breakdown")
            st.bar_chart(
                pd.DataFrame(
                    {
                        "count": [risk_counts.get("high", 0), risk_counts.get("medium", 0), risk_counts.get("low", 0)],
                    },
                    index=["high", "medium", "low"],
                )
            )

        with st.expander("Triage Output", expanded=True):
            st.json(triage)

    with tabs[1]:
        st.subheader("Filter Findings")
        severity_options = ["high", "medium", "low", "unknown"]
        module_options = sorted(modules.keys())
        fc1, fc2, fc3 = st.columns([1, 1, 2])
        selected_severity = fc1.multiselect("Severity", severity_options, default=severity_options)
        selected_modules = fc2.multiselect("Modules", module_options, default=module_options)
        query_text = fc3.text_input("Search title/details", value="")

        filtered = [
            f
            for f in findings
            if f["severity"] in selected_severity
            and f["module"] in selected_modules
            and query_text.lower() in (f"{f['title']} {f['details']} {f['impact']}".lower())
        ]

        st.caption(f"Showing {len(filtered)} of {len(findings)} findings")
        if not filtered:
            st.info("No findings match the selected filters.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "module": f["module"],
                        "severity": f["severity"],
                        "title": f["title"],
                        "impact": f["impact"],
                        "evidence_count": f["evidence_count"],
                    }
                    for f in filtered
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.subheader("Finding Details")
            for i, f in enumerate(filtered, start=1):
                with st.expander(f"{i}. [{f['severity']}] {f['module']} - {f['title']}"):
                    st.write(f["details"])
                    if f["impact"]:
                        st.caption(f"Impact: {f['impact']}")
                    render_evidence_list(f["evidence"])

    with tabs[2]:
        if not recommendations:
            st.info("No recommendations returned.")
        else:
            rdf = pd.DataFrame(
                [
                    {
                        "module": r["module"],
                        "effort": r["effort"],
                        "title": r["title"],
                        "steps": len(r["steps"]),
                        "evidence_count": r["evidence_count"],
                    }
                    for r in recommendations
                ]
            )
            st.dataframe(rdf, use_container_width=True, hide_index=True)

            st.subheader("Recommendation Details")
            for i, r in enumerate(recommendations, start=1):
                with st.expander(f"{i}. [{r['effort']}] {r['module']} - {r['title']}"):
                    for step in r["steps"]:
                        st.markdown(f"- {step}")
                    render_evidence_list(r["evidence"])

    with tabs[3]:
        if not modules:
            st.info("No modules executed for this mode.")
        for module_name, module_data in modules.items():
            render_module(module_name, module_data)

    with tabs[4]:
        st.code(json.dumps(data, indent=2), language="json")


st.title("System Design Reviewer - Demo Dashboard")
st.caption("Upload a PDF, ingest it, then run triage/targeted/deep analysis.")

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None
if "analysis_summary" not in st.session_state:
    st.session_state.analysis_summary = None
if "analysis_raw_output" not in st.session_state:
    st.session_state.analysis_raw_output = None
if "analysis_retry_count" not in st.session_state:
    st.session_state.analysis_retry_count = 0

with st.sidebar:
    st.header("Configuration")
    base_url = st.text_input("API Base URL", value=API_BASE_URL)
    ingest_token = st.text_input("Ingest Token", type="password")
    collection = st.text_input("Collection", value="default")
    mode = st.selectbox("Mode", options=["triage", "targeted", "deep"], index=1)
    top_k = st.number_input("top_k", min_value=1, max_value=20, value=6, step=1)
    budget_modules = st.slider("budget_modules", min_value=1, max_value=9, value=3)
    file_filter = st.text_input("file_filter (optional)", value="")

st.subheader("1) Upload and ingest PDF")
uploaded = st.file_uploader("Choose a PDF file", type=["pdf"])

if st.button("Ingest PDF", type="primary", disabled=uploaded is None):
    if not ingest_token:
        st.error("Please set ingest token in the sidebar.")
    elif uploaded is None:
        st.error("Please upload a PDF first.")
    else:
        files = {"file": (uploaded.name, uploaded.getvalue(), "application/pdf")}
        headers = {"x-ingest-token": ingest_token}
        try:
            resp = requests.post(
                f"{base_url}/ingest",
                params={"collection": collection},
                headers=headers,
                files=files,
                timeout=120,
            )
            detail = ""
            try:
                body = resp.json()
                detail = body.get("detail", "")
            except Exception:
                body = None
                detail = resp.text

            if resp.status_code >= 400:
                st.error(_friendly_error_message(resp.status_code, detail, "ingest"))
                with st.expander("Show Raw Output"):
                    st.code(resp.text or "No response body", language="json")
            else:
                st.success("PDF ingested successfully.")
                st.json(body if body is not None else {"status": "ok"})
        except requests.exceptions.Timeout:
            st.error("Ingest timed out. The file may be large; please retry.")
        except requests.exceptions.RequestException:
            st.error("Could not reach the API for ingest. Check API Base URL and server status.")

st.subheader("2) Run analysis")
query = st.text_area("Query", value=DEFAULT_QUERY, height=100)

if st.button("Analyze", type="secondary"):
    payload = {
        "collection": collection,
        "query": query,
        "mode": mode,
        "top_k": int(top_k),
        "file_filter": file_filter or None,
        "budget_modules": int(budget_modules),
    }
    try:
        can_analyze = True
        files_resp = requests.get(f"{base_url}/files", params={"collection": collection}, timeout=30)
        if files_resp.status_code == 200:
            files_body = files_resp.json()
            if not files_body.get("files"):
                st.warning("No files found in this collection. Ingest a PDF before running analysis.")
                st.session_state.analysis_result = None
                st.session_state.analysis_summary = None
                st.session_state.analysis_retry_count = 0
                st.session_state.analysis_raw_output = None
                can_analyze = False

        if not can_analyze:
            st.session_state.analysis_raw_output = None
        else:
            resp = requests.post(f"{base_url}/analyze", json=payload, timeout=180)
            st.session_state.analysis_raw_output = resp.text
            if resp.status_code >= 400:
                detail = ""
                try:
                    detail = resp.json().get("detail", "")
                except Exception:
                    detail = resp.text
                if _is_invalid_structured_output(detail=detail, status_code=resp.status_code):
                    with st.container(border=True):
                        st.error("Analysis Failed")
                        st.write("The model returned invalid structured output.")
                        st.write("Please retry or inspect the raw response.")
                else:
                    st.error(_friendly_error_message(resp.status_code, detail, "analyze"))
                st.session_state.analysis_result = None
                st.session_state.analysis_summary = None
                st.session_state.analysis_retry_count = 0
            else:
                result = resp.json()
                st.session_state.analysis_result = result
                st.session_state.analysis_summary = build_analysis_summary(payload=payload, response=resp, data=result)
                st.session_state.analysis_retry_count = _extract_retry_count(result)
    except requests.exceptions.Timeout:
        st.error("Analysis timed out. Try reducing top_k, narrowing file_filter, or retrying.")
        st.session_state.analysis_result = None
        st.session_state.analysis_summary = None
        st.session_state.analysis_retry_count = 0
        st.session_state.analysis_raw_output = None
    except requests.exceptions.RequestException:
        st.error("Could not reach the API for analysis. Check API Base URL and server status.")
        st.session_state.analysis_result = None
        st.session_state.analysis_summary = None
        st.session_state.analysis_retry_count = 0
        st.session_state.analysis_raw_output = None

if st.session_state.analysis_result:
    render_analysis_summary(st.session_state.analysis_summary or {})
    if st.session_state.analysis_retry_count > 0:
        st.caption("JSON repaired (1 retry)")
    st.subheader("3) Findings Dashboard")
    render_findings_dashboard(st.session_state.analysis_result)

if st.session_state.analysis_raw_output:
    with st.expander("Show Raw Output"):
        raw_text = st.session_state.analysis_raw_output
        try:
            parsed = json.loads(raw_text)
            st.code(json.dumps(parsed, indent=2), language="json")
        except Exception:
            st.code(raw_text, language="text")
