"""
chat.py — Multi-turn Q&A across all processed meeting notes.

Context strategy (designed to balance detail vs. token cost):
────────────────────────────────────────────────────────────
  1. Summaries for the TOP 30 most relevant memos (capped).
     Relevance is scored by keyword overlap between the question and the
     memo's filename + summary. Compact (~200 tokens each). If you have
     more than 30 memos a note tells the model the library is larger.

  2. Transcript excerpts for the TOP 2 most relevant memos only.
     For each top memo we extract sliding windows (~600 chars) around every
     keyword match in the raw transcript, merge overlapping windows, and cap
     at 3 excerpts per memo.

     This means specific factual questions find the answer in the raw
     transcript without sending 50,000 tokens of audio transcription to the API.

Token budget (rough):
  • Up to 30 memos × ~200 tokens (summary) = ~6,000 tokens
  • 2 memos × 3 excerpts × ~150 tokens     = ~900 tokens
  • Total stays well under 10,000 tokens for any size library.
"""
import re
from openai import OpenAI
from config import OPENROUTER_API_KEY, SUMMARIZER_MODEL
import db

SYSTEM_PROMPT = """You are a personal assistant with access to meeting notes and transcripts.

For each memo you receive:
  • SUMMARY — a structured digest of the meeting's key points
  • TRANSCRIPT EXCERPTS — snippets of the actual spoken words, pulled from the
    section of the recording most relevant to the current question

The transcript excerpts are the ground truth. When the summary and the transcript
disagree, trust the transcript. When looking for specific facts — names, numbers,
fund performance figures, dates — always check the transcript excerpts first.

Rules:
  • Always cite which memo/recording you are drawing from.
  • If the answer is not in the provided context, say so clearly. Do not guess.
  • Keep answers concise but complete.
"""


# ── Keyword extraction ────────────────────────────────────────────────────────

_STOP = {
    "what", "who", "when", "where", "how", "why", "did", "does", "is", "are",
    "was", "were", "the", "a", "an", "in", "of", "for", "to", "and", "or",
    "but", "you", "your", "me", "my", "their", "his", "her", "its", "this",
    "that", "these", "those", "which", "with", "about", "from", "into", "than",
    "then", "tell", "can", "will", "would", "could", "should", "have", "has",
    "had", "been", "being", "do", "get", "got", "make", "made", "any", "give",
    "just", "also", "more", "very", "much", "many", "some", "such", "like",
    "use", "used", "using", "based", "per",
}


def _keywords(text: str) -> list[str]:
    """Return meaningful words from text, lowercased, stop-words removed."""
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text)
    return [w.lower() for w in words if w.lower() not in _STOP]


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _score_memo(memo: dict, kws: list[str]) -> int:
    """Count keyword hits in filename + summary (fast proxy for relevance)."""
    haystack = (memo.get("filename", "") + " " + memo.get("summary", "")).lower()
    return sum(haystack.count(kw) for kw in kws)


# ── Transcript excerpt extraction ─────────────────────────────────────────────

def _excerpt(transcript: str, kws: list[str],
             window: int = 600, max_chunks: int = 3) -> str:
    """Return up to max_chunks keyword-centred windows from transcript.

    Each window is window characters wide. Overlapping windows are merged.
    Falls back to the first window characters if no keyword is found.
    """
    if not transcript:
        return ""
    if not kws:
        return transcript[:window]

    text_lower = transcript.lower()
    half = window // 2

    # Collect all match positions, sorted
    positions: list[int] = []
    for kw in kws:
        for m in re.finditer(r"\b" + re.escape(kw) + r"\b", text_lower):
            positions.append(m.start())
    positions = sorted(set(positions))

    if not positions:
        return transcript[:window]

    # Merge overlapping windows
    merged: list[tuple[int, int]] = []
    cur_s = max(0, positions[0] - half)
    cur_e = min(len(transcript), positions[0] + half)
    for pos in positions[1:]:
        s = max(0, pos - half)
        e = min(len(transcript), pos + half)
        if s <= cur_e:          # overlapping — extend current window
            cur_e = max(cur_e, e)
        else:
            merged.append((cur_s, cur_e))
            cur_s, cur_e = s, e
        if len(merged) >= max_chunks:
            break
    merged.append((cur_s, cur_e))

    parts: list[str] = []
    for s, e in merged[:max_chunks]:
        chunk = transcript[s:e].strip()
        if s > 0:
            chunk = "…" + chunk
        if e < len(transcript):
            chunk = chunk + "…"
        parts.append(chunk)

    return "\n\n".join(parts)


