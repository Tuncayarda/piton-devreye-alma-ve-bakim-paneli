#!/usr/bin/env python3
"""Capture the figures used by the two guides, from tools/docshots/server.py.

Every shot is taken at 1440x900 with a device pixel ratio of 2 — the
application window's own size (app.py WIDTH/HEIGHT) at print resolution, so a
figure is 2880x1800 and stays sharp on a page.

The point of a script rather than a person with a screenshot key is that the
figures are REPRODUCIBLE: the demo readings are deterministic (see
server.py), the states each screen is put into are written down here, and a
recapture six months from now differs only where the product differs.

Needs Playwright and a Google Chrome installed on this machine:

    python3 -m pip install playwright
    python3 tools/docshots/server.py &            # in another terminal
    python3 tools/docshots/capture.py             # all figures
    python3 tools/docshots/capture.py 10-switch-genel fig5-contextmenu

Output goes to tools/docshots/out/ and is copied into docs/user-guide-assets/
and docs/dev-guide-assets/ only when it has been looked at.
"""
from __future__ import annotations

from pathlib import Path
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
URL = "http://127.0.0.1:8845/"
VIEWPORT = {"width": 1440, "height": 900}

ONLY = []
for argument in sys.argv[1:]:
    if argument.startswith("http"):
        URL = argument
    else:
        ONLY.append(argument)
OUT.mkdir(exist_ok=True)


def want(*names) -> bool:
    return not ONLY or any(name in ONLY for name in names)


def shot(page, name: str, clip=None) -> None:
    settle(page)
    page.screenshot(path=OUT / f"{name}.png", clip=clip)
    print("  ✓", name)


def scanning(page) -> bool:
    """Does the top bar say a scan is in progress?"""
    try:
        return "Taranıyor" in page.locator("header").first.inner_text()
    except Exception:                # mid-redraw; assume yes and ask again
        return True


def drop_error_toasts(page) -> None:
    """Read out any error toast and close it.

    An error toast is sticky BY DESIGN: `showError` passes duration 0
    (components/toast.js) because a message about something that did not
    happen is often the only copy there is. Waiting for one to clear is
    therefore waiting forever — the full limit below, per figure — and it
    lands in the figure regardless. So it is printed, which is the part
    worth keeping, and then dismissed.
    """
    for _ in range(4):
        errors = page.locator('.toast-item[data-kind="error"]')
        if not errors.count():
            return
        item = errors.first
        try:
            print("  ! error toast:",
                  item.locator(".toast-text").inner_text()[:110])
            item.locator(".toast-close").click()
        except Exception:            # gone between the count and the click
            return
        page.wait_for_timeout(300)


def settle(page, limit_ms: int = 30000) -> None:
    """Wait until nothing transient is on screen.

    Two things otherwise end up in a figure: a toast ("signed in to
    127.0.0.1") sitting on top of the switch faceplate, and the top bar
    reading "Scanning…" because entering a screen started a round. Toasts
    clear themselves after 4.2 s (components/toast.js) — except the error
    ones, which are dismissed above.
    """
    waited = 0
    while waited < limit_ms:
        drop_error_toasts(page)
        if not (page.locator(".toast-item").count() or scanning(page)):
            break
        page.wait_for_timeout(500)
        waited += 500
    else:
        # THE FIGURE IS STILL TAKEN — a run that stops here produces nothing
        # — but no longer silently. Every figure of a run whose top bar was
        # stuck on "Taranıyor…" carried it into the guides while eighteen ✓
        # marks said the run had gone well.
        print(f"  ! nothing settled in {limit_ms // 1000} s; the figure has "
              f"{'a scan running' if scanning(page) else 'a toast'} in it")
    page.wait_for_timeout(500)


def side(page, label: str) -> None:
    close_dialog(page)
    page.get_by_role("button", name=label, exact=True).first.click()
    page.wait_for_timeout(1400)


def close_dialog(page) -> None:
    """Escape is not enough when focus never entered the dialog: the backdrop
    stays and swallows every later click, which is how one figure used to
    take the rest of the run down with it."""
    backdrop = page.locator(".backdrop")
    if not backdrop.count():
        return
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    if backdrop.count():
        backdrop.first.click(position={"x": 6, "y": 6})
        page.wait_for_timeout(400)


def optab(page, view: str) -> None:
    page.locator(f'.action-tab[data-view="{view}"]').first.click()
    page.wait_for_timeout(1400)


