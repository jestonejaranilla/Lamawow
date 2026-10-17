import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The existing suite runs with auth off and no database. New auth tests turn auth on with monkeypatch.
# Empty values stop a developer's real .env from being used (load_dotenv never overrides set variables).
os.environ["ATLAS_AUTH"] = "off"   # forced: a value left in the developer's shell (for example "on") must not change the suite
for _k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_JWT_SECRET",
           "SUPABASE_JWKS_URL", "ATLAS_CORS_ORIGINS"):
    os.environ[_k] = ""
os.environ.pop("RENDER", None)


"""
Shared test fixtures and the ONE faculty-pool builder used by every test.

dept_faculty(dept): 10 professors, each holding 2 or 3 tags of that
department's `specializations`, every tag covered, available Mon to Thu,
max_units 24, absolute_max_units 30. Deterministic.

IT uses the pool the dashboard starts with (`default_faculty` in IT.json), so
the tests run on the real demo data. IT2B1 has 45 students, so its labs are not
split and it needs 15 meetings in the 20 Mon to Thu slots (with 48 students it
needed 21, which cannot fit: one meeting per block per slot, R4).
"""

from tools.faculty_pool import (  # noqa: F401  (re-exported: the tests import these names from conftest)
    DAYS, DEPTS, SEM1, SEM2, SEMS, POOL_SIZE, make_faculty, _tag_demand, dept_faculty,
)


def legacy_subjects():
    """A non-empty request without group ids: the engine builds every group from the curriculum."""
    return [{"name": "x"}]