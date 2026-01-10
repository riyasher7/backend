from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from supabase_client import supabase
from typing import Optional

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

        print("👉 SUPABASE RESPONSE DATA:", res.data)

        return res.data[0]

    except Exception as e:
        print("❌ ERROR WHILE INSERTING CAMPAIGN:", e)
        raise HTTPException(status_code=500, detail=str(e))
