from pathlib import Path

from assertpy2 import assert_that
from tools.screenshots import sources

_ASSETS = Path(__file__).parent.parent / "docs" / "assets"


def test_every_screenshot_still_shows_what_the_tool_produces():
    # A screenshot is an image, so no test can read what it says. The text it was rendered FROM is committed
    # beside it and pinned here instead: change a diagnostic and this fails, rather than leaving a stale
    # picture in the README - which is precisely what the coercion shot became when `help:` turned into
    # `note:`, with every other test still green. `python tools/screenshots.py` rewrites the text and the
    # image in one pass, so the two cannot drift apart. Byte-comparing the PNGs in CI would not work: the
    # font stack resolves differently on Linux than on Windows.
    for name, text in sources().items():
        stored = (_ASSETS / f"{name}.txt").read_text(encoding="utf-8")
        assert_that(stored).described_as(f"docs/assets/{name}.png is stale: run `python tools/screenshots.py`")
        assert_that(stored).is_equal_to(text)
