"""
transcriber.py — Audio transcription via Groq Whisper.
Handles large files by compressing with ffmpeg before uploading.
To swap providers: replace the OpenAI client init and model name.
"""
import os
import subprocess
import tempfile
from openai import OpenAI
from config import GROQ_API_KEY, WHISPER_MODEL, GROQ_MAX_BYTES


def compress_audio(src_path: str) -> str:
    """Compress audio to mono MP3 at 64 kbps using ffmpeg.
    Returns the path to a temp file — caller is responsible for deleting it.
    Raises RuntimeError if ffmpeg is not installed or compression fails.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()

    result = subprocess.run(
        ["ffmpeg", "-y", "-i", src_path,
         "-ac", "1",       # mono
         "-ar", "16000",   # 16 kHz — sufficient for speech
         "-b:a", "64k",    # 64 kbps
         tmp.name],
        capture_output=True
    )

    if result.returncode != 0:
        os.unlink(tmp.name)
        raise RuntimeError(
            "ffmpeg compression failed. Install it with: brew install ffmpeg\n"
            + result.stderr.decode()
        )

    return tmp.name


def transcribe(file_path: str) -> str:
    """Transcribe an audio file using Groq Whisper.
    Automatically compresses the file if it exceeds GROQ_MAX_BYTES.
    Returns the transcript as a plain string.
    """
    compressed_path = None
    send_path = file_path

    if os.path.getsize(file_path) > GROQ_MAX_BYTES:
        compressed_path = compress_audio(file_path)
        send_path = compressed_path

    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )
        with open(send_path, "rb") as audio_file:
            result = client.audio.transcriptions.create(
                model=WHISPER_MODEL,
                file=audio_file,
                response_format="text"
            )
        return result
    finally:
        if compressed_path:
            try:
                os.unlink(compressed_path)
            except Exception:
                pass
