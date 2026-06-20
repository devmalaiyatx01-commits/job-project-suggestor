import chromadb
from sentence_transformers import SentenceTransformer
import hashlib

print("Loading embedding model... (first time takes 1-2 minutes)")
model = SentenceTransformer("all-MiniLM-L6-v2")
print("Embedding model ready.")

client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection(
    name="job_descriptions",
    metadata={"heuristic": "cosine"}
)

def embed_and_store_jobs(query: str, jobs: list):
    documents = []
    ids = []
    metadatas = []

    for i, job in enumerate(jobs):
        text = f"{job.get('title', '')} {job.get('description', '')}"
        doc_id = hashlib.md5(f"{query}_{i}".encode()).hexdigest()
        documents.append(text)
        ids.append(doc_id)
        metadatas.append({
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "link": job.get("link", ""),
            "location": job.get("location", ""),
            "query": query
        })

    embeddings = model.encode(documents).tolist()

    collection.upsert(
        documents=documents,
        embeddings=embeddings,
        ids=ids,
        metadatas=metadatas
    )

def get_relevant_jobs(query: str, jobs: list, top_k: int = 10):
    embed_and_store_jobs(query, jobs)

    query_embedding = model.encode([query]).tolist()

    results = collection.query(
        query_embeddings=query_embedding,
        n_results=min(top_k, len(jobs)),
        where={"query": query}
    )

    relevant_jobs = []
    if results and results["metadatas"]:
        for i, metadata in enumerate(results["metadatas"][0]):
            relevant_jobs.append({
                "title": metadata.get("title", ""),
                "company": metadata.get("company", ""),
                "link": metadata.get("link", ""),
                "location": metadata.get("location", ""),
                "description": results["documents"][0][i][:800] if results["documents"] else "",
                "skills": []
            })

    return relevant_jobs