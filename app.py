"""
==================================================================
 Government Polytechnic Pune
 Electronics and Telecommunication Department
 Smart Attendance System v2.0 for L2
==================================================================
 Author  : @niclotronics
 Stack   : Flask + HTML + Vanilla CSS + JavaScript + CSV
 Storage : Plain CSV files (No DB required, optimized file I/O)
==================================================================
"""

import csv
import io
import json
import os
import random
import string
import threading
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, send_file, make_response
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER

# ==================================================================
# APP CONFIGURATION
# ==================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
STUDENTS_CSV = os.path.join(BASE_DIR, "students.csv")
ATTENDANCE_CSV = os.path.join(BASE_DIR, "attendance.csv")

app = Flask(__name__)
app.secret_key = "gpp-l2-smart-attendance-secret-key-2026"

TEACHER_SESSION_TIMEOUT_MINUTES = 30
DEFAULT_PASSWORD_VALIDITY_SECONDS = 120
ANTI_PROXY_COOLDOWN_SECONDS = 300  # 5 minutes device cooldown

SUBJECTS = ["PYT", "ECN", "DT", "POC", "LIC", "IC"]

FACULTY_MAP = {
    "PYT": "Chhatwani Mam",
    "ECN": "Deulkar Mam",
    "DT": "Vikhankar Sir",
    "POC": "Rajhans Mam",
    "LIC": "Nimbalkar Mam",
    "IC": "Nimbalkar Mam",
}

COLLEGE_HEADER = "Government Polytechnic Pune"
DEPARTMENT_HEADER = "Electronics and Telecommunication Department"
SYSTEM_HEADER = "Smart Attendance System v2.0 for L2"
FOOTER_TEXT = "Designed by @niclotronics"

csv_lock = threading.Lock()

# ==================================================================
# IN-MEMORY ACTIVE SESSION STATE
# ==================================================================

active_session = {
    "is_active": False,
    "session_id": None,
    "subject": None,
    "faculty": None,
    "password": None,
    "started_at": None,   # datetime
    "expires_at": None,   # datetime
    "duration_seconds": DEFAULT_PASSWORD_VALIDITY_SECONDS,
    "geo_enabled": False,
    "teacher_lat": None,
    "teacher_lng": None,
    "allowed_radius_meters": 50,
}

# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two GPS coordinates in meters using Haversine formula."""
    try:
        R = 6371000  # Radius of Earth in meters
        phi1 = math.radians(float(lat1))
        phi2 = math.radians(float(lat2))
        delta_phi = math.radians(float(lat2) - float(lat1))
        delta_lambda = math.radians(float(lon2) - float(lon1))

        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except (ValueError, TypeError):
        return 999999.0


