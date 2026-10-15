"""Part 10: logout exists only in app/account.html."""
import pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAT = re.compile(r"log ?out", re.I)


def test_logout_only_in_account_page():
    for folder in ("pages", "faculty", "app"):
        for f in (ROOT / folder).glob("*.html"):
            has = bool(PAT.search(f.read_text(encoding="utf-8")))
            assert has == (f.name == "account.html" and folder == "app"), f


def test_account_link_kept_and_logout_api_kept():
    for p in ("pages/dashboard.html", "faculty/dashboard.html"):
        assert "../app/account.html" in (ROOT / p).read_text(encoding="utf-8")
    assert "window.atlasLogout" in (ROOT / "assets/js/app-core.js").read_text(encoding="utf-8")
    assert 'id="btnSignOut"' in (ROOT / "app/account.html").read_text(encoding="utf-8")
    js = (ROOT / "assets/js/app-script.js").read_text(encoding="utf-8")
    assert "appLogout" not in js and "data-logout" not in (ROOT / "assets/js/faculty-script.js").read_text(encoding="utf-8")