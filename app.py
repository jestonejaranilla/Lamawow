from flask import Flask, jsonify, request
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