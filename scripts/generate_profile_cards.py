#!/usr/bin/env python3
"""Regenerate the GitHub profile stat cards (profile/stats.svg + profile/top-langs.svg).

Unlike the public github-readme-stats service, this reads EVERY repo you have
authored commits in, including private and organisation repos, so the language
card reflects your whole body of work rather than only public/owned repos.

Auth: needs a token in GH_TOKEN or GITHUB_TOKEN (a classic PAT with `repo` and
`read:org` scopes so it can see private org repos). If neither is set it falls
back to `gh auth token`.

Usage:
    GH_TOKEN=ghp_xxx python3 scripts/generate_profile_cards.py --out profile
"""

import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = "https://api.github.com"
USER = os.environ.get("PROFILE_USER", "jameshoweee")
# First name shown in the stats card header ("<NAME>'s GitHub Stats").
NAME = os.environ.get("PROFILE_NAME", "James")

# Languages never shown on the card (papers/build noise). Edit to taste.
EXCLUDE_LANGS = {"TeX"}
# Repos to leave out of the language mix entirely (e.g. giant monorepos where
# you own only a sliver). Empty by default so the card shows everything.
EXCLUDE_REPOS: set[str] = set()

TOP_N = 12  # languages shown before the rest roll into "Other"

# GitHub Linguist colours (fallbacks for anything missing).
LANG_COLORS = {
    "C": "#555555", "C++": "#f34b7d", "Python": "#3572A5", "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a", "Kotlin": "#A97BFF", "Go": "#00ADD8", "OCaml": "#3be133",
    "Rust": "#dea584", "HTML": "#e34c26", "CSS": "#563d7c", "SCSS": "#c6538c",
    "Shell": "#89e051", "Assembly": "#6E4C13", "Verilog": "#b2b7f8", "VHDL": "#adb2cb",
    "CUDA": "#3A4E3A", "Java": "#b07219", "Jupyter Notebook": "#DA5B0B",
    "Starlark": "#76d275", "HCL": "#844FBA", "Makefile": "#427819", "CMake": "#DA3434",
    "Dockerfile": "#384d54", "PostScript": "#da291c", "Perl": "#0298c3", "Ruby": "#701516",
    "Roff": "#ecdebe", "Batchfile": "#C1F12E", "Nix": "#7e7eff", "Lua": "#000080",
    "MATLAB": "#e16737", "R": "#198CE7", "Julia": "#a270ba", "Fortran": "#4d41b1",
    "Swift": "#F05138", "Haskell": "#5e5086", "Scala": "#c22d40", "C#": "#178600",
    "Vim Script": "#199f4b", "Sage": "#555555", "Mathematica": "#dd1100", "TeX": "#3D6117",
    "PowerShell": "#012456",
}
DEFAULT_COLOR = "#858585"
OTHER_COLOR = "#666666"


# --------------------------------------------------------------------------- #
# GitHub API helpers
# --------------------------------------------------------------------------- #
def get_token() -> str:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        sys.exit("No token: set GH_TOKEN / GITHUB_TOKEN, or run `gh auth login`.")


TOKEN = None  # set in main()


def _req(url: str, method: str = "GET", data: bytes | None = None) -> urllib.request.Request:
    r = urllib.request.Request(url, method=method, data=data)
    r.add_header("Authorization", f"Bearer {TOKEN}")
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("User-Agent", f"{USER}-profile-cards")
    if data is not None:
        r.add_header("Content-Type", "application/json")
    return r


def rest(path: str):
    """GET a REST endpoint, following Link pagination. Returns list or dict."""
    url = path if path.startswith("http") else f"{API}{path}"
    out = []
    while url:
        try:
            with urllib.request.urlopen(_req(url)) as resp:
                body = json.loads(resp.read().decode())
                link = resp.headers.get("Link", "")
        except urllib.error.HTTPError as e:
            if e.code in (403, 409):  # empty repo / rate detail
                return out or []
            raise
        if not isinstance(body, list):
            return body
        out.extend(body)
        url = ""
        for part in link.split(","):
            if 'rel="next"' in part:
                url = part[part.find("<") + 1 : part.find(">")]
    return out


def graphql(query: str) -> dict:
    data = json.dumps({"query": query}).encode()
    with urllib.request.urlopen(_req(f"{API}/graphql", "POST", data)) as resp:
        return json.loads(resp.read().decode())["data"]


def search_count(q: str) -> int:
    import urllib.parse
    url = f"{API}/search/issues?q={urllib.parse.quote(q)}&per_page=1"
    with urllib.request.urlopen(_req(url)) as resp:
        return json.loads(resp.read().decode())["total_count"]


