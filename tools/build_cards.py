#!/usr/bin/env python3
"""Rebuild the profile stat cards from the live GitHub API.

Outputs (self-contained SVG, no external fonts or images):
    assets/cards/langs.svg    top languages by code volume
    assets/cards/domains.svg  public repositories grouped by project family

Data source: the GitHub CLI (`gh api`), authenticated as the profile owner.
No third-party Python packages are used.

Usage:
    python tools/build_cards.py                # measure and print, write nothing
    python tools/build_cards.py --write        # rewrite the two cards
    python tools/build_cards.py --write --date 2026-11-07
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

OWNER = "paulmann"
ROOT = pathlib.Path(__file__).resolve().parent.parent
CARDS = ROOT / "assets" / "cards"

# Curated project families. Every public, non-fork repository of the profile
# belongs to exactly one family; the card and the README navigator share this
# grouping, so a new repository is added here once and both stay consistent.
DOMAINS: list[tuple[str, list[str]]] = [
    (
        "Windows & RDP security",
        [
            "Windows-11-25H2-Update-Script",
            "RDP-Diagnostic-Tool",
            "1st-Remote-Session-Manager-Pro",
            "1st-RDPMon",
            "RDPAudit",
            "Get-Windows-Security-Events-By-IP",
            "Windows-LogOff",
            "windows-show-all-tray-icons",
            "Windows-Cleaner-and-Optimizer",
            "Clear-TempFolders",
            "Print-Spooler-Queue-Cleanup",
            "Import-CaCertificates",
        ],
    ),
    (
        "AI & LLM tooling",
        [
            "RAGRAF",
            "AI-Consensus",
            "RevoAp",
            "ctf-collect-to-file",
            "1st-Launch-Projects-Code-from-LLM-Responses-in-Markdown-into-Actual-File-Structures",
            "sr-search-replace",
            "github-agent",
            "github-wiki-llm-writer",
            "agent-prompt-kit",
        ],
    ),
    (
        "Web, PHP & databases",
        [
            "HTML.PHP",
            "IIS-PHP-FastCGI-AutoDeploy",
            "Bash_WP-CLI_Update",
            "woocommerce-1c-data-cleaner",
            "BAS-IP",
            "Clean_BOM_Senior",
            "pg-encoding-migrator",
            "regru-control",
            "fornex-control",
        ],
    ),
    (
        "Email infrastructure",
        [
            "hMailServer-Spam-Provisioner",
            "SpamAssassin-Windows-PS7",
            "PowerShell_Export-hMailServerData",
            "hMailServer-External-Antivirus",
            "hmailserver-kaspersky-cleanup",
            "hmailserver-clamav-cleanup",
            "Clean-RoundCube-Cache-PostgreSQL-Windows",
        ],
    ),
    (
        "Linux, network & security",
        [
            "sata-spindown-guard",
            "cert-unifier",
            "mikrotik-doh-failover",
            "CVE-2026-111497",
        ],
    ),
    (
        "Spam & abuse defence",
        [
            "Contact-Form-7-LLM-Spam-Checker",
            "PHP-Form-Spam-Checker",
            "Fail2Ban_AbuseIPDB",
        ],
    ),
    ("Documentation & content", ["MD.Viewer", "MD.Scribe"]),
    (
        "Packaging",
        ["homebrew-github-agent-cli", "scoop-github-agent-cli"],
    ),
]

# Linguist colours, lightened where the original is unreadable on #161b22.
LANG_COLORS = {
    "PHP": "#8892BF",
    "Python": "#4B8BBE",
    "C#": "#3FB950",
    "PowerShell": "#5391FE",
    "JavaScript": "#F1E05A",
    "Shell": "#89E051",
    "C++": "#F34B7D",
    "CSS": "#A371F7",
    "HTML": "#E34C26",
    "Batchfile": "#C1F12E",
    "C": "#555555",
    "Go": "#00ADD8",
    "TypeScript": "#3178C6",
    "Ruby": "#701516",
    "Makefile": "#427819",
    "Dockerfile": "#384D54",
    "Mermaid": "#FF3670",
}
LANG_FALLBACK = "#8B949E"
DOMAIN_COLORS = ["#1F6FEB"] * 8
DOMAIN_COLORS[1] = "#A371F7"

WIDTH = 360
BG = "#161b22"
BORDER = "#30363d"
FG = "#e6edf3"
LABEL = "#c9d1d9"
MUTED = "#8b949e"
FOOT = "#6e7681"


def gh_json(path: str):
    """Run `gh api <path>` and parse JSON; abort with a clear message on failure."""
    try:
        out = subprocess.run(
            ["gh", "api", path],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except FileNotFoundError:
        sys.exit("error: GitHub CLI (gh) is not installed or not in PATH")
    except subprocess.CalledProcessError as exc:
        sys.exit(f"error: gh api {path} failed: {exc.stderr.strip()}")
    return json.loads(out)


def public_repos() -> list[dict]:
    return gh_json(f"users/{OWNER}/repos?per_page=100&type=owner")


def language_bytes(repo: str) -> dict[str, int]:
    return {name: int(value) for name, value in gh_json(f"repos/{OWNER}/{repo}/languages").items()}


def fmt_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.0f} KB"


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def card(title: str, subtitle: str, rows: list[dict], footer: str) -> str:
    """Render one card: 360 px wide, one label/bar pair per row."""
    start_y, step = 72, 30
    height = start_y + len(rows) * step + 16
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'role="img" aria-label="{esc(title)}">',
        f'<rect width="{WIDTH}" height="{height}" rx="10" fill="{BG}" stroke="{BORDER}"/>',
        f'<text x="20" y="30" font-family="Verdana, DejaVu Sans, sans-serif" font-size="15" '
        f'font-weight="bold" fill="{FG}">{esc(title)}</text>',
        f'<text x="20" y="49" font-family="Verdana, DejaVu Sans, sans-serif" font-size="10" '
        f'fill="{MUTED}">{esc(subtitle)}</text>',
    ]
    bar_x, bar_max = 20, 320
    for index, row in enumerate(rows):
        y = start_y + index * step
        width = round(bar_max * row["share"], 1)
        parts.append(
            f'<text x="20" y="{y}" font-family="Verdana, DejaVu Sans, sans-serif" '
            f'font-size="12" fill="{LABEL}">{esc(row["label"])}</text>'
        )
        parts.append(
            f'<text x="340" y="{y}" text-anchor="end" font-family="Verdana, DejaVu Sans, sans-serif" '
            f'font-size="11" font-weight="bold" fill="{FG}">{esc(row["value"])}</text>'
        )
        parts.append(
            f'<rect x="{bar_x}" y="{y + 6}" width="{width}" height="6" rx="3" '
            f'fill="{row["color"]}" opacity="0.9"/>'
        )
    parts.append(
        f'<text x="20" y="{height - 12}" font-family="Verdana, DejaVu Sans, sans-serif" '
        f'font-size="9" fill="{FOOT}">{esc(footer)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the SVG cards")
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="snapshot date for the footer")
    args = parser.parse_args()

    repos = public_repos()
    by_name = {repo["name"]: repo for repo in repos}
    product = [repo for repo in repos if not repo["fork"] and repo["name"] != OWNER]

    grouped = {name for _, names in DOMAINS for name in names}
    grouped.add(OWNER)
    ungrouped = sorted(repo["name"] for repo in repos if not repo["fork"] and repo["name"] not in grouped)
    missing = sorted(name for _, names in DOMAINS for name in names if name not in by_name)
    if ungrouped or missing:
        print("error: grouping is out of date; add or remove entries in tools/build_cards.py", file=sys.stderr)
        for name in ungrouped:
            print(f"  ungrouped public repository: {name}", file=sys.stderr)
        for name in missing:
            print(f"  listed but not found: {name}", file=sys.stderr)
        return 2

    totals: dict[str, int] = {}
    for repo in product:
        for name, size in language_bytes(repo["name"]).items():
            totals[name] = totals.get(name, 0) + size
    code_bytes = sum(totals.values())
    top = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:8]
    top_share = top[0][1]

    langs_rows = [
        {
            "label": name,
            "value": f"{size / code_bytes * 100:.1f}%",
            "share": size / top_share,
            "color": LANG_COLORS.get(name, LANG_FALLBACK),
        }
        for name, size in top
    ]
    langs_svg = card(
        "Top languages by code volume",
        f"{len(product)} product repos · {fmt_bytes(code_bytes)} of code",
        langs_rows,
        f"github.com/{OWNER} · GitHub languages API · {args.date}",
    )

    domain_counts = sorted(((name, len(names)) for name, names in DOMAINS), key=lambda item: item[1], reverse=True)
    domain_top = domain_counts[0][1]
    domain_rows = [
        {
            "label": name,
            "value": str(count),
            "share": count / domain_top,
            "color": DOMAIN_COLORS[index % len(DOMAIN_COLORS)],
        }
        for index, (name, count) in enumerate(domain_counts)
    ]
    domains_total = sum(count for _, count in domain_counts)
    domains_svg = card(
        f"{domains_total} product repos by domain",
        "curated project families · sources and tooling",
        domain_rows,
        f"github.com/{OWNER} · rebuilt {args.date}",
    )

    print(f"repos: {len(product)} public product repos ({len(repos)} incl. fork/profile)")
    print(f"code:  {fmt_bytes(code_bytes)} across {len(totals)} languages")
    for name, size in top:
        print(f"  {name:<14} {size:>10,} bytes  {size / code_bytes * 100:5.1f}%")
    print("domains:")
    for name, count in domain_counts:
        print(f"  {name:<26} {count}")

    if args.write:
        CARDS.mkdir(parents=True, exist_ok=True)
        (CARDS / "langs.svg").write_text(langs_svg, encoding="utf-8", newline="\n")
        (CARDS / "domains.svg").write_text(domains_svg, encoding="utf-8", newline="\n")
        print(f"wrote {CARDS / 'langs.svg'}")
        print(f"wrote {CARDS / 'domains.svg'}")
    else:
        print("dry run: pass --write to rewrite the cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
