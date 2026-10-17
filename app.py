import os
import re

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from config.settings import SUBJECT_TYPES
from config.curriculum import available_departments, load_curriculum
from routes.schedule_routes import schedule_bp
from routes.analytics_routes import analytics_bp
from routes.run_routes import runs_bp
from routes.session_routes import session_bp
from services.auth_service import ANY_ROLE, AuthError, auth_enabled, error_response, gate, require_user, scope_dept

try:                                    # local development: read .env (Render sets real environment variables)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# CORS. The site is served by this same Flask app, so normal use is same-origin and needs no CORS at all.
# ATLAS_CORS_ORIGINS (comma separated, "*" allowed) sets the allowed origins explicitly. Without it:
# auth off (local dev) allows everything; auth on allows only the local dev ports.
_LOCAL_ORIGINS = [
    # this computer (Flask :5000, VS Code Live Server :5500/:5501, any other dev port) and the school LAN / a phone on it
    re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"),
    re.compile(r"^https?://(192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?$"),
    "http://localhost:5000", "http://127.0.0.1:5000",
    # the deployed site: static frontend on Render and the backend's own address
    "https://atlas-psu.onrender.com", "https://atlas-drsg.onrender.com",
]


def cors_origins():
    raw = (os.environ.get("ATLAS_CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return _LOCAL_ORIGINS if auth_enabled() else "*"


CORS(app, origins=cors_origins(), allow_headers=["Authorization", "Content-Type"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])

app.before_request(gate)                # every endpoint except the public ones needs a valid token


def _supabase_origins() -> list:
    """The Supabase project URL comes from the environment (never hard-coded). Without it (local dev) the
    whole supabase.co domain is allowed so the page still works."""
    base = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    if base.startswith("https://") and "." in base:
        return [base, "wss://" + base[len("https://"):]]
    return ["https://*.supabase.co", "wss://*.supabase.co"]


def content_security_policy() -> str:
    connect = " ".join(["'self'"] + _supabase_origins())
    return "; ".join([
        "default-src 'self'",
        "script-src 'self'",                       # no inline scripts: they live in assets/js
        "style-src 'self' 'unsafe-inline'",       # inline style attributes are used by the UI
        "img-src 'self' data:",
        "font-src 'self'",
        f"connect-src {connect}",
        "manifest-src 'self'",
        "worker-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ])


@app.after_request
def _security_headers(resp):
    h = resp.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "strict-origin-when-cross-origin"
    h["Content-Security-Policy"] = content_security_policy()
    return resp


@app.errorhandler(AuthError)
def _auth_error(e):
    return error_response(e)

# All runtime state (progress, results, analytics, class sizes, rooms, soft
# constraints, faculty) lives per department in services/schedule_service.py.

# ── Register blueprints ───────────────────────────────────────────────────────
app.register_blueprint(schedule_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(runs_bp)
app.register_blueprint(session_bp)


# ── Frontend (served by Flask so one command runs the whole demo) ─────────────
# Only these folders and files are public; the Python code, tests, .env and the
# README are never served. send_from_directory rejects paths that leave the folder.
ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIRS = ("pages", "faculty", "assets", "app", "data")


@app.route("/", methods=["GET"])
@app.route("/index.html", methods=["GET"])
def index_page():
    return send_from_directory(ROOT, "index.html")


@app.route("/manifest.json", methods=["GET"])
def manifest_file():
    return send_from_directory(ROOT, "manifest.json")


@app.route("/404.html", methods=["GET"])
def not_found_page():
    return send_from_directory(ROOT, "404.html")


@app.route("/sw.js", methods=["GET"])
def offline_worker():
    """The offline page worker. It must be served from the site root and never cached for long."""
    resp = send_from_directory(ROOT, "sw.js", mimetype="application/javascript")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.errorhandler(404)
def handle_404(_error):
    """A browser asking for a page that does not exist gets the 404 page; API clients keep getting JSON."""
    wants_html = request.method == "GET" and request.accept_mimetypes.best == "text/html"
    if wants_html:
        resp = send_from_directory(ROOT, "404.html")
        resp.status_code = 404
        return resp
    return jsonify({"success": False, "error": "Not found", "data": {}, "metrics": {}, "warnings": []}), 404


@app.route("/<any(%s):folder>/<path:filename>" % ",".join(STATIC_DIRS), methods=["GET"])
def static_files(folder, filename):
    return send_from_directory(os.path.join(ROOT, folder), filename)


@app.route("/subject-types", methods=["GET"])
@require_user(ANY_ROLE)
def get_subject_types():
    """Allowed specialization tags: the department's own list when ?dept= is given."""
    dept = scope_dept(request.args.get("dept") or None)
    types = SUBJECT_TYPES
    if dept:
        if dept not in available_departments():
            return jsonify({"success": False, "error": f"Unknown department: {dept}",
                            "data": {}, "metrics": {}, "warnings": []}), 400
        types = load_curriculum(dept).get("specializations", SUBJECT_TYPES)
    return jsonify({"success": True, "data": {"subject_types": types},
                    "metrics": {}, "warnings": []})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)