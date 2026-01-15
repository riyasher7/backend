from fastapi import FastAPI, HTTPException, File, UploadFile, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime, timedelta
from supabase_client import supabase
from typing import Optional
from uuid import UUID
import uuid
import csv
import io
import secrets
import bcrypt
from ws import router as ws_router
from websocket_manager import manager
import re
from typing import Optional

app = FastAPI()

app.include_router(ws_router)

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://localhost:9100",
        "http://127.0.0.1:9100",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add this helper function near the top of main.py (after imports)
def is_valid_email(email: str) -> bool:
    """
    Validate email format using regex
    """
    # RFC 5322 compliant email regex (simplified version)
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_pattern, email) is not None

def validate_email(email: str) -> str:
    """
    Validate and normalize email
    Raises HTTPException if invalid
    """
    if not email or not email.strip():
        raise HTTPException(status_code=400, detail="Email is required")
    
    email = email.strip().lower()  # Normalize: trim and lowercase
    
    if not is_valid_email(email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    if len(email) > 254:  # RFC 5321
        raise HTTPException(status_code=400, detail="Email is too long")
    
    return email

# ---------------- SESSION STORAGE ----------------
# In production, use Redis or a database for session storage
active_sessions = {}

# ---------------- MODELS ----------------
class LoginRequest(BaseModel):
    email: str
    password: str

class EmployeeLoginRequest(BaseModel):
    email: str
    password: str

class CampaignCreate(BaseModel):
    campaign_name: str
    city_filter: Optional[str] = None
    content: str
    created_by: UUID

class NewsletterCreate(BaseModel):
    news_name: str
    city_filter: Optional[str] = None
    content: str
    created_by: UUID

class EmployeeCreate(BaseModel):
    name: str
    email: str
    password: str
    role_id: int

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

class SignUp(BaseModel):
    name: str
    email: EmailStr
    password: str
    gender: str
    city: str
    phone: str

class CampaignSendRequest(BaseModel):
    schedule_after_minutes: Optional[int] = 0


# ---------------- AUTHENTICATION HELPERS ----------------
def hash_password(password: str) -> str:
    """Hash a password using bcrypt"""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_session_token() -> str:
    """Generate a secure random session token"""
    return secrets.token_urlsafe(32)

def create_session(user_id: str, role_id: int, email: str) -> str:
    """Create a new session and return the token"""
    token = create_session_token()
    active_sessions[token] = {
        "user_id": user_id,
        "role_id": role_id,
        "email": email,
        "created_at": datetime.utcnow(),
        "expires_at": datetime.utcnow() + timedelta(days=7)  # 7 day expiry
    }
    return token

def get_current_user(authorization: Optional[str] = Header(None)):
    """Dependency to get current authenticated user"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    # Extract token (supports both "Bearer TOKEN" and just "TOKEN")
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    session = active_sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    # Check if session has expired
    if datetime.utcnow() > session["expires_at"]:
        del active_sessions[token]
        raise HTTPException(status_code=401, detail="Session expired")
    
    return session

def admin_only(authorization: Optional[str] = Header(None)):
    """Dependency to ensure user is an admin"""
    user = get_current_user(authorization)
    if user["role_id"] != 1:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def build_default_password(name: str, phone: str) -> str:
    return f"{name.lower().replace(' ', '')}{phone}"

# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "ok"}

# ---------------- AUTH ----------------
@app.post("/auth/user/login")
def user_login(payload: LoginRequest):
    email = validate_email(payload.email)
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

    # Verify password hash
    if not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create session
    token = create_session(user["user_id"], user["role_id"], user["email"])

    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
        "role_id": user["role_id"],
        "session_token": token
    }

@app.post("/auth/user/signup")
def user_signup(payload: SignUp):

    email = validate_email(payload.email)

    existing = (
        supabase
        .table("users")
        .select("*")
        .eq("email", payload.email)
        .execute()
    )
    if existing.data:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    hashed_password = hash_password(payload.password)

    supabase.table("users").insert({
        "user_id": user_id,
        "name": payload.name,
        "email": payload.email,
        "password": hashed_password,
        "phone": payload.phone,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
        "gender": payload.gender,
        "city": payload.city,
        "role_id": 4,
    }).execute()

    supabase.table("user_preferences").insert({
        "user_id": user_id,
        "offers": True,
        "order_updates": True,
        "newsletter": True
    }).execute()

    supabase.table("notification_type").insert({
        "user_id": user_id
    }).execute()

    # Create session for new user
    token = create_session(user_id, 4, payload.email)

    return {
        "user_id": user_id,
        "email": payload.email,
        "name": payload.name,
        "session_token": token
    }

@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(None)):
    """Logout and invalidate session"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    
    if token in active_sessions:
        del active_sessions[token]
    
    return {"message": "Logged out successfully"}

@app.get("/auth/me")
def get_current_user_info(user: dict = Depends(get_current_user)):
    """Get current authenticated user information"""
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "role_id": user["role_id"]
    }

