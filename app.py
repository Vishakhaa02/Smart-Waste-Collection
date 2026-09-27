import os
import csv
import io
import math
import sqlite3
import string
import random
from datetime import datetime, date
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g, Response
)

APP_SECRET = os.environ.get("SECRET_KEY", "dev-secret-change-me")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data", "waste.db"))
PAGE_SIZE = 12

app = Flask(__name__)
app.secret_key = APP_SECRET

CATEGORIES = {
    "organic": {
        "label": "Organic / Biodegradable",
        "icon": "🍂",
        "guide": "Food scraps, garden waste, and other compostable material. Keep it separate from plastics and liquids so it can be composted.",
    },
    "recyclable": {
        "label": "Recyclable (Paper, Plastic, Glass, Metal)",
        "icon": "♻️",
        "guide": "Clean and dry paper, cardboard, plastic bottles, glass and metal containers. Rinse containers before placing them out.",
    },
    "e-waste": {
        "label": "E-Waste (Electronics & Batteries)",
        "icon": "🔌",
        "guide": "Old phones, cables, appliances, batteries and other electronics. Never mix with regular household waste.",
    },
    "hazardous": {
        "label": "Hazardous (Chemicals, Paint, Medical)",
        "icon": "☣️",
        "guide": "Paints, solvents, pesticides, expired medicines. Keep sealed in original containers and clearly labelled.",
    },
    "bulky": {
        "label": "Bulky Waste (Furniture, Appliances)",
        "icon": "🛋️",
        "guide": "Furniture, mattresses, large appliances. Please confirm the item can be carried through a standard doorway.",
    },
    "general": {
        "label": "General Waste",
        "icon": "🗑️",
        "guide": "Non-recyclable household waste that does not fit the other categories.",
    },
}

STATUS_FLOW = ["Pending", "Scheduled", "Collected", "Cancelled"]

