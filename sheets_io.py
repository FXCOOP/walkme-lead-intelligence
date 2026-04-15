"""
Google Sheets I/O module.
Handles reading leads from Google Sheets and writing scored results back.
Falls back to local CSV when Sheets credentials are not configured.
"""

import csv
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Optional Google Sheets dependencies
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    logger.info("gspread not installed — will use local CSV fallback")

from config import (
    GOOGLE_SHEETS_CREDENTIALS_FILE, GOOGLE_SHEET_ID,
    INPUT_SHEET_NAME, OUTPUT_SHEET_NAME,
)


def _get_sheets_client():
    """Authenticate with Google Sheets API using service account credentials."""
    if not GSPREAD_AVAILABLE:
        raise RuntimeError("gspread library not installed. Run: pip install gspread")

    creds_path = Path(GOOGLE_SHEETS_CREDENTIALS_FILE)
    if not creds_path.exists():
        raise FileNotFoundError(
            f"Google Sheets credentials file not found at {creds_path}. "
            "See README for setup instructions."
        )

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(creds_path), scopes=scopes)
    return gspread.authorize(creds)


def read_leads_from_sheets() -> list[dict]:
    """Read leads from Google Sheets. Returns list of lead dicts."""
    try:
        gc = _get_sheets_client()
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)
        worksheet = spreadsheet.worksheet(INPUT_SHEET_NAME)
        records = worksheet.get_all_records()
        logger.info(f"Loaded {len(records)} leads from Google Sheets")
        return records
    except Exception as e:
        logger.warning(f"Google Sheets read failed: {e}")
        raise


def read_leads_from_csv(file_path: str = "data/leads_input.csv") -> list[dict]:
    """Read leads from local CSV file. Fallback when Sheets is unavailable."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        leads = list(reader)

    logger.info(f"Loaded {len(leads)} leads from {path}")
    return leads


def read_leads(source: str = "auto") -> list[dict]:
    """
    Unified lead reader. Tries Google Sheets first, falls back to CSV.
    source: "sheets" | "csv" | "auto"
    """
    if source == "csv":
        return read_leads_from_csv()

    if source == "sheets":
        return read_leads_from_sheets()

    # Auto mode: try Sheets first, fall back to CSV
    if GSPREAD_AVAILABLE and GOOGLE_SHEET_ID:
        try:
            return read_leads_from_sheets()
        except Exception as e:
            logger.warning(f"Sheets unavailable, falling back to CSV: {e}")

    return read_leads_from_csv()


def write_results_to_sheets(results: list[dict]) -> None:
    """Write scored results back to Google Sheets output tab."""
    try:
        gc = _get_sheets_client()
        spreadsheet = gc.open_by_key(GOOGLE_SHEET_ID)

        # Create or get output worksheet
        try:
            worksheet = spreadsheet.worksheet(OUTPUT_SHEET_NAME)
            worksheet.clear()
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=OUTPUT_SHEET_NAME, rows=len(results) + 1, cols=30
            )

        if not results:
            logger.warning("No results to write")
            return

        # Write headers
        headers = list(results[0].keys())
        worksheet.update(range_name="A1", values=[headers])

        # Write data rows
        rows = []
        for r in results:
            row = []
            for h in headers:
                val = r.get(h, "")
                # Convert non-string types for Sheets
                if isinstance(val, (dict, list)):
                    val = json.dumps(val)
                elif isinstance(val, bool):
                    val = str(val)
                row.append(val)
            rows.append(row)

        worksheet.update(range_name="A2", values=rows)
        logger.info(f"Wrote {len(results)} scored leads to Google Sheets")

    except Exception as e:
        logger.error(f"Google Sheets write failed: {e}")
        raise


def write_results_to_csv(results: list[dict], file_path: str = None) -> str:
    """Write scored results to local CSV file."""
    from config import OUTPUT_DIR, SCORED_LEADS_FILE
    if file_path is None:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        file_path = os.path.join(OUTPUT_DIR, SCORED_LEADS_FILE)

    if not results:
        logger.warning("No results to write")
        return file_path

    # Select output columns in logical order
    output_columns = [
        "lead_id", "first_name", "last_name", "email", "company", "job_title",
        "company_size", "industry", "country", "lead_source",
        "icp_fit_score", "intent_score", "engagement_score", "data_confidence_score",
        "final_score", "tier", "adjusted_tier",
        "routing_owner", "routing_sla_minutes", "recommended_action_summary",
        "ai_reasoning", "ai_confidence",
        "adjudication_needed", "adjudication_reasons", "adjudication_decision",
        "is_partnership",
        "research_summary", "research_raw",
        "human_review_needed",
    ]

    # Only include columns that exist in the data
    available_columns = [c for c in output_columns if c in results[0]]

    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=available_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    logger.info(f"Wrote {len(results)} scored leads to {file_path}")
    return file_path
