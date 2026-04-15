"""
Evaluation module — runs post-scoring analysis on all leads.
Produces per-lead assessments and system-level findings.
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def evaluate_lead(scored_lead: dict) -> dict:
    """Produce a per-lead evaluation assessment."""
    lead_id = scored_lead.get("lead_id", "Unknown")
    tier = scored_lead.get("adjusted_tier") or scored_lead.get("tier", "?")
    final_score = scored_lead.get("final_score", 0)
    ai_confidence = scored_lead.get("ai_confidence", "unknown")
    adjudication = scored_lead.get("adjudication_needed", False)

    # Assess correctness based on heuristics
    issues = []
    assessment = "likely_correct"

    # Flag potential false positives: high tier but low confidence
    if tier in ("A", "B") and ai_confidence == "low":
        issues.append("High tier with low AI confidence — possible false positive")
        assessment = "needs_review"

    # Flag potential false negatives: low tier but strong individual signals
    icp = scored_lead.get("icp_fit_score", 0)
    intent = scored_lead.get("intent_score", 0)
    if tier in ("C", "D") and (icp > 70 or intent > 70):
        issues.append(f"Low tier but strong individual signals (ICP={icp}, Intent={intent})")
        assessment = "needs_review"

    # Flag data quality concerns
    data_conf = scored_lead.get("data_confidence_score", 100)
    if data_conf < 50:
        issues.append(f"Low data confidence ({data_conf}) — scoring may be unreliable")

    # Flag adjudicated leads
    if adjudication:
        issues.append(f"Required adjudication: {scored_lead.get('adjudication_reasons', 'Unknown')}")

    return {
        "lead_id": lead_id,
        "company": scored_lead.get("company", "Unknown"),
        "assigned_tier": tier,
        "final_score": final_score,
        "assessment": assessment,
        "correct_signals": _identify_correct_signals(scored_lead),
        "questionable_signals": issues if issues else ["None identified"],
        "ai_confidence": ai_confidence,
    }


def _identify_correct_signals(lead: dict) -> list:
    """Identify what the model clearly got right."""
    correct = []
    tier = lead.get("adjusted_tier") or lead.get("tier", "")

    if tier == "A" and lead.get("demo_requested", "").lower() == "yes":
        correct.append("Demo request correctly boosted priority")
    if tier == "D" and lead.get("company_size", 0) in (0, "0"):
        correct.append("Unknown/micro company correctly deprioritized")
    if lead.get("icp_fit_score", 0) > 70 and "enterprise" in str(lead.get("company_size", 0)):
        correct.append("Enterprise size correctly recognized")
    if lead.get("data_confidence_score", 100) < 50 and lead.get("adjudication_needed"):
        correct.append("Low data confidence correctly flagged for adjudication")

    if not correct:
        correct.append("Scoring appears directionally correct based on available signals")

    return correct


def generate_system_evaluation(evaluations: list, scored_leads: list) -> dict:
    """Generate system-level evaluation summary."""
    total = len(evaluations)
    needs_review = sum(1 for e in evaluations if e["assessment"] == "needs_review")
    likely_correct = sum(1 for e in evaluations if e["assessment"] == "likely_correct")

    # Tier distribution
    tier_dist = {}
    for lead in scored_leads:
        t = lead.get("adjusted_tier") or lead.get("tier", "?")
        tier_dist[t] = tier_dist.get(t, 0) + 1

    # Confidence distribution
    conf_dist = {}
    for lead in scored_leads:
        c = lead.get("ai_confidence", "unknown")
        conf_dist[c] = conf_dist.get(c, 0) + 1

    # Adjudication stats
    adjudicated = sum(1 for l in scored_leads if l.get("adjudication_needed"))

    # Find potential issues
    issues = []

    # Check for tier skew
    tier_a_pct = tier_dist.get("A", 0) / total * 100 if total > 0 else 0
    if tier_a_pct > 40:
        issues.append(f"Tier A over-representation ({tier_a_pct:.0f}%) — scoring may be too generous")
    if tier_a_pct < 10 and total > 10:
        issues.append(f"Tier A under-representation ({tier_a_pct:.0f}%) — scoring may be too strict")

    # Check confidence levels
    low_conf_pct = conf_dist.get("low", 0) / total * 100 if total > 0 else 0
    if low_conf_pct > 30:
        issues.append(f"High proportion of low-confidence assessments ({low_conf_pct:.0f}%)")

    return {
        "timestamp": datetime.now().isoformat(),
        "total_leads": total,
        "likely_correct": likely_correct,
        "needs_review": needs_review,
        "self_assessed_agreement": (
            f"Self-assessed agreement: {likely_correct}/{total} leads. "
            f"No external validation dataset. "
            f"Requires 60-day backtest on closed-won data."
        ) if total > 0 else "N/A",
        "tier_distribution": tier_dist,
        "confidence_distribution": conf_dist,
        "adjudicated_leads": adjudicated,
        "system_issues": issues if issues else ["No systemic issues detected"],
    }


def format_evaluation_report(evaluations: list, system_eval: dict, scored_leads: list) -> str:
    """Generate the full evaluation report as markdown."""
    report = []
    report.append("# Evaluation Report: Lead Intelligence & Prioritization System")
    report.append(f"\n**Generated:** {system_eval['timestamp']}")
    report.append(f"**Total Leads Processed:** {system_eval['total_leads']}")
    report.append("")

    # System-level summary
    report.append("## System Performance Summary")
    report.append("")
    report.append(f"| Metric | Value |")
    report.append(f"|--------|-------|")
    report.append(f"| Leads likely correct | {system_eval['likely_correct']}/{system_eval['total_leads']} (self-assessed agreement) |")
    report.append(f"| Leads needing review | {system_eval['needs_review']} |")
    report.append(f"| Leads adjudicated | {system_eval['adjudicated_leads']} |")
    report.append("")

    # Tier distribution
    report.append("### Tier Distribution")
    report.append("")
    report.append("| Tier | Count | Percentage |")
    report.append("|------|-------|------------|")
    total = system_eval["total_leads"]
    for tier in ["A", "B", "C", "D"]:
        count = system_eval["tier_distribution"].get(tier, 0)
        pct = f"{count/total*100:.0f}%" if total > 0 else "0%"
        report.append(f"| {tier} | {count} | {pct} |")
    report.append("")

    # Confidence distribution
    report.append("### AI Confidence Distribution")
    report.append("")
    report.append("| Confidence | Count |")
    report.append("|------------|-------|")
    for conf in ["high", "medium", "low", "unknown"]:
        count = system_eval["confidence_distribution"].get(conf, 0)
        if count > 0:
            report.append(f"| {conf} | {count} |")
    report.append("")

    # System issues
    report.append("### System Issues & Observations")
    report.append("")
    for issue in system_eval["system_issues"]:
        report.append(f"- {issue}")
    report.append("")

    # Per-lead evaluation
    report.append("## Per-Lead Evaluation")
    report.append("")
    report.append("| Lead ID | Company | Tier | Score | Assessment | AI Confidence | Issues |")
    report.append("|---------|---------|------|-------|------------|---------------|--------|")

    for ev in evaluations:
        issues_str = "; ".join(ev["questionable_signals"][:2])
        report.append(
            f"| {ev['lead_id']} | {ev['company']} | {ev['assigned_tier']} | "
            f"{ev['final_score']} | {ev['assessment']} | {ev['ai_confidence']} | "
            f"{issues_str} |"
        )
    report.append("")

    # Detailed findings for flagged leads
    flagged = [e for e in evaluations if e["assessment"] == "needs_review"]
    if flagged:
        report.append("## Detailed Findings: Leads Needing Review")
        report.append("")
        for ev in flagged:
            report.append(f"### {ev['lead_id']} — {ev['company']}")
            report.append(f"- **Tier:** {ev['assigned_tier']} | **Score:** {ev['final_score']}")
            report.append(f"- **AI Confidence:** {ev['ai_confidence']}")
            report.append(f"- **Correct signals:** {'; '.join(ev['correct_signals'])}")
            report.append(f"- **Issues:** {'; '.join(ev['questionable_signals'])}")
            report.append("")

    # What breaks and what to fix first
    report.append("## Where the System Breaks")
    report.append("")
    report.append("### Known Failure Modes")
    report.append("")
    report.append("1. **Personal email + senior title**: The system correctly flags these as low data confidence, ")
    report.append("   but the deterministic scorer cannot verify whether the claim is real. These leads get ")
    report.append("   appropriately routed to human review, but a production system needs email verification.")
    report.append("")
    report.append("2. **Event badge scans with no digital engagement**: Leads like L019 and L028 have zero time ")
    report.append("   on site because their interaction was physical. The engagement score underweights them. ")
    report.append("   Fix: add an event-source bypass that overrides time-on-site for badge scan leads.")
    report.append("")
    report.append("3. **[FIXED]** Partnership inquiries now route to Partnership Team. partner_inquiry was removed ")
    report.append("   from high_intent_forms (0 intent points), and routing.py overrides routing to ")
    report.append("   Partnership Team / Channel Manager regardless of tier score.")
    report.append("")
    report.append("4. **Junior titles at massive companies**: L020 (PwC Senior Associate) and L030 (GM Analyst) ")
    report.append("   get deprioritized by title, but at 300K+ employee companies, junior champions can drive ")
    report.append("   enterprise deals. Fix: add a company-size override that boosts champion-path leads.")
    report.append("")
    report.append("5. **[FIXED]** Country abbreviations no longer cause silent scoring losses. A COUNTRY_ALIASES dict ")
    report.append("   in config.py maps common abbreviations (US, UK, UAE, etc.) to full names. scoring.py ")
    report.append("   normalizes country before geography lookup. L020 (PwC, country='US') now gets correct ")
    report.append("   tier-1 geography points.")
    report.append("")
    report.append("6. **Geographic bias**: The model penalizes tier-2 geographies (India, Brazil, UAE) even when ")
    report.append("   the lead profile is otherwise enterprise-grade. This reflects a Western-centric bias in ")
    report.append("   the ICP definition that may not match actual revenue potential.")
    report.append("")

    report.append("### What to Fix First")
    report.append("")
    report.append("1. **Email verification integration** — highest-impact data quality improvement")
    report.append("2. **Event-source engagement bypass** — prevents false negatives from offline leads")
    report.append("3. **Partnership routing path** — prevents misrouting of non-buyer leads")
    report.append("")

    # Production metrics
    report.append("## Production Monitoring Metrics")
    report.append("")
    report.append("| Metric | What It Measures | Alert Threshold | Action If Breached |")
    report.append("|--------|-----------------|-----------------|-------------------|")
    report.append("| Tier A → Meeting Rate | Lead quality of top tier | < 30% in any 2-week window | Review scoring weights; audit recent Tier A leads |")
    report.append("| Time-to-First-Touch (Tier A) | SLA adherence | > 60 min average | Escalate to sales ops; check alert delivery |")
    report.append("| False Positive Rate | Leads demoted by AE within 48h | > 20% of Tier A | Tighten ICP criteria; increase confidence threshold |")
    report.append("| False Negative Recovery | Tier C/D leads that close within 90 days | > 5% of closed-won | Audit scoring for those patterns; adjust weights |")
    report.append("| Manual Override Frequency | How often humans overrule AI | > 25% of adjudicated leads | Retrain scoring model; review adjudication prompts |")
    report.append("| Research Failure Rate | Account research completions | > 15% failure | Check API limits; expand source coverage |")
    report.append("| Confidence Drift | % of low-confidence assessments over time | > 30% in any week | Data quality degrading; audit lead sources |")
    report.append("| Score Distribution Entropy | Tier balance over time | > 60% in any single tier | Calibration issue; review scoring thresholds |")
    report.append("")

    return "\n".join(report)
