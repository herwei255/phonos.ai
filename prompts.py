"""
prompts.py — Loads AI prompt templates from the prompts/ folder.

To edit a prompt: open the corresponding .txt file in the prompts/ folder
using any text editor (TextEdit, Notepad, VS Code, etc.) and save.
Changes take effect immediately — no code changes needed.

To add a new note type:
  1. Create prompts/<your_type>.txt with {transcript} and optionally {date} placeholders.
  2. Add an entry to PROMPT_REGISTRY below: "your_type": _load("your_type")
"""

import os

_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def _load(name: str) -> str:
    """Read a prompt file from the prompts/ directory."""
    path = os.path.join(_DIR, f"{name}.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ── Prompts ───────────────────────────────────────────────────────────────────

STANDARD_PROMPT         = _load("standard")
HEDGE_FUND_PROMPT       = _load("hedge_fund")
DIFF_PROMPT             = _load("diff")
GLOSSARY_EXTRACT_PROMPT = _load("glossary_extract")


# ── Registry ──────────────────────────────────────────────────────────────────
# Keys are the note_type strings passed from the frontend.
# Add a new entry here once you've created the matching prompts/<key>.txt file.

PROMPT_REGISTRY: dict[str, str] = {
    "standard":   STANDARD_PROMPT,
    "hedge_fund": HEDGE_FUND_PROMPT,
}
