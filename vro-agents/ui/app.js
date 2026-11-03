"use strict";
/* Dependency-free SPA. Every piece of vendor- or model-derived text is inserted with textContent (never innerHTML) so
   embedded markup or links in untrusted documents cannot execute or exfiltrate (plan GR-020). */
const ROLES = ["sponsor", "analyst", "senior_analyst", "aml", "infosec", "legal", "manager", "senior_risk", "committee", "head_tprm", "admin", "auditor"];
const S = { user: sessionStorage.getItem("vro.user") || "ui_user", role: sessionStorage.getItem("vro.role") || "analyst", tenant: "t_demo" };
const MAIN_STEPS = [["INTAKE_REVIEW", "Intake"], ["SCREENING", "Screening"], ["TIERING", "Tiering"], ["DUE_DILIGENCE", "Due diligence"], ["ASSESSMENT", "Assessment"],
  ["VERIFICATION", "Verification"], ["HUMAN_REVIEW", "Human review"], ["CONTRACTING", "Contracting"], ["FINAL_APPROVAL", "Final approval"], ["MONITORING", "Monitoring"]];
const ORDER = ["NEW", "INTAKE_REVIEW", "SCREENING", "HUMAN_SCREEN_REVIEW", "TIERING", "DUE_DILIGENCE", "ASSESSMENT", "VERIFICATION", "HUMAN_REVIEW", "CONTRACTING", "FINAL_APPROVAL", "ONBOARDED", "MONITORING"];

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.appendChild(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const badge = (text, cls) => h("span", { class: "badge " + (cls || "") }, text);
const fmt = (s) => (s ? String(s).replace("T", " ").slice(0, 16) : "");
const money = (n) => (n == null ? "-" : "$" + Number(n).toLocaleString());

function toast(msg, kind) {
  const t = h("div", { class: "toast " + (kind || "") }, msg);
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 3500);
}
function $(s, r) { return (r || document).querySelector(s); }

async function api(method, path, body, raw) {
  const opts = { method, headers: { Authorization: `Bearer dev.${S.user}.${S.role}.${S.tenant}` } };
  if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  if (raw) return r;
  let data = null;
  try { data = await r.json(); } catch (e) { /* non-JSON */ }
  if (!r.ok) { const err = new Error((data && data.error && data.error.message) || r.statusText); err.code = data && data.error && data.error.code; throw err; }
  return data;
}
async function act(fn, okMsg) {
  try { const r = await fn(); if (okMsg) toast(okMsg, "ok"); return r; }
  catch (e) { toast((e.code ? e.code + ": " : "") + e.message, "err"); return null; }
}

function modal(title, fields, submitLabel, danger) {
  return new Promise((resolve) => {
    const root = $("#modal-root");
    const inputs = {};
    const form = h("div", { class: "modal", role: "dialog", "aria-modal": "true", "aria-label": title }, h("h2", {}, title));
    for (const f of fields) {
      let inp;
      if (f.type === "select") inp = h("select", {}, f.options.map((o) => h("option", { value: o.value ?? o }, o.label ?? o)));
      else if (f.type === "textarea") inp = h("textarea", { rows: 3, placeholder: f.placeholder || "" });
      else inp = h("input", { type: f.type || "text", placeholder: f.placeholder || "" });
      if (f.value !== undefined) inp.value = f.value;
      inputs[f.name] = inp;
      form.appendChild(h("label", { class: "f" }, h("span", {}, f.label), inp));
    }
    const close = (v) => { root.innerHTML = ""; resolve(v); };
    form.appendChild(h("div", { class: "row", style: "margin-top:12px;justify-content:flex-end" },
      h("button", { onclick: () => close(null) }, "Cancel"),
      h("button", { class: danger ? "danger" : "primary", onclick: () => { const v = {}; for (const k in inputs) v[k] = inputs[k].value; close(v); } }, submitLabel || "Submit")));
    root.innerHTML = "";
    root.appendChild(h("div", { class: "overlay" }, form));
    const first = form.querySelector("input,textarea,select"); if (first) first.focus();
  });
}

/* ---------------------------------------------------------------- views */
const sevBadge = (s) => badge(s, "sev-" + s);
const stateBadge = (s) => badge(s.replace(/_/g, " "), "state " + (["REJECTED"].includes(s) ? "bad" : ["ONBOARDED", "MONITORING"].includes(s) ? "good" : ""));

async function viewQueue(app) {
  const state = new URLSearchParams(location.hash.split("?")[1] || "").get("state") || "";
  const { cases } = await api("GET", "/v1/cases" + (state ? "?state=" + encodeURIComponent(state) : ""));
  const states = ["", "INTAKE_REVIEW", "HUMAN_SCREEN_REVIEW", "TIERING", "DUE_DILIGENCE", "HUMAN_REVIEW", "CONTRACTING", "FINAL_APPROVAL", "MONITORING", "REJECTED"];
  app.append(h("h1", {}, "Case queue"), h("p", { class: "muted" }, "Cases waiting on a person show their open gate and SLA due time. Agents only prepare; people decide."));
  app.append(h("div", { class: "row" }, h("label", {}, "State ", h("select", { onchange: (e) => (location.hash = "#/" + (e.target.value ? "?state=" + e.target.value : "")) },
    states.map((s) => h("option", { value: s, selected: s === state }, s || "All")))), h("span", { class: "grow" }), h("a", { href: "#/new" }, "+ New case")));
  const now = new Date().toISOString();
  app.append(h("div", { class: "card" }, cases.length ? h("table", {}, h("thead", {}, h("tr", {}, ["Vendor", "State", "Tier", "Open gate", "Due", "Requester", "Updated"].map((t) => h("th", {}, t)))),
    h("tbody", {}, cases.map((c) => h("tr", { class: "click", tabindex: 0, onclick: () => (location.hash = "#/case/" + c.case_id), onkeydown: (e) => e.key === "Enter" && (location.hash = "#/case/" + c.case_id) },
      h("td", {}, h("b", {}, c.legal_name || c.case_id), c.emergency ? badge("EMERGENCY", "sev-HIGH") : null), h("td", {}, stateBadge(c.state)),
      h("td", {}, c.final_tier || c.proposed_tier ? "T" + (c.final_tier || c.proposed_tier) : "-"), h("td", {}, c.open_gates || "-"),
      h("td", { class: c.next_due && c.next_due < now ? "small" : "small", style: c.next_due && c.next_due < now ? "color:#b91c1c;font-weight:600" : "" }, fmt(c.next_due) + (c.next_due && c.next_due < now ? " (overdue)" : "")),
      h("td", { class: "small" }, c.requester_id), h("td", { class: "small" }, fmt(c.updated_at)))))) : h("p", { class: "muted" }, "No cases yet. Create one or load a synthetic scenario from New case.")));
}

