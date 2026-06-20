from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
import requests
import os
import json
import re
from dotenv import load_dotenv

from database import (
    init_db, get_cached_jobs, save_jobs_to_cache,
    get_cached_suggestions, save_suggestions_to_cache,
    log_search, get_user_search_history,
    get_total_users, get_total_searches, get_top_searches
)
from embeddings import get_relevant_jobs
from evaluator import evaluate_suggestions

load_dotenv()
init_db()

app = FastAPI(
    title="Job Project Suggester API",
    description="Scrapes real jobs, analyzes resumes, and builds career roadmaps",
    version="4.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    location: str = "India"
    username: str = "anonymous"

class SuggestionResponse(BaseModel):
    query: str
    job_count: int
    jobs_analyzed: list
    suggestions: str
    scores: list
    from_cache: bool

class ResumeAnalysisRequest(BaseModel):
    resume_text: str
    query: str
    location: str = "India"
    username: str = "anonymous"

class RoadmapRequest(BaseModel):
    resume_text: str
    query: str
    username: str = "anonymous"

# ── Helpers ───────────────────────────────────────────────────

def get_secret(key: str) -> str:
    try:
        import streamlit as st
        return st.secrets[key]
    except Exception:
        return os.getenv(key)

def get_groq_client():
    return Groq(api_key=get_secret("GROQ_API_KEY"))

def fetch_jobs_from_api(query: str, location: str) -> list:
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
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            jobs = response.json().get("data", [])
            all_jobs.extend(jobs)
    return all_jobs

def extract_job_info(jobs: list) -> list:
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

def generate_suggestions(query: str, jobs_info: list) -> str:
    client = get_groq_client()
    jobs_text = ""
    for i, job in enumerate(jobs_info, 1):
        skills = ", ".join(job["skills"]) if job.get("skills") else "not specified"
        jobs_text += f"""
Job {i}: {job['title']} at {job['company']}
Skills required: {skills}
Description: {job['description'][:400]}
---"""

    prompt = f"""I searched for "{query}" jobs and found these {len(jobs_info)} listings:

{jobs_text}

Analyze ALL listings. Suggest 6-8 specific portfolio projects. For each:
- **Project name** (concrete, not generic)
- **What it does** (1-2 sentences)
- **Key tech/skills it demonstrates**
- **Why it works for these roles** (connect to patterns you saw in the JDs)
- **Rough difficulty** (Weekend / 1 week / 2-3 weeks)

Be extremely specific. Every project must connect to skills seen in multiple job listings."""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.choices[0].message.content

# ── Endpoints ─────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "running", "version": "4.0.0"}

@app.get("/stats")
def stats():
    return {
        "total_users": get_total_users(),
        "total_searches": get_total_searches(),
        "top_searches": [
            {"query": row[0], "count": row[1]}
            for row in get_top_searches(5)
        ]
    }

@app.get("/history/{username}")
def user_history(username: str):
    rows = get_user_search_history(username)
    return {
        "history": [
            {"query": r[0], "location": r[1], "job_count": r[2], "searched_at": r[3]}
            for r in rows
        ]
    }

@app.post("/suggest", response_model=SuggestionResponse)
def suggest_projects(request: SearchRequest):
    query = request.query.strip()
    location = request.location.strip()
    username = request.username.strip() or "anonymous"

    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    cached_suggestions, cached_scores = get_cached_suggestions(query)
    if cached_suggestions and cached_scores:
        cached_jobs = get_cached_jobs(query, location) or []
        log_search(username, query, location, len(cached_jobs))
        return SuggestionResponse(
            query=query,
            job_count=len(cached_jobs),
            jobs_analyzed=[{
                "title": j.get("title", ""),
                "company": j.get("company", ""),
                "link": j.get("link", ""),
                "location": j.get("location", "")
            } for j in cached_jobs[:15]],
            suggestions=cached_suggestions,
            scores=cached_scores,
            from_cache=True
        )

    jobs = get_cached_jobs(query, location)
    if not jobs:
        raw_jobs = fetch_jobs_from_api(query, location)
        if not raw_jobs:
            raise HTTPException(status_code=404, detail="No jobs found for this query")
        jobs = extract_job_info(raw_jobs)
        save_jobs_to_cache(query, location, jobs)

    log_search(username, query, location, len(jobs))
    relevant_jobs = get_relevant_jobs(query, jobs, top_k=10)
    suggestions = generate_suggestions(query, relevant_jobs)
    scores = evaluate_suggestions(suggestions, query)
    save_suggestions_to_cache(query, suggestions, scores)

    return SuggestionResponse(
        query=query,
        job_count=len(jobs),
        jobs_analyzed=[{
            "title": j.get("title", ""),
            "company": j.get("company", ""),
            "link": j.get("link", ""),
            "location": j.get("location", "")
        } for j in jobs[:15]],
        suggestions=suggestions,
        scores=scores,
        from_cache=False
    )

@app.post("/analyze-resume")
def analyze_resume(request: ResumeAnalysisRequest):
    """
    Takes a resume (as plain text) and a target job role.
    Fetches real job listings for that role.
    Uses LLM to:
      - Score ATS compatibility (0-100)
      - Find keyword gaps
      - Assess overall job fit
      - Give formatting tips
      - List strengths and weaknesses
    """
    if not request.resume_text or len(request.resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Resume text is too short")

    query = request.query.strip()
    location = request.location.strip()

    # Get or fetch jobs for this role
    jobs = get_cached_jobs(query, location)
    if not jobs:
        raw_jobs = fetch_jobs_from_api(query, location)
        if not raw_jobs:
            raise HTTPException(status_code=404, detail="No jobs found for this role")
        jobs = extract_job_info(raw_jobs)
        save_jobs_to_cache(query, location, jobs)

    # Build a summary of what skills/keywords appear across job listings
    all_skills = []
    job_summaries = ""
    for i, job in enumerate(jobs[:10], 1):
        skills = job.get("skills", [])
        all_skills.extend(skills)
        job_summaries += f"Job {i} ({job['title']} at {job['company']}): {job['description'][:300]}\n---\n"

    # Truncate resume to avoid token limits
    resume_truncated = request.resume_text[:3000]

    client = get_groq_client()

    prompt = f"""You are an expert ATS (Applicant Tracking System) analyst and career coach.

TARGET ROLE: {query}

REAL JOB LISTINGS FOR THIS ROLE:
{job_summaries}

CANDIDATE'S RESUME:
{resume_truncated}

Analyze the resume against these real job listings and respond ONLY with valid JSON. No markdown, no backticks, raw JSON only:

{{
  "ats_score": <number 0-100, overall ATS compatibility>,
  "fit_score": <number 0-100, how well candidate fits these specific roles>,
  "keyword_analysis": {{
    "present": [<list of keywords/skills from JDs that ARE in the resume>],
    "missing": [<list of important keywords/skills from JDs that are NOT in the resume>]
  }},
  "strengths": [
    "<strength 1 — specific, tied to what you saw in both resume and JDs>",
    "<strength 2>",
    "<strength 3>"
  ],
  "gaps": [
    "<gap 1 — specific skill or experience missing>",
    "<gap 2>",
    "<gap 3>"
  ],
  "ats_formatting_tips": [
    "<formatting tip 1 — specific issue you noticed in the resume>",
    "<formatting tip 2>",
    "<formatting tip 3>"
  ],
  "quick_wins": [
    "<thing they can add/change in their resume this week to improve ATS score>",
    "<quick win 2>",
    "<quick win 3>"
  ],
  "overall_verdict": "<2-3 sentence honest assessment of where they stand for this role>"
}}"""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        # If JSON parsing fails, return the raw text in a safe wrapper
        result = {
            "ats_score": 0,
            "fit_score": 0,
            "keyword_analysis": {"present": [], "missing": []},
            "strengths": [],
            "gaps": [],
            "ats_formatting_tips": [],
            "quick_wins": [],
            "overall_verdict": raw
        }

    return result

@app.post("/roadmap")
def get_roadmap(request: RoadmapRequest):
    """
    Takes a resume and target role.
    Generates a personalized 6-month roadmap with:
    - Month-by-month goals
    - Specific free resources for each month
    - Weekly time commitment
    - Milestones to hit
    """
    if not request.resume_text or len(request.resume_text.strip()) < 50:
        raise HTTPException(status_code=400, detail="Resume text is too short")

    resume_truncated = request.resume_text[:3000]
    query = request.query.strip()

    client = get_groq_client()

    prompt = f"""You are a senior career coach specializing in tech and data roles in India.

TARGET ROLE: {query}
CANDIDATE RESUME:
{resume_truncated}

Create a detailed, personalized 6-month career roadmap for this candidate to become competitive for {query} roles. 

Base it on what you actually see in their resume — their current skills, gaps, and background.

Respond ONLY with valid JSON. No markdown, no backticks, raw JSON only:

{{
  "current_level": "<honest assessment of where they are right now>",
  "target_outcome": "<what they will be able to do / show after 6 months>",
  "months": [
    {{
      "month": 1,
      "title": "<theme for this month>",
      "focus": "<what to learn/build this month and why>",
      "weekly_hours": <number>,
      "goals": [
        "<specific measurable goal 1>",
        "<specific measurable goal 2>",
        "<specific measurable goal 3>"
      ],
      "resources": [
        {{
          "name": "<resource name>",
          "url": "<actual URL>",
          "type": "<Course / YouTube / Book / Practice Platform / Documentation>",
          "cost": "Free",
          "why": "<why this specific resource for this candidate>"
        }}
      ],
      "milestone": "<what they should have to show at end of this month>"
    }},
    {{
      "month": 2,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{
          "name": "<name>",
          "url": "<url>",
          "type": "<type>",
          "cost": "Free",
          "why": "<why>"
        }}
      ],
      "milestone": "<milestone>"
    }},
    {{
      "month": 3,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}
      ],
      "milestone": "<milestone>"
    }},
    {{
      "month": 4,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}
      ],
      "milestone": "<milestone>"
    }},
    {{
      "month": 5,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}
      ],
      "milestone": "<milestone>"
    }},
    {{
      "month": 6,
      "title": "<theme>",
      "focus": "<focus>",
      "weekly_hours": <number>,
      "goals": ["<goal 1>", "<goal 2>", "<goal 3>"],
      "resources": [
        {{"name": "<name>", "url": "<url>", "type": "<type>", "cost": "Free", "why": "<why>"}}
      ],
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
  "final_checklist": [
    "<thing they must have ready before applying>",
    "<thing 2>",
    "<thing 3>",
    "<thing 4>",
    "<thing 5>"
  ]
}}

Use REAL, SPECIFIC free resources. Examples of good ones to consider based on role:
- Python: cs50p.harvard.edu, docs.python.org, freeCodeCamp YouTube
- ML: coursera.org/learn/machine-learning (audit free), fast.ai, kaggle.com/learn
- SQL: mode.com/sql-tutorial, stratascratch.com, leetcode.com/study-plan/sql-50
- DSA: neetcode.io, takeuforward.org (Striver), leetcode.com
- Data Analysis: kaggle.com/learn, pandas.pydata.org/docs
- Statistics: statquest.org (YouTube), seeing-theory.brown.edu
- System Design: github.com/donnemartin/system-design-primer
- Projects: github.com, kaggle.com/competitions

Pick resources actually relevant to the candidate's target role and current gaps."""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse roadmap. Try again.")

    return result

@app.delete("/cache")
def clear_cache():
    import sqlite3
    conn = sqlite3.connect("jobs_cache.db")
    conn.execute("DELETE FROM job_cache")
    conn.execute("DELETE FROM suggestion_cache")
    conn.commit()
    conn.close()
    return {"message": "Cache cleared"}