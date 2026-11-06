#!/usr/bin/env python3
"""Check every URL and local image referenced by README.md.

Why: a root-relative or missing asset in a profile README renders as a broken
image on GitHub, and a dead external badge makes the page look unmaintained.
This checker is the executable form of the README's maintenance step.

Usage:
    python tools/check_links.py                 # check README.md in the repo root
    python tools/check_links.py --repo-root . --json
    python tools/check_links.py --skip-external # only local assets and anchors

Exit codes: 0 clean, 1 broken references, 2 usage/environment error.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

USER_AGENT = "paulmann-profile-link-check/1.0"
MD_LINK = re.compile(r"!?\[[^\]]*\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_ATTR = re.compile(r"""(?:src|href)\s*=\s*["'](?P<url>[^"']+)["']""")
ANCHOR = re.compile(r"^#(.+)$")


def strip_code(markdown: str) -> str:
    """Remove fenced code blocks so their contents are not treated as links."""
    out, fence = [], None
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = None if fence == marker else (fence or marker)
            continue
        if fence is None:
            out.append(line)
    return "\n".join(out)


def references(markdown: str) -> list[str]:
    text = strip_code(markdown)
    found: list[str] = []
    for match in MD_LINK.finditer(text):
        found.append(match.group("url"))
    for match in HTML_ATTR.finditer(text):
        found.append(match.group("url"))
    return list(dict.fromkeys(found))


def heading_anchors(markdown: str) -> set[str]:
    """Approximate GitHub heading slugs: drop punctuation, keep spaces as hyphens.

    Emoji are punctuation and disappear, leaving the space that follows them as
    a leading hyphen (``## 👋 About me`` -> ``#-about-me``); a removed ``&``
    leaves two adjacent hyphens (``## 🤖 AI & LLM`` -> ``#-ai--llm``). Spaces
    are therefore replaced, never stripped or collapsed.
    """
    anchors: set[str] = set()
    for line in markdown.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        if not title:
            continue
        slug = title.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = slug.replace(" ", "-")
        anchors.add(slug)
    return anchors


def check_url(url: str, timeout: float) -> tuple[bool, str]:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 400, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405, 406):  # some hosts refuse HEAD; retry with GET
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return 200 <= response.status < 400, f"HTTP {response.status} (GET)"
            except Exception as exc2:  # noqa: BLE001 - report, do not crash
                return False, f"HTTP {exc.code} then {exc2}"
        return False, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - network failures are findings
        # Some image hosts (capsule-render) complete a TLS handshake with
        # browsers and curl but not with Python's OpenSSL; confirm with curl
        # before reporting a defect.
        fallback = check_url_with_curl(url, timeout)
        if fallback is not None:
            return fallback
        return False, f"{type(exc).__name__}: {exc}"


def check_url_with_curl(url: str, timeout: float) -> tuple[bool, str] | None:
    """Fallback probe through curl.exe; returns None when curl is unavailable."""
    try:
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-o",
                os.devnull,
                "-w",
                "%{http_code}",
                "--max-time",
                str(int(timeout)),
                "-A",
                USER_AGENT,
                url,
            ],
            capture_output=True,
            text=True,
            timeout=timeout + 10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    code = result.stdout.strip()
    if not code.isdigit():
        return None
    return 200 <= int(code) < 400, f"HTTP {code} (curl fallback)"


def check_local(root: pathlib.Path, url: str) -> tuple[bool, str]:
    path = (root / url).resolve()
    if not path.is_file():
        return False, "missing file"
    size = path.stat().st_size
    if size == 0:
        return False, "empty file"
    if path.suffix.lower() == ".svg":
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            return False, f"invalid SVG XML: {exc}"
        return True, f"{size} bytes, SVG parses"
    return True, f"{size} bytes"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="repository root (default: current directory)")
    parser.add_argument("--readme", default="README.md", help="README file relative to the root")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--skip-external", action="store_true", help="do not make network requests")
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args()

    root = pathlib.Path(args.repo_root).resolve()
    readme_path = root / args.readme
    if not readme_path.is_file():
        print(f"error: {readme_path} not found", file=sys.stderr)
        return 2

    markdown = readme_path.read_text(encoding="utf-8")
    anchors = heading_anchors(markdown)

    findings: list[dict] = []
    checked = 0
    for url in references(markdown):
        if url.startswith(("mailto:", "tel:")):
            continue
        if url.startswith("#"):
            target = url[1:]
            ok = target == "" or target in anchors
            findings.append({"ref": url, "kind": "anchor", "ok": ok, "detail": "heading found" if ok else "no such heading"})
            checked += 1
            continue
        if url.startswith(("http://", "https://")):
            if args.skip_external:
                continue
            ok, detail = check_url(url, args.timeout)
            findings.append({"ref": url, "kind": "external", "ok": ok, "detail": detail})
            checked += 1
            continue
        ok, detail = check_local(root, url)
        findings.append({"ref": url, "kind": "local", "ok": ok, "detail": detail})
        checked += 1

    failed = [item for item in findings if not item["ok"]]
    if args.json:
        print(json.dumps({"checked": checked, "failed": failed, "findings": findings}, indent=2))
    else:
        for item in findings:
            mark = "OK  " if item["ok"] else "FAIL"
            print(f"{mark} {item['kind']:<8} {item['ref']}  -> {item['detail']}")
        print(f"\n{checked} references checked, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
