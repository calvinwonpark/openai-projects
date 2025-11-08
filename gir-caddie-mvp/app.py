import os, base64, json
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt

# Load env + OpenAI client
load_dotenv()
ocli = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html","r",encoding="utf-8") as f:
        return HTMLResponse(f.read())

class PlayerProfile(BaseModel):
    player_id: str = "user"
    clubs: list[dict]  # [{club, carry, std_lr, std_long, std_short}]
    miss_bias: Optional[dict] = None

@app.post("/api/profile")
async def api_profile(req: Request):
    data = await req.json()
    try:
        prof = PlayerProfile(**data)
    except Exception as e:
        return JSONResponse({"error": f"Bad profile: {e}"}, status_code=400)
    os.makedirs("uploads", exist_ok=True)
    with open("uploads/player_profile.json","w",encoding="utf-8") as f:
        json.dump(prof.model_dump(), f, ensure_ascii=False, indent=2)
    return {"ok": True}

def _b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode("utf-8")

SCORECARD_SYSTEM = (
    "You are a golf scorecard extractor. "
    "Return STRICT JSON with course name, list of tees, and per-hole yardages by tee and par. "
    "Schema: {\"course\": string, \"tees\": string[], "
    "\"holes\": [{\"num\": number, \"par\": number, \"yardages\": { [tee]: number|null }}]}"
)

@retry(wait=wait_exponential(min=1, max=15), stop=stop_after_attempt(4))
def _parse_scorecard_with_openai(image_bytes: bytes) -> dict:
    b64 = _b64(image_bytes)
    resp = ocli.chat.completions.create(
        model="gpt-4o",
        response_format={"type":"json_object"},
        messages=[
            {"role": "system", "content": SCORECARD_SYSTEM},
            {"role": "user", "content": [
                {"type":"text","text":"Extract the scorecard into JSON (strict schema)."},
                {"type":"image_url","image_url":{"url": f"data:image/jpeg;base64,{b64}"}}
            ]},
        ],
        temperature=0.0,
    )
    return json.loads(resp.choices[0].message.content)

from fastapi import UploadFile

