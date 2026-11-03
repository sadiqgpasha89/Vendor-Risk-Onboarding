"""Report and audit export formatting utilities."""

import json
from typing import Dict, Any, List
from src.schemas.assessment import ComprehensiveRiskDossier


def format_dossier_as_markdown(dossier: ComprehensiveRiskDossier) -> str:
    """Format ComprehensiveRiskDossier as an audit-ready Markdown document."""
    lines = [
        f"# Vendor Risk Assessment Report: {dossier.vendor_id}",
        f"**Assessment ID:** `{dossier.assessment_id}`  ",
        f"**Generated:** `{dossier.created_at.isoformat()}`  ",
        f"**Overall Risk Tier:** **{dossier.overall_tier.value}** (Score: `{dossier.overall_score:.1f}/100`)  ",
        f"**Recommendation:** `{dossier.recommendation.value}`  ",
        f"**HITL Review Required:** `{'YES' if dossier.hitl_required else 'NO'}`" + (f" ({dossier.hitl_reason})" if dossier.hitl_reason else ""),
        "",
        "---",
        "",
        "## Executive Summary",
        dossier.executive_summary,
        "",
        "## Tier 1 Deterministic Policy Violations",
    ]

    if dossier.tier1_violations:
        lines.append("| Rule ID | Rule Name | Severity | Description |")
        lines.append("|---|---|---|---|")
        for v in dossier.tier1_violations:
            lines.append(f"| `{v.rule_id}` | {v.rule_name} | **{v.severity}** | {v.description} |")
    else:
        lines.append("✅ *No hard statutory or deterministic policy violations detected.*")

    lines.append("")
    lines.append("## Tier 2 Quantitative ML Anomaly & Risk Profile")
    if dossier.tier2_ml:
        ml = dossier.tier2_ml
        lines.append(f"- **Model:** `{ml.model_name} v{ml.model_version}`")
        lines.append(f"- **Calibrated Fraud/Risk Probability:** `{ml.calibrated_risk_probability:.4f}`")
        lines.append(f"- **Risk Decile:** `{ml.risk_decile}/10`")
        lines.append("")
        lines.append("### Top Risk Drivers (Local Feature Contribution)")
        for factor in ml.top_risk_drivers:
            lines.append(f"- **{factor.feature_name}** (+{factor.contribution:.2f}): {factor.description} (Value: `{factor.feature_value}`)")
    else:
        lines.append("*Quantitative ML score not available for this run.*")

    lines.append("")
    lines.append("## Operational & Regulatory Dimensions")
    lines.append("| Dimension | Score | Risk Level | Key Findings |")
    lines.append("|---|---|---|---|")
    for dim_name, dim in dossier.dimension_scores.items():
        findings_str = "; ".join(dim.findings[:2]) if dim.findings else "None"
        lines.append(f"| {dim.dimension} | {dim.score:.1f} | **{dim.risk_level.value}** | {findings_str} |")

    lines.append("")
    lines.append("## Key Red Flags")
    if dossier.key_red_flags:
        for rf in dossier.key_red_flags:
            lines.append(f"- 🚩 {rf}")
    else:
        lines.append("- *No critical red flags identified.*")

    lines.append("")
    lines.append("## Recommended Remediation Steps")
    for step in dossier.remediation_steps:
        lines.append(f"1. {step}")

    lines.append("")
    lines.append("## Citations & Audit Provenance")
    for citation in dossier.citations:
        lines.append(f"- {citation}")

    return "\n".join(lines)


def format_dossier_as_html(dossier: ComprehensiveRiskDossier) -> str:
    """Format ComprehensiveRiskDossier as self-contained HTML executive report."""
    md_content = format_dossier_as_markdown(dossier)
    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Vendor Risk Dossier - {dossier.vendor_id}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1a202c; }}
        h1, h2, h3 {{ color: #2d3748; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #e2e8f0; padding: 10px 12px; text-align: left; }}
        th {{ background-color: #f7fafc; font-weight: 600; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; }}
        .badge-critical {{ background: #fed7d7; color: #9b2c2c; }}
        .badge-high {{ background: #feebc8; color: #9c4221; }}
        .badge-medium {{ background: #fefcbf; color: #975a16; }}
        .badge-low {{ background: #c6f6d5; color: #22543d; }}
    </style>
</head>
<body>
    <pre style="white-space: pre-wrap; font-family: inherit;">{md_content}</pre>
</body>
</html>"""


def format_html_dossier(dossier_or_data: Any) -> str:
    """Format ComprehensiveRiskDossier or summary dictionary as self-contained styled HTML."""
    if isinstance(dossier_or_data, ComprehensiveRiskDossier):
        return format_dossier_as_html(dossier_or_data)

    data = dossier_or_data if isinstance(dossier_or_data, dict) else {}
    title = data.get("vendor_name", "Vendor Risk Dossier")
    tier = data.get("risk_tier", "ASSESSED")
    decision = data.get("decision", "PENDING")
    score = data.get("composite_score", 0.0)
    tier1 = data.get("tier1_summary", "No statutory violations")
    tier2 = data.get("tier2_summary", "ML score computed")
    agent = data.get("agent_summary", "Multi-agent synthesis complete")
    recs = data.get("recommendations", [])
    evid = data.get("evidence", [])

    recs_html = "".join(f"<li>{r}</li>" for r in recs) or "<li>None</li>"
    evid_html = "".join(f"<li>{e}</li>" for e in evid) or "<li>None</li>"

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.6; max-width: 960px; margin: 40px auto; padding: 0 20px; color: #1a202c; background: #f8fafc; }}
        .container {{ background: #ffffff; padding: 32px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
        h1 {{ color: #1e293b; margin-top: 0; }}
        .meta-bar {{ display: flex; gap: 16px; margin: 20px 0; }}
        .badge {{ display: inline-block; padding: 6px 12px; border-radius: 6px; font-weight: 700; font-size: 0.9em; }}
        .badge-risk {{ background: #fee2e2; color: #991b1b; }}
        .badge-decision {{ background: #dbeafe; color: #1e40af; }}
        .card {{ background: #f1f5f9; padding: 16px 20px; border-radius: 8px; margin-bottom: 16px; }}
        ul {{ margin-top: 6px; padding-left: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{title}</h1>
        <div class="meta-bar">
            <span class="badge badge-risk">TIER: {tier} (Score: {score})</span>
            <span class="badge badge-decision">DECISION: {decision}</span>
        </div>
        <div class="card">
            <h3>Tier 1: Deterministic Policy Check</h3>
            <p>{tier1}</p>
        </div>
        <div class="card">
            <h3>Tier 2: Quantitative ML & Anomaly Profile</h3>
            <p>{tier2}</p>
        </div>
        <div class="card">
            <h3>Tier 3: Agentic Governance & Synthesis</h3>
            <p>{agent}</p>
        </div>
        <h3>Key Recommendations</h3>
        <ul>{recs_html}</ul>
        <h3>Evidence & Audit Trail</h3>
        <ul>{evid_html}</ul>
    </div>
</body>
</html>"""


def format_markdown_dossier(dossier_or_data: Any) -> str:
    """Format ComprehensiveRiskDossier or dictionary as Markdown."""
    if isinstance(dossier_or_data, ComprehensiveRiskDossier):
        return format_dossier_as_markdown(dossier_or_data)
    data = dossier_or_data if isinstance(dossier_or_data, dict) else {}
    return f"# {data.get('vendor_name', 'Risk Dossier')}\n\n**Decision:** {data.get('decision', 'PENDING')}\n**Score:** {data.get('composite_score', 0)}"

