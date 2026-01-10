from fastapi import FastAPI, HTTPException, File, UploadFile
import csv
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from supabase_client import supabase
from typing import Optional
from typing import List
import uuid

app = FastAPI()

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:9100",
        "http://127.0.0.1:9100",
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

# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "ok"}

# ---------------- USER LOGIN ----------------
@app.post("/auth/user/login")
def user_login(payload: LoginRequest):
    res = (
        supabase
        .table("users")
        .select("*")
        .eq("email", payload.email)
        .eq("is_active", True)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = res.data[0]

    if user["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
    }

# ---------------- EMPLOYEE LOGIN ----------------
@app.post("/auth/employee/login")
def employee_login(payload: EmployeeLoginRequest):
    res = (
        supabase
        .table("employees")
        .select("employee_id, email, password, role_id")
        .eq("email", payload.email)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    employee = res.data[0]

    if employee["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "employee_id": employee["employee_id"],
        "email": employee["email"],
        "role_id": employee["role_id"],
    }

# ---------------- CAMPAIGNS ----------------
@app.get("/campaigns")
def list_campaigns():
    try:
        res = (
            supabase
            .table("campaigns")
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/campaigns")
def create_campaign(payload: CampaignCreate):
    print("👉 PAYLOAD RECEIVED:", payload)

    try:
        res = (
            supabase
            .table("campaigns")
            .insert({
                "campaign_name": payload.campaign_name,
                "notification_type": payload.notification_type,
                "city_filter": payload.city_filter,
                "content": payload.content,
                "created_by": payload.created_by,  # MUST be int
                "status": "draft",
            })
            .execute()
        )

        print("SUPABASE RESPONSE DATA:", res.data)

        return res.data[0]

    except Exception as e:
        print("ERROR WHILE INSERTING CAMPAIGN:", e)
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- USER MANAGEMENT ----------------

def build_default_password(name: str, phone: str) -> str:
    return f"{name.lower().replace(' ', '')}{phone}"

class CreateUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    gender: str | None = None

@app.post("/admin/users")
def create_user(payload: CreateUserRequest):
    user_id = str(uuid.uuid4())
    password = build_default_password(payload.name, payload.phone)

    user = {
        "user_id": user_id,
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "city": payload.city,
        "gender": payload.gender,
        "password": password,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
    }

    user_res = supabase.table("users").insert(user).execute()

    if not user_res.data:
        raise HTTPException(status_code=500, detail="User creation failed")

    pref = {
        "user_id": user_id,
        "offers": True,
        "order_updates": True,
        "newsletter": True,
        "email_channel": True,
        "sms_channel": False,
        "push_channel": False,
        "updated_at": datetime.utcnow().isoformat(),
    }

    supabase.table("user_preferences").insert(pref).execute()

    return user_res.data[0]

@app.get("/admin/users")
def get_users():
    res = (
        supabase
        .table("users")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

class UpdateUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    gender: str | None = None

@app.put("/admin/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest):
    res = (
        supabase
        .table("users")
        .update(payload.dict(exclude_none=True))
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]

@app.patch("/admin/users/{user_id}/toggle-active")
def toggle_user(user_id: str):
    user = (
        supabase
        .table("users")
        .select("is_active")
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    new_value = not user.data["is_active"]

    supabase.table("users").update({
        "is_active": new_value
    }).eq("user_id", user_id).execute()

    return {"is_active": new_value}

@app.post("/admin/users/upload-csv")
def upload_users_csv(file: UploadFile = File(...)):
    rows = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(rows)

    users = []
    prefs = []

    for row in reader:
        user_id = str(uuid.uuid4())
        password = build_default_password(row["name"], row["phone"])

        users.append({
            "user_id": user_id,
            "name": row["name"],
            "email": row["email"],
            "phone": row["phone"],
            "city": row["city"],
            "gender": row.get("gender"),
            "password": password,
            "is_active": True,
        })

        prefs.append({
            "user_id": user_id,
            "offers": True,
            "order_updates": True,
            "newsletter": True,
            "email_channel": True,
            "sms_channel": False,
            "push_channel": False,
            "updated_at": datetime.utcnow().isoformat(),
        })

    supabase.table("users").insert(users).execute()
    supabase.table("user_preferences").insert(prefs).execute()

    return {"created": len(users)}


@app.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: str):
    # Fetch campaign
    campaign_res = (
        supabase
        .table("campaigns")
        .select("*")
        .eq("campaign_id", campaign_id)
        .single()
        .execute()
    )

    campaign = campaign_res.data
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get eligible recipients
    recipients = get_campaign_recipients(campaign_id)["recipients"]

    logs = []
    for user in recipients:
        logs.append({
            "log_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "user_id": user["user_id"],
            "status": "success",
            "sent_at": datetime.utcnow().isoformat()
        })

    if logs:
        supabase.table("campaign_logs").insert(logs).execute()

    # Update campaign status
    supabase.table("campaigns").update({
        "status": "sent",
        "sent_at": datetime.utcnow().isoformat()
    }).eq("campaign_id", campaign_id).execute()

    return {
        "sent_to": len(logs),
        "status": "sent"
    }

@app.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: str):
    # Fetch campaign
    campaign_res = (
        supabase
        .table("campaigns")
        .select("*")
        .eq("campaign_id", campaign_id)
        .single()
        .execute()
    )

    campaign = campaign_res.data
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Get eligible recipients
    recipients = get_campaign_recipients(campaign_id)["recipients"]

    logs = []
    for user in recipients:
        logs.append({
            "log_id": str(uuid.uuid4()),
            "campaign_id": campaign_id,
            "user_id": user["user_id"],
            "status": "success",
            "sent_at": datetime.utcnow().isoformat()
        })

    if logs:
        supabase.table("campaign_logs").insert(logs).execute()

    # Update campaign status
    supabase.table("campaigns").update({
        "status": "sent",
        "sent_at": datetime.utcnow().isoformat()
    }).eq("campaign_id", campaign_id).execute()

    return {
        "sent_to": len(logs),
        "status": "sent"
    }
