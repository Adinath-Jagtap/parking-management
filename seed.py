"""
Parking Management - Dummy Data Seeder
Run: python seed_dummy_data.py
Requires: pymongo flask-bcrypt qrcode pillow python-dotenv
"""

import os
import json
import math
import base64
import secrets
import qrcode
from io import BytesIO
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pymongo import MongoClient
from bson.objectid import ObjectId
from flask_bcrypt import Bcrypt
from flask import Flask

# ── Config ────────────────────────────────────────────────────────────────────
MONGO_URI = "mongodb+srv://adinathjagtap9702:ap8t0LMQvrnWgbG0@cluster0.1vvqqc.mongodb.net/?appName=Cluster0"
DB_NAME   = "parking_management"

IST = ZoneInfo("Asia/Kolkata")

def now_ist():
    return datetime.now(IST).replace(tzinfo=None)

def past(days=0, hours=0, minutes=0):
    return now_ist() - timedelta(days=days, hours=hours, minutes=minutes)

def future(days=0, hours=0, minutes=0):
    return now_ist() + timedelta(days=days, hours=hours, minutes=minutes)

# ── Setup ─────────────────────────────────────────────────────────────────────
app   = Flask(__name__)
bcrypt = Bcrypt(app)

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=10000)
db     = client[DB_NAME]

users_col            = db.users
lots_col             = db.parking_lots
slots_col            = db.parking_slots
vehicles_col         = db.vehicles
bookings_col         = db.bookings
invoices_col         = db.invoices
admin_ver_col        = db.admin_verification
scan_logs_col        = db.scan_logs
wallet_tx_col        = db.wallet_transactions
sub_plans_col        = db.subscription_plans
user_subs_col        = db.user_subscriptions
watchman_collect_col = db.watchman_collections

def hp(pw):
    return bcrypt.generate_password_hash(pw).decode("utf-8")

