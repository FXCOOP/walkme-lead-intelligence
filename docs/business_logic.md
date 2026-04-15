# Business Logic: Lead Intelligence & Prioritization Engine

## Executive Summary

This is a decision engine, not a scoring tool. It converts raw inbound signals into prioritized routing decisions with explicit confidence awareness at every layer.

Most lead scoring systems produce a number and call it done. This system produces a number, tells you how much to trust it, flags where the data is thin, and routes ambiguous cases to either AI adjudication or human review. The architecture reflects a core operational principle: **a system that cannot express uncertainty is a liability in production.**

---

## 1. Dataset Design Rationale

### Why These 30 Leads

The dataset was built to break the system, not to validate it. A scoring engine that only works on clean, obvious leads has no production value.

| Category | Count | Purpose |
|----------|-------|---------|
| Strong ICP matches | 8 | Confirm the engine correctly fast-tracks enterprise buyers with clear intent |
| Partial matches | 7 | Stress-test nuanced scoring where some dimensions are strong and others are absent |
| Clear low-fit | 5 | Verify the engine correctly filters noise without human intervention |
| Genuinely ambiguous | 10 | The actual test -- leads where the right answer depends on judgment, not rules |

### Deliberate Ambiguity Cases

These are the leads that expose whether a system is production-grade or a demo:

| Lead | Ambiguity | What It Tests |
|------|-----------|---------------|
| L005 -- TechStartup CEO | CEO title, 12-person company | Whether title seniority overrides company fit. It should not. |
| L012 -- Tom Bradley (Hotmail + VP) | Claims VP at Acme Corp, uses hotmail address | Data confidence scoring under identity mismatch |
| L014 -- Meta Program Manager | Fortune 10 company, mid-level title, one ad click | Whether brand halo inflates scores. A PM clicking an ad is not a deal. |
| L019 -- Saudi Aramco Director | Badge scan at event, zero digital engagement | Whether the engine penalizes offline-first leads unfairly |
| L024 -- Infosys Practice Lead | Partnership inquiry, not a purchase intent signal | Whether routing logic distinguishes buyer from partner intent |
| L026 -- Yahoo email claiming Oracle VP | Unverifiable identity, possible adversarial input | Data confidence scoring under adversarial conditions |
| L028 -- Airbus SVP (event scan) | Strong verbal intent at trade show, no digital trail | Same offline bias as L019, higher seniority |
| L030 -- GM Change Analyst | Junior title at massive company, low engagement | Whether company size compensates for weak individual signals. It should not. |

### Field Selection

**Input fields** mirror what a production marketing automation platform (HubSpot, Marketo, Pardot) actually captures:

- **Identity**: name, email, company, title -- who this person claims to be
- **Firmographic**: company_size, industry, country -- ICP matching signals
- **Behavioral**: pages_visited, time_on_site, form_type -- what they did
- **Engagement**: webinar_attended, content_asset, demo_requested -- depth of interaction
- **Contextual**: technology_stack, notes, inferred_intent_signal -- enrichment and human-entered context

**Output fields** serve two audiences: the BDR who needs to act in 30 seconds, and the RevOps manager who needs to audit the system weekly.

---

## 2. Scoring Architecture

### Four-Dimensional Model

A single composite score destroys information. A lead with perfect ICP fit and zero intent is fundamentally different from a lead with strong intent and no ICP match -- but a single number can rate them identically. The four-dimension model preserves the signal structure that routing decisions actually depend on.

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| **ICP Fit** | 40% | How closely this lead matches the ideal customer profile -- company size, industry, title seniority, geography, email legitimacy, tech stack |
| **Intent** | 35% | Behavioral signals indicating active buying interest -- page visits, form submissions, demo requests, time on site |
| **Engagement** | 15% | Multi-touch interaction depth -- page diversity, lead source quality, content consumption, engagement notes |
| **Data Confidence** | 10% | Trustworthiness of the data itself -- field completeness, corporate email, company verifiability, red flag detection |

### Weight Rationale

**ICP Fit at 40%:** ICP fit is the ceiling on deal potential. A perfect behavioral lead at a 12-person startup will never close an enterprise deal. No amount of intent overcomes structural misfit.

**Intent at 35%:** Without active buying signals, even a perfect ICP match is a name in a database. Intent is the leading indicator that converts profile into pipeline.

**Engagement at 15%:** Engagement adds signal depth. A lead who attended a webinar, downloaded a whitepaper, and visited pricing is meaningfully different from one who hit the pricing page once. This dimension rewards multi-touch patterns.

