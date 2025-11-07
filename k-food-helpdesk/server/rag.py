import os, psycopg2
from typing import List, Tuple
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PGHOST=os.getenv("PGHOST","db"); PGPORT=int(os.getenv("PGPORT","5432"))
PGDATABASE=os.getenv("PGDATABASE","helpdesk")
PGUSER=os.getenv("PGUSER","postgres"); PGPASSWORD=os.getenv("PGPASSWORD","postgres")

def _conn():
    return psycopg2.connect(host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD)

def _embed(text:str)->List[float]:
    r=client.embeddings.create(model="text-embedding-3-small", input=text)
    return r.data[0].embedding

def top_k(query:str, k:int=4)->List[Tuple[str,str]]:
    qvec=_embed(query)
    with _conn() as con, con.cursor() as cur:
        # Format vector as PostgreSQL array string for pgvector
        vec_str = "[" + ",".join(str(x) for x in qvec) + "]"
        cur.execute("SELECT content, source FROM docs ORDER BY embedding <-> %s::vector LIMIT %s", (vec_str, k))
        return [(c,s) for (c,s) in cur.fetchall()]
