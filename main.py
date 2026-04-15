"""
Lead Intelligence & Prioritization System — Main Pipeline Orchestrator.

Ingests leads → scores → reasons with AI → adjudicates conflicts →
researches top-tier accounts → routes → evaluates → outputs results.

Usage:
    python main.py                      # Auto-detect source (Sheets → CSV fallback)
    python main.py --source csv         # Force local CSV
    python main.py --source sheets      # Force Google Sheets
    python main.py --skip-ai            # Run deterministic scoring only (no API calls)
    python main.py --skip-research      # Score + reason but skip account research
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from config import OUTPUT_DIR, OPENAI_API_KEY, ADJUDICATION_CONFIG, LLM_INFERENCE
from scoring import score_lead, can_apply_ai_tier_change
from routing import route_lead
from sheets_io import read_leads, write_results_to_csv
from evaluator import evaluate_lead, generate_system_evaluation, format_evaluation_report

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pipeline")


def run_ai_reasoning(scored_lead: dict) -> dict:
    """Run OpenAI reasoning on a scored lead. Returns enriched lead."""
    from openai import OpenAI
    from prompts import build_lead_reasoning_prompt
    from config import OPENAI_MODEL

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = build_lead_reasoning_prompt(scored_lead, scored_lead)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=LLM_INFERENCE["temperature"],
            seed=LLM_INFERENCE["seed"],
        )

        # Log system_fingerprint for backend-routing traceability (best-effort
        # reproducibility: seed is honored only when fingerprint is stable).
        fp = getattr(response, "system_fingerprint", None)
        if fp:
            scored_lead["ai_system_fingerprint"] = fp

        result = json.loads(response.choices[0].message.content)

        scored_lead["ai_reasoning"] = result.get("reasoning", "")
        scored_lead["ai_confidence"] = result.get("confidence", "unknown")
        scored_lead["ai_tier_assessment"] = result.get("tier_assessment", "")
        scored_lead["ai_suggested_tier"] = result.get("suggested_tier", "")
        scored_lead["ai_key_strengths"] = "; ".join(result.get("key_strengths", []))
        scored_lead["ai_key_risks"] = "; ".join(result.get("key_risks", []))
        scored_lead["ai_recommended_action"] = result.get("recommended_action", "")
        missing = result.get("missing_data_needed", result.get("missing_data_impact", ""))
        if isinstance(missing, list):
            scored_lead["ai_missing_data_needed"] = json.dumps(missing)
            scored_lead["ai_missing_data_impact"] = "; ".join(
                f"{m.get('field','?')} ({m.get('impact','?')}, would_change_tier={m.get('would_change_tier', False)})"
                for m in missing if isinstance(m, dict)
            )
        else:
            scored_lead["ai_missing_data_needed"] = json.dumps([])
            scored_lead["ai_missing_data_impact"] = str(missing)

        # Bounded AI authority: AI suggestion is preserved for audit; tier
        # change is applied only if confidence, gray-zone, and guardrail
        # constraints all pass. Otherwise adjusted_tier stays at base tier
        # and any AI disagreement flags human_review_needed.
        base_tier = scored_lead["tier"]
        suggested = result.get("suggested_tier", "") or base_tier
        dims = {
            "icp_fit": scored_lead.get("icp_fit_score", 0),
            "intent": scored_lead.get("intent_score", 0),
            "engagement": scored_lead.get("engagement_score", 0),
            "data_confidence": scored_lead.get("data_confidence_score", 0),
        }
        allowed, reason = can_apply_ai_tier_change(
            base_tier, suggested, scored_lead.get("final_score", 0),
            dims, scored_lead.get("ai_confidence", ""),
        )
        scored_lead["ai_tier_change_applied"] = allowed
        scored_lead["ai_tier_change_reason"] = reason
        if allowed:
            scored_lead["adjusted_tier"] = suggested
        else:
            scored_lead["adjusted_tier"] = base_tier
            if suggested and suggested != base_tier:
                scored_lead["human_review_needed"] = True

    except Exception as e:
        logger.error(f"AI reasoning failed for {scored_lead.get('lead_id')}: {e}")
        scored_lead["ai_reasoning"] = f"AI reasoning unavailable: {str(e)[:100]}"
        scored_lead["ai_confidence"] = "unknown"
        scored_lead["adjusted_tier"] = scored_lead["tier"]

    return scored_lead


def run_ai_adjudication(scored_lead: dict) -> dict:
    """Run AI adjudication for leads with conflicting signals."""
    from openai import OpenAI
    from prompts import build_adjudication_prompt
    from config import OPENAI_MODEL

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = build_adjudication_prompt(
        scored_lead, scored_lead,
        scored_lead.get("adjudication_reasons", ""),
    )

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=LLM_INFERENCE["temperature"],
            seed=LLM_INFERENCE["seed"],
        )

        fp = getattr(response, "system_fingerprint", None)
        if fp:
            scored_lead["adjudication_system_fingerprint"] = fp

        result = json.loads(response.choices[0].message.content)

        scored_lead["adjudication_decision"] = result.get("decision", "keep")
        scored_lead["adjudication_analysis"] = result.get("conflict_analysis", "")
        scored_lead["adjudication_confidence"] = result.get("confidence", "unknown")

        # Bounded authority also applies to adjudication: promote/downgrade is
        # subject to the same gray-zone, confidence, and guardrail constraints.
        # Escalation to human is always honored (no tier change, flag raised).
        base_tier = scored_lead["tier"]
        decision = result.get("decision", "keep")
        proposed = result.get("adjusted_tier", base_tier)

        if decision == "escalate_to_human":
            scored_lead["human_review_needed"] = True
        elif decision in ("promote", "downgrade"):
            dims = {
                "icp_fit": scored_lead.get("icp_fit_score", 0),
                "intent": scored_lead.get("intent_score", 0),
                "engagement": scored_lead.get("engagement_score", 0),
                "data_confidence": scored_lead.get("data_confidence_score", 0),
            }
            allowed, reason = can_apply_ai_tier_change(
                base_tier, proposed, scored_lead.get("final_score", 0),
                dims, result.get("confidence", ""),
            )
            scored_lead["adjudication_change_applied"] = allowed
            scored_lead["adjudication_change_reason"] = reason
            if allowed:
                scored_lead["adjusted_tier"] = proposed
            else:
                # Keep deterministic tier; log disagreement for audit.
                scored_lead["human_review_needed"] = True

    except Exception as e:
        logger.error(f"Adjudication failed for {scored_lead.get('lead_id')}: {e}")
        scored_lead["adjudication_decision"] = "error"

    return scored_lead


def run_account_research(scored_lead: dict) -> dict:
    """Run grounded account research for top-tier leads."""
    from research import research_account, format_research_summary

    research = research_account(scored_lead)
    scored_lead["research_summary"] = format_research_summary(research)
    scored_lead["research_confidence"] = research.get("research_confidence", "unknown")
    scored_lead["research_raw"] = json.dumps(research)

    return scored_lead


def run_pipeline(source: str = "auto", skip_ai: bool = False, skip_research: bool = False):
    """Execute the full lead intelligence pipeline."""

    logger.info("=" * 60)
    logger.info("LEAD INTELLIGENCE & PRIORITIZATION SYSTEM")
    logger.info("=" * 60)

    # Step 1: Ingest leads
    logger.info("Step 1: Ingesting leads...")
    leads = read_leads(source=source)
    logger.info(f"Loaded {len(leads)} leads")

    if not leads:
        logger.error("No leads found. Exiting.")
        return

    # Step 2: Deterministic scoring
    logger.info("Step 2: Running deterministic scoring...")
    scored_leads = []
    for lead in leads:
        scored = score_lead(lead)
        scored_leads.append(scored)
        tier = scored["tier"]
        score = scored["final_score"]
        adj = "⚠️ ADJUDICATION" if scored["adjudication_needed"] else ""
        logger.info(f"  {scored['lead_id']}: {scored['company']:30s} → Tier {tier} ({score}) {adj}")

    # Step 3: AI reasoning (if enabled)
    if not skip_ai and OPENAI_API_KEY:
        logger.info("Step 3: Running AI reasoning layer...")
        for i, lead in enumerate(scored_leads):
            logger.info(f"  [{i+1}/{len(scored_leads)}] Reasoning: {lead['lead_id']} ({lead['company']})")
            scored_leads[i] = run_ai_reasoning(lead)
            time.sleep(1)

        # Step 4: AI adjudication for flagged leads
        logger.info("Step 4: Running AI adjudication for flagged leads...")
        adjudicated_count = 0
        for i, lead in enumerate(scored_leads):
            if lead.get("adjudication_needed"):
                logger.info(f"  Adjudicating: {lead['lead_id']} ({lead['company']})")
                scored_leads[i] = run_ai_adjudication(lead)
                adjudicated_count += 1
                time.sleep(1)
        logger.info(f"  Adjudicated {adjudicated_count} leads")

        # Step 5: Account research for top-tier leads
        if not skip_research:
            logger.info("Step 5: Running account research for top-tier leads...")
            # Research pool uses the deterministic base tier, not adjusted_tier.
            # This decouples the research set from AI drift so the same accounts
            # get researched across repeated runs on identical input.
            tier_a_leads = [l for l in scored_leads if l["tier"] == "A"]
            max_research = ADJUDICATION_CONFIG["max_research_leads"]
            research_targets = tier_a_leads[:max_research]

            for i, lead in enumerate(research_targets):
                idx = scored_leads.index(lead)
                logger.info(f"  [{i+1}/{len(research_targets)}] Researching: {lead['company']}")
                scored_leads[idx] = run_account_research(lead)
                time.sleep(2)
        else:
            logger.info("Step 5: Skipping account research (--skip-research)")
    else:
        if skip_ai:
            logger.info("Steps 3-5: Skipping AI layer (--skip-ai)")
        else:
            logger.warning("Steps 3-5: Skipping AI layer (OPENAI_API_KEY not set)")

        # Set defaults for AI fields
        for lead in scored_leads:
            lead["ai_reasoning"] = "AI layer skipped"
            lead["ai_confidence"] = "unknown"
            lead["adjusted_tier"] = lead["tier"]
            lead["research_summary"] = "Research skipped"

    # Step 6: Route leads
    logger.info("Step 6: Applying routing logic...")
    for i, lead in enumerate(scored_leads):
        routing = route_lead(lead)
        scored_leads[i].update(routing)

    # Step 7: Evaluate
    logger.info("Step 7: Running evaluation...")
    evaluations = [evaluate_lead(lead) for lead in scored_leads]
    system_eval = generate_system_evaluation(evaluations, scored_leads)

    # Step 8: Output results
    logger.info("Step 8: Writing output files...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Write scored leads CSV
    csv_path = write_results_to_csv(scored_leads)
    logger.info(f"  → {csv_path}")

    # Write evaluation report
    eval_report = format_evaluation_report(evaluations, system_eval, scored_leads)
    eval_path = os.path.join(OUTPUT_DIR, "evaluation_report.md")
    with open(eval_path, "w", encoding="utf-8") as f:
        f.write(eval_report)
    logger.info(f"  → {eval_path}")

    # Write system evaluation JSON (machine-readable)
    eval_json_path = os.path.join(OUTPUT_DIR, "system_evaluation.json")
    with open(eval_json_path, "w", encoding="utf-8") as f:
        json.dump(system_eval, f, indent=2)
    logger.info(f"  → {eval_json_path}")

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Leads processed:    {len(scored_leads)}")
    logger.info(f"Tier A:             {system_eval['tier_distribution'].get('A', 0)}")
    logger.info(f"Tier B:             {system_eval['tier_distribution'].get('B', 0)}")
    logger.info(f"Tier C:             {system_eval['tier_distribution'].get('C', 0)}")
    logger.info(f"Tier D:             {system_eval['tier_distribution'].get('D', 0)}")
    logger.info(f"Adjudicated:        {system_eval['adjudicated_leads']}")
    logger.info(f"Likely correct:     {system_eval['likely_correct']}/{system_eval['total_leads']} (self-assessed agreement)")
    logger.info(f"Needs review:       {system_eval['needs_review']}")
    logger.info(f"Output directory:   {OUTPUT_DIR}/")
    logger.info("=" * 60)

    return scored_leads, evaluations, system_eval


def main():
    parser = argparse.ArgumentParser(
        description="Lead Intelligence & Prioritization System"
    )
    parser.add_argument(
        "--source", choices=["auto", "csv", "sheets"], default="auto",
        help="Lead data source (default: auto-detect)"
    )
    parser.add_argument(
        "--skip-ai", action="store_true",
        help="Run deterministic scoring only, skip OpenAI calls"
    )
    parser.add_argument(
        "--skip-research", action="store_true",
        help="Skip account research for top-tier leads"
    )

    args = parser.parse_args()
    run_pipeline(source=args.source, skip_ai=args.skip_ai, skip_research=args.skip_research)


if __name__ == "__main__":
    main()