def load_config():
    """Read teacher security key + config from config.json."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"teacher_security_key": "GPP@L2#2026"}


def get_teacher_key():
    return load_config().get("teacher_security_key", "GPP@L2#2026")


def ensure_attendance_csv():
    """Create attendance.csv with header if it does not exist."""
    with csv_lock:
        if not os.path.exists(ATTENDANCE_CSV) or os.path.getsize(ATTENDANCE_CSV) == 0:
            with open(ATTENDANCE_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    ["Student_ID", "Name", "Date", "Session_ID",
                     "Subject", "Faculty", "Time"]
                )


def ensure_students_csv():
    """Create students.csv with header if missing."""
    with csv_lock:
        if not os.path.exists(STUDENTS_CSV) or os.path.getsize(STUDENTS_CSV) == 0:
            with open(STUDENTS_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Student_ID", "Name"])


def load_students():
    """Return dict {student_id: name} from students.csv."""
    ensure_students_csv()
    students = {}
    with csv_lock:
        if os.path.exists(STUDENTS_CSV):
            with open(STUDENTS_CSV, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sid = (row.get("Student_ID") or "").strip()
                    name = (row.get("Name") or "").strip()
                    if sid:
                        students[sid] = name
    return students


def save_students_dict(students_dict):
    """Save student dict {sid: name} back to students.csv."""
    ensure_students_csv()
    with csv_lock:
        with open(STUDENTS_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Student_ID", "Name"])
            for sid, name in sorted(students_dict.items()):
                writer.writerow([sid, name])


def load_attendance_rows():
    """Return list of dict rows from attendance.csv."""
    ensure_attendance_csv()
    rows = []
    with csv_lock:
        with open(ATTENDANCE_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    return rows


def append_attendance_row(row):
    ensure_attendance_csv()
    with csv_lock:
        with open(ATTENDANCE_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [row["Student_ID"], row["Name"], row["Date"],
                 row["Session_ID"], row["Subject"], row["Faculty"], row["Time"]]
            )


def generate_next_session_id(subject_code):
    """
    Session ID format = SubjectCode + 3 digits, e.g. PYT001, PYT002 ...
    Independent numbering derived from attendance.csv.
    """
    rows = load_attendance_rows()
    max_num = 0
    prefix = subject_code
    for row in rows:
        sess = row.get("Session_ID", "")
        if sess.startswith(prefix):
            suffix = sess[len(prefix):]
            if suffix.isdigit():
                max_num = max(max_num, int(suffix))

    if active_session.get("subject") == subject_code and active_session.get("session_id"):
        sess = active_session["session_id"]
        suffix = sess[len(prefix):]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))

    next_num = max_num + 1
    return f"{prefix}{next_num:03d}"


def generate_password(length=6):
    """6 character random uppercase + digit password."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def is_teacher_authenticated():
    if not session.get("teacher_auth"):
        return False
    login_time_str = session.get("teacher_auth_time")
    if not login_time_str:
        return False
    try:
        login_time = datetime.fromisoformat(login_time_str)
        if datetime.now() - login_time > timedelta(minutes=TEACHER_SESSION_TIMEOUT_MINUTES):
            session.pop("teacher_auth", None)
            session.pop("teacher_auth_time", None)
            return False
    except Exception:
        return False
    return True


def teacher_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_teacher_authenticated():
            if request.path.startswith("/api/") or request.path in ["/report_data", "/session_status", "/start_session", "/end_session", "/manual_mark", "/reset_attendance"]:
                return jsonify(status="error", message="Teacher session expired. Redirecting to login...", redirect=url_for("generate_login", next=request.path)), 200
            nxt = request.path
            return redirect(url_for("generate_login", next=nxt))
        return f(*args, **kwargs)
    return wrapper


def get_active_session_public():
    """Return JSON snapshot of active session for dashboard & clients."""
    if not active_session["is_active"]:
        return {"is_active": False}

    now = datetime.now()
    remaining = (active_session["expires_at"] - now).total_seconds()
    password_expired = remaining <= 0

    rows = load_attendance_rows()
    present_rows = [r for r in rows if r.get("Session_ID") == active_session["session_id"]]
    present_count = len(present_rows)
    total_students = len(load_students())
    percentage = round((present_count / total_students) * 100, 2) if total_students else 0

    # Get recent present student records for ticker
    recent_present = [
        {"student_id": r.get("Student_ID"), "name": r.get("Name"), "time": r.get("Time")}
        for r in reversed(present_rows[-10:])
    ]

    return {
        "is_active": True,
        "session_id": active_session["session_id"],
        "subject": active_session["subject"],
        "faculty": active_session["faculty"],
        "password": active_session["password"],
        "password_expired": password_expired,
        "remaining_seconds": max(0, int(remaining)),
        "duration_seconds": active_session.get("duration_seconds", DEFAULT_PASSWORD_VALIDITY_SECONDS),
        "geo_enabled": active_session.get("geo_enabled", False),
        "allowed_radius_meters": active_session.get("allowed_radius_meters", 50),
        "present_count": present_count,
        "total_students": total_students,
        "attendance_percentage": percentage,
        "recent_present": recent_present,
    }