def ensure_admin(page) -> None:
    """Admin mode is SERVER state and outlives the page.

    The remote-session figure steps out of it, so the next run of this script
    would start in field mode — with no Switch and no ADB screen in the rail,
    and a sidebar click that waits thirty seconds for a button that is not
    there.
    """
    enter = page.get_by_role("button", name="Admin moduna geç")
    if enter.count():
        enter.first.click()
        page.wait_for_timeout(2000)
        print("  admin mode re-entered")


def scan(page) -> None:
    """A full scan, so every screen has something to draw."""
    print("scan…")
    page.get_by_role("button", name="Şimdi tara").first.click()
    for _ in range(150):
        page.wait_for_timeout(500)
        if not scanning(page):
            break
    else:
        # "Scanning…" IS CLIENT STATE (`state.scanRunning`, app.js), set when
        # the button is pressed and cleared only by the state fetch that the
        # job loop makes while a job is running. Miss that one fetch and the
        # label never comes back, with the server long since idle — and then
        # every figure in the run carries "Taranıyor…" in its top bar and
        # settle() below pays its full limit waiting for a scan that ended
        # minutes ago. A reload refetches the state, which is the whole
        # repair. It is safe here and nowhere else: this runs before the
        # first figure, while the panel is still on the screen it opens on.
        print("   the top bar is still scanning; reloading the page")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        if scanning(page):
            print("   ! still scanning after the reload — the server really "
                  "is busy, or a scan job is stuck")
    page.wait_for_timeout(2000)
    print("  ", page.locator("h1").first.inner_text().replace("\n", " · "))


def connect_switch(page) -> bool:
    """Find the fake switch on loopback and open it."""
    side(page, "Switch Yönetim")
    page.locator(".switch-range-field").first.fill("127.0.0.1")
    page.select_option(".switch-prefix-field", "24")
    page.get_by_role("button", name="Tara", exact=True).first.click()
    for _ in range(120):
        page.wait_for_timeout(500)
        if page.locator(".switch-row").count():
            break
    page.wait_for_timeout(1200)
    found = page.locator(".switch-row").count()
    print("   switches found:", found)
    if not found:
        return False
    if page.locator("#v-switch .pm-port").count():
        return True          # already open from an earlier run
    creds = page.locator(".switch-credential")
    if creds.count() >= 2:
        creds.nth(0).fill("admin")
        creds.nth(1).fill("123")
        # Enter in the password box is what the row itself wires to
        # `connectSwitch` (views/switch/discovery.js). Clicking the button
        # instead loses the race with the discovery poll's redraw: Playwright
        # waits for the element to be stable and it never is.
        creds.nth(1).press("Enter")
    else:
        # BY CSS, not by role. The row is a div carrying aria-selected, and
        # Chrome drops its children out of the accessibility tree because of
        # it — `get_by_role("button", name="Bağlan")` matches nothing at all,
        # so the click waited out its full timeout every time the switch was
        # already signed in from an earlier run.
        page.locator("#v-switch .switch-row button").last.click(force=True)
    for _ in range(60):
        page.wait_for_timeout(500)
        if page.locator("#v-switch .pm-port").count():
            break
    page.wait_for_timeout(1500)
    return page.locator("#v-switch .pm-port").count() > 0


ENLARGE = """(portId) => {
  const source = document.querySelector(
    `#v-switch .pm-port[data-port-id="${portId}"]`);
  if (!source) return false;
  const stage = document.createElement('div');
  stage.id = '__figstage';
  // THE WHOLE BUTTON is cloned, not the bare svg. Every line and pin of the
  // connector is coloured by a `.pm-port .shell` / `.pm-port .pin` rule
  // (static/css/switch.css); an svg lifted out of that class matches none of
  // them and comes out a black disc. The size is asked for the way the
  // stylesheet asks for it, through --pm-svg, so the drawing stays vector.
  stage.style.cssText = 'position:fixed;inset:0;display:flex;' +
    'align-items:center;justify-content:center;background:#0b1017;' +
    'z-index:99999;--pm-svg:400px;--pm-label:32px';
  const clone = source.cloneNode(true);
  clone.style.width = '480px';
  stage.appendChild(clone);
  document.body.appendChild(stage);
  return true;
}"""


def connector(page, port_id: str, path):
    """One connector on its own, drawn large.

    The SVG is cloned onto a full-window stage and given a real size rather
    than the screenshot being enlarged afterwards: the faceplate draws
    vectors, and a vector asked for 460 pixels is sharp where a 60-pixel
    capture blown up six times is not.
    """
    if not page.evaluate(ENLARGE, port_id):
        return False
    page.wait_for_timeout(300)
    # The CLONE, not the stage: the stage fills the window and most of
    # it is background, which the composite below then has to pad around.
    page.locator("#__figstage .pm-port").screenshot(path=str(path))
    page.evaluate("() => document.getElementById('__figstage').remove()")
    return True


