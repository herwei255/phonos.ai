"""
chat.py — Chat-with-your-notes feature.
Builds a context window from all stored summaries and sends the user's
question to DeepSeek via OpenRouter. Answers are grounded in your notes only.
"""
from datetime import datetime
from openai import OpenAI
from config import OPENROUTER_API_KEY, SUMMARIZER_MODEL
import db

SYSTEM_PROMPT = """You are a personal assistant with access to a collection of meeting notes and voice recordings.

Your job is to answer questions based ONLY on the notes provided. When answering:
- Be concise and direct.
- Reference the specific meeting or recording title when citing information.
- If the answer spans multiple meetings, list each source clearly.
- If the information is not in any of the notes, say so plainly — do not guess or hallucinate.
- Format any lists or structured answers cleanly."""


def build_context(memos: list[dict]) -> str:
    """Build a readable context block from all processed memos."""
    if not memos:
        return "No meeting notes have been processed yet."

    parts = []
    for m in memos:
        if not m.get("summary"):
            continue
        date_str = ""
        if m.get("file_date"):
            try:
                d = datetime.fromisoformat(m["file_date"])
                date_str = d.strftime("%b %d, %Y at %I:%M %p")
            except Exception:
                date_str = m["file_date"]

        parts.append(
            f"---\n"
            f"RECORDING: {m['filename']}\n"
            f"DATE: {date_str}\n"
            f"TYPE: {'Hedge Fund' if m.get('note_type') == 'hedge_fund' else 'Standard'}\n\n"
            f"{m['summary'].strip()}"
        )

    if not parts:
        return "No summaries available yet — process some voice memos first."

    return "\n\n".join(parts)


def answer(question: str, history: list[dict] | None = None) -> str:
    """Answer a question grounded in all stored meeting notes.

    Args:
        question: The user's question.
        history:  Optional list of previous messages for multi-turn chat.
                  Each item: {"role": "user"|"assistant", "content": "..."}

    Returns:
        The assistant's answer as a string.
    """
    memos   = db.list_memos()
    context = build_context(memos)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "system",
            "content": f"Here are all the meeting notes you have access to:\n\n{context}"
        }
    ]

    # Include prior turns for multi-turn conversation
    if history:
        messages.extend(history)

    messages.append({"role": "user", "content": question})

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
    response = client.chat.completions.create(
        model=SUMMARIZER_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=1500
    )
    return response.choices[0].message.content
