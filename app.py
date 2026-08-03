"""
==================================================================
 Government Polytechnic Pune
 Electronics and Telecommunication Department
 Smart Attendance System for L2
==================================================================
 Author  : Nikhil Wani
 Stack   : Flask + HTML + CSS + JavaScript + CSV
 Storage : Plain CSV files (no database used, as required)
==================================================================
"""

import csv
import io
import json
import os
import random
import string
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
# Secret key is only used to sign the Flask session cookie (teacher login
# state + anti-proxy device cookie). Not used for any DB / crypto purpose.
app.secret_key = "gpp-l2-smart-attendance-secret-key-2026"

# How long a teacher stays logged in before automatic logout
TEACHER_SESSION_TIMEOUT_MINUTES = 30

# How long a generated attendance password stays valid
PASSWORD_VALIDITY_SECONDS = 120

# Anti proxy: minimum gap required between two attendance submissions
# coming from the SAME browser (device cookie), regardless of session id.
ANTI_PROXY_COOLDOWN_SECONDS = 300  # 5 minutes

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
SYSTEM_HEADER = "Smart Attendance System for L2"
FOOTER_TEXT = "Designed by Nikhil Wani"

# ==================================================================
# IN-MEMORY ACTIVE SESSION STATE
# ==================================================================
# NOTE: Since this project intentionally avoids a database, the LIVE
# attendance session (currently running lecture) is kept in server
# memory. Historical data (closed sessions) always lives in
# attendance.csv, so nothing is lost on restart -- only a session that
# was live at the exact moment of a server restart would need to be
# started again by the teacher.

active_session = {
    "is_active": False,
    "session_id": None,
    "subject": None,
    "faculty": None,
    "password": None,
    "started_at": None,   # datetime
    "expires_at": None,   # datetime
}


# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def load_config():
    """Read teacher security key + any other config from config.json."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_teacher_key():
    return load_config().get("teacher_security_key", "")


def ensure_attendance_csv():
    """Create attendance.csv with header if it does not exist."""
    if not os.path.exists(ATTENDANCE_CSV):
        with open(ATTENDANCE_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Student_ID", "Name", "Date", "Session_ID",
                 "Subject", "Faculty", "Time"]
            )


def load_students():
    """Return dict {student_id: name} from students.csv."""
    students = {}
    if os.path.exists(STUDENTS_CSV):
        with open(STUDENTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sid = row.get("Student_ID", "").strip()
                name = row.get("Name", "").strip()
                if sid:
                    students[sid] = name
    return students


def load_attendance_rows():
    """Return list of dict rows from attendance.csv."""
    ensure_attendance_csv()
    rows = []
    with open(ATTENDANCE_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def append_attendance_row(row):
    ensure_attendance_csv()
    with open(ATTENDANCE_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [row["Student_ID"], row["Name"], row["Date"],
             row["Session_ID"], row["Subject"], row["Faculty"], row["Time"]]
        )


def generate_next_session_id(subject_code):
    """
    Session ID format = SubjectCode + 3 digits, e.g. PYT001, PYT002 ...
    Each subject keeps its own independent numbering. We derive the next
    number by scanning attendance.csv (the permanent record) for the
    highest existing number used by this subject.
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
    # Also consider the currently active session (in case teacher ended
    # a session with zero attendance, so it never made it into the csv)
    if active_session.get("subject") == subject_code and active_session.get("session_id"):
        sess = active_session["session_id"]
        suffix = sess[len(prefix):]
        if suffix.isdigit():
            max_num = max(max_num, int(suffix))
    next_num = max_num + 1
    return f"{prefix}{next_num:03d}"


def generate_password(length=6):
    """6 character password made of capital letters + numbers."""
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def is_teacher_authenticated():
    if not session.get("teacher_auth"):
        return False
    login_time_str = session.get("teacher_auth_time")
    if not login_time_str:
        return False
    login_time = datetime.fromisoformat(login_time_str)
    if datetime.now() - login_time > timedelta(minutes=TEACHER_SESSION_TIMEOUT_MINUTES):
        # Session expired -- force logout
        session.pop("teacher_auth", None)
        session.pop("teacher_auth_time", None)
        return False
    return True


