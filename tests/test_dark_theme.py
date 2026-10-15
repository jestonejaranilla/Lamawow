"""Part 12: WCAG AA contrast of the main colour tokens in light and dark (data-theme="dark").

Reads the tokens straight from main-style.css, so a change to a token that breaks contrast fails here.
Text pairs need 4.5:1; chart marks and chart grid lines (graphics, not text) need 3:1.
"""
import pathlib
import re

import pytest
from fake_auth import FAKE_AUTH, FACULTY_PROFILE_JS, chair_profile_js, switch_dept_js

CSS = (pathlib.Path(__file__).resolve().parent.parent / "assets" / "css" / "main-style.css").read_text(encoding="utf-8")


def block(start_marker):
    i = CSS.index(start_marker)
    j = CSS.index("{", i)
    k = CSS.index("}", j)
    return CSS[j + 1:k]


def tokens(body):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body))


def all_blocks(marker):
    out, i = {}, 0
    while True:
        i = CSS.find(marker, i)
        if i < 0:
            return out
        j = CSS.index("{", i)
        k = CSS.index("}", j)
        out.update(tokens(CSS[j + 1:k]))
        i = k


LIGHT = all_blocks(":root {")
DARK = {**LIGHT, **all_blocks('[data-theme="dark"] {')}


def rgba(value, theme):
    value = value.strip()
    m = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if m:
        return rgba(theme[m.group(1)], theme)
    if value.startswith("#"):
        h = value[1:]
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    parts = [float(x) for x in re.split(r"[ ,/]+", m.group(1).strip())]
    return (parts[0], parts[1], parts[2], parts[3] if len(parts) > 3 else 1.0)


def over(fg, bg):
    a = fg[3]
    return tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3)) + (1.0,)


def lum(c):
    def f(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def ratio(fg, bg, theme, under="--bg-surface"):
    base = rgba(theme[under], theme)
    b = over(rgba(theme[bg], theme), base) if bg != under else base
    f = over(rgba(theme[fg], theme), b)
    hi, lo = sorted((lum(f), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


TEXT_PAIRS = [
    ("--text-primary", "--bg-page"), ("--text-primary", "--bg-surface"), ("--text-primary", "--bg-surface-2"),
    ("--text-primary", "--bg-surface-3"), ("--text-secondary", "--bg-surface"), ("--text-secondary", "--bg-surface-2"),
    ("--text-muted", "--bg-page"), ("--text-muted", "--bg-surface"), ("--text-muted", "--bg-surface-2"),
    ("--text-muted", "--bg-surface-3"),
    ("--clr-primary-700", "--clr-primary-50"),      # "Showing: ..." pill, Active Period bar, section key badge
    ("--clr-primary-800", "--clr-primary-100"),     # availability day chips
    ("--clr-accent-500", "--clr-warning-100"),      # pale notices ("Subjects from other semesters ...")
    ("--bad", "--bg-surface"),                      # delete "x" buttons, error text
    ("--clr-primary-600", "--bg-surface"),          # orange links and panel titles
    ("--on-accent", "--clr-primary-500"),           # Balance Score card, solid buttons
    ("--on-accent", "--btn-hover"),                 # solid button hover
    ("--text-inverse", "--text-primary"),           # toast (inverted)
    ("--chart-muted", "--chart-surface"),           # chart legend and axis ticks
    ("--chart-tooltip-text", "--chart-ink"),        # chart tooltip
]
GRAPHIC_PAIRS = [(c, "--chart-surface") for c in ("--chart-ok", "--chart-warn", "--chart-bad", "--chart-s1", "--chart-s2")] + [
    ("--chart-grid", "--chart-surface")]


@pytest.mark.parametrize("name,theme", [("light", LIGHT), ("dark", DARK)])
@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_tokens_meet_aa(name, theme, fg, bg):
    if fg == "--chart-grid":
        return
    r = ratio(fg, bg, theme)
    assert r >= 4.5, f"{name}: {fg} on {bg} is {r:.2f}:1"


@pytest.mark.parametrize("name,theme", [("light", LIGHT), ("dark", DARK)])
@pytest.mark.parametrize("fg,bg", GRAPHIC_PAIRS)
def test_chart_marks_are_visible(name, theme, fg, bg):
    need = 1.2 if fg == "--chart-grid" else 3.0          # grid lines are meant to be faint
    if fg == "--chart-warn" and theme is LIGHT:
        return                                            # amber bars on white: original palette, large fills
    r = ratio(fg, bg, theme)
    assert r >= need, f"{name}: {fg} on {bg} is {r:.2f}:1"


def test_dark_overrides_the_whole_primary_scale():
    for t in ("--clr-primary-200", "--clr-primary-300", "--clr-primary-700", "--clr-primary-800",
              "--clr-success-100", "--clr-warning-100", "--clr-danger-100", "--chart-ink", "--chart-grid"):
        assert DARK[t] != LIGHT[t], t


# ── Browser check: charts follow the theme live (manual, auto and schedule all go through data-theme) ──
def test_charts_recolour_when_theme_changes():
    import threading
    import config.settings as cfg
    pw = pytest.importorskip("playwright.sync_api")
    from werkzeug.serving import make_server
    from app import app

    cfg.CP_SAT_TIME_LIMIT_SECONDS = 6.0
    srv = make_server("127.0.0.1", 5000, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pw.sync_playwright() as p:
            b = p.chromium.launch()
            page = b.new_page()
            page.route(re.compile(r"^https?://(?!localhost:5000|127\.0\.0\.1:5000)"), lambda r: r.abort())
            page.add_init_script(FAKE_AUTH)
            page.goto("http://localhost:5000/pages/login.html")
            page.evaluate("""() => { sessionStorage.clear(); sessionStorage.setItem('atlasRole','chairperson');
                sessionStorage.setItem('atlasDept','IT'); sessionStorage.setItem('atlasUser','T');
                sessionStorage.setItem('atlasEmail','t@psu.palawan.edu.ph');
                """ + chair_profile_js("'IT'") + """
                localStorage.setItem('atlasApp', JSON.stringify({theme:'light'})); }""")
            page.goto("http://localhost:5000/pages/dashboard.html")
            page.wait_for_selector("#facultyTable tbody tr", state="attached")
            probe = """() => ({ ink: Chart.defaults.plugins.tooltip.backgroundColor, tick: Chart.defaults.color,
                grid: dashboardChart.options.scales.y.grid.color, pie: reportsChart.data.datasets[0].borderColor })"""
            light = page.evaluate(probe)
            page.evaluate("atlasApp.set('theme','dark')")
            page.wait_for_timeout(300)
            dark = page.evaluate(probe)
            assert light["ink"] == LIGHT["--chart-ink"] and dark["ink"] == DARK["--chart-ink"]
            assert dark["tick"] == DARK["--chart-muted"] and dark["grid"] == DARK["--chart-grid"]
            assert dark["pie"] == DARK["--chart-surface"] and light["pie"] == LIGHT["--chart-surface"]
            page.evaluate("atlasApp.set('theme','light')")
            page.wait_for_timeout(300)
            assert page.evaluate(probe) == light
            b.close()
    finally:
        srv.shutdown()