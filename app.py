import os

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from config.settings import SUBJECT_TYPES
from config.curriculum import available_departments, load_curriculum
from routes.schedule_routes import schedule_bp
from routes.analytics_routes import analytics_bp

app = Flask(__name__)
CORS(app)

# All runtime state (progress, results, analytics, class sizes, rooms, soft
# constraints, faculty) lives per department in services/schedule_service.py.

# ── Register blueprints ───────────────────────────────────────────────────────
app.register_blueprint(schedule_bp)
app.register_blueprint(analytics_bp)


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
def get_subject_types():
    """Allowed specialization tags: the department's own list when ?dept= is given."""
    dept = request.args.get("dept")
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