# ==================================================================
# STUDENT ROUTES & PUBLIC APIS
# ==================================================================

@app.route("/", methods=["GET"])
def student_login():
    """Student portal with Mark Attendance & Student Analytics tabs."""
    return render_template(
        "login.html",
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
    )


@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    """
    AJAX endpoint for marking student attendance.
    Validates Student ID, Session state, Password & Anti-Proxy rules.
    """
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()
    password = (data.get("password") or "").strip().upper()

    students = load_students()

    # 1. Validate student ID
    if student_id not in students:
        return jsonify(status="error", message="Invalid Student ID. Please check your roll number."), 200

    # 2. Check if active session exists
    if not active_session["is_active"]:
        return jsonify(status="error", message="No active attendance session at this time."), 200

    # 3. Password expiry check
    now = datetime.now()
    if now > active_session["expires_at"]:
        return jsonify(status="error", message="Attendance password has expired for this session."), 200

    # 4. Password correctness check
    if password != active_session["password"]:
        return jsonify(status="error", message="Incorrect attendance password. Please verify the code."), 200

    # 4.5 Geofence Location Check (if enabled by teacher for this session)
    if active_session.get("geo_enabled"):
        student_lat = data.get("student_lat")
        student_lng = data.get("student_lng")
        if student_lat is None or student_lng is None:
            return jsonify(
                status="error",
                message="GPS Location required for this session! Please enable Location Services on your device."
            ), 200

        if active_session.get("teacher_lat") is not None and active_session.get("teacher_lng") is not None:
            dist_meters = haversine_distance(
                active_session["teacher_lat"], active_session["teacher_lng"],
                student_lat, student_lng
            )
            max_allowed = active_session.get("allowed_radius_meters", 50)
            if dist_meters > max_allowed:
                return jsonify(
                    status="error",
                    message=f"Location Out of Bounds! You are {int(dist_meters)}m away from classroom (Max allowed: {max_allowed}m)."
                ), 200

    # 5. Anti-proxy cooldown check per browser
    last_ts_str = request.cookies.get("gpp_last_attendance_ts")
    if last_ts_str:
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            elapsed = (now - last_ts).total_seconds()
            if elapsed < ANTI_PROXY_COOLDOWN_SECONDS:
                remaining_wait = int(ANTI_PROXY_COOLDOWN_SECONDS - elapsed)
                return jsonify(
                    status="error",
                    message=f"Anti-proxy security active. Attendance already marked from this device. Please wait {remaining_wait}s."
                ), 200
        except ValueError:
            pass

    # 6. Duplicate check for same session
    session_id = active_session["session_id"]
    rows = load_attendance_rows()
    for row in rows:
        if row.get("Student_ID") == student_id and row.get("Session_ID") == session_id:
            return jsonify(
                status="error",
                message=f"Attendance already marked for student {student_id} in session {session_id}."
            ), 200

    # Passed checks - Record attendance
    new_row = {
        "Student_ID": student_id,
        "Name": students[student_id],
        "Date": now.strftime("%Y-%m-%d"),
        "Session_ID": session_id,
        "Subject": active_session["subject"],
        "Faculty": active_session["faculty"],
        "Time": now.strftime("%H:%M:%S"),
    }
    append_attendance_row(new_row)

    resp = jsonify(
        status="success",
        message=f"Success! Attendance marked for {students[student_id]} ({student_id}) in {session_id}."
    )
    resp.set_cookie(
        "gpp_last_attendance_ts", now.isoformat(),
        max_age=ANTI_PROXY_COOLDOWN_SECONDS, httponly=True, samesite="Lax"
    )
    return resp


@app.route("/api/student_lookup/<student_id>")
def student_lookup_api(student_id):
    """Public lookup API for students to check their personal attendance."""
    student_id = student_id.strip()
    analytics = compute_student_analytics(student_id)
    if not analytics:
        return jsonify(status="error", message="Student ID not found in roster."), 404
    return jsonify(status="success", data=analytics)


