from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
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

class CreateUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    gender: Optional[str] = None

class UpdateUserRequest(BaseModel):
    name: str
    email: str
    phone: str
    city: str
    gender: Optional[str] = None

class EmployeeCreate(BaseModel):
    email: str
    password: str
    role_id: int

class UserPreferencesUpdate(BaseModel):
    offers: bool
    push_channel: bool
    email_channel: bool
    sms_channel: bool
    order_updates: bool
    newsletter: bool

# ---------------- HELPERS ----------------
def hash_password(password: str) -> str:
    # ⚠️ Replace with bcrypt in production
    return password

def admin_only():
    # ⚠️ Replace with real auth / JWT check
    return {"employee_id": 1, "role": "admin"}

def build_default_password(name: str, phone: str) -> str:
    return f"{name.lower().replace(' ', '')}{phone}"

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

@app.post("/auth/employee/login")
def employee_login(payload: EmployeeLoginRequest):
    res = (
        supabase.table("employees")
        .select("employee_id, email, password, role_id")
        .eq("email", payload.email)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    employee = res.data[0]

    if employee["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return employee

# ---------------- ADMIN EMPLOYEES ----------------
@app.get("/admin/employees")
def list_employees(_: dict = Depends(admin_only)):
    res = (
        supabase.table("employees")
        .select("employee_id, email, role_id")
        .order("email")
        .execute()
    )
    return res.data or []

@app.post("/admin/employees")
def create_employee(data: EmployeeCreate, _: dict = Depends(admin_only)):
    supabase.table("employees").insert({
        "email": data.email,
        "password": hash_password(data.password),
        "role_id": data.role_id
    }).execute()
    return {"success": True}

@app.delete("/admin/employees/{employee_id}")
def delete_employee(employee_id: int, user=Depends(admin_only)):
    if employee_id == user["employee_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    supabase.table("employees").delete().eq(
        "employee_id", employee_id
    ).execute()

    return {"success": True}

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
    notification_type_map = {
        "offers": "offers",
        "promotional_offers": "offers",
        "order_updates": "order_updates",
        "newsletter": "newsletter",
        "newsletters": "newsletter",
    }

    input_type = payload.notification_type.strip().lower()
    db_type = notification_type_map.get(input_type)

    if not db_type:
        raise HTTPException(status_code=400, detail="Invalid notification type")

    res = supabase.table("campaigns").insert({
        "campaign_name": payload.campaign_name,
        "notification_type": db_type,
        "city_filter": payload.city_filter,
        "content": payload.content,
        "created_by": payload.created_by,
        "status": "draft",
        "created_at": datetime.utcnow().isoformat(),
    }).execute()

    return res.data[0]

# ---------------- USERS ----------------
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

@app.get("/admin/users")
def get_users():
    return (
        supabase.table("users")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

@app.put("/admin/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest):
    res = (
        supabase.table("users")
        .update(payload.dict(exclude_none=True))
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]

@app.patch("/admin/users/{user_id}/toggle-active")
def toggle_user(user_id: str):
    user = (
        supabase.table("users")
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

@app.get("/users/{user_id}/preferences")
def get_user_preferences(user_id: str):
    res = (
        supabase.table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    return res.data

@app.put("/users/{user_id}/preferences")
def update_user_preferences(user_id: UUID, prefs: UserPreferencesUpdate):
    result = (
        supabase.table("user_preferences")
        .update(prefs.model_dump())
        .eq("user_id", str(user_id))
        .execute()
    )
    return {"message": "Preferences updated", "data": result.data}

@app.post("/admin/users/upload-csv")
def upload_users_csv(file: UploadFile = File(...)):
    content = file.file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(content)

    users, prefs = [], []

    for row in reader:
        if not row.get("name") or not row.get("email") or not row.get("phone"):
            continue

        user_id = str(uuid.uuid4())
        password = build_default_password(row["name"], row["phone"])

        users.append({
            "user_id": user_id,
            "name": row["name"].strip(),
            "email": row["email"].strip(),
            "phone": row["phone"].strip(),
            "city": row.get("city"),
            "gender": row.get("gender"),
            "password": password,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
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
