"""Check that relative links in Markdown files point to files that exist."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def markdown_files():
    return [p for p in ROOT.rglob("*.md") if ".git" not in p.parts]


def test_relative_links_resolve():
    broken = []
    for md in markdown_files():
        for target in LINK.findall(md.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if path and not (md.parent / path).exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    assert not broken, "Broken relative links:\n" + "\n".join(broken)
