from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from supabase_client import supabase
from typing import Optional
from uuid import UUID
import uuid
import csv

app = FastAPI()

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- MODELS ----------------
class LoginRequest(BaseModel):
    email: str
    password: str

class EmployeeLoginRequest(BaseModel):
    email: str
    password: str

class CampaignCreate(BaseModel):
    campaign_name: str
    notification_type: str
    city_filter: Optional[str] = None
    content: str
    created_by: int

class CreateUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    gender: Optional[str] = None

# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "ok"}

# ---------------- AUTH ----------------
@app.post("/auth/user/login")
def user_login(payload: LoginRequest):
    res = (
        supabase.table("users")
        .select("*")
        .eq("email", payload.email)
        .eq("is_active", True)
        .execute()
    )

    if not res.data or res.data[0]["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = res.data[0]
    return {"user_id": user["user_id"], "email": user["email"], "name": user["name"]}

@app.post("/auth/employee/login")
def employee_login(payload: EmployeeLoginRequest):
    res = (
        supabase.table("employees")
        .select("employee_id, email, password, role_id")
        .eq("email", payload.email)
        .execute()
    )

    if not res.data or res.data[0]["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    emp = res.data[0]
    return emp

# ---------------- CAMPAIGNS ----------------
@app.get("/campaigns")
def list_campaigns():
    return (
        supabase.table("campaigns")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

@app.post("/campaigns")
def create_campaign(payload: CampaignCreate):
    res = (
        supabase.table("campaigns")
        .insert({
            "campaign_name": payload.campaign_name,
            "notification_type": payload.notification_type,
            "city_filter": payload.city_filter,
            "content": payload.content,
            "created_by": payload.created_by,
            "status": "draft",
        })
        .execute()
    )
    return res.data[0]


from uuid import UUID

@app.get("/campaigns/{campaign_id}/recipients")
def get_campaign_recipients(campaign_id: UUID):
    # 1️⃣ Fetch campaign
    campaign = (
        supabase
        .table("campaigns")
        .select("city_filter, notification_type")
        .eq("campaign_id", str(campaign_id))
        .single()
        .execute()
    )

    if not campaign.data:
        return []

    city = campaign.data["city_filter"]
    notif_type = campaign.data["notification_type"]

    # 2️⃣ Map notification type → preference column
    preference_column = {
        "Promotional Offers": "offers",
        "Order Updates": "order_updates",
        "Newsletter": "newsletter",
    }.get(notif_type)

    if not preference_column:
        return []

    # 3️⃣ Fetch eligible users
    result = (
        supabase
        .table("users")
        .select("""
            user_id,
            name,
            email,
            city,
            user_preferences!inner(
                offers,
                order_updates,
                newsletter
            )
        """)
        .eq("city", city)
        .eq("is_active", True)
        .eq(f"user_preferences.{preference_column}", True)
        .execute()
    )

    return result.data


# ---------------- SEND CAMPAIGN ----------------
@app.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: str):
    recipients = get_campaign_recipients(campaign_id)

    if not recipients:
        return {"sent_to": 0, "status": "no_recipients"}

    logs = [
        {
            "log_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "user_id": u["user_id"],
            "status": "success",
            "sent_at": datetime.utcnow().isoformat(),
        }
        for u in recipients
    ]

    supabase.table("campaign_logs").insert(logs).execute()

    supabase.table("campaigns").update({
        "status": "sent",
        "sent_at": datetime.utcnow().isoformat(),
    }).eq("campaign_id", campaign_id).execute()

    return {"sent_to": len(logs), "status": "sent"}

# ---------------- USERS ----------------
def build_default_password(name: str, phone: str) -> str:
    return f"{name.lower().replace(' ', '')}{phone}"

@app.post("/admin/users")
def create_user(payload: CreateUserRequest):
    user_id = str(uuid.uuid4())
    password = build_default_password(payload.name, payload.phone)

    supabase.table("users").insert({
        "user_id": user_id,
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "city": payload.city,
        "gender": payload.gender,
        "password": password,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()

    supabase.table("user_preferences").insert({
        "user_id": user_id,
        "offers": True,
        "order_updates": True,
        "newsletter": True,
        "email_channel": True,
        "sms_channel": False,
        "push_channel": False,
        "updated_at": datetime.utcnow().isoformat(),
    }).execute()

    return {"user_id": user_id}

@app.get("/users/{user_id}/preferences")
def get_user_preferences(user_id: str):
    res = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Preferences not found")
    return res.data
