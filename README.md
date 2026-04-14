<div align="center">

<!-- Animated Banner -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:1a1a2e,50:16213e,100:0f3460&height=200&section=header&text=ParkSmart%20🚗&fontSize=60&fontColor=e94560&fontAlignY=38&desc=Intelligent%20Parking%20Management%20System&descAlignY=60&descColor=a8b2d8&animation=fadeIn" width="100%"/>

<!-- Live Badge Row -->
<p align="center">
  <a href="https://parking-management-afot.onrender.com/" target="_blank">
    <img src="https://img.shields.io/badge/🌐%20Live%20Demo-Click%20Here-e94560?style=for-the-badge&labelColor=1a1a2e" alt="Live Demo"/>
  </a>
  &nbsp;
  <img src="https://img.shields.io/badge/Python-3.x-3776AB?style=for-the-badge&logo=python&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Flask-3.0-000000?style=for-the-badge&logo=flask&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/MongoDB-Atlas-47A248?style=for-the-badge&logo=mongodb&logoColor=white&labelColor=1a1a2e"/>
  &nbsp;
  <img src="https://img.shields.io/badge/Razorpay-Payments-072654?style=for-the-badge&logo=razorpay&logoColor=white&labelColor=1a1a2e"/>
</p>

<!-- Visitor Count -->
<p align="center">
  <img src="https://komarev.com/ghpvc/?username=parking-management&label=👁️%20Repo%20Views&color=e94560&style=for-the-badge&labelColor=1a1a2e" alt="Visitor Count"/>
</p>

</div>

---

## 🧭 Navigation

<div align="center">

