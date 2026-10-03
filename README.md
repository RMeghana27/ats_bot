# AI-Powered ATS Chatbot (Telegram)

A conversational Applicant Tracking System (ATS) built as a **chatbot** instead of a traditional web dashboard — recruiters interact with it entirely through Telegram.

## Problem Statement
Build a chat application that:
- Accepts a resume upload and returns an ATS score based on defined parameters
- Gives improvement suggestions
- Recommends relevant certification courses based on skill gaps
- Supports multiple resume uploads and ranks candidates, showing the score/percentage difference between them

## Features
- 💬 Fully conversational — no web UI, works through a Telegram bot
- 📄 Parses PDF and DOCX resumes
- 🎯 Weighted ATS scoring across 6 parameters:
  - Mandatory skills match (40%)
  - Preferred skills match (15%)
  - Experience (15%)
  - Education (10%)
  - Certifications already held (10%)
  - Projects / portfolio signals (10%)
- 💡 Personalized improvement suggestions based on score gaps
- 🎓 Certification recommendations mapped to missing skills
- 🏆 Multi-resume ranking with point-gap comparison
- 🤔 Rejects non-resume documents with a gentle reminder instead of scoring garbage

## Tech Stack
- Python 3
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) — Telegram Bot API wrapper
- [pdfplumber](https://github.com/jsvine/pdfplumber) — PDF text extraction
- [python-docx](https://github.com/python-openxml/python-docx) — DOCX text extraction

## How It Works
```
Recruiter (Telegram)
   │
   ├── /newjob → paste Job Description
   │        └── Bot auto-detects mandatory & preferred skills
   │            (or set manually with /setmandatory, /setpreferred)
   │
   ├── Upload resume(s) (PDF/DOCX)
   │        └── Bot checks it's actually a resume
   │        └── Scores it against the JD (weighted parameters)
   │        └── Returns score breakdown + suggestions + certifications
   │
   └── /rank → see all uploaded resumes sorted by score,
                with the point gap to #1 shown
```

## Setup & Run

1. **Create a Telegram bot**
   - Message [@BotFather](https://t.me/BotFather) on Telegram
   - Send `/newbot`, follow the prompts, and copy the API token it gives you

2. **Clone this repo and install dependencies**
   ```bash
   git clone <your-repo-url>
   cd ats_bot
   pip install -r requirements.txt
   ```

3. **Set your bot token as an environment variable**
   ```bash
   # Windows (Command Prompt)
   set TELEGRAM_BOT_TOKEN=your_token_here

   # Mac/Linux
   export TELEGRAM_BOT_TOKEN=your_token_here
   ```

4. **Run the bot**
   ```bash
   python bot.py
   ```

5. **Chat with it on Telegram**
   - Send `/start` to see the command menu
   - `/newjob` → paste a job description
   - Upload resume(s)
   - `/rank` to compare them

## Sample Data
The `sample_resumes/` folder contains 3 test resumes designed to produce clearly different scores (strong/medium/weak match) for demoing the ranking feature.

## Commands
| Command | Description |
|---|---|
| `/start` | Show the welcome menu |
| `/newjob` | Start a new screening session |
| `/setmandatory skill1, skill2, ...` | Manually set must-have skills |
| `/setpreferred skill1, skill2, ...` | Manually set nice-to-have skills |
| `/rank` | Show all uploaded resumes ranked by score |
| `/reset` | Clear the current session |

## Future Improvements
- Semantic skill matching using embeddings instead of exact keyword matching
- Persistent storage (database) instead of in-memory sessions
- Support for additional chat platforms (Slack, Discord)

## Author
Built by Meghana as part of a college placement-training assignment.
