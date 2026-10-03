"""
AI-powered ATS Telegram bot — lightweight version.
Flow:
  1. Recruiter sends /newjob then pastes the job description as plain text.
  2. Recruiter sends /setmandatory and /setpreferred with comma-separated skills
     (or just relies on auto-extraction from the JD text — see extract_skills()).
  3. Recruiter uploads one or more resumes (PDF or DOCX).
  4. Bot scores each resume, gives suggestions + certification recommendations.
  5. Recruiter sends /rank to see all uploaded resumes ranked with % breakdown.
"""

import logging
import os
import re
import tempfile
from collections import defaultdict

import pdfplumber
import docx
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")")

# Weighted scoring model (mirrors the ideas in the Java spec, simplified)
WEIGHTS = {
    "mandatory_skills": 0.40,   # heaviest — must-haves
    "preferred_skills": 0.15,   # nice-to-haves
    "experience": 0.15,
    "education": 0.10,
    "certifications": 0.10,
    "projects": 0.10,
}

# Simple gap -> certification lookup table (extend as needed)
CERT_LOOKUP = {
    "aws": "AWS Certified Cloud Practitioner",
    "azure": "Microsoft Azure Fundamentals (AZ-900)",
    "gcp": "Google Associate Cloud Engineer",
    "docker": "Docker Certified Associate",
    "kubernetes": "Certified Kubernetes Administrator (CKA)",
    "python": "PCEP / PCAP Python Certification",
    "java": "Oracle Certified Associate Java Programmer",
    "sql": "Microsoft SQL Server Certification",
    "machine learning": "DeepLearning.AI Machine Learning Specialization",
    "react": "Meta Front-End Developer Certificate",
    "node.js": "OpenJS Node.js Application Developer",
    "devops": "AWS Certified DevOps Engineer",
    "ci/cd": "GitLab CI/CD Certification",
    "terraform": "HashiCorp Terraform Associate",
}

# Generic fallback suggestions used to top up the list to 3, when there aren't enough gap-based ones
GENERIC_SUGGESTIONS = [
    "Use strong action verbs (Built, Led, Designed) at the start of each bullet point",
    "Add measurable results to your achievements (e.g. 'reduced load time by 30%')",
    "Keep formatting simple and consistent — avoid tables/images that ATS systems can't parse",
    "Add a 2-3 line professional summary at the top tailored to this role",
    "Make sure your contact info (email, phone, LinkedIn) is clearly visible at the top",
    "Match the exact keywords from the job description wherever truthfully applicable",
]

# Generic fallback certifications used to top up the list to 3
GENERIC_CERTS = [
    "Google IT Support Professional Certificate",
    "Scrum Master Certification (CSM)",
    "Project Management Professional (PMP)",
]

EXPERIENCE_KEYWORDS = re.compile(r"(\d+)\+?\s*(?:years|yrs)", re.IGNORECASE)
EDUCATION_KEYWORDS = ["b.tech", "bachelor", "b.e", "m.tech", "master", "mba", "phd"]
PROJECT_SIGNALS = ["github.com", "project", "portfolio", "built a", "developed a", "deployed"]
RESUME_SIGNALS = [
    "experience", "education", "skills", "objective", "summary",
    "project", "certification", "contact", "@",  # email marker
]


def looks_like_a_resume(text: str) -> bool:
    """Heuristic check: does this text resemble a resume at all?"""
    lower = text.lower()
    hits = sum(1 for sig in RESUME_SIGNALS if sig in lower)
    has_email = bool(re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text))
    return hits >= 3 or has_email


def progress_bar(pct: float, length: int = 10) -> str:
    filled = round(pct / 100 * length)
    return "█" * filled + "░" * (length - filled)

# In-memory session store: { chat_id: {"jd_text":..., "mandatory":[...], "preferred":[...], "resumes": [...] } }
SESSIONS = defaultdict(lambda: {"jd_text": "", "mandatory": [], "preferred": [], "resumes": []})


# ------------------------------------------------------------------
# TEXT EXTRACTION
# ------------------------------------------------------------------
def extract_text_from_pdf(path: str) -> str:
    text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text.append(page_text)
    return "\n".join(text)


def extract_text_from_docx(path: str) -> str:
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs)


def extract_text(path: str) -> str:
    if path.lower().endswith(".pdf"):
        return extract_text_from_pdf(path)
    elif path.lower().endswith(".docx"):
        return extract_text_from_docx(path)
    else:
        raise ValueError("Unsupported file type. Please upload PDF or DOCX.")


# ------------------------------------------------------------------
# SCORING
# ------------------------------------------------------------------
def skill_present(text: str, skill: str) -> bool:
    return skill.lower().strip() in text.lower()