async function viewNew(app) {
  const { scenarios } = await api("GET", "/v1/dev/scenarios").catch(() => ({ scenarios: [] }));
  app.append(h("h1", {}, "New vendor case"));
  if (scenarios.length) {
    app.append(h("div", { class: "card" }, h("h2", {}, "Load a synthetic scenario"), h("p", { class: "muted small" }, "Fictional vendors with documents for a safe walkthrough. Requires the sponsor role."),
      h("table", {}, h("tbody", {}, scenarios.map((s) => h("tr", {}, h("td", {}, h("b", {}, s.name), h("div", { class: "small muted" }, s.note || s.key)), h("td", { class: "small" }, s.docs + " docs"),
        h("td", {}, h("button", { onclick: async () => { const r = await act(() => api("POST", `/v1/dev/scenarios/${s.key}/load`), "Scenario loaded"); if (r) location.hash = "#/case/" + r.case_id; } }, "Load"))))))));
  }
  const f = {};
  const field = (name, label, type, ph, val) => { f[name] = type === "select" ? null : h("input", { type: type || "text", placeholder: ph || "", value: val ?? "" }); return h("label", { class: "f" }, h("span", {}, label), f[name]); };
  const sel = (name, label, opts, val) => { f[name] = h("select", {}, opts.map((o) => h("option", { value: o, selected: o === val }, o))); return h("label", { class: "f" }, h("span", {}, label), f[name]); };
  const own = h("textarea", { rows: 2, placeholder: "One per line: Name, percent, country (e.g. Aldane Capital Fund II, 60, LU)" });
  const desc = h("textarea", { rows: 3, placeholder: "What will the bank use this vendor for?" });
  const dt = h("select", { multiple: true, size: 5 }, ["public", "internal", "confidential", "customer_pii", "payment_card", "authentication_secrets", "regulated_other"].map((o) => h("option", { value: o, selected: o === "customer_pii" }, o)));
  const jur = h("select", { multiple: true, size: 4 }, ["US", "EU", "IN", "UK", "OTHER"].map((o) => h("option", { value: o, selected: o === "EU" }, o)));
  const emerg = h("input", { type: "checkbox" });
  app.append(h("div", { class: "card" }, h("h2", {}, "Intake form"), h("div", { class: "grid" },
    field("legal_name", "Legal name", "text", "Acme Cloud Ltd"), field("country_iso2", "Country (ISO-2)", "text", "DE", "DE"), field("registration_number", "Registration number", "text"),
    field("website", "Website", "text"), field("business_owner", "Business owner", "text", "", S.user), field("annual_spend_usd", "Annual spend (USD)", "number", "250000")),
    h("label", { class: "f" }, h("span", {}, "Service description"), desc),
    h("div", { class: "grid" }, sel("criticality_hint", "Criticality", ["low", "medium", "high", "critical"], "medium"), sel("substitutability", "Substitutability", ["easy", "moderate", "hard", "very_hard"], "moderate"),
      sel("volume", "Data volume", ["none", "low", "medium", "high", "very_high"], "medium"), sel("access_type", "Access type", ["none", "read_only", "read_write", "privileged", "network_connectivity"], "read_only"),
      field("storage_locations", "Storage locations (comma separated ISO-2)", "text", "DE, IE")),
    h("div", { class: "grid" }, h("label", { class: "f" }, h("span", {}, "Data types (hold Ctrl/Cmd for several)"), dt), h("label", { class: "f" }, h("span", {}, "Jurisdictions"), jur)),
    h("label", { class: "f" }, h("span", {}, "Declared owners (25%+ holders)"), own), field("subcontractors", "Subcontractors (comma separated)", "text"), field("directors", "Directors (comma separated)", "text"),
    h("label", { class: "row" }, emerg, h("span", {}, "Emergency onboarding (needs Head of TPRM conditional approval)")),
    h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "primary", onclick: async () => {
      const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
      const owners = own.value.split("\n").map((l) => l.split(",").map((x) => x.trim())).filter((p) => p[0]).map((p) => ({ name: p[0], pct: parseFloat(p[1] || "0"), country_iso2: p[2] || null }));
      const body = { legal_name: f.legal_name.value, country_iso2: f.country_iso2.value.toUpperCase(), registration_number: f.registration_number.value || null, website: f.website.value || null,
        service_description: desc.value, business_owner: f.business_owner.value, annual_spend_usd: f.annual_spend_usd.value ? parseFloat(f.annual_spend_usd.value) : null,
        data_access: { data_types: [...dt.selectedOptions].map((o) => o.value), volume: f.volume.value, storage_locations: list(f.storage_locations.value), access_type: f.access_type.value },
        criticality_hint: f.criticality_hint.value, substitutability: f.substitutability.value, subcontractors: list(f.subcontractors.value), directors: list(f.directors.value),
        jurisdictions: [...jur.selectedOptions].map((o) => o.value), declared_owners: owners, emergency: emerg.checked };
      const r = await act(() => api("POST", "/v1/cases", body), "Case created");
      if (r) location.hash = "#/case/" + r.case_id;
    } }, "Create case"))));
}

