<div align="center">

<!-- Animated Banner -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:1a1a2e,50:16213e,100:0f3460&height=220&section=header&text=ParkEasy%20🚗&fontSize=68&fontColor=e94560&fontAlignY=38&desc=Intelligent%20Multi-Role%20Parking%20Management%20Platform&descAlignY=62&descColor=a8b2d8&animation=fadeIn" width="100%"/>

<!-- Badge Row -->
<p align="center">
  <a href="https://parking-management-afot.onrender.com/" target="_blank">
    <img src="https://img.shields.io/badge/🌐%20Live%20Demo-parking--management--afot.onrender.com-e94560?style=for-the-badge&labelColor=1a1a2e" alt="Live Demo"/>
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11.9-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Flask-3.0.0-000000?style=for-the-badge&logo=flask&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/MongoDB-Atlas-47A248?style=for-the-badge&logo=mongodb&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Razorpay-Integrated-072654?style=for-the-badge&logo=razorpay&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Deployed%20on-Render-46E3B7?style=for-the-badge&logo=render&logoColor=black&labelColor=1a1a2e"/>
</p>
</div>

---

## 🧭 Navigation

<div align="center">

[🎯 About](#-about) &nbsp;·&nbsp; [✨ Features & Status](#-features--status) &nbsp;·&nbsp; [🏗️ Tech Stack](#️-tech-stack) &nbsp;·&nbsp; [⚙️ Architecture](#️-system-architecture) &nbsp;·&nbsp; [🚀 Getting Started](#-getting-started) &nbsp;·&nbsp; [🗂️ Project Structure](#️-project-structure) &nbsp;·&nbsp; [👥 Team](#-team--links)

</div>

---

## 🎯 About

> **ParkEasy** is a full-stack, production-grade intelligent parking management platform built for the modern world. It bridges the gap between parking-lot owners, security personnel, and everyday drivers — all inside a single unified system powered by Python 3.11, Flask 3, and MongoDB Atlas.

<div align="center">

|         🧑‍💼 Multi-Role System          |   💳 Payment Ecosystem   |   📱 QR-Based Entry   | 🕐 Real-Time Availability |
| :-----------------------------------: | :----------------------: | :-------------------: | :-----------------------: |
| User · Admin · Watchman · Super Admin | Razorpay + In-App Wallet | Unique QR per Vehicle | Walk-in & Pre-book Slots  |

</div>

---

## ✨ Features & Status

> Every feature listed below was verified directly from `app.py` (3 461 lines) and the template tree. No feature is speculative.

<div align="center">

|  #  | Feature                                                                                 |    Module    | Status |
| :-: | :-------------------------------------------------------------------------------------- | :----------: | :----: |
|  1  | Secure registration & login with CSRF protection and rate-limiting                      |     Auth     |   ✅   |
|  2  | Role-based access control (User / Admin / Watchman / Super Admin)                       |     Auth     |   ✅   |
|  3  | Multi-vehicle registration with per-vehicle unique QR codes (H-level ECC)               |     User     |   ✅   |
|  4  | QR code download (`PNG`) and one-click regeneration with token invalidation             |     User     |   ✅   |
|  5  | Walk-in parking via watchman QR scan + watchman-selects-slot flow                       |   Watchman   |   ✅   |
|  6  | Slot pre-booking with calendar picker and real-time slot availability API               |     User     |   ✅   |
|  7  | Pre-booking wallet hold & cancellation policy (full refund > 2 h, none < 2 h)           |     User     |   ✅   |
|  8  | Automated no-show handling via APScheduler (fires 20 min after booked start)            |  Scheduler   |   ✅   |
|  9  | In-app wallet with Razorpay top-up (₹50 – ₹10 000), HMAC signature verification         |    Wallet    |   ✅   |
| 10  | Subscription plans (custom duration, vehicle type, per-lot) with wallet deduction       | Subscription |   ✅   |
| 11  | Subscription-aware checkout — zero-fee exit for active subscribers                      |   Watchman   |   ✅   |
| 12  | Walk-in payment at gate: wallet / cash / UPI collection recorded per watchman           |   Watchman   |   ✅   |
| 13  | Auto-generated watchman credentials on parking lot creation                             |    Admin     |   ✅   |
| 14  | Admin dashboard: occupancy rate, revenue, recent bookings                               |    Admin     |   ✅   |
| 15  | Admin analytics: daily revenue (30 d), peak-hour heatmap, slot occupancy per lot        |    Admin     |   ✅   |
| 16  | Watchman audit trail: cash & UPI collections grouped by watchman with date filter       |    Admin     |   ✅   |
| 17  | Admin subscription plan management (create, activate, deactivate)                       |    Admin     |   ✅   |
| 18  | Super Admin: verify / reject / disable admins and manage the approval pipeline          | Super Admin  |   ✅   |
| 19  | Super Admin: platform analytics — revenue (30 d), user growth (6 mo), booking breakdown | Super Admin  |   ✅   |
| 20  | Super Admin: force-checkout any active booking with logged reason & ₹0 invoice          | Super Admin  |   ✅   |
| 21  | Super Admin: manual wallet credit / debit with audit trail                              | Super Admin  |   ✅   |
| 22  | Super Admin: delete parking lot with cascading slot cleanup & hold-amount refunds       | Super Admin  |   ✅   |
| 23  | Downloadable invoices with unique `INV-YYYYMMDDHHMMSS-XXXXXX` numbering                 |   Invoices   |   ✅   |
| 24  | User analytics: monthly spend, avg duration, most-visited lot, booking breakdown        |     User     |   ✅   |
| 25  | Profile management with photo upload (PNG/JPG/GIF, 5 MB limit)                          |  All Roles   |   ✅   |
| 26  | Security headers: `X-Frame-Options`, `X-XSS-Protection`, `CSP`, `nosniff`               |   Platform   |   ✅   |
| 27  | IST timezone-aware scheduling (all timestamps stored as naive IST datetimes)            |   Platform   |   ✅   |
| 28  | MongoDB indexes for QR tokens, bookings, and scan logs for query performance            |   Database   |   ✅   |
| 29  | Paginated listing for parking lots, bookings, invoices, transactions, users             |   Platform   |   ✅   |
| 30  | Custom 403 / 404 / 500 error pages                                                      |   Platform   |   ✅   |

</div>

---

## 🏗️ Tech Stack

<div align="center">

|        Layer        | Technology                                                                                                                         |
| :-----------------: | :--------------------------------------------------------------------------------------------------------------------------------- |
|     **Runtime**     | ![Python](https://img.shields.io/badge/Python-3.11.9-3776AB?logo=python&logoColor=white) — `runtime.txt` pins `python-3.11.9`      |
|  **Web Framework**  | ![Flask](https://img.shields.io/badge/Flask-3.0.0-000?logo=flask&logoColor=white) · Flask-WTF 1.2.1 · Jinja2 templates             |
|    **Database**     | ![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white) · PyMongo 4.6.1 · 11 collections        |
| **Auth & Security** | Flask-Login 0.6.3 · Flask-Bcrypt 1.0.1 · Flask-WTF CSRF · Flask-Limiter 3.5.0                                                      |
|    **Payments**     | ![Razorpay](https://img.shields.io/badge/Razorpay-1.4.2-072654?logo=razorpay&logoColor=white) · HMAC-SHA256 signature verification |
|    **QR Codes**     | `qrcode[pil]` 7.4.2 · Error-correction level H (30 % recovery) · base64-embedded                                                   |
| **Background Jobs** | APScheduler 3.10.4 · `BackgroundScheduler` — no-show auto-cancel at T+20 min                                                       |
|   **Validation**    | WTForms 3.1.1 · email-validator 2.1.0                                                                                              |
|     **Config**      | python-dotenv 1.0.0 · `zoneinfo` (stdlib) for IST awareness                                                                        |
|   **WSGI Server**   | Gunicorn 21.2.0                                                                                                                    |
|   **Deployment**    | ![Render](https://img.shields.io/badge/Render-46E3B7?logo=render&logoColor=black) — production-ready                               |

</div>

---

## ⚙️ System Architecture

```
🌐 Super Admin
    └── ✅ Verify / ❌ Reject / 🔒 Disable Admins
         └── 🔥 Force Checkout  /  💰 Wallet Adjust  /  🗑️ Delete Lot (with cascading refunds)
              └── 🏢 Admin
                     └── 🅿️ Create Parking Lots (walkin % / prebook %)
                         └── 🔑 Auto-generated Watchman Account (per lot)
                              └── 👮 Watchman
                                   └── 📷 QR Scan → Walk-in Check-in (selects slot) / Check-out
                                       └── 💳 Collect Payment: Wallet · Cash · UPI

👤 User
    └── 🚗 Register Vehicles → Unique QR Code (level-H, downloadable + regeneratable)
        └── 📅 Pre-Book Slot → 💰 Wallet Hold (refund policy enforced)
            └── APScheduler → ⏱️ No-show handler fires at T+20 min
        └── 🏷️ Buy Subscription Plan → Free parking during active period
        └── 💳 Wallet Top-Up via Razorpay (HMAC verified)
        └── 🧾 Invoices (INV-YYYYMMDDHHMMSS-XXXXXX) + Analytics Dashboard
```

---

## 🚀 Getting Started

### Prerequisites

```
Python 3.11.x
MongoDB Atlas URI  (or local MongoDB instance)
Razorpay API Keys  (test or live)
```

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Adinath-Jagtap/parking-management.git
cd parking-management

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux / macOS
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env .env.local              # or create .env manually (see below)
# Edit .env with your real credentials
```

### Environment Variables

```env
SECRET_KEY=<a-long-random-hex-string>
MONGO_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/?appName=<AppName>
RAZORPAY_KEY_ID=rzp_test_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX
```

> **Note:** `MONGO_URI` must point to a database named `parking_management`. The app auto-creates all 11 collections and their indexes on first run.

### Run Locally

```bash
python app.py
# Visit: http://localhost:5000
```

For production, Render uses Gunicorn automatically (configured via `Procfile`-compatible `gunicorn app:app`).

---

## 🗂️ Project Structure

```
parking-management/
│
├── app.py                        # Monolithic Flask app — all routes, models, business logic (3 461 lines)
├── requirements.txt              # Pinned Python dependencies (15 packages)
├── runtime.txt                   # python-3.11.9 (Render runtime pin)
├── user.json                     # Seed / reference data
├── .env                          # Local environment variables (not committed)
├── .python-version               # pyenv version pin
├── .gitignore
│
├── static/
│   ├── uploads/                  # User & admin profile image uploads (served at /static/uploads/)
│   ├── favicon-16.png
│   ├── favicon-32.png
│   ├── apple-touch-icon.png
│   └── og-image.png              # Open Graph preview image
│
└── templates/
    ├── base.html                 # Base layout (nav, flash messages, security meta tags)
    ├── index.html                # Public landing page
    │
    ├── auth/
    │   ├── login.html
    │   └── register.html
    │
    ├── user/
    │   ├── dashboard.html        # Active bookings, spend summary, recent invoices
    │   ├── parking_lots.html     # Searchable & paginated lot listing with real-time slots
    │   ├── my_vehicles.html      # Vehicle management + QR display / download / regenerate
    │   ├── prebook_slot.html     # Slot picker with fee estimator API
    │   ├── my_bookings.html      # Paginated bookings + cancel pre-bookings
    │   ├── invoices.html         # Paginated invoice history
    │   ├── subscriptions.html    # Browse plans (grouped by lot) + active subscriptions
    │   ├── wallet.html           # Balance, Razorpay top-up modal, transaction history
    │   ├── analytics.html        # Spend chart, avg duration, most-visited lot
    │   └── profile.html          # Name + profile photo update
    │
    ├── admin/
    │   ├── dashboard.html        # KPIs: lots, slots, occupancy %, revenue, recent bookings
    │   ├── manage_slots.html     # Create lots (walkin/prebook ratio), add/delete slots
    │   ├── lot_users.html        # Users who have parked in admin's lots
    │   ├── invoices.html         # Paginated invoices for admin's lots
    │   ├── subscriptions.html    # Create / activate / deactivate subscription plans
    │   ├── watchman_audit.html   # Cash & UPI collections grouped by watchman (date filter)
    │   ├── analytics.html        # 30-day revenue, peak hours, occupancy per lot, watchman totals
    │   └── profile.html
    │
    ├── watchman/
    │   ├── dashboard.html        # Live slot counts + QR camera scanner + recent scan log
    │   └── collections.html      # Watchman's own collection history
    │
    ├── super_admin/
    │   ├── dashboard.html        # Platform-wide KPIs + recent users & bookings
    │   ├── manage_admins.html    # Pending / verified / disabled admin pipeline
    │   ├── all_users.html        # Searchable paginated user list + soft-delete
    │   ├── all_lots.html         # All lots across platform + delete with cascade
    │   ├── platform_analytics.html  # 30-d revenue, top-5 lots, user growth, booking breakdown
    │   ├── watchman_collections.html # Platform-wide cash/UPI grouped by watchman
    │   ├── unpaid_invoices.html  # Overdue invoices (> 1 h pending)
    │   ├── force_checkout.html   # Force-complete any active booking with reason
    │   └── wallet_adjust.html    # Manual credit / debit with reason log
    │
    ├── invoices/
    │   └── view.html             # Role-gated invoice detail page (user / admin / watchman / super_admin)
    │
    └── errors/
        ├── 403.html
        ├── 404.html
        └── 500.html
```

---

## 🗄️ Database Collections

<div align="center">

| Collection             | Purpose                                                             |
| :--------------------- | :------------------------------------------------------------------ |
| `users`                | All roles: user, admin, watchman, super_admin. Holds wallet balance |
| `parking_lots`         | Lot metadata, walkin/prebook ratios, embedded watchman credentials  |
| `parking_slots`        | Individual slots with type (2W/4W), mode (walkin/prebook), status   |
| `vehicles`             | User vehicles with QR token + base64 QR image                       |
| `bookings`             | Walk-in, pre-book, reserved, and completed bookings                 |
| `invoices`             | Generated invoices (pending → paid/subscription/force_cleared)      |
| `admin_verification`   | Admin approval pipeline status                                      |
| `scan_logs`            | Watchman QR scan events + security alerts                           |
| `wallet_transactions`  | Debit/credit ledger with running balance                            |
| `subscription_plans`   | Admin-defined plans (name, price, duration, vehicle type)           |
| `user_subscriptions`   | Active subscriptions linking user ↔ vehicle ↔ lot ↔ plan            |
| `watchman_collections` | Cash & UPI payments recorded by watchman at checkout                |

</div>

---

## 👥 Team & Links

<div align="center">

<table>
<tr>
<td align="center">
  <a href="https://github.com/Adinath-Jagtap">
    <img src="https://avatars.githubusercontent.com/Adinath-Jagtap?v=4" width="100px;" alt="Adinath Somnath Jagtap"/>
  </a>
  <br/><sub><b>Adinath Jagtap</b></sub>
  <br/><br/>
  <a href="https://github.com/Adinath-Jagtap"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/></a>&nbsp;
  <a href="https://www.linkedin.com/in/adinath-jagtap"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/></a>
</td>
<td align="center">
  <a href="https://github.com/prajwalzolage55">
    <img src="https://avatars.githubusercontent.com/prajwalzolage55?v=4" width="100px;" alt="Prajwal Ashok Zolage"/>    
  </a>
  <br/><sub><b>Prajwal Zolage</b></sub>
  <br/><br/>
  <a href="https://github.com/prajwalzolage55"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/></a>&nbsp;
  <a href="https://www.linkedin.com/in/prajwal-zolage-82ab10347"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/></a>
</td>
<td align="center">
  <a href="https://github.com/VirajK1207">
    <img src="https://avatars.githubusercontent.com/VirajK1207?v=4" width="100px;" alt="Viraj Vikram Kakade"/>
  </a>
  <br/><sub><b>Viraj Kakade</b></sub>
  <br/><br/>
  <a href="https://github.com/VirajK1207"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/></a>&nbsp;
  <a href="https://www.linkedin.com/in/viraj-kakade-94ba173a0"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/></a>
</td>
<td align="center">
  <a href="https://github.com/anuragamale">
    <img src="https://avatars.githubusercontent.com/anuragamale?v=4" width="100px;" alt="Anurag Santosh Amale"/>
  </a>
  <br/><sub><b>Anurag Amale</b></sub>
  <br/><br/>
  <a href="https://github.com/anuragamale"><img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/></a>&nbsp;
  <a href="https://www.linkedin.com/in/anurag-amale-68686b3b4/"><img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/></a>
</td>
</tr>
</table>

<br/>
</div>
  
> 🎓 **Terna Engineering College · Nerul, Navi Mumbai · 2026**

---

## ⚡ Roles & Access Summary

```
🌐 Super Admin
    ├── Verify / Reject / Disable Admins
    ├── View platform-wide analytics, lots, users, watchman collections
    ├── Force-checkout any active booking (with reason + ₹0 invoice)
    ├── Manually credit / debit any user wallet (audited)
    └── Delete parking lot → cascades: slots deleted, reserved bookings cancelled, holds refunded

🏢 Admin  (must be approved by Super Admin)
    ├── Create parking lots (2-wheeler & 4-wheeler slots · walkin/prebook ratio)
    ├── Watchman account auto-generated per lot on creation
    ├── Manage subscription plans per lot (create, activate, deactivate)
    ├── View lot analytics, invoices, watchman audit trail (cash & UPI)
    └── View all users who have parked in their lots

👮 Watchman  (assigned to one lot)
    ├── QR scan check-in (walk-in: selects from available slots) / check-out
    ├── Pre-booked vehicle check-in (arrival window: booked_start − 15 min → booked_end)
    ├── Subscription check — zero-fee checkout for active subscribers
    └── Collect payment: Wallet deduction · Cash · UPI (recorded per transaction)

👤 User
    ├── Register multiple vehicles → per-vehicle unique QR (downloadable, regeneratable)
    ├── Browse paginated parking lots with real-time slot counts
    ├── Walk-in parking (via watchman scan) or pre-book slots in advance
    ├── Wallet top-up via Razorpay (₹50–₹10 000) · subscription purchase via wallet
    ├── Cancellation policy: full refund if > 2 h before start; no refund otherwise
    └── View invoices, analytics, booking history, subscription status
```

---

## 📄 License

This project was developed for educational and academic purposes at Terna Engineering College, Nerul, Navi Mumbai (2026).

---

## ⭐ Support the Project

<div align="center">

**If this project helped you or impressed you, drop a star — it takes 2 seconds and means the world to the team!**

<br/>

<a href="https://github.com/Adinath-Jagtap/parking-management/stargazers">
  <img src="https://img.shields.io/github/stars/Adinath-Jagtap/parking-management?style=for-the-badge&logo=github&labelColor=black&color=FFD700" alt="GitHub Stars"/>
</a>

</div>

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0f3460,50:16213e,100:1a1a2e&height=100&section=footer&fontSize=20&fontColor=e94560" width="100%"/>

**Made with ❤️ by Team ParkEasy · Terna Engineering College · 2026**

</div>
