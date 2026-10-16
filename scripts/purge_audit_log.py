"""
ATLAS PSU - scripts/purge_audit_log.py   (admin-only developer tool)

Deletes audit_log rows older than a given age by calling the database function public.purge_audit_log(interval).
That function only accepts a signed-in ADMIN user, so this script signs in as an admin (email and password are
asked for; the password is never taken from the command line and never printed or stored).

  python scripts/purge_audit_log.py --older-than "12 months"
  python scripts/purge_audit_log.py --older-than "1 day"          (development only)
  python scripts/purge_audit_log.py --older-than "400 days" --dry-run

Retention rule (team decision): PRODUCTION keeps at least 12 months of audit rows. In production the script
refuses anything shorter than 12 months, and there is no override. Development may purge freely.
Production is detected from ATLAS_ENV=production or the RENDER variable.

Needs SUPABASE_URL and SUPABASE_ANON_KEY (public key) in the environment or .env. The service key is not used.
"""
import argparse
import getpass
import os
import re
import sys

MIN_PRODUCTION_DAYS = 365
_UNITS = {"day": 1.0, "week": 7.0, "month": 30.4375, "year": 365.25}      # 12 months = 365.25 days
_PATTERN = re.compile(r"^\s*(\d{1,4})\s*(day|week|month|year)s?\s*$", re.IGNORECASE)


def parse_interval(text: str):
    """'12 months' -> ('12 months', 365.25). Raises ValueError for anything that is not whole days, weeks, months or years."""
    m = _PATTERN.match(text or "")
    if not m or int(m.group(1)) < 1:
        raise ValueError('--older-than must look like "12 months", "400 days", "52 weeks" or "1 year".')
    n, unit = int(m.group(1)), m.group(2).lower()
    return "%d %s%s" % (n, unit, "" if n == 1 else "s"), n * _UNITS[unit]


def is_production(env=None) -> bool:
    env = os.environ if env is None else env
    return (env.get("ATLAS_ENV", "").strip().lower() in ("production", "prod")) or bool(env.get("RENDER"))


def check_retention(days: float, production: bool) -> None:
    if production and days < MIN_PRODUCTION_DAYS:
        raise ValueError("Production keeps at least 12 months of audit rows. Refusing to purge anything newer than that.")


def run(argv=None, client_factory=None, ask=input, ask_secret=getpass.getpass, env=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Purge old audit_log rows (admin only).")
    ap.add_argument("--older-than", required=True, help='age, e.g. "12 months", "400 days"')
    ap.add_argument("--dry-run", action="store_true", help="only count the rows that would be deleted")
    args = ap.parse_args(argv)
    try:
        interval, days = parse_interval(args.older_than)
        check_retention(days, is_production(env))
    except ValueError as e:
        out("Error: %s" % e)
        return 2

    if client_factory is None:
        client_factory = _real_client
    email = (os.environ.get("ATLAS_ADMIN_EMAIL") or "").strip() or ask("Admin email: ").strip()
    password = ask_secret("Admin password: ")
    try:
        client = client_factory(email, password)
    except Exception as e:                                                            # noqa: BLE001
        out("Could not sign in as admin: %s" % e)
        return 1

    try:
        cutoff = _cutoff_iso(days)
        res = client.table("audit_log").select("id", count="exact").lt("at", cutoff).limit(1).execute()
        n = getattr(res, "count", None)
    except Exception:                                                                 # noqa: BLE001
        n = None
    out("Environment: %s" % ("PRODUCTION" if is_production(env) else "development"))
    out("Rows older than %s: %s" % (interval, "unknown" if n is None else n))
    if args.dry_run:
        out("Dry run: nothing deleted.")
        return 0

    answer = ask('This permanently deletes them. Type "PURGE" to continue: ').strip()
    if answer != "PURGE":
        out("Cancelled. Nothing was deleted.")
        return 1
    try:
        res = client.rpc("purge_audit_log", {"older_than": interval}).execute()
    except Exception as e:                                                            # noqa: BLE001
        out("The purge failed: %s" % e)
        return 1
    out("Deleted %s audit rows." % res.data)
    return 0


def _cutoff_iso(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _real_client(email: str, password: str):
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_ANON_KEY", "")
    if not (url and key):
        try:
            from dotenv import load_dotenv
            load_dotenv()
            url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_ANON_KEY", "")
        except ImportError:
            pass
    if not (url and key):
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY must be set.")
    from supabase import create_client
    client = create_client(url, key)
    client.auth.sign_in_with_password({"email": email, "password": password})
    return client


if __name__ == "__main__":
    sys.exit(run())