function stepper(c) {
  const cur = c.state; const idx = ORDER.indexOf(cur === "HUMAN_SCREEN_REVIEW" ? "SCREENING" : cur === "ONBOARDED" ? "MONITORING" : cur);
  return h("div", { class: "stepper" }, cur === "REJECTED" ? badge("REJECTED", "state bad") : null, MAIN_STEPS.map(([k, label]) => {
    const i = ORDER.indexOf(k); const cls = cur === "REJECTED" ? (i < idx ? "done" : "") : i < idx ? "done" : i === idx ? "cur" : "";
    return h("span", { class: "step " + cls }, label);
  }));
}

function canDecide(v, gate) { const r = (v.allowed_gate_roles || {})[gate] || []; return r.includes(S.role); }

function nextStepPanel(v, reload) {
  const c = v.case, cid = c.case_id, st = c.state;
  const box = (title, ...kids) => h("div", { class: "card next" }, h("h2", {}, title), ...kids);
  const roleNote = (gate) => canDecide(v, gate) ? null : h("p", { class: "small muted" }, `You are ${S.role}. Allowed to decide ${gate}: ${(v.allowed_gate_roles[gate] || []).join(", ") || "none"}. Switch role at the top to act.`);
  const btn = (label, cls, fn, disabled) => h("button", { class: cls, disabled, onclick: async () => { const r = await fn(); if (r !== null && r !== undefined) reload(); } }, label);
  const wait = (t) => box("Waiting", h("p", { class: "muted" }, t));
  if (v.open_critical) var critWarn = h("div", { class: "danger-box" }, `${v.open_critical} CRITICAL finding(s) are open. Approval is blocked until each is remediated or has a time-boxed exception.`);
  if (st === "INTAKE_REVIEW") {
    const t = v.tasks.find((x) => x.gate === "G0" && x.status === "OPEN");
    if (!t) return wait("Advancing automatically.");
    const cands = (t.payload && t.payload.candidates) || [];
    return box("G0: Is this an existing vendor?", h("p", {}, "The system found a similar vendor in the master but is not sure enough to link automatically."),
      h("table", {}, h("tbody", {}, cands.map((x) => h("tr", {}, h("td", {}, x.legal_name), h("td", { class: "small" }, "match probability " + x.p), h("td", {}, btn("Same vendor: link", "primary", () => act(() => api("POST", `/v1/cases/${cid}/gates/G0`, { decision: "CONFIRM", subject: x.vendor_id, rationale: "confirmed same legal entity" }), "Linked"), !canDecide(v, "G0"))))))),
      h("div", { class: "row", style: "margin-top:8px" }, btn("Different vendor: continue as new", "", () => act(() => api("POST", `/v1/cases/${cid}/gates/G0`, { decision: "REJECT", rationale: "not the same legal entity" }), "Continuing as new vendor"), !canDecide(v, "G0"))), roleNote("G0"));
  }
  if (st === "HUMAN_SCREEN_REVIEW") {
    const open = v.screening.filter((s) => s.auto_disposition === "POTENTIAL_MATCH" && !s.human_disposition);
    return box(`G1: Sanctions review (${open.length} open)`, h("p", { class: "small muted" }, "Only an AML officer can clear or confirm a match. The system recommendation is shown for triage only and never clears anything."),
      open.map((s) => h("div", { class: "finding" }, h("div", {}, h("b", {}, s.subject_name), " ", badge(s.subject_role), " vs ", h("b", {}, s.match_name || "(ownership aggregate)"), " score ", (s.score || 0).toFixed(2)),
        h("div", { class: "small" }, "Recommendation (advisory): ", badge(s.recommendation || "NEEDS_HUMAN")), h("p", { class: "small" }, s.explanation),
        h("div", { class: "row" }, btn("Clear (false positive)", "", async () => { const m = await modal("Clear match", [{ name: "rationale", label: "Rationale (required)", type: "textarea" }], "Clear"); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/screening/${s.screening_id}`, { decision: "CLEAR", rationale: m.rationale }), "Match cleared"); }, !canDecide(v, "G1")),
          btn("Confirm true match: reject vendor", "danger", async () => { const m = await modal("Confirm match", [{ name: "rationale", label: "Rationale (required)", type: "textarea" }], "Confirm and reject", true); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/screening/${s.screening_id}`, { decision: "CONFIRM_MATCH", rationale: m.rationale }), "Match confirmed"); }, !canDecide(v, "G1"))))), roleNote("G1"));
  }
  if (st === "TIERING") {
    const t = v.tasks.find((x) => x.gate === "G2" && x.status === "OPEN"); if (!t) return wait("Advancing automatically.");
    const p = (t.payload && t.payload.proposal) || {}; const fac = p.factors || {};
    return box(`G2: Confirm tier. Proposed T${c.proposed_tier} (inherent score ${p.inherent_score})`, h("p", { class: "small muted" }, "Score computed by code from the intake, not by a model. Override needs a written reason."),
      h("table", {}, h("thead", {}, h("tr", {}, ["Factor", "Value", "Weight", "Points", "Why"].map((x) => h("th", {}, x)))), h("tbody", {}, Object.entries(fac).map(([k, f]) => h("tr", {}, h("td", {}, k.replace(/_/g, " ")), h("td", {}, f.value), h("td", {}, f.weight), h("td", {}, f.contribution), h("td", { class: "small" }, f.reason))))),
      p.floors_applied && p.floors_applied.length ? h("p", { class: "small" }, "Floors applied: " + p.floors_applied.join(", ")) : null,
      h("div", { class: "row", style: "margin-top:8px" }, btn("Confirm tier", "primary", () => act(() => api("POST", `/v1/cases/${cid}/gates/G2`, { decision: "CONFIRM", rationale: "agree with proposed tier" }), "Tier confirmed"), !canDecide(v, "G2")),
        btn("Override tier", "", async () => { const m = await modal("Override tier", [{ name: "tier", label: "New tier", type: "select", options: ["1", "2", "3", "4"] }, { name: "rationale", label: "Rationale (min 15 chars)", type: "textarea" }], "Override"); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/gates/G2`, { decision: "OVERRIDE", override_tier: parseInt(m.tier), rationale: m.rationale }), "Tier overridden"); }, !canDecide(v, "G2"))), roleNote("G2"));
  }
  if (st === "DUE_DILIGENCE") {
    return box("Due diligence: waiting for evidence", v.missing_docs.length ? h("div", {}, h("p", {}, "Still required for this tier and jurisdiction:"), h("ul", {}, v.missing_docs.map((d) => h("li", {}, d.replace(/_/g, " ")))),
      h("p", { class: "small muted" }, "A draft request to the vendor has been prepared on the Questions & drafts tab. Nothing is sent automatically."),
      h("div", { class: "row" }, h("a", { href: `#/case/${cid}/documents` }, "Upload documents"), h("span", { class: "grow" }),
        btn("Proceed with documented gaps", "", async () => { const m = await modal("Proceed with gaps", [{ name: "ok", label: "Type PROCEED to confirm. Missing evidence is scored as zero coverage.", type: "text" }], "Proceed"); if (!m || m.ok !== "PROCEED") return null; return act(() => api("POST", `/v1/cases/${cid}/actions/proceed-with-gaps`, {}), "Proceeding"); }, !["analyst", "senior_analyst"].includes(S.role)))) : h("p", {}, "All required documents are on file."));
  }
  if (st === "HUMAN_REVIEW") {
    return box("G3: Review findings", critWarn, h("p", {}, `${v.findings.length} open finding(s). Review each on the Findings tab; dispute anything you disagree with, and record remediation or time-boxed exceptions.`),
      h("div", { class: "row" }, btn("Approve to contracting", "primary", async () => { const m = await modal("Approve findings review", [{ name: "rationale", label: "Rationale", type: "textarea" }], "Approve"); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/gates/G3`, { decision: "APPROVE", rationale: m.rationale }), "Moved to contracting"); }, !canDecide(v, "G3")),
        btn("Request rework", "", async () => { const m = await modal("Request rework", [{ name: "rationale", label: "What should change?", type: "textarea" }], "Send back"); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/gates/G3`, { decision: "REQUEST_REWORK", rationale: m.rationale }), "Sent back"); }, !canDecide(v, "G3")),
        btn("Reject vendor", "danger", async () => { const m = await modal("Reject vendor", [{ name: "rationale", label: "Reason", type: "textarea" }], "Reject", true); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/gates/G3`, { decision: "REJECT", rationale: m.rationale }), "Rejected"); }, !canDecide(v, "G3"))), roleNote("G3"));
  }
  if (st === "CONTRACTING") return box("Contracting", h("p", {}, "Negotiate any missing clauses, then mark contracting complete."), btn("Mark contracting complete", "primary", () => act(() => api("POST", `/v1/cases/${cid}/actions/contracting-complete`, {}), "Sent to final approval"), !["analyst", "senior_analyst", "legal"].includes(S.role)));
  if (st === "FINAL_APPROVAL") {
    return box(`G4: Final approval (T${c.final_tier})`, critWarn, h("p", { class: "small muted" }, `Approver must differ from the requester (${c.requester_id}) and the preparer (${c.preparer_id || "n/a"}).`),
      h("div", { class: "row" }, btn("Approve", "primary", async () => { const m = await modal("Final approval", [{ name: "rationale", label: "Rationale", type: "textarea" }, { name: "cond", label: "Conditions (one per line; leave empty for unconditional)", type: "textarea" }, { name: "exp", label: "Condition deadline (YYYY-MM-DD, max 30 days; required with conditions)", type: "text" }], "Approve"); if (!m) return null;
        const conds = m.cond.split("\n").map((x) => x.trim()).filter(Boolean); return act(() => api("POST", `/v1/cases/${cid}/gates/G4`, { decision: "APPROVE", rationale: m.rationale, conditions: conds, expires_at: m.exp || null }), "Vendor onboarded"); }, !canDecide(v, "G4")),
        btn("Reject", "danger", async () => { const m = await modal("Reject vendor", [{ name: "rationale", label: "Reason", type: "textarea" }], "Reject", true); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/gates/G4`, { decision: "REJECT", rationale: m.rationale }), "Rejected"); }, !canDecide(v, "G4")),
        h("a", { href: `/v1/cases/${cid}/packet`, target: "_blank", rel: "noopener" }, "Open approval packet")), roleNote("G4"));
  }
  if (st === "MONITORING" || st === "ONBOARDED") return box("Onboarded: continuous monitoring", h("p", {}, "Staleness sweeps and list updates re-open work automatically."),
    btn("Record material change", "", async () => { const m = await modal("Material change", [{ name: "kind", label: "What changed? (e.g. ownership, breach, new subprocessor)", type: "text" }], "Record"); if (!m) return null; return act(() => api("POST", `/v1/cases/${cid}/actions/material-change`, { kind: m.kind }), "Re-assessing"); }));
  if (st === "REJECTED") return box("Case closed: rejected", h("p", { class: "muted" }, "This case is terminal. The audit trail is retained."));
  return wait("The system is working on this step.");
}

