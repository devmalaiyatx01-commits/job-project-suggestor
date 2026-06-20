from groq import Groq
import os
import json
import re
from dotenv import load_dotenv

load_dotenv()

def evaluate_suggestions(suggestions_text: str, query: str) -> list:
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    prompt = f"""You are an evaluator judging portfolio project suggestions for someone applying to "{query}" roles.

Here are the suggestions:
{suggestions_text}

For each project suggestion, score it on:
1. relevance_score (1-10): How relevant to "{query}" roles?
2. specificity_score (1-10): How specific and concrete?
3. difficulty_calibration (1-10): How well calibrated for entry-level?

Respond ONLY with a valid JSON array. No explanation, no markdown, no backticks. Raw JSON only:
[
  {{"project_name": "Name here", "relevance_score": 8, "specificity_score": 7, "difficulty_calibration": 9, "overall": 8, "one_line_verdict": "Strong because..."}},
  {{"project_name": "Name here", "relevance_score": 6, "specificity_score": 5, "difficulty_calibration": 7, "overall": 6, "one_line_verdict": "Decent but..."}}
]"""

    message = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []