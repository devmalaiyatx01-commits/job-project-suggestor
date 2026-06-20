import streamlit as st
import httpx
import pdfplumber
import io
from auth import register_user, login_user, get_security_question, reset_password, SECURITY_QUESTIONS

API_URL = "http://localhost:8000"

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

# ── Helper functions ──────────────────────────────────────────

def fetch_stats():
    try:
        resp = httpx.get(f"{API_URL}/stats", timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {"total_users": 0, "total_searches": 0, "top_searches": []}

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract all text from a PDF file"""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        text = ""
    return text.strip()

def score_color(score: int) -> str:
    """Returns a color based on score value"""
    if score >= 75:
        return "green"
    elif score >= 50:
        return "orange"
    else:
        return "red"

def score_label(score: int) -> str:
    if score >= 75:
        return "Strong ✅"
    elif score >= 50:
        return "Moderate ⚠️"
    else:
        return "Needs Work ❌"

# ── Header ────────────────────────────────────────────────────
stats = fetch_stats()

st.title("🎯 Job-to-Project Suggester")

col_u, col_s, col_gap = st.columns([1, 1, 2])
col_u.metric("👥 Total Users", stats["total_users"])
col_s.metric("🔍 Total Searches", stats["total_searches"])

st.markdown("*Search any job role → get real listings → AI tells you what to build, how your resume scores, and your 6-month plan*")
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
                                    help="Remember this — you'll need it to reset your password")

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
            history_resp = httpx.get(
                f"{API_URL}/history/{st.session_state.username}", timeout=5
            )
            if history_resp.status_code == 200:
                history = history_resp.json().get("history", [])
                if history:
                    for item in history:
                        st.markdown(f"**{item['query']}** — {item['job_count']} jobs")
                else:
                    st.markdown("*No searches yet*")
        except Exception:
            st.markdown("*Could not load history*")

        st.markdown("---")
        if st.button("🗑️ Clear Job Cache"):
            try:
                httpx.delete(f"{API_URL}/cache")
                st.success("Cache cleared!")
            except Exception:
                st.error("Could not reach API")

        st.markdown("---")
        st.markdown("### 📊 Platform Stats")
        st.markdown(f"👥 **{stats['total_users']}** registered users")
        st.markdown(f"🔍 **{stats['total_searches']}** searches run")
        top = stats.get("top_searches", [])
        if top:
            st.markdown("**🔥 Top Searches:**")
            for item in top:
                st.markdown(f"- {item['query']} ({item['count']}x)")

    # ── Resume upload (persistent across tabs) ────────────────
    st.markdown(f"Welcome, **{st.session_state.username}**!")

    with st.expander("📄 Upload Your Resume (used across all features)", expanded=not st.session_state.resume_text):
        st.caption("Upload once — your resume will be used for ATS analysis and roadmap generation")

        upload_method = st.radio(
            "How do you want to add your resume?",
            ["Upload PDF", "Paste as text"],
            horizontal=True
        )

        if upload_method == "Upload PDF":
            uploaded_file = st.file_uploader(
                "Upload your resume PDF",
                type=["pdf"],
                help="Max 5MB"
            )
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
                    response = httpx.post(
                        f"{API_URL}/suggest",
                        json={
                            "query": query,
                            "location": location,
                            "username": st.session_state.username
                        },
                        timeout=120
                    )

                    if response.status_code == 200:
                        data = response.json()

                        if data.get("from_cache"):
                            st.info("⚡ Loaded from cache — instant!")
                        else:
                            st.success(f"✅ Analyzed {data['job_count']} live listings for **{query}**")

                        # Job listings
                        st.markdown("---")
                        st.markdown("## 📋 Jobs Found — Apply Directly")
                        jobs = data.get("jobs_analyzed", [])
                        if jobs:
                            for job in jobs:
                                title = job.get("title", "Unknown Role")
                                company = job.get("company", "Unknown")
                                link = job.get("link", "")
                                loc = job.get("location", "")
                                col_info, col_btn = st.columns([4, 1])
                                with col_info:
                                    loc_text = f" · 📍 {loc}" if loc else ""
                                    st.markdown(f"**{title}** at {company}{loc_text}")
                                with col_btn:
                                    if link:
                                        st.markdown(f"[🔗 Apply]({link})")
                                    else:
                                        st.markdown("*No link*")

                        # Suggestions
                        st.markdown("---")
                        st.markdown("## 🚀 Projects to Build for Your Resume")
                        st.markdown(data["suggestions"])

                        # Scores
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

                    elif response.status_code == 404:
                        st.error("No jobs found. Try a different role or location.")
                    else:
                        st.error(f"Error: {response.text}")

                except httpx.ConnectError:
                    st.error("❌ Cannot reach API. Make sure Terminal 1 is running: uvicorn main:app --reload")
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

                        if response.status_code == 200:
                            data = response.json()

                            # ── Score cards ───────────────────
                            st.markdown("---")
                            st.markdown("## 🎯 Your Scores")

                            ats = data.get("ats_score", 0)
                            fit = data.get("fit_score", 0)

                            col_ats, col_fit, col_gap = st.columns([1, 1, 2])

                            with col_ats:
                                st.metric(
                                    "ATS Score",
                                    f"{ats}/100",
                                    delta=score_label(ats)
                                )
                                st.progress(ats / 100)

                            with col_fit:
                                st.metric(
                                    "Job Fit Score",
                                    f"{fit}/100",
                                    delta=score_label(fit)
                                )
                                st.progress(fit / 100)

                            # ── Overall verdict ───────────────
                            st.markdown("---")
                            st.markdown("### 💬 Overall Assessment")
                            st.info(data.get("overall_verdict", ""))

                            # ── Keywords ──────────────────────
                            st.markdown("---")
                            st.markdown("### 🔑 Keyword Analysis")

                            kw = data.get("keyword_analysis", {})
                            present = kw.get("present", [])
                            missing = kw.get("missing", [])

                            col_p, col_m = st.columns(2)

                            with col_p:
                                st.markdown("**✅ Keywords you have:**")
                                if present:
                                    for kw_item in present:
                                        st.markdown(f"- {kw_item}")
                                else:
                                    st.markdown("*None detected*")

                            with col_m:
                                st.markdown("**❌ Keywords you're missing:**")
                                if missing:
                                    for kw_item in missing:
                                        st.markdown(f"- {kw_item}")
                                else:
                                    st.markdown("*None — great coverage!*")

                            # ── Strengths & Gaps ──────────────
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

                            # ── Formatting tips ───────────────
                            st.markdown("---")
                            st.markdown("### 📝 ATS Formatting Tips")
                            st.caption("These are specific issues detected in your resume")
                            for tip in data.get("ats_formatting_tips", []):
                                st.warning(tip)

                            # ── Quick wins ────────────────────
                            st.markdown("---")
                            st.markdown("### ⚡ Quick Wins — Do These This Week")
                            st.caption("Small changes that immediately improve your ATS score")
                            for i, win in enumerate(data.get("quick_wins", []), 1):
                                st.markdown(f"**{i}.** {win}")

                        elif response.status_code == 404:
                            st.error("No jobs found for this role. Try a different title.")
                        else:
                            st.error(f"Error: {response.text}")

                    except httpx.ConnectError:
                        st.error("❌ Cannot reach API. Make sure Terminal 1 is running.")
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
                        response = httpx.post(
                            f"{API_URL}/roadmap",
                            json={
                                "resume_text": st.session_state.resume_text,
                                "query": roadmap_query,
                                "username": st.session_state.username
                            },
                            timeout=120
                        )

                        if response.status_code == 200:
                            data = response.json()

                            # ── Summary ───────────────────────
                            st.markdown("---")
                            col_now, col_then = st.columns(2)
                            with col_now:
                                st.markdown("### 📍 Where You Are Now")
                                st.info(data.get("current_level", ""))
                            with col_then:
                                st.markdown("### 🎯 Where You'll Be in 6 Months")
                                st.success(data.get("target_outcome", ""))

                            # ── Monthly breakdown ─────────────
                            st.markdown("---")
                            st.markdown("## 📅 Month-by-Month Plan")

                            months = data.get("months", [])
                            for month_data in months:
                                month_num = month_data.get("month", "")
                                title = month_data.get("title", "")
                                focus = month_data.get("focus", "")
                                weekly_hours = month_data.get("weekly_hours", "")
                                goals = month_data.get("goals", [])
                                resources = month_data.get("resources", [])
                                milestone = month_data.get("milestone", "")

                                with st.expander(
                                    f"**Month {month_num}: {title}** — {weekly_hours}hrs/week",
                                    expanded=(month_num == 1)
                                ):
                                    st.markdown(f"**🎯 Focus:** {focus}")
                                    st.markdown(f"**⏱️ Time commitment:** {weekly_hours} hours per week")

                                    st.markdown("**📌 Goals this month:**")
                                    for goal in goals:
                                        st.markdown(f"- {goal}")

                                    if resources:
                                        st.markdown("**📚 Resources:**")
                                        for res in resources:
                                            name = res.get("name", "")
                                            url = res.get("url", "")
                                            res_type = res.get("type", "")
                                            why = res.get("why", "")
                                            cost = res.get("cost", "Free")

                                            col_res, col_type = st.columns([3, 1])
                                            with col_res:
                                                if url:
                                                    st.markdown(f"🔗 [{name}]({url})")
                                                else:
                                                    st.markdown(f"📖 {name}")
                                                if why:
                                                    st.caption(why)
                                            with col_type:
                                                st.caption(f"{res_type} · {cost}")

                                    st.markdown("---")
                                    st.success(f"🏁 **End of month milestone:** {milestone}")

                            # ── Interview prep ────────────────
                            interview = data.get("interview_prep", {})
                            if interview:
                                st.markdown("---")
                                st.markdown("## 🎤 Interview Preparation")

                                topics = interview.get("topics", [])
                                if topics:
                                    st.markdown("**Topics to master:**")
                                    cols = st.columns(min(len(topics), 3))
                                    for i, topic in enumerate(topics):
                                        cols[i % 3].markdown(f"- {topic}")

                                int_resources = interview.get("resources", [])
                                if int_resources:
                                    st.markdown("**Resources:**")
                                    for res in int_resources:
                                        name = res.get("name", "")
                                        url = res.get("url", "")
                                        if url:
                                            st.markdown(f"🔗 [{name}]({url})")
                                        else:
                                            st.markdown(f"📖 {name}")

                            # ── Final checklist ───────────────
                            checklist = data.get("final_checklist", [])
                            if checklist:
                                st.markdown("---")
                                st.markdown("## ✅ Before You Apply — Final Checklist")
                                for item in checklist:
                                    st.checkbox(item, key=f"check_{item[:20]}")

                            # ── Download roadmap ──────────────
                            roadmap_text = f"6-MONTH ROADMAP FOR: {roadmap_query}\n\n"
                            roadmap_text += f"Current Level: {data.get('current_level', '')}\n"
                            roadmap_text += f"Target: {data.get('target_outcome', '')}\n\n"
                            for m in months:
                                roadmap_text += f"\nMONTH {m.get('month')}: {m.get('title')}\n"
                                roadmap_text += f"Focus: {m.get('focus')}\n"
                                roadmap_text += f"Hours/week: {m.get('weekly_hours')}\n"
                                roadmap_text += "Goals:\n"
                                for g in m.get("goals", []):
                                    roadmap_text += f"  - {g}\n"
                                roadmap_text += "Resources:\n"
                                for r in m.get("resources", []):
                                    roadmap_text += f"  - {r.get('name')} ({r.get('url', 'no url')})\n"
                                roadmap_text += f"Milestone: {m.get('milestone')}\n"

                            st.download_button(
                                "📥 Download Roadmap as .txt",
                                data=roadmap_text,
                                file_name=f"roadmap_{roadmap_query.replace(' ','_')}.txt",
                                mime="text/plain"
                            )

                        else:
                            st.error(f"Error: {response.text}")

                    except httpx.ConnectError:
                        st.error("❌ Cannot reach API. Make sure Terminal 1 is running.")
                    except Exception as e:
                        st.error(f"Something went wrong: {str(e)}")