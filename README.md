# 🎯 Job Project Suggester

> Search real job postings, get AI-generated portfolio project ideas tailored to what employers are actually asking for, score your resume against live job descriptions, and get a personalized 6-month roadmap to become competitive for the role.

🔗 **Live demo:** [https://job-project-suggestor-df6vrjgmlchtmhgzneqhk9.streamlit.app/]
📂 **Repo:** [github.com/devmalaiyatx01-commits/job-project-suggestor](https://github.com/devmalaiyatx01-commits/job-project-suggestor)



---

## What it does

Most "build a portfolio project" advice is generic. This tool grounds it in reality: it pulls live job postings for the role you're targeting, then uses an LLM to suggest portfolio projects that map directly to the skills those listings actually ask for — not a generic tutorial list.

- **🔍 Live job search** — pulls real, recent listings for any role + location via the JSearch API
- **🧠 Semantic relevance ranking** — embeds job descriptions with `sentence-transformers` and ranks them by cosine similarity to the search query, so the most relevant postings drive the suggestions
- **💡 AI portfolio project suggestions** — Groq-hosted Llama 3.3 70B analyzes the listings and proposes 6–8 specific, scoped projects (with difficulty estimate) tied to patterns across multiple job descriptions
- **✅ LLM-as-judge scoring** — every suggestion is independently scored on relevance, specificity, and difficulty calibration, so low-quality suggestions don't slip through
- **📄 Resume ATS analysis** — upload a resume (PDF or text) and get an ATS compatibility score, job-fit score, keyword gap analysis, strengths/gaps, and formatting tips — all benchmarked against real listings for your target role
- **🗺️ 6-month roadmap generator** — a personalized, month-by-month learning plan with free resources, weekly time commitments, and milestones, built from your actual resume and target role
- **👤 Accounts + history** — simple username/password auth (PBKDF2-hashed, with security-question recovery) and per-user search history
- **⚡ Caching** — job listings and AI suggestions are cached in SQLite so repeat searches are instant and don't burn API quota

## Tech stack

| Layer | Tech |
|---|---|
| Frontend | Streamlit |
| Backend (optional) | FastAPI |
| LLM | Groq API (Llama 3.3 70B) |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Job data | JSearch API (RapidAPI) |
| Storage | SQLite |
| Resume parsing | `pdfplumber` |
| Auth | PBKDF2-HMAC password hashing (`hashlib`) |

The Streamlit app can run standalone (calling the same logic directly) or talk to the FastAPI backend if it's running — useful for local dev vs. lightweight cloud deployment.

## Running it locally

```bash
git clone https://github.com/devmalaiyatx01-commits/job-project-suggestor.git
cd job-project-suggestor
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your keys:

```
RAPID_API_KEY=your_jsearch_rapidapi_key
GROQ_API_KEY=your_groq_api_key
```

- Get a free JSearch key from [RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch)
- Get a free Groq API key from [console.groq.com](https://console.groq.com)

Then run the app:

```bash
streamlit run app.py
```

(Optional) Run the FastAPI backend alongside it:

```bash
uvicorn main:app --reload
```

## Project structure

```
app.py          # Streamlit frontend — UI, auth flow, tabs for search/resume/roadmap
main.py         # FastAPI backend — same logic exposed as REST endpoints
auth.py         # Password hashing, validation, login/register/reset logic
database.py     # SQLite schema + cache, user, and search-history queries
embeddings.py   # Sentence-transformer embeddings + cosine similarity ranking
evaluator.py    # LLM-as-judge scoring for generated suggestions
requirements.txt
```

## What I'd build next

- Swap SQLite for Postgres to support concurrent users at scale
- Add OAuth login instead of username/password
- Let users save/export their generated project suggestions as a checklist
- Surface salary range and seniority filters on job search

## License

MIT — feel free to fork and adapt.
