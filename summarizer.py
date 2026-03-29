"""
summarizer.py — Meeting notes generation via DeepSeek (OpenRouter).
To add a new note type: add its prompt to prompts.py and register it in PROMPT_REGISTRY.
To swap models: change SUMMARIZER_MODEL in config.py.
"""
from datetime import datetime
from openai import OpenAI
from config import OPENROUTER_API_KEY, SUMMARIZER_MODEL
from prompts import PROMPT_REGISTRY


def generate(transcript: str, note_type: str = "standard", custom_instructions: str = "") -> str:
    """Generate structured meeting notes from a transcript.

    Args:
        transcript:           Raw transcript text.
        note_type:            Key into PROMPT_REGISTRY (e.g. 'standard', 'hedge_fund').
        custom_instructions:  Optional freeform instructions appended to the prompt
                              (e.g. "include more bullet points", "be more concise").

    Returns:
        Formatted meeting notes as a plain text string.

    Raises:
        ValueError: If note_type is not registered in PROMPT_REGISTRY.
    """
    if note_type not in PROMPT_REGISTRY:
        raise ValueError(
            f"Unknown note_type '{note_type}'. "
            f"Available types: {list(PROMPT_REGISTRY.keys())}"
        )

    prompt_template = PROMPT_REGISTRY[note_type]
    prompt = prompt_template.format(
        transcript=transcript,
        date=datetime.now().strftime("%B %d, %Y")
    )

    if custom_instructions:
        prompt += f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{custom_instructions}"

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    response = client.chat.completions.create(
        model=SUMMARIZER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=3000
    )
    return response.choices[0].message.content


def extract_title(notes: str, note_type: str = "standard") -> str:
    """Extract a human-readable title from generated notes.
    Falls back to a date-stamped default if no title line is found.
    """
    today = datetime.now().strftime("%b %d, %Y")

    markers = {
        "hedge_fund": ("FUND:", f"Fund Meeting – {today}"),
        "standard":   ("MEETING TITLE:", f"Meeting Notes – {today}"),
    }
    prefix, fallback = markers.get(note_type, ("MEETING TITLE:", f"Meeting Notes – {today}"))

    for line in notes.split("\n"):
        if line.startswith(prefix):
            title = line.replace(prefix, "").strip()
            if title:
                return title
    return fallback