def teacher_required(f):
    """Decorator for routes that require an authenticated teacher."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_teacher_authenticated():
            nxt = request.path
            return redirect(url_for("generate_login", next=nxt))
        return f(*args, **kwargs)
    return wrapper


def get_active_session_public():
    """Return a JSON-safe snapshot of the active session (or empty)."""
    if not active_session["is_active"]:
        return {"is_active": False}

    now = datetime.now()
    remaining = (active_session["expires_at"] - now).total_seconds()
    password_expired = remaining <= 0

    # Count how many students have marked attendance for this live session
    rows = load_attendance_rows()
    present_count = sum(
        1 for r in rows if r.get("Session_ID") == active_session["session_id"]
    )
    total_students = len(load_students())
    percentage = round((present_count / total_students) * 100, 2) if total_students else 0

    return {
        "is_active": True,
        "session_id": active_session["session_id"],
        "subject": active_session["subject"],
        "faculty": active_session["faculty"],
        "password": active_session["password"],
        "password_expired": password_expired,
        "remaining_seconds": max(0, int(remaining)),
        "present_count": present_count,
        "total_students": total_students,
        "attendance_percentage": percentage,
    }


# ==================================================================
# STUDENT ROUTES
# ==================================================================

@app.route("/", methods=["GET"])
def student_login():
    """Student facing page. Only shows Student ID / Password / button."""
    return render_template(
        "login.html",
        college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
    )


@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    """
    AJAX endpoint used by login.html to validate and store attendance.
    Returns JSON: {status: "success"/"error", message: "..."}
    """
    data = request.get_json(silent=True) or request.form
    student_id = (data.get("student_id") or "").strip()
    password = (data.get("password") or "").strip().upper()

    students = load_students()

    # 1. Validate student id
    if student_id not in students:
        return jsonify(status="error", message="Invalid Student ID"), 200

    # 2. Is there an active session at all?
    if not active_session["is_active"]:
        return jsonify(status="error", message="No Active Attendance Session"), 200

    # 3. Password expiry check
    now = datetime.now()
    if now > active_session["expires_at"]:
        return jsonify(status="error", message="Password Expired"), 200

    # 4. Password correctness check
    if password != active_session["password"]:
        return jsonify(status="error", message="Wrong Password"), 200

    # 5. Anti proxy check -- one browser, one attendance, within 5 minutes
    #    (applies across ANY session, to stop one device proxy-marking
    #    attendance for many students back to back).
    last_ts_str = request.cookies.get("gpp_last_attendance_ts")
    if last_ts_str:
        try:
            last_ts = datetime.fromisoformat(last_ts_str)
            elapsed = (now - last_ts).total_seconds()
            if elapsed < ANTI_PROXY_COOLDOWN_SECONDS:
                return jsonify(
                    status="error",
                    message="Attendance already submitted from this device. "
                            "Please wait 5 minutes."
                ), 200
        except ValueError:
            pass  # malformed cookie, ignore and continue

    # 6. Duplicate rule -- one student can mark attendance only once per
    #    Session ID (separate from the anti-proxy device cooldown above).
    session_id = active_session["session_id"]
    rows = load_attendance_rows()
    for row in rows:
        if row.get("Student_ID") == student_id and row.get("Session_ID") == session_id:
            return jsonify(
                status="error",
                message="You have already marked attendance for this session."
            ), 200

    # All checks passed -- store attendance
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
        message=f"Attendance marked successfully for {students[student_id]} "
                 f"({session_id})"
    )
    resp.set_cookie(
        "gpp_last_attendance_ts", now.isoformat(),
        max_age=ANTI_PROXY_COOLDOWN_SECONDS, httponly=True, samesite="Lax"
    )
    return resp


# ==================================================================
# TEACHER AUTH (shared by /generate and /report)
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
            error = "Invalid Security Key"

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
# GENERATE PAGE (teacher creates attendance sessions)
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

    if subject not in SUBJECTS:
        return jsonify(status="error", message="Invalid subject selected"), 400

    if active_session["is_active"]:
        return jsonify(
            status="error",
            message="A session is already active. End it before starting a new one."
        ), 400

    session_id = generate_next_session_id(subject)
    password = generate_password()
    started_at = datetime.now()
    expires_at = started_at + timedelta(seconds=PASSWORD_VALIDITY_SECONDS)

    active_session.update({
        "is_active": True,
        "session_id": session_id,
        "subject": subject,
        "faculty": FACULTY_MAP[subject],
        "password": password,
        "started_at": started_at,
        "expires_at": expires_at,
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
    })
    return jsonify(status="success", message="Attendance Session Closed")


@app.route("/session_status")
@teacher_required
def session_status():
    """Polled by generate.html JS every few seconds for the live dashboard."""
    return jsonify(get_active_session_public())


# ==================================================================
# ANALYTICS HELPERS (shared by report + student profile)
# ==================================================================

def compute_subject_analytics():
    """
    For every subject: faculty, total distinct sessions conducted,
    total attendance records, average attendance percentage.
    Average attendance % = (total attendance records / (sessions * total_students)) * 100
    """
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
    """
    Per-subject breakdown for one student:
    sessions conducted (for that subject), sessions attended by student,
    attendance percentage, plus overall attendance percentage.
    """
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

    # Recent sessions attended by this student (most recent first)
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
        "recent_sessions": student_rows[:10],
        "last_attendance_date": last_date,
        "status": status,
    }


def compute_defaulter_dashboard():
    """
    Classify every student into Safe / Warning / Defaulter zone based
    on their OVERALL attendance percentage across all subjects, and
    also build a flattened subject-wise table for the defaulter view.
    """
    students = load_students()
    safe, warning, defaulter = 0, 0, 0
    table_rows = []
    summary = []

    for sid, name in students.items():
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
    """
    Central JSON endpoint used by report.html's JavaScript to render:
    - filtered attendance table
    - subject analytics cards + charts
    - defaulter dashboard
    - today's summary
    """
    rows = load_attendance_rows()

    # ---- filters ----
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

    # Sort newest first (by Date then Time)
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
    """Search students by ID or name for the Student Analytics section."""
    q = (request.args.get("q") or "").strip().lower()
    students = load_students()
    matches = [
        {"student_id": sid, "name": name}
        for sid, name in students.items()
        if q in sid.lower() or q in name.lower()
    ]
    return jsonify(matches=matches[:20])


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
    """
    Re-authenticate with the teacher security key, then wipe all
    attendance records but KEEP the CSV header. students.csv is
    never touched.
    """
    data = request.get_json(silent=True) or request.form
    entered_key = (data.get("security_key") or "").strip()

    if entered_key != get_teacher_key():
        return jsonify(status="error", message="Invalid Security Key"), 200

    with open(ATTENDANCE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["Student_ID", "Name", "Date", "Session_ID",
             "Subject", "Faculty", "Time"]
        )

    return jsonify(status="success", message="Attendance Reset Successfully")


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
# DOWNLOADS
# ==================================================================

@app.route("/download_csv")
@teacher_required
def download_csv():
    return send_file(
        ATTENDANCE_CSV, as_attachment=True,
        download_name="attendance.csv", mimetype="text/csv"
    )


@app.route("/download_pdf")
@teacher_required
def download_pdf():
    """
    Build a professional PDF attendance report using reportlab:
    College header, department, date, attendance table, summary.
    Optional filters are accepted via query string, same as /report_data.
    """
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
        f"Total Records: {len(rows)}", styles["Normal"]
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
    """Individual student profile PDF (Print PDF button on profile page)."""
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
        Paragraph(f"Overall Attendance: {analytics['overall_percentage']}% ({analytics['status']})", styles["Normal"]),
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
# ERROR HANDLERS
# ==================================================================

@app.errorhandler(404)
def not_found(e):
    return render_template(
        "login.html", college=COLLEGE_HEADER, department=DEPARTMENT_HEADER,
        system=SYSTEM_HEADER, footer=FOOTER_TEXT,
    ), 404


# ==================================================================
# ENTRY POINT
# ==================================================================

if __name__ == "__main__":
    ensure_attendance_csv()
    app.run(debug=True, host="0.0.0.0", port=5000)