function overviewTab(v) {
  const c = v.case, a = v.assessment, i = c.intake; const res = a && a.residual;
  return h("div", {}, h("div", { class: "grid" },
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Tier"), h("div", { class: "kpi" }, c.final_tier || c.proposed_tier ? "T" + (c.final_tier || c.proposed_tier) : "-"), h("div", { class: "small muted" }, c.final_tier ? "confirmed" : "proposed")),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Residual risk"), h("div", {}, res ? badge(res.band, "band-" + res.band) : "-"), h("div", { class: "small muted" }, res ? `inherent ${a.inherent.inherent_score} → residual ${res.residual_score}` + (res.critical_cap_applied ? " (floor applied)" : "") : "not assessed")),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Claims"), h("div", {}, Object.entries(v.claim_counts).map(([k, n]) => h("span", { style: "margin-right:6px" }, badge(k + " " + n, "st-" + k))))),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Open findings"), h("div", {}, ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"].map((s) => { const n = v.findings.filter((f) => f.severity === s).length; return n ? h("span", { style: "margin-right:6px" }, badge(s + " " + n, "sev-" + s)) : null; })))),
    a ? h("div", { class: "card" }, h("h2", {}, "Assessment summary"), h("p", {}, a.narrative), h("p", { class: "small muted" }, `Scoring ${a.scoring_version}. Narrative text is produced from structured results; numbers come from the scoring engine.`),
      h("div", { class: "grid" }, Object.entries(a.control_effectiveness || {}).map(([d, x]) => h("div", {}, h("div", { class: "small" }, d, " ", (x.ce * 100).toFixed(0) + "%"), h("div", { class: "bar" }, h("i", { style: `width:${Math.round(x.ce * 100)}%` })))))) : null,
    h("div", { class: "card" }, h("h2", {}, "Vendor"), h("table", {}, h("tbody", {}, [["Legal name", i.legal_name], ["Country", i.country_iso2], ["Service", i.service_description], ["Business owner", i.business_owner], ["Annual spend", money(i.annual_spend_usd)],
      ["Data", `${i.data_access.data_types.join(", ")} (${i.data_access.volume}), access ${i.data_access.access_type}`], ["Jurisdictions", i.jurisdictions.join(", ")], ["Subcontractors", (i.subcontractors || []).join(", ") || "-"]].map(([k, val]) => h("tr", {}, h("th", { style: "width:160px" }, k), h("td", {}, val)))))));
}

