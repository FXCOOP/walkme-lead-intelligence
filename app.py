"""
FastAPI service for the Lead Intelligence & Prioritization Engine.

Design principle: single source of truth. All scoring, AI reasoning, and
research go through the existing Python modules (scoring.py, main.py,
research.py). This file is a thin HTTP wrapper — no business logic lives here.

Endpoints:
- GET  /           → HTML UI (served from templates/index.html)
- GET  /demo       → Pre-computed canonical result from output/scored_leads.csv
                     (instant, no OpenAI calls, matches approved submission).
- POST /score      → Live pipeline on user-supplied leads. Runs scoring,
                     optional AI reasoning, optional adjudication, optional
                     Tier A research. Reuses main.py helpers.
- GET  /health     → Liveness probe for Render.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# Reuse existing pipeline modules — no duplication.
from config import OPENAI_API_KEY, OUTPUT_DIR, ADJUDICATION_CONFIG
from scoring import score_lead
from routing import route_lead
from evaluator import evaluate_lead, generate_system_evaluation
from main import run_ai_reasoning, run_ai_adjudication, run_account_research

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("app")

ROOT = Path(__file__).parent
CANONICAL_CSV = ROOT / "output" / "scored_leads.csv"
CANONICAL_EVAL = ROOT / "output" / "system_evaluation.json"
RAW_INPUT_CSV = ROOT / "data" / "leads_input.csv"
TEMPLATES_DIR = ROOT / "templates"

app = FastAPI(
    title="Lead Intelligence Engine",
    description="Deterministic lead scoring + bounded AI reasoning. Single source of truth: Python pipeline.",
    version="1.0.0",
)

# CORS: allow the Vercel UI (and any other origin) to consume /demo and /score
# so the existing web-rust-ten-89.vercel.app can be repointed here without a
# second deploy. Restrict methods to what's actually used.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ─── Models ──────────────────────────────────────────────────────────
class LeadInput(BaseModel):
    lead_id: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    company: str = ""
    job_title: str = ""
    company_size: Any = 0
    industry: str = ""
    country: str = ""
    lead_source: str = ""
    pages_visited: str = ""
    time_on_site_seconds: Any = 0
    form_type: str = ""
    webinar_attended: str = ""
    content_asset: str = ""
    demo_requested: str = ""
    technology_stack: str = ""
    notes: str = ""
    inferred_intent_signal: str = ""
    created_at: Optional[str] = None
    last_activity_at: Optional[str] = None

    class Config:
        extra = "allow"


class ScoreRequest(BaseModel):
    leads: list[LeadInput] = Field(..., min_length=1, max_length=50)
    with_ai: bool = False
    with_research: bool = False


# ─── Helpers ─────────────────────────────────────────────────────────
def _coerce(value: str):
    """Convert CSV string cell to JSON-friendly type."""
    if value == "" or value is None:
        return ""
    if value in ("True", "False"):
        return value == "True"
    # try int then float
    try:
        if "." not in value and "e" not in value.lower():
            return int(value)
    except (ValueError, TypeError):
        pass
    try:
        return float(value)
    except (ValueError, TypeError):
        return value


def _load_canonical() -> dict:
    """Load the approved Python submission artifact as the canonical demo payload.
    No re-scoring, no OpenAI calls — this is the locked result.

    Merges two sources:
    - output/scored_leads.csv → scores, tier, AI reasoning, routing, adjudication.
    - data/leads_input.csv    → raw behavioral fields (pages_visited, time_on_site,
                                 form_type, etc.) that the scored CSV omits but the
                                 UI and /score re-run need.
    """
    if not CANONICAL_CSV.exists():
        raise HTTPException(status_code=500, detail=f"Canonical artifact missing: {CANONICAL_CSV}")

    with open(CANONICAL_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Merge raw behavioral fields from the input dataset by lead_id so the demo
    # payload carries the full lead context, not just the scored output columns.
    raw_by_id: dict[str, dict] = {}
    if RAW_INPUT_CSV.exists():
        with open(RAW_INPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                raw_by_id[r.get("lead_id", "")] = r

    merged_rows = []
    for scored in rows:
        lid = scored.get("lead_id", "")
        raw = raw_by_id.get(lid, {})
        # Raw input fields fill in what the scored CSV doesn't carry.
        # Scored fields (tier, final_score, ai_reasoning, etc.) win on conflict.
        combined = {**raw, **scored}
        merged_rows.append(combined)

    typed_rows = [{k: _coerce(v) for k, v in r.items()} for r in merged_rows]

    stats = {}
    if CANONICAL_EVAL.exists():
        with open(CANONICAL_EVAL, encoding="utf-8") as f:
            se = json.load(f)
        td = se.get("tier_distribution", {})
        avg = round(
            sum(float(r.get("final_score", 0) or 0) for r in typed_rows) / max(len(typed_rows), 1),
            1,
        )
        stats = {
            "total": se.get("total_leads", len(typed_rows)),
            "tierA": td.get("A", 0),
            "tierB": td.get("B", 0),
            "tierC": td.get("C", 0),
            "tierD": td.get("D", 0),
            "adjudicated": se.get("adjudicated_leads", 0),
            "likely_correct": se.get("likely_correct", 0),
            "needs_review": se.get("needs_review", 0),
            "avgScore": avg,
            "source": "approved Python submission artifact",
            "generated_at": se.get("timestamp", ""),
        }

    return {"leads": typed_rows, "stats": stats}


def _run_live_pipeline(leads: list[dict], with_ai: bool, with_research: bool) -> dict:
    """Run the exact same pipeline as main.py.run_pipeline but in-process and
    without file I/O. All business logic is imported from scoring/routing/
    evaluator/main — nothing reimplemented here."""
    # Step 1: deterministic scoring
    scored_leads = [score_lead(lead) for lead in leads]

    if with_ai and OPENAI_API_KEY:
        # Step 2: AI reasoning per lead (bounded authority applied inside
        # main.run_ai_reasoning via scoring.can_apply_ai_tier_change).
        scored_leads = [run_ai_reasoning(lead) for lead in scored_leads]

        # Step 3: adjudication for flagged leads
        for i, lead in enumerate(scored_leads):
            if lead.get("adjudication_needed"):
                scored_leads[i] = run_ai_adjudication(lead)

        # Step 4: research for base Tier A leads (deterministic pool, per
        # the stability upgrade — does not depend on adjusted_tier drift).
        if with_research:
            max_research = ADJUDICATION_CONFIG.get("max_research_leads", 10)
            tier_a = [l for l in scored_leads if l["tier"] == "A"][:max_research]
            for lead in tier_a:
                idx = scored_leads.index(lead)
                scored_leads[idx] = run_account_research(lead)
    else:
        for lead in scored_leads:
            lead.setdefault("ai_reasoning", "AI layer skipped")
            lead.setdefault("ai_confidence", "unknown")
            lead.setdefault("adjusted_tier", lead["tier"])
            lead.setdefault("research_summary", "Research skipped")

    # Step 5: routing
    for i, lead in enumerate(scored_leads):
        scored_leads[i].update(route_lead(lead))

    # Step 6: evaluation
    evaluations = [evaluate_lead(l) for l in scored_leads]
    system_eval = generate_system_evaluation(evaluations, scored_leads)

    td = system_eval.get("tier_distribution", {})
    stats = {
        "total": system_eval.get("total_leads", len(scored_leads)),
        "tierA": td.get("A", 0),
        "tierB": td.get("B", 0),
        "tierC": td.get("C", 0),
        "tierD": td.get("D", 0),
        "adjudicated": system_eval.get("adjudicated_leads", 0),
        "likely_correct": system_eval.get("likely_correct", 0),
        "needs_review": system_eval.get("needs_review", 0),
        "avgScore": round(
            sum(float(l.get("final_score", 0) or 0) for l in scored_leads) / max(len(scored_leads), 1),
            1,
        ),
        "source": "live pipeline",
    }
    return {"leads": scored_leads, "stats": stats, "system_evaluation": system_eval}


# ─── Endpoints ───────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "canonical_available": CANONICAL_CSV.exists()}


@app.get("/demo")
def demo():
    """Return the deterministic pipeline result on the sample dataset.

    No OpenAI calls. Runs scoring.py + routing.py + evaluator.py only.
    This is the honest "before AI" view — the reviewer sees the raw
    deterministic tier distribution, then clicks 'Re-run live AI' to
    see the AI-assisted result.
    """
    if not RAW_INPUT_CSV.exists():
        raise HTTPException(status_code=500, detail=f"Raw input missing: {RAW_INPUT_CSV}")
    with open(RAW_INPUT_CSV, newline="", encoding="utf-8") as f:
        leads = list(csv.DictReader(f))
    result = _run_live_pipeline(leads, with_ai=False, with_research=False)
    result["stats"]["source"] = "deterministic pipeline (no AI)"
    return JSONResponse(result)


@app.get("/canonical")
def canonical():
    """Return the locked approved Python submission artifact. Used only for
    reviewer verification against output/scored_leads.csv. Not surfaced in UI."""
    return JSONResponse(_load_canonical())


@app.post("/score")
def score(req: ScoreRequest):
    """Run the live Python pipeline on user-supplied leads. Uses the same
    scoring/adjudication/routing modules as main.py — no parallel logic.

    - with_ai=false  → deterministic scoring + routing only (fast, no OpenAI).
    - with_ai=true   → adds AI reasoning + adjudication on flagged leads.
    - with_research=true + with_ai=true → adds grounded Tier A account research.
    """
    if req.with_ai and not OPENAI_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="with_ai=true but OPENAI_API_KEY is not configured on the server.",
        )

    leads = [l.model_dump() for l in req.leads]
    try:
        result = _run_live_pipeline(leads, with_ai=req.with_ai, with_research=req.with_research)
    except Exception as e:
        logger.exception("Pipeline failed")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    return JSONResponse(result)


@app.get("/", response_class=HTMLResponse)
def index():
    """Minimal HTML UI served directly by FastAPI. Calls /demo and /score via
    client-side fetch. No framework, no build step, no parallel logic."""
    html_path = TEMPLATES_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Lead Intelligence Engine</h1><p>UI template not found.</p>")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
