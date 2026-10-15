import os

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
_LOCAL_ORIGINS = ["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:5500",
                  "http://127.0.0.1:5500", "http://localhost:5501", "http://127.0.0.1:5501",
                  "http://localhost:3000", "http://127.0.0.1:3000"]


def cors_origins():
    raw = (os.environ.get("ATLAS_CORS_ORIGINS") or "").strip()
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return _LOCAL_ORIGINS if auth_enabled() else "*"


CORS(app, origins=cors_origins(), allow_headers=["Authorization", "Content-Type"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])

app.before_request(gate)                # every endpoint except the public ones needs a valid token


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