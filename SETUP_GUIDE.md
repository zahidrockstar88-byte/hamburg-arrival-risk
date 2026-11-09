# Setup guide (Mac, first time using Python)

Follow the steps in order. Copy each grey command, paste it in the terminal, and press Enter.
Total time: about 20 minutes.

---

## Step 1: Put the project folder somewhere easy

1. Unzip `hamburg-arrival-risk.zip` (double-click it in Finder).
2. Move the folder `hamburg-arrival-risk` into your `claude code` folder (in your home folder).

## Step 2: Open it in VS Code

1. Open VS Code.
2. **File → Open Folder…** → choose `hamburg-arrival-risk` → **Open**.
3. If VS Code asks "Do you trust the authors?", click **Yes**.
4. Open the terminal: menu **Terminal → New Terminal**. A panel opens at the bottom.
   This is where you type commands.

## Step 3: Create a private Python space for the project

This keeps the project's tools separate from the rest of your Mac.

```bash
python3 -m venv .venv
```

Then switch it on:

```bash
source .venv/bin/activate
```

You now see `(.venv)` at the start of the terminal line. **Run this `source` command again every time you
open a new terminal for this project.**

## Step 4: Install the tools the project needs

```bash
pip install -r requirements.txt
```

Wait until it finishes (1–3 minutes). Warnings in yellow are normal.

## Step 5: Check everything works

```bash
python -m pytest
```

You should see `6 passed`. If you see `failed`, copy the red text and ask Claude Code.

## Step 6: Open the dashboard with demo data

```bash
streamlit run app.py
```

Your browser opens the dashboard. It shows 10 **invented** demo ships, so you can see every flag.
To stop the dashboard: click in the terminal and press **Control + C**.

> The first time, Streamlit may ask for your email. Just press Enter to skip.

## Step 7: Get your free live-data key

1. Go to https://aisstream.io and sign up (you can use your GitHub or Google account).
2. Find **API Keys** and create a key. Copy it.
3. In VS Code, find the file `.env.example` in the left panel. Right-click → **Copy**, then right-click the
   folder → **Paste**. Rename the copy to exactly `.env`
   *(or run `cp .env.example .env` in the terminal)*.
4. Open `.env` and replace `paste_your_key_here` with your key. Save (**Cmd + S**).

Your key stays only on your Mac. The `.gitignore` file makes sure it is never uploaded to GitHub.

## Step 8: Collect live data

```bash
python collector.py --minutes 15
```

Leave it running. Every minute it prints how many ships it has found heading to Hamburg.
After 15 minutes it saves `data/ships.json` and stops.

Then start the dashboard again:

```bash
streamlit run app.py
```

In the sidebar, choose **Live data**.

**Tip:** run the collector a few times a day. Data builds up between runs.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| `command not found: python3` | Install Python from python.org, then close and reopen VS Code |
| `No module named streamlit` | You forgot `source .venv/bin/activate`. Run it, then try again |
| `No API key found` | Check the file is named exactly `.env` (with the dot) and saved |
| `AISStream refused the connection` | The key is wrong or has a space. Copy it again |
| 0 ships heading to Hamburg | Run longer: ships send their destination only every ~6 minutes |
| Map has no background | Check your internet connection. The ship dots still work |

For anything else: open Claude Code in this folder and paste the error. It has read `CLAUDE.md`
and knows the whole project.

---

## Later: put it online (for your CV)

1. Create a free account at https://github.com and a new **public** repository called `hamburg-arrival-risk`.
2. Ask Claude Code: *"Help me upload this project to my GitHub repository, step by step."*
3. Go to https://share.streamlit.io, sign in with GitHub, click **Create app**, pick the repository and `app.py`.
4. You get a public link to paste into your CV and LinkedIn.
5. Optional: to keep the online data fresh, add your key as a GitHub secret named `AISSTREAM_API_KEY`
   (repository → Settings → Secrets and variables → Actions). The file `.github/workflows/collect.yml`
   then collects new data every 3 hours, for free.