def front_panel_figure(page):
    """The faceplate, with a PoE and an uplink connector enlarged below it."""
    if not page.locator("#v-switch .pm-grid").count():
        print("  ! fig3-frontpanel: no .pm-grid on the page")
        return
    settle(page)
    # A PAGE screenshot with a clip, not an element screenshot: the switch
    # screen polls and redraws, so Playwright's "wait until the element is
    # stable" never comes true and the element capture times out. A clip is
    # measured once and taken immediately.
    #
    # SCOPED TO THE SWITCH VIEW. The IP screen draws faceplates too and its
    # container sits earlier in the document; hidden, it measures zero, and a
    # bare '.pm-grid' selector picked that one.
    #
    # The faceplate is scrolled into the middle of the window first and then
    # measured. The page's scroller is #content, not the window, so
    # `full_page` reaches nothing: a clip taken from an unscrolled rect cut
    # the bottom two rows off and caught the status bar instead.
    page.evaluate("""() => document.querySelector('#v-switch .pm-grid')
      .scrollIntoView({block: 'center'})""")
    page.wait_for_timeout(600)
    box = page.evaluate("""() => {
      const rect = document.querySelector('#v-switch .pm-grid')
        .getBoundingClientRect();
      return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
    }""")
    if not box or box["width"] < 10 or box["height"] < 10:
        print("  ! fig3-frontpanel: the faceplate has no size yet")
        return
    pad = 20
    box = {"x": max(0, box["x"] - pad), "y": max(0, box["y"] - pad),
           "width": min(VIEWPORT["width"], box["width"] + 2 * pad),
           "height": min(VIEWPORT["height"] - max(0, box["y"] - pad),
                         box["height"] + 2 * pad)}
    top = OUT / "_fig3-panel.png"
    page.screenshot(path=str(top), clip=box)
    poe = OUT / "_fig3-poe.png"
    uplink = OUT / "_fig3-uplink.png"
    made = (connector(page, "3", poe) and connector(page, "27", uplink))
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if not made or Image is None:
        top.replace(OUT / "fig3-frontpanel.png")
        print("  ✓ fig3-frontpanel (faceplate only)")
        return

    face = Image.open(top)
    left, right = Image.open(poe), Image.open(uplink)
    gap = 40
    height = max(left.height, right.height)
    width = face.width
    half = (width - gap) // 2
    left = left.resize((half, int(left.height * half / left.width)))
    right = right.resize((half, int(right.height * half / right.width)))
    height = max(left.height, right.height)
    canvas = Image.new("RGB", (width, face.height + gap + height), "#0b1017")
    canvas.paste(face, (0, 0))
    canvas.paste(left, (0, face.height + gap))
    canvas.paste(right, (width - half, face.height + gap))
    canvas.save(OUT / "fig3-frontpanel.png")
    for scratch in (top, poe, uplink):
        scratch.unlink(missing_ok=True)
    print("  ✓ fig3-frontpanel")


def step(names, body):
    """One figure group. A group that fails says so and the run continues —
    a broken selector must not cost the other fifteen figures."""
    if not want(*names):
        return
    try:
        body()
    except Exception as error:      # a capture run, not the panel
        print(f"  ! {names[0]}: {type(error).__name__}: "
              f"{str(error).splitlines()[0][:120]}")


def panel_is_up() -> bool:
    """A plain GET before Chrome is started.

    Without it, a run with no server behind it fails as a Playwright stack
    trace about ERR_CONNECTION_REFUSED thirty seconds in — which reads as a
    broken capture rather than the one-line mistake it is.
    """
    try:
        with urllib.request.urlopen(URL, timeout=5) as answer:
            return answer.status == 200
    except (OSError, urllib.error.URLError):
        return False