# ==================================================================
# TEACHER AUTH
# ==================================================================

@app.route("/generate_login", methods=["GET", "POST"])
def generate_login():
    error = None
    next_url = request.args.get("next") or url_for("generate_page")
    if request.method == "POST":
        entered_key = (request.form.get("security_key") or "").strip()
        next_url = request.form.get("next") or next_url
        if entered_key == get_teacher_key():
            session["teacher_auth"] = True
            session["teacher_auth_time"] = datetime.now().isoformat()
            return redirect(next_url)
        else:
            error = "Invalid Teacher Security Key."

    return render_template(
        "generate_login.html", error=error, next_url=next_url,
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
    )


@app.route("/logout_teacher")
def logout_teacher():
    session.pop("teacher_auth", None)
    session.pop("teacher_auth_time", None)
    return redirect(url_for("student_login"))


# ==================================================================
# GENERATE PAGE (Teacher Attendance Control Hub)
# ==================================================================

@app.route("/generate")
@teacher_required
def generate_page():
    return render_template(
        "generate.html",
        subjects=SUBJECTS, faculty_map=FACULTY_MAP,
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
        timeout_minutes=TEACHER_SESSION_TIMEOUT_MINUTES,
    )


@app.route("/start_session", methods=["POST"])
@teacher_required
def start_session():
    data = request.get_json(silent=True) or request.form
    subject = (data.get("subject") or "").strip().upper()
    try:
        duration_seconds = int(data.get("duration", DEFAULT_PASSWORD_VALIDITY_SECONDS))
        if duration_seconds < 30 or duration_seconds > 1800:
            duration_seconds = DEFAULT_PASSWORD_VALIDITY_SECONDS
    except (ValueError, TypeError):
        duration_seconds = DEFAULT_PASSWORD_VALIDITY_SECONDS

    geo_enabled = bool(data.get("geo_enabled"))
    teacher_lat = data.get("teacher_lat")
    teacher_lng = data.get("teacher_lng")
    try:
        allowed_radius = int(data.get("radius", 50))
        if allowed_radius < 10 or allowed_radius > 1000:
            allowed_radius = 50
    except (ValueError, TypeError):
        allowed_radius = 50

    if subject not in SUBJECTS:
        return jsonify(status="error", message="Invalid subject selected"), 400

    if active_session["is_active"]:
        return jsonify(
            status="error",
            message="A session is already active. End it before starting a new one."
        ), 400

    if geo_enabled and (teacher_lat is None or teacher_lng is None):
        return jsonify(
            status="error",
            message="GPS Location required to enable Geofenced session. Please allow location access."
        ), 400

    session_id = generate_next_session_id(subject)
    password = generate_password()
    started_at = datetime.now()
    expires_at = started_at + timedelta(seconds=duration_seconds)

    active_session.update({
        "is_active": True,
        "session_id": session_id,
        "subject": subject,
        "faculty": FACULTY_MAP[subject],
        "password": password,
        "started_at": started_at,
        "expires_at": expires_at,
        "duration_seconds": duration_seconds,
        "geo_enabled": geo_enabled,
        "teacher_lat": float(teacher_lat) if teacher_lat is not None else None,
        "teacher_lng": float(teacher_lng) if teacher_lng is not None else None,
        "allowed_radius_meters": allowed_radius,
    })

    return jsonify(status="success", session=get_active_session_public())


@app.route("/end_session", methods=["POST"])
@teacher_required
def end_session():
    active_session.update({
        "is_active": False,
        "session_id": None,
        "subject": None,
        "faculty": None,
        "password": None,
        "started_at": None,
        "expires_at": None,
        "duration_seconds": DEFAULT_PASSWORD_VALIDITY_SECONDS,
        "geo_enabled": False,
        "teacher_lat": None,
        "teacher_lng": None,
        "allowed_radius_meters": 50,
    })
    return jsonify(status="success", message="Attendance Session Closed Successfully")


