#!/usr/bin/env python3
"""
GitHub Profile Analyzer — Full Repository Scan
Parcourt TOUS les repositories (paginés) et génère analyse-profile.json.

Usage:
    GITHUB_TOKEN=xxx python analyse-profile.py --username rasata
    python analyse-profile.py --username rasata   # utilise gh CLI
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Module 'requests' requis: pip install requests")
    sys.exit(1)


# ─── GitHub API Client ───────────────────────────────────────────────────────

class GitHubClient:
    API = "https://api.github.com"

    def __init__(self, token: str | None = None):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "GitHub-Profile-Analyzer",
        })
        if token:
            self.session.headers["Authorization"] = f"token {token}"
        self.rate_remaining = None

    def get(self, url: str) -> dict | list | None:
        resp = self.session.get(url)
        self.rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 403:
            print(f"  ⚠ Rate limit or forbidden: {url}")
        elif resp.status_code != 404:
            print(f"  ⚠ HTTP {resp.status_code}: {url}")
        return None

    def get_all_pages(self, url: str, per_page: int = 100) -> list:
        """Fetch every page until exhaustion."""
        items = []
        page = 1
        sep = "&" if "?" in url else "?"
        while True:
            data = self.get(f"{url}{sep}per_page={per_page}&page={page}")
            if not data:
                break
            items.extend(data)
            if len(data) < per_page:
                break
            page += 1
            if page % 5 == 0:
                print(f"    … {len(items)} items fetched (page {page})  [rate left: {self.rate_remaining}]")
        return items

    def graphql(self, query: str) -> dict | None:
        resp = self.session.post(
            f"{self.API}/graphql",
            json={"query": query},
        )
        if resp.status_code == 200:
            return resp.json().get("data")
        print(f"  ⚠ GraphQL error {resp.status_code}")
        return None


# ─── Analyzer ─────────────────────────────────────────────────────────────────

class ProfileAnalyzer:
    def __init__(self, client: GitHubClient, username: str):
        self.gh = client
        self.username = username

    # -- basic profile ---------------------------------------------------------
    def fetch_user(self) -> dict:
        print("→ Fetching user profile…")
        return self.gh.get(f"{GitHubClient.API}/users/{self.username}") or {}

    # -- ALL repos -------------------------------------------------------------
    def fetch_all_repos(self) -> list[dict]:
        print("→ Fetching ALL repositories (this may take a moment)…")
        repos = self.gh.get_all_pages(
            f"{GitHubClient.API}/users/{self.username}/repos?sort=pushed"
        )
        print(f"  ✓ {len(repos)} repositories fetched")
        return repos

    # -- organisations ---------------------------------------------------------
    def fetch_orgs(self) -> list[dict]:
        print("→ Fetching organizations…")
        return self.gh.get_all_pages(f"{GitHubClient.API}/users/{self.username}/orgs")

    # -- starred (count only via Link header) ----------------------------------
    def fetch_starred_count(self) -> int:
        resp = self.gh.session.get(
            f"{GitHubClient.API}/users/{self.username}/starred?per_page=1"
        )
        if resp.status_code != 200:
            return 0
        link = resp.headers.get("Link", "")
        m = re.search(r'page=(\d+)>; rel="last"', link)
        return int(m.group(1)) if m else len(resp.json())

    # -- contributions (GraphQL) -----------------------------------------------
    def fetch_contributions(self) -> dict:
        print("→ Fetching contributions (GraphQL)…")
        data = self.gh.graphql(f"""
        {{
          user(login: "{self.username}") {{
            contributionsCollection {{
              totalCommitContributions
              totalPullRequestContributions
              totalPullRequestReviewContributions
              totalIssueContributions
              totalRepositoryContributions
              contributionCalendar {{
                totalContributions
                weeks {{
                  contributionDays {{
                    contributionCount
                    date
                  }}
                }}
              }}
            }}
            repositoriesContributedTo(first: 100, contributionTypes: [COMMIT, PULL_REQUEST, ISSUE]) {{
              totalCount
              nodes {{
                nameWithOwner
                description
                stargazerCount
                primaryLanguage {{ name }}
              }}
            }}
          }}
        }}
        """)
        if data and data.get("user"):
            return data["user"]
        return {}

    # -- recent events ---------------------------------------------------------
    def fetch_events(self) -> list[dict]:
        print("→ Fetching recent public events…")
        return self.gh.get_all_pages(
            f"{GitHubClient.API}/users/{self.username}/events/public",
            per_page=100,
        )


# ─── Analysis Functions ──────────────────────────────────────────────────────

def analyse_repos(repos: list[dict], username: str) -> dict:
    """Deep analysis of every repository."""

    now = datetime.now(timezone.utc)

    own = [r for r in repos if not r.get("fork")]
    forks = [r for r in repos if r.get("fork")]

    # ── Languages ────────────────────────────────────────────────────────────
    lang_counter = Counter()
    lang_bytes = Counter()  # size as proxy for bytes
    for r in own:
        lang = r.get("language")
        if lang:
            lang_counter[lang] += 1
            lang_bytes[lang] += r.get("size", 0)

    fork_lang_counter = Counter()
    for r in forks:
        lang = r.get("language")
        if lang:
            fork_lang_counter[lang] += 1

    all_lang_counter = Counter()
    for r in repos:
        lang = r.get("language")
        if lang:
            all_lang_counter[lang] += 1

    # ── Stars / Forks ────────────────────────────────────────────────────────
    total_stars = sum(r.get("stargazers_count", 0) for r in own)
    total_forks = sum(r.get("forks_count", 0) for r in own)
    total_watchers = sum(r.get("watchers_count", 0) for r in own)
    total_open_issues = sum(r.get("open_issues_count", 0) for r in own)

    # ── Topics ───────────────────────────────────────────────────────────────
    topic_counter = Counter()
    for r in repos:
        for t in r.get("topics", []):
            topic_counter[t] += 1

    # ── Licenses ─────────────────────────────────────────────────────────────
    license_counter = Counter()
    for r in repos:
        lic = (r.get("license") or {})
        sid = lic.get("spdx_id") if isinstance(lic, dict) else lic
        if sid and sid != "NOASSERTION":
            license_counter[sid] += 1

    # ── Timeline ─────────────────────────────────────────────────────────────
    def parse_dt(s):
        if not s:
            return None
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    creation_dates = sorted(filter(None, (parse_dt(r.get("created_at")) for r in own)))
    push_dates = sorted(filter(None, (parse_dt(r.get("pushed_at")) for r in own)))

    years_active = Counter()
    for d in creation_dates:
        years_active[d.year] += 1

    # repos created per year (all)
    years_all = Counter()
    for r in repos:
        d = parse_dt(r.get("created_at"))
        if d:
            years_all[d.year] += 1

    # ── Top own repos by stars ───────────────────────────────────────────────
    top_starred = sorted(own, key=lambda r: r.get("stargazers_count", 0), reverse=True)[:20]
    top_forked = sorted(own, key=lambda r: r.get("forks_count", 0), reverse=True)[:10]
    recently_pushed = sorted(own, key=lambda r: r.get("pushed_at", ""), reverse=True)[:15]
    largest_repos = sorted(own, key=lambda r: r.get("size", 0), reverse=True)[:10]

    # ── Fork analysis — what projects interest this user ─────────────────────
    notable_forks = sorted(forks, key=lambda r: r.get("stargazers_count", 0), reverse=True)

    # Categorise forks by detected domain
    domain_keywords = {
        "AI / Machine Learning": [
            "llm", "gpt", "ai", "ml", "machine-learning", "deep-learning",
            "neural", "torch", "tensor", "whisper", "detectron", "esrgan",
            "vlm", "openvino", "llama", "fine-tuning", "notebook", "transformer",
        ],
        "AI Agents": [
            "agent", "flowise", "browser-use", "claude", "mcp", "shell-oracle",
            "ai-shell", "claw", "council",
        ],
        "Cybersecurity": [
            "security", "owasp", "pentest", "vulnerability", "cve", "phish",
            "amass", "attack", "exploit", "sniper", "hexstrike", "dependency-check",
        ],
        "Document Processing": [
            "pdf", "document", "layout", "ocr", "doclaynet", "pdfme",
            "stirling", "watermark",
        ],
        "DevOps / Infrastructure": [
            "kubernetes", "kubespray", "docker", "devpod", "coolify", "rudder",
            "codespace", "hocus", "terraform", "ansible",
        ],
        "Blockchain / Web3": [
            "blockchain", "ethereum", "ganache", "web3", "solidity",
        ],
        "Networking / WebRTC": [
            "coturn", "turn", "webrtc", "proxy", "zoraxy", "gfw", "firewall",
        ],
        "Hardware / IoT": [
            "arduino", "oximeter", "nfc", "hce", "cardpeek", "emv", "iot",
        ],
        "Frontend / UI": [
            "react", "vue", "css", "html", "particles", "aloha", "editor",
            "chrome-extension", "pake",
        ],
        "Database": [
            "pouchdb", "alasql", "baserow", "airtable", "sql", "database",
        ],
    }

    fork_domains = defaultdict(list)
    for r in forks:
        name_lower = (r.get("name") or "").lower()
        desc_lower = (r.get("description") or "").lower()
        combined = f"{name_lower} {desc_lower}"
        matched = False
        for domain, keywords in domain_keywords.items():
            if any(kw in combined for kw in keywords):
                fork_domains[domain].append({
                    "name": r["name"],
                    "description": (r.get("description") or "")[:120],
                    "language": r.get("language"),
                    "original_url": r.get("html_url"),
                })
                matched = True
                break
        if not matched:
            fork_domains["Other"].append({
                "name": r["name"],
                "description": (r.get("description") or "")[:120],
                "language": r.get("language"),
            })

    # ── Archived / active ────────────────────────────────────────────────────
    archived_count = sum(1 for r in repos if r.get("archived"))
    has_homepage = sum(1 for r in own if r.get("homepage"))

    # ── Size stats ───────────────────────────────────────────────────────────
    sizes = [r.get("size", 0) for r in repos if r.get("size", 0) > 0]
    total_size_kb = sum(sizes)

    # ── Build result ─────────────────────────────────────────────────────────
    def repo_summary(r):
        return {
            "name": r["name"],
            "description": (r.get("description") or "")[:150],
            "language": r.get("language"),
            "stars": r.get("stargazers_count", 0),
            "forks": r.get("forks_count", 0),
            "size_kb": r.get("size", 0),
            "topics": r.get("topics", []),
            "created_at": r.get("created_at"),
            "pushed_at": r.get("pushed_at"),
            "homepage": r.get("homepage"),
            "license": ((r.get("license") or {}).get("spdx_id") if isinstance(r.get("license"), dict) else r.get("license")),
            "archived": r.get("archived", False),
            "html_url": r.get("html_url"),
        }

    return {
        "counts": {
            "total_repos": len(repos),
            "own_repos": len(own),
            "forked_repos": len(forks),
            "archived_repos": archived_count,
            "repos_with_homepage": has_homepage,
            "total_stars_received": total_stars,
            "total_forks_received": total_forks,
            "total_watchers": total_watchers,
            "total_open_issues": total_open_issues,
        },
        "languages": {
            "own_repos_by_count": dict(lang_counter.most_common()),
            "own_repos_by_size_kb": dict(lang_bytes.most_common()),
            "forked_repos_by_count": dict(fork_lang_counter.most_common()),
            "all_repos_by_count": dict(all_lang_counter.most_common()),
            "unique_languages_count": len(all_lang_counter),
        },
        "topics": dict(topic_counter.most_common(50)),
        "licenses": dict(license_counter.most_common()),
        "timeline": {
            "first_own_repo_created": creation_dates[0].isoformat() if creation_dates else None,
            "latest_own_push": push_dates[-1].isoformat() if push_dates else None,
            "own_repos_created_per_year": dict(sorted(years_active.items())),
            "all_repos_created_per_year": dict(sorted(years_all.items())),
        },
        "storage": {
            "total_size_kb": total_size_kb,
            "total_size_mb": round(total_size_kb / 1024, 1),
            "average_repo_size_kb": round(total_size_kb / max(len(repos), 1), 1),
            "largest_repo_kb": max(sizes) if sizes else 0,
        },
        "top_own_repos_by_stars": [repo_summary(r) for r in top_starred],
        "top_own_repos_by_forks": [repo_summary(r) for r in top_forked],
        "recently_active_own_repos": [repo_summary(r) for r in recently_pushed],
        "largest_own_repos": [repo_summary(r) for r in largest_repos],
        "fork_analysis": {
            "total_forks": len(forks),
            "domains": {
                domain: {
                    "count": len(items),
                    "repos": items[:15],  # cap for readability
                }
                for domain, items in sorted(fork_domains.items(), key=lambda x: -len(x[1]))
            },
        },
    }


def analyse_events(events: list[dict]) -> dict:
    type_counter = Counter()
    repo_activity = Counter()
    for e in events:
        type_counter[e.get("type", "Unknown")] += 1
        repo_activity[e.get("repo", {}).get("name", "unknown")] += 1

    return {
        "total_recent_events": len(events),
        "event_types": dict(type_counter.most_common()),
        "most_active_repos": dict(repo_activity.most_common(10)),
        "events": [
            {
                "type": e.get("type"),
                "repo": e.get("repo", {}).get("name"),
                "date": e.get("created_at"),
                "action": e.get("payload", {}).get("action"),
            }
            for e in events[:30]
        ],
    }


def analyse_contributions(contrib_data: dict) -> dict:
    cc = contrib_data.get("contributionsCollection", {})
    cal = cc.get("contributionCalendar", {})
    contrib_to = contrib_data.get("repositoriesContributedTo", {})

    # longest streak from calendar
    weeks = cal.get("weeks", [])
    all_days = []
    for w in weeks:
        for d in w.get("contributionDays", []):
            all_days.append(d)

    current_streak = 0
    longest_streak = 0
    streak = 0
    for d in all_days:
        if d.get("contributionCount", 0) > 0:
            streak += 1
            longest_streak = max(longest_streak, streak)
        else:
            streak = 0
    current_streak = streak  # streak at end of calendar

    # busiest day
    busiest = max(all_days, key=lambda d: d.get("contributionCount", 0)) if all_days else {}

    return {
        "total_contributions_this_year": cal.get("totalContributions", 0),
        "commits": cc.get("totalCommitContributions", 0),
        "pull_requests": cc.get("totalPullRequestContributions", 0),
        "pull_request_reviews": cc.get("totalPullRequestReviewContributions", 0),
        "issues": cc.get("totalIssueContributions", 0),
        "repositories_created": cc.get("totalRepositoryContributions", 0),
        "contributed_to_count": contrib_to.get("totalCount", 0),
        "contributed_to": [
            {
                "repo": n.get("nameWithOwner"),
                "description": (n.get("description") or "")[:120],
                "stars": n.get("stargazerCount", 0),
                "language": (n.get("primaryLanguage") or {}).get("name"),
            }
            for n in (contrib_to.get("nodes") or [])
        ],
        "streaks": {
            "longest_streak_days": longest_streak,
            "current_streak_days": current_streak,
        },
        "busiest_day": {
            "date": busiest.get("date"),
            "contributions": busiest.get("contributionCount", 0),
        },
    }


# ─── Main ─────────────────────────────────────────────────────────────────────

def get_token() -> str | None:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description="Full GitHub profile analyzer → analyse-profile.json")
    parser.add_argument("--username", "-u", required=True)
    parser.add_argument("--output", "-o", default="analyse-profile.json")
    args = parser.parse_args()

    token = get_token()
    if token:
        print("✓ GitHub token detected")
    else:
        print("⚠ No token — rate limit will be low (60 req/h)")

    client = GitHubClient(token)
    analyzer = ProfileAnalyzer(client, args.username)

    # 1. User profile
    user = analyzer.fetch_user()
    if not user:
        print("✗ Could not fetch user profile")
        sys.exit(1)
    print(f"  ✓ {user.get('name')} — {user.get('public_repos')} public repos")

    # 2. ALL repos
    repos = analyzer.fetch_all_repos()

    # 3. Orgs
    orgs = analyzer.fetch_orgs()
    print(f"  ✓ {len(orgs)} organizations")

    # 4. Starred count
    starred = analyzer.fetch_starred_count()
    print(f"  ✓ {starred} starred repos")

    # 5. Contributions (GraphQL)
    contrib_data = analyzer.fetch_contributions()

    # 6. Events
    events = analyzer.fetch_events()
    print(f"  ✓ {len(events)} recent events")

    # ── Build final JSON ─────────────────────────────────────────────────────
    print("\n→ Analyzing…")
    repo_analysis = analyse_repos(repos, args.username)
    event_analysis = analyse_events(events)
    contrib_analysis = analyse_contributions(contrib_data)

    now = datetime.now(timezone.utc)
    created = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
    account_age_years = round((now - created).days / 365.25, 1)

    result = {
        "_meta": {
            "generated_at": now.isoformat(),
            "generator": "analyse-profile.py",
            "username": args.username,
        },
        "profile": {
            "login": user.get("login"),
            "id": user.get("id"),
            "name": user.get("name"),
            "bio": user.get("bio"),
            "location": user.get("location"),
            "company": user.get("company"),
            "blog": user.get("blog"),
            "twitter_username": user.get("twitter_username"),
            "hireable": user.get("hireable"),
            "avatar_url": user.get("avatar_url"),
            "html_url": user.get("html_url"),
            "followers": user.get("followers"),
            "following": user.get("following"),
            "public_repos": user.get("public_repos"),
            "public_gists": user.get("public_gists"),
            "created_at": user.get("created_at"),
            "account_age_years": account_age_years,
            "starred_repos_count": starred,
        },
        "organizations": [
            {"login": o.get("login"), "name": o.get("description") or o.get("login"), "avatar": o.get("avatar_url")}
            for o in orgs
        ],
        "contributions": contrib_analysis,
        "repositories": repo_analysis,
        "recent_activity": event_analysis,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Analysis saved to {args.output}")
    print(f"  {repo_analysis['counts']['total_repos']} repos analyzed")
    print(f"  {repo_analysis['languages']['unique_languages_count']} languages detected")
    print(f"  {repo_analysis['fork_analysis']['total_forks']} forks across {len(repo_analysis['fork_analysis']['domains'])} domains")
    print(f"  {contrib_analysis['total_contributions_this_year']} contributions this year")


if __name__ == "__main__":
    main()