FAQS = [
    ("How do I know which category my waste belongs to?",
     "Check the category guide on the home page — each category lists common examples. "
     "If you're still unsure, choose the closest match and add details in the notes field; "
     "the collection team will confirm with you if needed."),
    ("How long does it take for a pickup to be scheduled?",
     "Most requests are reviewed and scheduled within 1–2 working days. You can check the "
     "current status any time using your tracking code."),
    ("I lost my tracking code — can I still find my request?",
     "Yes. Use the 'My requests' page and search with the phone number you submitted the "
     "request with; it will list every request tied to that number."),
    ("Can I cancel or change a request after submitting it?",
     "Contact the collection team with your tracking code and they can update or cancel the "
     "request from the admin dashboard."),
    ("What happens after my waste is collected?",
     "The request is marked 'Collected' and you'll be able to leave a quick rating and "
     "comment on the tracking page — this helps the team improve the service."),
    ("Is there a cost for requesting a pickup?",
     "This platform only handles the request and scheduling workflow. Any service charges "
     "depend on your local collection provider's own policy."),
]


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracking_code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            category TEXT NOT NULL,
            address TEXT NOT NULL,
            landmark TEXT,
            preferred_date TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            changed_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER UNIQUE NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (request_id) REFERENCES requests (id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def generate_tracking_code():
    chars = string.ascii_uppercase + string.digits
    return "WC-" + "".join(random.choices(chars, k=6))


def log_status(db, request_id, status, note=None):
    db.execute(
        "INSERT INTO status_history (request_id, status, note, changed_at) VALUES (?, ?, ?, ?)",
        (request_id, status, note, datetime.now().isoformat(timespec="seconds")),
    )


# ---------------------------------------------------------------- helpers
def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_globals():
    db = get_db()
    active_announcements = db.execute(
        "SELECT * FROM announcements WHERE active = 1 ORDER BY created_at DESC"
    ).fetchall()
    return {
        "categories": CATEGORIES,
        "current_year": datetime.now().year,
        "active_announcements": active_announcements,
    }


def get_stats(db):
    stats = {
        "total": db.execute("SELECT COUNT(*) c FROM requests").fetchone()["c"],
        "pending": db.execute("SELECT COUNT(*) c FROM requests WHERE status='Pending'").fetchone()["c"],
        "scheduled": db.execute("SELECT COUNT(*) c FROM requests WHERE status='Scheduled'").fetchone()["c"],
        "collected": db.execute("SELECT COUNT(*) c FROM requests WHERE status='Collected'").fetchone()["c"],
        "cancelled": db.execute("SELECT COUNT(*) c FROM requests WHERE status='Cancelled'").fetchone()["c"],
    }
    return stats


# ---------------------------------------------------------------- public routes
@app.route("/")
def landing():
    db = get_db()
    stats = get_stats(db)
    avg_rating_row = db.execute("SELECT AVG(rating) a, COUNT(*) c FROM feedback").fetchone()
    avg_rating = round(avg_rating_row["a"], 1) if avg_rating_row["a"] else None
    recent_feedback = db.execute(
        """SELECT f.rating, f.comment, r.category, f.created_at FROM feedback f
           JOIN requests r ON r.id = f.request_id
           WHERE f.comment IS NOT NULL AND f.comment != ''
           ORDER BY f.created_at DESC LIMIT 3"""
    ).fetchall()
    return render_template(
        "landing.html",
        stats=stats,
        avg_rating=avg_rating,
        rating_count=avg_rating_row["c"],
        recent_feedback=recent_feedback,
    )


@app.route("/request", methods=["GET"])
def request_form():
    return render_template("request_form.html", today=date.today().isoformat())


@app.route("/submit", methods=["POST"])
def submit_request():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    category = request.form.get("category", "")
    address = request.form.get("address", "").strip()
    landmark = request.form.get("landmark", "").strip()
    preferred_date = request.form.get("preferred_date", "")
    notes = request.form.get("notes", "").strip()

    errors = []
    if not name:
        errors.append("Please enter your name.")
    if not phone:
        errors.append("Please enter a contact phone number.")
    if category not in CATEGORIES:
        errors.append("Please select a valid waste category.")
    if not address:
        errors.append("Please enter a pickup address.")
    if not preferred_date:
        errors.append("Please choose a preferred pickup date.")

    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("request_form"))

    db = get_db()
    code = generate_tracking_code()
    while db.execute("SELECT 1 FROM requests WHERE tracking_code = ?", (code,)).fetchone():
        code = generate_tracking_code()

    now = datetime.now().isoformat(timespec="seconds")
    cur = db.execute(
        """INSERT INTO requests
           (tracking_code, name, phone, category, address, landmark, preferred_date, notes, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)""",
        (code, name, phone, category, address, landmark, preferred_date, notes, now, now),
    )
    log_status(db, cur.lastrowid, "Pending", "Request submitted")
    db.commit()
    return redirect(url_for("confirmation", code=code))


@app.route("/confirmation/<code>")
def confirmation(code):
    return render_template("confirmation.html", code=code)


@app.route("/track", methods=["GET", "POST"])
def track():
    result = None
    history = []
    existing_feedback = None
    searched = False

    code = ""
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()
        searched = True
    elif request.args.get("code"):
        code = request.args.get("code", "").strip().upper()
        searched = True

    if code:
        db = get_db()
        result = db.execute(
            "SELECT * FROM requests WHERE tracking_code = ?", (code,)
        ).fetchone()
        if result:
            history = db.execute(
                "SELECT * FROM status_history WHERE request_id = ? ORDER BY changed_at ASC",
                (result["id"],),
            ).fetchall()
            existing_feedback = db.execute(
                "SELECT * FROM feedback WHERE request_id = ?", (result["id"],)
            ).fetchone()

    return render_template(
        "track.html", result=result, searched=searched, code=code,
        history=history, existing_feedback=existing_feedback,
    )