@app.route("/session_status")
def session_status():
    """Polled by dashboard & client pages."""
    return jsonify(get_active_session_public())


# ==================================================================
# MANUAL OVERRIDE & ROSTER MANAGEMENT
# ==================================================================

@app.route("/manual_mark", methods=["POST"])
@teacher_required
def manual_mark():
    """Teacher manual attendance override for a specific student."""
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()
    subject = (data.get("subject") or "").strip().upper()
    session_id = (data.get("session_id") or "").strip().upper()
    date_str = (data.get("date") or "").strip() or datetime.now().strftime("%Y-%m-%d")

    students = load_students()
    if student_id not in students:
        return jsonify(status="error", message="Student ID not found in roster"), 400

    if subject not in SUBJECTS:
        return jsonify(status="error", message="Invalid subject code"), 400

    if not session_id:
        session_id = f"{subject}MAN"

    # Duplicate check
    rows = load_attendance_rows()
    for r in rows:
        if r.get("Student_ID") == student_id and r.get("Session_ID") == session_id:
            return jsonify(status="error", message="Attendance already recorded for this student & session"), 400

    now = datetime.now()
    new_row = {
        "Student_ID": student_id,
        "Name": students[student_id],
        "Date": date_str,
        "Session_ID": session_id,
        "Subject": subject,
        "Faculty": FACULTY_MAP[subject],
        "Time": now.strftime("%H:%M:%S"),
    }
    append_attendance_row(new_row)

    return jsonify(status="success", message=f"Manual attendance marked for {students[student_id]} ({student_id})")


@app.route("/api/students", methods=["GET"])
@teacher_required
def get_students_api():
    students = load_students()
    student_list = [{"student_id": sid, "name": name} for sid, name in sorted(students.items())]
    return jsonify(status="success", students=student_list)


@app.route("/api/add_student", methods=["POST"])
@teacher_required
def add_student_api():
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()
    name = (data.get("name") or "").strip().upper()

    if not student_id or not name:
        return jsonify(status="error", message="Student ID and Name are required"), 400

    students = load_students()
    if student_id in students:
        return jsonify(status="error", message="Student ID already exists"), 400

    students[student_id] = name
    save_students_dict(students)
    return jsonify(status="success", message=f"Added student {name} ({student_id})")


@app.route("/api/edit_student", methods=["POST"])
@teacher_required
def edit_student_api():
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()
    name = (data.get("name") or "").strip().upper()

    students = load_students()
    if student_id not in students:
        return jsonify(status="error", message="Student ID not found"), 404

    students[student_id] = name
    save_students_dict(students)
    return jsonify(status="success", message=f"Updated student name to {name}")


@app.route("/api/delete_student", methods=["POST"])
@teacher_required
def delete_student_api():
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()

    students = load_students()
    if student_id not in students:
        return jsonify(status="error", message="Student ID not found"), 404

    del students[student_id]
    save_students_dict(students)
    return jsonify(status="success", message=f"Deleted student {student_id}")


# ==================================================================
# ANALYTICS HELPERS
# ==================================================================

def compute_subject_analytics():
    """Per subject stats: conducted sessions, records, average percentage."""
    rows = load_attendance_rows()
    total_students = len(load_students()) or 1

    result = []
    for subj in SUBJECTS:
        subj_rows = [r for r in rows if r.get("Subject") == subj]
        sessions = sorted(set(r.get("Session_ID") for r in subj_rows if r.get("Session_ID")))
        total_sessions = len(sessions)
        total_records = len(subj_rows)
        max_possible = total_sessions * total_students
        avg_pct = round((total_records / max_possible) * 100, 2) if max_possible else 0.0
        result.append({
            "subject": subj,
            "faculty": FACULTY_MAP[subj],
            "total_sessions": total_sessions,
            "total_records": total_records,
            "avg_percentage": avg_pct,
        })
    return result


