# Deploying to Railway

## What works in the cloud
- ✅ Upload audio → transcribe → generate notes
- ✅ Chat with all your notes
- ✅ Copy / download notes
- ❌ Apple Notes saving (AppleScript only runs on your Mac)
- ❌ Auto-sync from Voice Memos (local only)

---

## Step 1 — Push to GitHub

If you don't have a GitHub repo yet:

```bash
cd ~/Code/meeting-notes-tool
git init
git add .
git commit -m "Initial commit"
```

Then go to https://github.com/new, create a new **private** repo, and follow the instructions to push:

```bash
git remote add origin https://github.com/YOUR_USERNAME/meeting-notes-tool.git
git push -u origin main
```

---

## Step 2 — Create a Railway project

1. Go to **https://railway.app** and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `meeting-notes-tool` repo
4. Railway auto-detects the `Procfile` and starts building

---

## Step 3 — Add a Persistent Volume (important!)

Without this, your database and uploaded files reset every deploy.

1. In your Railway project, click your service
2. Go to **Volumes** tab → **Add Volume**
3. Set **Mount Path** to `/data`
4. Click **Create**

---

## Step 4 — Set Environment Variables

In Railway → your service → **Variables** tab, add:

| Variable | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key (starts with `gsk_`) |
| `OPENROUTER_API_KEY` | Your OpenRouter API key |
| `APP_PASSWORD` | A strong password of your choice |
| `SECRET_KEY` | Any long random string (e.g. run `openssl rand -hex 32` in Terminal) |
| `VOICE_MEMOS_DIR` | `/data/voice_memos` |
| `DB_PATH` | `/data/memos.db` |

---

## Step 5 — Deploy

Railway deploys automatically when you push to GitHub. After the build finishes:

1. Click **Settings → Networking → Generate Domain**
2. You'll get a URL like `https://meeting-notes-tool-xyz.up.railway.app`
3. Open it — you'll be prompted for your `APP_PASSWORD`

---

## Updating the app

Any `git push` to `main` triggers an automatic redeploy.

```bash
cd ~/Code/meeting-notes-tool
git add .
git commit -m "your change"
git push
```

---

## Cost

Railway gives **$5/month free credit**. A lightly-used Flask app typically costs ~$0.50–$1/month, well within the free tier.

---

## Notes

- **Apple Notes toggle**: The "Save to Apple Notes" option is hidden automatically when running in the cloud (it uses AppleScript which only works on your Mac).
- **ffmpeg**: Installed automatically via `nixpacks.toml` — large audio files will be compressed before transcription, just like locally.
- **Single worker**: The app uses 1 gunicorn worker (`--workers 1`) to avoid SQLite write conflicts.
