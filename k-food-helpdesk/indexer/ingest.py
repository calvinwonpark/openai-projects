import os, glob, json, psycopg2, pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PGHOST=os.getenv("PGHOST","db"); PGPORT=int(os.getenv("PGPORT","5432"))
PGDATABASE=os.getenv("PGDATABASE","helpdesk")
PGUSER=os.getenv("PGUSER","postgres"); PGPASSWORD=os.getenv("PGPASSWORD","postgres")

def conn():
    return psycopg2.connect(host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD)

def chunks(t, n=800):
    t=(t or "").strip()
    while t:
        yield t[:n]
        t=t[n:]

def embed_many(texts):
    r=client.embeddings.create(model="text-embedding-3-small", input=texts)
    return [d.embedding for d in r.data]

def upsert(cur, source, content, emb, meta):
    cur.execute("INSERT INTO docs (source, content, embedding, meta) VALUES (%s,%s,%s,%s)",
                (source, content, emb, json.dumps(meta)))

def ingest_policies(cur):
    for path in glob.glob("data/policies/*.md"):
        raw=open(path,"r",encoding="utf-8").read()
        parts=list(chunks(raw))
        if not parts: continue
        embs=embed_many(parts)
        for i,(ck,emb) in enumerate(zip(parts,embs)):
            upsert(cur, os.path.basename(path), ck, emb, {"kind":"policy","chunk":i})

def ingest_restaurants(cur, csv_path="data/policies/restaurants.csv"):
    if not os.path.exists(csv_path):
        print("No restaurants.csv found — skipping.")
        return
    df=pd.read_csv(csv_path).fillna("")
    for idx,row in df.iterrows():
        text=(f"Restaurant: {row.get('name','')}\nDistrict: {row.get('district','')}\n"
              f"Categories: {row.get('categories','')}\nHours: {row.get('hours','')}\n"
              f"DeliveryArea: {row.get('delivery_area','')}\nAllergens: {row.get('allergens','')}\n"
              f"Notes: {row.get('notes','')}\n")
        for j,ck in enumerate(chunks(text,600)):
            emb=embed_many([ck])[0]
            upsert(cur, "restaurants.csv", ck, emb, {"kind":"restaurant","row":int(idx),"chunk":j})

def main():
    with conn() as c, c.cursor() as cur:
        ingest_policies(cur)
        ingest_restaurants(cur)
        c.commit()
    print("Ingest complete.")

if __name__=="__main__":
    main()
