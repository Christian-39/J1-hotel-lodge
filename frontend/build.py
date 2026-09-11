#!/usr/bin/env python3
"""J-ONE frontend builder.

The public header / footer / mobile nav live ONCE in /components. The build
inlines them into every page author-time, so the deployed site is fully
self-contained with zero runtime component-request overhead — satisfying the
spec's "optimize component loading" rule while keeping one source of truth.

Every public page contains these markers, replaced at build time:
    <!--HEADER-->   → components/header.html
    <!--FOOTER-->   → components/footer.html
    <!--MOBILE-->   → components/mobile-nav.html

Usage:  python3 build.py
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent

HEADER = (ROOT / "components/header.html").read_text(encoding="utf-8")
FOOTER = (ROOT / "components/footer.html").read_text(encoding="utf-8")
MOBILE = (ROOT / "components/mobile-nav.html").read_text(encoding="utf-8")

THEME_BOOT = (
    '<script>(function(){var t;try{t=JSON.parse(localStorage.getItem("jone.theme"))}'
    'catch(e){}if(t!=="dark"&&t!=="light"){t=(window.matchMedia&&'
    'window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light"}'
    'document.documentElement.setAttribute("data-theme",t);})();</script>'
)

# Matches any prior injected theme-boot snippet (new setAttribute-only form or the
# old classList.remove form) so re-runs are idempotent, and strips the old
# preload-theme class add so it never hides the body.
_THEME_STRIP = re.compile(
    r'<script>\(function\(\)\{var t;try\{t=JSON\.parse\(localStorage\.getItem\("jone\.theme"\)\)\}'
    r'catch\(e\)\{\}if\(t!=="dark"&&t!=="light"\)\{t=\(window\.matchMedia&&'
    r'window\.matchMedia\("\(prefers-color-scheme: dark\)"\)\.matches\)\?"dark":"light"\}'
    r'document\.documentElement\.setAttribute\("data-theme",t\);.*?\}\)\(\);</script>',
    re.S,
)
_PRELOAD_STRIP = re.compile(
    r'<script>document\.documentElement\.classList\.add\("preload-theme"\);</script>',
)

JS_BLOCK = """<script src="js/config.js"></script>
<script src="js/utils.js"></script>
<script src="js/icons.js"></script>
<script src="js/api.js"></script>
<script src="js/theme.js"></script>
<script src="js/ui.js"></script>
<script src="js/hotel-data.js"></script>
<script src="js/navigation.js"></script>
<script src="js/contact.js"></script>
<script>JONE.ui.initChrome(); JONE.nav.init();</script>"""

# name -> absolute root-relative path expected to exist (mirrors spec structure)
PUBLIC_PAGES = [
    "index.html", "about.html", "rooms.html", "room-details.html",
    "facilities.html", "gallery.html", "offers.html",
    "booking.html", "booking-review.html", "booking-confirmation.html",
    "contact.html", "policies.html", "privacy.html", "terms.html",
    "cancellation-policy.html", "refund-policy.html",
    "login.html", "my-bookings.html", "404.html", "403.html", "500.html",
]


def build(path):
    f = ROOT / path
    if not f.exists():
        return False
    raw = f.read_text(encoding="utf-8")

    # --- Re-inject shared chrome idempotently -------------------------------
    # After the first build the page has chrome baked in and no <!--HEADER-->
    # markers remain, so edits to components/ wouldn't propagate. We instead
    # anchor on stable boundaries and swap the chrome region each run. Only do
    # this for pages that carry the public chrome (have a site footer).
    if 'class="site-footer"' in raw:
        # Header region: everything between <body> and <main id="main">.
        def repl_head(m):
            return m.group(1) + "\n" + HEADER + "\n" + m.group(3)
        raw = re.sub(r'(<body>)(.*?)(<main id="main">)', repl_head, raw, count=1, flags=re.S)
        # Footer + mobile region: everything between </main> and <script src="js/config.js">.
        # group(3) is the anchor <script src="js/config.js"> — it MUST be kept or
        # config.js (and therefore window.APP_CONFIG / JONE.APP_CONFIG) is dropped.
        def repl_foot(m):
            return m.group(1) + "\n" + FOOTER + "\n" + MOBILE + "\n" + m.group(3)
        raw = re.sub(r'(</main>)(.*?)(<script src="js/config\.js">)', repl_foot, raw, count=1, flags=re.S)

    # Also handle freshly-authored pages that still use markers.
    raw = raw.replace("<!--HEADER-->", HEADER)
    raw = raw.replace("<!--FOOTER-->", FOOTER)
    raw = raw.replace("<!--MOBILE-->", MOBILE)

    # Idempotent theme boot: drop any prior injected snippets with a literal
    # string replace, then inject ONE snippet inside <head> before first paint.
    for _ in range(8):
        if THEME_BOOT not in raw:
            break
        raw = raw.replace(THEME_BOOT, "")
    old_boot = (
        '<script>(function(){var t;try{t=JSON.parse(localStorage.getItem("jone.theme"))}'
        'catch(e){}if(t!=="dark"&&t!=="light"){t=(window.matchMedia&&'
        'window.matchMedia("(prefers-color-scheme: dark)").matches)?"dark":"light"}'
        'document.documentElement.setAttribute("data-theme",t);'
        'document.documentElement.classList.remove("preload-theme");})();</script>'
    )
    raw = raw.replace(old_boot, "")
    raw = _PRELOAD_STRIP.sub("", raw)
    if '<script>document.documentElement.classList.add("preload-theme");</script>' not in raw:
        raw = re.sub(r'(<link rel="stylesheet" href="css/main\.css">)', r'\1' + "\n" + THEME_BOOT, raw, count=1)
    raw = re.sub(r"<!--JS-->", JS_BLOCK, raw)
    f.write_text(raw, encoding="utf-8")
    return True


def main():
    built = []
    for p in PUBLIC_PAGES:
        if build(p):
            built.append(p)
    print("Built %d pages: %s" % (len(built), ", ".join(built)))


if __name__ == "__main__":
    main()
