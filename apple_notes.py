"""
apple_notes.py — Apple Notes integration via AppleScript.

Two folders are used:
  • APPLE_NOTES_FOLDER       ("Voice Notes")       — structured meeting summaries
  • APPLE_TRANSCRIPTS_FOLDER ("Voice Transcripts") — raw transcripts

Notes are cross-linked via applenotes:// deep-link URLs that Apple Notes creates
for every note. The summary note contains a clickable link to its transcript.

Implementation detail: HTML body content is written to a temp file and read by
AppleScript via POSIX file. This avoids the AppleScript string-length limit and
handles any special characters (quotes, backslashes, unicode) reliably.
"""
from __future__ import annotations
import os
import re
import subprocess
import tempfile
from config import APPLE_NOTES_FOLDER, APPLE_TRANSCRIPTS_FOLDER


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_as(s: str) -> str:
    """Escape a value for a double-quoted AppleScript string (title / path only).
    Body content is passed via file — do not use this for large text blobs.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _find_or_create_folder_script(folder_name: str) -> str:
    """AppleScript fragment that resolves (or creates) a named folder in the
    default account, leaving the result in the variable `targetFolder`."""
    f = _esc_as(folder_name)
    return f'''
    set targetFolder to missing value
    repeat with f in folders of default account
        if name of f is "{f}" then
            set targetFolder to f
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then
        set targetFolder to make new folder at default account with properties {{name:"{f}"}}
    end if'''


# ── HTML formatters ───────────────────────────────────────────────────────────

def notes_to_html(text: str, transcript_url: str | None = None,
                  source_filename: str | None = None) -> str:
    """Convert plain-text meeting notes to styled HTML for Apple Notes."""
    SECTION_RE = re.compile(r'^[A-Z][A-Z &\/\-]{2,}:?\s*$')
    META_RE    = re.compile(r'^(DATE|MEETING TITLE|FUND):\s*(.*)')

    lines = text.split("\n")
    html_parts: list[str] = []
    meta_buffer: list[str] = []

    # Filename header at the very top
    if source_filename:
        html_parts.append(
            f'<p style="font-size:11px;color:#a1a1aa;margin:0 0 12px 0;'
            f'padding-bottom:10px;border-bottom:1px solid #e4e4e7;'
            f'font-family:\'SF Mono\',\'Menlo\',monospace;">'
            f'🎙️ {_esc_html(source_filename)}</p>'
        )

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
        m = META_RE.match(stripped)
        if m:
            meta_buffer.append(
                f'<b style="color:#3f3f46">{_esc_html(m.group(1))}:</b> {_esc_html(m.group(2))}'
            )
            continue
        flush_meta()
        if SECTION_RE.match(stripped):
            html_parts.append(
                f'<p style="font-size:11px;font-weight:700;letter-spacing:0.8px;'
                f'text-transform:uppercase;color:#6366f1;margin:20px 0 4px 0;">'
                f'{_esc_html(stripped.rstrip(":"))}</p>'
            )
        elif stripped.startswith("- ") or stripped.startswith("* "):
            content = stripped[2:]
            is_none = re.match(r'^none\b', content, re.IGNORECASE)
            colour  = "#a1a1aa" if is_none else "#18181b"
            style   = "font-style:italic;" if is_none else ""
            html_parts.append(
                f'<p style="margin:2px 0 2px 8px;color:{colour};{style}">'
                f'<span style="color:#6366f1;margin-right:6px;">•</span>'
                f'{_esc_html(content)}</p>'
            )
        elif stripped != "---":
            html_parts.append(
                f'<p style="margin:2px 0;color:#18181b;">{_esc_html(stripped)}</p>'
            )
    flush_meta()

    if transcript_url:
        html_parts.append(
            f'<br><p style="font-size:12px;color:#a1a1aa;margin-top:20px;'
            f'border-top:1px solid #e4e4e7;padding-top:12px;">'
            f'📝 <a href="{_esc_html(transcript_url)}" style="color:#6366f1;text-decoration:none;">'
            f'View full transcript</a></p>'
        )
    return "\n".join(html_parts)


def transcript_to_html(transcript: str, summary_url: str | None = None,
                       summary_title: str | None = None,
                       source_filename: str | None = None) -> str:
    """Format raw transcript text for Apple Notes (readable monospace style).

    If summary_url is provided, a clickable "View summary" link is shown
    at the top of the note as a back-link to the corresponding summary note.
    """
    header = ""
    if source_filename:
        header += (
            f'<p style="font-size:11px;color:#a1a1aa;margin:0 0 12px 0;'
            f'padding-bottom:10px;border-bottom:1px solid #e4e4e7;'
            f'font-family:\'SF Mono\',\'Menlo\',monospace;">'
            f'🎙️ {_esc_html(source_filename)}</p>\n'
        )
    if summary_url:
        label = _esc_html(summary_title or "View meeting summary")
        header = (
            f'<p style="font-size:12px;color:#a1a1aa;margin-bottom:16px;'
            f'padding-bottom:12px;border-bottom:1px solid #e4e4e7;">'
            f'📋 <a href="{_esc_html(summary_url)}" style="color:#6366f1;text-decoration:none;">'
            f'{label}</a></p>\n'
        )
    lines = transcript.split("\n")
    paras = []
    for line in lines:
        escaped = _esc_html(line) if line.strip() else "&nbsp;"
        paras.append(
            f'<p style="font-family:\'SF Mono\',\'Menlo\',monospace;font-size:12px;'
            f'color:#27272a;line-height:1.7;margin:1px 0;">'
            f'{escaped}</p>'
        )
    # Wrap in an explicit white container — prevents Apple Notes from applying
    # any default gray/dark background to the monospace content block.
    content = (
        '<div style="background-color:#ffffff;padding:4px 0;">\n'
        + "\n".join(paras)
        + '\n</div>'
    )
    return header + content


# ── AppleScript bridge ────────────────────────────────────────────────────────

def _create_note_and_get_url(folder_name: str, title: str, html_body: str) -> str | None:
    """Create an Apple Notes note and return its applenotes:// URL.

    The HTML body is written to a temp file so AppleScript reads it via
    ``POSIX file`` — this sidesteps AppleScript string-length limits and
    avoids escaping issues with quotes, backslashes, or unicode in the content.

    Returns the URL string on success, None on failure.
    """
    # Write body to a temp file (utf-8)
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        )
        tmp.write(html_body)
        tmp.close()
        tmp_path = tmp.name
    except Exception as e:
        print(f"[Apple Notes] Failed to write temp file: {e}")
        return None

    try:
        safe_title = _esc_as(title)
        safe_path  = _esc_as(tmp_path)
        folder_script = _find_or_create_folder_script(folder_name)

        script = f'''tell application "Notes"
    activate{folder_script}
    set htmlContent to (read POSIX file "{safe_path}" as «class utf8»)
    set newNote to make new note at targetFolder with properties {{name:"{safe_title}", body:htmlContent}}
    return url of newNote
end tell
'''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[Apple Notes] AppleScript error: {result.stderr.strip()}")
            return None
        url = result.stdout.strip()
        return url if url else None

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _update_note_body(folder_name: str, note_title: str, html_body: str) -> bool:
    """Replace the body of an existing note identified by title and folder.

    Uses the same temp-file pattern as _create_note_and_get_url to handle
    any content length or special characters safely.

    Returns True on success, False if the note wasn't found or on error.
    """
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        )
        tmp.write(html_body)
        tmp.close()
        tmp_path = tmp.name
    except Exception as e:
        print(f"[Apple Notes] Failed to write temp file for update: {e}")
        return False

    try:
        safe_title  = _esc_as(note_title)
        safe_folder = _esc_as(folder_name)
        safe_path   = _esc_as(tmp_path)

        script = f'''tell application "Notes"
    set targetFolder to missing value
    repeat with f in folders of default account
        if name of f is "{safe_folder}" then
            set targetFolder to f
            exit repeat
        end if
    end repeat
    if targetFolder is missing value then return "folder not found"
    set targetNote to missing value
    repeat with n in notes of targetFolder
        if name of n is "{safe_title}" then
            set targetNote to n
            exit repeat
        end if
    end repeat
    if targetNote is missing value then return "note not found"
    set htmlContent to (read POSIX file "{safe_path}" as «class utf8»)
    set body of targetNote to htmlContent
    return "ok"
end tell
'''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[Apple Notes] Update error: {result.stderr.strip()}")
            return False
        return result.stdout.strip() == "ok"

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Upsert helper ─────────────────────────────────────────────────────────────

def _upsert_note_and_get_url(folder_name: str, title: str, html_body: str) -> str | None:
    """Create or update an Apple Notes note, always returning its applenotes:// URL.

    If a note with the same title already exists in the folder its body is
    replaced in-place (no duplicate created). If it doesn't exist yet a new
    note is created. Either way the URL of the note is returned.

    This is done in a single AppleScript call so there's no race condition.
    """
    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        )
        tmp.write(html_body)
        tmp.close()
        tmp_path = tmp.name
    except Exception as e:
        print(f"[Apple Notes] Failed to write temp file: {e}")
        return None

    try:
        safe_title  = _esc_as(title)
        safe_path   = _esc_as(tmp_path)
        folder_script = _find_or_create_folder_script(folder_name)

        script = f'''tell application "Notes"
    activate{folder_script}
    set htmlContent to (read POSIX file "{safe_path}" as «class utf8»)
    set targetNote to missing value
    repeat with n in notes of targetFolder
        if name of n is "{safe_title}" then
            set targetNote to n
            exit repeat
        end if
    end repeat
    if targetNote is missing value then
        set targetNote to make new note at targetFolder with properties {{name:"{safe_title}", body:htmlContent}}
    else
        set body of targetNote to htmlContent
    end if
    return url of targetNote
end tell
'''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"[Apple Notes] Upsert error: {result.stderr.strip()}")
            return None
        url = result.stdout.strip()
        return url if url else None

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def save_note(title: str, content_plain: str,
              transcript_url: str | None = None,
              source_filename: str | None = None) -> str | None:
    """Create or update a meeting summary in APPLE_NOTES_FOLDER ("Voice Notes").

    If a note with this title already exists its body is replaced in-place —
    no duplicate is created. Returns the applenotes:// URL on success.
    """
    html_body = notes_to_html(content_plain, transcript_url=transcript_url,
                              source_filename=source_filename)
    return _upsert_note_and_get_url(APPLE_NOTES_FOLDER, title, html_body)


def save_transcript_note(title: str, transcript: str,
                         source_filename: str | None = None) -> str | None:
    """Create or update a transcript note in APPLE_TRANSCRIPTS_FOLDER.

    If a note with this title already exists its body is replaced in-place.
    Returns the applenotes:// URL so the summary note can link to it.
    """
    if not transcript:
        return None
    html_body = transcript_to_html(transcript, source_filename=source_filename)
    return _upsert_note_and_get_url(APPLE_TRANSCRIPTS_FOLDER, title, html_body)


def update_transcript_note_with_summary_link(transcript_title: str, transcript: str,
                                              summary_url: str, summary_title: str,
                                              source_filename: str | None = None) -> bool:
    """Add a back-link to the summary note at the top of an existing transcript note.

    Called after both notes have been created so we have the summary's URL.
    Rewrites the transcript note body with the summary link prepended.

    Returns True on success, False on failure (non-fatal — the notes still exist,
    they just won't have the back-link).
    """
    html_body = transcript_to_html(transcript,
                                   summary_url=summary_url,
                                   summary_title=f"View summary: {summary_title}",
                                   source_filename=source_filename)
    return _update_note_body(APPLE_TRANSCRIPTS_FOLDER, transcript_title, html_body)