def score_resume(resume_text: str, mandatory: list, preferred: list) -> dict:
    resume_lower = resume_text.lower()

    # --- Skill matching ---
    mandatory_hits = [s for s in mandatory if skill_present(resume_lower, s)]
    mandatory_misses = [s for s in mandatory if s not in mandatory_hits]
    mandatory_score = (len(mandatory_hits) / len(mandatory) * 100) if mandatory else 100

    preferred_hits = [s for s in preferred if skill_present(resume_lower, s)]
    preferred_misses = [s for s in preferred if s not in preferred_hits]
    preferred_score = (len(preferred_hits) / len(preferred) * 100) if preferred else 100

    # --- Experience ---
    exp_matches = EXPERIENCE_KEYWORDS.findall(resume_text)
    years = max((int(x) for x in exp_matches), default=0)
    experience_score = min(years / 8 * 100, 100)  # cap: 8+ yrs = full score

    # --- Education ---
    education_score = 100 if any(k in resume_lower for k in EDUCATION_KEYWORDS) else 40

    # --- Certifications present in resume already ---
    certs_found = [c for c in CERT_LOOKUP.values() if c.lower() in resume_lower]
    certification_score = min(len(certs_found) * 50, 100)

    # --- Projects / portfolio signals ---
    project_hits = sum(1 for sig in PROJECT_SIGNALS if sig in resume_lower)
    projects_score = min(project_hits * 35, 100)

    total = (
        mandatory_score * WEIGHTS["mandatory_skills"]
        + preferred_score * WEIGHTS["preferred_skills"]
        + experience_score * WEIGHTS["experience"]
        + education_score * WEIGHTS["education"]
        + certification_score * WEIGHTS["certifications"]
        + projects_score * WEIGHTS["projects"]
    )

    # --- Suggestions ---
    suggestions = []
    if mandatory_misses:
        suggestions.append(f"Add these MANDATORY skills if you have them: {', '.join(mandatory_misses)}")
    if preferred_misses:
        suggestions.append(f"Consider adding preferred skills: {', '.join(preferred_misses)}")
    if experience_score < 60:
        suggestions.append("Quantify your years of experience clearly (e.g. '5+ years in...')")
    if education_score < 100:
        suggestions.append("Make sure your degree/qualification is clearly stated")
    if projects_score < 50:
        suggestions.append("Add a Projects section with links (e.g. GitHub) and a short description of what you built")

    # Top up to exactly 3 suggestions using generic tips (skip duplicates)
    for tip in GENERIC_SUGGESTIONS:
        if len(suggestions) >= 3:
            break
        if tip not in suggestions:
            suggestions.append(tip)
    suggestions = suggestions[:3]

    # --- Certification recommendations (based on gaps first) ---
    gap_skills = mandatory_misses + preferred_misses
    recommended_certs = []
    for skill in gap_skills:
        for key, cert in CERT_LOOKUP.items():
            if key in skill.lower() and cert not in recommended_certs:
                recommended_certs.append(cert)

    # If still short of 3, recommend advanced certs for skills the candidate already has
    if len(recommended_certs) < 3:
        held_skills = mandatory_hits + preferred_hits
        for skill in held_skills:
            if len(recommended_certs) >= 3:
                break
            for key, cert in CERT_LOOKUP.items():
                if key in skill.lower() and cert not in recommended_certs:
                    recommended_certs.append(cert)
                    break

    # Final top-up with generic, universally useful certs
    for cert in GENERIC_CERTS:
        if len(recommended_certs) >= 3:
            break
        if cert not in recommended_certs:
            recommended_certs.append(cert)

    recommended_certs = recommended_certs[:3]

    return {
        "total": round(total, 1),
        "breakdown": {
            "mandatory_skills": round(mandatory_score, 1),
            "preferred_skills": round(preferred_score, 1),
            "experience": round(experience_score, 1),
            "education": round(education_score, 1),
            "certifications": round(certification_score, 1),
            "projects": round(projects_score, 1),
        },
        "mandatory_hits": mandatory_hits,
        "mandatory_misses": mandatory_misses,
        "preferred_hits": preferred_hits,
        "preferred_misses": preferred_misses,
        "suggestions": suggestions,
        "recommended_certs": recommended_certs,
    }


def extract_skills(jd_text: str) -> list:
    """Very simple fallback: pull out capitalized/known tech words from JD text."""
    known = list(CERT_LOOKUP.keys()) + [
        "javascript", "typescript", "spring boot", "fastapi", "flask",
        "django", "postgresql", "mongodb", "redis", "git", "linux",
        "communication", "leadership", "agile", "scrum",
    ]
    found = [k for k in known if k in jd_text.lower()]
    return found


# ------------------------------------------------------------------
# TELEGRAM HANDLERS
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the ATS bot.\n\n"
        "1) /newjob — start a new job screening session\n"
        "2) Paste the job description as a normal message\n"
        "3) /setmandatory skill1, skill2, ... — set must-have skills\n"
        "4) /setpreferred skill1, skill2, ... — set nice-to-have skills\n"
        "5) Upload resumes (PDF/DOCX) — one or many\n"
        "6) /rank — see all resumes ranked\n"
        "7) /reset — clear the current session"
    )


async def newjob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SESSIONS[chat_id] = {"jd_text": "", "mandatory": [], "preferred": [], "resumes": []}
    await update.message.reply_text("New session started. Paste the job description now.")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    SESSIONS[chat_id] = {"jd_text": "", "mandatory": [], "preferred": [], "resumes": []}
    await update.message.reply_text("Session cleared.")


