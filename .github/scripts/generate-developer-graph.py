#!/usr/bin/env python3
"""Generate a self-contained GitHub developer graph SVG for the profile README."""
from __future__ import annotations

import base64, html, json, math, os, re, sys, time, urllib.parse, urllib.request
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
SKILL_BASE = "https://raw.githubusercontent.com/danielcranney/profileme-dev/main/public/icons/skills"
LANG_ICON = {"Python":"python-colored.svg","TypeScript":"typescript-colored.svg","JavaScript":"javascript-colored.svg","Rust":"rust-colored.svg","Jupyter Notebook":"jupyter-colored.svg","HTML":"html5-colored.svg","CSS":"css3-colored.svg","C":"c-colored.svg","C++":"cplusplus-colored.svg","Go":"go-colored.svg","Shell":"bash-colored.svg","Vue":"vuejs-colored.svg"}
LANG_BADGE = {"Python":"Py","TypeScript":"TS","JavaScript":"JS","Rust":"Rs","Jupyter Notebook":"Nb","HTML":"H5","CSS":"CSS","C":"C","C++":"C++","Go":"Go","Shell":"Sh","Vue":"Vue"}
OCTICON = {
    "Push":"M8 1.25a.75.75 0 0 1 .75.75v8.19l2.22-2.22a.749.749 0 1 1 1.06 1.06l-3.5 3.5a.749.749 0 0 1-1.06 0l-3.5-3.5a.749.749 0 1 1 1.06-1.06l2.22 2.22V2A.75.75 0 0 1 8 1.25Z",
    "Watch":"M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.75.75 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z",
    "Create":"M7.25 7.25V2a.75.75 0 0 1 1.5 0v5.25H14a.75.75 0 0 1 0 1.5H8.75V14a.75.75 0 0 1-1.5 0V8.75H2a.75.75 0 0 1 0-1.5h5.25Z",
    "PullRequest":"M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm10 0a2.25 2.25 0 1 1 1.5 2.122V8A3.75 3.75 0 0 1 9.25 11.75H8.5a.75.75 0 0 1 0-1.5h.75A2.25 2.25 0 0 0 11.5 8V5.372A2.25 2.25 0 0 1 11.5 3.25Z",
    "Fork":"M5 3.25a2.25 2.25 0 1 1 1.5 2.122v1.001A3.75 3.75 0 0 0 8 6.75a3.75 3.75 0 0 0 1.5-.377V5.372a2.25 2.25 0 1 1 1.5 0v1.001A5.25 5.25 0 0 1 8.75 7.95v2.678a2.251 2.251 0 1 1-1.5 0V7.95A5.25 5.25 0 0 1 5 6.373V5.372A2.25 2.25 0 0 1 5 3.25Z",
}

def esc(v: Any) -> str: return html.escape(str(v), quote=True)
def clamp(s: str, n: int = 34) -> str: return s if len(s.strip()) <= n else s.strip()[:n-1] + "…"
def nid(s: str) -> str: return re.sub(r"[^a-zA-Z0-9_-]", "-", s)
def sz(w: int) -> float: return 10 + min(13, math.sqrt(max(w, 1)) * 1.45)

def hdr() -> dict[str, str]:
    h = {"Accept":"application/vnd.github+json", "User-Agent":f"{USERNAME}-profile-readme-graph", "X-GitHub-Api-Version":"2022-11-28"}
    if TOKEN: h["Authorization"] = f"Bearer {TOKEN}"
    return h

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=hdr())
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()  # nosec B310

def get_json(path: str, q: dict[str, Any] | None = None, default: Any = None) -> Any:
    try:
        url = path if path.startswith("https://") else API + path
        if q: url += "?" + urllib.parse.urlencode(q)
        return json.loads(fetch_bytes(url).decode())
    except Exception as e:
        print(f"[warn] {path}: {e}", file=sys.stderr); return default

def uri(url: str, mime: str) -> str:
    try: return f"data:{mime};base64," + base64.b64encode(fetch_bytes(url)).decode("ascii")
    except Exception as e:
        print(f"[warn] inline failed {url}: {e}", file=sys.stderr); return ""

def avatar(login: str) -> str: return uri(f"https://github.com/{urllib.parse.quote(login)}.png?size=96", "image/png")
def skill(lang: str) -> str:
    icon = LANG_ICON.get(lang)
    return uri(f"{SKILL_BASE}/{icon}", "image/svg+xml") if icon else ""

def repo_score(r: dict[str, Any]) -> int:
    y = int((r.get("pushed_at") or r.get("updated_at") or "1970")[:4])
    return int(r.get("stargazers_count",0))*3 + int(r.get("forks_count",0))*2 + max(0, y-2020) + (0 if r.get("fork") else 4)

