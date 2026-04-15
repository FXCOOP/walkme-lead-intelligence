# Lead Intelligence & Prioritization Engine

In a 30-lead stress test, 63% of leads required AI adjudication — not because scoring failed, but because the system refuses to act with false confidence when signals conflict.

This system is designed as a real-time lead decision engine, not a traditional scoring model.

---

## What This Does

This is not a lead scoring tool. It is a decision engine with four layers:

1. **Ingest** -- reads leads from Google Sheets or local CSV
2. **Score** -- four-dimension deterministic model (ICP Fit, Intent, Engagement, Data Confidence)
3. **Reason** -- AI evaluates each lead's tier assignment in context, confirms or challenges it
4. **Adjudicate** -- AI resolves conflicting signals on flagged leads (63% of the sample triggered adjudication)
5. **Research** -- grounded account intelligence for Tier A leads via web search (no fabrication)
6. **Route** -- maps each lead to owner, SLA, automated actions, and human-review flags
7. **Evaluate** -- self-assessment that surfaces where the system breaks, not just where it works

---

## Architecture

```
Google Sheets / CSV
        |
        v
+-------------------+
| Scoring Engine    |  scoring.py
| 4 dimensions x   |  Deterministic rules, fully auditable
| weighted score    |  Output: tier + dimension breakdown
+--------+----------+
         |
         v
+-------------------+
| AI Reasoning      |  prompts.py + gpt-4o-mini
| Per-lead          |  Validates tier, explains risks,
| assessment        |  recommends action, states confidence
+--------+----------+
         |
         v
+-------------------+
| AI Adjudication   |  prompts.py + gpt-4o-mini
| Flagged leads     |  Resolves signal conflicts:
| only              |  promote / downgrade / keep / escalate
+--------+----------+
         |
         v
+-------------------+
| Account Research  |  research.py + gpt-4o-mini (web search)
| Tier A only       |  Grounded company intelligence briefs
|                   |  Refuses to fabricate -- by design
+--------+----------+
         |
         v
+-------------------+
| Routing Engine    |  routing.py
|                   |  Owner, SLA, actions, human-review flags
+--------+----------+
         |
         v
+-------------------+
| Evaluator         |  evaluator.py
|                   |  Per-lead + system-level analysis
+--------+----------+
         |
         v
  scored_leads.csv
  evaluation_report.md
  system_evaluation.json
```

---

## Project Structure

```
walkme-lead-intelligence/
├── main.py                 # Pipeline orchestrator
├── config.py               # Weights, tiers, ICP definition, routing rules
├── scoring.py              # Deterministic 4-dimension scoring engine
├── prompts.py              # AI prompts: reasoning, adjudication, research
├── research.py             # Account research via OpenAI Responses API + web search
├── routing.py              # Tier -> owner / SLA / action mapping
├── sheets_io.py            # Google Sheets + CSV I/O
├── evaluator.py            # Self-evaluation and report generation
├── requirements.txt
├── .env.example
├── data/
│   └── leads_input.csv     # 30 leads with realistic variation and deliberate ambiguity
├── output/                 # Generated after running the pipeline
│   ├── scored_leads.csv
│   ├── evaluation_report.md
│   └── system_evaluation.json
└── docs/
    └── business_logic.md   # Full scoring logic, routing rules, evaluation findings
```

---

## Quick Start

### Deterministic Only (no API keys needed)

```bash
cd walkme-lead-intelligence
pip install -r requirements.txt
python main.py --skip-ai --source csv
```

### Full Pipeline with AI

```bash
cp .env.example .env
# Add your OPENAI_API_KEY to .env

python main.py --source csv

# Skip account research to save API calls:
python main.py --source csv --skip-research
```

### Google Sheets Integration

```bash
# 1. Create service account at console.cloud.google.com with Sheets API access
# 2. Download credentials JSON -> save as credentials.json
# 3. Share your Google Sheet with the service account email
# 4. Set GOOGLE_SHEET_ID and GOOGLE_SHEETS_CREDENTIALS_FILE in .env

python main.py
```

