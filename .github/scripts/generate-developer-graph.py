#!/usr/bin/env python3
"""Generate a static GitHub developer relationship graph for the profile README.

The script reads public GitHub profile, repository, issue/PR, and event data,
then writes two generated assets used by README.md:

- assets/github-developer-graph.json
- assets/github-developer-graph.svg
"""

from __future__ import annotations

import html
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

USERNAME = os.getenv("GITHUB_USERNAME", "hu-qi")
TOKEN = os.getenv("GITHUB_TOKEN", "")
ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = ROOT / "assets"
OUT_SVG = ASSET_DIR / "github-developer-graph.svg"
OUT_JSON = ASSET_DIR / "github-developer-graph.json"
API = "https://api.github.com"

ACTIVITY_ICONS = {
    "Push": "↑",
    "Watch": "★",
    "Create": "+",
    "PullRequest": "PR",
    "PullRequestReview": "✓",
    "Issues": "!",
    "Fork": "⑂",
    "Release": "↗",
}
LANG_BADGES = {
    "Python": "Py",
    "TypeScript": "TS",
    "JavaScript": "JS",
    "Rust": "Rs",
    "Jupyter Notebook": "Nb",
    "HTML": "H5",
    "CSS": "CSS",
    "C": "C",
    "C++": "C++",
    "Go": "Go",
    "Shell": "Sh",
    "Vue": "Vue",
    "MDX": "MDX",
}


def request_json(path: str, *, query: dict[str, Any] | None = None) -> Any:
    """Fetch JSON from the GitHub REST API or a fully qualified GitHub URL."""
    url = path if path.startswith("https://") else f"{API}{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USERNAME}-profile-readme-graph",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as res:  # nosec B310 - GitHub API only
        return json.loads(res.read().decode("utf-8"))


def safe_request(path: str, *, query: dict[str, Any] | None = None, default: Any = None) -> Any:
    """Fetch GitHub JSON and return a fallback value when the request fails."""
    try:
        return request_json(path, query=query)
    except Exception as exc:  # noqa: BLE001 - README generation should be best-effort
        print(f"[warn] failed to fetch {path}: {exc}", file=sys.stderr)
        return default


def esc(value: Any) -> str:
    """Escape a value for safe insertion into SVG XML text or attributes."""
    return html.escape(str(value), quote=True)


