"""
Deterministic scoring engine for lead prioritization.
Computes four dimension scores, weighted final score, tier assignment,
and flags leads that need AI adjudication.
"""

import math
import re
from datetime import datetime, timezone
from config import (
    SCORING_WEIGHTS, TIER_BOUNDARIES, ICP_CRITERIA,
    INTENT_SIGNALS, ADJUDICATION_CONFIG, COUNTRY_ALIASES,
)


def _reference_now() -> datetime:
    """Return the reference 'now' for recency scoring. Uses REFERENCE_NOW from
    config if set (frozen for reproducibility); otherwise live UTC clock."""
    try:
        from config import REFERENCE_NOW
    except ImportError:
        REFERENCE_NOW = None
    if REFERENCE_NOW:
        try:
            ts = datetime.fromisoformat(str(REFERENCE_NOW).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


def _days_since(timestamp: str, now: datetime | None = None) -> float | None:
    """Return days elapsed since an ISO timestamp. None if unparseable/missing.

    `now` lets callers freeze the reference time for reproducibility; defaults
    to config.REFERENCE_NOW or the live clock."""
    if not timestamp:
        return None
    try:
        ts = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ref = now if now is not None else _reference_now()
        return (ref - ts).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


def recency_bonus(lead: dict) -> tuple[float, str]:
    """Recency bonus based on last_activity_at. Lives inside Intent because
    recency conditions how behavioral signals should be interpreted: a demo
    request from last week is live pipeline, the same signal 30 days stale
    is a re-engagement case. Capped so it can't alone promote a cold lead."""
    days = _days_since(lead.get("last_activity_at", ""))
    if days is None:
        return 0.0, "recency unknown (+0)"
    if days < 2:
        return 15.0, f"recent activity <2d (+15)"
    if days < 7:
        return 10.0, f"recent activity <7d (+10)"
    if days < 30:
        return 5.0, f"recent activity <30d (+5)"
    return 0.0, f"stale activity {int(days)}d (+0)"


def score_icp_fit(lead: dict) -> float:
    """Score 0-100 based on company size, industry, title, geography, email, tech stack.

    Company size uses a sigmoid curve instead of step thresholds to produce a
    continuous score that rewards growth proportionally: near-0 for micro companies,
    ~15 at 500 employees, ~28 at 1500, saturating at 30 for large enterprises.

    Title scoring is context-aware: post-sale signals (success/support) receive a
    penalty, while mid-level titles at very large companies get a champion-path bonus.
    """
    score = 0.0
    breakdown = []

    # Company size (0-30 points) — sigmoid curve for continuous scoring.
    # Formula: 30 / (1 + exp(-0.005 * (size - 500)))
    # This replaces the naive step function (>=1000 -> 30, >=200 -> 20, etc.)
    # with a smooth curve. The inflection point at 500 employees means mid-market
    # companies score ~15, while the curve saturates near 30 for enterprises.
    try:
        size = int(lead.get("company_size", 0))
    except (ValueError, TypeError):
        size = 0

    if size <= 0:
        size_score = 0.0
        breakdown.append(f"unknown/zero company size (+0.0)")
    else:
        size_score = round(30 / (1 + math.exp(-0.005 * (size - 500))), 1)
        breakdown.append(f"company size {size} — sigmoid (+{size_score})")
    score += size_score

    # Industry match (0-20 points)
    industry = lead.get("industry", "")
    if industry in ICP_CRITERIA["target_industries"]:
        score += 20
        breakdown.append(f"target industry: {industry} (+20)")
    else:
        breakdown.append(f"non-target industry: {industry} (+0)")

    # Title seniority (0-25 points) with context-aware modifiers.
    title = lead.get("job_title", "").lower()
    negative_match = any(neg in title for neg in ICP_CRITERIA["negative_titles"])
    positive_match = any(pos in title for pos in ICP_CRITERIA["target_titles_keywords"])

    if negative_match:
        score += 0
        breakdown.append(f"negative title signal: {lead.get('job_title')} (+0)")
    elif positive_match:
        score += 25
        breakdown.append(f"senior title match: {lead.get('job_title')} (+25)")
    else:
        score += 10
        breakdown.append(f"mid-level title: {lead.get('job_title')} (+10)")

    # Context-aware title modifiers (applied after base title score).
    # Post-sale signals: "success" or "support" in title suggests non-buyer role.
    post_sale_keywords = ["success", "support"]
    if any(kw in title for kw in post_sale_keywords):
        score -= 5
        breakdown.append(f"post-sale title signal ({lead.get('job_title')}) (-5)")

    # Large-company champion path: mid-level titles at 50k+ companies often
    # drive internal adoption and can be strong champions.
    is_mid_level = not negative_match and not positive_match
    if size > 50000 and is_mid_level:
        score += 5
        breakdown.append(f"large-company champion path (size {size}, mid-level) (+5)")

    # Geography (0–10 points) — normalize country aliases first
    country = lead.get("country", "").strip()
    country = COUNTRY_ALIASES.get(country, COUNTRY_ALIASES.get(country.lower(), country)) if country else ""
    if country in ICP_CRITERIA["target_countries_tier1"]:
        score += 10
        breakdown.append(f"tier-1 geography: {country} (+10)")
    elif country in ICP_CRITERIA["target_countries_tier2"]:
        score += 6
        breakdown.append(f"tier-2 geography: {country} (+6)")
    else:
        score += 2
        breakdown.append(f"other geography: {country} (+2)")

    # Corporate email (0–5 points)
    email = lead.get("email", "")
    domain = email.split("@")[-1] if "@" in email else ""
    if domain in ICP_CRITERIA["corporate_email_domains_negative"]:
        score += 0
        breakdown.append(f"personal email domain: {domain} (+0)")
    else:
        score += 5
        breakdown.append(f"corporate email: {domain} (+5)")

    # Tech stack alignment (0–10 points)
    tech = lead.get("technology_stack", "")
    matches = [t for t in ICP_CRITERIA["high_value_tech_stack"] if t.lower() in tech.lower()]
    if len(matches) >= 2:
        score += 10
        breakdown.append(f"strong tech overlap: {', '.join(matches)} (+10)")
    elif len(matches) == 1:
        score += 5
        breakdown.append(f"partial tech overlap: {', '.join(matches)} (+5)")
    else:
        breakdown.append("no tech stack overlap (+0)")

    return min(score, 100), breakdown


def score_intent(lead: dict) -> float:
    """Score 0-100 based on pages visited, form type, demo request, webinar, content.

    High-intent page scoring uses diminishing returns: 1st page = 10pts,
    2nd = 8pts, 3rd = 6pts, 4th+ = 4pts each. This prevents inflated scores
    from page-count alone and better distinguishes leads who visited
    pricing+demo+submitted a form from those who just browsed many pages.
    """
    score = 0.0
    breakdown = []

    # Pages visited analysis (0-35 points) — diminishing returns for high-intent pages.
    pages = [p.strip() for p in lead.get("pages_visited", "").split(";") if p.strip()]
    high_pages = [p for p in pages if p in INTENT_SIGNALS["high_intent_pages"]]
    med_pages = [p for p in pages if p in INTENT_SIGNALS["medium_intent_pages"]]

    # Diminishing returns schedule for high-intent pages:
    # 1st = 10, 2nd = 8, 3rd = 6, 4th+ = 4 each.
    high_page_schedule = [10, 8, 6]  # first three; rest get 4
    high_page_total = 0
    for i in range(len(high_pages)):
        high_page_total += high_page_schedule[i] if i < len(high_page_schedule) else 4

    page_score = min(high_page_total + len(med_pages) * 4, 35)
    score += page_score
    if high_pages:
        breakdown.append(f"high-intent pages: {', '.join(high_pages)} (+{high_page_total} diminishing)")
    if med_pages:
        breakdown.append(f"medium-intent pages: {', '.join(med_pages)} (+{len(med_pages)*4})")

    # Form type (0–25 points)
    form = lead.get("form_type", "none").strip()
    if form in INTENT_SIGNALS.get("partnership_forms", []):
        score += 0
        breakdown.append(f"partnership form — not buyer intent: {form} (+0)")
    elif form in INTENT_SIGNALS["high_intent_forms"]:
        score += 25
        breakdown.append(f"high-intent form: {form} (+25)")
    elif form in INTENT_SIGNALS["medium_intent_forms"]:
        score += 12
        breakdown.append(f"medium-intent form: {form} (+12)")
    else:
        breakdown.append(f"low/no intent form: {form} (+0)")

    # Demo requested (0–15 points)
    if lead.get("demo_requested", "").lower() == "yes":
        score += 15
        breakdown.append("demo requested (+15)")

    # Webinar attended (0–10 points)
    if lead.get("webinar_attended", "").lower() == "yes":
        score += 10
        breakdown.append("webinar attended (+10)")

    # Time on site (0–15 points)
    try:
        time_on_site = int(lead.get("time_on_site_seconds", 0))
    except (ValueError, TypeError):
        time_on_site = 0

    thresholds = INTENT_SIGNALS["time_on_site_thresholds"]
    if time_on_site >= thresholds["high"]:
        score += 15
        breakdown.append(f"high time on site: {time_on_site}s (+15)")
    elif time_on_site >= thresholds["medium"]:
        score += 8
        breakdown.append(f"medium time on site: {time_on_site}s (+8)")
    elif time_on_site >= thresholds["low"]:
        score += 3
        breakdown.append(f"low time on site: {time_on_site}s (+3)")
    else:
        breakdown.append(f"minimal time on site: {time_on_site}s (+0)")

    # Recency bonus — conditions interpretation of all prior intent signals.
    rec_bonus, rec_label = recency_bonus(lead)
    if rec_bonus:
        score += rec_bonus
        breakdown.append(rec_label)

    return min(score, 100), breakdown


def score_engagement(lead: dict) -> float:
    """Score 0-100 based on multi-touch signals and interaction depth.

    Combines page diversity, lead source quality, content depth, engagement
    note signals, and recency proxy via form submission into a composite
    engagement score. Each sub-dimension is capped independently.
    """
    score = 0.0
    breakdown = []

    # Number of distinct page categories visited (0–30 points)
    pages = [p.strip() for p in lead.get("pages_visited", "").split(";") if p.strip()]
    page_diversity = min(len(pages) * 8, 30)
    score += page_diversity
    breakdown.append(f"page diversity: {len(pages)} categories (+{page_diversity})")

    # Lead source quality (0–20 points)
    source = lead.get("lead_source", "").lower()
    source_scores = {
        "referral": 20, "event scan": 15, "paid search": 12,
        "paid linkedin": 12, "webinar": 10, "content download": 5,
        "organic search": 5, "product hunt": 5,
    }
    source_score = source_scores.get(source, 3)
    score += source_score
    breakdown.append(f"lead source: {lead.get('lead_source')} (+{source_score})")

    # Content depth (0–20 points)
    content_asset = lead.get("content_asset", "")
    if content_asset and content_asset.lower() != "none":
        score += 10
        breakdown.append(f"downloaded content: {content_asset} (+10)")

    if lead.get("webinar_attended", "").lower() == "yes":
        score += 10
        breakdown.append("webinar engagement (+10)")

    # Notes signal strength (0–15 points) — presence of strong engagement notes
    notes = (lead.get("notes") or "").lower()
    strong_note_signals = ["asked", "engaged", "referred", "multiple", "urgent", "3 times"]
    note_matches = [s for s in strong_note_signals if s in notes]
    if note_matches:
        note_score = min(len(note_matches) * 8, 15)
        score += note_score
        breakdown.append(f"strong engagement notes (+{note_score})")

    # Recency proxy via form submission (0–15 points)
    form = lead.get("form_type", "none")
    if form in INTENT_SIGNALS.get("partnership_forms", []):
        score += 7
        breakdown.append("partnership form submission (+7)")
    elif form in INTENT_SIGNALS["high_intent_forms"]:
        score += 15
        breakdown.append("high-intent form submission (+15)")
    elif form in INTENT_SIGNALS["medium_intent_forms"]:
        score += 7
        breakdown.append("medium-intent form submission (+7)")

    return min(score, 100), breakdown


def score_data_confidence(lead: dict, *, icp_fit: float = None, intent: float = None) -> float:
    """Score 0-100 based on completeness, verifiability, and consistency of lead data.

    Evaluates field completeness, corporate email verification, company size
    availability, tech stack presence, and data red flags. Also performs a
    signal contradiction check: if ICP fit is high (>70) but intent is low (<20),
    the lead may be a data import rather than organic -- confidence is reduced by 10.
    """
    score = 0.0
    breakdown = []

    # Key field completeness (0–40 points)
    required_fields = ["email", "company", "job_title", "company_size", "industry", "country"]
    filled = sum(1 for f in required_fields if lead.get(f) and str(lead[f]).strip()
                 and str(lead[f]).strip() not in ("0", "Unknown", "none", ""))
    completeness = int((filled / len(required_fields)) * 40)
    score += completeness
    breakdown.append(f"field completeness: {filled}/{len(required_fields)} (+{completeness})")

    # Corporate email verification (0–20 points)
    email = lead.get("email", "")
    domain = email.split("@")[-1] if "@" in email else ""
    if domain and domain not in ICP_CRITERIA["corporate_email_domains_negative"]:
        score += 20
        breakdown.append(f"verified corporate domain: {domain} (+20)")
    elif domain:
        score += 5
        breakdown.append(f"personal email domain: {domain} (+5)")
    else:
        breakdown.append("no email (+0)")

    # Company size is a real number, not 0 (0–15 points)
    try:
        size = int(lead.get("company_size", 0))
        if size > 0:
            score += 15
            breakdown.append(f"company size known: {size} (+15)")
        else:
            breakdown.append("company size unknown (+0)")
    except (ValueError, TypeError):
        breakdown.append("company size unparseable (+0)")

    # Tech stack provided (0–10 points)
    tech = lead.get("technology_stack", "")
    if tech and tech.strip():
        score += 10
        breakdown.append("tech stack provided (+10)")
    else:
        breakdown.append("no tech stack info (+0)")

    # Notes consistency check (0–15 points)
    notes = lead.get("notes", "")
    title = lead.get("job_title", "")
    email_domain = domain

    # Check for red flags
    red_flags = []
    if any(neg in email_domain for neg in ["gmail", "yahoo", "hotmail", "outlook"]):
        if any(kw in title.lower() for kw in ["vp", "director", "chief", "svp", "head"]):
            red_flags.append("senior title with personal email")
    if lead.get("company", "").lower() in ["unknown", "", "freelance"]:
        if title and "student" not in title.lower():
            red_flags.append("title without verifiable company")

    if not red_flags:
        score += 15
        breakdown.append("no data red flags (+15)")
    else:
        score += 0
        breakdown.append(f"red flags detected: {'; '.join(red_flags)} (+0)")

    # Signal contradiction check: strong ICP profile with no engagement suggests
    # a data import (e.g., list purchase, CRM sync) rather than an organic lead.
    if icp_fit is not None and intent is not None:
        if icp_fit > 70 and intent < 20:
            score -= 10
            breakdown.append(
                "signal contradiction: strong profile with no engagement "
                "— possible data import, not organic lead (-10)"
            )

    return min(max(score, 0), 100), breakdown


def compute_final_score(dimension_scores: dict) -> float:
    """Compute weighted final score from dimension scores."""
    final = sum(
        dimension_scores[dim] * SCORING_WEIGHTS[dim]
        for dim in SCORING_WEIGHTS
    )
    return round(final, 1)


def assign_tier(final_score: float) -> str:
    """Assign tier letter based on final score."""
    for tier, (low, high) in TIER_BOUNDARIES.items():
        if low <= final_score <= high:
            return tier
    return "D"


def check_adjudication_needed(dimension_scores: dict, final_score: float, data_confidence: float) -> dict:
    """Determine if a lead needs AI adjudication due to conflicting signals or uncertainty."""
    reasons = []
    cfg = ADJUDICATION_CONFIG

    # Gray zone score
    low, high = cfg["score_gray_zone"]
    if low <= final_score <= high:
        reasons.append(f"Score {final_score} falls in gray zone ({low}–{high})")

    # Low data confidence
    if data_confidence < cfg["confidence_threshold"] * 100:
        reasons.append(f"Low data confidence: {data_confidence}")

    # Conflicting signals
    scores = list(dimension_scores.values())
    delta = max(scores) - min(scores)
    if delta > cfg["conflicting_signal_delta"]:
        reasons.append(f"Signal conflict: max-min delta = {delta}")

    return {
        "adjudication_needed": len(reasons) > 0,
        "adjudication_reasons": "; ".join(reasons) if reasons else "None",
    }


_TIER_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def _tier_boundary_distance(score: float) -> float:
    """Minimum distance in points from `score` to any tier boundary."""
    boundaries = []
    for _, (low, high) in TIER_BOUNDARIES.items():
        boundaries.extend([low, high])
    return min(abs(score - b) for b in boundaries)


def can_apply_ai_tier_change(
    base_tier: str,
    ai_suggested_tier: str,
    final_score: float,
    dimension_scores: dict,
    ai_confidence: str,
) -> tuple[bool, str]:
    """Decide whether AI is permitted to overwrite the deterministic tier.

    Deterministic scoring is the system of record. AI may move tier only when:
      1. The lead is within the gray zone (±N points of a tier boundary),
         meaning the deterministic decision was itself close to flipping.
      2. AI self-confidence is "high" (low/medium recommendations are advisory).
      3. The move is at most one tier level (no A↔C, no B↔D).
      4. Hard business guardrails are not violated by the proposed tier.

    Returns (allowed, reason). `reason` is a short audit string either way.
    """
    from config import AI_AUTHORITY

    if not ai_suggested_tier or ai_suggested_tier == base_tier:
        return False, "no change proposed"

    if ai_suggested_tier not in _TIER_ORDER:
        return False, f"invalid suggested tier '{ai_suggested_tier}'"

    # Rule 1: gray zone
    gz = AI_AUTHORITY["gray_zone_points"]
    dist = _tier_boundary_distance(final_score)
    if dist > gz:
        return False, f"score {final_score} is {dist:.1f}pt from any boundary (>{gz}); deterministic decision not borderline"

    # Rule 2: confidence
    required = AI_AUTHORITY["require_confidence"]
    if (ai_confidence or "").lower() != required:
        return False, f"ai_confidence='{ai_confidence}' != required '{required}'"

    # Rule 3: one-tier move only
    jump = abs(_TIER_ORDER[ai_suggested_tier] - _TIER_ORDER[base_tier])
    if jump > AI_AUTHORITY["max_tier_jump"]:
        return False, f"multi-tier jump ({base_tier}→{ai_suggested_tier}) blocked"

    # Rule 4: hard guardrails on the proposed tier
    g = AI_AUTHORITY["guardrails"]
    if ai_suggested_tier == "A":
        icp = dimension_scores.get("icp_fit", 0)
        intent = dimension_scores.get("intent", 0)
        conf = dimension_scores.get("data_confidence", 0)
        if icp < g["min_icp_for_tier_a"]:
            return False, f"guardrail: ICP {icp} < {g['min_icp_for_tier_a']} for Tier A"
        if intent < g["min_intent_for_tier_a"]:
            return False, f"guardrail: Intent {intent} < {g['min_intent_for_tier_a']} for Tier A"
        # promotion-to-A confidence check (only blocks promotion, not demotion to A from... n/a)
        if _TIER_ORDER[base_tier] > _TIER_ORDER["A"] and conf < g["min_confidence_for_tier_a"]:
            return False, f"guardrail: Data Confidence {conf} < {g['min_confidence_for_tier_a']} for promotion to Tier A"

    return True, f"applied within gray zone (dist={dist:.1f}pt, conf=high, 1-tier move)"


def score_lead(lead: dict) -> dict:
    """Full scoring pipeline for a single lead. Returns enriched lead dict."""
    icp_score, icp_breakdown = score_icp_fit(lead)
    intent_score, intent_breakdown = score_intent(lead)
    engagement_score, engagement_breakdown = score_engagement(lead)
    confidence_score, confidence_breakdown = score_data_confidence(
        lead, icp_fit=icp_score, intent=intent_score
    )

    dimension_scores = {
        "icp_fit": icp_score,
        "intent": intent_score,
        "engagement": engagement_score,
        "data_confidence": confidence_score,
    }

    final_score = compute_final_score(dimension_scores)
    tier = assign_tier(final_score)
    adjudication = check_adjudication_needed(dimension_scores, final_score, confidence_score)

    return {
        **lead,
        "icp_fit_score": icp_score,
        "intent_score": intent_score,
        "engagement_score": engagement_score,
        "data_confidence_score": confidence_score,
        "final_score": final_score,
        "tier": tier,
        "adjudication_needed": adjudication["adjudication_needed"],
        "adjudication_reasons": adjudication["adjudication_reasons"],
        "icp_breakdown": " | ".join(icp_breakdown),
        "intent_breakdown": " | ".join(intent_breakdown),
        "engagement_breakdown": " | ".join(engagement_breakdown),
        "confidence_breakdown": " | ".join(confidence_breakdown),
    }
