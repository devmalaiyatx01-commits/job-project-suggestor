from sentence_transformers import SentenceTransformer, util
import numpy as np

print("Loading embedding model... (first time takes 1-2 minutes)")
model = SentenceTransformer("all-MiniLM-L6-v2")
print("Embedding model ready.")

def get_relevant_jobs(query: str, jobs: list, top_k: int = 10):
    if not jobs:
        return []

    documents = [f"{job.get('title', '')} {job.get('description', '')}" for job in jobs]

    job_embeddings = model.encode(documents)
    query_embedding = model.encode([query])

    similarities = util.cos_sim(query_embedding, job_embeddings)[0].numpy()

    k = min(top_k, len(jobs))
    top_indices = np.argsort(-similarities)[:k]

    relevant_jobs = []
    for i in top_indices:
        job = jobs[int(i)]
        relevant_jobs.append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "link": job.get("link", ""),
            "location": job.get("location", ""),
            "description": (job.get("description", "") or "")[:800],
            "skills": job.get("skills", [])
        })

    return relevant_jobs
