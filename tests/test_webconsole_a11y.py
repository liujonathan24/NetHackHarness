"""Accessibility regression tests for the web console pages.

Renders each page via Flask's test client and asserts the structural
accessibility invariants the UI relies on, so they can't silently regress:

  * <html lang> + responsive viewport
  * a skip link whose target (#main-content) exists
  * exactly one <main id="main-content"> landmark per page
  * a labelled primary <nav>
  * no positive tabindex (which would break natural focus order)
  * no duplicate ids (which break label/ARIA associations)
  * an inline favicon (no /favicon.ico 404)
  * every static <input> has an accessible name (label[for], aria-label,
    or aria-labelledby), and every aria-labelledby target exists

Pure template rendering — does NOT depend on the C engine; exercises the page
routes via app.test_client() (tools is importable via tests/conftest.py).
"""
from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser

import pytest

import tools.play_server as ps

# Browser navigations send Accept: text/html — needed so /traces returns the
# Tracer page rather than the JSON rollout list.
PAGES = ["/", "/map", "/obs", "/traces"]
_HTML = {"Accept": "text/html"}


@pytest.fixture()
def client():
    ps.app.config["TESTING"] = True
    return ps.app.test_client()


def _html(client, path: str) -> str:
    r = client.get(path, headers=_HTML)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    return r.get_data(as_text=True)


class _Collector(HTMLParser):
    """Collect ids, inputs (with their a11y attrs), and label[for] targets."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.inputs: list[dict] = []
        self.label_for: set[str] = set()
        self.labelledby: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])
        if tag == "input":
            self.inputs.append(a)
            if a.get("aria-labelledby"):
                self.labelledby.extend(a["aria-labelledby"].split())


def _collect(html: str) -> _Collector:
    c = _Collector()
    c.feed(html)
    return c


@pytest.mark.parametrize("path", PAGES)
def test_lang_and_viewport(client, path):
    html = _html(client, path)
    assert '<html lang="en">' in html
    assert 'name="viewport"' in html and "width=device-width" in html


@pytest.mark.parametrize("path", PAGES)
def test_skip_link_targets_existing_main(client, path):
    html = _html(client, path)
    assert 'class="skip-link"' in html and 'href="#main-content"' in html
    assert 'id="main-content"' in html  # the skip target exists
    # the target must be focusable (tabindex=-1) so the skip link actually moves
    # focus into it, not just scroll (WCAG 2.4.1)
    main = re.search(r"<main[^>]*\bid=\"main-content\"[^>]*>", html)
    assert main and 'tabindex="-1"' in main.group(0), "skip target must be focusable"


@pytest.mark.parametrize("path", PAGES)
def test_exactly_one_main_landmark(client, path):
    html = _html(client, path)
    assert html.count("<main") == 1, "each page must have exactly one main landmark"
    assert html.count('id="main-content"') == 1


@pytest.mark.parametrize("path", PAGES)
def test_primary_nav_is_labelled(client, path):
    html = _html(client, path)
    assert '<nav id="nav" aria-label="Primary">' in html


@pytest.mark.parametrize("path", PAGES)
def test_no_positive_tabindex(client, path):
    html = _html(client, path)
    assert not re.search(r'tabindex="[1-9][0-9]*"', html), "positive tabindex breaks focus order"


@pytest.mark.parametrize("path", PAGES)
def test_no_duplicate_ids(client, path):
    ids = _collect(_html(client, path)).ids
    dupes = [i for i, n in Counter(ids).items() if n > 1]
    assert not dupes, f"duplicate ids on {path}: {dupes}"


@pytest.mark.parametrize("path", PAGES)
def test_inline_favicon(client, path):
    html = _html(client, path)
    assert 'rel="icon"' in html, "inline favicon avoids a /favicon.ico 404"
    assert 'href="data:image/svg+xml' in html


@pytest.mark.parametrize("path", PAGES)
def test_static_inputs_have_accessible_names(client, path):
    c = _collect(_html(client, path))
    for inp in c.inputs:
        has_name = (
            inp.get("aria-label")
            or inp.get("aria-labelledby")
            or (inp.get("id") and inp["id"] in c.label_for)
        )
        assert has_name, f"input without an accessible name on {path}: {inp}"


@pytest.mark.parametrize("path", PAGES)
def test_labelledby_targets_exist(client, path):
    c = _collect(_html(client, path))
    ids = set(c.ids)
    for ref in c.labelledby:
        assert ref in ids, f"aria-labelledby points at missing id {ref!r} on {path}"


def test_obs_dash_css_not_html_escaped(client):
    """The obs page injects the trusted rollout_view dashboard CSS via Jinja.
    It must be rendered |safe: that CSS has single quotes
    (font-family:'Press Start 2P'), and Jinja autoescape would turn them into
    &#39;. HTML character references are NOT decoded inside a <style> element,
    so the CSS parser would see literal &#39;, drop the declaration, and the
    chart titles/KPIs would silently lose their retro font."""
    html = _html(client, "/obs")
    assert "font-family:&#39;" not in html and "&#x27;" not in html, \
        "dash_css single-quotes were HTML-escaped inside <style> (drop |safe?)"
    assert "font-family:'Press Start 2P'" in html, \
        "dashboard CSS not injected intact into the obs page"


def test_landing_gif_gallery_has_hide_control(client):
    """The landing demo gallery auto-plays looping GIFs; WCAG 2.2.2 (Level A)
    needs a pause/stop/hide mechanism. Assert a toggle exists, is a real button,
    and its aria-controls points at the gallery container it shows/hides."""
    html = _html(client, "/")
    c = _collect(html)
    assert 'id="gif-toggle"' in html, "no gallery hide/show control on landing"
    assert 'aria-controls="demos"' in html, "toggle missing aria-controls"
    assert 'aria-expanded=' in html, "toggle missing aria-expanded state"
    assert "demos" in set(c.ids), "aria-controls target #demos does not exist"