def make_qr(vehicle_id, vehicle_number, qr_token):
    data = json.dumps({
        "vehicle_id":     str(vehicle_id),
        "vehicle_number": vehicle_number,
        "qr_token":       qr_token,
        "type":           "parking_qr"
    })
    qr = qrcode.QRCode(version=1,
                       error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def gen_invoice_number():
    ts  = now_ist().strftime("%Y%m%d%H%M%S")
    sfx = secrets.token_hex(3).upper()
    return f"INV-{ts}-{sfx}"

def credit(user_id, amount, reason, ref_id):
    users_col.update_one({"_id": user_id}, {"$inc": {"wallet_balance": amount}})
    user = users_col.find_one({"_id": user_id})
    wallet_tx_col.insert_one({
        "user_id":      user_id,
        "type":         "credit",
        "amount":       round(amount, 2),
        "reason":       reason,
        "reference_id": str(ref_id),
        "balance_after": round(user["wallet_balance"], 2),
        "created_at":   now_ist()
    })

def debit(user_id, amount, reason, ref_id):
    users_col.update_one({"_id": user_id}, {"$inc": {"wallet_balance": -amount}})
    user = users_col.find_one({"_id": user_id})
    wallet_tx_col.insert_one({
        "user_id":      user_id,
        "type":         "debit",
        "amount":       round(amount, 2),
        "reason":       reason,
        "reference_id": str(ref_id),
        "balance_after": round(user["wallet_balance"], 2),
        "created_at":   now_ist()
    })

# ── Wipe existing dummy data (keep real data safe by checking a flag) ──────────
print("⚠  Dropping all collections for a clean seed …")
for col in [users_col, lots_col, slots_col, vehicles_col, bookings_col,
            invoices_col, admin_ver_col, scan_logs_col, wallet_tx_col,
            sub_plans_col, user_subs_col, watchman_collect_col]:
    col.delete_many({})

# ═══════════════════════════════════════════════════════════════════════════════
# 1. SUPER ADMIN
# ═══════════════════════════════════════════════════════════════════════════════
super_admin_id = users_col.insert_one({
    "name":           "Super Admin",
    "email":          "superadmin@parking.com",
    "password":       hp("superadmin123"),
    "role":           "super_admin",
    "verified":       True,
    "wallet_balance": 0.0,
    "created_at":     past(days=60),
    "profile_image":  None
}).inserted_id

# ═══════════════════════════════════════════════════════════════════════════════
# 2. ADMINS  (2 verified)
# ═══════════════════════════════════════════════════════════════════════════════
admins_raw = [
    {"name": "Ravi Sharma",   "email": "ravi.admin@parking.com",   "pw": "Admin@1234"},
    {"name": "Priya Mehta",   "email": "priya.admin@parking.com",  "pw": "Admin@1234"},
]

admin_ids = []
for a in admins_raw:
    aid = users_col.insert_one({
        "name":           a["name"],
        "email":          a["email"],
        "password":       hp(a["pw"]),
        "role":           "admin",
        "verified":       True,
        "wallet_balance": 0.0,
        "created_at":     past(days=50),
        "profile_image":  None
    }).inserted_id
    admin_ver_col.insert_one({
        "admin_id":    aid,
        "status":      "verified",
        "verified_by": super_admin_id,
        "verified_at": past(days=49),
        "created_at":  past(days=50)
    })
    admin_ids.append(aid)

# ═══════════════════════════════════════════════════════════════════════════════
# 3. PARKING LOTS + SLOTS + WATCHMEN  (2 lots per admin = 4 lots total)
# ═══════════════════════════════════════════════════════════════════════════════
LOT_SPECS = [
    # admin_idx, name, address, pincode, 2w_total, 2w_price, 4w_total, 4w_price, walkin%
    (0, "Green Park Parking",   "MG Road, Pune",           "411001", 20, 10.0, 10, 20.0, 70),
    (0, "Blue Bay Lot",         "FC Road, Pune",            "411004", 16, 12.0, 8,  25.0, 60),
    (1, "Skyline Parking",      "Baner Road, Pune",         "411045", 24, 8.0,  12, 18.0, 70),
    (1, "Metro Lot Central",    "Shivaji Nagar, Pune",      "411005", 12, 15.0, 6,  30.0, 50),
]

lot_ids      = []
watchman_ids = []

def split_slots(total, walkin_pct):
    w = math.floor(total * walkin_pct / 100)
    return w, total - w

for spec in LOT_SPECS:
    a_idx, lname, laddr, pin, tw_tot, tw_pr, fw_tot, fw_pr, wpct = spec
    ppct = 100 - wpct
    admin_id = admin_ids[a_idx]

    lot_id = lots_col.insert_one({
        "admin_id":      admin_id,
        "name":          lname,
        "address":       laddr,
        "pincode":       pin,
        "walkin_ratio":  wpct,
        "prebook_ratio": ppct,
        "created_at":    past(days=45)
    }).inserted_id
    lot_ids.append(lot_id)

    tw_w, tw_p = split_slots(tw_tot, wpct)
    fw_w, fw_p = split_slots(fw_tot, wpct)

    slot_docs = []
    for i in range(1, tw_w + 1):
        slot_docs.append({"lot_id": lot_id, "slot_number": f"A{i}",  "slot_type": "2-wheeler", "mode": "walkin",  "price_per_hour": tw_pr, "status": "available", "created_at": past(days=45)})
    for i in range(tw_w + 1, tw_tot + 1):
        slot_docs.append({"lot_id": lot_id, "slot_number": f"A{i}",  "slot_type": "2-wheeler", "mode": "prebook", "price_per_hour": tw_pr, "status": "available", "created_at": past(days=45)})
    for i in range(1, fw_w + 1):
        slot_docs.append({"lot_id": lot_id, "slot_number": f"B{i}",  "slot_type": "4-wheeler", "mode": "walkin",  "price_per_hour": fw_pr, "status": "available", "created_at": past(days=45)})
    for i in range(fw_w + 1, fw_tot + 1):
        slot_docs.append({"lot_id": lot_id, "slot_number": f"B{i}",  "slot_type": "4-wheeler", "mode": "prebook", "price_per_hour": fw_pr, "status": "available", "created_at": past(days=45)})

    slots_col.insert_many(slot_docs)

    # Auto-create watchman
    slug      = "".join(c for c in lname.lower().replace(" ", "_") if c.isalnum() or c == "_")
    rand_suf  = secrets.token_hex(2)[:4]
    w_email   = f"watchman_{slug}_{rand_suf}@parking.local"
    w_plain   = "Watch@1234"
    w_id      = users_col.insert_one({
        "name":          f"Watchman - {lname}",
        "email":         w_email,
        "password":      hp(w_plain),
        "role":          "watchman",
        "verified":      True,
        "lot_id":        lot_id,
        "created_at":    past(days=44),
        "profile_image": None
    }).inserted_id
    watchman_ids.append(w_id)

    lots_col.update_one({"_id": lot_id}, {"$set": {
        "watchman_user_id":       w_id,
        "watchman_username":      w_email,
        "watchman_plain_password": w_plain
    }})

# ═══════════════════════════════════════════════════════════════════════════════
# 4. REGULAR USERS  (5 users)
# ═══════════════════════════════════════════════════════════════════════════════
users_raw = [
    {"name": "Arjun Kapoor",   "email": "arjun@example.com",   "pw": "User@1234"},
    {"name": "Sneha Patil",    "email": "sneha@example.com",   "pw": "User@1234"},
    {"name": "Rahul Desai",    "email": "rahul@example.com",   "pw": "User@1234"},
    {"name": "Pooja Joshi",    "email": "pooja@example.com",   "pw": "User@1234"},
    {"name": "Amit Kulkarni",  "email": "amit@example.com",    "pw": "User@1234"},
]

user_ids = []
for u in users_raw:
    uid = users_col.insert_one({
        "name":           u["name"],
        "email":          u["email"],
        "password":       hp(u["pw"]),
        "role":           "user",
        "verified":       True,
        "wallet_balance": 0.0,
        "created_at":     past(days=30),
        "profile_image":  None
    }).inserted_id
    # Give each user a wallet top-up
    topup = 1000.0
    credit(uid, topup, "Initial wallet top-up (seed)", "seed_topup")
    user_ids.append(uid)

# ═══════════════════════════════════════════════════════════════════════════════
# 5. VEHICLES  (2 per user)
# ═══════════════════════════════════════════════════════════════════════════════
vehicle_plates = [
    ["MH12AB1234", "MH12CD5678"],
    ["MH14EF2345", "MH14GH6789"],
    ["MH15IJ3456", "MH15KL7890"],
    ["MH01MN4567", "MH01OP8901"],
    ["MH04QR5678", "MH04ST9012"],
]
vehicle_types_pattern = [("2-wheeler", "4-wheeler")] * 5  # each user gets one of each

vehicle_ids = []  # flat list: [u0_v0, u0_v1, u1_v0, u1_v1, …]

for i, uid in enumerate(user_ids):
    for j, (plate, vtype) in enumerate(zip(vehicle_plates[i], ["2-wheeler", "4-wheeler"])):
        tok  = secrets.token_urlsafe(16)
        vid  = vehicles_col.insert_one({
            "user_id":         uid,
            "vehicle_number":  plate,
            "vehicle_type":    vtype,
            "qr_token":        tok,
            "currently_parked": False,
            "created_at":      past(days=25)
        }).inserted_id
        qr64 = make_qr(vid, plate, tok)
        vehicles_col.update_one({"_id": vid}, {"$set": {
            "qr_code_base64":  qr64,
            "qr_generated_at": past(days=25)
        }})
        vehicle_ids.append({"id": vid, "uid": uid, "number": plate, "type": vtype, "tok": tok})

# ═══════════════════════════════════════════════════════════════════════════════
# 6. SUBSCRIPTION PLANS  (2 plans per lot)
# ═══════════════════════════════════════════════════════════════════════════════
plan_ids_2w = []
plan_ids_4w = []

for idx, lot_id in enumerate(lot_ids):
    lot = lots_col.find_one({"_id": lot_id})
    aid = lot["admin_id"]
    sample_2w = slots_col.find_one({"lot_id": lot_id, "slot_type": "2-wheeler"})
    sample_4w = slots_col.find_one({"lot_id": lot_id, "slot_type": "4-wheeler"})

    p2w = sub_plans_col.insert_one({
        "name":          f"Monthly 2W - {lot['name']}",
        "duration_days": 30,
        "price":         round((sample_2w["price_per_hour"] if sample_2w else 10) * 8 * 22, 2),
        "vehicle_type":  "2-wheeler",
        "lot_id":        lot_id,
        "admin_id":      aid,
        "active":        True,
        "created_at":    past(days=40)
    }).inserted_id
    plan_ids_2w.append(p2w)

    p4w = sub_plans_col.insert_one({
        "name":          f"Monthly 4W - {lot['name']}",
        "duration_days": 30,
        "price":         round((sample_4w["price_per_hour"] if sample_4w else 20) * 8 * 22, 2),
        "vehicle_type":  "4-wheeler",
        "lot_id":        lot_id,
        "admin_id":      aid,
        "active":        True,
        "created_at":    past(days=40)
    }).inserted_id
    plan_ids_4w.append(p4w)

# ═══════════════════════════════════════════════════════════════════════════════
# 7. COMPLETED WALK-IN BOOKINGS  (past 30 days, various users/lots)
# ═══════════════════════════════════════════════════════════════════════════════
COMPLETED_BOOKINGS = [
    # (vehicle_idx, lot_idx, entry_offset_hours, duration_hours, pay_method)
    (0, 0, 24*28, 2.0, "wallet"),
    (1, 0, 24*27, 3.5, "cash"),
    (2, 1, 24*26, 1.0, "upi"),
    (3, 1, 24*25, 4.0, "wallet"),
    (4, 2, 24*24, 2.5, "cash"),
    (5, 2, 24*23, 1.5, "upi"),
    (6, 3, 24*22, 3.0, "wallet"),
    (7, 3, 24*21, 2.0, "cash"),
    (8, 0, 24*20, 5.0, "wallet"),
    (9, 1, 24*19, 1.0, "upi"),
    (0, 2, 24*18, 2.0, "cash"),
    (2, 3, 24*17, 3.0, "wallet"),
    (4, 0, 24*16, 1.5, "upi"),
    (6, 1, 24*15, 4.0, "wallet"),
    (8, 2, 24*14, 2.5, "cash"),
    (1, 3, 24*13, 1.0, "wallet"),
    (3, 0, 24*12, 3.5, "upi"),
    (5, 1, 24*11, 2.0, "cash"),
    (7, 2, 24*10, 1.5, "wallet"),
    (9, 3, 24*9,  4.5, "wallet"),
]

for v_idx, l_idx, entry_hours_ago, dur_hrs, pay_method in COMPLETED_BOOKINGS:
    veh   = vehicle_ids[v_idx]
    lot_id = lot_ids[l_idx]
    lot   = lots_col.find_one({"_id": lot_id})

    slot  = slots_col.find_one({
        "lot_id":    lot_id,
        "slot_type": veh["type"],
        "mode":      "walkin",
        "status":    "available"
    })
    if not slot:
        continue

    entry  = past(hours=entry_hours_ago)
    exit_t = entry + timedelta(hours=dur_hrs)
    fee    = round(dur_hrs * slot["price_per_hour"], 2)

    w_user = users_col.find_one({"role": "watchman", "lot_id": lot_id})
    w_id   = w_user["_id"] if w_user else watchman_ids[0]

    bk_id = bookings_col.insert_one({
        "user_id":                  veh["uid"],
        "slot_id":                  slot["_id"],
        "vehicle_id":               veh["id"],
        "lot_id":                   lot_id,
        "booking_type":             "walkin",
        "entry_time":               entry,
        "exit_time":                exit_t,
        "status":                   "completed",
        "checked_in_lot_id":        lot_id,
        "checked_in_by_watchman_id": w_id,
        "checked_out_by_watchman_id": w_id,
        "created_at":               entry
    }).inserted_id

    inv_id = invoices_col.insert_one({
        "booking_id":     bk_id,
        "user_id":        veh["uid"],
        "invoice_number": gen_invoice_number(),
        "amount":         fee,
        "payment_status": f"paid_{pay_method}" if pay_method in ("cash","upi") else "paid_wallet",
        "lot_id":         lot_id,
        "watchman_id":    w_id,
        "generated_at":   exit_t
    }).inserted_id

    if pay_method == "wallet":
        debit(veh["uid"], fee, "Parking fee (wallet)", str(bk_id))
    elif pay_method in ("cash", "upi"):
        watchman_collect_col.insert_one({
            "watchman_id":  w_id,
            "lot_id":       lot_id,
            "invoice_id":   inv_id,
            "user_id":      veh["uid"],
            "amount":       fee,
            "method":       pay_method,
            "collected_at": exit_t
        })

    scan_logs_col.insert_one({"watchman_id": w_id, "lot_id": lot_id, "vehicle_id": veh["id"], "action": "checkin",  "result_message": f"Checked in at slot {slot['slot_number']}",  "timestamp": entry})
    scan_logs_col.insert_one({"watchman_id": w_id, "lot_id": lot_id, "vehicle_id": veh["id"], "action": "checkout", "result_message": f"Checked out. Duration: {dur_hrs}h, Fee: Rs.{fee}", "timestamp": exit_t})

# ═══════════════════════════════════════════════════════════════════════════════
# 8. ACTIVE (currently parked) BOOKINGS  — 3 vehicles parked right now
# ═══════════════════════════════════════════════════════════════════════════════
ACTIVE_CHECKINS = [
    (0, 0, 1.5),   # vehicle_idx, lot_idx, hours_ago
    (3, 1, 0.5),
    (6, 2, 2.0),
]

for v_idx, l_idx, hrs_ago in ACTIVE_CHECKINS:
    veh    = vehicle_ids[v_idx]
    lot_id = lot_ids[l_idx]

    slot = slots_col.find_one({
        "lot_id":    lot_id,
        "slot_type": veh["type"],
        "mode":      "walkin",
        "status":    "available"
    })
    if not slot:
        continue

    w_user = users_col.find_one({"role": "watchman", "lot_id": lot_id})
    w_id   = w_user["_id"] if w_user else watchman_ids[0]
    entry  = past(hours=hrs_ago)

    bk_id = bookings_col.insert_one({
        "user_id":                  veh["uid"],
        "slot_id":                  slot["_id"],
        "vehicle_id":               veh["id"],
        "lot_id":                   lot_id,
        "booking_type":             "walkin",
        "entry_time":               entry,
        "exit_time":                None,
        "status":                   "active",
        "checked_in_lot_id":        lot_id,
        "checked_in_by_watchman_id": w_id,
        "created_at":               entry
    }).inserted_id

    slots_col.update_one({"_id": slot["_id"]},   {"$set": {"status": "occupied"}})
    vehicles_col.update_one({"_id": veh["id"]},  {"$set": {"currently_parked": True}})

    scan_logs_col.insert_one({"watchman_id": w_id, "lot_id": lot_id, "vehicle_id": veh["id"], "action": "checkin", "result_message": f"Checked in at slot {slot['slot_number']}", "timestamp": entry})

# ═══════════════════════════════════════════════════════════════════════════════
# 9. PRE-BOOKED (reserved) BOOKING  — 1 upcoming booking
# ═══════════════════════════════════════════════════════════════════════════════
pb_veh    = vehicle_ids[4]   # Arjun's 4-wheeler
pb_lot_id = lot_ids[0]
pb_slot   = slots_col.find_one({"lot_id": pb_lot_id, "slot_type": pb_veh["type"], "mode": "prebook", "status": "available"})

if pb_slot:
    pb_start  = future(hours=3)
    pb_end    = future(hours=5)
    pb_fee    = round(2.0 * pb_slot["price_per_hour"], 2)

    pb_bk_id = bookings_col.insert_one({
        "user_id":           pb_veh["uid"],
        "slot_id":           pb_slot["_id"],
        "vehicle_id":        pb_veh["id"],
        "lot_id":            pb_lot_id,
        "booking_type":      "prebook",
        "entry_time":        None,
        "exit_time":         None,
        "status":            "reserved",
        "booked_start":      pb_start,
        "booked_end":        pb_end,
        "hold_amount":       pb_fee,
        "checked_in_lot_id": pb_lot_id,
        "created_at":        now_ist()
    }).inserted_id
    debit(pb_veh["uid"], pb_fee, "Booking hold for pre-book reservation", str(pb_bk_id))

# ═══════════════════════════════════════════════════════════════════════════════
# 10. USER SUBSCRIPTION  — give user[1] an active subscription
# ═══════════════════════════════════════════════════════════════════════════════
sub_uid = user_ids[1]
sub_veh = vehicle_ids[2]   # Sneha's 2-wheeler
plan    = sub_plans_col.find_one({"lot_id": lot_ids[0], "vehicle_type": "2-wheeler"})

if plan:
    start_d = past(days=5)
    end_d   = start_d + timedelta(days=30)
    sub_id  = user_subs_col.insert_one({
        "user_id":    sub_uid,
        "plan_id":    plan["_id"],
        "lot_id":     lot_ids[0],
        "vehicle_id": sub_veh["id"],
        "start_date": start_d,
        "end_date":   end_d,
        "price_paid": plan["price"],
        "status":     "active",
        "created_at": start_d
    }).inserted_id
    debit(sub_uid, plan["price"], "subscription_purchase", str(sub_id))

# ═══════════════════════════════════════════════════════════════════════════════
# 11. NO-SHOW BOOKING  — historical
# ═══════════════════════════════════════════════════════════════════════════════
ns_veh  = vehicle_ids[8]   # Pooja's 2-wheeler
ns_lot  = lot_ids[3]
ns_slot = slots_col.find_one({"lot_id": ns_lot, "slot_type": ns_veh["type"], "mode": "prebook", "status": "available"})

if ns_slot:
    ns_start = past(days=7, hours=3)
    ns_end   = ns_start + timedelta(hours=2)
    ns_fee   = round(2.0 * ns_slot["price_per_hour"], 2)
    ns_noshow_fee = round(ns_slot["price_per_hour"] * (20/60), 2)
    ns_refund = max(0, round(ns_fee - ns_noshow_fee, 2))

    ns_bk_id = bookings_col.insert_one({
        "user_id":     ns_veh["uid"],
        "slot_id":     ns_slot["_id"],
        "vehicle_id":  ns_veh["id"],
        "lot_id":      ns_lot,
        "booking_type": "prebook",
        "entry_time":  None,
        "exit_time":   None,
        "status":      "noshow",
        "booked_start": ns_start,
        "booked_end":  ns_end,
        "hold_amount": ns_fee,
        "noshow_fee":  ns_noshow_fee,
        "refund_amount": ns_refund,
        "noshow_at":   ns_start + timedelta(minutes=20),
        "checked_in_lot_id": ns_lot,
        "created_at":  ns_start - timedelta(hours=1)
    }).inserted_id

    if ns_refund > 0:
        credit(ns_veh["uid"], ns_refund, f"Partial refund - no-show (20-min fee: Rs.{ns_noshow_fee})", str(ns_bk_id))

# ═══════════════════════════════════════════════════════════════════════════════
# 12. CANCELLED BOOKING  — historical
# ═══════════════════════════════════════════════════════════════════════════════
cn_veh  = vehicle_ids[6]   # Rahul's 4-wheeler
cn_lot  = lot_ids[2]
cn_slot = slots_col.find_one({"lot_id": cn_lot, "slot_type": cn_veh["type"], "mode": "prebook", "status": "available"})

if cn_slot:
    cn_start = past(days=10, hours=5)
    cn_end   = cn_start + timedelta(hours=3)
    cn_fee   = round(3.0 * cn_slot["price_per_hour"], 2)

    cn_bk_id = bookings_col.insert_one({
        "user_id":     cn_veh["uid"],
        "slot_id":     cn_slot["_id"],
        "vehicle_id":  cn_veh["id"],
        "lot_id":      cn_lot,
        "booking_type": "prebook",
        "entry_time":  None,
        "exit_time":   None,
        "status":      "cancelled",
        "booked_start": cn_start,
        "booked_end":  cn_end,
        "hold_amount": cn_fee,
        "cancelled_at": cn_start - timedelta(hours=6),
        "checked_in_lot_id": cn_lot,
        "created_at":  cn_start - timedelta(hours=12)
    }).inserted_id

    debit(cn_veh["uid"], cn_fee, "Booking hold for pre-book reservation", str(cn_bk_id))
    credit(cn_veh["uid"], cn_fee, "Full refund - booking cancelled (>2h before start)", str(cn_bk_id))

# ═══════════════════════════════════════════════════════════════════════════════
# PRINT CREDENTIALS SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "="*65)
print("            DUMMY DATA SEEDED SUCCESSFULLY")
print("="*65)

print("\n── SUPER ADMIN ──────────────────────────────────────────────")
print(f"  Email    : superadmin@parking.com")
print(f"  Password : superadmin123")

print("\n── ADMINS ───────────────────────────────────────────────────")
for a in admins_raw:
    print(f"  Email    : {a['email']}")
    print(f"  Password : {a['pw']}")
    print()

print("── WATCHMEN (auto-generated, 1 per lot) ────────────────────")
for lot_doc in lots_col.find({"watchman_username": {"$exists": True}}):
    print(f"  Lot      : {lot_doc['name']}")
    print(f"  Email    : {lot_doc['watchman_username']}")
    print(f"  Password : {lot_doc['watchman_plain_password']}")
    print()

print("── USERS ────────────────────────────────────────────────────")
for u in users_raw:
    print(f"  Email    : {u['email']}")
    print(f"  Password : {u['pw']}")
    print()

print("── WALLET BALANCES (after all seed transactions) ────────────")
for u in users_col.find({"role": "user"}):
    print(f"  {u['name']:<20} ₹{u['wallet_balance']:.2f}")

print("\n── STATS ────────────────────────────────────────────────────")
print(f"  Parking Lots       : {lots_col.count_documents({})}")
print(f"  Parking Slots      : {slots_col.count_documents({})}")
print(f"  Vehicles           : {vehicles_col.count_documents({})}")
print(f"  Bookings total     : {bookings_col.count_documents({})}")
print(f"    Completed        : {bookings_col.count_documents({'status':'completed'})}")
print(f"    Active (parked)  : {bookings_col.count_documents({'status':'active'})}")
print(f"    Reserved (future): {bookings_col.count_documents({'status':'reserved'})}")
print(f"    No-show          : {bookings_col.count_documents({'status':'noshow'})}")
print(f"    Cancelled        : {bookings_col.count_documents({'status':'cancelled'})}")
print(f"  Invoices           : {invoices_col.count_documents({})}")
print(f"  Subscription Plans : {sub_plans_col.count_documents({})}")
print(f"  Active Subs        : {user_subs_col.count_documents({})}")
print(f"  Watchman Records   : {watchman_collect_col.count_documents({})}")
print("="*65 + "\n")