### CLI Options

```
python main.py [options]

--source {auto,csv,sheets}   Lead data source (default: auto)
--skip-ai                    Deterministic scoring only, no OpenAI calls
--skip-research              Score + reason but skip account research
```

---

## AI Layer Design

### Three Functions, Three Triggers

| Function | Trigger | Model | Output |
|----------|---------|-------|--------|
| Lead Reasoning | Every lead | gpt-4o-mini | Tier validation, risk flags, recommended action, confidence level |
| Conflict Adjudication | Flagged leads only | gpt-4o-mini | Promote / downgrade / keep / escalate decision with reasoning |
| Account Research | Tier A only | gpt-4o-mini + web search | Grounded company brief with verified facts and explicit data gaps |

### Design Principles

**Structured JSON output.** Every prompt specifies an exact schema. Outputs are parseable, auditable, and consistent. No free-text summaries to parse downstream.

**Confidence at every layer.** Every AI response includes a confidence level (high/medium/low). Low confidence triggers human review. The system never pretends certainty it does not have.

**Grounding over generation.** Account research explicitly forbids fabrication. When data is not available, the system says so. This is enforced in the prompt, validated in the output, and treated as a feature, not a limitation.

**Low temperature.** All prompts run at 0.2-0.3. The goal is deterministic judgment, not creative writing.

---

## Scoring Model

### Dimensions

| Dimension | Weight | What It Captures |
|-----------|--------|------------------|
| ICP Fit | 40% | Structural deal potential -- company size, industry, title, geography, tech stack |
| Intent | 35% | Active buying signals -- page visits, form fills, demo requests, time on site |
| Engagement | 15% | Multi-touch depth -- page diversity, source quality, content consumption |
| Data Confidence | 10% | Signal trustworthiness -- field completeness, email legitimacy, red flag detection |

### Tier Boundaries

| Tier | Range | Routing |
|------|-------|---------|
| A | 83-100 | AE / Senior BDR, 30-min SLA |
| B | 60-82 | SDR / BDR, 2-hour SLA |
| C | 40-59 | Marketing nurture, 24-hour |
| D | 0-39 | Archive, quarterly re-evaluation |

### Adjudication Triggers

Leads are flagged when:
- Final score is in the gray zone (55-75)
- Data confidence is below 60
- Gap between highest and lowest dimension scores exceeds 30 points

In the sample run, **19 of 30 leads (63%) triggered adjudication.** This is realistic for production lead data.

Full scoring breakdown: [docs/business_logic.md](docs/business_logic.md)

---

## Bounded AI Authority & Reproducibility

The system is designed around a single principle: **deterministic scoring is the source of truth; the AI layer is a bounded advisor.** This prevents stochastic drift from reshaping the priority queue across repeated runs.

| Layer | Role | Authority |
|---|---|---|
| Deterministic scoring | System of record | Owns `tier` |
| AI reasoning | Per-lead judgment, risk flags, recommended action | Advises `adjusted_tier` |
| AI adjudication | Conflict resolution on flagged leads | Advises `adjusted_tier` within guardrails |
| AI research | Grounded account intelligence | Read-only; pool selected by deterministic tier |

### Bounded Tier Authority

AI may overwrite `tier` only if **all** of the following are true:

1. The lead's final score is within **±7 points** of a tier boundary (the deterministic decision was itself borderline).
2. AI self-rated confidence is `high`.
3. The proposed move is at most one tier level (A↔B, B↔C, C↔D — no two-tier jumps).
4. No hard business guardrail is violated: a lead with ICP < 50 or Intent < 60 cannot be Tier A; a lead with Data Confidence < 60 cannot be promoted to Tier A.

When AI disagrees with the deterministic tier but the change is blocked, `adjusted_tier` stays at base, the disagreement is preserved in `ai_suggested_tier` for audit, and `human_review_needed` is set. The AI's judgment is never silently discarded.

### Reproducibility Controls

