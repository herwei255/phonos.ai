# Phonos.ai

Turn your voice memos into structured meeting notes — automatically.

Record on your iPhone, upload to the app, and Phonos transcribes the audio and generates a clean summary in seconds. Works with mixed-language recordings (English + Mandarin). Has a special Hedge Fund mode that understands finance slang like "up in the teens" and "vs the 300" — and gets smarter with every meeting you process.

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

Then open your browser and go to: **http://localhost:5001**

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

- **Standard** — general meeting notes with summary, action items, decisions, next steps
- **Hedge Fund** — structured allocator meeting note with sections for investment philosophy, team, AUM, portfolio construction, risk management, outlook, terms, and track record. Understands finance shorthand out of the box, and learns new terminology from each meeting you process (see "Dynamic Glossary" below)

### Auto-generated titles

Every memo automatically gets a short title extracted from the AI-generated notes — so you see "Edelweiss Q1 Review" in the sidebar instead of "20260329 230125-6587917D". You can also rename any memo manually by clicking the pencil icon.

### Chat with your notes

Switch to the **Chat with Notes** tab and ask anything across all your recordings — "What did the Edelweiss fund say about their drawdown?" or "What action items came out of last week's meetings?"

### Recurring meeting series

If you meet with the same fund or person regularly, link those memos together using **📅 Link to recurring meeting series**. Then hit **⚡ Compare meetings** to get an AI-generated "What Changed?" brief across all sessions.

### Playback

Click the **Transcript** tab on any memo to see the audio player and timestamped transcript. Click any timestamp to jump to that moment in the recording.

---

## Dynamic Glossary (Hedge Fund mode)

Every time you process a Hedge Fund memo, Phonos runs a second AI pass in the background to scan the transcript for new terminology — fund names, strategy names, proprietary signals, internal shorthand — anything not already in the standard glossary.

New terms are saved to a private database on your computer. From that point on, every future Hedge Fund memo is processed with that growing vocabulary injected into the prompt, so the AI understands your specific managers, strategies, and in-house language.

You never have to configure it. It builds itself as you use the app.

**Example:** If a manager refers to their "STAR signal" in a meeting, Phonos learns what that term means in context and applies it correctly in every future note for that manager.

---

## Editing the Hedge Fund prompt

The note format and rules for each note type live as plain text files in the `prompts/` folder:

```
prompts/
├── standard.txt      ← general meeting notes format
├── hedge_fund.txt    ← allocator-style meeting minutes
├── diff.txt          ← "What Changed?" comparison prompt
└── glossary_extract.txt  ← (internal) term extraction prompt
```

Open any of these in TextEdit or any text editor, make your changes, and save. The change takes effect the next time you process a memo — no code changes, no restart needed.

---

## iCloud auto-watch (optional)

If you have Voice Memos syncing to iCloud, Phonos can detect new recordings automatically and process them without any uploading.

To enable it, turn on iCloud sync on your iPhone:
**Settings → your name → iCloud → Voice Memos → toggle on**

Once synced, new recordings will appear in:
`~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings/`

Phonos watches this folder automatically when the app is running. The sidebar shows a green **"watching"** pill when it's active — hover over it to see which folder is being watched. New memos are picked up every 20 seconds, transcribed, and appear in the sidebar without you doing anything.

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

**iPhone recordings not showing up via iCloud watch**
Make sure iCloud Voice Memos sync is on (Settings → iCloud → Voice Memos). There can be a delay of a minute or two between recording on your phone and the file appearing on your Mac. Phonos checks every 20 seconds.

**Apple Notes toggle is missing**
Apple Notes integration only works on macOS. It won't appear on Windows or Linux.

**I forgot my password**
Open `.env` in a text editor and look for `APP_PASSWORD=`. If it's blank, there's no password. If it's set, that's your password.

**App won't start / "port already in use"**
The app runs on port 5001. If something else is using that port, open `.env` and add `PORT=5002` (or any other number), then restart.

---

## File structure (for the curious)

```
meeting-notes-tool/
├── voice_memos/           ← your audio files live here
├── memos.db               ← all transcripts, notes, and glossary stored here (SQLite)
├── .env                   ← your API keys (never share this file)
├── start.sh               ← the script you run to start the app
├── run.py                 ← app entry point
├── transcriber.py         ← Groq Whisper transcription
├── summarizer.py          ← DeepSeek note generation
├── glossary.py            ← dynamic terminology extraction and injection
├── prompts/               ← all AI prompt templates as plain text files
│   ├── standard.txt
│   ├── hedge_fund.txt
│   ├── diff.txt
│   └── glossary_extract.txt
├── prompts.py             ← loads prompts from the prompts/ folder
├── chat.py                ← Chat with Notes logic
├── apple_notes.py         ← Apple Notes integration (macOS only)
├── watcher.py             ← iCloud folder auto-watch
├── voice_memo_metadata.py ← display name extraction (backlog)
├── db.py                  ← database layer
└── routes.py              ← all API endpoints
```

---

## Deploying online (so anyone can access it from anywhere)

See `DEPLOY.md` for step-by-step instructions to deploy on Railway (free tier available). Once deployed, you get a public URL you can open on any device — phone, tablet, or another laptop.