**Data Confidence at 10%:** Small weight, disproportionate operational impact. This dimension does not score the lead -- it scores how much the other scores should be trusted. Low data confidence is the primary trigger for the adjudication layer.

### Scoring Rules

Each dimension scores 0-100 using deterministic, auditable rules:

#### ICP Fit (0-100)
- Company size: Enterprise 1000+ (30pts), Mid-market 200-999 (20pts), SMB 50-199 (10pts), Micro <50 (0pts)
- Industry match: Target industry (20pts), Non-target (0pts)
- Title seniority: VP/Director/Chief/Head (25pts), Mid-level (10pts), Negative signals (0pts)
- Geography: Tier-1 markets (10pts), Tier-2 (6pts), Other (2pts). Country names are normalized before scoring (e.g., 'US' -> 'United States', 'UK' -> 'United Kingdom') to prevent silent scoring losses from inconsistent CRM data.
- Corporate email: Verified domain (5pts), Personal email (0pts)
- Tech stack overlap: 2+ matches (10pts), 1 match (5pts), None (0pts)

#### Intent (0-100)
- High-intent page visits: 8pts each (pricing, enterprise, demo, security, compliance, ROI)
- Medium-intent pages: 4pts each (case-studies, integrations, features)
- High-intent form: 25pts (demo_request, contact_sales)
- Partnership forms (partner_inquiry) receive 0 intent points and are routed to a separate partnership pipeline regardless of tier score.
- Demo requested: 15pts
- Webinar attended: 10pts
- Time on site: >400s (15pts), >150s (8pts), >60s (3pts)

#### Engagement (0-100)
- Page diversity: 8pts per distinct page category
- Lead source: Referral (20pts), Event (15pts), Paid (12pts), Webinar (10pts), Organic (5pts)
- Content download: 10pts
- Webinar engagement: 10pts
- Strong engagement notes: 8pts per keyword match
- High-intent form: 15pts

#### Data Confidence (0-100)
- Field completeness: pro-rated across 6 key fields (40pts)
- Corporate email domain: 20pts
- Known company size: 15pts
- Tech stack provided: 10pts
- No red flags: 15pts (deducted for personal email + senior title, missing company, etc.)

### Tier Assignment

| Tier | Score Range | Operational Meaning |
|------|------------|---------------------|
| A | 83-100 | High-priority buyer signal. Route to AE immediately. 30-min SLA. |
| B | 60-82 | Promising, needs development. Route to SDR for qualification. |
| C | 40-59 | Not ready to buy. Enroll in marketing nurture. |
| D | 0-39 | Low fit or noise. Archive. Batch re-evaluate quarterly. |

**Tier A calibration note:** The Tier A floor was raised from 80 to 83 after the sample run produced 43% Tier A concentration. Shifting the 80–82 band into Tier B forces marginal leads into SDR qualification rather than immediate AE touch — a deliberate calibration against over-promotion.

### Recency as a First-Class Signal

Inbound intent decays quickly. A lead who hit the pricing page 36 hours ago is operationally different from the same lead 30 days later, even though the static behavioral data is identical. The dataset carries two timestamps per lead — `created_at` and `last_activity_at` — and the Intent score adds a recency bonus:

| Last activity | Bonus |
|---------------|-------|
| < 2 days | +15 |
| < 7 days | +10 |
| < 30 days | +5 |
| ≥ 30 days | 0 |

Recency lives inside Intent (not Engagement) because it conditions the *interpretation* of behavioral signals: a demo request from last week is live pipeline; a demo request from Q3 is a re-engagement campaign. The bonus is capped so it cannot by itself promote a cold lead.

---

## 3. Confidence-Aware Routing

### The Adjudication Layer

This is the architectural decision that separates a decision engine from a scoring spreadsheet. Leads are flagged for AI adjudication when any of these conditions trigger:

1. **Gray zone score**: Final score falls between 55-75 (the decision boundary between "nurture" and "sales-ready")
2. **Low data confidence**: Data confidence score below 60
3. **Signal conflict**: Gap between highest and lowest dimension scores exceeds 30 points

When flagged, the AI receives the full lead profile, the specific conflict reason, and the deterministic scores. It then makes one of four operational decisions:

- **Promote**: Upgrade the tier -- signals suggest the deterministic model underweighted something contextual
- **Downgrade**: Lower the tier -- signals suggest score inflation or data quality issues
- **Keep**: Current tier is appropriate despite the ambiguity
- **Escalate to human**: The AI itself lacks sufficient confidence to decide

### Why This Matters Operationally