def dataset() -> dict[str, Any]:
    user = get_json(f"/users/{USERNAME}", default={}) or {}
    repos = get_json(f"/users/{USERNAME}/repos", {"per_page":100,"sort":"updated","type":"owner"}, []) or []
    events = get_json(f"/users/{USERNAME}/events/public", {"per_page":100}, []) or []
    authored = get_json("/search/issues", {"q":f"author:{USERNAME} -user:{USERNAME}","sort":"updated","order":"desc","per_page":60}, {"items":[]}) or {"items":[]}
    rc, oc, lc, ec = Counter(), Counter(), Counter(), Counter()
    for r in repos:
        if r.get("name"): rc[f"{USERNAME}/{r['name']}"] += max(1, repo_score(r))
        if r.get("language"): lc[r["language"]] += 1 + int(r.get("stargazers_count",0) or 0)
    for it in authored.get("items", []):
        u = it.get("repository_url", ""); full = u.rsplit("/repos/",1)[-1] if "/repos/" in u else ""
        if full and not full.startswith(f"{USERNAME}/"):
            rc[full] += 8; oc[full.split("/",1)[0]] += 5
    for ev in events:
        typ = ev.get("type", "Event").replace("Event", ""); ec[typ] += 1
        rn = (ev.get("repo") or {}).get("name")
        if rn:
            rc[rn] += 3; owner = rn.split("/",1)[0]
            if owner != USERNAME: oc[owner] += 2
    return {"generated_at":time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),"user":{"login":user.get("login",USERNAME),"name":user.get("name") or USERNAME,"public_repos":user.get("public_repos",0),"followers":user.get("followers",0),"following":user.get("following",0)},"repos":rc.most_common(7),"orgs":oc.most_common(6),"languages":lc.most_common(7),"events":ec.most_common(5)}

def repo_node(label: str, w: int, y: int) -> str:
    width = min(265, max(150, 46 + len(clamp(label))*7)); r = sz(w)
    return f'<rect x="80" y="{y}" width="{width}" height="34" rx="17" class="pill"/><rect x="{97-r:.1f}" y="{y+17-r:.1f}" width="{2*r:.1f}" height="{2*r:.1f}" rx="7" class="repo-icon"/><path d="M91 {y+11}h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H91a2 2 0 0 1-2-2V{y+13}a2 2 0 0 1 2-2Zm1.5 3v8h9v-8h-9Z" class="repo-path"/><text x="120" y="{y+22}" class="label">{esc(clamp(label))}</text>'

def org_node(label: str, w: int, y: int) -> str:
    width = min(250, max(142, 46 + len(clamp(label))*7)); x = 1120 - width; ax = 1102; r = sz(w); clip = "av-" + nid(label); img = avatar(label)
    inside = f'<image href="{img}" x="{ax-r:.1f}" y="{y+17-r:.1f}" width="{2*r:.1f}" height="{2*r:.1f}" clip-path="url(#{clip})" preserveAspectRatio="xMidYMid slice"/>' if img else f'<text x="{ax}" y="{y+21}" text-anchor="middle" class="avatar-text">{esc(label[:2].upper())}</text>'
    return f'<clipPath id="{clip}"><circle cx="{ax}" cy="{y+17}" r="{r:.1f}"/></clipPath><rect x="{x}" y="{y}" width="{width}" height="34" rx="17" class="pill"/><circle cx="{ax}" cy="{y+17}" r="{r:.1f}" class="avatar-fallback"/>{inside}<circle cx="{ax}" cy="{y+17}" r="{r:.1f}" class="avatar-ring"/><text x="{x+width-44}" y="{y+22}" text-anchor="end" class="label">{esc(clamp(label))}</text>'

def sides(repos: list[tuple[str,int]], orgs: list[tuple[str,int]]) -> str:
    p = ['<text x="80" y="192" class="section">Repositories</text>','<text x="1120" y="217" text-anchor="end" class="section">Communities / Orgs</text>']
    for i,(l,w) in enumerate(repos):
        y=210+i*48; p += [f'<path d="M600 360 C405 360 405 {y+17} 90 {y+17}" class="edge"/>', repo_node(l,int(w),y)]
    for i,(l,w) in enumerate(orgs):
        y=235+i*48; p += [f'<path d="M600 360 C795 360 795 {y+17} 1110 {y+17}" class="edge"/>', org_node(l,int(w),y)]
    return "\n".join(p)

def languages(items: list[tuple[str,int]]) -> str:
    if not items: return ""
    start = 600 - (len(items)-1)*118//2; p=['<text x="600" y="575" text-anchor="middle" class="section">Languages</text>']
    for i,(l,w) in enumerate(items):
        x=start+i*118; y=615; r=sz(int(w))+4; ic=skill(l)
        p += [f'<path d="M600 360 C600 455 {x} 455 {x} {y}" class="edge"/>', f'<rect x="{x-r:.1f}" y="{y-r:.1f}" width="{2*r:.1f}" height="{2*r:.1f}" rx="10" class="icon-shell"/>']
        p.append(f'<image href="{ic}" x="{x-r+5:.1f}" y="{y-r+5:.1f}" width="{2*r-10:.1f}" height="{2*r-10:.1f}"/>' if ic else f'<text x="{x}" y="{y+4}" text-anchor="middle" class="lang-text">{esc(LANG_BADGE.get(l, clamp(l,3)))}</text>')
        p.append(f'<text x="{x}" y="{y+r+16:.1f}" text-anchor="middle" class="label">{esc(clamp(l,14))}</text>')
    return "\n".join(p)

