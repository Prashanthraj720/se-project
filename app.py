"""Hostel Mess Management System (HMMS) - single-file Streamlit app."""
import hashlib
import os
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------- constants
DB_FILE = "hmms.db"
PBKDF2_ROUNDS = 200_000
ROLES = ["Student", "Mess Staff", "Warden", "Admin"]
MEAL_TYPES = ["Breakfast", "Lunch", "Dinner"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COMPLAINT_STATUSES = ["Pending", "In Progress", "Resolved"]
LEAVE_STATUSES = ["Pending", "Approved", "Rejected"]
PAYMENT_METHODS = ["UPI", "Credit/Debit Card", "Net Banking"]
DEFAULT_SETTINGS = {
    "meal_rate": "50",
    "time_Breakfast": "07:30 - 09:30",
    "time_Lunch": "12:30 - 14:30",
    "time_Dinner": "19:30 - 21:30",
}
# (username, password, full name, email, phone, role, room)
DEMO_USERS = [
    ("admin", "admin123", "System Admin", "admin@hostel.local", "9000000001", "Admin", ""),
    ("warden", "warden123", "Hostel Warden", "warden@hostel.local", "9000000002", "Warden", ""),
    ("staff", "staff123", "Mess Staff", "staff@hostel.local", "9000000003", "Mess Staff", ""),
    ("student1", "student123", "Demo Student", "student1@hostel.local", "9000000004", "Student", "A-101"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT,
    phone TEXT,
    role TEXT NOT NULL,
    room_no TEXT,
    balance REAL DEFAULT 0,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS menu (
    menu_id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    items TEXT NOT NULL,
    menu_date TEXT
);
CREATE TABLE IF NOT EXISTS meal_record (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    date TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Present',
    verified INTEGER DEFAULT 0,
    UNIQUE (student_id, date, meal_type)
);
CREATE TABLE IF NOT EXISTS bill (
    bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    month TEXT NOT NULL,
    total_amount REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'Unpaid',
    UNIQUE (student_id, month)
);
CREATE TABLE IF NOT EXISTS payment (
    payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES bill(bill_id),
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    amount REAL NOT NULL,
    payment_date TEXT NOT NULL,
    transaction_id TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT UNIQUE NOT NULL,
    quantity REAL NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    unit TEXT,
    price REAL DEFAULT 0,
    min_level REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS stock_request (
    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_id INTEGER NOT NULL REFERENCES users(user_id),
    item_id INTEGER NOT NULL REFERENCES inventory(item_id),
    request_date TEXT NOT NULL,
    requested_quantity REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS complaint (
    complaint_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    description TEXT NOT NULL,
    date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
);
CREATE TABLE IF NOT EXISTS feedback (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    message TEXT NOT NULL,
    rating INTEGER,
    date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leave_request (
    leave_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES users(user_id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Pending'
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

ATTENDANCE_SQL = """
SELECT u.full_name AS Student, u.room_no AS Room,
       SUM(CASE WHEN m.status = 'Present' THEN 1 ELSE 0 END) AS Marked,
       SUM(m.verified) AS Verified
FROM meal_record m JOIN users u ON u.user_id = m.student_id
WHERE m.date LIKE ?
GROUP BY u.user_id
ORDER BY u.full_name
"""
BILLING_SQL = """
SELECT month AS Month, COUNT(*) AS Bills, SUM(total_amount) AS Total,
       SUM(CASE WHEN status = 'Paid' THEN total_amount ELSE 0 END) AS Collected,
       SUM(CASE WHEN status = 'Unpaid' THEN total_amount ELSE 0 END) AS Outstanding
FROM bill GROUP BY month ORDER BY month DESC
"""
STOCK_SQL = """
SELECT item_name AS Item, quantity AS Quantity, unit AS Unit, price AS Price,
       ROUND(quantity * price, 2) AS Value,
       CASE WHEN quantity <= min_level THEN 'LOW' ELSE 'OK' END AS Level
FROM inventory ORDER BY item_name
"""

# Clean, minimal light look: white page, hairline borders, one dark accent, no shadows.
APP_CSS = """
<style>
#MainMenu, footer { visibility: hidden; }
.stApp { background: #ffffff; color: #1f2937; }
.block-container { padding-top: 2.5rem; max-width: 1040px; }
h1, h2, h3 { color: #111827; font-weight: 600; letter-spacing: -0.01em; }
h2 { font-size: 1.6rem; }
h3 { font-size: 1.1rem; margin-top: 1.2rem; }
section[data-testid="stSidebar"] { background: #f8fafc; border-right: 1px solid #e5e7eb; }
div[data-testid="stForm"] {
    background: #ffffff; border: 1px solid #e5e7eb; border-radius: 10px;
    padding: 1rem 1.2rem; box-shadow: none;
}
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button,
button[data-testid="stBaseButton-secondary"], button[data-testid="stBaseButton-secondaryFormSubmit"] {
    background: #111827; color: #ffffff; border: 1px solid #111827; border-radius: 8px;
    padding: 0.45rem 1.1rem; font-weight: 500;
}
.stButton > button p, .stFormSubmitButton > button p, .stDownloadButton > button p { color: #ffffff; }
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {
    background: #374151; border-color: #374151; color: #ffffff;
}
div[data-testid="stMetric"] {
    background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 10px; padding: 12px 16px;
}
div[data-testid="stMetricLabel"] { color: #6b7280; }
button[data-baseweb="tab"] { font-weight: 500; }
.stTable td, .stTable th { padding: 0.6rem 0.9rem; }
.login-title { text-align: center; font-size: 1.7rem; font-weight: 700; color: #111827; margin: 2.5rem 0 0.3rem; }
.login-sub { text-align: center; color: #6b7280; margin-bottom: 1.2rem; }
.hint { text-align: center; font-size: 0.82rem; color: #6b7280; margin-top: 0.9rem; }
@media (max-width: 640px) { .login-title { font-size: 1.35rem; } }
</style>
"""

# Must be the first Streamlit call in the script.
st.set_page_config(page_title="HMMS", page_icon="🍽️", layout="wide")


# ------------------------------------------------------------ database layer
def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def fetch_all(sql, params=()):
    conn = get_conn()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def fetch_one(sql, params=()):
    conn = get_conn()
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def count_rows(sql, params=()):
    return fetch_one(sql, params)[0]


def run_statements(statements):
    """Run (sql, params) pairs in one transaction so a failure leaves nothing half-written."""
    conn = get_conn()
    try:
        with conn:
            for sql, params in statements:
                conn.execute(sql, params)
    finally:
        conn.close()


def flash(message, kind="success"):
    # Messages are stored in session state because st.rerun() would erase inline ones.
    st.session_state["flash"] = (kind, message)


def show_flash():
    pending = st.session_state.pop("flash", None)
    if pending:
        kind, message = pending
        {"success": st.success, "error": st.error, "warning": st.warning}[kind](message)


def save(statements, success_message, conflict_message="That record already exists or is still in use."):
    """Write to the database, queue a message for the user, then refresh the page."""
    if not statements:
        flash("Nothing to update (the bill may already be paid).", "warning")
    else:
        try:
            run_statements(statements)
            flash(success_message, "success")
        except sqlite3.IntegrityError:
            flash(conflict_message, "error")
        except sqlite3.Error as err:
            flash(f"Database error: {err}", "error")
    st.rerun()


def init_db():
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def seed_data():
    """Create default settings, and demo accounts on the very first run only."""
    statements = [
        ("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        for key, value in DEFAULT_SETTINGS.items()
    ]
    if count_rows("SELECT COUNT(*) FROM users") == 0:
        for username, password, full_name, email, phone, role, room_no in DEMO_USERS:
            password_hash, salt = hash_password(password)
            statements.append((
                "INSERT INTO users (username, password_hash, salt, full_name, email, phone, role, room_no) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, password_hash, salt, full_name, email, phone, role, room_no),
            ))
    run_statements(statements)


def get_setting(key):
    row = fetch_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def setting_statement(key, value):
    return ("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))


def get_meal_rate():
    try:
        return float(get_setting("meal_rate"))
    except ValueError:
        return float(DEFAULT_SETTINGS["meal_rate"])


def is_on_leave(student_id, day):
    """True when the student has an approved leave covering the given ISO date."""
    return count_rows(
        "SELECT COUNT(*) FROM leave_request "
        "WHERE student_id = ? AND status = 'Approved' AND ? BETWEEN start_date AND end_date",
        (student_id, day),
    ) > 0


def build_bill_statements(student_id, month):
    """Writes that create or refresh a month's bill from verified meals (paid bills stay untouched)."""
    meals = count_rows(
        "SELECT COUNT(*) FROM meal_record "
        "WHERE student_id = ? AND status = 'Present' AND verified = 1 AND date LIKE ?",
        (student_id, f"{month}%"),
    )
    total = round(meals * get_meal_rate(), 2)
    existing = fetch_one("SELECT status FROM bill WHERE student_id = ? AND month = ?", (student_id, month))
    if existing is None:
        return [("INSERT INTO bill (student_id, month, total_amount, status) VALUES (?, ?, ?, 'Unpaid')",
                 (student_id, month, total))]
    if existing["status"] == "Unpaid":
        return [("UPDATE bill SET total_amount = ? WHERE student_id = ? AND month = ?",
                 (total, student_id, month))]
    return []


def create_backup():
    """Copy the live database into a timestamped file using SQLite's own backup API."""
    backup_name = f"hmms_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    source = get_conn()
    target = sqlite3.connect(backup_name)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_name


@st.cache_resource
def setup_database():
    init_db()
    seed_data()
    return True


# ---------------------------------------------------------- security helpers
def hash_password(password, salt=None):
    salt_bytes = salt if salt is not None else os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, PBKDF2_ROUNDS)
    return digest.hex(), salt_bytes.hex()


def verify_password(password, stored_hash, salt_hex):
    candidate, _ = hash_password(password, bytes.fromhex(salt_hex))
    return candidate == stored_hash


def authenticate(username, password):
    """Return (user_row, None) on success or (None, error_message) on failure."""
    row = fetch_one("SELECT * FROM users WHERE username = ?", (username,))
    if row is None or not verify_password(password, row["password_hash"], row["salt"]):
        return None, "Invalid username or password. Please try again."
    if not row["active"]:
        return None, "This account is deactivated. Please contact the administrator."
    return row, None


# --------------------------------------------------------------- UI helpers
def inject_css():
    st.markdown(APP_CSS, unsafe_allow_html=True)


def rows_to_df(rows):
    return pd.DataFrame([dict(row) for row in rows])


def show_table(rows, empty_text="No records yet."):
    if rows:
        st.dataframe(rows_to_df(rows), hide_index=True)
    else:
        st.info(empty_text)


def show_report(title, rows, key):
    st.subheader(title)
    if not rows:
        st.info("No data for this report yet.")
        return
    frame = rows_to_df(rows)
    st.dataframe(frame, hide_index=True)
    st.download_button("Download CSV", frame.to_csv(index=False).encode("utf-8"),
                       file_name=f"{key}.csv", mime="text/csv", key=f"download_{key}")


def render_metrics(metrics):
    """Show (label, value) pairs as a row of metric cards."""
    for column, (label, value) in zip(st.columns(len(metrics)), metrics):
        column.metric(label, value)


def render_bar_chart(title, rows, label_column, empty_text):
    st.subheader(title)
    if not rows:
        st.info(empty_text)
        return
    st.bar_chart(rows_to_df(rows).set_index(label_column))


def pick_row(label, rows, id_column, describe, key, empty_text="Nothing to choose from yet."):
    """Selectbox over database rows; returns the chosen row, or None if there are no rows."""
    if not rows:
        st.info(empty_text)
        return None
    by_id = {row[id_column]: row for row in rows}
    chosen = st.selectbox(label, list(by_id), format_func=lambda row_id: describe(by_id[row_id]), key=key)
    return by_id[chosen]


def valid_month(text):
    try:
        datetime.strptime(text, "%Y-%m")
        return True
    except ValueError:
        return False


def reports_section(prefix):
    """Attendance, billing and stock reports shared by the staff and warden pages."""
    month = st.text_input("Month for the attendance summary (YYYY-MM)",
                          value=date.today().strftime("%Y-%m"), key=f"{prefix}_report_month").strip()
    if valid_month(month):
        show_report(f"Attendance summary - {month}", fetch_all(ATTENDANCE_SQL, (f"{month}%",)),
                    f"{prefix}_attendance")
    else:
        st.error("Please use the format YYYY-MM, for example 2025-01.")
    show_report("Billing summary", fetch_all(BILLING_SQL), f"{prefix}_billing")
    show_report("Stock summary", fetch_all(STOCK_SQL), f"{prefix}_stock")


# ---------------------------------------------------------------- login page
def login_page():
    _, centre, _ = st.columns([1, 1.4, 1])
    with centre:
        st.markdown('<div class="login-title">Hostel Mess Management System</div>'
                    '<div class="login-sub">Sign in to continue</div>', unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Login")
        st.markdown(
            '<div class="hint">Demo logins: admin / admin123 &middot; warden / warden123 &middot; '
            'staff / staff123 &middot; student1 / student123</div>',
            unsafe_allow_html=True,
        )
        if submitted:
            if not username.strip() or not password:
                st.warning("Please enter both username and password.")
                return
            row, error = authenticate(username.strip(), password)
            if error:
                st.error(error)
                return
            st.session_state["user"] = {key: row[key] for key in ("user_id", "username", "full_name", "role")}
            st.rerun()


# ------------------------------------------------------------- student pages
def render_today_menu():
    today_name = DAYS[date.today().weekday()]
    st.subheader(f"Today's menu - {today_name}")
    items_by_meal = {row["meal_type"]: row["items"]
                     for row in fetch_all("SELECT meal_type, items FROM menu WHERE day = ?", (today_name,))}
    show_table([{"Meal": meal, "Items": items_by_meal.get(meal, "-"), "Timing": get_setting(f"time_{meal}")}
                for meal in MEAL_TYPES])


def render_menu_and_timetable():
    st.subheader("Weekly menu")
    grid = {day: {meal: "-" for meal in MEAL_TYPES} for day in DAYS}
    for row in fetch_all("SELECT day, meal_type, items FROM menu"):
        if row["day"] in grid and row["meal_type"] in MEAL_TYPES:
            grid[row["day"]][row["meal_type"]] = row["items"]
    st.dataframe(pd.DataFrame.from_dict(grid, orient="index"))
    st.subheader("Mess timetable")
    timetable = [{"Meal": meal, "Timing": get_setting(f"time_{meal}")} for meal in MEAL_TYPES]
    st.dataframe(pd.DataFrame(timetable), hide_index=True)


def student_home_tab(user):
    month_prefix = f"{date.today():%Y-%m}%"
    verified = count_rows("SELECT COUNT(*) FROM meal_record WHERE student_id = ? AND verified = 1 AND date LIKE ?",
                          (user["user_id"], month_prefix))
    waiting = count_rows("SELECT COUNT(*) FROM meal_record WHERE student_id = ? AND verified = 0 AND date LIKE ?",
                         (user["user_id"], month_prefix))
    due = fetch_one("SELECT COALESCE(SUM(total_amount), 0) FROM bill WHERE student_id = ? AND status = 'Unpaid'",
                    (user["user_id"],))[0]
    render_metrics([("Verified meals this month", verified), ("Awaiting verification", waiting),
                    ("Amount due", f"₹{due:.2f}")])
    render_today_menu()


def student_attendance_tab(user):
    today = date.today().isoformat()
    st.subheader("Mark today's attendance")
    with st.form("attendance_form"):
        meal = st.selectbox("Meal", MEAL_TYPES, key="attendance_meal")
        submitted = st.form_submit_button("Mark present")
    if submitted:
        already = fetch_one(
            "SELECT 1 FROM meal_record WHERE student_id = ? AND date = ? AND meal_type = ?",
            (user["user_id"], today, meal),
        )
        if is_on_leave(user["user_id"], today):
            st.warning("You have approved leave today, so attendance cannot be marked.")
        elif already:
            st.warning(f"You have already marked {meal} for today.")
        else:
            save([("INSERT INTO meal_record (student_id, date, meal_type, status) VALUES (?, ?, ?, 'Present')",
                   (user["user_id"], today, meal))],
                 f"{meal} attendance marked. It now waits for staff verification.",
                 "Attendance for this meal is already recorded.")
    st.subheader("My recent attendance")
    rows = fetch_all(
        "SELECT date AS Date, meal_type AS Meal, status AS Status, "
        "CASE WHEN verified = 1 THEN 'Yes' ELSE 'No' END AS Verified "
        "FROM meal_record WHERE student_id = ? ORDER BY date DESC, record_id DESC LIMIT 30",
        (user["user_id"],),
    )
    show_table(rows, "No attendance marked yet.")


def student_billing_tab(user):
    month = date.today().strftime("%Y-%m")
    st.subheader("Mess charges")
    st.caption(f"Rate: ₹{get_meal_rate():.2f} per verified meal. Current month: {month}")
    with st.form("generate_bill_form"):
        st.write("Create or refresh this month's bill from your verified meals.")
        generate = st.form_submit_button("Generate my bill")
    if generate:
        save(build_bill_statements(user["user_id"], month), f"Your bill for {month} is up to date.")

    bills = fetch_all("SELECT bill_id, month, total_amount, status FROM bill WHERE student_id = ? "
                      "ORDER BY month DESC", (user["user_id"],))
    show_table([{"Bill": b["bill_id"], "Month": b["month"], "Amount": b["total_amount"], "Status": b["status"]}
                for b in bills], "No bills yet. Generate one after your meals are verified.")

    st.subheader("Pay a bill")
    unpaid = [b for b in bills if b["status"] == "Unpaid" and b["total_amount"] > 0]
    bill = pick_row("Unpaid bill", unpaid, "bill_id",
                    lambda b: f"{b['month']} - ₹{b['total_amount']:.2f}", "pay_bill_pick",
                    "No payable bills right now.")
    if bill is not None:
        with st.form("payment_form"):
            method = st.selectbox("Payment method (demo gateway)", PAYMENT_METHODS, key="pay_method")
            pay = st.form_submit_button("Pay now")
        if pay:
            transaction_id = f"TXN{datetime.now():%Y%m%d%H%M%S}{os.urandom(3).hex().upper()}"
            paid_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save([
                ("INSERT INTO payment (bill_id, student_id, amount, payment_date, transaction_id, status) "
                 "VALUES (?, ?, ?, ?, ?, 'Success')",
                 (bill["bill_id"], user["user_id"], bill["total_amount"], paid_at, transaction_id)),
                ("UPDATE bill SET status = 'Paid' WHERE bill_id = ?", (bill["bill_id"],)),
            ], f"Payment of ₹{bill['total_amount']:.2f} via {method} successful. Transaction ID: {transaction_id}")

    st.subheader("Payment history")
    # "Transaction" is a reserved word in SQLite, so the alias is Txn_ID.
    show_table(fetch_all(
        "SELECT p.payment_date AS Date, b.month AS Month, p.amount AS Amount, "
        "p.transaction_id AS Txn_ID, p.status AS Status "
        "FROM payment p JOIN bill b ON b.bill_id = p.bill_id "
        "WHERE p.student_id = ? ORDER BY p.payment_id DESC", (user["user_id"],)), "No payments yet.")


def student_leave_tab(user):
    st.subheader("Request meal leave")
    st.caption("While a leave is approved, attendance cannot be marked for those dates.")
    with st.form("leave_form", clear_on_submit=True):
        start = st.date_input("From", value=date.today(), key="leave_start")
        end = st.date_input("To", value=date.today(), key="leave_end")
        reason = st.text_input("Reason", key="leave_reason")
        submitted = st.form_submit_button("Submit request")
    if submitted:
        if end < start:
            st.error("The end date cannot be before the start date.")
        elif not reason.strip():
            st.error("Please give a short reason.")
        else:
            save([("INSERT INTO leave_request (student_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)",
                   (user["user_id"], start.isoformat(), end.isoformat(), reason.strip()))],
                 "Leave request sent to the warden.")
    show_table(fetch_all(
        "SELECT leave_id AS ID, start_date AS From_date, end_date AS To_date, reason AS Reason, status AS Status "
        "FROM leave_request WHERE student_id = ? ORDER BY leave_id DESC", (user["user_id"],)),
        "You have not requested any leave.")


def student_complaints_tab(user):
    today = date.today().isoformat()
    st.subheader("Register a complaint")
    with st.form("complaint_form", clear_on_submit=True):
        description = st.text_area("Describe the problem", key="complaint_text")
        submitted = st.form_submit_button("Submit complaint")
    if submitted:
        if not description.strip():
            st.error("Please describe your complaint before submitting.")
        else:
            save([("INSERT INTO complaint (student_id, description, date, status) VALUES (?, ?, ?, 'Pending')",
                   (user["user_id"], description.strip(), today))], "Complaint registered.")
    show_table(fetch_all(
        "SELECT complaint_id AS ID, date AS Date, description AS Complaint, status AS Status "
        "FROM complaint WHERE student_id = ? ORDER BY complaint_id DESC", (user["user_id"],)),
        "You have not registered any complaints.")

    st.subheader("Give feedback")
    with st.form("feedback_form", clear_on_submit=True):
        rating = st.slider("Rating", 1, 5, 4, key="feedback_rating")
        message = st.text_area("Your feedback", key="feedback_text")
        sent = st.form_submit_button("Send feedback")
    if sent:
        if not message.strip():
            st.error("Please write a short message.")
        else:
            save([("INSERT INTO feedback (student_id, message, rating, date) VALUES (?, ?, ?, ?)",
                   (user["user_id"], message.strip(), rating, today))], "Thank you for your feedback!")


def student_page(user):
    tabs = st.tabs(["Home", "Menu & Timetable", "Attendance", "Billing", "Leave", "Complaints & Feedback"])
    with tabs[0]:
        student_home_tab(user)
    with tabs[1]:
        render_menu_and_timetable()
    with tabs[2]:
        student_attendance_tab(user)
    with tabs[3]:
        student_billing_tab(user)
    with tabs[4]:
        student_leave_tab(user)
    with tabs[5]:
        student_complaints_tab(user)


# ----------------------------------------------------------- mess staff page
def staff_menu_tab():
    st.subheader("Update menu")
    with st.form("menu_form"):
        day = st.selectbox("Day", DAYS, key="menu_day")
        meal = st.selectbox("Meal", MEAL_TYPES, key="menu_meal")
        items = st.text_input("Items (comma separated)", key="menu_items")
        submitted = st.form_submit_button("Save menu")
    if submitted:
        if not items.strip():
            st.error("Please enter at least one item.")
        else:
            # Delete-then-insert keeps exactly one row per day and meal.
            save([("DELETE FROM menu WHERE day = ? AND meal_type = ?", (day, meal)),
                  ("INSERT INTO menu (day, meal_type, items, menu_date) VALUES (?, ?, ?, ?)",
                   (day, meal, items.strip(), date.today().isoformat()))],
                 f"{meal} menu for {day} saved.")

    st.subheader("Update timetable")
    with st.form("timetable_form"):
        timings = {meal: st.text_input(f"{meal} timing", value=get_setting(f"time_{meal}"), key=f"timing_{meal}")
                   for meal in MEAL_TYPES}
        saved = st.form_submit_button("Save timetable")
    if saved:
        if not all(value.strip() for value in timings.values()):
            st.error("Every meal needs a timing.")
        else:
            save([setting_statement(f"time_{meal}", value.strip()) for meal, value in timings.items()],
                 "Timetable updated.")
    render_menu_and_timetable()


def staff_verify_tab():
    st.subheader("Verify student attendance")
    chosen = st.date_input("Attendance date", value=date.today(), key="verify_date")
    pending = fetch_all(
        "SELECT m.record_id, m.meal_type, u.full_name, u.room_no FROM meal_record m "
        "JOIN users u ON u.user_id = m.student_id "
        "WHERE m.date = ? AND m.verified = 0 AND m.status = 'Present' ORDER BY m.meal_type, u.full_name",
        (chosen.isoformat(),),
    )
    if not pending:
        st.info("No attendance waiting for verification on this date.")
        return
    labels = {row["record_id"]: f"{row['full_name']} ({row['room_no'] or 'no room'}) - {row['meal_type']}"
              for row in pending}
    st.write(f"{len(pending)} record(s) pending.")
    with st.form("verify_form"):
        picked = st.multiselect("Select records to verify", list(labels), format_func=labels.get,
                                key=f"verify_pick_{chosen.isoformat()}")
        verify_selected = st.form_submit_button("Verify selected")
        verify_all = st.form_submit_button("Verify all pending")
    if verify_selected or verify_all:
        record_ids = list(labels) if verify_all else picked
        if not record_ids:
            st.warning("Select at least one record, or use 'Verify all pending'.")
        else:
            save([("UPDATE meal_record SET verified = 1 WHERE record_id = ?", (record_id,))
                  for record_id in record_ids], f"Verified {len(record_ids)} record(s).")


def inventory_add_form():
    with st.form("add_item_form", clear_on_submit=True):
        name = st.text_input("Item name", key="add_item_name")
        quantity = st.number_input("Quantity", min_value=0.0, value=0.0, step=1.0, key="add_item_qty")
        unit = st.text_input("Unit (kg, litre, pcs)", value="kg", key="add_item_unit")
        price = st.number_input("Price per unit", min_value=0.0, value=0.0, step=1.0, key="add_item_price")
        min_level = st.number_input("Low-stock level", min_value=0.0, value=5.0, step=1.0, key="add_item_min")
        submitted = st.form_submit_button("Add item")
    if submitted:
        if not name.strip() or not unit.strip():
            st.error("Item name and unit are required.")
        else:
            save([("INSERT INTO inventory (item_name, quantity, unit, price, min_level) VALUES (?, ?, ?, ?, ?)",
                   (name.strip(), quantity, unit.strip(), price, min_level))],
                 f"Added {name.strip()} to inventory.", "An item with this name already exists.")


def inventory_adjust_form(items):
    item = pick_row("Item", items, "item_id",
                    lambda i: f"{i['item_name']} ({i['quantity']:g} {i['unit']})", "adjust_item_pick",
                    "Add an item first.")
    if item is None:
        return
    with st.form("adjust_stock_form"):
        action = st.radio("Action", ["Add stock", "Use stock"], horizontal=True, key="adjust_action")
        amount = st.number_input("Amount", min_value=0.0, value=0.0, step=1.0, key="adjust_amount")
        submitted = st.form_submit_button("Apply")
    if submitted:
        change = amount if action == "Add stock" else -amount
        if amount <= 0:
            st.error("Enter an amount greater than zero.")
        elif item["quantity"] + change < 0:
            st.error(f"Not enough stock. Only {item['quantity']:g} {item['unit']} available.")
        else:
            save([("UPDATE inventory SET quantity = quantity + ? WHERE item_id = ?",
                   (change, item["item_id"]))], f"Stock of {item['item_name']} updated.")


def inventory_edit_form(items):
    item = pick_row("Item", items, "item_id", lambda i: i["item_name"], "edit_item_pick", "Add an item first.")
    if item is None:
        return
    item_id = item["item_id"]
    with st.form(f"edit_item_form_{item_id}"):
        name = st.text_input("Item name", value=item["item_name"], key=f"edit_item_name_{item_id}")
        unit = st.text_input("Unit", value=item["unit"] or "", key=f"edit_item_unit_{item_id}")
        price = st.number_input("Price per unit", min_value=0.0, value=float(item["price"]), step=1.0,
                                key=f"edit_item_price_{item_id}")
        min_level = st.number_input("Low-stock level", min_value=0.0, value=float(item["min_level"]), step=1.0,
                                    key=f"edit_item_min_{item_id}")
        save_clicked = st.form_submit_button("Save changes")
        remove_clicked = st.form_submit_button("Remove item")
    if save_clicked:
        if not name.strip() or not unit.strip():
            st.error("Item name and unit are required.")
        else:
            save([("UPDATE inventory SET item_name = ?, unit = ?, price = ?, min_level = ? WHERE item_id = ?",
                   (name.strip(), unit.strip(), price, min_level, item_id))],
                 "Item updated.", "Another item already uses this name.")
    if remove_clicked:
        save([("DELETE FROM stock_request WHERE item_id = ?", (item_id,)),
              ("DELETE FROM inventory WHERE item_id = ?", (item_id,))],
             f"Removed {item['item_name']}.")


def inventory_request_form(user, items):
    item = pick_row("Item to request", items, "item_id", lambda i: i["item_name"], "request_item_pick",
                    "Add an item first.")
    if item is None:
        return
    with st.form("stock_request_form"):
        quantity = st.number_input("Quantity needed", min_value=0.0, value=0.0, step=1.0, key="request_qty")
        submitted = st.form_submit_button("Request stock")
    if submitted:
        if quantity <= 0:
            st.error("Enter a quantity greater than zero.")
        else:
            save([("INSERT INTO stock_request (staff_id, item_id, request_date, requested_quantity) "
                   "VALUES (?, ?, ?, ?)", (user["user_id"], item["item_id"], date.today().isoformat(), quantity))],
                 "Stock request recorded.")
    show_table(fetch_all(
        "SELECT r.request_id AS ID, r.request_date AS Date, i.item_name AS Item, "
        "r.requested_quantity AS Quantity, u.full_name AS Requested_by "
        "FROM stock_request r JOIN inventory i ON i.item_id = r.item_id "
        "JOIN users u ON u.user_id = r.staff_id ORDER BY r.request_id DESC LIMIT 20"), "No stock requests yet.")


def staff_inventory_tab(user):
    items = fetch_all("SELECT * FROM inventory ORDER BY item_name")
    low_items = [item["item_name"] for item in items if item["quantity"] <= item["min_level"]]
    if low_items:
        st.warning("Low stock: " + ", ".join(low_items))
    show_table(items, "The inventory is empty. Add your first item below.")
    tabs = st.tabs(["Add item", "Adjust stock", "Edit / remove", "Stock request"])
    with tabs[0]:
        inventory_add_form()
    with tabs[1]:
        inventory_adjust_form(items)
    with tabs[2]:
        inventory_edit_form(items)
    with tabs[3]:
        inventory_request_form(user, items)


def staff_reports_tab():
    reports_section("staff")
    st.subheader("Refresh all student bills")
    with st.form("bulk_bill_form"):
        month = st.text_input("Month (YYYY-MM)", value=date.today().strftime("%Y-%m"), key="bulk_bill_month")
        submitted = st.form_submit_button("Generate bills for all students")
    if submitted:
        if not valid_month(month.strip()):
            st.error("Please use the format YYYY-MM.")
            return
        students = fetch_all("SELECT user_id FROM users WHERE role = 'Student' AND active = 1")
        statements = [stmt for student in students
                      for stmt in build_bill_statements(student["user_id"], month.strip())]
        save(statements, f"Bills for {month.strip()} generated for {len(students)} student(s).")


def staff_page(user):
    tabs = st.tabs(["Menu & Timetable", "Verify Attendance", "Inventory", "Reports"])
    with tabs[0]:
        staff_menu_tab()
    with tabs[1]:
        staff_verify_tab()
    with tabs[2]:
        staff_inventory_tab(user)
    with tabs[3]:
        staff_reports_tab()


# --------------------------------------------------------------- warden page
def warden_dashboard_tab():
    today = date.today().isoformat()
    render_metrics([
        ("Students", count_rows("SELECT COUNT(*) FROM users WHERE role = 'Student' AND active = 1")),
        ("Today's attendance", count_rows("SELECT COUNT(*) FROM meal_record WHERE date = ?", (today,))),
        ("Pending complaints", count_rows("SELECT COUNT(*) FROM complaint WHERE status = 'Pending'")),
        ("Pending leave", count_rows("SELECT COUNT(*) FROM leave_request WHERE status = 'Pending'")),
        ("Unpaid bills", count_rows("SELECT COUNT(*) FROM bill WHERE status = 'Unpaid'")),
    ])
    st.subheader("Today's attendance by meal")
    show_table(fetch_all("SELECT meal_type AS Meal, COUNT(*) AS Marked, SUM(verified) AS Verified "
                         "FROM meal_record WHERE date = ? GROUP BY meal_type", (today,)),
               "No attendance marked today.")
    week_start = (date.today() - timedelta(days=6)).isoformat()
    left, right = st.columns(2)
    with left:
        render_bar_chart("Meals marked - last 7 days",
                         fetch_all("SELECT date AS Day, COUNT(*) AS Meals FROM meal_record "
                                   "WHERE date >= ? GROUP BY date ORDER BY date", (week_start,)),
                         "Day", "No attendance in the last 7 days.")
    with right:
        render_bar_chart("Complaints by status",
                         fetch_all("SELECT status AS Status, COUNT(*) AS Total FROM complaint GROUP BY status"),
                         "Status", "No complaints yet.")


def warden_complaints_tab():
    status_filter = st.selectbox("Show", ["All"] + COMPLAINT_STATUSES, key="complaint_filter")
    rows = [row for row in fetch_all(
        "SELECT c.complaint_id, c.date, u.full_name, u.room_no, c.description, c.status "
        "FROM complaint c JOIN users u ON u.user_id = c.student_id "
        "ORDER BY CASE c.status WHEN 'Pending' THEN 0 WHEN 'In Progress' THEN 1 ELSE 2 END, c.complaint_id DESC")
        if status_filter == "All" or row["status"] == status_filter]
    show_table(rows, "No complaints match this filter.")
    complaint = pick_row("Complaint to update", rows, "complaint_id",
                         lambda c: f"#{c['complaint_id']} {c['full_name']} - {c['description'][:40]} [{c['status']}]",
                         "complaint_pick", "Nothing to review right now.")
    if complaint is None:
        return
    complaint_id = complaint["complaint_id"]
    with st.form(f"complaint_status_form_{complaint_id}"):
        new_status = st.selectbox("New status", COMPLAINT_STATUSES,
                                  index=COMPLAINT_STATUSES.index(complaint["status"]),
                                  key=f"complaint_status_{complaint_id}")
        submitted = st.form_submit_button("Update status")
    if submitted:
        save([("UPDATE complaint SET status = ? WHERE complaint_id = ?", (new_status, complaint_id))],
             f"Complaint #{complaint_id} marked {new_status}.")


def warden_leave_tab():
    rows = fetch_all(
        "SELECT l.leave_id, u.full_name, u.room_no, l.start_date, l.end_date, l.reason, l.status "
        "FROM leave_request l JOIN users u ON u.user_id = l.student_id "
        "ORDER BY CASE l.status WHEN 'Pending' THEN 0 ELSE 1 END, l.leave_id DESC")
    show_table(rows, "No leave requests yet.")
    leave = pick_row("Request to decide", rows, "leave_id",
                     lambda item: f"#{item['leave_id']} {item['full_name']}, {item['start_date']} to "
                                  f"{item['end_date']} [{item['status']}]",
                     "leave_pick", "Nothing to review right now.")
    if leave is None:
        return
    leave_id = leave["leave_id"]
    with st.form(f"leave_status_form_{leave_id}"):
        decision = st.selectbox("Decision", LEAVE_STATUSES, index=LEAVE_STATUSES.index(leave["status"]),
                                key=f"leave_decision_{leave_id}")
        submitted = st.form_submit_button("Save decision")
    if submitted:
        save([("UPDATE leave_request SET status = ? WHERE leave_id = ?", (decision, leave_id))],
             f"Leave request #{leave_id} marked {decision}.")


def warden_reports_tab():
    reports_section("warden")
    st.subheader("Student feedback")
    average = fetch_one("SELECT AVG(rating) FROM feedback")[0]
    st.metric("Average rating", f"{average:.1f} / 5" if average is not None else "No ratings yet")
    show_table(fetch_all(
        "SELECT f.date AS Date, u.full_name AS Student, f.rating AS Rating, f.message AS Message "
        "FROM feedback f JOIN users u ON u.user_id = f.student_id ORDER BY f.feedback_id DESC"),
        "No feedback received yet.")


def warden_page(user):
    st.caption(f"Welcome, {user['full_name']}.")
    tabs = st.tabs(["Dashboard", "Complaints", "Leave Requests", "Reports & Feedback"])
    with tabs[0]:
        warden_dashboard_tab()
    with tabs[1]:
        warden_complaints_tab()
    with tabs[2]:
        warden_leave_tab()
    with tabs[3]:
        warden_reports_tab()


# ---------------------------------------------------------------- admin page
def admin_add_user_form():
    with st.form("add_user_form", clear_on_submit=True):
        username = st.text_input("Username", key="new_username")
        full_name = st.text_input("Full name", key="new_full_name")
        email = st.text_input("Email", key="new_email")
        phone = st.text_input("Phone", key="new_phone")
        role = st.selectbox("Role", ROLES, key="new_role")
        room_no = st.text_input("Room number (students)", key="new_room")
        password = st.text_input("Initial password", type="password", key="new_password")
        submitted = st.form_submit_button("Create user")
    if submitted:
        username = username.strip()
        if not username or not full_name.strip() or len(password) < 6:
            st.error("Username, full name and a password of at least 6 characters are required.")
        elif fetch_one("SELECT 1 FROM users WHERE username = ?", (username,)):
            st.error("That username is already taken.")
        else:
            password_hash, salt = hash_password(password)
            save([("INSERT INTO users (username, password_hash, salt, full_name, email, phone, role, room_no) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (username, password_hash, salt, full_name.strip(), email.strip(), phone.strip(), role,
                    room_no.strip()))], f"User {username} created.", "That username is already taken.")


def admin_edit_user_form(target, admin):
    user_id = target["user_id"]
    with st.form(f"edit_user_form_{user_id}"):
        full_name = st.text_input("Full name", value=target["full_name"], key=f"edit_user_name_{user_id}")
        email = st.text_input("Email", value=target["email"] or "", key=f"edit_user_email_{user_id}")
        phone = st.text_input("Phone", value=target["phone"] or "", key=f"edit_user_phone_{user_id}")
        role = st.selectbox("Role", ROLES, index=ROLES.index(target["role"]), key=f"edit_user_role_{user_id}")
        room_no = st.text_input("Room number", value=target["room_no"] or "", key=f"edit_user_room_{user_id}")
        submitted = st.form_submit_button("Save changes")
    if submitted:
        if not full_name.strip():
            st.error("Full name cannot be empty.")
        elif user_id == admin["user_id"] and role != "Admin":
            st.error("You cannot remove your own admin role.")
        else:
            if user_id == admin["user_id"]:
                admin["full_name"] = full_name.strip()  # keep the sidebar greeting current
            save([("UPDATE users SET full_name = ?, email = ?, phone = ?, role = ?, room_no = ? "
                   "WHERE user_id = ?", (full_name.strip(), email.strip(), phone.strip(), role,
                                         room_no.strip(), user_id))], "User details updated.")


def admin_password_form(target):
    user_id = target["user_id"]
    with st.form(f"reset_password_form_{user_id}"):
        password = st.text_input("New password", type="password", key=f"reset_password_{user_id}")
        submitted = st.form_submit_button("Reset password")
    if submitted:
        if len(password) < 6:
            st.error("The password must be at least 6 characters long.")
        else:
            password_hash, salt = hash_password(password)
            save([("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?",
                   (password_hash, salt, user_id))], f"Password reset for {target['username']}.")


def admin_status_form(target, admin):
    user_id = target["user_id"]
    make_active = not target["active"]
    with st.form(f"status_form_{user_id}"):
        st.write(f"{target['username']} is currently {'active' if target['active'] else 'deactivated'}.")
        submitted = st.form_submit_button("Activate user" if make_active else "Deactivate user")
    if submitted:
        if user_id == admin["user_id"]:
            st.error("You cannot deactivate your own account.")
        else:
            save([("UPDATE users SET active = ? WHERE user_id = ?", (int(make_active), user_id))],
                 f"{target['username']} is now {'active' if make_active else 'deactivated'}.")


def admin_delete_form(target, admin):
    user_id = target["user_id"]
    with st.form(f"delete_form_{user_id}"):
        confirmed = st.checkbox(f"I understand that deleting {target['username']} cannot be undone.",
                                key=f"delete_confirm_{user_id}")
        submitted = st.form_submit_button("Delete user")
    if submitted:
        if user_id == admin["user_id"]:
            st.error("You cannot delete your own account.")
        elif not confirmed:
            st.warning("Tick the confirmation box first.")
        else:
            save([("DELETE FROM users WHERE user_id = ?", (user_id,))], f"User {target['username']} deleted.",
                 "This user has attendance, billing or other records. Deactivate the account instead.")


def admin_users_tab(admin):
    search_col, role_col = st.columns([2, 1])
    search = search_col.text_input("Search by name or username", key="admin_user_search").strip().lower()
    role_filter = role_col.selectbox("Role", ["All"] + ROLES, key="admin_role_filter")
    users = [u for u in fetch_all("SELECT user_id, username, full_name, email, phone, role, room_no, active "
                                  "FROM users ORDER BY role, username")
             if (role_filter == "All" or u["role"] == role_filter)
             and search in f"{u['username']} {u['full_name']}".lower()]
    show_table([{"ID": u["user_id"], "Username": u["username"], "Name": u["full_name"], "Email": u["email"],
                 "Phone": u["phone"], "Role": u["role"], "Room": u["room_no"],
                 "Active": "Yes" if u["active"] else "No"} for u in users], "No users match your search.")
    target = pick_row("Select a user to edit, reset, deactivate or delete", users, "user_id",
                      lambda u: f"{u['username']} - {u['full_name']} ({u['role']})", "admin_user_pick")
    tabs = st.tabs(["Add user", "Edit", "Reset password", "Activate / deactivate", "Delete"])
    with tabs[0]:
        admin_add_user_form()
    if target is None:
        return
    with tabs[1]:
        admin_edit_user_form(target, admin)
    with tabs[2]:
        admin_password_form(target)
    with tabs[3]:
        admin_status_form(target, admin)
    with tabs[4]:
        admin_delete_form(target, admin)


def admin_settings_tab():
    st.subheader("Mess charge rate")
    with st.form("settings_form"):
        rate = st.number_input("Charge per verified meal (₹)", min_value=0.0, value=get_meal_rate(),
                               step=1.0, key="setting_meal_rate")
        submitted = st.form_submit_button("Save settings")
    if submitted:
        save([setting_statement("meal_rate", rate)], "Meal rate updated. It applies the next time bills are generated.")


def admin_backup_tab():
    st.subheader("Database backup")
    with st.form("backup_form"):
        st.write("Create a timestamped copy of the database.")
        create = st.form_submit_button("Create backup")
    if create:
        try:
            st.session_state["last_backup"] = create_backup()
            st.success("Backup created. Download it below.")
        except (sqlite3.Error, OSError) as err:
            st.error(f"Backup failed: {err}")
    backup_path = st.session_state.get("last_backup")
    if backup_path and os.path.exists(backup_path):
        with open(backup_path, "rb") as backup_file:
            backup_bytes = backup_file.read()
        st.download_button(f"Download {backup_path}", backup_bytes, file_name=backup_path,
                           mime="application/octet-stream", key="download_backup")


def admin_page(user):
    tabs = st.tabs(["Users", "Settings", "Backup"])
    with tabs[0]:
        admin_users_tab(user)
    with tabs[1]:
        admin_settings_tab()
    with tabs[2]:
        admin_backup_tab()


# ---------------------------------------------------------------------- main
def change_password_form(user):
    """Let any logged-in user change their own password from the sidebar."""
    with st.sidebar.expander("Change password"):
        with st.form("change_password_form", clear_on_submit=True):
            current = st.text_input("Current password", type="password", key="cp_current")
            new_password = st.text_input("New password", type="password", key="cp_new")
            confirm = st.text_input("Confirm new password", type="password", key="cp_confirm")
            submitted = st.form_submit_button("Update password")
        if submitted:
            row = fetch_one("SELECT password_hash, salt FROM users WHERE user_id = ?", (user["user_id"],))
            if not verify_password(current, row["password_hash"], row["salt"]):
                st.error("Current password is incorrect.")
            elif len(new_password) < 6:
                st.error("The new password must be at least 6 characters long.")
            elif new_password != confirm:
                st.error("The two new passwords do not match.")
            else:
                password_hash, salt = hash_password(new_password)
                save([("UPDATE users SET password_hash = ?, salt = ? WHERE user_id = ?",
                       (password_hash, salt, user["user_id"]))], "Your password was changed.")


def render_sidebar(user):
    st.sidebar.markdown(f"Logged in as **{user['full_name']}** ({user['role']})")
    change_password_form(user)
    if st.sidebar.button("Logout", key="logout_button"):
        st.session_state.clear()
        st.rerun()


def main():
    setup_database()
    inject_css()
    user = st.session_state.get("user")
    if user is None:
        login_page()
        return
    pages = {"Student": student_page, "Mess Staff": staff_page, "Warden": warden_page, "Admin": admin_page}
    render_sidebar(user)
    st.header(f"{user['role']} Dashboard")
    show_flash()
    pages[user["role"]](user)


if __name__ == "__main__":
    main()