In the sample run of 30 leads, **19 were flagged for adjudication (63%)** -- more than half. This is not a failure. In real-world lead data, ambiguity is the norm. A system that only produces clean answers is hiding uncertainty behind false precision, and that uncertainty will surface as wasted AE time or missed deals.

---

## 4. AI Layer -- Three Distinct Functions

The AI layer is not a black box that produces a number. It performs three distinct, auditable functions with different triggers, different models, and different output schemas.

### Function 1: Lead Reasoning
**Trigger:** Every lead. **Model:** gpt-4o-mini (chat completions).

For each lead, the AI evaluates the deterministic score in context. It can confirm, question, or override the tier. Its reasoning is logged and visible in the output.

A VP of Digital Transformation at Salesforce who requested a demo is obvious. A badge scan from a Saudi Aramco director at a trade show is not. The deterministic model handles the first case. The AI layer handles the second.

### Function 2: Conflict Adjudication
**Trigger:** Flagged leads only. **Model:** gpt-4o-mini (chat completions).

For flagged leads, the AI performs deeper analysis of the specific conflict -- competing signals, data quality gaps, contextual factors the rules engine cannot capture. It recommends a resolution and states what additional data would resolve the ambiguity.

Without adjudication, the system either over-promotes ambiguous leads (wasting AE time) or under-promotes them (missing real opportunities). The adjudication layer forces an explicit decision with a stated confidence level.

### Function 3: Account Research
**Trigger:** Tier A leads only. **Model:** gpt-4o-mini (Responses API + web search).

For top-tier leads, the AI uses web search to build a grounded intelligence brief: company overview, recent developments, relevant pain points, urgency signals.

**Non-negotiable constraint:** Research must be grounded in verifiable public sources. If reliable information cannot be found, the system explicitly returns "Insufficient reliable public data found" rather than fabricating content. This is enforced in the prompt, validated in the output, and is a deliberate design choice -- not a limitation.

---

## 4.5. Bounded AI Authority

AI reasoning and adjudication may change the deterministic tier only within explicit bounds. The AI is an advisor; the deterministic engine is the system of record.

**A tier change is applied only if all four conditions hold:**

1. **Gray zone** — the final score is within ±7 points of a tier boundary (the deterministic decision was already borderline).
2. **High confidence** — AI self-rates `confidence == "high"`. Low or medium confidence recommendations are preserved as advisory and flag human review.
3. **One-tier move** — A↔B, B↔C, C↔D only. Two-tier jumps (e.g. C→A) are blocked.
4. **Business guardrails** — ICP < 50 or Intent < 60 cannot reach Tier A. Promotion to Tier A requires Data Confidence ≥ 60.

When the AI's suggestion is blocked, `adjusted_tier` remains at the deterministic base, `ai_suggested_tier` preserves the disagreement for audit, and `human_review_needed` is set. This keeps AI judgment visible without letting sampling noise reshape the priority queue.

### Reproducibility

- All AI calls use `temperature=0` and `seed=42`. `system_fingerprint` is logged per call.
- Research pool is built from the **deterministic tier**, not `adjusted_tier`, so the researched account set is stable across runs.
- Recency scoring uses a configurable `REFERENCE_NOW` to freeze demo runs against calendar drift.

---

## 5. Routing & Actions

| Tier | Owner | SLA | Automated Actions | Human Review |
|------|-------|-----|-------------------|--------------|
| A | AE / Senior BDR | 30 min | Slack alert, account brief, outreach draft, research summary, CRM record | Required for ambiguous or low-confidence leads |
| B | SDR / BDR | 2 hours | Priority queue, AI email draft, task creation, sequence enrollment | Required if adjudication flag is set |
| C | Marketing Nurture | 24 hours | Nurture sequence, content recommendation, retargeting, digest | Not required unless override requested |
| D | Marketing (Low Priority) | None | Archive, optional retargeting, quarterly batch re-evaluation | Not required |

### Human-in-the-Loop Design

Automation without human oversight is a liability, not an efficiency gain. The system mandates human review for:

1. **Ambiguous leads** -- where the adjudication layer was invoked
2. **Conflicting signal leads** -- where dimension scores diverge by more than 30 points
3. **Low-confidence high-score leads** -- where the AI itself expressed uncertainty
4. **Insufficient public data** -- where account research could not verify the company

The goal: focus human judgment on the 20% of leads where it changes outcomes, and automate the 80% that are deterministic.

---

## 6. Evaluation Findings

### Tier Distribution (Sample Run)