def clamp(text: str, limit: int = 34) -> str:
    """Trim long labels so they fit inside the SVG graph layout."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def node_id(value: str) -> str:
    """Build a stable SVG id suffix from an arbitrary label."""
    return re.sub(r"[^a-zA-Z0-9_-]", "-", value)


def score_repo(repo: dict[str, Any]) -> float:
    """Score a repository by popularity, freshness, and whether it is original."""
    pushed_at = repo.get("pushed_at") or repo.get("updated_at") or "1970-01-01T00:00:00Z"
    try:
        year = int(pushed_at[:4])
    except ValueError:
        year = 1970
    freshness = max(0, year - 2020)
    return (
        float(repo.get("stargazers_count", 0)) * 3
        + float(repo.get("forks_count", 0)) * 2
        + freshness
        + (4 if not repo.get("fork") else 0)
    )


def build_dataset() -> dict[str, Any]:
    """Aggregate profile, repository, collaboration, language, and event data."""
    user = safe_request(f"/users/{USERNAME}", default={})
    repos = safe_request(
        f"/users/{USERNAME}/repos",
        query={"per_page": 100, "sort": "updated", "type": "owner"},
        default=[],
    )
    events = safe_request(f"/users/{USERNAME}/events/public", query={"per_page": 100}, default=[])
    authored = safe_request(
        "/search/issues",
        query={
            "q": f"author:{USERNAME} -user:{USERNAME}",
            "sort": "updated",
            "order": "desc",
            "per_page": 60,
        },
        default={"items": []},
    )

    repo_counter: Counter[str] = Counter()
    org_counter: Counter[str] = Counter()
    lang_counter: Counter[str] = Counter()
    event_counter: Counter[str] = Counter()

    for repo in repos:
        name = repo.get("name")
        if not name:
            continue
        repo_counter[f"{USERNAME}/{name}"] += int(score_repo(repo)) or 1
        if repo.get("language"):
            lang_counter[repo["language"]] += 1 + int(repo.get("stargazers_count", 0) or 0)

    for item in authored.get("items", []):
        repo_url = item.get("repository_url", "")
        full_name = repo_url.rsplit("/repos/", 1)[-1] if "/repos/" in repo_url else ""
        if not full_name or full_name.startswith(f"{USERNAME}/"):
            continue
        repo_counter[full_name] += 8
        org_counter[full_name.split("/", 1)[0]] += 5

    for event in events:
        event_type = event.get("type", "Event").replace("Event", "")
        event_counter[event_type] += 1
        repo_name = (event.get("repo") or {}).get("name")
        if repo_name:
            repo_counter[repo_name] += 3
            owner = repo_name.split("/", 1)[0]
            if owner != USERNAME:
                org_counter[owner] += 2

    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "user": {
            "login": user.get("login", USERNAME),
            "name": user.get("name") or USERNAME,
            "public_repos": user.get("public_repos", 0),
            "followers": user.get("followers", 0),
            "following": user.get("following", 0),
        },
        "repos": repo_counter.most_common(7),
        "orgs": org_counter.most_common(6),
        "languages": lang_counter.most_common(7),
        "events": event_counter.most_common(5),
    }


def weight_size(weight: int) -> float:
    """Convert an aggregate weight into a bounded node radius."""
    return 8 + min(13, math.sqrt(max(weight, 1)) * 1.6)


def draw_repo_pill(label: str, weight: int, x: int, y: int, anchor: str) -> str:
    """Render a repository node with a small repository icon badge."""
    text = clamp(label)
    width = min(250, max(134, 38 + len(text) * 7))
    rect_x = x if anchor == "left" else x - width
    text_x = rect_x + 40 if anchor == "left" else rect_x + width - 16
    text_anchor = "start" if anchor == "left" else "end"
    icon_x = rect_x + 17 if anchor == "left" else rect_x + width - 17
    icon_size = weight_size(weight)
    return f'''
<rect x="{rect_x}" y="{y}" width="{width}" height="34" rx="17" class="pill"/>
<rect x="{icon_x - icon_size:.1f}" y="{y + 17 - icon_size:.1f}" width="{icon_size * 2:.1f}" height="{icon_size * 2:.1f}" rx="7" class="repo-icon"/>
<text x="{icon_x}" y="{y + 21}" text-anchor="middle" class="icon-text">⌘</text>
<text x="{text_x}" y="{y + 22}" text-anchor="{text_anchor}" class="label">{esc(text)}</text>'''


def draw_org_pill(label: str, weight: int, x: int, y: int, anchor: str) -> str:
    """Render an organization node with its GitHub avatar."""
    text = clamp(label)
    width = min(240, max(126, 40 + len(text) * 7))
    rect_x = x if anchor == "left" else x - width
    text_x = rect_x + 40 if anchor == "left" else rect_x + width - 16
    text_anchor = "start" if anchor == "left" else "end"
    avatar_x = rect_x + 17 if anchor == "left" else rect_x + width - 17
    r = weight_size(weight)
    clip = f"avatar-{node_id(label)}"
    return f'''
<clipPath id="{clip}"><circle cx="{avatar_x}" cy="{y + 17}" r="{r:.1f}"/></clipPath>
<rect x="{rect_x}" y="{y}" width="{width}" height="34" rx="17" class="pill"/>
<circle cx="{avatar_x}" cy="{y + 17}" r="{r:.1f}" class="avatar-fallback"/>
<image href="https://github.com/{esc(label)}.png?size=64" x="{avatar_x - r:.1f}" y="{y + 17 - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" clip-path="url(#{clip})" preserveAspectRatio="xMidYMid slice"/>
<circle cx="{avatar_x}" cy="{y + 17}" r="{r:.1f}" class="avatar-ring"/>
<text x="{text_x}" y="{y + 22}" text-anchor="{text_anchor}" class="label">{esc(text)}</text>'''


def draw_group(title: str, items: list[tuple[str, int]], x: int, y: int, anchor: str, line_x: int, *, kind: str) -> str:
    """Render a vertical group of repo or org nodes with curved edges."""
    if not items:
        return ""
    parts = [f'<text x="{x}" y="{y - 18}" text-anchor="{anchor}" class="section">{esc(title)}</text>']
    for idx, (label, weight) in enumerate(items):
        py = y + idx * 48
        side = "left" if anchor == "start" else "right"
        pill = draw_org_pill(label, int(weight), x, py, side) if kind == "org" else draw_repo_pill(label, int(weight), x, py, side)
        edge_end_x = x + 10 if anchor == "start" else x - 10
        edge_end_y = py + 17
        parts.append(f'<path d="M 600 360 C {line_x} 360, {line_x} {edge_end_y}, {edge_end_x} {edge_end_y}" class="edge"/>')
        parts.append(pill)
    return "\n".join(parts)


def draw_bottom(items: list[tuple[str, int]], start_x: int, y: int) -> str:
    """Render language badges at the bottom of the graph."""
    if not items:
        return ""
    parts = [f'<text x="600" y="{y - 30}" text-anchor="middle" class="section">Languages</text>']
    gap = 118
    for idx, (label, weight) in enumerate(items):
        x = start_x + idx * gap
        r = weight_size(int(weight)) + 2
        badge = LANG_BADGES.get(label, clamp(label, 3))
        parts.append(f'<path d="M 600 360 C 600 455, {x} 455, {x} {y}" class="edge"/>')
        parts.append(f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" rx="9" class="lang-icon"/>')
        parts.append(f'<text x="{x}" y="{y + 4}" text-anchor="middle" class="lang-text">{esc(badge)}</text>')
        parts.append(f'<text x="{x}" y="{y + r + 17:.1f}" text-anchor="middle" class="label">{esc(clamp(label, 14))}</text>')
    return "\n".join(parts)


def draw_top(items: list[tuple[str, int]], start_x: int, y: int) -> str:
    """Render recent activity icon badges above the center node."""
    if not items:
        return ""
    parts = ['<text x="600" y="205" text-anchor="middle" class="section">Recent Activity</text>']
    gap = 130
    for idx, (label, weight) in enumerate(items):
        x = start_x + idx * gap
        r = weight_size(int(weight)) + 2
        icon = ACTIVITY_ICONS.get(label, label[:2])
        parts.append(f'<path d="M 600 360 C 600 310, {x} 300, {x} {y}" class="edge"/>')
        parts.append(f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r:.1f}" height="{2 * r:.1f}" rx="{min(12, r):.1f}" class="activity-icon"/>')
        parts.append(f'<text x="{x}" y="{y + 4}" text-anchor="middle" class="activity-text">{esc(icon)}</text>')
        parts.append(f'<text x="{x}" y="{y - r - 10:.1f}" text-anchor="middle" class="label">{esc(clamp(label, 16))}</text>')
    return "\n".join(parts)


def render_svg(data: dict[str, Any]) -> str:
    """Assemble the complete SVG document from the aggregated graph dataset."""
    repos = data.get("repos", [])[:7]
    orgs = data.get("orgs", [])[:6]
    languages = data.get("languages", [])[:7]
    events = data.get("events", [])[:5]
    user = data.get("user", {})

    lang_start = 600 - (max(len(languages), 1) - 1) * 118 // 2
    event_start = 600 - (max(len(events), 1) - 1) * 130 // 2

    return f'''<svg width="1200" height="760" viewBox="0 0 1200 760" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
<title id="title">{esc(USERNAME)} GitHub Developer Relationship Graph</title>
<desc id="desc">Generated from GitHub profile, repositories, authored issues and pull requests, and public events.</desc>
<style>
  .bg {{ fill: #0d1117; }}
  .card {{ fill: rgba(255,255,255,.045); stroke: rgba(255,255,255,.12); }}
  .title {{ fill: #f0f6fc; font: 700 34px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .sub {{ fill: #8b949e; font: 500 15px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .section {{ fill: #c9d1d9; font: 700 17px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .label {{ fill: #dbe7ff; font: 600 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .small {{ fill: #8b949e; font: 500 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .edge {{ stroke: rgba(88,166,255,.24); stroke-width: 1.4; fill: none; }}
  .pill {{ fill: rgba(255,255,255,.055); stroke: rgba(255,255,255,.14); }}
  .core {{ fill: url(#core); stroke: rgba(255,255,255,.85); stroke-width: 2; filter: drop-shadow(0 0 24px rgba(126,231,135,.35)); }}
  .repo-icon {{ fill: #58a6ff; stroke: rgba(255,255,255,.7); stroke-width: 1; filter: drop-shadow(0 0 10px rgba(88,166,255,.24)); }}
  .icon-text {{ fill: #ffffff; font: 800 11px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .avatar-fallback {{ fill: #d2a8ff; }}
  .avatar-ring {{ fill: none; stroke: rgba(255,255,255,.86); stroke-width: 1.2; filter: drop-shadow(0 0 10px rgba(210,168,255,.24)); }}
  .lang-icon {{ fill: #7ee787; stroke: rgba(255,255,255,.76); stroke-width: 1; filter: drop-shadow(0 0 10px rgba(126,231,135,.24)); }}
  .lang-text {{ fill: #0d1117; font: 800 11px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  .activity-icon {{ fill: #ffa657; stroke: rgba(255,255,255,.78); stroke-width: 1; filter: drop-shadow(0 0 10px rgba(255,166,87,.28)); }}
  .activity-text {{ fill: #0d1117; font: 900 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }}
  @media (prefers-color-scheme: light) {{
    .bg {{ fill: #ffffff; }}
    .card {{ fill: #f6f8fa; stroke: #d0d7de; }}
    .title {{ fill: #24292f; }}
    .sub, .small {{ fill: #57606a; }}
    .section {{ fill: #24292f; }}
    .label {{ fill: #24292f; }}
    .edge {{ stroke: rgba(9,105,218,.22); }}
    .pill {{ fill: #ffffff; stroke: #d0d7de; }}
  }}
</style>
<defs>
  <linearGradient id="core" x1="520" y1="280" x2="680" y2="440" gradientUnits="userSpaceOnUse">
    <stop stop-color="#7ee787"/>
    <stop offset="1" stop-color="#58a6ff"/>
  </linearGradient>
</defs>
<rect width="1200" height="760" rx="28" class="bg"/>
<rect x="32" y="32" width="1136" height="696" rx="26" class="card"/>
<text x="600" y="82" text-anchor="middle" class="title">GitHub Developer Graph · {esc(USERNAME)}</text>
<text x="600" y="112" text-anchor="middle" class="sub">Data from GitHub REST API · repos · PRs / issues · public events · generated {esc(data.get('generated_at', ''))}</text>

{draw_top(events, event_start, 245)}
{draw_group('Repositories', repos, 80, 210, 'start', 405, kind='repo')}
{draw_group('Communities / Orgs', orgs, 1120, 235, 'end', 795, kind='org')}
{draw_bottom(languages, lang_start, 610)}

<circle cx="600" cy="360" r="86" class="core"/>
<text x="600" y="345" text-anchor="middle" style="fill:#0d1117;font:800 28px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">{esc(user.get('name') or USERNAME)}</text>
<text x="600" y="374" text-anchor="middle" style="fill:#0d1117;font:700 14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">@{esc(USERNAME)}</text>
<text x="600" y="401" text-anchor="middle" style="fill:#0d1117;font:700 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">{esc(user.get('public_repos', 0))} repos · {esc(user.get('followers', 0))} followers</text>

<text x="600" y="704" text-anchor="middle" class="small">Generated by .github/scripts/generate-developer-graph.py · update via GitHub Actions</text>
</svg>
'''


def main() -> None:
    """Generate and write the developer graph JSON and SVG assets."""
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = build_dataset()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_SVG.write_text(render_svg(data), encoding="utf-8")
    print(f"[ok] wrote {OUT_SVG}")
    print(f"[ok] wrote {OUT_JSON}")


if __name__ == "__main__":
    main()