# ── Context builder ───────────────────────────────────────────────────────────

TOP_N_TRANSCRIPTS = 2   # include transcript excerpts for this many top memos
MAX_SUMMARY_MEMOS = 30  # cap summaries at this many; excess memos are omitted


def _build_context(memos: list[dict], question: str) -> str:
    """Build the context block sent to the model.

    The TOP MAX_SUMMARY_MEMOS most-relevant memos contribute a summary.
    The TOP_N_TRANSCRIPTS most question-relevant memos also contribute
    keyword-matched transcript excerpts.

    When there are more than MAX_SUMMARY_MEMOS memos, a note is prepended
    so the model knows the full library is larger.
    """
    if not memos:
        return "No processed meeting notes available yet."

    kws = _keywords(question)

    # Rank by relevance score (desc). ISO date strings sort correctly as-is,
    # so equal-score memos are ordered oldest-first as a tiebreaker (harmless).
    all_ranked = sorted(
        [m for m in memos if m.get("summary")],
        key=lambda m: (-_score_memo(m, kws), m.get("file_date") or ""),
    )

    total = len(all_ranked)
    ranked = all_ranked[:MAX_SUMMARY_MEMOS]

    header_note = ""
    if total > MAX_SUMMARY_MEMOS:
        header_note = (
            f"*Note: You have {total} processed memos. "
            f"Showing the {MAX_SUMMARY_MEMOS} most relevant to this question.*\n\n"
        )

    sections: list[str] = []
    for idx, memo in enumerate(ranked):
        fname      = memo.get("filename", "Unknown")
        date       = (memo.get("file_date") or "")[:10]
        ntype      = memo.get("note_type", "standard")
        summary    = (memo.get("summary") or "").strip()
        transcript = (memo.get("transcript") or "").strip()

        header = f"### Memo: {fname}  |  {date}  |  type: {ntype}"

        if idx < TOP_N_TRANSCRIPTS and transcript and kws:
            ex = _excerpt(transcript, kws)
            sections.append(
                f"{header}\n\n**SUMMARY:**\n{summary}"
                f"\n\n**TRANSCRIPT EXCERPTS** (sections most relevant to your question):\n{ex}"
            )
        else:
            sections.append(f"{header}\n\n**SUMMARY:**\n{summary}")

    return header_note + "\n\n---\n\n".join(sections)


# ── Public API ────────────────────────────────────────────────────────────────

MAX_HISTORY = 20   # keep last 20 messages (10 turns) to bound payload size


def answer(question: str, history: list[dict] | None = None,
           user_id: int = 1) -> str:
    """Answer question using all processed meeting notes as context.

    Args:
        question: The user's question.
        history:  Optional list of prior {role, content} dicts for multi-turn chat.
        user_id:  The current user's DB id (scopes memos to their own notes).

    Returns:
        The assistant's answer as a string.
    """
    memos   = db.list_memos(user_id)
    context = _build_context(memos, question)

    system_with_context = (
        SYSTEM_PROMPT.strip()
        + "\n\n---\n\n# YOUR MEETING NOTES & TRANSCRIPTS\n\n"
        + context
    )

    messages: list[dict] = [{"role": "system", "content": system_with_context}]

    # Append prior turns, capped to control payload size
    if history:
        messages.extend(history[-MAX_HISTORY:])

    messages.append({"role": "user", "content": question})

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )
    response = client.chat.completions.create(
        model=SUMMARIZER_MODEL,
        messages=messages,
        temperature=0.2,
        max_tokens=1500,
    )
    return response.choices[0].message.content