def compute_student_analytics(student_id):
    """Detailed breakdown for a specific student across all subjects."""
    rows = load_attendance_rows()
    students = load_students()
    name = students.get(student_id)
    if name is None:
        return None

    breakdown = []
    total_conducted = 0
    total_attended = 0

    for subj in SUBJECTS:
        subj_rows = [r for r in rows if r.get("Subject") == subj]
        sessions_conducted = sorted(set(
            r.get("Session_ID") for r in subj_rows if r.get("Session_ID")
        ))
        conducted_count = len(sessions_conducted)

        attended_sessions = set(
            r.get("Session_ID") for r in subj_rows
            if r.get("Student_ID") == student_id
        )
        attended_count = len(attended_sessions)

        pct = round((attended_count / conducted_count) * 100, 2) if conducted_count else 0.0

        total_conducted += conducted_count
        total_attended += attended_count

        breakdown.append({
            "subject": subj,
            "faculty": FACULTY_MAP[subj],
            "sessions_conducted": conducted_count,
            "sessions_attended": attended_count,
            "percentage": pct,
        })

    overall_pct = round((total_attended / total_conducted) * 100, 2) if total_conducted else 0.0

    student_rows = [r for r in rows if r.get("Student_ID") == student_id]
    student_rows.sort(key=lambda r: (r.get("Date", ""), r.get("Time", "")), reverse=True)
    last_date = student_rows[0]["Date"] if student_rows else None

    if overall_pct >= 85:
        status = "Safe"
    elif overall_pct >= 75:
        status = "Warning"
    else:
        status = "Defaulter"

    return {
        "student_id": student_id,
        "name": name,
        "breakdown": breakdown,
        "overall_percentage": overall_pct,
        "recent_sessions": student_rows[:15],
        "last_attendance_date": last_date,
        "status": status,
    }


def compute_defaulter_dashboard():
    """Classification of all students into Safe / Warning / Defaulter zones."""
    students = load_students()
    safe, warning, defaulter = 0, 0, 0
    table_rows = []
    summary = []

    for sid, name in sorted(students.items()):
        analytics = compute_student_analytics(sid)
        overall = analytics["overall_percentage"]

        if overall >= 85:
            safe += 1
        elif overall >= 75:
            warning += 1
        else:
            defaulter += 1

        summary.append({
            "student_id": sid, "name": name,
            "overall_percentage": overall, "status": analytics["status"],
        })

        for item in analytics["breakdown"]:
            if item["sessions_conducted"] == 0:
                continue
            pct = item["percentage"]
            if pct >= 85:
                status = "Safe"
            elif pct >= 75:
                status = "Warning"
            else:
                status = "Defaulter"
            table_rows.append({
                "student_id": sid, "name": name,
                "subject": item["subject"], "percentage": pct,
                "status": status,
            })

    return {
        "safe_count": safe, "warning_count": warning, "defaulter_count": defaulter,
        "table_rows": table_rows, "student_summary": summary,
    }


def compute_today_summary():
    rows = load_attendance_rows()
    today = datetime.now().strftime("%Y-%m-%d")
    today_rows = [r for r in rows if r.get("Date") == today]
    sessions_today = sorted(set(r.get("Session_ID") for r in today_rows if r.get("Session_ID")))

    subj_analytics = compute_subject_analytics()
    subj_with_sessions = [s for s in subj_analytics if s["total_sessions"] > 0]
    best_subject = max(subj_with_sessions, key=lambda s: s["avg_percentage"], default=None)
    lowest_subject = min(subj_with_sessions, key=lambda s: s["avg_percentage"], default=None)

    total_students = len(load_students()) or 1
    max_possible_today = len(sessions_today) * total_students
    avg_today = round((len(today_rows) / max_possible_today) * 100, 2) if max_possible_today else 0.0

    return {
        "today_date": today,
        "sessions_conducted_today": len(sessions_today),
        "attendance_entries_today": len(today_rows),
        "average_attendance_today": avg_today,
        "best_subject": best_subject["subject"] if best_subject else "N/A",
        "lowest_subject": lowest_subject["subject"] if lowest_subject else "N/A",
    }


