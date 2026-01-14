from fastapi import FastAPI, HTTPException, File, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from datetime import datetime
from supabase_client import supabase
from typing import Optional
from uuid import UUID
import uuid
import csv
from ws import router as ws_router
from websocket_manager import manager

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



def admin_only():
    return {"employee_id" : 1, "role" : "admin"}
# ---------------- ROOT ----------------
@app.get("/")
def root():
    return {"status": "ok"}

# ---------------- AUTH ----------------
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
        "role_id": user["role_id"],
    }

@app.post("/auth/user/signup")
def user_signup(payload: SignUp):
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
    supabase.table("users").insert({
        "user_id": user_id,
        "name": payload.name,
        "email": payload.email,
        "password": payload.password,
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

    return {"user_id": user_id, "email": payload.email, "name": payload.name}

@app.get("/admin/employeesmgmt")
def list_employees(_: dict = Depends(admin_only)):
    res = (
        supabase.table("users")
        .select("user_id, name, email, role_id")
        .in_("role_id", [1, 2, 3])  
        .order("email")
        .execute()
    )
    return res.data or []


@app.post("/admin/employeesmgmt")
def create_employee(data: EmployeeCreate, _: dict = Depends(admin_only)):
    supabase.table("users").insert({
        "name": data.name,
        "email": data.email,
        "password": data.password,
        "role_id": data.role_id,
        "created_at": datetime.utcnow().isoformat(),
    }).execute()
    return {"success": True}

@app.delete("/admin/employeesmgmt/{employee_id}")
def delete_employee(employee_id: int, user=Depends(admin_only)):
    if employee_id == user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    supabase.table("users").delete().eq(
        "user_id", employee_id
    ).execute()

    return {"success": True}
# ---------------- CAMPAIGNS ----------------
@app.get("/campaigns")
def list_campaigns():
    return (
        supabase
        .table("campaigns")
        .select("*")
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )

@app.post("/campaigns")
def create_campaign(payload: CampaignCreate):
    res = (
        supabase
        .table("campaigns")
        .insert({
            "campaign_name": payload.campaign_name,
            #"notification_type": "promotional_offers",
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
def get_campaign_recipients(campaign_id: UUID):
    recipients = get_eligible_users_for_campaign(campaign_id)
    return {"recipients": recipients}

@app.post("/campaigns/{campaign_id}/send")
async def send_campaign(campaign_id: UUID):
    recipients = get_eligible_users_for_campaign(campaign_id)

    if not recipients:
        return {"status": "sent", "sent_to": 0}

    now = datetime.utcnow().isoformat()

    # fetch campaign details to include message content/title in payload
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
    for user in recipients:
        success = False
        try:
            success = await manager.send_to_user(
                str(user["user_id"]),
                {
                    "type": "CAMPAIGN",
                    "campaign_id": str(campaign_id),
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
                    "user_id": user["user_id"],
                    "payload": {
                        "type": "CAMPAIGN",
                        "campaign_id": str(campaign_id),
                        "title": title,
                        "content": content,
                    },
                    "created_at": now,
                }).execute()
            except Exception:
                print("Warning: failed to queue notification for user", user["user_id"])
        else:
            success_count += 1

        # record log as SUCCESS for sent or queued so admin sees it as accepted
        logs.append({
            "log_id": str(campaign_id),
            "user_id": user["user_id"],
            "notification_type": "CAMPAIGN",
            "status": "SUCCESS",
            "sent_at": now,
        })

    # write logs (best-effort)
    try:
        supabase.table("notification_logs").insert(logs).execute()
    except Exception:
        print("Warning: failed to insert notification logs")


    try:
        supabase.table("campaigns").update({
            "status": "SENT"
        }).eq("campaign_id", str(campaign_id)).execute()
    except Exception:
        print("Warning: failed to update campaign status")

    return {
        "status": "SENT",
        "sent_to": len(recipients),
        "success_count": success_count,
        "queued_count": queued_count,
        "failed_count": len(recipients) - success_count - queued_count
    }


@app.post("/test/notify/{user_id}")
async def test_notify(user_id: str, message: Optional[str] = None):
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
def list_newsletters():
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
def create_newsletter(payload: NewsletterCreate):
    res = (
        supabase
        .table("newsletters")
        .insert({
            "news_name": payload.news_name,
            #"notification_type": "promotional_offers",
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

    pref_key = "newsletters"
    eligible = []
    pref_key = "newsletter"

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
def get_newsletter_recipients(newsletter_id: UUID):
    recipients = get_eligible_users_for_newsletter(newsletter_id)
    return {"recipients": recipients}

@app.post("/newsletters/{newsletter_id}/send")
async def send_newsletter(newsletter_id: UUID):
    recipients = get_eligible_users_for_newsletter(newsletter_id)

    if not recipients:
        return {"status": "SENT", "sent_to": 0, "success_count": 0, "queued_count": 0, "failed_count": 0}

    now = datetime.utcnow().isoformat()

    # fetch newsletter details to include content/title
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

    for user in recipients:
        success = False
        try:
            success = await manager.send_to_user(
                str(user["user_id"]),
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
                    "user_id": user["user_id"],
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
            "user_id": user["user_id"],
            "notification_type": "NEWSLETTER",
            "status": "SUCCESS",
            "sent_at": now,
        })

    # write logs (best-effort)
    try:
        supabase.table("notification_logs").insert(logs).execute()
    except Exception:
        print("Warning: failed to insert newsletter notification logs")

    # update newsletter status (best-effort)
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
def get_user_notifications(user_id: str, limit: int = 50):
    try:
        res = (
            supabase
            .table("pending_notifications")
            .select("*")
            .eq("user_id", user_id)
            .order("sent_at", desc=True)
            .limit(limit)
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
            "sent_at": row.get("sent_at"),
            "type": payload.get("type") or row.get("notification_type"),
        })

    return out


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
def get_users():
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

@app.get("/users/{user_id}/preferences")
def get_user_preferences(user_id: str):
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
    prefs: UserPreferencesUpdate
):
    # only include fields that were provided (avoid overwriting with None)
    data = prefs.model_dump(exclude_none=True)

    resp = {"preferences": None, "notification_type": None}

    # update top-level user_preferences columns if present
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

    # update/insert notification_type row when any channel fields are provided
    channel_keys = (
        "campaign_email",
        "campaign_sms",
        "campaign_push",
        "newsletter_email",
        "newsletter_sms",
        "newsletter_push",
        "update_email",
        "update_sms",
        "update_push",
    )
    notif_fields = {k: data[k] for k in channel_keys if k in data}
    if notif_fields:
        payload = {"user_id": str(user_id), **notif_fields}
        # upsert so we create a row if one doesn't exist, or update if it does
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
    channels: NotificationChannelUpdate
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
def get_notification_channels(user_id: UUID):
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

@app.post("/admin/users/upload-csv")
def upload_users_csv(file: UploadFile = File(...)):
    try:
        content = file.file.read().decode("utf-8").splitlines()
        reader = csv.DictReader(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid CSV file")

    users = []
    prefs = []
    type = []

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
            "city": row["city"],
            "gender": row.get("gender"),
            "password": password,
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

        type.append({
            "user_id": user_id,
            "email": True,
            "sms": True,
            "push": True,
        })
    

    if not users:
        raise HTTPException(status_code=400, detail="No valid users found in CSV")
    
    user_res = supabase.table("users").insert(users).execute()
    if not user_res.data:
        raise HTTPException(status_code=500, detail="Failed to insert users")
    
    pref_res = supabase.table("user_preferences").insert(prefs).execute()
    if not pref_res.data:
        raise HTTPException(status_code=500, detail="Failed to insert preferences")
    
    type_res = supabase.table("notification_type").insert(type).execute()
    if not type_res.data:
        raise HTTPException(status_code=500, detail="Failed to insert notification types")

    return {
        "status": "success",
        "created": len(users)
    }

class CreateOrderRequest(BaseModel):
    order_name: str

@app.post("/users/{user_id}/orders")
def create_order(user_id: UUID, payload: CreateOrderRequest):
    order_id = str(uuid.uuid4())

    res = (
        supabase
        .table("orders")
        .insert({
            "order_id": order_id,
            "user_id": str(user_id),
            "order_name": payload.order_name,  # ✅ dynamic
            "status": "PLACED",
        })
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=500, detail="Failed to create order")

    return res.data[0]

@app.get("/admin/orders")
def admin_orders():
    res = (
        supabase
        .table("orders")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []


@app.get("/users/{user_id}/orders")
def get_user_orders(user_id: UUID):
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
def request_order_update(user_id: UUID, order_id: UUID):
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
def send_order_update(user_id: UUID, order_id: UUID):
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

