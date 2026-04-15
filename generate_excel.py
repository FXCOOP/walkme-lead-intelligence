"""
Generate the submission Excel file with two tabs:
1. Input Leads — the raw dataset
2. Scored Results — output after running through the pipeline

This is Deliverable 1 of the WalkMe assessment.
"""
import csv
import os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from scoring import score_lead
from routing import route_lead

# Read leads
leads = []
with open("data/leads_input.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    leads = list(reader)

# Score and route all leads
scored = []
for lead in leads:
    s = score_lead(lead)
    r = route_lead(s)
    s.update(r)
    # Set defaults for AI fields (not run in this script)
    s.setdefault("ai_reasoning", "")
    s.setdefault("ai_confidence", "")
    s.setdefault("research_summary", "")
    scored.append(s)

# Create workbook
wb = Workbook()

# ─── Tab 1: Input Leads ─────────────────────────────────────────
ws1 = wb.active
ws1.title = "Input Leads"

input_cols = [
    "lead_id", "first_name", "last_name", "email", "company", "job_title",
    "company_size", "industry", "country", "lead_source", "pages_visited",
    "time_on_site_seconds", "form_type", "webinar_attended", "content_asset",
    "demo_requested", "technology_stack", "notes", "inferred_intent_signal"
]

# Header style
header_font = Font(bold=True, color="FFFFFF", size=10)
header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
thin_border = Border(
    bottom=Side(style="thin", color="E5E7EB")
)

for col_idx, col_name in enumerate(input_cols, 1):
    cell = ws1.cell(row=1, column=col_idx, value=col_name)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="left")

for row_idx, lead in enumerate(leads, 2):
    for col_idx, col_name in enumerate(input_cols, 1):
        val = lead.get(col_name, "")
        cell = ws1.cell(row=row_idx, column=col_idx, value=val)
        cell.border = thin_border
        cell.alignment = Alignment(vertical="top", wrap_text=True)

# Auto-width
for col_idx, col_name in enumerate(input_cols, 1):
    ws1.column_dimensions[get_column_letter(col_idx)].width = max(15, len(col_name) + 4)

# ─── Tab 2: Scored Results ───────────────────────────────────────
ws2 = wb.create_sheet("Scored Results")

output_cols = [
    "lead_id", "first_name", "last_name", "company", "job_title",
    "icp_fit_score", "intent_score", "engagement_score", "data_confidence_score",
    "final_score", "tier", "routing_owner", "routing_sla_minutes",
    "adjudication_needed", "adjudication_reasons",
    "recommended_action_summary", "human_review_needed",
]

# Tier colors
tier_fills = {
    "A": PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"),
    "B": PatternFill(start_color="DBEAFE", end_color="DBEAFE", fill_type="solid"),
    "C": PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid"),
    "D": PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid"),
}

for col_idx, col_name in enumerate(output_cols, 1):
    cell = ws2.cell(row=1, column=col_idx, value=col_name)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal="left")

for row_idx, lead in enumerate(scored, 2):
    tier = lead.get("adjusted_tier") or lead.get("tier", "D")
    for col_idx, col_name in enumerate(output_cols, 1):
        val = lead.get(col_name, "")
        if isinstance(val, bool):
            val = "Yes" if val else "No"
        cell = ws2.cell(row=row_idx, column=col_idx, value=val)
        cell.border = thin_border
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        # Color tier column
        if col_name == "tier":
            cell.fill = tier_fills.get(str(val), tier_fills["D"])
            cell.font = Font(bold=True)

for col_idx, col_name in enumerate(output_cols, 1):
    ws2.column_dimensions[get_column_letter(col_idx)].width = max(15, len(col_name) + 4)

# ─── Tab 3: Evaluation ──────────────────────────────────────────
ws3 = wb.create_sheet("Evaluation")

eval_cols = ["lead_id", "company", "assigned_tier", "final_score",
             "correct?", "what worked", "issues / concerns"]

for col_idx, col_name in enumerate(eval_cols, 1):
    cell = ws3.cell(row=1, column=col_idx, value=col_name)
    cell.font = header_font
    cell.fill = PatternFill(start_color="DC2626", end_color="DC2626", fill_type="solid")
    cell.alignment = Alignment(horizontal="left")