function screeningTab(v) {
  return h("div", { class: "card" }, h("h2", {}, "Sanctions and ownership screening"), h("p", { class: "small muted" }, "Every subject is screened (vendor, trade names, directors, owners, subcontractors). Review threshold favours recall; humans disposition potential matches."),
    h("table", {}, h("thead", {}, h("tr", {}, ["Subject", "Role", "Best candidate", "Score", "System", "Human"].map((x) => h("th", {}, x)))), h("tbody", {}, v.screening.map((s) => h("tr", {}, h("td", {}, s.subject_name), h("td", {}, badge(s.subject_role)), h("td", {}, s.match_name || "-"),
      h("td", {}, (s.score || 0).toFixed(2)), h("td", {}, badge(s.auto_disposition, s.auto_disposition === "POTENTIAL_MATCH" ? "sev-HIGH" : ""), h("div", { class: "small muted" }, s.explanation)),
      h("td", {}, s.human_disposition ? badge(s.human_disposition) : "-", s.rationale ? h("div", { class: "small muted" }, s.dispositioned_by + ": " + s.rationale) : null))))));
}

function documentsTab(v, reload) {
  const cid = v.case.case_id; const inp = h("input", { type: "file", multiple: true, "aria-label": "choose documents" });
  const up = async () => {
    for (const f of inp.files) {
      const buf = new Uint8Array(await f.arrayBuffer()); let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
      const r = await act(() => api("POST", `/v1/cases/${cid}/documents`, { filename: f.name, content_base64: btoa(bin) }), null);
      if (r) toast(`${f.name}: ${r.duplicate ? "already on file" : r.status}${r.flags && r.flags.length ? " (embedded instructions neutralised)" : ""}`, r.flags && r.flags.length ? "err" : "ok");
    }
    reload();
  };
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Upload evidence"), h("p", { class: "small muted" }, "TXT, MD, HTML, DOCX, CSV are parsed. PDF parsing is not enabled in this build. Files are quarantined, scanned for hidden or instruction-like text, and treated as untrusted data."),
    h("div", { class: "row" }, inp, h("button", { class: "primary", onclick: up }, "Upload")), v.missing_docs.length ? h("p", { class: "warn" }, "Missing: " + v.missing_docs.join(", ")) : null),
    h("div", { class: "card" }, h("h2", {}, "Documents"), v.documents.length ? h("table", {}, h("thead", {}, h("tr", {}, ["File", "Type", "Status", "Flags", "Uploaded", ""].map((x) => h("th", {}, x)))), h("tbody", {}, v.documents.map((d) => h("tr", {},
      h("td", {}, d.filename, d.supersedes_doc_id ? h("div", { class: "small muted" }, "supersedes an earlier version") : null), h("td", {}, d.doc_type), h("td", {}, badge(d.quarantine_status)),
      h("td", {}, (d.injection_flags || []).length ? badge("embedded instructions: " + d.injection_flags.map((x) => x.kind).join(", "), "sev-HIGH") : d.hidden_text_flag ? badge("hidden text", "sev-MEDIUM") : "-"),
      h("td", { class: "small" }, fmt(d.uploaded_at) + " " + d.uploaded_by), h("td", {}, d.quarantine_status === "ACCEPTED" ? h("a", { href: `#/doc/${cid}/${d.doc_id}` }, "View") : null))))) : h("p", { class: "muted" }, "No documents yet.")));
}

