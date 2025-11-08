import os, psycopg2
from typing import List, Tuple, Optional
from dotenv import load_dotenv
from openai import OpenAI
import math

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PGHOST=os.getenv("PGHOST","db"); PGPORT=int(os.getenv("PGPORT","5432"))
PGDATABASE=os.getenv("PGDATABASE","helpdesk")
PGUSER=os.getenv("PGUSER","postgres"); PGPASSWORD=os.getenv("PGPASSWORD","postgres")

# Session-aware retrieval cache: {session_id: [(query_embedding, results), ...]}
_retrieval_cache = {}

def _conn():
    return psycopg2.connect(host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD)

def _embed(text:str)->List[float]:
    r=client.embeddings.create(model="text-embedding-3-small", input=text)
    return r.data[0].embedding

def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(a * a for a in vec2))
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)

def top_k(query:str, k:int=4, session_id:Optional[str]=None)->List[Tuple[str,str]]:
    """
    Retrieve top k documents for a query, with session-aware caching.
    Reuses previous results if cosine similarity > 0.9 with a cached query.
    """
    qvec=_embed(query)
    
    # Check cache if session_id is provided
    if session_id and session_id in _retrieval_cache:
        for cached_qvec, cached_results in _retrieval_cache[session_id]:
            similarity = _cosine_similarity(qvec, cached_qvec)
            if similarity > 0.9:
                # Return cached results (limit to k if needed)
                return cached_results[:k]
    
    # Cache miss or no session - perform retrieval
    with _conn() as con, con.cursor() as cur:
        # Format vector as PostgreSQL array string for pgvector
        vec_str = "[" + ",".join(str(x) for x in qvec) + "]"
        cur.execute("SELECT content, source FROM docs ORDER BY embedding <-> %s::vector LIMIT %s", (vec_str, k))
        results = [(c,s) for (c,s) in cur.fetchall()]
    
    # Cache the results if session_id is provided
    if session_id:
        if session_id not in _retrieval_cache:
            _retrieval_cache[session_id] = []
        _retrieval_cache[session_id].append((qvec, results))
        # Limit cache size per session (keep last 50 queries)
        if len(_retrieval_cache[session_id]) > 50:
            _retrieval_cache[session_id] = _retrieval_cache[session_id][-50:]
    
    return results