@app.post("/api/parse-scorecard")
async def api_parse_scorecard(req: Request):
    form = await req.form()
    file: UploadFile = form.get("scorecard_image")
    if not file:
        return JSONResponse({"error":"scorecard_image is required"}, status_code=400)
    img_bytes = await file.read()
    data = _parse_scorecard_with_openai(img_bytes)
    os.makedirs("uploads", exist_ok=True)
    with open("uploads/scorecard.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"data": data}


LAYOUT_SYSTEM = (
    "You are a golf hole layout analyzer. The image may show a single hole OR a full course map with multiple holes. "
    "Your task is to find and analyze ONLY the specific hole number requested by the user. "
    "\n\n"
    "IMPORTANT: If the image shows multiple holes (a full course map): "
    "1. First, locate the hole number requested by the user. Look for a number in a circle or white circle near the fairway. "
    "2. Identify that specific hole's tee box (usually a small white circle or starting point) and green (marked with a red flag). "
    "3. Focus ONLY on hazards that affect THIS specific hole, not other holes. "
    "4. The fairway for this hole connects the tee to the green. Follow this path to identify relevant hazards. "
    "\n\n"
    "For a single hole image: "
    "1. The tee is where the player starts (often a white circle or marked area). "
    "2. The green is marked with a red flag. "
    "3. The hole number may be shown in a circle or label. "
    "\n\n"
    "Use the provided tee-to-green yardage to compute pixel_per_yard. "
    "For each hazard affecting the specified hole, calculate the yardage from the tee to the nearest point of the hazard using pixel_per_yard. "
    "Hazards include: water (blue areas), bunkers/sand traps (white/light areas), out of bounds (typically marked or at edges). "
    "\n\n"
    "Return strict JSON: {\"hole_num\": number, \"image_size\":[w,h], "
    "\"tee_px\":[x,y], \"green_center_px\":[x,y], \"pixel_per_yard\": number, "
    "\"hazards\":[{\"type\": \"water|bunker|ob_left|ob_right|fairway|rough\", \"yardage_to_hazard\": number, \"note\": string}], "
    "\"notes\": string }"
)

@retry(wait=wait_exponential(min=1, max=15), stop=stop_after_attempt(4))
def _extract_layout_with_openai(image_bytes: bytes, hole_num: int, tee_yardage: int, hazard_corrections: Optional[list] = None) -> dict:
    b64 = _b64(image_bytes)
    
    correction_text = ""
    if hazard_corrections:
        corrections_list = []
        for corr in hazard_corrections:
            corrections_list.append(f"Hazard at {corr.get('yardage_to_hazard', 'unknown')} yards: {corr.get('type', 'unknown')} is on the {corr.get('direction', 'unknown')} side of the fairway.")
        correction_text = "\n\nIMPORTANT CORRECTIONS: " + " ".join(corrections_list) + " Use these corrections to accurately identify hazard positions."
    
    resp = ocli.chat.completions.create(
        model="gpt-4o",
        response_format={"type":"json_object"},
        messages=[
            {"role":"system","content": LAYOUT_SYSTEM},
            {"role":"user","content":[
                {"type":"text","text": f"Analyze HOLE NUMBER {hole_num} in this image. "
                                        f"If this is a full course map with multiple holes, find and focus ONLY on hole {hole_num}. "
                                        f"Look for the number {hole_num} in a circle or label to identify the correct hole. "
                                        f"Tee-to-green yardage for this hole: {tee_yardage} yards. "
                                        f"Identify the tee box (starting point) and green (red flag) for hole {hole_num}. "
                                        f"Compute pixel_per_yard based on the distance from tee to green. "
                                        f"For each hazard that affects hole {hole_num}, calculate the yardage from the tee to the nearest point of the hazard. "
                                        f"Only include hazards that are relevant to hole {hole_num}, not other holes. "
                                        f"{correction_text}"},
                {"type":"image_url","image_url":{"url": f"data:image/jpeg;base64,{b64}"}}
            ]}
        ],
        temperature=0.2,
    )
    return json.loads(resp.choices[0].message.content)

@app.post("/api/extract-hole-layout")
async def api_extract_layout(req: Request):
    form = await req.form()
    file: UploadFile = form.get("hole_image")
    hole_num = int(form.get("hole_num", "1"))
    tee_yardage = int(form.get("tee_yardage", "400"))
    if not file:
        return JSONResponse({"error":"hole_image is required"}, status_code=400)
    img_bytes = await file.read()
    data = _extract_layout_with_openai(img_bytes, hole_num, tee_yardage)
    with open(f"uploads/hole_{hole_num}_layout.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"data": data}

@app.post("/api/recalibrate-hole-layout")
async def api_recalibrate_layout(req: Request):
    form = await req.form()
    file: UploadFile = form.get("hole_image")
    hole_num = int(form.get("hole_num", "1"))
    tee_yardage = int(form.get("tee_yardage", "400"))
    hazard_corrections_json = form.get("hazard_corrections", "[]")
    
    if not file:
        return JSONResponse({"error":"hole_image is required"}, status_code=400)
    
    try:
        hazard_corrections = json.loads(hazard_corrections_json)
    except:
        return JSONResponse({"error":"Invalid hazard_corrections JSON"}, status_code=400)
    
    img_bytes = await file.read()
    data = _extract_layout_with_openai(img_bytes, hole_num, tee_yardage, hazard_corrections)
    with open(f"uploads/hole_{hole_num}_layout.json","w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"data": data}

class HoleSelection(BaseModel):
    hole_num: int
    tee_box: str  # e.g., "Blue"

PLANNER_SYSTEM = (
    "You are an expert golf caddie. Using the player's dispersion, the chosen tee-box yardage, "
    "and the layout hazards (pixels, with pixel_per_yard), choose the safest plan that maximizes GIR probability. "
    "Prefer full-shot yardages over awkward in-betweens. "
    "Return STRICT JSON: {"
    "\"hole\": number, \"par\": number, \"tee_box\": string, "
    "\"shots\":[{\"shot_num\": number, \"club\": string, \"aim_note\": string, "
    "\"intended_carry_yards\": number, \"expected_leave_yards\": number|null, \"risk_notes\": string[]}], "
    "\"rationale\": string[], \"estimated_gir_probability\": number }"
)

@retry(wait=wait_exponential(min=1, max=15), stop=stop_after_attempt(4))
def _plan_with_openai(player_json: dict, hole_json: dict, layout_json: dict, hole_num: int, tee_box: str) -> dict:
    par = None
    tee_yardage = None
    for h in hole_json.get("holes", []):
        if int(h.get("num")) == int(hole_num):
            par = h.get("par")
            yardages = (h.get("yardages") or {})
            tee_yardage = yardages.get(tee_box)
            break

    messages = [
        {"role":"system","content": PLANNER_SYSTEM},
        {"role":"user","content": f"Player profile:\n{json.dumps(player_json, ensure_ascii=False)}"},
        {"role":"user","content": f"Hole context (tee={tee_box}, par={par}, yardage={tee_yardage}):\n"
                                  f"{json.dumps({'num':hole_num,'par':par,'yardage':tee_yardage,'tee_box':tee_box}, ensure_ascii=False)}"},
        {"role":"user","content": f"Layout & hazards:\n{json.dumps(layout_json, ensure_ascii=False)}"},
    ]
    resp = ocli.chat.completions.create(
        model="gpt-4o",
        response_format={"type":"json_object"},
        messages=messages,
        temperature=0.2,
    )
    return json.loads(resp.choices[0].message.content)

@app.post("/api/plan-hole")
async def api_plan_hole(req: Request):
    body = await req.json()
    try:
        sel = HoleSelection(**{"hole_num": body.get("hole_num"), "tee_box": body.get("tee_box")})
    except Exception as e:
        return JSONResponse({"error": f"Bad selection: {e}"}, status_code=400)

    try:
        player = json.load(open("uploads/player_profile.json","r",encoding="utf-8"))
        scorecard = json.load(open("uploads/scorecard.json","r",encoding="utf-8"))
        layout = json.load(open(f"uploads/hole_{sel.hole_num}_layout.json","r",encoding="utf-8"))
    except FileNotFoundError:
        return JSONResponse({"error":"Missing player/scorecard/layout. Upload those first."}, status_code=400)

    plan = _plan_with_openai(player, scorecard, layout, sel.hole_num, sel.tee_box)
    return {"plan": plan}
