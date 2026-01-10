from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from supabase_client import supabase

app = FastAPI()

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- MODELS ----------------
class LoginRequest(BaseModel):
    email: str
    password: str

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

    # ⚠️ Plain-text check (OK for demo)
    if user["password"] != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
    }

# ---------------- USER PREFERENCES ----------------
@app.get("/users/{user_id}/preferences")
def get_user_preferences(user_id: str):
    # 1️⃣ Try to fetch existing preferences
    res = (
        supabase
        .table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .execute()
    )

    if res.data:
        return res.data[0]

    # 2️⃣ If not found → create default preferences
    default_prefs = {
        "user_id": user_id,
        "offers": True,
        "order_updates": True,
        "newsletter": True,
        "email_channel": True,
        "sms_channel": False,
        "push_channel": False,
        "updated_at": datetime.utcnow().isoformat(),
    }

    insert_res = (
        supabase
        .table("user_preferences")
        .insert(default_prefs)
        .execute()
    )

    if not insert_res.data:
        raise HTTPException(
            status_code=500,
            detail="Failed to create user preferences"
        )

    return insert_res.data[0]

from pydantic import BaseModel

# ---------------- PREFERENCES MODEL ----------------
class PreferenceUpdate(BaseModel):
    offers: bool
    order_updates: bool
    newsletter: bool
    email_channel: bool
    sms_channel: bool
    push_channel: bool

# ---------------- UPDATE USER PREFERENCES ----------------
@app.put("/users/{user_id}/preferences")
def update_user_preferences(user_id: str, payload: PreferenceUpdate):
    res = (
        supabase
        .table("user_preferences")
        .update(payload.dict())
        .eq("user_id", user_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(
            status_code=500,
            detail="Failed to update preferences"
        )

    return {
        "status": "success",
        "preferences": res.data[0]
    }

class EmployeeLoginRequest(BaseModel):
    email: str
    password: str

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
        "role_id": employee["role_id"],  # ✅ THIS is critical
    }