async function claimsTab(v) {
  const { claims } = await api("GET", `/v1/cases/${v.case.case_id}/claims`);
  let filter = "";
  const holder = h("div", { class: "card" });

  const claimRow = (c) => h("tr", {},
    h("td", {}, badge(c.status === "STALE" ? "STALE / DON'T TRUST YET" : c.status, "st-" + c.status), c.stale_reason ? h("div", { class: "small muted" }, c.stale_reason) : null),
    h("td", {}, c.statement, h("div", { class: "small muted mono" }, c.predicate)),
    h("td", { class: "small" }, (c.evidence || []).map((e) => e.doc_id
      ? h("div", {}, h("a", { href: `#/doc/${v.case.case_id}/${e.doc_id}?page=${e.page || 1}&q=${encodeURIComponent(e.quote || "")}` }, "p." + (e.page || "?")), " \u201c" + (e.quote || e.locator || "") + "\u201d")
      : h("div", {}, e.source_type + ": " + (e.locator || "")))));
  const draw = () => {
    holder.innerHTML = "";
    const shown = claims.filter((c) => !filter || c.status === filter);
    holder.append(h("h2", {}, `Claim ledger (${shown.length})`), h("p", { class: "small muted" }, "Every claim cites a document, page and verbatim quote. Only TRUSTED claims feed scoring. Stale claims are shown, labelled, and never deleted."),
      h("div", { class: "row" }, ["", "TRUSTED", "UNTRUSTED", "STALE", "REFUTED", "SUPERSEDED"].map((s) => h("button", { class: filter === s ? "primary" : "", onclick: () => { filter = s; draw(); } }, s || "All"))),
      h("table", {}, h("thead", {}, h("tr", {}, ["Status", "Statement", "Evidence"].map((x) => h("th", {}, x)))), h("tbody", {}, shown.map(claimRow))));
  };
  draw();
  return holder;
}

function findingsTab(v, reload) {
  const cid = v.case.case_id; const claimsP = api("GET", `/v1/cases/${cid}/claims`);
  const wrap = h("div", {});
  claimsP.then(({ claims }) => {
    const byId = Object.fromEntries(claims.map((c) => [c.claim_id, c]));
    if (!v.findings.length) wrap.append(h("div", { class: "card" }, "No open findings."));
    for (const f of v.findings) {
      wrap.append(h("div", { class: "finding" }, h("div", { class: "row" }, sevBadge(f.severity), h("b", {}, f.title), h("span", { class: "small muted mono" }, f.rule_id || ""), f.disposition ? badge(f.disposition, "st-TRUSTED") : null, f.disputed ? badge("disputed", "st-STALE") : null),
        h("p", {}, f.description), f.remediation ? h("p", { class: "small" }, h("b", {}, "Suggested remediation: "), f.remediation) : null,
        (f.regulation_refs || []).length ? h("p", { class: "small muted" }, "References (VERIFY with Compliance): " + f.regulation_refs.join("; ")) : null,
        (f.claim_ids || []).map((id) => { const c = byId[id]; if (!c) return null; return h("div", { class: "cite" }, h("b", {}, c.status === "TRUSTED" ? "TRUSTED" : c.status), ": ", c.statement,
          (c.evidence || []).map((e) => e.doc_id ? h("div", {}, h("a", { href: `#/doc/${cid}/${e.doc_id}?page=${e.page || 1}&q=${encodeURIComponent(e.quote || "")}` }, "document p." + (e.page || "?")), " “" + (e.quote || "") + "”") : h("div", {}, "system record: " + (e.locator || "")))); }),
        h("div", { class: "row", style: "margin-top:8px" },
          h("button", { onclick: async () => { const m = await modal("I disagree with this finding", [{ name: "reason", label: "Why? (feeds evaluation review)", type: "textarea" }], "Send"); if (m) { if (await act(() => api("POST", `/v1/cases/${cid}/findings/${f.finding_id}/dispute`, { reason: m.reason }), "Feedback recorded")) reload(); } } }, "I disagree"),
          h("button", { onclick: async () => { const m = await modal("Disposition finding", [{ name: "action", label: "Action", type: "select", options: ["REMEDIATED", "ACCEPT_RISK"] }, { name: "rationale", label: "Rationale", type: "textarea" }, { name: "exp", label: "Exception expiry (YYYY-MM-DD, required for ACCEPT_RISK)", type: "text" }], "Save"); if (m) { if (await act(() => api("POST", `/v1/cases/${cid}/findings/${f.finding_id}/disposition`, { action: m.action, rationale: m.rationale, expires_at: m.exp || null }), "Disposition recorded")) reload(); } } }, "Disposition"))));
    }
  });
  return wrap;
}

function questionsTab(v, reload) {
  const cid = v.case.case_id;
  return h("div", {}, h("div", { class: "card" }, h("h2", {}, "Open questions"), v.questions.length ? h("table", {}, h("tbody", {}, v.questions.map((q) => h("tr", {}, h("td", {}, badge(q.to_role), q.blocking ? badge("blocking", "sev-HIGH") : null), h("td", {}, q.text, h("div", { class: "small muted" }, q.why)),
    h("td", {}, q.status === "OPEN" ? h("button", { onclick: async () => { const m = await modal("Answer question", [{ name: "answer", label: q.text, type: "textarea" }], "Save"); if (m) { if (await act(() => api("POST", `/v1/cases/${cid}/questions/${q.question_id}/answer`, { answer: m.answer }), "Saved")) reload(); } } }, "Answer") : badge("answered", "st-TRUSTED")))))) : h("p", { class: "muted" }, "None.")),
    h("div", { class: "card" }, h("h2", {}, "Drafts for the vendor"), h("p", { class: "small muted" }, "Drafts only. Nothing in this system sends a message; a person reviews and sends from their own mail client."),
      v.drafts.length ? v.drafts.map((d) => h("div", { class: "finding" }, h("div", { class: "row" }, badge(d.kind), badge(d.status), h("span", { class: "small muted" }, fmt(d.created_at))), h("pre", { class: "page" }, d.body))) : h("p", { class: "muted" }, "None.")));
}

