"""
apple_notes.py — Apple Notes integration via AppleScript.
Converts plain-text meeting notes to styled HTML so formatting is
preserved in Apple Notes (bold headers, bullets, meta lines).
"""
import re
import subprocess
from config import APPLE_NOTES_FOLDER


# ── Text → HTML converter ─────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notes_to_html(text: str) -> str:
    """Convert plain-text meeting notes to HTML for Apple Notes.

    Rules applied in order:
    - DATE / MEETING TITLE / FUND lines → grey meta block at top
    - ALL-CAPS section headings          → bold indigo label
    - Lines starting with - or *         → bullet list items
    - Divider (---) and blank lines      → spacing
    - Everything else                    → normal paragraph
    """
    SECTION_RE = re.compile(r'^[A-Z][A-Z &\/\-]{2,}:?\s*$')
    META_RE    = re.compile(r'^(DATE|MEETING TITLE|FUND):\s*(.*)')

    lines = text.split("\n")
    html_parts: list[str] = []
    meta_buffer: list[str] = []

    def flush_meta():
        nonlocal meta_buffer
        if meta_buffer:
            inner = "<br>".join(meta_buffer)
            html_parts.append(
                f'<p style="color:#71717a;font-size:13px;margin:0 0 16px 0;">{inner}</p>'
            )
            meta_buffer = []

    for line in lines:
        stripped = line.strip()

        if not stripped:
            flush_meta()
            html_parts.append('<br>')
            continue

        # META lines (DATE:, MEETING TITLE:, FUND:)
        m = META_RE.match(stripped)
        if m:
            label, value = m.group(1), m.group(2)
            meta_buffer.append(
                f'<b style="color:#3f3f46">{_esc(label)}:</b> {_esc(value)}'
            )
            continue

        flush_meta()

        # Section headings (ALL CAPS)
        if SECTION_RE.match(stripped):
            heading = stripped.rstrip(":")
            html_parts.append(
                f'<p style="font-size:11px;font-weight:700;letter-spacing:0.8px;'
                f'text-transform:uppercase;color:#6366f1;margin:20px 0 4px 0;">'
                f'{_esc(heading)}</p>'
            )
            continue

        # Bullet lines
        if stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:]
            is_none = re.match(r'^none\b', content, re.IGNORECASE)
            colour  = "#a1a1aa" if is_none else "#18181b"
            style   = "font-style:italic;" if is_none else ""
            html_parts.append(
                f'<p style="margin:2px 0 2px 8px;color:{colour};{style}">'
                f'<span style="color:#6366f1;margin-right:6px;">•</span>'
                f'{_esc(content)}</p>'
            )
            continue

        # Horizontal rule
        if stripped == "---":
            continue

        # Normal paragraph
        html_parts.append(
            f'<p style="margin:2px 0;color:#18181b;">{_esc(stripped)}</p>'
        )

    flush_meta()
    return "\n".join(html_parts)


# ── AppleScript bridge ────────────────────────────────────────────────────────

def _esc_applescript(s: str) -> str:
    """Escape a string for safe inclusion inside an AppleScript double-quoted string."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def save_note(title: str, content_plain: str) -> bool:
    """Create a note in Apple Notes under APPLE_NOTES_FOLDER.

    Uses the default account (avoids hardcoding 'iCloud' which varies by user).
    Converts plain text to HTML so formatting is preserved.

    Returns True on success, False on failure (error printed to console).
    """
    html_body  = notes_to_html(content_plain)
    safe_title = _esc_applescript(title)
    safe_body  = _esc_applescript(html_body)
    folder     = APPLE_NOTES_FOLDER

    script = f'''
tell application "Notes"
    activate
    set targetFolder to missing value
    repeat with f in folders of default account
        if name of f is "{folder}" then
            set targetFolder to f
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then
        set targetFolder to make new folder at default account with properties {{name:"{folder}"}}
    end if
    make new note at targetFolder with properties {{name:"{safe_title}", body:"{safe_body}"}}
end tell
'''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[Apple Notes] Error: {result.stderr.strip()}")
    return result.returncode == 0