# ==================================================================
# REPORT PAGE
# ==================================================================

@app.route("/report")
@teacher_required
def report_page():
    students = load_students()
    return render_template(
        "report.html",
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
        subjects=SUBJECTS, faculty_map=FACULTY_MAP,
        students=students,
    )


@app.route("/report_data")
@teacher_required
def report_data():
    rows = load_attendance_rows()

    student_id_q = (request.args.get("student_id") or "").strip().lower()
    student_name_q = (request.args.get("student_name") or "").strip().lower()
    date_q = (request.args.get("date") or "").strip()
    subject_q = (request.args.get("subject") or "").strip()
    faculty_q = (request.args.get("faculty") or "").strip().lower()
    session_q = (request.args.get("session_id") or "").strip().lower()

    filtered = []
    for r in rows:
        if student_id_q and student_id_q not in r.get("Student_ID", "").lower():
            continue
        if student_name_q and student_name_q not in r.get("Name", "").lower():
            continue
        if date_q and r.get("Date") != date_q:
            continue
        if subject_q and r.get("Subject") != subject_q:
            continue
        if faculty_q and faculty_q not in r.get("Faculty", "").lower():
            continue
        if session_q and session_q not in r.get("Session_ID", "").lower():
            continue
        filtered.append(r)

    filtered.sort(key=lambda r: (r.get("Date", ""), r.get("Time", "")), reverse=True)

    total_records = len(rows)
    total_students_present = len(set(r.get("Student_ID") for r in rows))

    return jsonify(
        rows=filtered,
        total_records=total_records,
        total_students_present=total_students_present,
        subject_analytics=compute_subject_analytics(),
        defaulter_dashboard=compute_defaulter_dashboard(),
        today_summary=compute_today_summary(),
    )


@app.route("/student_search")
@teacher_required
def student_search():
    q = (request.args.get("q") or "").strip().lower()
    students = load_students()
    matches = [
        {"student_id": sid, "name": name}
        for sid, name in students.items()
        if q in sid.lower() or q in name.lower()
    ]
    return jsonify(matches=matches[:25])


@app.route("/student_analytics/<student_id>")
@teacher_required
def student_analytics_api(student_id):
    analytics = compute_student_analytics(student_id)
    if analytics is None:
        return jsonify(status="error", message="Invalid Student ID"), 404
    return jsonify(status="success", data=analytics)


@app.route("/reset_attendance", methods=["POST"])
@teacher_required
def reset_attendance():
    data = request.get_json(silent=True) or request.form
    entered_key = (data.get("security_key") or "").strip()

    if entered_key != get_teacher_key():
        return jsonify(status="error", message="Invalid Security Key"), 200

    with csv_lock:
        with open(ATTENDANCE_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Student_ID", "Name", "Date", "Session_ID",
                 "Subject", "Faculty", "Time"]
            )

    return jsonify(status="success", message="All Attendance Records Reset Successfully")


# ==================================================================
# STUDENT PROFILE PAGE
# ==================================================================

@app.route("/student_profile/<student_id>")
@teacher_required
def student_profile(student_id):
    analytics = compute_student_analytics(student_id)
    if analytics is None:
        return redirect(url_for("report_page"))

    return render_template(
        "student_profile.html",
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
        analytics=analytics,
    )


# ==================================================================
# DOWNLOADS & PDF EXPORT
# ==================================================================

@app.route("/download_csv")
@teacher_required
def download_csv():
    ensure_attendance_csv()
    return send_file(
        ATTENDANCE_CSV, as_attachment=True,
        download_name="attendance.csv", mimetype="text/csv"
    )