function timelineTab(v) {
  return h("div", { class: "card" }, h("h2", {}, "Audit timeline"), h("p", { class: "small muted" }, "Append-only and hash-chained. Entries cannot be edited or deleted."),
    h("table", {}, h("thead", {}, h("tr", {}, ["#", "When", "Actor", "Action", "Detail"].map((x) => h("th", {}, x)))), h("tbody", {}, v.timeline.map((e) => h("tr", {}, h("td", { class: "small" }, e.seq), h("td", { class: "small" }, fmt(e.ts)), h("td", {}, e.actor, " ", badge(e.actor_type)), h("td", { class: "mono small" }, e.action), h("td", { class: "small mono" }, JSON.stringify(e.payload).slice(0, 220)))))));
}

async function viewCase(app, cid, tab) {
  tab = tab || "overview";
  const reload = () => render();
  const v = await api("GET", "/v1/cases/" + cid);
  const c = v.case;
  app.append(h("div", { class: "row" }, h("div", { class: "grow" }, h("h1", {}, c.intake.legal_name), h("div", { class: "small muted" }, `${cid} · requester ${c.requester_id} · created ${fmt(c.created_at)}`)), stateBadge(c.state),
    c.emergency ? badge("EMERGENCY", "sev-HIGH") : null, c.conditional_expires ? badge("conditional until " + c.conditional_expires, "st-STALE") : null), stepper(c));
  app.append(nextStepPanel(v, reload));
  const tabs = [["overview", "Overview"], ["screening", "Screening"], ["documents", "Documents"], ["claims", "Claims"], ["findings", `Findings (${v.findings.length})`], ["questions", "Questions & drafts"], ["timeline", "Timeline"], ["packet", "Approval packet"]];
  app.append(h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, label]) => h("a", { class: "tab " + (k === tab ? "on" : ""), role: "tab", href: `#/case/${cid}/${k}` }, label))));
  const body = h("div", { style: "padding-top:12px" }); app.append(body);
  if (tab === "overview") body.append(overviewTab(v));
  else if (tab === "screening") body.append(screeningTab(v));
  else if (tab === "documents") body.append(documentsTab(v, reload));
  else if (tab === "claims") body.append(await claimsTab(v));
  else if (tab === "findings") body.append(findingsTab(v, reload));
  else if (tab === "questions") body.append(questionsTab(v, reload));
  else if (tab === "timeline") body.append(timelineTab(v));
  else if (tab === "packet") {
    const r = await api("GET", `/v1/cases/${cid}/packet`, undefined, true); const html = await r.text();
    body.append(h("div", { class: "card" }, h("div", { class: "row" }, h("h2", { class: "grow" }, "Approval packet"), h("span", { class: "small muted" }, "Rendered in a sandboxed frame; Download for the standalone file."), h("button", { onclick: () => { const b = new Blob([html], { type: "text/html" }); const u = URL.createObjectURL(b); const a = h("a", { href: u, download: `packet-${cid}.html` }); document.body.append(a); a.click(); a.remove(); } }, "Download")),
      h("iframe", { sandbox: "", srcdoc: html, style: "width:100%;height:720px;border:1px solid #d9dee6;border-radius:6px", title: "approval packet" })));
  }
}

async function viewDoc(app, cid, did, params) {
  const r = await api("GET", `/v1/cases/${cid}/documents/${did}`);
  const page = parseInt(params.get("page") || "1"); const q = params.get("q") || "";
  const quotes = new Set(r.citations.map((c) => c.quote).filter(Boolean)); if (q) quotes.add(q);
  app.append(h("p", {}, h("a", { href: `#/case/${cid}/documents` }, "← back to case")), h("h1", {}, r.doc.filename), h("div", { class: "small muted" }, `${r.doc.doc_type} · sha256 ${r.doc.sha256.slice(0, 16)}… · ${r.doc.page_count} page(s)`));
  if ((r.doc.injection_flags || []).length) app.append(h("div", { class: "danger-box" }, "This document contains instruction-like or hidden content aimed at automated reviewers (" + r.doc.injection_flags.map((x) => x.kind).join(", ") + "). It was neutralised before analysis. Treat the submission with suspicion and review manually."));
  r.pages.forEach((text, i) => {
    const el = h("div", { class: "page", id: "p" + (i + 1) }); const segs = [{ t: text, m: false }];
    for (const qt of quotes) {
      for (let s = 0; s < segs.length; s++) {
        if (segs[s].m) continue; const idx = segs[s].t.toLowerCase().indexOf(qt.toLowerCase());
        if (idx >= 0) { const t = segs[s].t; segs.splice(s, 1, { t: t.slice(0, idx), m: false }, { t: t.slice(idx, idx + qt.length), m: true }, { t: t.slice(idx + qt.length), m: false }); break; }
      }
    }
    segs.forEach((sg) => el.appendChild(sg.m ? h("mark", {}, sg.t) : document.createTextNode(sg.t)));
    app.append(h("h3", {}, "Page " + (i + 1)), el);
  });
  const t = document.getElementById("p" + page); if (t) t.scrollIntoView();
}