@app.route("/feedback/<code>", methods=["POST"])
def submit_feedback(code):
    code = code.strip().upper()
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE tracking_code = ?", (code,)).fetchone()
    if not req or req["status"] != "Collected":
        flash("Feedback can only be left once a request is collected.", "error")
        return redirect(url_for("track", code=code))

    already = db.execute("SELECT 1 FROM feedback WHERE request_id = ?", (req["id"],)).fetchone()
    if already:
        flash("You've already left feedback for this request.", "error")
        return redirect(url_for("track", code=code))

    try:
        rating = int(request.form.get("rating", 0))
    except ValueError:
        rating = 0
    comment = request.form.get("comment", "").strip()

    if rating < 1 or rating > 5:
        flash("Please choose a rating between 1 and 5.", "error")
        return redirect(url_for("track", code=code))

    db.execute(
        "INSERT INTO feedback (request_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
        (req["id"], rating, comment, datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    flash("Thanks for the feedback!", "success")
    return redirect(url_for("track", code=code))


@app.route("/my-requests", methods=["GET", "POST"])
def my_requests():
    results = []
    searched = False
    phone = ""
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        searched = True
        if phone:
            db = get_db()
            results = db.execute(
                "SELECT * FROM requests WHERE phone = ? ORDER BY created_at DESC", (phone,)
            ).fetchall()
    return render_template("my_requests.html", results=results, searched=searched, phone=phone)


@app.route("/about")
def about():
    db = get_db()
    stats = get_stats(db)
    return render_template("about.html", stats=stats)


@app.route("/faq")
def faq():
    return render_template("faq.html", faqs=FAQS)


# ---------------------------------------------------------------- admin routes
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            next_url = request.args.get("next") or url_for("admin_overview")
            return redirect(next_url)
        flash("Incorrect password.", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("landing"))


@app.route("/admin")
@admin_required
def admin_root():
    return redirect(url_for("admin_overview"))


@app.route("/admin/overview")
@admin_required
def admin_overview():
    db = get_db()
    stats = get_stats(db)
    category_counts = db.execute(
        "SELECT category, COUNT(*) c FROM requests GROUP BY category"
    ).fetchall()
    recent_activity = db.execute(
        """SELECT sh.status, sh.note, sh.changed_at, r.tracking_code, r.name
           FROM status_history sh JOIN requests r ON r.id = sh.request_id
           ORDER BY sh.changed_at DESC LIMIT 8"""
    ).fetchall()
    avg_rating_row = db.execute("SELECT AVG(rating) a, COUNT(*) c FROM feedback").fetchone()
    return render_template(
        "admin/overview.html",
        stats=stats,
        category_counts={r["category"]: r["c"] for r in category_counts},
        recent_activity=recent_activity,
        avg_rating=round(avg_rating_row["a"], 1) if avg_rating_row["a"] else None,
        rating_count=avg_rating_row["c"],
        active_tab="overview",
    )


def _build_requests_query():
    status_filter = request.args.get("status", "")
    category_filter = request.args.get("category", "")
    search = request.args.get("q", "").strip()

    where = "WHERE 1=1"
    params = []
    if status_filter:
        where += " AND status = ?"
        params.append(status_filter)
    if category_filter:
        where += " AND category = ?"
        params.append(category_filter)
    if search:
        where += " AND (name LIKE ? OR tracking_code LIKE ? OR phone LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like, like])
    return where, params, status_filter, category_filter, search


@app.route("/admin/requests")
@admin_required
def admin_requests():
    db = get_db()
    where, params, status_filter, category_filter, search = _build_requests_query()

    total = db.execute(f"SELECT COUNT(*) c FROM requests {where}", params).fetchone()["c"]
    page = max(1, int(request.args.get("page", 1) or 1))
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    rows = db.execute(
        f"SELECT * FROM requests {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [PAGE_SIZE, offset],
    ).fetchall()

    return render_template(
        "admin/requests.html",
        requests=rows,
        status_filter=status_filter,
        category_filter=category_filter,
        search=search,
        statuses=STATUS_FLOW,
        active_tab="requests",
        page=page,
        total_pages=total_pages,
        total=total,
    )


@app.route("/admin/requests/<int:req_id>")
@admin_required
def admin_request_detail(req_id):
    db = get_db()
    req = db.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
    if not req:
        flash("Request not found.", "error")
        return redirect(url_for("admin_requests"))
    history = db.execute(
        "SELECT * FROM status_history WHERE request_id = ? ORDER BY changed_at ASC", (req_id,)
    ).fetchall()
    fb = db.execute("SELECT * FROM feedback WHERE request_id = ?", (req_id,)).fetchone()
    return render_template(
        "admin/detail.html", r=req, history=history, feedback=fb,
        statuses=STATUS_FLOW, active_tab="requests",
    )


@app.route("/admin/update/<int:req_id>", methods=["POST"])
@admin_required
def admin_update_status(req_id):
    new_status = request.form.get("status")
    note = request.form.get("note", "").strip() or None
    if new_status not in STATUS_FLOW:
        flash("Invalid status.", "error")
        return redirect(request.referrer or url_for("admin_requests"))
    db = get_db()
    db.execute(
        "UPDATE requests SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, datetime.now().isoformat(timespec="seconds"), req_id),
    )
    log_status(db, req_id, new_status, note)
    db.commit()
    flash("Request updated.", "success")
    return redirect(request.referrer or url_for("admin_requests"))


@app.route("/admin/bulk-update", methods=["POST"])
@admin_required
def admin_bulk_update():
    ids = request.form.getlist("selected")
    new_status = request.form.get("bulk_status")
    if not ids:
        flash("Select at least one request first.", "error")
    elif new_status not in STATUS_FLOW:
        flash("Choose a status to apply.", "error")
    else:
        db = get_db()
        now = datetime.now().isoformat(timespec="seconds")
        for rid in ids:
            db.execute("UPDATE requests SET status = ?, updated_at = ? WHERE id = ?", (new_status, now, rid))
            log_status(db, rid, new_status, "Bulk update")
        db.commit()
        flash(f"Updated {len(ids)} request(s) to {new_status}.", "success")

    # preserve filters
    qs = {k: v for k, v in request.form.items() if k in ("status", "category", "q", "page")}
    return redirect(url_for("admin_requests", **qs))


@app.route("/admin/export.csv")
@admin_required
def admin_export_csv():
    db = get_db()
    where, params, *_ = _build_requests_query()
    rows = db.execute(f"SELECT * FROM requests {where} ORDER BY created_at DESC", params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Tracking Code", "Name", "Phone", "Category", "Address", "Landmark",
                      "Preferred Date", "Status", "Notes", "Submitted", "Last Updated"])
    for r in rows:
        writer.writerow([r["tracking_code"], r["name"], r["phone"], r["category"], r["address"],
                          r["landmark"], r["preferred_date"], r["status"], r["notes"],
                          r["created_at"], r["updated_at"]])

    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=waste_requests.csv"},
    )