@app.get("/admin/employeesmgmt")
def list_employees(user: dict = Depends(admin_only)):
    
    res = (
        supabase.table("users")
        .select("user_id, name, email, role_id")
        .in_("role_id", [1, 2, 3])  
        .order("email")
        .execute()
    )
    return res.data or []

@app.post("/admin/employeesmgmt")
def create_employee(data: EmployeeCreate, user: dict = Depends(admin_only)):
    email = validate_email(data.email)
    hashed_password = hash_password(data.password)
    
    supabase.table("users").insert({
        "name": data.name,
        "email": data.email,
        "password": hashed_password,
        "role_id": data.role_id,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
    return {"success": True}

@app.delete("/admin/employeesmgmt/{employee_id}")
def delete_employee(employee_id: int, user: dict = Depends(admin_only)):
    if employee_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    supabase.table("users").delete().eq(
        "user_id", employee_id
    ).execute()

    return {"success": True}

# ---------------- CAMPAIGNS ----------------
@app.get("/campaigns")
def list_campaigns(user: dict = Depends(get_current_user)):
    now = datetime.utcnow().isoformat()

    return (
        supabase
        .table("campaigns")
        .select("*")
        .lte("created_at", now)   # 👈 filter added
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

@app.post("/campaigns")
def create_campaign(payload: CampaignCreate, user: dict = Depends(get_current_user)):
    res = (
        supabase
        .table("campaigns")
        .insert({
            "campaign_name": payload.campaign_name,
            "city_filter": payload.city_filter,
            "content": payload.content,
            "created_by": str(payload.created_by),
            "status": "DRAFT",
            "created_at": datetime.utcnow().isoformat(),
        })
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create campaign")

    return res.data[0]

def get_eligible_users_for_campaign(campaign_id: UUID):
    campaign = (
        supabase.table("campaigns")
        .select("*")
        .eq("campaign_id", str(campaign_id))
        .single()
        .execute()
        .data
    )

    if not campaign:
        return []

    users = (
        supabase.table("users")
        .select("user_id, name, email, city, user_preferences(*)")
        .eq("is_active", True)
        .eq("role_id", 4)
        .execute()
        .data
    )

    pref_key = "offers"
    eligible = []

    for user in users:
        prefs = user.get("user_preferences")
        if not prefs:
            continue

        if prefs.get(pref_key) is not True:
            continue

        if campaign["city_filter"]:
            if not user["city"] or user["city"].lower() != campaign["city_filter"].lower():
                continue

        eligible.append({
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "city": user["city"],
        })

    return eligible

@app.get("/campaigns/{campaign_id}/recipients")
def get_campaign_recipients(campaign_id: UUID, user: dict = Depends(get_current_user)):
    recipients = get_eligible_users_for_campaign(campaign_id)
    return {"recipients": recipients}

@app.post("/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: UUID, body: CampaignSendRequest, user: dict = Depends(get_current_user)):
    recipients = get_eligible_users_for_campaign(campaign_id)

    if not recipients:
        return {"status": "sent", "sent_to": 0}

    now_dt = datetime.utcnow()
    delay_minutes = body.schedule_after_minutes or 0
    send_dt = now_dt + timedelta(minutes=delay_minutes)

    now = now_dt.isoformat()
    send_at = send_dt.isoformat()


    campaign = (
        supabase.table("campaigns")
        .select("*")
        .eq("campaign_id", str(campaign_id))
        .single()
        .execute()
        .data
    )

    title = campaign.get("campaign_name", "New Campaign") if campaign else "New Campaign"
    content = campaign.get("content", "") if campaign else ""

    logs = []
    success_count = 0
    queued_count = 0
    for recipient in recipients:
        is_scheduled = delay_minutes > 0
        print(is_scheduled)
        success = False

        if not is_scheduled:
            try:
                success = await manager.send_to_user(
                    str(recipient["user_id"]),
                    {
                        "type": "CAMPAIGN",
                        "campaign_id": str(campaign_id),
                        "title": title,
                        "content": content,
                    }
                )
            except Exception:
                success = False

        if is_scheduled or not success:
            queued_count += 1
            try:
                supabase.table("pending_notifications").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": recipient["user_id"],
                    "payload": {
                        "type": "CAMPAIGN",
                        "campaign_id": str(campaign_id),
                        "title": title,
                        "content": content,
                        "send_at": send_at
                    },
                    "created_at": now,
                }).execute()
            except Exception:
                print("Warning: failed to queue notification for user", recipient["user_id"])
        else:
            success_count += 1

        logs.append({
            "log_id": str(uuid.uuid4()),
            "user_id": recipient["user_id"],
            "notification_type": "CAMPAIGN",
            "status": "PENDING" if is_scheduled else "SUCCESS",
            "sent_at": send_at,
        })


    try:
        supabase.table("notification_logs").insert(logs).execute()
    except Exception:
        print("Warning: failed to insert notification logs")

    try:
        supabase.table("campaigns").update({
        "status": "SCHEDULED" if delay_minutes > 0 else "SENT"
    }).eq("campaign_id", str(campaign_id)).execute()

    except Exception:
        print("Warning: failed to update campaign status")

    return {
        "status": "SCHEDULED" if delay_minutes > 0 else "SENT",
        "send_at": send_at,
        "sent_to": len(recipients),
        "success_count": success_count,
        "queued_count": queued_count,
        "failed_count": len(recipients) - success_count - queued_count
    }


@app.post("/test/notify/{user_id}")
async def test_notify(user_id: str, message: Optional[str] = None, auth_user: dict = Depends(get_current_user)):
    """Send a simple test notification to a connected user and log the attempt."""
    payload = {
        "type": "TEST",
        "message": message or "Test notification",
    }
    sent = False
    queued = False
    try:
        sent = await manager.send_to_user(user_id, payload)
    except Exception:
        sent = False

    if not sent:
        queued = True
        try:
            supabase.table("pending_notifications").insert({
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "payload": payload,
                "created_at": datetime.utcnow().isoformat(),
            }).execute()
        except Exception:
            print("Warning: failed to queue test notification for user", user_id)

    # mark log as SUCCESS (delivered now or queued for later)
    try:
        supabase.table("notification_logs").insert({
            "log_id": str(uuid.uuid4()),
            "user_id": user_id,
            "notification_type": "TEST",
            "status": "SUCCESS",
            "sent_at": datetime.utcnow().isoformat(),
        }).execute()
    except Exception:
        print("Warning: failed to insert test notification log")

    return {"sent": sent, "queued": queued}


@app.get("/newsletters")
async def list_newsletters(user: dict = Depends(get_current_user)):
    return (
        supabase
        .table("newsletters")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

@app.post("/newsletters")
def create_newsletter(payload: NewsletterCreate, user: dict = Depends(get_current_user)):
    res = (
        supabase
        .table("newsletters")
        .insert({
            "news_name": payload.news_name,
            "city_filter": payload.city_filter,
            "content": payload.content,
            "created_by": str(payload.created_by),
            "status": "DRAFT",
            "created_at": datetime.utcnow().isoformat(),
        })
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create newsletter")

    return res.data[0]

def get_eligible_users_for_newsletter(newsletter_id: UUID):
    newsletter = (
        supabase.table("newsletters")
        .select("*")
        .eq("newsletter_id", str(newsletter_id))
        .single()
        .execute()
        .data
    )

    if not newsletter:
        return []

    users = (
        supabase.table("users")
        .select("user_id, name, email, city, user_preferences(*)")
        .eq("is_active", True)
        .eq("role_id", 4)
        .execute()
        .data
    )

    pref_key = "newsletter"
    eligible = []

    for user in users:
        prefs = user.get("user_preferences")
        if not prefs:
            continue

        if prefs.get(pref_key) is not True:
            continue

        if newsletter["city_filter"]:
            if not user["city"] or user["city"].lower() != newsletter["city_filter"].lower():
                continue

        eligible.append({
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "city": user["city"],
        })

    return eligible

@app.get("/newsletters/{newsletter_id}/recipients")
def get_newsletter_recipients(newsletter_id: UUID, user: dict = Depends(get_current_user)):
    recipients = get_eligible_users_for_newsletter(newsletter_id)
    return {"recipients": recipients}

@app.post("/newsletters/{newsletter_id}/send")
async def send_newsletter(newsletter_id: UUID, user: dict = Depends(get_current_user)):
    recipients = get_eligible_users_for_newsletter(newsletter_id)

    if not recipients:
        return {"status": "SENT", "sent_to": 0, "success_count": 0, "queued_count": 0, "failed_count": 0}

    now = datetime.utcnow().isoformat()

    newsletter = (
        supabase.table("newsletters")
        .select("*")
        .eq("newsletter_id", str(newsletter_id))
        .single()
        .execute()
        .data
    )

    title = newsletter.get("news_name", "Newsletter") if newsletter else "Newsletter"
    content = newsletter.get("content", "") if newsletter else ""

    logs = []
    success_count = 0
    queued_count = 0

    for recipient in recipients:
        success = False
        try:
            success = await manager.send_to_user(
                str(recipient["user_id"]),
                {
                    "type": "NEWSLETTER",
                    "newsletter_id": str(newsletter_id),
                    "title": title,
                    "content": content,
                }
            )
        except Exception:
            success = False

        if not success:
            queued_count += 1
            try:
                supabase.table("pending_notifications").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": recipient["user_id"],
                    "payload": {
                        "type": "NEWSLETTER",
                        "newsletter_id": str(newsletter_id),
                        "title": title,
                        "content": content,
                    },
                    "created_at": now,
                }).execute()
            except Exception:
                print("Warning: failed to queue newsletter for user", user["user_id"])
        else:
            success_count += 1

        # record log as SUCCESS for sent or queued
        logs.append({
            "log_id": str(newsletter_id),
            "user_id": recipient["user_id"],
            "notification_type": "NEWSLETTER",
            "status": "SUCCESS",
            "sent_at": now,
        })

    try:
        supabase.table("notification_logs").insert(logs).execute()
    except Exception:
        print("Warning: failed to insert newsletter notification logs")

    try:
        supabase.table("newsletters").update({
            "status": "SENT"
        }).eq("newsletter_id", str(newsletter_id)).execute()
    except Exception:
        print("Warning: failed to update newsletter status")

    return {
        "status": "SENT",
        "sent_to": len(recipients),
        "success_count": success_count,
        "queued_count": queued_count,
        "failed_count": len(recipients) - success_count - queued_count
    }

@app.get("/users/{user_id}/notifications")
def get_user_notifications(user_id: str):
    try:
        res = (
            supabase
            .table("pending_notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = res.data or []
    except Exception:
        print("Warning: failed to read pending_notifications for", user_id)
        data = []

    # normalize payloads to a consistent shape for the frontend
    out = []
    for row in data:
        payload = row.get("payload") or {}
        title = payload.get("title")
        content = payload.get("content") or ""
        out.append({
            "id": row.get("log_id"),
            "title": title,
            "content": content,
            "created_at": row.get("created_at"),
            "type": payload.get("type") or row.get("notification_type"),
        })

    return out

# ---------------- USERS ----------------
def build_default_password(name: str, phone: str) -> str:
    return f"{name.lower().replace(' ', '')}{phone}"

@app.post("/admin/users")
def create_user(payload: CreateUserRequest, user: dict = Depends(admin_only)):
    email = validate_email(payload.email)
    user_id = str(uuid.uuid4())
    password = build_default_password(payload.name, payload.phone)
    hashed_password = hash_password(password)

    supabase.table("users").insert({
        "user_id": user_id,
        "name": payload.name,
        "email": payload.email,
        "phone": payload.phone,
        "city": payload.city,
        "gender": payload.gender,
        "password": hashed_password,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
        "role_id": 4,
    }).execute()

    supabase.table("user_preferences").insert({
        "user_id": user_id,
        "offers": True,
        "order_updates": True,
        "newsletter": True,
    }).execute()

    supabase.table("notification_type").insert({
        "user_id": user_id,
        "email": True,
        "sms": True,
        "push": True,
    }).execute()

    return {"user_id": user_id}

@app.get("/admin/users")
def get_users(user: dict = Depends(admin_only)):
    res = (
        supabase
        .table("users")
        .select("*")
        .eq("role_id", 4)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

@app.put("/admin/users/{user_id}")
def update_user(user_id: str, payload: UpdateUserRequest, user: dict = Depends(admin_only)):
    res = (
        supabase
        .table("users")
        .update(payload.dict(exclude_none=True))
        .eq("user_id", user_id)
        .execute()
    )
    return res.data[0]

@app.patch("/admin/users/{user_id}/toggle-active")
def toggle_user(user_id: str, user: dict = Depends(admin_only)):
    target_user = (
        supabase
        .table("users")
        .select("is_active")
        .eq("user_id", user_id)
        .single()
        .execute()
    )

    new_value = not target_user.data["is_active"]

    supabase.table("users").update({
        "is_active": new_value
    }).eq("user_id", user_id).execute()

    return {"is_active": new_value}

@app.get("/users/{user_id}/preferences")
def get_user_preferences(user_id: str, user: dict = Depends(get_current_user)):
    res = (
        supabase
        .table("user_preferences")
        .select("*")
        .eq("user_id", user_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Preferences not found")
    return res.data

class UserPreferencesUpdate(BaseModel):
    offers: Optional[bool] = None
    order_updates: Optional[bool] = None
    newsletter: Optional[bool] = None

    campaign_email: Optional[bool] = None
    campaign_sms: Optional[bool] = None
    campaign_push: Optional[bool] = None

    newsletter_email: Optional[bool] = None
    newsletter_sms: Optional[bool] = None
    newsletter_push: Optional[bool] = None

    update_email: Optional[bool] = None
    update_sms: Optional[bool] = None
    update_push: Optional[bool] = None

@app.put("/users/{user_id}/preferences")
def update_user_preferences(
    user_id: UUID,
    prefs: UserPreferencesUpdate,
    user: dict = Depends(get_current_user)
):
    data = prefs.model_dump(exclude_none=True)
    resp = {"preferences": None, "notification_type": None}

    user_fields = {k: data[k] for k in ("offers", "order_updates", "newsletter") if k in data}
    if user_fields:
        res = (
            supabase
            .table("user_preferences")
            .update(user_fields)
            .eq("user_id", str(user_id))
            .execute()
        )
        resp["preferences"] = res.data

    channel_keys = (
        "campaign_email", "campaign_sms", "campaign_push",
        "newsletter_email", "newsletter_sms", "newsletter_push",
        "update_email", "update_sms", "update_push",
    )
    notif_fields = {k: data[k] for k in channel_keys if k in data}
    if notif_fields:
        payload = {"user_id": str(user_id), **notif_fields}
        res2 = supabase.table("notification_type").upsert(payload).execute()
        resp["notification_type"] = res2.data

    return {"success": True, "data": resp}

class NotificationChannelUpdate(BaseModel):
    email: bool
    sms: bool
    push: bool

@app.put("/users/{user_id}/channels")
def update_notification_channels(
    user_id: UUID,
    channels: NotificationChannelUpdate,
    user: dict = Depends(get_current_user)
):
    res = (
        supabase
        .table("notification_type")
        .update(channels.model_dump())
        .eq("user_id", str(user_id))
        .execute()
    )
    return {"success": True, "data": res.data}

@app.get("/users/{user_id}/channels")
def get_notification_channels(user_id: UUID, user: dict = Depends(get_current_user)):
    res = (
        supabase
        .table("notification_type")
        .select("*")
        .eq("user_id", str(user_id))
        .single()
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=404, detail="Channels not found")

    return res.data

@app.post("/admin/employeesmgmt")
def create_employee(data: EmployeeCreate, user: dict = Depends(admin_only)):
    # Validate email
    email = validate_email(data.email)
    
    hashed_password = hash_password(data.password)
    
    supabase.table("users").insert({
        "name": data.name,
        "email": email,  # Use validated email
        "password": hashed_password,
        "role_id": data.role_id,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
    return {"success": True}


# 4. Update create_user endpoint
@app.post("/admin/users")
def create_user(payload: CreateUserRequest, user: dict = Depends(admin_only)):
    # Validate email
    email = validate_email(payload.email)
    
    user_id = str(uuid.uuid4())
    password = build_default_password(payload.name, payload.phone)
    hashed_password = hash_password(password)

    supabase.table("users").insert({
        "user_id": user_id,
        "name": payload.name,
        "email": email,  # Use validated email
        "phone": payload.phone,
        "city": payload.city,
        "gender": payload.gender,
        "password": hashed_password,
        "is_active": True,
        "created_at": datetime.utcnow().isoformat(),
        "role_id": 4,
    }).execute()

    # ... rest of the code


# 5. Update CSV upload endpoint
@app.post("/admin/users/upload-csv")
async def upload_users_csv(
    file: UploadFile = File(...),
    user: dict = Depends(admin_only)
):
    try:
        contents = await file.read()
        text = contents.decode("utf-8", errors="replace")
        stream = io.StringIO(text)
        reader = csv.DictReader(stream)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid CSV file")

    users = []
    errors = []

    for row_num, row in enumerate(reader, start=2):
        if not row.get("name") or not row.get("email") or not row.get("phone"):
            errors.append(f"Row {row_num}: Missing required fields")
            continue

        # Validate email
        try:
            email = validate_email(row["email"])
        except HTTPException as e:
            errors.append(f"Row {row_num}: {e.detail}")
            continue

        user_id = str(uuid.uuid4())
        password = build_default_password(row["name"], row["phone"])
        hashed_password = hash_password(password)

        users.append({
            "user_id": user_id,
            "name": row["name"].strip(),
            "email": email,
            "phone": row["phone"].strip(),
            "city": (row.get("city") or "").strip() or None,
            "gender": (row.get("gender") or "").strip() or None,
            "password": hashed_password,
            "is_active": True,
            "created_at": datetime.utcnow().isoformat(),
            "role_id": 4,
        })

        prefs.append({
            "user_id": user_id,
            "offers": True,
            "order_updates": True,
            "newsletter": True,
        })

        type_data.append({
            "user_id": user_id,
            "campaign_email": True,
            "campaign_sms": True,
            "campaign_push": True,
            "newsletter_email": True,
            "newsletter_sms": True,
            "newsletter_push": True,
            "update_email": True,
            "update_sms": True,
            "update_push": True,
        })

    if not users:
        raise HTTPException(status_code=400, detail="No valid users found in CSV")

    # Check for existing emails to avoid duplicates
    # Check for existing emails to avoid duplicates
    emails = [u["email"] for u in users]
    try:
        existing_res = (
            supabase.table("users")
            .select("email")
            .in_("email", emails)
            .execute()
        )
        existing_emails = {r["email"] for r in (existing_res.data or [])}
    except Exception as e:
        print("Error checking existing emails:", e)
        existing_emails = set()


    to_insert_users = [u for u in users if u["email"] not in existing_emails]
    if not to_insert_users:
        raise HTTPException(status_code=400, detail="All emails already exist")

    prefs_to_insert = [
        {"user_id": u["user_id"], "offers": True, "order_updates": True, "newsletter": True}
        for u in to_insert_users
    ]
    types_to_insert = [
        {"user_id": u["user_id"], "email": True, "sms": True, "push": True}
        for u in to_insert_users
    ]

    # Insert into Supabase
    try:
        supabase.table("users").insert(to_insert_users).execute()
        supabase.table("user_preferences").insert(prefs_to_insert).execute()
        supabase.table("notification_type").insert(types_to_insert).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to insert users: {str(e)}")

    inserted_count = len(to_insert_users)

    return {
        "message": "Users uploaded successfully",
        "requested": len(users),
        "inserted": inserted_count,
        "skipped_existing": len(users) - inserted_count
    }


class CreateOrderRequest(BaseModel):
    order_name: str

@app.post("/users/{user_id}/orders")
def create_order(user_id: UUID, payload: CreateOrderRequest, user: dict = Depends(get_current_user)):
    order_id = str(uuid.uuid4())

    res = (
        supabase
        .table("orders")
        .insert({
            "order_id": order_id,
            "user_id": str(user_id),
            "order_name": payload.order_name,
            "status": "PLACED",
        })
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create order")

    return res.data[0]

@app.get("/admin/orders")
def admin_orders(user: dict = Depends(admin_only)):
    res = (
        supabase
        .table("orders")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

@app.get("/users/{user_id}/orders")
def get_user_orders(user_id: UUID, user: dict = Depends(get_current_user)):
    res = (
        supabase
        .table("orders")
        .select("*")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []

@app.post("/users/{user_id}/orders/{order_id}/request-update")
def request_order_update(user_id: UUID, order_id: UUID, user: dict = Depends(get_current_user)):
    supabase.table("orders").update({
        "status": "UPDATE_REQUESTED"
    }).eq("order_id", str(order_id)).eq("user_id", str(user_id)).execute()

    supabase.table("notification_logs").insert({
        "log_id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "notification_type": "ORDER_UPDATE",
        "status": "PENDING",
        "sent_at": datetime.utcnow().isoformat(),
    }).execute()

    return {"message": "Update requested"}

@app.post("/admin/users/{user_id}/orders/{order_id}/send-update")
def send_order_update(user_id: UUID, order_id: UUID, user: dict = Depends(admin_only)):
    supabase.table("orders").update({
        "status": "SENT"
    }).eq("order_id", str(order_id)).execute()

    supabase.table("notification_logs").insert({
        "log_id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "notification_type": "ORDER_UPDATE",
        "status": "SUCCESS",
        "sent_at": datetime.utcnow().isoformat(),
    }).execute()

    return {"message": "Order update sent"}

# Add this endpoint to your main.py file

# ---------------- NOTIFICATION LOGS ----------------
@app.get("/admin/notification-logs")
def get_notification_logs(user: dict = Depends(get_current_user)):
    """
    Get all notification logs.
    Can be accessed by authenticated users.
    Admins can see all logs, users can see their own.
    """
    try:
        # If admin, return all logs
        if user["role_id"] == 1:
            res = (
                supabase
                .table("notification_logs")
                .select("*")
                .order("sent_at", desc=True)
                .execute()
            )
        else:
            # Regular users see only their own logs
            res = (
                supabase
                .table("notification_logs")
                .select("*")
                .eq("user_id", user["user_id"])
                .order("sent_at", desc=True)
                .execute()
            )
        
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch logs: {str(e)}")

@app.get("/admin/notification-logs/campaign/{campaign_id}")
def get_campaign_logs(campaign_id: UUID, user: dict = Depends(get_current_user)):
    """Get logs for a specific campaign"""
    try:
        res = (
            supabase
            .table("notification_logs")
            .select("*")
            .eq("log_id", str(campaign_id))
            .order("sent_at", desc=True)
            .execute()
        )
        
        return res.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch campaign logs: {str(e)}")

@app.get("/admin/notification-logs/stats")
def get_notification_stats(user: dict = Depends(admin_only)):
    """Get notification statistics"""
    try:
        res = (
            supabase
            .table("notification_logs")
            .select("*")
            .execute()
        )
        
        logs = res.data or []
        
        total = len(logs)
        success = len([log for log in logs if log["status"] == "SUCCESS"])
        failed = len([log for log in logs if log["status"] == "FAILED"])
        
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": round((success / total * 100) if total > 0 else 0, 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")