def main() -> int:
    if not panel_is_up():
        print(f"nothing answering at {URL} — start the demo server first:\n"
              f"    python3 tools/docshots/server.py")
        return 2
    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=2,
                                locale="tr-TR")
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1500)
        ensure_admin(page)
        scan(page)

        # ── the operator's screens, in the user guide's order ─────────
        def overview():
            side(page, "Genel bakış")
            shot(page, "01-genel-bakis")
            shot(page, "fig2-overview")

        def devices():
            side(page, "Cihazlar")
            shot(page, "02-cihazlar")

        def operations(view, name):
            def body():
                side(page, "İşlemler")
                optab(page, view)
                shot(page, name)
            return body

        def plain(label, name):
            def body():
                side(page, label)
                shot(page, name)
            return body

        def project_dialog():
            side(page, "Genel bakış")
            page.locator("header button").first.click()
            page.wait_for_timeout(1200)
            shot(page, "09-proje-secimi")
            close_dialog(page)

        def remote_session():
            # The remote-session button is the FIELD half of the top bar: in
            # admin mode its place is taken by "leave admin mode". So this
            # figure is captured last, after stepping out of admin.
            side(page, "Genel bakış")
            leave = page.get_by_role("button", name="Admin modundan çık")
            if leave.count():
                leave.first.click()
                page.wait_for_timeout(2000)
            page.get_by_role("button", name="Uzaktan oturum").first.click()
            page.wait_for_timeout(3500)
            shot(page, "12-uzaktan-oturum")
            close_dialog(page)

        def switch_screen():
            opened = connect_switch(page)
            shot(page, "fig4-switch")
            if not opened:
                print("  ! switch never opened; skipping its figures")
                return
            shot(page, "10-switch-genel")
            front_panel_figure(page)
            # Three ports selected, then the menu that applies to all three
            # at once — which is the point of the figure.
            for index, port in enumerate(("3", "7", "11")):
                cell = page.locator(f'#v-switch .pm-port[data-port-id="{port}"]')
                if not cell.count():
                    continue
                cell.first.click(
                    modifiers=[] if index == 0 else ["ControlOrMeta"])
                page.wait_for_timeout(200)
            page.wait_for_timeout(600)
            target = page.locator('#v-switch .pm-port[data-port-id="11"]')
            if target.count():
                target.first.click(button="right")
                page.wait_for_timeout(900)
            shot(page, "fig5-contextmenu")
            page.keyboard.press("Escape")
            page.wait_for_timeout(400)

        def adb_screen():
            side(page, "ADB araçları")
            page.wait_for_timeout(2500)
            ticks = page.locator(".adb-tick")
            for index in range(min(3, ticks.count())):
                ticks.nth(index).click()
                page.wait_for_timeout(250)
            # THE APPLICATION SEARCH, not the address box beside it. Reaching
            # for the first text input in the column typed the keyword into
            # the "add a device" field and the figure came back carrying a
            # red "not a valid IPv4 address".
            search = page.locator(".adb-packages .search-input")
            if search.count():
                search.first.fill("com.piton")
                page.locator(".adb-search button[type='submit']").first.click()
                page.wait_for_timeout(3500)
            shot(page, "11-adb-genel")
            shot(page, "fig6-adb")

        def architecture():
            """Not a screenshot: the call-chain diagram, drawn in an SVG that
            lives beside the figure it produces."""
            source = (HERE.parent.parent / "docs" / "dev-guide-assets"
                      / "fig1-architecture.src.html")
            if not source.is_file():
                print("  ! fig1-architecture: no source html")
                return
            sheet = browser.new_page(viewport={"width": 1200, "height": 1000},
                                     device_scale_factor=2)
            sheet.goto(source.as_uri(), wait_until="load")
            sheet.wait_for_timeout(600)
            sheet.locator("svg").screenshot(
                path=str(OUT / "fig1-architecture.png"))
            sheet.close()
            print("  ✓ fig1-architecture")

        step(("fig1-architecture",), architecture)
        step(("01-genel-bakis", "fig2-overview"), overview)
        step(("02-cihazlar",), devices)
        step(("03-ip-atama",), operations("ip", "03-ip-atama"))
        step(("04-cihaz-ayarlari",),
             operations("config", "04-cihaz-ayarlari"))
        step(("05-yazilim",), operations("firmware", "05-yazilim"))
        step(("06-ag",), plain("Ağ", "06-ag"))
        step(("07-dogrulama-rapor",),
             plain("Doğrulama ve raporlar", "07-dogrulama-rapor"))
        step(("08-gecmis",), plain("Geçmiş", "08-gecmis"))
        step(("09-proje-secimi",), project_dialog)
        step(("10-switch-genel", "fig3-frontpanel", "fig4-switch",
              "fig5-contextmenu"), switch_screen)
        step(("11-adb-genel", "fig6-adb"), adb_screen)
        # Last: it leaves admin mode, and the two screens above only exist
        # inside it.
        step(("12-uzaktan-oturum",), remote_session)

        browser.close()
    print("\nout ->", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
