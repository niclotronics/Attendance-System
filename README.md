# 🎓 Government Polytechnic Pune - Smart Attendance System v2.0
> **Electronics and Telecommunication Department (L2)**  
> **Author**: Nikhil Wani  
> **Stack**: Python (Flask) + HTML5 + Vanilla CSS (Glassmorphic) + JavaScript + CSV Storage  

---

## 🌟 Overview & Key Features

The **Smart Attendance System v2.0** is an upgraded, high-performance, database-less web application designed specifically for Government Polytechnic Pune. It relies exclusively on structured plain CSV storage while delivering real-time classroom features, advanced security, interactive analytics, and high-end glassmorphic UI aesthetics.

### 🚀 Key Features

1. **⚡ Dynamic QR Code & Projector Mode**:
   - Generates live QR codes when a lecture session starts.
   - Includes a **Fullscreen Projector Mode** designed for classroom smartboards/projectors so students can scan from their seats.
   - Auto-fills the session code and password when scanned.

2. **📱 Dual-Mode Student Portal**:
   - **Mark Attendance**: Students can enter their Roll Number / Student ID and the live session password (or scan via QR).
   - **Check Attendance**: Students can check their overall attendance %, subject breakdown, defaulter status (Safe / Warning / Defaulter), and history without teacher login.

3. **🔐 Smart Anti-Proxy & Security Safeguards**:
   - **Device Cooldown & Fingerprinting**: Prevents proxy attendance from the same device within 5 minutes.
   - **Configurable Password Expiry**: Timers (1 min, 2 min, 5 min, 10 min) with live countdown progress bars.
   - **Master Security Key**: Authentication required for teacher control, roster management, and data resets.

4. **🧑‍🎓 Student Roster Manager & Manual Override**:
   - **Roster Management**: Add, edit, or delete enrolled students directly from the teacher dashboard.
   - **Manual Override**: Allows teachers to manually mark attendance for students with battery or device issues.

5. **📊 Interactive Analytics & Export Options**:
   - **Defaulter Dashboard**: Categorizes students into **Safe** ($\ge 85\%$), **Warning** ($75-84.99\%$), and **Defaulter** ($<75\%$).
   - **Chart.js Integration**: Interactive subject-wise bar charts, pie charts, and horizontal student performance rankings.
   - **Export Options**: Download filtered CSV spreadsheets or professional ReportLab PDF reports with official college branding.

---

## 📁 File Structure

```text
NIKHIL/
├── app.py                  # Core Flask backend server & APIs
├── config.json             # Security configuration & keys
├── requirements.txt        # Dependencies (Flask, ReportLab, Gunicorn)
├── students.csv            # Enrolled student roster
├── attendance.csv          # Attendance logs database file
├── README.md               # Project documentation
├── static/
│   ├── style.css           # Dark Navy Glassmorphism CSS design system
│   └── script.js            # Frontend utilities, QR renderer & modals
└── templates/
    ├── login.html          # Dual-tab Student Portal
    ├── generate.html       # Teacher Live Session Control Hub
    ├── generate_login.html # Teacher Security Key Login
    ├── report.html         # Report & Analytics Hub
    └── student_profile.html# Detailed Student Profile & Graph
```

---

## 🛠️ Installation & Running Locally

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Run Application**:
   ```bash
   python app.py
   ```

3. **Access URLs**:
   - **Student Portal**: `http://localhost:5000/`
   - **Teacher Control Hub**: `http://localhost:5000/generate`
   - **Report Analytics Hub**: `http://localhost:5000/report`

---

## 🔐 Credentials & Default Config

- **Teacher Security Key**: `GPP@L2#2026` (configured in `config.json`)
- **Default Port**: `5000`
- **Subjects Configured**: `PYT`, `ECN`, `DT`, `POC`, `LIC`, `IC`
