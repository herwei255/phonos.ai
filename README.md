# Phonos.ai

Turn your voice memos into structured meeting notes — automatically.

Record on your iPhone, upload to the app, and Phonos transcribes the audio and generates a clean summary in seconds. Works with mixed-language recordings (English + Mandarin). Has a special Hedge Fund mode that understands finance slang like "up in the teens" and "vs the 300".

---

## What you need before starting

- A Mac (the setup below is for macOS)
- Python 3.10 or newer — check with `python3 --version` in Terminal
- Two free API keys (takes about 5 minutes to get both):
  - **Groq** — for transcription (free): https://console.groq.com
  - **OpenRouter** — for note generation (free tier available): https://openrouter.ai

---

## First-time setup

Open Terminal and run these commands one by one:

```bash
# 1. Go into the project folder
cd ~/Code/meeting-notes-tool

# 2. Copy the example config file
cp .env.example .env

# 3. Open it and paste in your API keys
nano .env
```

Inside `.env`, fill in your keys — it looks like this:

```
GROQ_API_KEY=gsk_...your key here...
OPENROUTER_API_KEY=sk-or-...your key here...
```

Press `Ctrl+O` then `Enter` to save, then `Ctrl+X` to exit.

```bash
# 4. Install dependencies (only needed once)
pip3 install -r requirements.txt

# 5. Start the app
bash start.sh
```

Then open your browser and go to: **http://localhost:5000**

---

## Every day after that

Just run this from the project folder:

```bash
bash start.sh
```

---

## How to use it

### Recording on your iPhone and uploading

1. Record in the **Voice Memos** app on your iPhone
2. Tap the recording → tap `···` → **Share** → **Save to Files** → pick a folder
3. Open Phonos in your browser → click **+ Upload Voice Memo** → select the file
4. It automatically starts transcribing and generating notes — no extra clicks needed

You can select multiple recordings at once and they'll all be processed in order.

### Choosing a note style

- **Standard** — general meeting notes with summary, action items, decisions
- **Hedge Fund** — structured allocator meeting note with fund details, track record, portfolio construction, terms. Understands finance shorthand (alpha, net/gross, basis points, index numbers like "300" / "500" / "1000", return ranges like "up in the teens")

### Chat with your notes

Switch to the **Chat with Notes** tab and ask anything across all your recordings — "What did the Edelweiss fund say about their drawdown?" or "What action items came out of last week's meetings?"

### Recurring meeting series

If you meet with the same fund or person regularly, link those memos together using **📅 Link to recurring meeting series**. Then hit **⚡ Compare meetings** to get an AI-generated "What Changed?" brief across all sessions.

### Playback

Click the **Transcript** tab on any memo to see the audio player and timestamped transcript. Click any line to jump to that moment in the recording.

---

## iCloud auto-watch (optional)

If you have Voice Memos syncing to iCloud, Phonos can detect new recordings automatically and process them without any uploading.

To enable it, turn on iCloud sync on your iPhone:
**Settings → your name → iCloud → Voice Memos → toggle on**

Once synced, new recordings will appear in:
`~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/`

Phonos watches this folder automatically when the app is running. The sidebar shows a green **"watching"** pill when it's active.

---

## Saving notes to Apple Notes (macOS only)

When generating notes, toggle on **Add to Apple Notes**. Phonos creates two linked notes:
- **Voice Notes** folder — the structured meeting summary
- **Voice Transcripts** folder — the full transcript

Both notes link to each other so you can jump between them.

---

## Troubleshooting

**"File not found in voice_memos folder"**
The uploaded file didn't save. Try uploading again.

**Transcription is slow**
Normal for long recordings — Groq compresses the audio first if it's large. A 1-hour recording takes around 30–60 seconds.

**"not watching" shown in sidebar**
Either the app was just started for the first time (restart it), or iCloud Voice Memos sync isn't enabled on your iPhone yet.

**Apple Notes toggle is missing**
Apple Notes integration only works on macOS. It won't appear on Windows or Linux.

**I forgot my password**
Open `.env` in a text editor and look for `APP_PASSWORD=`. If it's blank, there's no password. If it's set, that's your password.

---

## File structure (for the curious)

```
meeting-notes-tool/
├── voice_memos/      ← your audio files live here
├── memos.db          ← all transcripts + notes stored here (SQLite)
├── .env              ← your API keys (never share this file)
├── start.sh          ← the script you run to start the app
├── run.py            ← app entry point
├── transcriber.py    ← Groq Whisper integration
├── summarizer.py     ← DeepSeek note generation
├── prompts.py        ← Standard + Hedge Fund prompt templates
├── chat.py           ← Chat with Notes logic
├── apple_notes.py    ← Apple Notes integration (macOS only)
├── watcher.py        ← iCloud folder auto-watch
├── db.py             ← database layer
└── routes.py         ← all API endpoints
```

---

## Deploying online (so anyone can access it from anywhere)

See `DEPLOY.md` for step-by-step instructions to deploy on Railway (free tier available). Once deployed, you get a public URL you can open on any device — phone, tablet, or another laptop.