@app.route("/download_pdf")
@teacher_required
def download_pdf():
    rows = load_attendance_rows()

    subject_q = (request.args.get("subject") or "").strip()
    date_q = (request.args.get("date") or "").strip()
    if subject_q:
        rows = [r for r in rows if r.get("Subject") == subject_q]
    if date_q:
        rows = [r for r in rows if r.get("Date") == date_q]

    rows.sort(key=lambda r: (r.get("Date", ""), r.get("Time", "")), reverse=True)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=15 * mm, bottomMargin=15 * mm,
        leftMargin=12 * mm, rightMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"], fontSize=16,
        alignment=TA_CENTER, textColor=colors.HexColor("#0B1F3A"),
    )
    sub_style = ParagraphStyle(
        "SubStyle", parent=styles["Normal"], fontSize=10,
        alignment=TA_CENTER, textColor=colors.HexColor("#2B4C7E"),
    )

    elements = [
        Paragraph(COLLEGE_HEADER, title_style),
        Paragraph(DEPARTMENT_HEADER, sub_style),
        Paragraph(SYSTEM_HEADER, sub_style),
        Spacer(1, 6),
        Paragraph(f"Report Generated On: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", sub_style),
        Spacer(1, 12),
    ]

    table_data = [["Student ID", "Name", "Date", "Session ID", "Subject", "Faculty", "Time"]]
    for r in rows:
        table_data.append([
            r.get("Student_ID", ""), r.get("Name", ""), r.get("Date", ""),
            r.get("Session_ID", ""), r.get("Subject", ""),
            r.get("Faculty", ""), r.get("Time", ""),
        ])

    tbl = Table(table_data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F3A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EAF0FB")]),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(tbl)

    elements.append(Spacer(1, 14))
    elements.append(Paragraph(
        f"Total Attendance Entries: {len(rows)}", styles["Normal"]
    ))
    elements.append(Paragraph(FOOTER_TEXT, sub_style))

    doc.build(elements)
    buffer.seek(0)

    return send_file(
        buffer, as_attachment=True,
        download_name=f"attendance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        mimetype="application/pdf",
    )


@app.route("/download_student_pdf/<student_id>")
@teacher_required
def download_student_pdf(student_id):
    analytics = compute_student_analytics(student_id)
    if analytics is None:
        return redirect(url_for("report_page"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Title"], fontSize=15,
        alignment=TA_CENTER, textColor=colors.HexColor("#0B1F3A"),
    )
    sub_style = ParagraphStyle(
        "SubStyle", parent=styles["Normal"], fontSize=10,
        alignment=TA_CENTER, textColor=colors.HexColor("#2B4C7E"),
    )

    elements = [
        Paragraph(COLLEGE_HEADER, title_style),
        Paragraph(DEPARTMENT_HEADER, sub_style),
        Paragraph(SYSTEM_HEADER, sub_style),
        Spacer(1, 10),
        Paragraph(f"Student Profile: {analytics['name']} ({analytics['student_id']})", styles["Heading2"]),
        Paragraph(f"Overall Attendance: {analytics['overall_percentage']}% ({analytics['status']} Zone)", styles["Normal"]),
        Spacer(1, 10),
    ]

    table_data = [["Subject", "Faculty", "Sessions Conducted", "Sessions Attended", "Attendance %"]]
    for item in analytics["breakdown"]:
        table_data.append([
            item["subject"], item["faculty"],
            item["sessions_conducted"], item["sessions_attended"],
            f"{item['percentage']}%",
        ])

    tbl = Table(table_data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F3A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#AAAAAA")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 14))
    elements.append(Paragraph(FOOTER_TEXT, sub_style))

    doc.build(elements)
    buffer.seek(0)
    return send_file(
        buffer, as_attachment=True,
        download_name=f"{analytics['student_id']}_profile.pdf",
        mimetype="application/pdf",
    )


# ==================================================================
# ERROR HANDLERS & SERVER ENTRY POINT
# ==================================================================

@app.errorhandler(404)
def not_found(e):
    return render_template(
        "login.html", college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
    ), 404


if __name__ == "__main__":
    ensure_students_csv()
    ensure_attendance_csv()
    app.run(debug=True, host="0.0.0.0", port=5050)