# app.py
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import httpx

load_dotenv()

app = FastAPI()

# CORS (fine for local dev; you can tighten later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (index.html + realtime.js)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
def index():
    """
    Serve the main HTML page.
    """
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.post("/realtime-token")
def get_realtime_token():
    """
    Mint a short-lived ephemeral key for the browser to connect to gpt-realtime.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Missing OPENAI_API_KEY"}, status_code=500)

    body = {
        "session": {
            "type": "realtime",
            "model": "gpt-realtime",  # realtime model
        }
    }

    try:
        resp = httpx.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
    except Exception as e:
        return JSONResponse(
            {"error": "Failed to call client_secrets", "details": str(e)},
            status_code=500,
        )

    if resp.status_code != 200:
        return JSONResponse(
            {"error": "Failed to create client secret", "details": resp.text},
            status_code=500,
        )

    data = resp.json()
    client_secret = (
        data.get("client_secret", {}).get("value")
        or data.get("value")
    )

    if not client_secret:
        return JSONResponse(
            {"error": "client_secret not in response", "raw": data},
            status_code=500,
        )

    return {"client_secret": client_secret}
