"""
Configuration for the Lead Intelligence & Prioritization System.
Central place for scoring weights, tier boundaries, routing rules, and API settings.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Configuration ───────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_RESEARCH_MODEL = os.getenv("OPENAI_RESEARCH_MODEL", "gpt-4o-mini")

# ─── Google Sheets Configuration ─────────────────────────────────────
GOOGLE_SHEETS_CREDENTIALS_FILE = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "credentials.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
INPUT_SHEET_NAME = os.getenv("INPUT_SHEET_NAME", "Leads")
OUTPUT_SHEET_NAME = os.getenv("OUTPUT_SHEET_NAME", "Scored Results")

# ─── Scoring Weights ─────────────────────────────────────────────────
SCORING_WEIGHTS = {
    "icp_fit": 0.40,
    "intent": 0.35,
    "engagement": 0.15,
    "data_confidence": 0.10,
}

# ─── Tier Boundaries ─────────────────────────────────────────────────
# Tier A floor raised from 80 to 83 to calibrate against observed 43% Tier A
# concentration in the sample run. Shifts marginal Tier A leads (80-82 range)
# down to B for SDR qualification rather than immediate AE touch.
TIER_BOUNDARIES = {
    "A": (83, 100),
    "B": (60, 82),
    "C": (40, 59),
    "D": (0, 39),
}

# ─── ICP Definition ──────────────────────────────────────────────────
ICP_CRITERIA = {
    "target_company_sizes": {
        "enterprise": (1000, float("inf")),     # strong fit
        "mid_market": (200, 999),                # moderate fit
        "smb": (50, 199),                        # weak fit
        "micro": (0, 49),                        # poor fit
    },
    "target_industries": [
        "Enterprise Software", "Financial Services", "Banking",
        "Professional Services", "IT Consulting", "Technology",
        "Pharmaceuticals", "Healthcare", "Manufacturing",
        "Automotive", "Aerospace", "Energy", "Consumer Goods",
        "E-Commerce", "Transportation",
    ],
    "target_titles_keywords": [
        "vp", "vice president", "director", "svp", "senior vice president",
        "chief", "cdo", "cto", "cio", "coo", "head of", "programme director",
        "practice lead", "global",
    ],
    "negative_titles": [
        "student", "intern", "research assistant", "freelance",
        "junior analyst", "junior associate", "junior",
    ],
    "target_countries_tier1": [
        "United States", "United Kingdom", "Germany", "France",
        "Switzerland", "Japan", "South Korea", "Australia", "Canada",
    ],
    "target_countries_tier2": [
        "India", "UAE", "Saudi Arabia", "Spain", "Brazil",
        "Netherlands", "Singapore", "Israel",
    ],
    "corporate_email_domains_negative": [
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "aol.com", "protonmail.com",
    ],
    "high_value_tech_stack": [
        "SAP", "Oracle", "Salesforce", "ServiceNow", "Workday",
        "Temenos", "FIS", "Veeva",
    ],
}

# ─── Intent Signals ──────────────────────────────────────────────────
INTENT_SIGNALS = {
    "high_intent_pages": ["pricing", "enterprise", "demo", "security", "compliance", "roi-calculator"],
    "medium_intent_pages": ["case-studies", "integrations", "api-docs", "partners", "features"],
    "low_intent_pages": ["blog", "whitepaper", "newsletter", "developers"],
    "high_intent_forms": ["demo_request", "contact_sales"],
    "partnership_forms": ["partner_inquiry"],
    "medium_intent_forms": ["free_trial", "developer_signup", "badge_scan"],
    "low_intent_forms": ["content_download", "newsletter", "whitepaper_download", "none"],
    "time_on_site_thresholds": {
        "high": 400,    # seconds
        "medium": 150,
        "low": 60,
    },
}

# ─── Routing Configuration ───────────────────────────────────────────
ROUTING_RULES = {
    "A": {
        "owner": "Account Executive / Senior BDR",
        "sla_minutes": 30,
        "actions": [
            "Immediate Slack alert to AE team",
            "AI-generated account brief",
            "Personalized outreach draft",
            "Account research summary",
            "CRM record creation with full enrichment",
        ],
        "human_review": "Required for ambiguous or low-confidence leads",
    },
    "B": {
        "owner": "SDR / BDR",
        "sla_minutes": 120,
        "actions": [
            "Add to SDR priority queue",
            "AI-generated email draft",
            "CRM task creation",
            "Sequence enrollment",
        ],
        "human_review": "Review if adjudication_needed flag is set",
    },
    "C": {
        "owner": "Marketing (Nurture)",
        "sla_minutes": 1440,
        "actions": [
            "Enroll in nurture sequence",
            "Content recommendation engine",
            "Retargeting audience addition",
            "Monthly digest inclusion",
        ],
        "human_review": "Not required unless manual override requested",
    },
    "D": {
        "owner": "Marketing (Low Priority)",
        "sla_minutes": None,
        "actions": [
            "Archive to low-priority pool",
            "Optional retargeting list",
            "Quarterly re-evaluation batch",
        ],
        "human_review": "Not required",
    },
    "PARTNER": {
        "owner": "Partnership Team / Channel Manager",
        "sla_minutes": None,
        "actions": [
            "Route to partnership pipeline",
            "Partner program overview",
            "Channel manager notification",
            "Partnership qualification call",
        ],
        "human_review": "Required — partnership leads need manual qualification",
    },
}

# ─── Country Normalization ───────────────────────────────────────────
COUNTRY_ALIASES = {
    "US": "United States",
    "USA": "United States",
    "U.S.": "United States",
    "U.S.A.": "United States",
    "united states": "United States",
    "UK": "United Kingdom",
    "U.K.": "United Kingdom",
    "united kingdom": "United Kingdom",
    "GB": "United Kingdom",
}

# ─── Adjudication Thresholds ─────────────────────────────────────────
ADJUDICATION_CONFIG = {
    "score_gray_zone": (55, 75),        # scores in this range trigger deeper review
    "confidence_threshold": 0.6,         # below this → flag for adjudication
    "conflicting_signal_delta": 30,      # if max dimension - min dimension > this → conflict
    "max_research_leads": 10,            # cap on how many Tier A leads get full research
}

# ─── Bounded AI Authority ────────────────────────────────────────────
# AI reasoning/adjudication may change tier ONLY within these bounds.
# Deterministic scoring is the system of record; AI is an advisor with
# narrow, auditable write-access to tier assignments.
AI_AUTHORITY = {
    "gray_zone_points": 7,           # AI can only move tier if score is within ±N of a boundary
    "require_confidence": "high",    # AI must self-rate "high" to apply the change
    "max_tier_jump": 1,              # AI may move at most one tier (A↔B, B↔C, C↔D)
    "guardrails": {
        "min_icp_for_tier_a": 50,          # cannot be Tier A if ICP < 50
        "min_intent_for_tier_a": 60,       # cannot be Tier A if Intent < 60
        "min_confidence_for_tier_a": 60,   # cannot be promoted to Tier A if Data Confidence < 60
    },
}

# ─── LLM Inference Controls ──────────────────────────────────────────
# Pinned for reproducibility. `seed` is best-effort at the provider level;
# we log `system_fingerprint` to detect backend changes.
LLM_INFERENCE = {
    "temperature": 0,
    "seed": 42,
}

# ─── Reference Time (for recency scoring) ────────────────────────────
# When set, overrides datetime.now() in recency calculations. Used to freeze
# demo/submission runs so score outputs don't drift as calendar days pass.
# Format: ISO 8601, e.g. "2026-04-15T12:00:00Z". Unset → live clock.
REFERENCE_NOW = os.getenv("REFERENCE_NOW", "2026-04-15T12:00:00Z")

# ─── Output Configuration ────────────────────────────────────────────
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
SCORED_LEADS_FILE = "scored_leads.csv"
EVALUATION_REPORT_FILE = "evaluation_report.md"