@app.route("/admin/feedback")
@admin_required
def admin_feedback():
    db = get_db()
    rows = db.execute(
        """SELECT f.*, r.tracking_code, r.category, r.name FROM feedback f
           JOIN requests r ON r.id = f.request_id ORDER BY f.created_at DESC"""
    ).fetchall()
    avg_rating_row = db.execute("SELECT AVG(rating) a, COUNT(*) c FROM feedback").fetchone()
    return render_template(
        "admin/feedback.html", feedback=rows, active_tab="feedback",
        avg_rating=round(avg_rating_row["a"], 1) if avg_rating_row["a"] else None,
        rating_count=avg_rating_row["c"],
    )


@app.route("/admin/announcements", methods=["GET", "POST"])
@admin_required
def admin_announcements():
    db = get_db()
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            db.execute(
                "INSERT INTO announcements (message, active, created_at) VALUES (?, 1, ?)",
                (message, datetime.now().isoformat(timespec="seconds")),
            )
            db.commit()
            flash("Announcement posted.", "success")
        else:
            flash("Announcement message can't be empty.", "error")
        return redirect(url_for("admin_announcements"))

    rows = db.execute("SELECT * FROM announcements ORDER BY created_at DESC").fetchall()
    return render_template("admin/announcements.html", announcements=rows, active_tab="announcements")


@app.route("/admin/announcements/<int:ann_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_announcement(ann_id):
    db = get_db()
    row = db.execute("SELECT * FROM announcements WHERE id = ?", (ann_id,)).fetchone()
    if row:
        db.execute("UPDATE announcements SET active = ? WHERE id = ?", (0 if row["active"] else 1, ann_id))
        db.commit()
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:ann_id>/delete", methods=["POST"])
@admin_required
def admin_delete_announcement(ann_id):
    db = get_db()
    db.execute("DELETE FROM announcements WHERE id = ?", (ann_id,))
    db.commit()
    flash("Announcement deleted.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/api/stats")
def api_stats():
    db = get_db()
    rows = db.execute("SELECT status, COUNT(*) c FROM requests GROUP BY status").fetchall()
    return jsonify({r["status"]: r["c"] for r in rows})


@app.route("/healthz")
def healthz():
    return {"status": "ok"}


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
