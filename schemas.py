"""
Database Schemas for Smart Crop Advisory

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
"""
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from datetime import datetime


class Farmer(BaseModel):
    farmer_id: str = Field(..., description="Unique Farmer ID")
    name: Optional[str] = Field(None, description="Full name of the farmer")
    phone: str = Field(..., description="Mobile phone number")
    aadhaar: Optional[str] = Field(None, description="Aadhaar number (optional)")
    language: Optional[str] = Field("en", description="Preferred language code")
    location: Optional[str] = Field(None, description="Village/City, District, State")
    crops: Optional[List[str]] = Field(default_factory=list, description="Primary crops")
    soil_type: Optional[str] = Field(None, description="Soil type (e.g., loam, clay)")


class OTPRequest(BaseModel):
    farmer_id: Optional[str] = None
    phone: str
    otp: str
    expires_at: datetime
    verified: bool = False


class Session(BaseModel):
    farmer_id: str
    token: str
    created_at: datetime
    expires_at: datetime


class Recommendation(BaseModel):
    farmer_id: str
    crop: str
    score: float
    reason: str


class Notification(BaseModel):
    farmer_id: str
    title: str
    message: str
    level: str = Field("info", description="info|warning|critical")
    created_at: datetime


class CropCalendarItem(BaseModel):
    farmer_id: str
    crop: str
    phase: str = Field(..., description="sowing|irrigation|fertilizer|pest|harvest")
    date: datetime
    note: Optional[str] = None


class Scheme(BaseModel):
    name: str
    description: str
    state: Optional[str] = None
    crop_types: Optional[List[str]] = None
    benefit: Optional[str] = None
    link: Optional[str] = None