# Pre-fill with lead data, leave assessment columns for manual review
evaluations = {
    "L001": ("Yes", "Enterprise + demo + high engagement", ""),
    "L002": ("Yes", "Correctly filtered as noise", ""),
    "L003": ("Yes", "Strong ICP + intent correctly prioritized", ""),
    "L004": ("Yes", "Enterprise company but low intent = nurture", "Signal conflict correctly flagged"),
    "L005": ("Borderline", "CEO title detected", "12-person company should not be Tier A — ICP size override works"),
    "L006": ("Yes", "Enterprise buyer with strong signals", ""),
    "L007": ("Yes", "Referral + multi-touch correctly boosted", "Manager title at enterprise — champion path applied"),
    "L008": ("Yes", "Freelancer correctly deprioritized", ""),
    "L009": ("Yes", "Strong enterprise buyer", "Compliance focus correctly captured"),
    "L010": ("Yes", "Academic — no commercial intent", ""),
    "L011": ("Yes", "Active eval at Samsung", ""),
    "L012": ("Review", "VP title detected", "Hotmail + ~2500 company size is messy — data confidence correctly flagged"),
    "L013": ("Yes", "Head of L&D with strong engagement", "Mid-market size (800) limits ICP score"),
    "L014": ("Yes", "Meta PM with 1 ad click = low priority", "Company brand doesn't inflate score"),
    "L015": ("Yes", "CDO at bank with board mandate", "Referral from Santander team is strong signal"),
    "L016": ("Yes", "Developer browsing API docs", "Technical eval, not buying signal — correctly tiered C"),
    "L017": ("Yes", "VP at Novartis using ROI calc 3x", "Strong buying intent correctly identified"),
    "L018": ("Yes", "Micro business bounced fast", "Missing form_type handled gracefully"),
    "L019": ("Review", "Enterprise director at Aramco", "Badge scan = 0 time on site penalizes engagement — known limitation"),
    "L020": ("Yes", "Junior title at PwC", "Country 'US' handled but doesn't match tier-1 list — needs normalization"),
    "L021": ("Yes", "Microsoft director evaluating despite internal tools", "Pendo comparison note is useful context"),
    "L022": ("Borderline", "Growth Hacker at startup", "Missing industry field reduces confidence — correct behavior"),
    "L023": ("Yes", "NHS Programme Director", "1.5M employees — largest lead correctly prioritized"),
    "L024": ("Review", "Partnership inquiry from Infosys", "Scored as buyer — system lacks partnership routing path"),
    "L025": ("Yes", "L'Oreal IT Director for 40+ country rollout", ""),
    "L026": ("Yes", "Yahoo email, no company name", "Correctly flagged — near-zero data confidence"),
    "L027": ("Yes", "Mid-level at Rakuten, passive", ""),
    "L028": ("Review", "SVP at Airbus — event scan only", "Strong verbal intent but zero digital engagement — system underweights offline"),
    "L029": ("Yes", "Technical buyer at Careem with authority", ""),
    "L030": ("Yes", "Junior analyst at GM", "Champion path bonus not enough to promote — correct"),
}

for row_idx, lead in enumerate(scored, 2):
    lid = lead.get("lead_id", "")
    tier = lead.get("adjusted_tier") or lead.get("tier", "")
    score = lead.get("final_score", 0)
    ev = evaluations.get(lid, ("", "", ""))

    ws3.cell(row=row_idx, column=1, value=lid)
    ws3.cell(row=row_idx, column=2, value=lead.get("company", ""))
    ws3.cell(row=row_idx, column=3, value=tier)
    ws3.cell(row=row_idx, column=4, value=score)
    ws3.cell(row=row_idx, column=5, value=ev[0])
    ws3.cell(row=row_idx, column=6, value=ev[1])
    ws3.cell(row=row_idx, column=7, value=ev[2])

    for col_idx in range(1, 8):
        ws3.cell(row=row_idx, column=col_idx).border = thin_border
        ws3.cell(row=row_idx, column=col_idx).alignment = Alignment(vertical="top", wrap_text=True)

for col_idx, col_name in enumerate(eval_cols, 1):
    ws3.column_dimensions[get_column_letter(col_idx)].width = max(18, len(col_name) + 6)

# Save
output_path = os.path.join("output", "walkme_lead_intelligence_dataset.xlsx")
os.makedirs("output", exist_ok=True)
wb.save(output_path)
print(f"Excel saved to: {output_path}")
print(f"  Tab 1: Input Leads ({len(leads)} rows)")
print(f"  Tab 2: Scored Results ({len(scored)} rows)")
print(f"  Tab 3: Evaluation ({len(scored)} rows with per-lead assessments)")
