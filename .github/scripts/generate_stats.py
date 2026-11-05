"""Generate profile SVG cards (stats, top languages, contribution calendar).

Runs in GitHub Actions and writes the cards to assets/, so the README never
depends on a third-party image service being up.
"""
import json
import os
import sys
import urllib.request
from datetime import date
from html import escape

USER = os.environ.get("GH_USER", "burak-akkas")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT = os.environ.get("OUT_DIR", "assets")

# Tokyo Night palette
BG, TITLE, TEXT, ICON, MUTED = "#1a1b27", "#70a5fd", "#38bdae", "#bf91f3", "#a9b1d6"
LEVELS = ["#24283b", "#0e4429", "#006d32", "#26a641", "#39d353"]
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Sans-Serif"

QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    name
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date } }
      }
    }
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false) {
      pageInfo { hasNextPage endCursor }
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "User-Agent": "profile-stats"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if "errors" in body:
        sys.exit(f"GraphQL error: {body['errors']}")
    return body["data"]["user"]


def fetch():
    user, repos, after = None, [], None
    while True:
        page = graphql({"login": USER, "after": after})
        user = user or page
        repos += page["repositories"]["nodes"]
        info = page["repositories"]["pageInfo"]
        if not info["hasNextPage"]:
            break
        after = info["endCursor"]
    user["repos"] = repos
    return user


def card(width, height, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}">'
        f'<rect width="{width}" height="{height}" rx="6" fill="{BG}"/>{body}</svg>\n'
    )


def stats_svg(u):
    cc = u["contributionsCollection"]
    rows = [
        ("Total stars earned", sum(r["stargazerCount"] for r in u["repos"])),
        ("Commits (last year)", cc["totalCommitContributions"] + cc["restrictedContributionsCount"]),
        ("Total PRs", u["pullRequests"]["totalCount"]),
        ("Total issues", u["issues"]["totalCount"]),
        ("Contributions (last year)", cc["contributionCalendar"]["totalContributions"]),
    ]
    title = escape(f"{u.get('name') or USER}'s GitHub Stats")
    body = f'<text x="25" y="35" fill="{TITLE}" font-size="18" font-weight="600">{title}</text>'
    for i, (label, value) in enumerate(rows):
        y = 70 + i * 24
        body += (
            f'<circle cx="31" cy="{y - 5}" r="5" fill="{ICON}"/>'
            f'<text x="45" y="{y}" fill="{TEXT}" font-size="14" font-weight="600">{label}:</text>'
            f'<text x="290" y="{y}" fill="{TEXT}" font-size="14" font-weight="700">{value:,}</text>'
        )
    return card(400, 195, body)


def langs_svg(u, count=8):
    totals, colors = {}, {}
    for r in u["repos"]:
        for e in r["languages"]["edges"]:
            name = e["node"]["name"]
            totals[name] = totals.get(name, 0) + e["size"]
            colors[name] = e["node"]["color"] or MUTED
    top = sorted(totals.items(), key=lambda kv: -kv[1])[:count]
    total = sum(v for _, v in top) or 1
    width, bar_w = 340, 290
    body = f'<text x="25" y="35" fill="{TITLE}" font-size="18" font-weight="600">Most Used Languages</text>'
    body += f'<clipPath id="bar"><rect x="25" y="52" width="{bar_w}" height="8" rx="4"/></clipPath><g clip-path="url(#bar)">'
    x = 25.0
    for name, size in top:
        w = bar_w * size / total
        body += f'<rect x="{x:.2f}" y="52" width="{w:.2f}" height="8" fill="{colors[name]}"/>'
        x += w
    body += "</g>"
    for i, (name, size) in enumerate(top):
        cx, cy = 25 + (i % 2) * 150, 85 + (i // 2) * 25
        body += (
            f'<circle cx="{cx + 5}" cy="{cy - 4}" r="5" fill="{colors[name]}"/>'
            f'<text x="{cx + 15}" y="{cy}" fill="{MUTED}" font-size="11">'
            f'{escape(name)} {100 * size / total:.2f}%</text>'
        )
    height = 85 + ((len(top) + 1) // 2) * 25
    return card(width, max(height, 120), body)


def calendar_svg(u):
    cal = u["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"]
    peak = max((d["contributionCount"] for w in weeks for d in w["contributionDays"]), default=0) or 1
    cell, gap, left, top = 11, 3, 25, 50
    width = left * 2 + len(weeks) * (cell + gap) - gap
    height = top + 7 * (cell + gap) + 15
    body = (
        f'<text x="{left}" y="32" fill="{TITLE}" font-size="16" font-weight="600">'
        f'{cal["totalContributions"]:,} contributions in the last year</text>'
    )
    for wi, w in enumerate(weeks):
        for d in w["contributionDays"]:
            n = d["contributionCount"]
            level = 0 if n == 0 else min(4, 1 + int(3 * n / peak))
            dow = (date.fromisoformat(d["date"]).weekday() + 1) % 7  # Sunday = 0
            x, y = left + wi * (cell + gap), top + dow * (cell + gap)
            body += (
                f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" fill="{LEVELS[level]}">'
                f'<title>{n} on {d["date"]}</title></rect>'
            )
    return card(width, height, body)


def main():
    if os.environ.get("SAMPLE_JSON"):
        with open(os.environ["SAMPLE_JSON"]) as f:
            user = json.load(f)
    else:
        if not TOKEN:
            sys.exit("GH_TOKEN is not set")
        user = fetch()
    os.makedirs(OUT, exist_ok=True)
    for name, svg in [
        ("stats.svg", stats_svg(user)),
        ("top-langs.svg", langs_svg(user)),
        ("contributions.svg", calendar_svg(user)),
    ]:
        with open(os.path.join(OUT, name), "w") as f:
            f.write(svg)
        print(f"wrote {OUT}/{name}")


if __name__ == "__main__":
    main()
