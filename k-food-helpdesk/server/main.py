import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from rag import top_k
from prompts import SYSTEM_PROMPT

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatReq(BaseModel):
    message: str
    session_id: str | None = None

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/search")
def search(req: ChatReq):
    snips = top_k(req.message, 4)
    return {"results": [{"source": s, "content": c} for c, s in snips]}

@app.post("/chat")
def chat(req: ChatReq):
    snips = top_k(req.message, 4)
    context = "\n\n".join([f"[{s}]\n{c}" for c, s in snips])
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": f"Context:\n{context}"},
        {"role": "user", "content": req.message},
    ]
    out = client.chat.completions.create(model="gpt-4-turbo", messages=messages, temperature=0.2)
    # Deduplicate sources while preserving order
    sources = []
    seen = set()
    for _, s in snips:
        if s not in seen:
            sources.append(s)
            seen.add(s)
    return {"answer": out.choices[0].message.content, "sources": sources}
