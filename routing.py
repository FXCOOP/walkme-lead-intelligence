"""
Routing module — maps scored and adjudicated leads to owners, actions, and SLAs.
"""

from config import ROUTING_RULES, INTENT_SIGNALS


def route_lead(scored_lead: dict) -> dict:
    """
    Assign routing owner, actions, and SLA based on tier.
    Partnership leads are routed to a separate pipeline regardless of tier.
    """
    form = scored_lead.get("form_type", "").strip()
    is_partnership = form in INTENT_SIGNALS.get("partnership_forms", [])

    if is_partnership:
        rule = ROUTING_RULES.get("PARTNER", ROUTING_RULES["C"])
        tier = scored_lead.get("adjusted_tier") or scored_lead.get("tier", "D")
    else:
        tier = scored_lead.get("adjusted_tier") or scored_lead.get("tier", "D")
        rule = ROUTING_RULES.get(tier, ROUTING_RULES["D"])

    routing = {
        "routing_owner": rule["owner"],
        "routing_sla_minutes": rule["sla_minutes"],
        "routing_actions": "; ".join(rule["actions"]),
        "human_review_needed": _needs_human_review(scored_lead, rule),
        "is_partnership": is_partnership,
    }

    routing["recommended_action_summary"] = _build_action_summary(
        scored_lead, tier, rule, is_partnership
    )

    return routing


def _needs_human_review(lead: dict, rule: dict) -> bool:
    """Determine if human review is required based on adjudication and confidence."""
    if lead.get("adjudication_needed"):
        return True
    if lead.get("ai_confidence") == "low":
        return True
    if lead.get("tier") in ("A", "B") and lead.get("data_confidence_score", 100) < 60:
        return True
    return False


def _build_action_summary(lead: dict, tier: str, rule: dict, is_partnership: bool = False) -> str:
    """Build a concise, actionable summary string."""
    company = lead.get("company", "Unknown")
    name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    title = lead.get("job_title", "Unknown")

    if is_partnership:
        return (
            f"PARTNERSHIP: {name} ({title} at {company}) — "
            f"Route to {rule['owner']}. "
            f"Actions: Partnership qualification + channel manager notification."
        )
    elif tier == "A":
        return (
            f"HIGH PRIORITY: {name} ({title} at {company}) — "
            f"Route to {rule['owner']}. "
            f"SLA: {rule['sla_minutes']} min. "
            f"Actions: Account brief + personalized outreach."
        )
    elif tier == "B":
        return (
            f"PRIORITY: {name} ({title} at {company}) — "
            f"Route to {rule['owner']}. "
            f"SLA: {rule['sla_minutes']} min. "
            f"Actions: Sequence enrollment + AI email draft."
        )
    elif tier == "C":
        return (
            f"NURTURE: {name} ({title} at {company}) — "
            f"Route to {rule['owner']}. "
            f"Actions: Nurture sequence + content recommendation."
        )
    else:
        return (
            f"LOW PRIORITY: {name} ({title} at {company}) — "
            f"Archive. Optional retargeting."
        )