- All reasoning and adjudication calls run with `temperature=0` and `seed=42`.
- `system_fingerprint` is logged per call to detect provider-side backend routing.
- The account research pool is built from the **deterministic base tier**, not `adjusted_tier` — so the set of researched companies is stable across runs even when AI reasoning shifts around the margin.
- Recency scoring uses a configurable `REFERENCE_NOW` (default: frozen at the dataset date) so the same dataset cannot drift as calendar days pass.

This combination preserves AI judgment on ambiguous leads while keeping the business-visible output (tier distribution, research pool, routing assignments) stable on repeat runs.

---

## Known Limitations and Fix Path

| Limitation | Impact | Fix |
|------------|--------|-----|
| No email verification | L026-type false leads pass through | Integrate ZeroBounce/NeverBounce API |
| Offline engagement blind spot | Event-only leads (badge scans) are penalized | Add event-source engagement bypass |
| ~~No partnership routing~~ | ~~Partnership inquiries score as buyer intent~~ | **FIXED** -- partner_inquiry removed from high_intent_forms; routing overrides to Partnership Team |
| ~~Country abbreviation mismatch~~ | ~~Leads with "US"/"UK" got 0 geography points~~ | **FIXED** -- COUNTRY_ALIASES normalizes abbreviations before scoring |
| No CRM integration | Routing decisions are output-only | Production system writes to Salesforce/HubSpot |
| No feedback loop | Scoring weights are static | AE accept/reject feedback auto-adjusts weights |
| English-only | Non-English leads are not processed | Extend prompt layer for multilingual input |

---

## Design Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Language | Python | n8n / Make | Full control over scoring logic, prompt engineering, and output formatting. Workflow tools require workarounds for complex conditional logic. |
| AI model | gpt-4o-mini | reasoning models (o-series) | Default model: gpt-4o-mini (optimized for speed, cost, and production readiness). Reasoning models were tested and produced comparable quality at significantly higher latency — not worth the trade at production scale. |
| Research API | Responses API + web_search | Chat + manual search | Produces grounded results with citations. Chat completions cannot access current web data. |
| Output format | CSV + Markdown + JSON | Dashboard UI | Evaluator-friendly. Reviewer opens CSV in Excel, report in any browser. No infrastructure dependency. |
| Scoring model | 4-dimension weighted | Single score / ML classifier | Interpretable, auditable, tunable. An ML model with 30 leads would be overfitting theater. |
| Adjudication | Multi-condition trigger | Score-only | Score-only misses leads with high score but low confidence -- the most dangerous false positives. |

---

## Deliverables

| Deliverable | Location | Status |
|-------------|----------|--------|
| Dataset (30 leads) | `data/leads_input.csv` | Complete -- includes deliberate ambiguity cases |
| Business logic | `docs/business_logic.md` | Complete -- scoring, routing, evaluation, monitoring |
| Technical README | `README.md` | Complete |
| Working code | `*.py` files | Complete -- modular, documented, runnable |
| Sample output | `output/` | Generated via `python main.py --skip-ai` |
| Self-evaluation | `output/evaluation_report.md` | Complete -- surfaces failures, not just successes |

---

## Production Economics

At production scale, this pipeline is optimized for cost-per-lead, not just accuracy.

| Metric | Estimate |
|--------|----------|
| Leads processed per day | ~500 |
| AI calls per lead | 2–3 (reasoning + conditional adjudication + conditional research) |
| Cost per lead | $0.08–$0.15 |
| Daily cost | $40–$75 |
| Latency (batch) | ~2–4 minutes for a 500-lead batch |

**Optimization notes:**
- **Async processing** — designed for async/concurrent processing in production; this prototype runs sequentially for simplicity and auditability.
- **Batching** — adjudication is only triggered when the deterministic layer flags a conflict (~40–60% of leads), not for every lead.
- **Model selection** — `gpt-4o-mini` is the default across reasoning, adjudication, and research (optimized for speed, cost, and production readiness).
- **Recency signal** (`last_activity_at`) shifts priority toward hot leads without adding cost.

---

## Author

Dmitry (Dima) Hasin
April 2026