# --------------------------------------------------------------------------- #
# Data gathering
# --------------------------------------------------------------------------- #
def gather_stats(created_year: int) -> dict:
    # Stars: your own non-fork repos.
    owned = rest(f"/users/{USER}/repos?per_page=100&type=owner")
    stars = sum(r["stargazers_count"] for r in owned if not r["fork"])

    # Commits: sum of all-time contributions incl. private (restricted).
    this_year = datetime.date.today().year
    commits = 0
    for y in range(created_year, this_year + 1):
        q = f'''query{{user(login:"{USER}"){{contributionsCollection(
            from:"{y}-01-01T00:00:00Z",to:"{y}-12-31T23:59:59Z"){{
            totalCommitContributions restrictedContributionsCount}}}}}}'''
        c = graphql(q)["user"]["contributionsCollection"]
        commits += c["totalCommitContributions"] + c["restrictedContributionsCount"]

    prs = search_count(f"type:pr author:{USER}")
    issues = search_count(f"type:issue author:{USER}")
    contributed = graphql(
        f'query{{user(login:"{USER}"){{repositoriesContributedTo(first:1,'
        f"contributionTypes:[COMMIT,PULL_REQUEST,ISSUE,REPOSITORY]){{totalCount}}}}}}"
    )["user"]["repositoriesContributedTo"]["totalCount"]
    return {"stars": stars, "commits": commits, "prs": prs,
            "issues": issues, "contributed": contributed}


def _authored(full_name: str) -> bool:
    commits = rest(f"/repos/{full_name}/commits?author={USER}&per_page=1")
    return isinstance(commits, list) and len(commits) >= 1


def gather_languages() -> list[tuple[str, float]]:
    repos = rest(
        "/user/repos?per_page=100&affiliation=owner,collaborator,organization_member"
    )
    names = [r["full_name"] for r in repos if r["full_name"] not in EXCLUDE_REPOS]
    with ThreadPoolExecutor(max_workers=16) as ex:
        mine = [n for n, ok in zip(names, ex.map(_authored, names)) if ok]
    print(f"  authored commits in {len(mine)}/{len(names)} accessible repos")

    with ThreadPoolExecutor(max_workers=16) as ex:
        per_repo = list(ex.map(lambda n: rest(f"/repos/{n}/languages"), mine))

    totals: dict[str, int] = {}
    for d in per_repo:
        for lang, bytes_ in (d or {}).items():
            if lang in EXCLUDE_LANGS:
                continue
            totals[lang] = totals.get(lang, 0) + bytes_

    grand = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    top = ranked[:TOP_N]
    other = sum(v for _, v in ranked[TOP_N:])
    items = [(lang, v / grand) for lang, v in top]
    if other:
        items.append(("Other", other / grand))
    return items


# --------------------------------------------------------------------------- #
# SVG rendering (matches the existing tokyonight-styled cards)
# --------------------------------------------------------------------------- #
def render_stats(s: dict) -> str:
    rows = [
        ("Total Stars", f"{s['stars']:,}",
         "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z"),
        ("Total Commits", f"{s['commits']:,}",
         "M11.93 8.5a4.002 4.002 0 01-7.86 0H.75a.75.75 0 010-1.5h3.32a4.002 4.002 0 017.86 0h3.32a.75.75 0 010 1.5h-3.32zm-1.43-.75a2.5 2.5 0 10-5 0 2.5 2.5 0 005 0z"),
        ("Total PRs", f"{s['prs']:,}",
         "M7.177 3.073L9.573.677A.25.25 0 0110 .854v4.792a.25.25 0 01-.427.177L7.177 3.427a.25.25 0 010-.354zM3.75 2.5a.75.75 0 100 1.5.75.75 0 000-1.5zm-2.25.75a2.25 2.25 0 113 2.122v5.256a2.251 2.251 0 11-1.5 0V5.372A2.25 2.25 0 011.5 3.25zM11 2.5h-1V4h1a1 1 0 011 1v5.628a2.251 2.251 0 101.5 0V5A2.5 2.5 0 0011 2.5zm1 10.25a.75.75 0 111.5 0 .75.75 0 01-1.5 0zM3.75 12a.75.75 0 100 1.5.75.75 0 000-1.5z"),
        ("Total Issues", f"{s['issues']:,}",
         "M8 9.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3z"),
        ("Contributed to", f"{s['contributed']} repos",
         "M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1h-8a1 1 0 00-1 1v6.708A2.486 2.486 0 014.5 9h8V1.5zm-8 11h1.5v-2H4.5a1 1 0 100 2z"),
    ]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="180" viewBox="0 0 300 180">',
        "  <style>",
        "    .header { font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #70a5fd; }",
        "    .stat-label { font: 400 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: #38bdae; }",
        "    .stat-value { font: 700 13px 'Segoe UI', Ubuntu, Sans-Serif; fill: #c9d1d9; }",
        "    .icon { fill: #bf91f3; }",
        "  </style>",
        '  <rect x="0.5" y="0.5" rx="4.5" width="299" height="179" fill="#1a1b27" stroke="#444" stroke-opacity="1"/>',
        f'  <text x="25" y="35" class="header">{NAME}\'s GitHub Stats</text>',
    ]
    y = 52
    for label, value, icon in rows:
        parts.append(f'  <svg x="25" y="{y}" width="16" height="16" viewBox="0 0 16 16" class="icon">')
        if label == "Total Issues":
            parts.append('    <path d="M8 9.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3z"/>')
            parts.append('    <path fill-rule="evenodd" d="M8 0a8 8 0 100 16A8 8 0 008 0zM1.5 8a6.5 6.5 0 1113 0 6.5 6.5 0 01-13 0z"/>')
        else:
            fr = ' fill-rule="evenodd"' if label == "Contributed to" else ""
            parts.append(f'    <path{fr} d="{icon}"/>')
        parts.append("  </svg>")
        parts.append(f'  <text x="50" y="{y + 13}" class="stat-label">{label}</text>')
        parts.append(f'  <text x="230" y="{y + 13}" class="stat-value" text-anchor="end">{value}</text>')
        y += 26
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _pt(radius: float, ang_deg: float, cx=150.0, cy=140.0) -> tuple[float, float]:
    a = math.radians(ang_deg)
    return cx + radius * math.sin(a), cy - radius * math.cos(a)