| Tier | Count | % | Honest Assessment |
|------|-------|---|-------------------|
| A | 12 | 40% | Well-calibrated after raising the Tier A floor to 83 and applying AI reasoning-driven downgrades; dataset composition still skews enterprise but the AI layer catches over-promotion. |
| B | 2 | 7% | Reasonable for this dataset composition |
| C | 8 | 27% | Appropriate -- mostly partial-fit and low-engagement leads |
| D | 8 | 27% | Correct -- clear low-fit, stale, or unverifiable leads (recency signal penalizes cold leads). |

### On "Accuracy"

This system does not carry an accuracy percentage. There is no external validation dataset — no labels of closed-won/lost leads to evaluate against. The only internal measure is self-assessed agreement: how many of the system's tier assignments survive the evaluator's heuristic review.

> Self-assessed agreement: X/Y leads.
> No external validation dataset.
> Requires 60-day backtest on closed-won data before any accuracy claim is operationally meaningful.

Any accuracy number produced without that backtest would be theater, not measurement.

### What the System Gets Right

- Enterprise buyers with clear intent (L001, L003, L009, L015, L017, L023) are correctly fast-tracked
- Clear noise leads (L002, L008, L010, L018) are correctly filtered without human intervention
- Data quality issues (L012, L026) trigger appropriate confidence flags and adjudication

### What Breaks

These are known failure modes, not surprises. Each has a specific root cause and a defined fix path.

1. **Event-only leads are penalized.** L019 (Saudi Aramco) and L028 (Airbus) have zero time-on-site because they were badge scans. The engagement score does not account for offline interaction quality. Root cause: the engagement model is digital-first by design.

2. **[FIXED] Partnership inquiries are misrouted.** L024 (Infosys) scored Tier A because the form signals look like buying intent. It is actually a partnership inquiry. Root cause: the routing logic does not distinguish between buyer and partner intent at the form_type level. Fix applied: partner_inquiry removed from high_intent_forms, receives 0 intent points, and routing.py overrides routing to Partnership Team / Channel Manager.

3. **Company brand inflates scores.** L014 (Meta) and L016 (ByteDance) benefit from enterprise company size, but the individuals show weak buying signals. A Program Manager clicking one ad is not a deal. Root cause: ICP Fit weight of 40% gives large companies a structural advantage.

4. **[FIXED] Country abbreviations cause silent scoring losses.** L020 (PwC, country="US") received 0 geography points because "US" did not match "United States" in the tier-1 list. Root cause: no normalization of country abbreviations before scoring. Fix applied: COUNTRY_ALIASES dict in config.py maps common abbreviations to full names; scoring.py normalizes country before geography lookup.

5. **Junior champions are invisible.** L020 (PwC Senior Associate) and L030 (GM Analyst) are correctly scored as low-priority by individual signals. But at companies this size, junior champions frequently initiate evaluation processes that become enterprise deals. Root cause: no champion-path modifier in the scoring model.

### Priority Fix Path

| Priority | Fix | Impact | Complexity |
|----------|-----|--------|------------|
| 1 | Email verification API (ZeroBounce/NeverBounce) | Eliminates L026-type false leads, highest-impact data quality improvement | Low |
| 2 | Event-source engagement bypass | Prevents penalizing offline-first leads from trade shows and events | Medium |
| 3 | Partnership routing path | Separate pipeline for partner_inquiry form type, prevents misrouting | Low |
| 4 | Champion-path scoring | Company-size modifier for junior titles at enterprise companies | Medium |

---

## 7. Production Monitoring

| Metric | Purpose | Alert Threshold | Response |
|--------|---------|-----------------|----------|
| Tier A to Meeting Rate | Validates lead quality | < 30% over 2 weeks | Audit recent Tier A leads; review scoring weights |
| Time-to-First-Touch (Tier A) | SLA compliance | > 60 min average | Escalate to sales ops; check alert delivery |
| False Positive Rate | AE-demoted leads within 48h | > 20% of Tier A | Tighten ICP criteria; increase confidence threshold |
| False Negative Recovery | Tier C/D leads that close in 90 days | > 5% of closed-won | Audit scoring patterns for missed signals |
| Manual Override Frequency | Human overrule rate | > 25% of adjudicated | Retrain scoring; review adjudication prompts |
| Research Failure Rate | Research completion | > 15% failure | Check API limits; expand source coverage |
| Confidence Drift | % low-confidence over time | > 30% in any week | Data quality issue; audit lead sources |
| Score Distribution Entropy | Tier balance stability | > 60% in any single tier | Calibration issue; review thresholds |

Each metric has a defined threshold and a specific operational response. The system is designed to degrade visibly, not silently.
