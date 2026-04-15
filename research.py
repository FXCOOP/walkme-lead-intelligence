"""
Account research module using OpenAI with web search for top-tier leads.
Performs grounded company research and returns structured intelligence briefs.
"""

import json
import logging
from openai import OpenAI
from config import OPENAI_API_KEY, OPENAI_RESEARCH_MODEL
from prompts import build_research_prompt

logger = logging.getLogger(__name__)

client = None


def get_client() -> OpenAI:
    global client
    if client is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set. Check your .env file.")
        client = OpenAI(api_key=OPENAI_API_KEY)
    return client


def research_account(lead: dict) -> dict:
    """
    Perform grounded account research for a high-priority lead.
    Uses OpenAI with web search tool to find real, verifiable information.
    Returns structured research brief or explicit failure message.
    """
    prompt = build_research_prompt(lead)
    company = lead.get("company", "Unknown")

    try:
        api = get_client()

        # Use responses API with web search tool for grounded research
        response = api.responses.create(
            model=OPENAI_RESEARCH_MODEL,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )

        # Extract text from response
        raw_text = ""
        for item in response.output:
            if item.type == "message":
                for block in item.content:
                    if block.type == "output_text":
                        raw_text = block.text
                        break

        if not raw_text:
            logger.warning(f"Empty research response for {company}")
            return _research_failure(company, "Empty response from research model")

        # Parse JSON from response (handle markdown code fences)
        json_text = raw_text.strip()
        if json_text.startswith("```"):
            json_text = json_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        research = json.loads(json_text)
        research["research_status"] = "completed"
        logger.info(f"Research completed for {company} (confidence: {research.get('research_confidence', 'unknown')})")
        return research

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse research JSON for {company}: {e}")
        return _research_failure(company, f"Response parsing error: {str(e)[:100]}")

    except Exception as e:
        logger.error(f"Research failed for {company}: {e}")
        return _research_failure(company, str(e)[:200])


def _research_failure(company: str, reason: str) -> dict:
    """Return a structured failure response when research cannot be completed."""
    return {
        "company_overview": f"Insufficient reliable public data found for {company}.",
        "employee_count": "Unverified",
        "estimated_revenue": "Unverified",
        "recent_developments": ["Research could not be completed"],
        "pain_points": ["Unable to determine — manual research recommended"],
        "urgency_signals": ["None identified"],
        "existing_dap_vendors": "No public data found",
        "research_confidence": "low",
        "data_gaps": [reason],
        "one_line_brief": f"Research incomplete for {company} — manual account review required.",
        "research_status": "failed",
    }


def format_research_summary(research: dict) -> str:
    """Format research dict into a concise, human-readable summary for output."""
    if research.get("research_status") == "failed":
        return f"Research incomplete: {research.get('data_gaps', ['Unknown error'])[0]}"

    parts = []

    overview = research.get("company_overview", "")
    if overview and "insufficient" not in overview.lower():
        parts.append(overview)

    developments = research.get("recent_developments", [])
    if developments and developments[0] != "Research could not be completed":
        parts.append(f"Recent: {'; '.join(developments[:2])}")

    pain_points = research.get("pain_points", [])
    if pain_points and "unable to determine" not in pain_points[0].lower():
        parts.append(f"Pain points: {'; '.join(pain_points[:2])}")

    urgency = research.get("urgency_signals", [])
    if urgency and urgency[0].lower() != "none identified":
        parts.append(f"Urgency: {'; '.join(urgency[:2])}")

    brief = research.get("one_line_brief", "")
    if brief and "research incomplete" not in brief.lower():
        parts.append(f"Brief: {brief}")

    confidence = research.get("research_confidence", "unknown")
    parts.append(f"[Research confidence: {confidence}]")

    return " | ".join(parts) if parts else "No research data available."