async function viewKpis(app) {
  const k = await api("GET", "/v1/kpis");
  const total = Object.values(k.cases_by_state).reduce((a, b) => a + b, 0) || 1;
  app.append(h("h1", {}, "Programme KPIs"), h("div", { class: "grid" },
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Cases"), h("div", { class: "kpi" }, total)),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Trusted-claim ratio"), h("div", { class: "kpi" }, (k.trusted_ratio * 100).toFixed(0) + "%")),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "SLA overdue gates"), h("div", { class: "kpi" }, k.sla_overdue.length)),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Finding disputes (I disagree)"), h("div", { class: "kpi" }, k.finding_disputes)),
    h("div", { class: "card" }, h("div", { class: "muted small" }, "Agent cost (USD)"), h("div", { class: "kpi" }, Number(k.agent_cost_usd).toFixed(2)), h("div", { class: "small muted" }, k.agent_runs + " runs"))));
  const bars = (title, obj) => h("div", { class: "card" }, h("h2", {}, title), Object.entries(obj).map(([n, v]) => h("div", {}, h("div", { class: "small" }, n, " · ", v), h("div", { class: "bar" }, h("i", { style: `width:${Math.round((v / Math.max(...Object.values(obj), 1)) * 100)}%` })))));
  app.append(h("div", { class: "grid" }, bars("Cases by state", k.cases_by_state), bars("Open findings by severity", k.open_findings_by_severity), bars("Claims by status", k.claims_by_status)));
  const sd = k.stale_debt; app.append(h("div", { class: "card" }, h("h2", {}, "Stale debt"), h("pre", { class: "page" }, JSON.stringify(sd, null, 1))));
}

async function viewAdmin(app) {
  const a = await api("GET", "/v1/admin/status").catch((e) => ({ error: e.message }));
  if (a.error) { app.append(h("h1", {}, "Admin"), h("div", { class: "warn" }, a.error + ". Switch to the admin role at the top.")); return; }
  app.append(h("h1", {}, "Administration"),
    h("div", { class: "card" }, h("h2", {}, "Kill switch"), h("p", { class: "small muted" }, "Stops all model calls immediately. Cases keep their state; work resumes when switched off."),
      h("div", { class: "row" }, a.kill_switch ? badge("ACTIVE: all agents stopped", "sev-CRITICAL") : badge("off", "st-TRUSTED"),
        h("button", { class: a.kill_switch ? "primary" : "danger", onclick: async () => { if (await act(() => api("POST", "/v1/admin/kill-switch", { on: !a.kill_switch }), "Updated")) render(); } }, a.kill_switch ? "Resume agents" : "Stop all agents"))),
    h("div", { class: "card" }, h("h2", {}, "Policy"), h("p", {}, "Active: ", h("span", { class: "mono" }, a.policy_version)),
      h("p", { class: "small muted" }, "Activation needs a passing evaluation run and a second administrator (4-eyes)."),
      h("div", { class: "row" }, h("button", { onclick: async () => { const m = await modal("Request policy activation", [{ name: "pack", label: "Policy pack name", type: "text", value: "default" }], "Request"); if (m && (await act(() => api("POST", "/v1/admin/policy/requests", { pack: m.pack }), "Requested"))) render(); } }, "Request activation"),
        h("button", { onclick: async () => { if (await act(() => api("POST", "/v1/admin/sweep", {}), "Sweep done")) render(); } }, "Run staleness / SLA sweep")),
      h("table", {}, h("thead", {}, h("tr", {}, ["Pack", "Status", "Requested by", "Eval", ""].map((x) => h("th", {}, x)))), h("tbody", {}, a.activations.map((x) => h("tr", {}, h("td", {}, x.pack), h("td", {}, badge(x.status)), h("td", {}, x.requested_by), h("td", {}, x.eval_passed ? "passed" : "not run"),
        h("td", { class: "row" }, h("button", { onclick: async () => { const r = await act(() => api("POST", `/v1/admin/policy/requests/${x.activation_id}/eval`, {})); if (r) { toast(r.passed ? "Evaluation passed" : "Evaluation FAILED: " + r.failures.join("; "), r.passed ? "ok" : "err"); render(); } } }, "Run evals"),
          h("button", { onclick: async () => { if (await act(() => api("POST", `/v1/admin/policy/requests/${x.activation_id}/approve`, {}), "Activated")) render(); } }, "Approve")))))) ),
    h("div", { class: "card" }, h("h2", {}, "Audit log integrity"), h("p", {}, a.audit_chain.ok ? badge("hash chain intact · " + a.audit_chain.checked + " events", "st-TRUSTED") : badge("CHAIN BROKEN at seq " + a.audit_chain.first_bad_seq, "sev-CRITICAL")),
      h("p", { class: "small muted" }, "LLM provider: " + a.llm_provider)));
}

/* ---------------------------------------------------------------- router */
async function render() {
  const app = $("#app"); app.innerHTML = "";
  const raw = location.hash.replace(/^#\/?/, ""); const [path, qs] = raw.split("?"); const parts = path.split("/").filter(Boolean); const params = new URLSearchParams(qs || "");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("on", a.dataset.nav === (parts[0] || "queue")));
  try {
    if (!parts.length) await viewQueue(app);
    else if (parts[0] === "new") await viewNew(app);
    else if (parts[0] === "case") await viewCase(app, parts[1], parts[2]);
    else if (parts[0] === "doc") await viewDoc(app, parts[1], parts[2], params);
    else if (parts[0] === "kpis") await viewKpis(app);
    else if (parts[0] === "admin") await viewAdmin(app);
    else app.append(h("p", {}, "Not found."));
  } catch (e) { app.append(h("div", { class: "danger-box" }, (e.code ? e.code + ": " : "") + e.message)); }
  app.focus({ preventScroll: true });
}
window.addEventListener("hashchange", render);
const roleSel = $("#who-role"); ROLES.forEach((r) => roleSel.appendChild(h("option", { value: r, selected: r === S.role }, r)));
const userIn = $("#who-user"); userIn.value = S.user;
roleSel.addEventListener("change", () => { S.role = roleSel.value; sessionStorage.setItem("vro.role", S.role); render(); });
userIn.addEventListener("change", () => { S.user = userIn.value.replace(/[^\w-]/g, "") || "ui_user"; sessionStorage.setItem("vro.user", S.user); render(); });
render();