async def set_mandatory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    skills = " ".join(context.args).split(",")
    skills = [s.strip() for s in skills if s.strip()]
    SESSIONS[chat_id]["mandatory"] = skills
    await update.message.reply_text(f"Mandatory skills set: {', '.join(skills)}")


async def set_preferred(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    skills = " ".join(context.args).split(",")
    skills = [s.strip() for s in skills if s.strip()]
    SESSIONS[chat_id]["preferred"] = skills
    await update.message.reply_text(f"Preferred skills set: {', '.join(skills)}")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text

    # Treat any plain text message (that isn't a command) as the JD, if none set yet
    if not SESSIONS[chat_id]["jd_text"]:
        SESSIONS[chat_id]["jd_text"] = text
        auto_skills = extract_skills(text)
        if not SESSIONS[chat_id]["mandatory"]:
            SESSIONS[chat_id]["mandatory"] = auto_skills[:5]
        if not SESSIONS[chat_id]["preferred"]:
            SESSIONS[chat_id]["preferred"] = auto_skills[5:10]
        await update.message.reply_text(
            "✅ Job description received.\n\n"
            f"Auto-detected mandatory skills: {', '.join(SESSIONS[chat_id]['mandatory']) or 'none detected'}\n"
            f"Auto-detected preferred skills: {', '.join(SESSIONS[chat_id]['preferred']) or 'none detected'}\n\n"
            "You can override these with /setmandatory and /setpreferred.\n"
            "Now upload resumes (PDF/DOCX)."
        )
    else:
        await update.message.reply_text("JD already set for this session. Use /reset to start over.")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = SESSIONS[chat_id]

    if not session["jd_text"]:
        await update.message.reply_text("Please send the job description text first (or /newjob to start).")
        return

    doc = update.message.document
    file = await doc.get_file()
    local_path = os.path.join(tempfile.gettempdir(), f"{chat_id}_{doc.file_name}")
    await file.download_to_drive(local_path)

    try:
        resume_text = extract_text(local_path)
    except Exception as e:
        await update.message.reply_text(f"Couldn't read that file: {e}")
        return

    if not looks_like_a_resume(resume_text):
        await update.message.reply_text(
            "🔔 *Gentle reminder:* this file doesn't look like a resume — I couldn't find "
            "typical sections like Experience, Education, or Skills in it.\n\n"
            "Please upload the candidate's actual resume (PDF or DOCX) so I can score it correctly 🙂",
            parse_mode="Markdown",
        )
        return

    result = score_resume(resume_text, session["mandatory"], session["preferred"])
    session["resumes"].append({"name": doc.file_name, "result": result})

    b = result["breakdown"]
    total = result["total"]
    score_emoji = "🟢" if total >= 75 else "🟡" if total >= 50 else "🔴"

    msg = (
        f"📄 *{doc.file_name}*\n"
        f"{score_emoji} *Overall Score: {total}/100*\n"
        f"{progress_bar(total)}\n\n"
        f"*Breakdown*\n"
        f"Mandatory Skills   {progress_bar(b['mandatory_skills'], 8)}  {b['mandatory_skills']}%\n"
        f"Preferred Skills   {progress_bar(b['preferred_skills'], 8)}  {b['preferred_skills']}%\n"
        f"Experience         {progress_bar(b['experience'], 8)}  {b['experience']}%\n"
        f"Education          {progress_bar(b['education'], 8)}  {b['education']}%\n"
        f"Certifications     {progress_bar(b['certifications'], 8)}  {b['certifications']}%\n"
        f"Projects           {progress_bar(b['projects'], 8)}  {b['projects']}%\n"
    )
    if result["mandatory_misses"]:
        msg += f"\n⚠️ *Missing mandatory:* {', '.join(result['mandatory_misses'])}\n"
    if result["suggestions"]:
        msg += "\n💡 *Suggestions*\n" + "\n".join(f"• {s}" for s in result["suggestions"]) + "\n"
    if result["recommended_certs"]:
        msg += "\n🎓 *Recommended Certifications*\n" + "\n".join(f"• {c}" for c in result["recommended_certs"])

    await update.message.reply_text(msg, parse_mode="Markdown")


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    resumes = SESSIONS[chat_id]["resumes"]
    if not resumes:
        await update.message.reply_text("No resumes uploaded yet in this session.")
        return

    ranked = sorted(resumes, key=lambda r: r["result"]["total"], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 *Candidate Ranking*\n"]
    top_score = ranked[0]["result"]["total"]
    for i, r in enumerate(ranked, 1):
        gap = top_score - r["result"]["total"]
        gap_note = "" if i == 1 else f" _(−{gap:.1f} pts vs #1)_"
        marker = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{marker} {r['name']} — *{r['result']['total']}/100*{gap_note}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def main():
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newjob", newjob))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("setmandatory", set_mandatory))
    app.add_handler(CommandHandler("setpreferred", set_preferred))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    print("Bot running... (Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