def render_langs(items: list[tuple[str, float]]) -> str:
    R, r = 90.0, 55.0
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="280" viewBox="0 0 520 280">',
        "  <style>",
        "    .header { font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: #70a5fd; }",
        "    .lang-name { font: 600 12px 'Segoe UI', Ubuntu, Sans-Serif; fill: #c9d1d9; }",
        "    .lang-pct { font: 400 11px 'Segoe UI', Ubuntu, Sans-Serif; fill: #38bdae; }",
        "    .note { font: 400 10px 'Segoe UI', Ubuntu, Sans-Serif; fill: #38bdae; opacity: 0.5; }",
        "  </style>",
        '  <rect x="0.5" y="0.5" rx="4.5" width="519" height="279" fill="#1a1b27" stroke="#444" stroke-opacity="1"/>',
        '  <text x="25" y="35" class="header">Most Used Languages</text>',
        "",
    ]
    # donut segments
    start = 0.0
    for name, frac in items:
        sweep = frac * 360.0
        a0, a1 = start, start + sweep
        large = 1 if sweep > 180 else 0
        o0, o1, i1, i0 = _pt(R, a0), _pt(R, a1), _pt(r, a1), _pt(r, a0)
        color = OTHER_COLOR if name == "Other" else LANG_COLORS.get(name, DEFAULT_COLOR)
        parts.append(
            f'  <path d="M {o0[0]:.1f} {o0[1]:.1f} A {R:.0f} {R:.0f} 0 {large} 1 '
            f'{o1[0]:.1f} {o1[1]:.1f} L {i1[0]:.1f} {i1[1]:.1f} A {r:.0f} {r:.0f} 0 {large} 0 '
            f'{i0[0]:.1f} {i0[1]:.1f} Z" fill="{color}" stroke="#1a1b27" stroke-width="1.5"/>'
        )
        start = a1
    parts.append("")
    # legend
    for i, (name, frac) in enumerate(items):
        x = 280 if i % 2 == 0 else 400
        y = 60 + (i // 2) * 28
        color = OTHER_COLOR if name == "Other" else LANG_COLORS.get(name, DEFAULT_COLOR)
        parts.append(f'  <g transform="translate({x}, {y})">')
        parts.append(f'    <circle cx="6" cy="6" r="6" fill="{color}"/>')
        parts.append(f'    <text x="18" y="10" class="lang-name">{name}</text>')
        parts.append(f'    <text x="18" y="23" class="lang-pct">{frac * 100:.2f}%</text>')
        parts.append("  </g>")
    today = datetime.date.today().isoformat()
    parts.append("")
    parts.append(f'  <text x="25" y="268" class="note">Updated {today} (excludes TeX)</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


# --------------------------------------------------------------------------- #
def main() -> None:
    global TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="profile", help="output directory for the SVGs")
    args = ap.parse_args()

    TOKEN = get_token()
    created = rest(f"/users/{USER}")["created_at"]
    created_year = int(created[:4])

    print("Gathering stats...")
    stats = gather_stats(created_year)
    print(f"  {stats}")
    print("Gathering languages (this scans every repo you've committed to)...")
    langs = gather_languages()
    print("  " + " | ".join(f"{n} {f*100:.1f}%" for n, f in langs))

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "stats.svg"), "w") as f:
        f.write(render_stats(stats))
    with open(os.path.join(args.out, "top-langs.svg"), "w") as f:
        f.write(render_langs(langs))
    print(f"Wrote {args.out}/stats.svg and {args.out}/top-langs.svg")


if __name__ == "__main__":
    main()
