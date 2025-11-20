import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import Farmer, OTPRequest, Session, Recommendation, Notification, CropCalendarItem, Scheme

app = FastAPI(title="Smart Crop Advisory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Utility helpers

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def get_collection(name: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    return db[name]


# Auth models
class OTPStartRequest(BaseModel):
    phone: str
    farmer_id: Optional[str] = None


class OTPVerifyRequest(BaseModel):
    phone: str
    otp: str
    farmer_id: Optional[str] = None
    aadhaar: Optional[str] = None
    language: Optional[str] = "en"
    name: Optional[str] = None
    location: Optional[str] = None


class TokenResponse(BaseModel):
    token: str
    farmer_id: str
    expires_in: int


# Simple auth dependency
async def require_session(token: str) -> str:
    sessions = get_collection("session")
    s = sessions.find_one({"token": token})
    if not s:
        raise HTTPException(status_code=401, detail="Invalid token")
    if s.get("expires_at") and s["expires_at"] < now_utc():
        raise HTTPException(status_code=401, detail="Session expired")
    return s["farmer_id"]


@app.get("/")
def root():
    return {"name": "Smart Crop Advisory API", "status": "ok"}


@app.get("/test")
def test_database():
    try:
        collections = db.list_collection_names() if db is not None else []
        return {
            "backend": "✅ Running",
            "database": "✅ Connected" if db is not None else "❌ Not available",
            "collections": collections[:10],
        }
    except Exception as e:
        return {"backend": "✅ Running", "database": f"❌ Error: {str(e)}"}


# OTP flow (demo implementation - logs OTP to server instead of sending SMS)
@app.post("/auth/request-otp")
def request_otp(payload: OTPStartRequest):
    otp = f"{secrets.randbelow(1000000):06d}"
    expires = now_utc() + timedelta(minutes=5)
    otp_doc = OTPRequest(phone=payload.phone, otp=otp, expires_at=expires, verified=False, farmer_id=payload.farmer_id)
    create_document("otprequest", otp_doc)

    # In production, integrate SMS provider here. For demo, return masked and echo for testing
    masked = payload.phone[:-4].replace("0", "*").replace("1", "*") + payload.phone[-4:]
    return {"message": "OTP sent", "phone": masked, "demo_otp": otp}


@app.post("/auth/verify-otp", response_model=TokenResponse)
def verify_otp(payload: OTPVerifyRequest):
    otps = get_collection("otprequest")
    latest = otps.find_one({"phone": payload.phone}, sort=[("created_at", -1)])
    if not latest or latest.get("otp") != payload.otp:
        raise HTTPException(status_code=400, detail="Invalid OTP")
    if latest.get("expires_at") and latest["expires_at"] < now_utc():
        raise HTTPException(status_code=400, detail="OTP expired")

    # Upsert farmer profile
    farmers = get_collection("farmer")
    fid = payload.farmer_id or payload.phone
    farmer_doc = farmers.find_one({"farmer_id": fid})
    if not farmer_doc:
        farmer = Farmer(farmer_id=fid, phone=payload.phone, aadhaar=payload.aadhaar, language=payload.language, name=payload.name, location=payload.location)
        create_document("farmer", farmer)
    else:
        farmers.update_one({"farmer_id": fid}, {"$set": {"phone": payload.phone, "aadhaar": payload.aadhaar, "language": payload.language, "name": payload.name, "location": payload.location, "updated_at": now_utc()}})

    # Create session
    token = secrets.token_urlsafe(24)
    sess = Session(farmer_id=fid, token=token, created_at=now_utc(), expires_at=now_utc() + timedelta(days=7))
    create_document("session", sess)
    return TokenResponse(token=token, farmer_id=fid, expires_in=7 * 24 * 3600)


# Dashboard data
@app.get("/dashboard")
def get_dashboard(token: str = Depends(require_session)):
    fid = token  # actually returns farmer_id from dependency
    farmer_id = fid
    farmers = get_collection("farmer")
    f = farmers.find_one({"farmer_id": farmer_id}) or {}

    # Simple personalized suggestions (rule-based demo)
    crops = f.get("crops") or ["Paddy", "Wheat"]
    recommendations = [
        {"crop": c, "score": 0.85 - i * 0.1, "reason": "Based on seasonality and regional trends"}
        for i, c in enumerate(crops[:2])
    ]

    # Soil health status mock
    soil_status = {
        "status": "Moderate",
        "ph": 6.8,
        "nitrogen": "Medium",
        "phosphorus": "Low",
        "potassium": "Medium",
        "advice": "Apply balanced NPK and add organic compost."
    }

    # Weather risks mock
    weather_risk = {
        "risk_level": "Medium",
        "alerts": [
            {"type": "Rain", "message": "Light showers expected in 2 days."},
            {"type": "Heat", "message": "Afternoon temperature up to 34°C."}
        ]
    }

    irrigation_tips = [
        "Irrigate early morning to reduce evaporation",
        "Use mulching to retain soil moisture",
    ]

    notifications = list(get_collection("notification").find({"farmer_id": farmer_id}).sort("created_at", -1).limit(10))
    recent_activity = [
        {"type": "login", "time": now_utc().isoformat()},
        {"type": "viewed_calendar", "time": (now_utc()-timedelta(hours=2)).isoformat()},
    ]

    return {
        "farmer": {"farmer_id": farmer_id, "name": f.get("name"), "location": f.get("location"), "language": f.get("language", "en")},
        "recommendations": recommendations,
        "soil": soil_status,
        "weather": weather_risk,
        "irrigation_tips": irrigation_tips,
        "notifications": notifications,
        "recent_activity": recent_activity,
    }


# Crop calendar
class CalendarQuery(BaseModel):
    farmer_id: Optional[str] = None


@app.get("/calendar")
def get_calendar(token: str = Depends(require_session)):
    farmer_id = token
    items = list(get_collection("cropcalendaritem").find({"farmer_id": farmer_id}).sort("date", 1))
    # Provide sample items if none exist
    if not items:
        sample = [
            {"farmer_id": farmer_id, "crop": "Paddy", "phase": "sowing", "date": now_utc() + timedelta(days=1), "note": "Prepare nursery bed"},
            {"farmer_id": farmer_id, "crop": "Paddy", "phase": "irrigation", "date": now_utc() + timedelta(days=3), "note": "Light irrigation"},
            {"farmer_id": farmer_id, "crop": "Paddy", "phase": "fertilizer", "date": now_utc() + timedelta(days=7), "note": "Apply DAP"},
            {"farmer_id": farmer_id, "crop": "Paddy", "phase": "pest", "date": now_utc() + timedelta(days=12), "note": "Monitor for leaf folder"},
            {"farmer_id": farmer_id, "crop": "Paddy", "phase": "harvest", "date": now_utc() + timedelta(days=90), "note": "Expected harvest"},
        ]
        for it in sample:
            create_document("cropcalendaritem", CropCalendarItem(**it))
        items = list(get_collection("cropcalendaritem").find({"farmer_id": farmer_id}).sort("date", 1))

    # Serialize datetime
    for it in items:
        it["_id"] = str(it["_id"]) if "_id" in it else None
        if isinstance(it.get("date"), datetime):
            it["date"] = it["date"].isoformat()
    return {"items": items}


# AI Image-based disease detection (demo heuristic)
@app.post("/disease-detect")
async def disease_detect(file: UploadFile = File(...), crop: Optional[str] = Form(None), token: str = Form(None)):
    # Read a small chunk to "analyze"
    content = await file.read()
    size = len(content)
    if size < 10000:
        diagnosis = "Low confidence: image too small. Possible nutrient deficiency."
        treatment = "Apply balanced micronutrient spray; retake a clearer photo."
    else:
        # naive heuristic by byte pattern
        score = sum(content[:5000]) % 100 / 100
        if score > 0.6:
            diagnosis = "Likely Leaf Blight"
            treatment = "Remove affected leaves, apply recommended fungicide (mancozeb)."
        elif score > 0.3:
            diagnosis = "Possible Powdery Mildew"
            treatment = "Improve airflow, apply sulfur-based spray during evening."
        else:
            diagnosis = "Aphid/Pest infestation suspected"
            treatment = "Use neem oil or appropriate insecticide; monitor sticky traps."
    return {"crop": crop, "diagnosis": diagnosis, "treatment": treatment}


# Government scheme finder (static curated list + filters)
SCHEMES: List[Scheme] = [
    Scheme(
        name="PM-KISAN Income Support",
        description="Direct income support to farmer families.",
        state=None,
        crop_types=None,
        benefit="Rs. 6,000/year",
        link="https://pmkisan.gov.in"
    ),
    Scheme(
        name="Soil Health Card Scheme",
        description="Free soil testing and recommendations.",
        state=None,
        crop_types=None,
        benefit="Free soil testing",
        link="https://soilhealth.dac.gov.in"
    ),
    Scheme(
        name="Interest Subvention for Short Term Crop Loans",
        description="Subsidized interest for crop loans.",
        state=None,
        crop_types=None,
        benefit="Up to 3% subsidy",
        link="https://www.nabard.org"
    ),
    Scheme(
        name="State Micro Irrigation Subsidy",
        description="Drip/sprinkler irrigation subsidy.",
        state="Tamil Nadu",
        crop_types=["Paddy", "Sugarcane", "Vegetables"],
        benefit="Up to 55% subsidy",
        link="https://tnhorticulture.tn.gov.in"
    ),
]


class SchemeQuery(BaseModel):
    state: Optional[str] = None
    crop: Optional[str] = None


@app.post("/schemes")
def find_schemes(query: SchemeQuery):
    res = []
    for s in SCHEMES:
        if query.state and s.state and s.state.lower() != query.state.lower():
            continue
        if query.crop and s.crop_types and query.crop not in s.crop_types:
            continue
        res.append(s)
    return {"schemes": [s.model_dump() for s in res]}


# Market updates (mock)
@app.get("/market-updates")
def market_updates(crop: Optional[str] = None, state: Optional[str] = None):
    base = [
        {"crop": "Paddy", "min": 1500, "max": 2100, "unit": "Rs/quintal"},
        {"crop": "Wheat", "min": 1700, "max": 2200, "unit": "Rs/quintal"},
        {"crop": "Tomato", "min": 10, "max": 30, "unit": "Rs/kg"},
    ]
    data = [r for r in base if (not crop or r["crop"].lower()==crop.lower())]
    for r in data:
        r["state"] = state or ""
        r["last_updated"] = now_utc().isoformat()
    return {"prices": data}


# Soil health analysis (mock)
@app.post("/soil-analysis")
def soil_analysis(params: dict):
    ph = params.get("ph", 6.8)
    moisture = params.get("moisture", 45)
    organic = params.get("organic", 1.2)
    advice = []
    if ph < 6.5:
        advice.append("Apply lime to raise pH")
    if organic < 1.5:
        advice.append("Incorporate farmyard manure/compost")
    if moisture < 40:
        advice.append("Schedule drip irrigation every 3 days")
    return {"status": "Moderate", "advice": advice or ["Maintain current practices"]}


# Irrigation planning (mock)
@app.post("/irrigation-plan")
def irrigation_plan(payload: dict):
    crop = payload.get("crop", "Paddy")
    area = float(payload.get("area", 1))
    method = payload.get("method", "drip")
    water_need = 6 if crop.lower()=="paddy" else 3
    efficiency = 0.9 if method == "drip" else 0.7
    daily_liters = area * water_need * 1000 / efficiency
    return {"crop": crop, "area": area, "method": method, "daily_liters": round(daily_liters, 1), "tips": ["Irrigate at dawn", "Mulch to reduce evaporation"]}


# Simple 24/7 chatbot (FAQ + echo)
@app.post("/chat")
def chat(message: dict):
    q = (message.get("text") or "").lower()
    faqs = {
        "loan": "You can apply for subsidized crop loans at your nearest bank under the Interest Subvention scheme.",
        "soil": "Use the Soil Health Card scheme to test your soil for free.",
        "irrigation": "Micro-irrigation (drip/sprinkler) saves up to 40% water.",
    }
    for k, v in faqs.items():
        if k in q:
            return {"reply": v}
    return {"reply": "Thanks for your message. Our advisory team will get back. Meanwhile, check Dashboard and Calendar for guidance."}
