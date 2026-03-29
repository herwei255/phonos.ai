"""
glossary.py — Dynamic terminology management for Phonos.ai.

After each hedge fund memo is processed, this module:
  1. Runs a secondary AI pass to extract new finance jargon from the transcript
     that isn't already in the standard glossary.
  2. Saves the new terms to the `glossary` DB table.
  3. Provides a formatted block that gets injected into the next hedge fund prompt,
     so the AI always knows the growing fund-specific vocabulary.

The glossary is keyed by note_type (default "hedge_fund"), so in future you
can maintain separate term banks for other note types.
"""

import logging
import threading

logger = logging.getLogger(__name__)


# ── Injection ──────────────────────────────────────────────────────────────────

def build_dynamic_glossary_block(note_type: str = "hedge_fund") -> str:
    """Return a formatted prompt block of all saved dynamic terms, or empty string.

    Injected into the prompt as {dynamic_glossary}.
    If there are no saved terms yet, returns an empty string (no section added).
    """
    import db
    terms = db.get_glossary(note_type)
    if not terms:
        return ""

    lines = [
        "FUND-SPECIFIC TERMINOLOGY (learned from previous memos — apply these when interpreting the transcript):"
    ]
    for t in terms:
        lines.append(f'- "{t["term"]}" = {t["definition"]}')
    lines.append("")  # trailing blank line before the next section separator
    return "\n".join(lines) + "\n"


# ── Extraction ─────────────────────────────────────────────────────────────────

def extract_and_save_new_terms(transcript: str, note_type: str = "hedge_fund") -> list[dict]:
    """Run an AI pass to find new jargon in `transcript` and persist them.

    Called in a background thread after a memo is processed so it never slows
    down the main response. Returns the list of newly saved terms (may be empty).
    """
    try:
        from openai import OpenAI
        import db
        from config import OPENROUTER_API_KEY, SUMMARIZER_MODEL
        from prompts import GLOSSARY_EXTRACT_PROMPT

        # Format existing dynamic terms so the AI doesn't re-extract them
        existing = db.get_glossary(note_type)
        if existing:
            existing_block = "ALREADY SAVED DYNAMIC TERMS (do NOT re-add):\n" + "\n".join(
                f'- "{t["term"]}" = {t["definition"]}' for t in existing
            )
        else:
            existing_block = ""

        prompt = GLOSSARY_EXTRACT_PROMPT.format(
            transcript=transcript,
            existing_dynamic_terms=existing_block,
        )

        client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1"
        )
        response = client.chat.completions.create(
            model=SUMMARIZER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
        )
        raw = response.choices[0].message.content.strip()

        if raw == "NO_NEW_TERMS" or not raw:
            logger.info("[Glossary] No new terms found.")
            return []

        # Parse "TERM: x = y" lines
        new_terms = []
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("TERM:"):
                continue
            body = line[len("TERM:"):].strip()
            if " = " not in body:
                continue
            term, definition = body.split(" = ", 1)
            term       = term.strip()
            definition = definition.strip()
            if term and definition:
                db.upsert_glossary_term(term, definition, note_type)
                new_terms.append({"term": term, "definition": definition})
                logger.info(f"[Glossary] Saved: '{term}' = {definition}")

        return new_terms

    except Exception as exc:
        logger.warning(f"[Glossary] Term extraction failed: {exc}")
        return []


def extract_and_save_async(transcript: str, note_type: str = "hedge_fund") -> None:
    """Fire-and-forget wrapper — runs extraction in a background daemon thread."""
    t = threading.Thread(
        target=extract_and_save_new_terms,
        args=(transcript, note_type),
        daemon=True,
    )
    t.start()