[🎯 About](#-about) · [✨ Features](#-features) · [🏗️ Architecture](#️-tech-stack) · [🚀 Getting Started](#-getting-started) · [📸 Screenshots](#-screenshots) · [👥 Contributors](#-contributors) · [⭐ Support](#-support-the-project)

</div>

---

## 🎯 About

> **ParkSmart** is a full-stack intelligent parking management platform built for the modern world. It bridges the gap between drivers, parking lot admins, and watchmen — all in one unified system.

<div align="center">

| 🧑‍💼 Multi-Role System | 💳 Seamless Payments | 📱 QR-Based Entry | 🕐 Real-Time Slots |
|:---:|:---:|:---:|:---:|
| User · Admin · Watchman · Super Admin | Razorpay + Wallet | QR Code per Vehicle | Live Availability |

</div>

---

## ✨ Features

<table>
<tr>
<td width="50%">

### 👤 For Users
- 🔐 Secure registration & login (CSRF + rate limiting)
- 🚗 Register multiple vehicles with unique QR codes
- 📅 Pre-book parking slots in advance
- 💰 Integrated wallet with Razorpay top-up
- 📜 Subscription plans for regular users
- 🧾 Downloadable invoices & booking history
- 📲 QR code download & regeneration

</td>
<td width="50%">

### 🛠️ For Admins
- 📊 Admin dashboard with analytics
- 🏢 Create & manage parking lots and slots
- 🔑 Generate watchman credentials per lot
- 💼 View all users, invoices & audit logs
- 📦 Define custom subscription plans
- 🔍 Real-time watchman activity audit trail

</td>
</tr>
<tr>
<td width="50%">

### 👮 For Watchmen
- 📷 QR scanner for vehicle check-in/out
- 🔄 Real-time slot status updates
- 📋 Assigned to specific parking lots
- 🔒 Role-restricted secure access

</td>
<td width="50%">

### 🌐 Platform-Wide
- 🦸 Super Admin controls all admins
- ✅ Admin verification & approval flow
- 🌙 IST timezone-aware scheduling
- 🔒 HTTPS-ready with full security headers
- 📦 Deployed on Render.com (production-ready)

</td>
</tr>
</table>

---

## 🏗️ Tech Stack

<div align="center">

| Layer | Technology |
|:---:|:---|
| **Backend** | ![Flask](https://img.shields.io/badge/Flask-000?logo=flask&logoColor=white) ![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white) ![APScheduler](https://img.shields.io/badge/APScheduler-scheduling-orange) |
| **Database** | ![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?logo=mongodb&logoColor=white) ![PyMongo](https://img.shields.io/badge/PyMongo-ODM-green) |
| **Auth & Security** | ![Flask--Login](https://img.shields.io/badge/Flask--Login-session-blue) ![Bcrypt](https://img.shields.io/badge/Bcrypt-hashing-red) ![CSRF](https://img.shields.io/badge/CSRF-protection-yellow) |
| **Payments** | ![Razorpay](https://img.shields.io/badge/Razorpay-072654?logo=razorpay&logoColor=white) |
| **QR Codes** | ![qrcode](https://img.shields.io/badge/qrcode[pil]-generation-blueviolet) |
| **Deployment** | ![Render](https://img.shields.io/badge/Render-46E3B7?logo=render&logoColor=black) ![Gunicorn](https://img.shields.io/badge/Gunicorn-WSGI-green) |

</div>

---

## 🚀 Getting Started

### Prerequisites

```bash
Python 3.x
MongoDB Atlas URI
Razorpay API Keys
```

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/Adinath-Jagtap/parking-management.git
cd parking-management

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your credentials
```

### Environment Variables

```env
SECRET_KEY=your_secret_key
MONGO_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/parking_management
RAZORPAY_KEY_ID=your_razorpay_key
RAZORPAY_KEY_SECRET=your_razorpay_secret
```

### Run Locally

```bash
python app.py
# Visit: http://localhost:5000
```

---

## 🗂️ Project Structure

```
parking-management/
│
├── app.py                  # Main Flask application
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (not committed)
│
├── static/
│   ├── uploads/            # Profile & vehicle images
│   ├── favicon-*.png       # Favicons
│   └── og-image.png        # Social preview image
│
└── templates/              # Jinja2 HTML templates
    ├── user/               # User-facing pages
    ├── admin/              # Admin dashboard pages
    ├── watchman/           # Watchman interface
    └── super_admin/        # Super admin panel
```

---

## 📸 Screenshots

> 🔗 **Try it live →** [parking-management-afot.onrender.com](https://parking-management-afot.onrender.com/)

<div align="center">

| Dashboard | Booking | QR Entry |
|:---:|:---:|:---:|
| 📊 Analytics Overview | 📅 Slot Reservation | 📲 QR Scan Check-in |

</div>

---

## 👥 Contributors

<div align="center">

<!-- ────────────────────── CONTRIBUTOR CARDS ────────────────────── -->

<table>
<tr>

<!-- Card 1 -->
<td align="center" width="200px">
<div>
<a href="https://github.com/Adinath-Jagtap">
<img src="https://avatars.githubusercontent.com/Adinath-Jagtap?v=4" width="90px" style="border-radius:50%;border:3px solid #e94560;" alt="Adinath"/>
</a>
<br/><br/>
<b>Adinath Somnath Jagtap</b>
<br/>
<sub>💻 Full Stack Developer</sub>
<br/><br/>
<a href="https://github.com/Adinath-Jagtap">
<img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/>
</a>
&nbsp;
<a href="https://www.linkedin.com/in/adinath-jagtap">
<img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/>
</a>
</div>
</td>

<!-- Card 2 -->
<td align="center" width="200px">
<div>
<a href="https://github.com/prajwalzolage55">
<img src="https://avatars.githubusercontent.com/prajwalzolage55?v=4" width="90px" style="border-radius:50%;border:3px solid #e94560;" alt="Prajwal"/>
</a>
<br/><br/>
<b>Prajwal Ashok Zolage</b>
<br/>
<sub>💻 Full Stack Developer</sub>
<br/><br/>
<a href="https://github.com/prajwalzolage55">
<img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/>
</a>
&nbsp;
<a href="https://www.linkedin.com/in/prajwal-zolage-82ab10347">
<img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/>
</a>
</div>
</td>

<!-- Card 3 -->
<td align="center" width="200px">
<div>
<a href="https://github.com/VirajK1207">
<img src="https://avatars.githubusercontent.com/VirajK1207?v=4" width="90px" style="border-radius:50%;border:3px solid #e94560;" alt="Viraj"/>
</a>
<br/><br/>
<b>Viraj Vikram Kakade</b>
<br/>
<sub>💻 Full Stack Developer</sub>
<br/><br/>
<a href="https://github.com/VirajK1207">
<img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/>
</a>
&nbsp;
<a href="https://www.linkedin.com/in/viraj-kakade-94ba173a0">
<img src="https://img.shields.io/badge/LinkedIn-0A66C2?style=flat-square&logo=linkedin&logoColor=white"/>
</a>
</div>
</td>

<!-- Card 4 -->
<td align="center" width="200px">
<div>
<a href="https://github.com/anuragamale">
<img src="https://avatars.githubusercontent.com/anuragamale?v=4" width="90px" style="border-radius:50%;border:3px solid #e94560;" alt="Anurag"/>
</a>
<br/><br/>
<b>Anurag Santosh Amale</b>
<br/>
<sub>💻 Full Stack Developer</sub>
<br/><br/>
<a href="https://github.com/anuragamale">
<img src="https://img.shields.io/badge/GitHub-181717?style=flat-square&logo=github&logoColor=white"/>
</a>
</div>
</td>

</tr>
</table>

</div>

---

## ⚡ Roles & Access

```
🌐 Super Admin
    └── ✅ Verify / ❌ Reject / 🔒 Disable Admins
         └── 🏢 Admin
                └── 🅿️ Manage Parking Lots & Slots
                    └── 👮 Watchman (per lot)
                         └── 📷 QR Scan Check-in / Check-out
👤 User
    └── 🚗 Register Vehicles → Get QR
        └── 📅 Pre-Book Slots → 💳 Pay via Razorpay / Wallet
            └── 🧾 Invoice → 📲 Download QR
```

---

## 📄 License

This project is intended for educational and academic purposes.

---

## ⭐ Support the Project

<div align="center">

**If this project helped you or you find it impressive, please consider giving it a star!**

[![Star History Chart](https://api.star-history.com/svg?repos=Adinath-Jagtap/parking-management&type=Date)](https://star-history.com/#Adinath-Jagtap/parking-management&Date)

<br/>

<a href="https://github.com/Adinath-Jagtap/parking-management/stargazers">
  <img src="https://img.shields.io/github/stars/Adinath-Jagtap/parking-management?style=for-the-badge&logo=starship&color=e94560&labelColor=1a1a2e&label=⭐%20Total%20Stars" alt="GitHub Stars"/>
</a>
&nbsp;
<a href="https://github.com/Adinath-Jagtap/parking-management/network/members">
  <img src="https://img.shields.io/github/forks/Adinath-Jagtap/parking-management?style=for-the-badge&logo=git&color=0f3460&labelColor=1a1a2e&label=🍴%20Forks" alt="GitHub Forks"/>
</a>
&nbsp;
<a href="https://github.com/Adinath-Jagtap/parking-management/issues">
  <img src="https://img.shields.io/github/issues/Adinath-Jagtap/parking-management?style=for-the-badge&color=16213e&labelColor=1a1a2e&label=🐛%20Issues" alt="GitHub Issues"/>
</a>

</div>

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0f3460,50:16213e,100:1a1a2e&height=100&section=footer&fontSize=20&fontColor=e94560" width="100%"/>

**Made with ❤️ by Team ParkSmart · Terna Engineering College · 2026**

</div>