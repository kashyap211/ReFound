"""ReFound - Smart Lost & Found Detection System (Flask + SQLite).

Run:  python app.py   ->  http://127.0.0.1:5000
"""
import hmac
import os
import random
import sqlite3
import time
import uuid
from datetime import datetime, timedelta

from flask import (Flask, abort, flash, g, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}
CATEGORIES = ["Mobile Phone", "Wallet", "Keys", "Bag", "ID Card", "Watch", "Other"]
STATUSES = ["Found", "Pending", "Claimed", "Unclaimed"]
APP_START = time.time()

app = Flask(__name__)
# Secret key is read from the environment - never hard-coded.
app.config["SECRET_KEY"] = os.environ.get("REFOUND_SECRET_KEY") or os.urandom(24).hex()
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB upload limit
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ---------------------------------------------------------------- DATABASE --
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, category TEXT NOT NULL, description TEXT DEFAULT '',
    image_filename TEXT, date_detected TEXT NOT NULL, time_detected TEXT NOT NULL,
    location TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'Pending',
    notes TEXT DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL, detected_at TEXT NOT NULL, source TEXT NOT NULL,
    status TEXT NOT NULL, image_filename TEXT,
    FOREIGN KEY (item_id) REFERENCES items(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def get_db():
    """One SQLite connection per request. Foreign keys must be enabled per connection."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_setting(key, default=None):
    row = get_db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    db = get_db()
    db.execute("INSERT INTO settings(key,value) VALUES(?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    db.commit()


def demo_on():
    return get_setting("demo_mode", "1") == "1"


# Demo records: name, category, description, location, status, hours ago, colour
DEMO_ITEMS = [
    ("Black Wallet", "Wallet", "Black leather wallet with several card slots.", "Room 101", "Found", 2, "#334155"),
    ("Smartphone", "Mobile Phone", "Smartphone with a blue case, screen locked.", "Library - Reading Hall", "Pending", 5, "#2563eb"),
    ("Keychain", "Keys", "Three keys on a red ring.", "Cafeteria", "Found", 26, "#dc2626"),
    ("Backpack", "Bag", "Grey backpack with a laptop compartment.", "Lab 3", "Claimed", 30, "#64748b"),
    ("Student ID Card", "ID Card", "College ID card, photo slightly worn.", "Main Gate", "Unclaimed", 52, "#0d9488"),
    ("Silver Wrist Watch", "Watch", "Analog watch with a metal strap.", "Seminar Hall", "Pending", 76, "#7c3aed"),
    ("Water Bottle", "Other", "Steel water bottle with a dented base.", "Playground", "Unclaimed", 100, "#ea580c"),
    ("Earbuds Case", "Other", "White earbuds charging case.", "Room 204", "Claimed", 150, "#0891b2"),
]


def make_placeholder(filename, label, colour):
    """Create a simple local SVG picture so demo items have a photo (no internet needed)."""
    path = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">'
                    f'<rect width="400" height="300" fill="{colour}"/>'
                    f'<text x="200" y="160" font-family="Arial" font-size="32" fill="#fff" '
                    f'text-anchor="middle">{label}</text></svg>')


def demo_image(name, colour):
    fn = "demo_" + name.lower().replace(" ", "_") + ".svg"
    make_placeholder(fn, name, colour)
    return fn


def load_demo_data():
    """Insert the demo items (skips any that already exist). Returns how many were added."""
    db, added = get_db(), 0
    for name, cat, desc, loc, status, hrs, colour in DEMO_ITEMS:
        fn = demo_image(name, colour)
        if db.execute("SELECT 1 FROM items WHERE image_filename=?", (fn,)).fetchone():
            continue
        record_detection(db, name, cat, desc, loc, status, fn, "Demo Simulator",
                         when=datetime.now() - timedelta(hours=hrs))
        added += 1
    return added


def init_db():
    """Create tables if missing and seed demo data on the very first run."""
    db = get_db()
    db.executescript(SCHEMA)
    if get_setting("seeded") is None:
        set_setting("demo_mode", "1")
        load_demo_data()
        set_setting("seeded", "1")


# ------------------------------------------------------------- HELPERS -----
def record_detection(db, name, category, description="", location="", status="Found",
                     image_filename=None, source="Raspberry Pi", notes="", when=None):
    """DETECTION RECORDING: creates the item row AND its detection-history row.
    Date and time are recorded automatically. Returns (item_id, detection_id)."""
    when = when or datetime.now()
    cur = db.execute(
        "INSERT INTO items (name,category,description,image_filename,date_detected,"
        "time_detected,location,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (name, category, description, image_filename, when.strftime("%Y-%m-%d"),
         when.strftime("%H:%M:%S"), location, status, notes, when.strftime("%Y-%m-%d %H:%M:%S")))
    item_id = cur.lastrowid
    det = db.execute(
        "INSERT INTO detections (item_id,detected_at,source,status,image_filename) VALUES (?,?,?,?,?)",
        (item_id, when.strftime("%Y-%m-%d %H:%M:%S"), source, status, image_filename))
    db.commit()
    return item_id, det.lastrowid


def clean_item(data):
    """Validate and tidy user/Pi input. Returns (clean_dict, list_of_errors)."""
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "Other").strip()
    status = (data.get("status") or "Found").strip().title()
    clean = {"name": name, "category": category, "status": status,
             "description": (data.get("description") or "").strip()[:500],
             "location": (data.get("location") or "").strip()[:100],
             "notes": (data.get("notes") or "").strip()[:500]}
    errors = []
    if not name or len(name) > 100:
        errors.append("Item name is required (max 100 characters).")
    if category not in CATEGORIES:
        errors.append("Category must be one of: " + ", ".join(CATEGORIES) + ".")
    if status not in STATUSES:
        errors.append("Status must be one of: " + ", ".join(STATUSES) + ".")
    return clean, errors


def save_image(file):
    """IMAGE UPLOAD: check extension, make the filename safe + unique, save to uploads/.
    Returns (filename or None, error message or None)."""
    if not file or not file.filename:
        return None, None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXT:
        return None, "Only PNG, JPG, GIF or WEBP images are allowed."
    filename = f"{uuid.uuid4().hex[:10]}_{secure_filename(file.filename)}"
    file.save(os.path.join(UPLOAD_DIR, filename))
    return filename, None


def api_auth_ok():
    """Optional shared token. If REFOUND_API_TOKEN is set, the Pi must send it
    in the X-API-Token header. If not set, the API is open (fine on a local network)."""
    token = os.environ.get("REFOUND_API_TOKEN")
    return not token or hmac.compare_digest(request.headers.get("X-API-Token", ""), token)


# RASPBERRY PI INTEGRATION: the Pi will POST its health to /api/system-status.
# The latest report is kept in memory; it counts as "live" for 2 minutes.
PI_REPORT = {"data": None, "at": 0}


def get_system_status():
    """Returns hardware status. Replace the simulated branch once the Pi reports in."""
    last = get_db().execute("SELECT MAX(detected_at) AS t FROM detections").fetchone()["t"]
    rep = PI_REPORT["data"]
    if rep and time.time() - PI_REPORT["at"] < 120:  # real data from the Pi
        return {"mode": "live", "pi_online": bool(rep.get("pi_online")),
                "camera_online": bool(rep.get("camera_online")),
                "ir_active": bool(rep.get("ir_active")),
                "oled_online": bool(rep.get("oled_online")),
                "database_online": True, "last_detection": last,
                "uptime_seconds": int(rep.get("uptime_seconds") or 0)}
    sim = demo_on()  # no Pi: simulated values in demo mode, otherwise everything offline
    return {"mode": "simulated" if sim else "offline", "pi_online": sim,
            "camera_online": sim, "ir_active": sim, "oled_online": sim,
            "database_online": True, "last_detection": last,
            "uptime_seconds": int(time.time() - APP_START) if sim else 0}


@app.context_processor
def inject_globals():
    return {"demo_mode": demo_on(), "CATEGORIES": CATEGORIES, "STATUSES": STATUSES}


@app.template_global()
def img_url(filename):
    return url_for("uploaded_file", filename=filename) if filename else \
        url_for("static", filename="images/placeholder.svg")


@app.template_filter("det_id")
def det_id(n):
    return f"DET-{int(n):04d}"


@app.template_filter("uptime")
def uptime(sec):
    h, m = divmod(int(sec) // 60, 60)
    return f"{h}h {m}m"


# -------------------------------------------------------------- PAGES ------
@app.route("/")
def dashboard():
    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    count = lambda sql, p=(): db.execute(sql, p).fetchone()[0]
    stats = {"total": count("SELECT COUNT(*) FROM items"),
             "found": count("SELECT COUNT(*) FROM items WHERE status='Found'"),
             "pending": count("SELECT COUNT(*) FROM items WHERE status='Pending'"),
             "today": count("SELECT COUNT(*) FROM detections WHERE date(detected_at)=?", (today,))}
    recent = db.execute(
        "SELECT d.*, i.name, i.location, i.status AS item_status FROM detections d "
        "JOIN items i ON i.id=d.item_id ORDER BY d.detected_at DESC, d.id DESC LIMIT 6").fetchall()
    return render_template("index.html", stats=stats, recent=recent, status=get_system_status())


@app.route("/items")
def items():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "")
    st = request.args.get("status", "")
    sort = request.args.get("sort", "newest")
    sql, params = "SELECT * FROM items WHERE 1=1", []
    if q:
        sql += " AND (name LIKE ? OR description LIKE ? OR location LIKE ?)"
        params += [f"%{q}%"] * 3
    if cat in CATEGORIES:
        sql += " AND category=?"; params.append(cat)
    if st in STATUSES:
        sql += " AND status=?"; params.append(st)
    order = {"newest": "created_at DESC, id DESC", "oldest": "created_at ASC, id ASC",
             "name": "name COLLATE NOCASE ASC", "status": "status ASC, created_at DESC"}
    sql += " ORDER BY " + order.get(sort, order["newest"])  # whitelist -> safe
    rows = get_db().execute(sql, params).fetchall()
    return render_template("items.html", items=rows, q=q, cat=cat, st=st, sort=sort)


@app.route("/items/add", methods=["POST"])
def add_item():
    clean, errors = clean_item(request.form)
    filename, img_err = save_image(request.files.get("image"))
    if img_err:
        errors.append(img_err)
    if errors:
        for e in errors:
            flash(e, "error")
        return redirect(url_for("items"))
    item_id, _ = record_detection(get_db(), clean["name"], clean["category"], clean["description"],
                                  clean["location"], clean["status"], filename, "Manual Upload", clean["notes"])
    flash(f"'{clean['name']}' was added.", "success")
    return redirect(url_for("item_detail", item_id=item_id))


@app.route("/item/<int:item_id>")
def item_detail(item_id):
    item = get_db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    dets = get_db().execute("SELECT * FROM detections WHERE item_id=? ORDER BY detected_at DESC",
                            (item_id,)).fetchall()
    return render_template("item_detail.html", item=item, detections=dets)


@app.route("/item/<int:item_id>/status", methods=["POST"])
def update_status(item_id):
    data = request.get_json(silent=True) if request.is_json else request.form
    status = ((data or {}).get("status") or "").strip().title()
    if status not in STATUSES:
        if request.is_json:
            return jsonify(error="Invalid status"), 400
        flash("Invalid status.", "error")
        return redirect(url_for("item_detail", item_id=item_id))
    db = get_db()
    cur = db.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))
    db.commit()
    if cur.rowcount == 0:
        abort(404)
    if request.is_json:
        return jsonify(id=item_id, status=status)
    flash(f"Status changed to {status}.", "success")
    return redirect(url_for("item_detail", item_id=item_id))


@app.route("/item/<int:item_id>/delete", methods=["POST"])
def delete_item(item_id):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    db.execute("DELETE FROM items WHERE id=?", (item_id,))  # detections cascade
    db.commit()
    fn = item["image_filename"]
    if fn and not fn.startswith("demo_"):  # keep shared demo pictures
        still_used = db.execute("SELECT 1 FROM items WHERE image_filename=?", (fn,)).fetchone()
        path = os.path.join(UPLOAD_DIR, fn)
        if not still_used and os.path.exists(path):
            os.remove(path)
    if request.is_json:
        return jsonify(deleted=item_id)
    flash(f"'{item['name']}' was deleted.", "success")
    return redirect(url_for("items"))


@app.route("/detections")
def detections():
    date, cat, st = request.args.get("date", ""), request.args.get("category", ""), request.args.get("status", "")
    sql = ("SELECT d.*, i.name, i.category FROM detections d "
           "JOIN items i ON i.id=d.item_id WHERE 1=1")
    params = []
    if date:
        sql += " AND date(d.detected_at)=?"; params.append(date)
    if cat in CATEGORIES:
        sql += " AND i.category=?"; params.append(cat)
    if st in STATUSES:
        sql += " AND d.status=?"; params.append(st)
    sql += " ORDER BY d.detected_at DESC, d.id DESC"
    rows = get_db().execute(sql, params).fetchall()
    return render_template("detections.html", rows=rows, date=date, cat=cat, st=st)


@app.route("/settings")
def settings():
    return render_template("settings.html", status=get_system_status())


@app.route("/settings/demo", methods=["POST"])
def toggle_demo():
    new = "0" if demo_on() else "1"
    set_setting("demo_mode", new)
    flash("Demo mode is now " + ("ON." if new == "1" else "OFF."), "success")
    return redirect(url_for("settings"))


@app.route("/demo/load", methods=["POST"])
def demo_load():
    n = load_demo_data()
    flash(f"{n} demo item(s) added." if n else "Demo data is already loaded.", "success")
    return redirect(request.referrer or url_for("dashboard"))


@app.route("/demo/simulate", methods=["POST"])
def demo_simulate():
    """Fake a Pi detection so you can demo the dashboard without hardware."""
    if not demo_on():
        flash("Turn demo mode ON in Settings first.", "error")
        return redirect(url_for("dashboard"))
    name, cat, desc, loc, _s, _h, colour = random.choice(DEMO_ITEMS)
    record_detection(get_db(), name, cat, desc, loc, "Found", demo_image(name, colour), "Demo Simulator")
    flash(f"Simulated detection: {name}.", "success")
    return redirect(url_for("dashboard"))


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)  # blocks path traversal


# ---------------------------------------------------------------- API ------
@app.post("/api/detection")
def api_detection():
    """RASPBERRY PI ENDPOINT. Accepts JSON (or multipart form with an 'image' file).
    Example JSON: {"name":"Wallet","category":"Wallet","description":"...","location":"Room 101","status":"Found"}"""
    if not api_auth_ok():
        return jsonify(error="Invalid or missing API token"), 401
    data = request.get_json(silent=True) if request.is_json else request.form
    if not data:
        return jsonify(error="Send a JSON body or form data"), 400
    clean, errors = clean_item(data)
    filename = None
    if request.files.get("image"):
        filename, img_err = save_image(request.files["image"])
        if img_err:
            errors.append(img_err)
    if errors:
        return jsonify(error="Validation failed", details=errors), 400
    source = str(data.get("source") or "Raspberry Pi")[:50]
    item_id, det_id_ = record_detection(get_db(), clean["name"], clean["category"], clean["description"],
                                        clean["location"], clean["status"], filename, source, clean["notes"])
    return jsonify(message="Detection recorded", detection_id=det_id_,
                   detection_code=f"DET-{det_id_:04d}", item_id=item_id,
                   recorded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")), 201


@app.get("/api/items")
def api_items():
    rows = get_db().execute("SELECT * FROM items ORDER BY created_at DESC, id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/detections")
def api_detections():
    rows = get_db().execute(
        "SELECT d.*, i.name, i.category FROM detections d JOIN items i ON i.id=d.item_id "
        "ORDER BY d.detected_at DESC, d.id DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/system-status", methods=["GET", "POST"])
def api_system_status():
    """GET: dashboard/Pi reads status. POST: the Pi reports its hardware health."""
    if request.method == "POST":
        if not api_auth_ok():
            return jsonify(error="Invalid or missing API token"), 401
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error="Send a JSON object"), 400
        PI_REPORT["data"], PI_REPORT["at"] = data, time.time()
        return jsonify(message="Status received")
    return jsonify(get_system_status())


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="Not found"), 404
    flash("That page or item could not be found.", "error")
    return redirect(url_for("dashboard"))


@app.errorhandler(413)
def too_big(_e):
    flash("The image is too large (max 5 MB).", "error")
    return redirect(url_for("items"))


with app.app_context():
    init_db()

if __name__ == '__main__':
    import os
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=True
    )