def oct(label: str, x: int, y: int, size: float) -> str:
    d = OCTICON.get(label, OCTICON["Create"]); s = size/16
    return f'<g transform="translate({x-size/2:.1f} {y-size/2:.1f}) scale({s:.3f})"><path d="{d}" class="activity-path"/></g>'

def activity(items: list[tuple[str,int]]) -> str:
    if not items: return ""
    start = 600 - (len(items)-1)*118//2; p=['<text x="600" y="205" text-anchor="middle" class="section">Recent Activity</text>']
    for i,(l,w) in enumerate(items):
        x=start+i*118; y=245; r=sz(int(w))+4
        p += [f'<path d="M600 360 C600 295 {x} 300 {x} {y}" class="edge"/>', f'<rect x="{x-r:.1f}" y="{y-r:.1f}" width="{2*r:.1f}" height="{2*r:.1f}" rx="10" class="activity-icon"/>', oct(l,x,y,min(18,2*r-10)), f'<text x="{x}" y="{y-r-10:.1f}" text-anchor="middle" class="label">{esc(clamp(l,16))}</text>']
    return "\n".join(p)

def svg(data: dict[str, Any]) -> str:
    u = data["user"]
    return f'''<svg width="1200" height="760" viewBox="0 0 1200 760" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc"><title id="title">{esc(USERNAME)} GitHub Developer Graph</title><desc id="desc">Generated from GitHub profile, repositories, authored issues and pull requests, and public events.</desc><style>.bg{{fill:#0d1117}}.card{{fill:rgba(255,255,255,.045);stroke:rgba(255,255,255,.12)}}.title{{fill:#f0f6fc;font:700 34px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.sub{{fill:#8b949e;font:500 15px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.section{{fill:#c9d1d9;font:700 17px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.label{{fill:#dbe7ff;font:600 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.small{{fill:#8b949e;font:500 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.edge{{stroke:rgba(88,166,255,.24);stroke-width:1.4;fill:none}}.pill{{fill:rgba(255,255,255,.055);stroke:rgba(255,255,255,.14)}}.core{{fill:url(#core);stroke:rgba(255,255,255,.85);stroke-width:2;filter:drop-shadow(0 0 24px rgba(126,231,135,.35))}}.repo-icon{{fill:#58a6ff;stroke:rgba(255,255,255,.7);stroke-width:1}}.repo-path{{fill:#fff}}.avatar-fallback{{fill:#d2a8ff}}.avatar-ring{{fill:none;stroke:rgba(255,255,255,.86);stroke-width:1.2}}.avatar-text{{fill:#fff;font:800 10px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.icon-shell{{fill:rgba(126,231,135,.18);stroke:rgba(126,231,135,.55);stroke-width:1}}.lang-text{{fill:#0d1117;font:800 11px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}}.activity-icon{{fill:rgba(255,166,87,.2);stroke:rgba(255,166,87,.66);stroke-width:1}}.activity-path{{fill:#f0883e}}@media(prefers-color-scheme:light){{.bg{{fill:#fff}}.card{{fill:#f6f8fa;stroke:#d0d7de}}.title,.section,.label{{fill:#24292f}}.sub,.small{{fill:#57606a}}.edge{{stroke:rgba(9,105,218,.22)}}.pill{{fill:#fff;stroke:#d0d7de}}}}</style><defs><linearGradient id="core" x1="520" y1="280" x2="680" y2="440" gradientUnits="userSpaceOnUse"><stop stop-color="#7ee787"/><stop offset="1" stop-color="#58a6ff"/></linearGradient></defs><rect width="1200" height="760" rx="28" class="bg"/><rect x="32" y="32" width="1136" height="696" rx="26" class="card"/><text x="600" y="82" text-anchor="middle" class="title">GitHub Developer Graph · {esc(USERNAME)}</text><text x="600" y="112" text-anchor="middle" class="sub">Data from GitHub REST API · repos · PRs / issues · public events · generated {esc(data['generated_at'])}</text>{activity(data['events'][:5])}{sides(data['repos'][:7], data['orgs'][:6])}{languages(data['languages'][:7])}<circle cx="600" cy="360" r="86" class="core"/><text x="600" y="345" text-anchor="middle" style="fill:#0d1117;font:800 28px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">{esc(u.get('name') or USERNAME)}</text><text x="600" y="374" text-anchor="middle" style="fill:#0d1117;font:700 14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">@{esc(USERNAME)}</text><text x="600" y="401" text-anchor="middle" style="fill:#0d1117;font:700 12px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">{esc(u.get('public_repos',0))} repos · {esc(u.get('followers',0))} followers</text><text x="600" y="704" text-anchor="middle" class="small">Generated by .github/scripts/generate-developer-graph.py · update via GitHub Actions</text></svg>'''

def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    data = dataset()
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    OUT_SVG.write_text(svg(data), encoding="utf-8")
    print(f"[ok] wrote {OUT_SVG}")
    print(f"[ok] wrote {OUT_JSON}")

if __name__ == "__main__": main()
