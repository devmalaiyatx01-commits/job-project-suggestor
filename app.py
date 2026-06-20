import streamlit as st
import httpx
import pdfplumber
import io
import os
import json
import re
import requests
from groq import Groq
from auth import register_user, login_user, get_security_question, reset_password, SECURITY_QUESTIONS
from database import (
    init_db, get_cached_jobs, save_jobs_to_cache,
    get_cached_suggestions, save_suggestions_to_cache,
    log_search, get_user_search_history,
    get_total_users, get_total_searches, get_top_searches
)
from embeddings import get_relevant_jobs
from evaluator import evaluate_suggestions

# Initialize database immediately when app starts
init_db()

# ── Secrets + API detection ───────────────────────────────────

def get_secret(key: str) -> str:
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

def is_api_running() -> bool:
    try:
        httpx.get("http://localhost:8000/", timeout=2)
        return True
    except Exception:
        return False

API_AVAILABLE = is_api_running()
API_URL = "http://localhost:8000"

# ── Direct functions (bypass FastAPI on Streamlit Cloud) ──────

def fetch_jobs_direct(query: str, location: str) -> list:
    all_jobs = []
    for page in range(1, 3):
        url = "https://jsearch.p.rapidapi.com/search"
        params = {
            "query": query,
            "location": location,
            "page": str(page),
            "num_pages": "1",
            "date_posted": "month"
        }
        headers = {
            "X-RapidAPI-Key": get_secret("RAPID_API_KEY"),
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com"
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                jobs = response.json().get("data", [])
                all_jobs.extend(jobs)
        except Exception:
            pass
    return all_jobs

def extract_job_info_direct(jobs: list) -> list:
    extracted = []
    for job in jobs[:20]:
        extracted.append({
            "title": job.get("job_title", ""),
            "company": job.get("employer_name", ""),
            "description": (job.get("job_description", "") or "")[:800],
            "skills": job.get("job_required_skills", []) or [],
            "link": job.get("job_apply_link") or job.get("job_url") or "",
            "location": job.get("job_city", "") or job.get("job_country", ""),
        })
    return extracted

def generate_suggestions_direct(query: str, jobs_info: list) -> str:
    client = Groq(api_key=get_secret("GROQ_API_KEY"))
    jobs_text = ""
    for i, job in enumerate(jobs_info, 1):
        skills = ", ".join(job["skills"]) if job.get("skills") else "not specified"
        jobs_text += f"\nJob {i}: {job['title']} at {job['company']}\nSkills: {skills}\nDescription: {job['description'][:400]}\n---"

    prompt = f"""I searched for "{query}" jobs and found these {len(jobs_info)} listings:
{jobs_text}

Analyze ALL listings. Suggest 6-8 specific portfolio projects. For each:
- **Project name** (concrete, not generic)
- **What it does** (1-2 sentences)
- **Key tech/skills it demonstrates**
- **Why it works for these roles**
- **Rough difficulty** (Weekend / 1 week / 2-3 weeks)

Be extremely specific. Every project must connect to skills seen in multiple job listings."""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.choices[0].message.content

def suggest_direct(query: str, location: str, username: str) -> dict:
    cached_suggestions, cached_scores = get_cached_suggestions(query)
    cached_jobs = get_cached_jobs(query, location) or []

    if cached_suggestions and cached_scores:
        log_search(username, query, location, len(cached_jobs))
        return {
            "query": query,
            "job_count": len(cached_jobs),
            "jobs_analyzed": [{
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "link": j.get("link", ""),
                "location": j.get("location", "")
            } for j in cached_jobs[:15]],
            "suggestions": cached_suggestions,
            "scores": cached_scores,
            "from_cache": True
        }

    jobs = get_cached_jobs(query, location)
    if not jobs:
        raw_jobs = fetch_jobs_direct(query, location)
        if not raw_jobs:
            return None
        jobs = extract_job_info_direct(raw_jobs)
        save_jobs_to_cache(query, location, jobs)

    log_search(username, query, location, len(jobs))
    relevant_jobs = get_relevant_jobs(query, jobs, top_k=10)
    suggestions = generate_suggestions_direct(query, relevant_jobs)
    scores = evaluate_suggestions(suggestions, query)
    save_suggestions_to_cache(query, suggestions, scores)

    return {
        "query": query,
        "job_count": len(jobs),
        "jobs_analyzed": [{
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "link": j.get("link", ""),
            "location": j.get("location", "")
        } for j in jobs[:15]],
        "suggestions": suggestions,
        "scores": scores,
        "from_cache": False
    }

def analyze_resume_direct(resume_text: str, query: str, location: str) -> dict:
    jobs = get_cached_jobs(query, location)
    if not jobs:
        raw_jobs = fetch_jobs_direct(query, location)
        if not raw_jobs:
            return None
        jobs = extract_job_info_direct(raw_jobs)
        save_jobs_to_cache(query, location, jobs)

    job_summaries = ""
    for i, job in enumerate(jobs[:10], 1):
        job_summaries += f"Job {i} ({job['title']} at {job['company']}): {job['description'][:300]}\n---\n"

    client = Groq(api_key=get_secret("GROQ_API_KEY"))
    prompt = f"""You are an expert ATS analyst and career coach.

TARGET ROLE: {query}

REAL JOB LISTINGS:
{job_summaries}

CANDIDATE RESUME:
{resume_text[:3000]}

Respond ONLY with valid JSON, no markdown, no backticks:
{{
  "ats_score": <0-100>,
  "fit_score": <0-100>,
  "keyword_analysis": {{
    "present": ["<keyword>"],
    "missing": ["<keyword>"]
  }},
  "strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "gaps": ["<gap 1>", "<gap 2>", "<gap 3>"],
  "ats_formatting_tips": ["<tip 1>", "<tip 2>", "<tip 3>"],
  "quick_wins": ["<win 1>", "<win 2>", "<win 3>"],
  "overall_verdict": "<2-3 sentence honest assessment>"
}}"""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json|```", "", message.choices[0].message.content.strip()).strip()
    try:
        return json.loads(raw)
    except Exception:
        return {
            "ats_score": 0, "fit_score": 0,
            "keyword_analysis": {"present": [], "missing": []},
            "strengths": [], "gaps": [],
            "ats_formatting_tips": [], "quick_wins": [],
            "overall_verdict": raw
        }

def roadmap_direct(resume_text: str, query: str) -> dict:
    client = Groq(api_key=get_secret("GROQ_API_KEY"))
    prompt = f"""You are a senior career coach for tech roles in India.

TARGET ROLE: {query}
RESUME: {resume_text[:3000]}

Create a 6-month personalized roadmap. Respond ONLY with valid JSON, no markdown, no backticks:
{{
  "current_level": "<honest assessment of where they are>",
  "target_outcome": "<what they achieve in 6 months>",
  "months": [
    {{
      "month": 1,
      "title": "<theme for this month>",
      "focus": "<what to learn or build and why>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{
          "name": "<resource name>",
          "url": "<real working url>",
          "type": "<Course / YouTube / Platform / Book>",
          "cost": "Free",
          "why": "<why this resource for this candidate>"
        }}
      ],
      "milestone": "<what they have to show at end of month>"
    }},
    {{
      "month": 2,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [{{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}],
      "milestone": "<milestone>"
    }},
    {{
      "month": 3,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [{{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}],
      "milestone": "<milestone>"
    }},
    {{
      "month": 4,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [{{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}],
      "milestone": "<milestone>"
    }},
    {{
      "month": 5,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [{{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}],
      "milestone": "<milestone>"
    }},
    {{
      "month": 6,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [{{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}],
      "milestone": "<milestone>"
    }}
  ],
  "interview_prep": {{
    "topics": ["<topic 1>", "<topic 2>", "<topic 3>", "<topic 4>", "<topic 5>"],
    "resources": [
      {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free"}},
      {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free"}}
    ]
  }},
  "final_checklist": ["<item 1>", "<item 2>", "<item 3>", "<item 4>", "<item 5>"]
}}

Use REAL specific free resource URLs like cs50p.harvard.edu, fast.ai, kaggle.com/learn, neetcode.io, stratascratch.com, mode.com/sql-tutorial, statquest.org. Include all 6 months."""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = re.sub(r"```json|```", "", message.choices[0].message.content.strip()).strip()
    try:
        return json.loads(raw)
    except Exception:
        return None

def fetch_stats():
    if API_AVAILABLE:
        try:
            resp = httpx.get(f"{API_URL}/stats", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
    return {
        "total_users": get_total_users(),
        "total_searches": get_total_searches(),
        "top_searches": [{"query": r[0], "count": r[1]} for r in get_top_searches(5)]
    }

def extract_text_from_pdf(file_bytes: bytes) -> str:
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass
    return text.strip()

def score_label(score: int) -> str:
    if score >= 75:
        return "Strong ✅"
    elif score >= 50:
        return "Moderate ⚠️"
    else:
        return "Needs Work ❌"

# ── Page config ───────────────────────────────────────────────

st.set_page_config(
    page_title="Job Project Suggester",
    page_icon="🎯",
    layout="wide"
)

# ── Session state ─────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""

# ── Header ────────────────────────────────────────────────────
stats = fetch_stats()

st.title("🎯 Job-to-Project Suggester")

col_u, col_s, col_gap = st.columns([1, 1, 2])
col_u.metric("👥 Total Users", stats["total_users"])
col_s.metric("🔍 Total Searches", stats["total_searches"])

st.markdown("*Search any job role → get real listings with apply links → AI tells you what to build, scores your resume, and gives you a 6-month plan*")
st.markdown("---")

# ── Auth flow ─────────────────────────────────────────────────
if not st.session_state.logged_in:
    st.markdown("### Please log in or create an account to continue")

    tab_login, tab_register, tab_forgot = st.tabs([
        "🔑 Log In", "✏️ Create Account", "🔓 Forgot Password"
    ])

    with tab_login:
        st.markdown("#### Welcome back")
        login_username = st.text_input("Username", key="login_username")
        login_password = st.text_input("Password", type="password", key="login_password")

        if st.button("Log In", type="primary"):
            if login_username and login_password:
                success, result = login_user(login_username, login_password)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = result
                    st.success(f"Welcome back, {result}!")
                    st.rerun()
                else:
                    st.error(result)
            else:
                st.warning("Please enter both username and password")

    with tab_register:
        st.markdown("#### Create your free account")
        st.caption("Username: 3-20 characters, letters/numbers/underscores/hyphens only")

        reg_username = st.text_input("Choose a username", key="reg_username")
        reg_password = st.text_input("Choose a password", type="password", key="reg_password",
                                      help="At least 6 characters")
        reg_password2 = st.text_input("Confirm password", type="password", key="reg_password2")

        st.markdown("**Security question** (used if you forget your password)")
        security_q = st.selectbox("Choose a question", SECURITY_QUESTIONS, key="security_q")
        security_a = st.text_input("Your answer", key="security_a",
                                    help="Remember this — you will need it to reset your password")

        if st.button("Create Account", type="primary"):
            if not reg_username or not reg_password or not security_a:
                st.warning("Please fill in all fields")
            elif reg_password != reg_password2:
                st.error("Passwords do not match")
            else:
                success, message = register_user(reg_username, reg_password, security_q, security_a)
                if success:
                    st.session_state.logged_in = True
                    st.session_state.username = reg_username.lower().strip()
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

    with tab_forgot:
        st.markdown("#### Reset your password")
        forgot_username = st.text_input("Your username", key="forgot_username")

        if st.button("Find My Account"):
            if forgot_username:
                found, question = get_security_question(forgot_username)
                if found:
                    st.session_state.reset_question = question
                    st.session_state.reset_username = forgot_username.strip().lower()
                    st.rerun()
                else:
                    st.error(question)
            else:
                st.warning("Please enter your username")

        if st.session_state.get("reset_question"):
            st.markdown(f"**Security question:** {st.session_state.reset_question}")
            reset_answer = st.text_input("Your answer", key="reset_answer")
            new_password = st.text_input("New password", type="password", key="new_password")
            new_password2 = st.text_input("Confirm new password", type="password", key="new_password2")

            if st.button("Reset Password", type="primary"):
                if not reset_answer or not new_password:
                    st.warning("Please fill in all fields")
                elif new_password != new_password2:
                    st.error("Passwords do not match")
                else:
                    success, message = reset_password(
                        st.session_state.reset_username, reset_answer, new_password
                    )
                    if success:
                        st.success(message)
                        del st.session_state.reset_question
                        del st.session_state.reset_username
                    else:
                        st.error(message)

    top = stats.get("top_searches", [])
    if top:
        st.markdown("---")
        st.markdown("### 🔥 Most Searched Roles")
        for item in top:
            st.markdown(f"- **{item['query']}** — searched {item['count']} times")

# ── Main tool (logged in) ─────────────────────────────────────
else:
    # ── Sidebar ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown(f"### 👤 {st.session_state.username}")

        if st.button("🚪 Log Out"):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.resume_text = ""
            st.rerun()

        st.markdown("---")
        st.markdown("### 🕐 Your Search History")
        try:
            rows = get_user_search_history(st.session_state.username)
            if rows:
                for r in rows:
                    st.markdown(f"**{r[0]}** — {r[2]} jobs")
            else:
                st.markdown("*No searches yet*")
        except Exception:
            st.markdown("*Could not load history*")

        st.markdown("---")
        if st.button("🗑️ Clear Job Cache"):
            try:
                import sqlite3
                conn = sqlite3.connect("jobs_cache.db")
                conn.execute("DELETE FROM job_cache")
                conn.execute("DELETE FROM suggestion_cache")
                conn.commit()
                conn.close()
                st.success("Cache cleared!")
            except Exception as e:
                st.error(f"Error: {e}")

        st.markdown("---")
        st.markdown("### 📊 Platform Stats")
        st.markdown(f"👥 **{stats['total_users']}** registered users")
        st.markdown(f"🔍 **{stats['total_searches']}** searches run")
        top = stats.get("top_searches", [])
        if top:
            st.markdown("**🔥 Top Searches:**")
            for item in top:
                st.markdown(f"- {item['query']} ({item['count']}x)")

    # ── Resume upload panel ───────────────────────────────────
    st.markdown(f"Welcome, **{st.session_state.username}**!")

    with st.expander("📄 Upload Your Resume (used across all features)", expanded=not st.session_state.resume_text):
        st.caption("Upload once — your resume will be used for ATS analysis and roadmap generation")

        upload_method = st.radio(
            "How do you want to add your resume?",
            ["Upload PDF", "Paste as text"],
            horizontal=True
        )

        if upload_method == "Upload PDF":
            uploaded_file = st.file_uploader("Upload your resume PDF", type=["pdf"])
            if uploaded_file:
                file_bytes = uploaded_file.read()
                extracted = extract_text_from_pdf(file_bytes)
                if extracted:
                    st.session_state.resume_text = extracted
                    st.success(f"✅ Resume extracted — {len(extracted)} characters read")
                    with st.expander("Preview extracted text"):
                        st.text(extracted[:1000] + "..." if len(extracted) > 1000 else extracted)
                else:
                    st.error("Could not extract text from this PDF. Try the paste option instead.")
        else:
            pasted = st.text_area(
                "Paste your resume text here",
                height=200,
                placeholder="Paste your full resume content...",
                value=st.session_state.resume_text
            )
            if st.button("Save Resume"):
                if pasted and len(pasted.strip()) > 50:
                    st.session_state.resume_text = pasted.strip()
                    st.success("✅ Resume saved")
                else:
                    st.warning("Resume text is too short")

        if st.session_state.resume_text:
            st.info(f"✅ Resume loaded ({len(st.session_state.resume_text)} characters) — ready to use below")

    st.markdown("---")

    # ── Main tabs ─────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "🔍 Find Projects",
        "📊 Resume & ATS Analysis",
        "🗺️ 6-Month Roadmap"
    ])

    # ── TAB 1: Find Projects ──────────────────────────────────
    with tab1:
        st.markdown("### Find projects to build for your target role")

        col1, col2 = st.columns([2, 1])
        with col1:
            query = st.text_input(
                "Job title to search",
                placeholder="e.g. Data Analyst, ML Engineer, SDE, Product Manager",
                key="query_tab1"
            )
        with col2:
            location = st.text_input("Location", value="India", key="loc_tab1")

        if st.button("🔍 Find Projects to Build", type="primary", disabled=not query, key="btn_tab1"):
            with st.spinner("Fetching jobs and running AI analysis... (first search ~30 seconds)"):
                try:
                    if API_AVAILABLE:
                        response = httpx.post(
                            f"{API_URL}/suggest",
                            json={"query": query, "location": location, "username": st.session_state.username},
                            timeout=120
                        )
                        data = response.json() if response.status_code == 200 else None
                        if response.status_code != 200:
                            st.error(f"Error: {response.text}")
                    else:
                        data = suggest_direct(query, location, st.session_state.username)

                    if data:
                        if data.get("from_cache"):
                            st.info("⚡ Loaded from cache — instant!")
                        else:
                            st.success(f"✅ Analyzed {data['job_count']} live listings for **{query}**")

                        st.markdown("---")
                        st.markdown("## 📋 Jobs Found — Apply Directly")
                        for job in data.get("jobs_analyzed", []):
                            col_info, col_btn = st.columns([4, 1])
                            with col_info:
                                loc_text = f" · 📍 {job.get('location','')}" if job.get("location") else ""
                                st.markdown(f"**{job.get('title','?')}** at {job.get('company','?')}{loc_text}")
                            with col_btn:
                                if job.get("link"):
                                    st.markdown(f"[🔗 Apply]({job['link']})")
                                else:
                                    st.markdown("*No link*")

                        st.markdown("---")
                        st.markdown("## 🚀 Projects to Build for Your Resume")
                        st.markdown(data["suggestions"])

                        scores = data.get("scores", [])
                        if scores:
                            st.markdown("---")
                            st.markdown("## 📊 AI Evaluation of Each Project")
                            st.caption("Scored by a second AI on relevance, specificity, and difficulty")
                            for score in scores:
                                name = score.get("project_name", "Project")
                                overall = score.get("overall", "?")
                                with st.expander(f"**{name}** — Overall: {overall}/10"):
                                    c1, c2, c3 = st.columns(3)
                                    c1.metric("Relevance", f"{score.get('relevance_score','?')}/10")
                                    c2.metric("Specificity", f"{score.get('specificity_score','?')}/10")
                                    c3.metric("Difficulty Fit", f"{score.get('difficulty_calibration','?')}/10")
                                    st.markdown(f"**Verdict:** {score.get('one_line_verdict','')}")

                        st.download_button(
                            "📥 Download suggestions as .txt",
                            data=data["suggestions"],
                            file_name=f"projects_for_{query.replace(' ','_')}.txt",
                            mime="text/plain"
                        )
                    else:
                        st.error("No jobs found. Try a different role or location.")

                except Exception as e:
                    st.error(f"Something went wrong: {str(e)}")

    # ── TAB 2: Resume & ATS Analysis ─────────────────────────
    with tab2:
        st.markdown("### How does your resume score against real job listings?")

        if not st.session_state.resume_text:
            st.warning("⬆️ Please upload or paste your resume using the panel above first")
        else:
            col1, col2 = st.columns([2, 1])
            with col1:
                ats_query = st.text_input(
                    "Target role to analyze against",
                    placeholder="e.g. Data Analyst, ML Engineer, SDE",
                    key="query_tab2"
                )
            with col2:
                ats_location = st.text_input("Location", value="India", key="loc_tab2")

            if st.button("📊 Analyze My Resume", type="primary", disabled=not ats_query, key="btn_tab2"):
                with st.spinner("Fetching job listings and analyzing your resume... (~20 seconds)"):
                    try:
                        if API_AVAILABLE:
                            response = httpx.post(
                                f"{API_URL}/analyze-resume",
                                json={
                                    "resume_text": st.session_state.resume_text,
                                    "query": ats_query,
                                    "location": ats_location,
                                    "username": st.session_state.username
                                },
                                timeout=120
                            )
                            data = response.json() if response.status_code == 200 else None
                        else:
                            data = analyze_resume_direct(
                                st.session_state.resume_text, ats_query, ats_location
                            )

                        if data:
                            ats = data.get("ats_score", 0)
                            fit = data.get("fit_score", 0)

                            st.markdown("---")
                            st.markdown("## 🎯 Your Scores")
                            col_ats, col_fit, _ = st.columns([1, 1, 2])
                            with col_ats:
                                st.metric("ATS Score", f"{ats}/100", delta=score_label(ats))
                                st.progress(ats / 100)
                            with col_fit:
                                st.metric("Job Fit Score", f"{fit}/100", delta=score_label(fit))
                                st.progress(fit / 100)

                            st.markdown("---")
                            st.markdown("### 💬 Overall Assessment")
                            st.info(data.get("overall_verdict", ""))

                            st.markdown("---")
                            st.markdown("### 🔑 Keyword Analysis")
                            kw = data.get("keyword_analysis", {})
                            col_p, col_m = st.columns(2)
                            with col_p:
                                st.markdown("**✅ Keywords you have:**")
                                for k in kw.get("present", []):
                                    st.markdown(f"- {k}")
                            with col_m:
                                st.markdown("**❌ Keywords missing:**")
                                for k in kw.get("missing", []):
                                    st.markdown(f"- {k}")

                            st.markdown("---")
                            col_str, col_gap2 = st.columns(2)
                            with col_str:
                                st.markdown("### 💪 Your Strengths")
                                for s in data.get("strengths", []):
                                    st.success(s)
                            with col_gap2:
                                st.markdown("### 🔧 Gaps to Address")
                                for g in data.get("gaps", []):
                                    st.error(g)

                            st.markdown("---")
                            st.markdown("### 📝 ATS Formatting Tips")
                            for tip in data.get("ats_formatting_tips", []):
                                st.warning(tip)

                            st.markdown("---")
                            st.markdown("### ⚡ Quick Wins — Do These This Week")
                            for i, win in enumerate(data.get("quick_wins", []), 1):
                                st.markdown(f"**{i}.** {win}")
                        else:
                            st.error("No jobs found for this role. Try a different title.")

                    except Exception as e:
                        st.error(f"Something went wrong: {str(e)}")

    # ── TAB 3: 6-Month Roadmap ────────────────────────────────
    with tab3:
        st.markdown("### Your personalized 6-month plan to land your target role")

        if not st.session_state.resume_text:
            st.warning("⬆️ Please upload or paste your resume using the panel above first")
        else:
            roadmap_query = st.text_input(
                "Target role for your roadmap",
                placeholder="e.g. Data Analyst, ML Engineer, SDE, Product Manager",
                key="query_tab3"
            )

            if st.button("🗺️ Generate My 6-Month Roadmap", type="primary",
                         disabled=not roadmap_query, key="btn_tab3"):
                with st.spinner("Building your personalized roadmap... (~30 seconds)"):
                    try:
                        if API_AVAILABLE:
                            response = httpx.post(
                                f"{API_URL}/roadmap",
                                json={
                                    "resume_text": st.session_state.resume_text,
                                    "query": roadmap_query,
                                    "username": st.session_state.username
                                },
                                timeout=120
                            )
                            data = response.json() if response.status_code == 200 else None
                        else:
                            data = roadmap_direct(st.session_state.resume_text, roadmap_query)

                        if data:
                            col_now, col_then = st.columns(2)
                            with col_now:
                                st.markdown("### 📍 Where You Are Now")
                                st.info(data.get("current_level", ""))
                            with col_then:
                                st.markdown("### 🎯 Where You'll Be in 6 Months")
                                st.success(data.get("target_outcome", ""))

                            st.markdown("---")
                            st.markdown("## 📅 Month-by-Month Plan")

                            for m in data.get("months", []):
                                with st.expander(
                                    f"**Month {m.get('month')}: {m.get('title')}** — {m.get('weekly_hours')}hrs/week",
                                    expanded=(m.get("month") == 1)
                                ):
                                    st.markdown(f"**🎯 Focus:** {m.get('focus')}")
                                    st.markdown(f"**⏱️ Time commitment:** {m.get('weekly_hours')} hours/week")

                                    st.markdown("**📌 Goals this month:**")
                                    for g in m.get("goals", []):
                                        st.markdown(f"- {g}")

                                    st.markdown("**📚 Resources:**")
                                    for r in m.get("resources", []):
                                        col_r, col_t = st.columns([3, 1])
                                        with col_r:
                                            if r.get("url"):
                                                st.markdown(f"🔗 [{r.get('name')}]({r.get('url')})")
                                            else:
                                                st.markdown(f"📖 {r.get('name')}")
                                            if r.get("why"):
                                                st.caption(r.get("why"))
                                        with col_t:
                                            st.caption(f"{r.get('type','Resource')} · {r.get('cost','Free')}")

                                    st.markdown("---")
                                    st.success(f"🏁 **End of month milestone:** {m.get('milestone')}")

                            interview = data.get("interview_prep", {})
                            if interview:
                                st.markdown("---")
                                st.markdown("## 🎤 Interview Preparation")
                                topics = interview.get("topics", [])
                                if topics:
                                    st.markdown("**Topics to master:**")
                                    for topic in topics:
                                        st.markdown(f"- {topic}")
                                for r in interview.get("resources", []):
                                    if r.get("url"):
                                        st.markdown(f"🔗 [{r.get('name')}]({r.get('url')})")
                                    else:
                                        st.markdown(f"📖 {r.get('name')}")

                            checklist = data.get("final_checklist", [])
                            if checklist:
                                st.markdown("---")
                                st.markdown("## ✅ Before You Apply — Final Checklist")
                                for item in checklist:
                                    st.checkbox(item, key=f"chk_{item[:30]}")

                            # Build downloadable roadmap text
                            roadmap_text = f"6-MONTH ROADMAP FOR: {roadmap_query}\n\n"
                            roadmap_text += f"Current Level: {data.get('current_level','')}\n"
                            roadmap_text += f"Target: {data.get('target_outcome','')}\n\n"
                            for m in data.get("months", []):
                                roadmap_text += f"\nMONTH {m.get('month')}: {m.get('title')}\n"
                                roadmap_text += f"Focus: {m.get('focus')}\n"
                                roadmap_text += f"Hours/week: {m.get('weekly_hours')}\n"
                                roadmap_text += "Goals:\n"
                                for g in m.get("goals", []):
                                    roadmap_text += f"  - {g}\n"
                                roadmap_text += "Resources:\n"
                                for r in m.get("resources", []):
                                    roadmap_text += f"  - {r.get('name')} ({r.get('url','no url')})\n"
                                roadmap_text += f"Milestone: {m.get('milestone')}\n"

                            st.download_button(
                                "📥 Download Roadmap as .txt",
                                data=roadmap_text,
                                file_name=f"roadmap_{roadmap_query.replace(' ','_')}.txt",
                                mime="text/plain"
                            )
                        else:
                            st.error("Could not generate roadmap. Try again.")

                    except Exception as e:
                        st.error(f"Something went wrong: {str(e)}")