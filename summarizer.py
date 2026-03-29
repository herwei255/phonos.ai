"""
summarizer.py — Meeting notes generation via DeepSeek (OpenRouter).
To add a new note type: add its prompt to prompts.py and register it in PROMPT_REGISTRY.
To swap models: change SUMMARIZER_MODEL in config.py.
"""
from datetime import datetime
from openai import OpenAI
from config import OPENROUTER_API_KEY, SUMMARIZER_MODEL
from prompts import PROMPT_REGISTRY, DIFF_PROMPT


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

    # Build format kwargs — inject dynamic glossary for hedge_fund notes
    fmt_kwargs: dict = {
        "transcript": transcript,
        "date":       datetime.now().strftime("%B %d, %Y"),
    }
    if note_type == "hedge_fund":
        import glossary as gl
        fmt_kwargs["dynamic_glossary"] = gl.build_dynamic_glossary_block(note_type)

    prompt = prompt_template.format(**fmt_kwargs)

    if custom_instructions:
        prompt += (
            f"\n\nOVERRIDE INSTRUCTIONS (take priority over everything above):\n"
            f"{custom_instructions}\n"
            f"Apply these override instructions strictly. If they conflict with the format rules above, follow the override."
        )

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
    result = response.choices[0].message.content

    # After generating, kick off async term extraction for hedge fund notes
    if note_type == "hedge_fund":
        import glossary as gl
        gl.extract_and_save_async(transcript, note_type)

    return result


def generate_diff(series_name: str, meetings: list[dict]) -> str:
    """Generate a 'what changed?' comparison brief for a recurring meeting series.

    Args:
        series_name: Display name of the series (e.g. "Edelweiss SIF Quarterly").
        meetings:    List of memo dicts sorted by file_date ASC, each containing
                     at minimum 'file_date', 'summary', and 'display_name'/'filename'.

    Returns:
        Formatted diff brief as a plain text string.
    """
    if len(meetings) < 2:
        raise ValueError("Need at least 2 meetings to generate a comparison.")

    blocks = []
    for i, m in enumerate(meetings, 1):
        label = m.get("display_name") or m.get("filename", f"Meeting {i}")
        date  = (m.get("file_date") or "")[:10]
        summary = (m.get("summary") or "").strip()
        blocks.append(f"MEETING {i}: {label}  ({date})\n{summary}")

    meetings_block = "\n\n---\n\n".join(blocks)
    dates          = [(m.get("file_date") or "")[:10] for m in meetings]
    date_range     = f"{dates[0]} → {dates[-1]}"

    prompt = DIFF_PROMPT.format(
        series_name    = series_name,
        n_meetings     = len(meetings),
        meetings_block = meetings_block,
        date_range     = date_range,
    )

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    response = client.chat.completions.create(
        model=SUMMARIZER_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=2000,
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
