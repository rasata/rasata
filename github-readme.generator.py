#!/usr/bin/env python3
"""
GitHub Profile README Generator
Génère un README.md personnalisé basé sur votre profil GitHub.

Prérequis:
    pip install requests

Usage:
    # Avec GitHub CLI authentifié:
    python github_readme_generator.py

    # Ou avec un token:
    GITHUB_TOKEN=your_token python github_readme_generator.py

    # Pour un utilisateur spécifique:
    python github_readme_generator.py --username rasata
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from typing import Any

try:
    import requests
except ImportError:
    print("❌ Le module 'requests' est requis.")
    print("   Installez-le avec: pip install requests")
    sys.exit(1)


class GitHubProfileAnalyzer:
    """Analyse un profil GitHub et génère un README."""

    def __init__(self, token: str | None = None):
        self.token = token
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"token {token}"
        self.session.headers["Accept"] = "application/vnd.github.v3+json"
        self.session.headers["User-Agent"] = "GitHub-README-Generator"

    def _get(self, url: str) -> dict | list | None:
        """Effectue une requête GET sur l'API GitHub."""
        try:
            response = self.session.get(url)
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 403:
                print(f"⚠️  Rate limit atteint ou accès refusé pour {url}")
                return None
            elif response.status_code == 404:
                return None
            else:
                print(f"⚠️  Erreur {response.status_code} pour {url}")
                return None
        except requests.RequestException as e:
            print(f"❌ Erreur réseau: {e}")
            return None

    def _get_paginated(self, url: str, max_items: int = 100) -> list:
        """Récupère des données paginées."""
        items = []
        page = 1
        per_page = min(100, max_items)

        while len(items) < max_items:
            paginated_url = f"{url}{'&' if '?' in url else '?'}per_page={per_page}&page={page}"
            data = self._get(paginated_url)
            if not data:
                break
            items.extend(data)
            if len(data) < per_page:
                break
            page += 1

        return items[:max_items]

    def get_user_info(self, username: str) -> dict | None:
        """Récupère les informations de l'utilisateur."""
        return self._get(f"https://api.github.com/users/{username}")

    def get_repos(self, username: str, max_repos: int = 100) -> list:
        """Récupère les repositories de l'utilisateur."""
        return self._get_paginated(
            f"https://api.github.com/users/{username}/repos?sort=updated",
            max_repos
        )

    def get_starred_repos(self, username: str) -> int:
        """Compte le nombre de repos starés."""
        try:
            response = self.session.get(
                f"https://api.github.com/users/{username}/starred?per_page=1"
            )
            if response.status_code != 200:
                return 0
            # Parse le header Link pour trouver le total
            link_header = response.headers.get("Link", "")
            if 'rel="last"' in link_header:
                match = re.search(r'page=(\d+)>; rel="last"', link_header)
                if match:
                    return int(match.group(1))
            data = response.json()
            return len(data) if data else 0
        except requests.RequestException:
            return 0

    def analyze_languages(self, repos: list) -> dict:
        """Analyse les langages utilisés dans les repos."""
        languages = Counter()
        for repo in repos:
            if repo.get("language") and not repo.get("fork"):
                languages[repo["language"]] += 1
        return dict(languages.most_common(10))

    def get_top_repos(self, repos: list, limit: int = 6) -> list:
        """Récupère les repos les plus populaires (non-forks)."""
        own_repos = [r for r in repos if not r.get("fork")]
        # Trier par stars puis par date de mise à jour
        sorted_repos = sorted(
            own_repos,
            key=lambda x: (x.get("stargazers_count", 0), x.get("updated_at", "")),
            reverse=True
        )
        return sorted_repos[:limit]

    def get_recent_repos(self, repos: list, limit: int = 5) -> list:
        """Récupère les repos récemment mis à jour (non-forks)."""
        own_repos = [r for r in repos if not r.get("fork")]
        sorted_repos = sorted(
            own_repos,
            key=lambda x: x.get("pushed_at", ""),
            reverse=True
        )
        return sorted_repos[:limit]

    def calculate_stats(self, repos: list) -> dict:
        """Calcule des statistiques sur les repos."""
        own_repos = [r for r in repos if not r.get("fork")]
        forked_repos = [r for r in repos if r.get("fork")]

        total_stars = sum(r.get("stargazers_count", 0) for r in own_repos)
        total_forks = sum(r.get("forks_count", 0) for r in own_repos)

        return {
            "total_repos": len(repos),
            "own_repos": len(own_repos),
            "forked_repos": len(forked_repos),
            "total_stars": total_stars,
            "total_forks": total_forks,
        }


class ReadmeGenerator:
    """Génère le contenu du README."""

    # Mapping des langages vers leurs badges
    LANGUAGE_BADGES = {
        "JavaScript": ("JavaScript", "F7DF1E", "javascript", "black"),
        "TypeScript": ("TypeScript", "3178C6", "typescript", "white"),
        "Python": ("Python", "3776AB", "python", "white"),
        "Java": ("Java", "007396", "openjdk", "white"),
        "C++": ("C++", "00599C", "cplusplus", "white"),
        "C": ("C", "A8B9CC", "c", "black"),
        "C#": ("C%23", "239120", "csharp", "white"),
        "Go": ("Go", "00ADD8", "go", "white"),
        "Rust": ("Rust", "000000", "rust", "white"),
        "Ruby": ("Ruby", "CC342D", "ruby", "white"),
        "PHP": ("PHP", "777BB4", "php", "white"),
        "Swift": ("Swift", "FA7343", "swift", "white"),
        "Kotlin": ("Kotlin", "7F52FF", "kotlin", "white"),
        "Dart": ("Dart", "0175C2", "dart", "white"),
        "Shell": ("Shell", "4EAA25", "gnu-bash", "white"),
        "HTML": ("HTML5", "E34F26", "html5", "white"),
        "CSS": ("CSS3", "1572B6", "css3", "white"),
        "Vue": ("Vue.js", "4FC08D", "vue.js", "white"),
        "React": ("React", "61DAFB", "react", "black"),
        "Scala": ("Scala", "DC322F", "scala", "white"),
        "Elixir": ("Elixir", "4B275F", "elixir", "white"),
        "Haskell": ("Haskell", "5D4F85", "haskell", "white"),
        "Lua": ("Lua", "2C2D72", "lua", "white"),
        "R": ("R", "276DC3", "r", "white"),
        "MATLAB": ("MATLAB", "0076A8", "mathworks", "white"),
        "Jupyter Notebook": ("Jupyter", "F37626", "jupyter", "white"),
        "Dockerfile": ("Docker", "2496ED", "docker", "white"),
    }

    def __init__(self, user_info: dict, repos: list, languages: dict, stats: dict,
                 top_repos: list, recent_repos: list):
        self.user = user_info
        self.repos = repos
        self.languages = languages
        self.stats = stats
        self.top_repos = top_repos
        self.recent_repos = recent_repos

    def _generate_badge(self, lang: str) -> str:
        """Génère un badge shields.io pour un langage."""
        if lang in self.LANGUAGE_BADGES:
            name, color, logo, logo_color = self.LANGUAGE_BADGES[lang]
            return f"![{lang}](https://img.shields.io/badge/-{name}-{color}?style=flat-square&logo={logo}&logoColor={logo_color})"
        else:
            # Badge générique
            safe_name = lang.replace(" ", "%20").replace("#", "%23")
            return f"![{lang}](https://img.shields.io/badge/-{safe_name}-333333?style=flat-square)"

    def _format_number(self, n: int) -> str:
        """Formate un nombre (1234 -> 1.2k)."""
        if n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)

    def _get_repo_emoji(self, repo: dict) -> str:
        """Retourne un emoji basé sur le type de repo."""
        lang = (repo.get("language") or "").lower()
        topics = [t.lower() for t in repo.get("topics", [])]

        if any(t in topics for t in ["cli", "terminal", "shell"]):
            return "🖥️"
        if any(t in topics for t in ["api", "server", "backend"]):
            return "⚙️"
        if any(t in topics for t in ["web", "frontend", "website"]):
            return "🌐"
        if any(t in topics for t in ["mobile", "ios", "android"]):
            return "📱"
        if any(t in topics for t in ["ai", "ml", "machine-learning"]):
            return "🤖"
        if any(t in topics for t in ["data", "analytics"]):
            return "📊"
        if any(t in topics for t in ["security", "crypto"]):
            return "🔐"
        if any(t in topics for t in ["game", "gaming"]):
            return "🎮"
        if any(t in topics for t in ["tool", "utility"]):
            return "🛠️"
        if any(t in topics for t in ["automation", "bot"]):
            return "🤖"

        # Par langage
        emoji_map = {
            "javascript": "📜",
            "typescript": "💠",
            "python": "🐍",
            "go": "🔷",
            "rust": "🦀",
            "ruby": "💎",
            "java": "☕",
            "swift": "🍎",
            "kotlin": "🎯",
            "html": "🌐",
            "css": "🎨",
            "shell": "🐚",
            "dockerfile": "🐳",
        }
        return emoji_map.get(lang, "📦")

    def generate(self) -> str:
        """Génère le README complet."""
        username = self.user["login"]
        name = self.user.get("name") or username
        bio = self.user.get("bio") or ""
        location = self.user.get("location") or ""
        company = self.user.get("company") or ""
        blog = self.user.get("blog") or ""
        twitter = self.user.get("twitter_username") or ""
        hireable = self.user.get("hireable")

        sections = []

        # Header
        header_parts = []
        if location:
            header_parts.append(f"📍 **{location}**")
        if company:
            header_parts.append(f"🏢 **{company}**")
        if hireable:
            header_parts.append("💼 **Open to work**")

        header = f"# Hi, I'm {name.split()[0] if name else username} 👋\n\n"
        if header_parts:
            header += " | ".join(header_parts) + "\n\n"

        sections.append(header)

        # Badges des langages
        if self.languages:
            badges = [self._generate_badge(lang) for lang in list(self.languages.keys())[:8]]
            sections.append(" ".join(badges) + "\n")

        # Bio
        if bio:
            sections.append(f"\n> {bio}\n")

        # Stats rapides
        stats_line = []
        if self.stats["total_stars"] > 0:
            stats_line.append(f"⭐ {self._format_number(self.stats['total_stars'])} stars")
        stats_line.append(f"📦 {self.stats['own_repos']} repos")
        if self.user.get("followers", 0) > 0:
            stats_line.append(f"👥 {self._format_number(self.user['followers'])} followers")

        if stats_line:
            sections.append("\n" + " • ".join(stats_line) + "\n")

        # Projets populaires
        if self.top_repos:
            sections.append("\n## 🔥 Featured Projects\n\n")
            for repo in self.top_repos:
                emoji = self._get_repo_emoji(repo)
                name = repo["name"]
                desc = repo.get("description") or "No description"
                # Tronquer la description si trop longue
                if len(desc) > 80:
                    desc = desc[:77] + "..."
                stars = repo.get("stargazers_count", 0)
                lang = repo.get("language") or ""

                star_badge = f"⭐ {stars}" if stars > 0 else ""
                lang_badge = f"`{lang}`" if lang else ""

                sections.append(
                    f"- {emoji} **[{name}](https://github.com/{username}/{name})** - {desc} {star_badge} {lang_badge}\n"
                )

        # Activité récente
        if self.recent_repos and self.recent_repos != self.top_repos:
            sections.append("\n## 🕐 Recent Activity\n\n")
            for repo in self.recent_repos[:5]:
                name = repo["name"]
                pushed = repo.get("pushed_at", "")
                if pushed:
                    date = datetime.fromisoformat(pushed.replace("Z", "+00:00")) if pushed.endswith("Z") else datetime.fromisoformat(pushed)
                    date_str = date.strftime("%b %d, %Y")
                else:
                    date_str = ""
                sections.append(f"- [{name}](https://github.com/{username}/{name}) - Updated {date_str}\n")

        # GitHub Activity Graph
        sections.append(f"\n## 📊 GitHub Activity\n\n")
        sections.append(f"[![GitHub Contribution Graph](https://ghchart.rshah.org/{username})](https://github.com/{username})\n\n")

        # Stats cards
        sections.append('<p align="center">\n')
        sections.append(f'  <img src="https://github-readme-stats.vercel.app/api?username={username}&show_icons=true&theme=default&hide_border=true&count_private=true" alt="GitHub Stats" />\n')
        sections.append('</p>\n\n')

        sections.append('<p align="center">\n')
        sections.append(f'  <img src="https://github-readme-stats.vercel.app/api/top-langs/?username={username}&layout=compact&hide_border=true&langs_count=8" alt="Top Languages" />\n')
        sections.append('</p>\n')

        # Tech Stack
        if self.languages:
            sections.append("\n## 🛠️ Tech Stack\n\n")
            lang_list = " • ".join(list(self.languages.keys())[:10])
            sections.append(f"```\n{lang_list}\n```\n")

        # Connect
        sections.append("\n## 📫 Connect\n\n")
        connect_badges = []

        if blog:
            if not blog.startswith("http"):
                blog = f"https://{blog}"
            domain = blog.replace("https://", "").replace("http://", "").split("/")[0]
            connect_badges.append(
                f"[![Website](https://img.shields.io/badge/-{domain}-FF5722?style=flat-square&logo=google-chrome&logoColor=white)]({blog})"
            )

        if twitter:
            connect_badges.append(
                f"[![Twitter](https://img.shields.io/badge/-@{twitter}-1DA1F2?style=flat-square&logo=twitter&logoColor=white)](https://twitter.com/{twitter})"
            )

        connect_badges.append(
            f"[![GitHub](https://img.shields.io/badge/-Follow-181717?style=flat-square&logo=github&logoColor=white)](https://github.com/{username})"
        )

        sections.append(" ".join(connect_badges) + "\n")

        # Footer
        sections.append("\n---\n\n")
        sections.append('<p align="center">\n')
        sections.append(f'  <img src="https://komarev.com/ghpvc/?username={username}&color=blueviolet&style=flat-square" alt="Profile views" />\n')
        sections.append('</p>\n')

        return "".join(sections)


def get_token_from_gh_cli() -> str | None:
    """Récupère le token depuis GitHub CLI si disponible."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def get_username_from_gh_cli() -> str | None:
    """Récupère le username depuis GitHub CLI si disponible."""
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Génère un README.md pour votre profil GitHub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  %(prog)s                           # Utilise gh CLI pour l'auth
  %(prog)s --username rasata         # Spécifie un utilisateur
  %(prog)s -o profile-readme.md      # Spécifie le fichier de sortie
  GITHUB_TOKEN=xxx %(prog)s          # Utilise un token personnalisé
        """
    )
    parser.add_argument(
        "--username", "-u",
        help="Nom d'utilisateur GitHub (auto-détecté si gh CLI est configuré)"
    )
    parser.add_argument(
        "--output", "-o",
        default="README.md",
        help="Fichier de sortie (défaut: README.md)"
    )
    parser.add_argument(
        "--max-repos",
        type=int,
        default=100,
        help="Nombre max de repos à analyser (défaut: 100)"
    )

    args = parser.parse_args()

    print("🔍 GitHub Profile README Generator\n")

    # Récupération du token
    token = os.environ.get("GITHUB_TOKEN") or get_token_from_gh_cli()
    if token:
        print("✅ Token GitHub détecté")
    else:
        print("⚠️  Pas de token GitHub trouvé (rate limit réduit)")
        print("   Conseil: installez gh CLI et faites 'gh auth login'\n")

    # Récupération du username
    username = args.username
    if not username:
        username = get_username_from_gh_cli()
        if username:
            print(f"✅ Utilisateur détecté: {username}")
        else:
            print("❌ Impossible de détecter l'utilisateur.")
            print("   Spécifiez --username ou configurez gh CLI")
            sys.exit(1)

    print(f"\n📊 Analyse du profil de {username}...")

    # Analyse
    analyzer = GitHubProfileAnalyzer(token)

    user_info = analyzer.get_user_info(username)
    if not user_info:
        print(f"❌ Impossible de récupérer les infos de {username}")
        sys.exit(1)

    print(f"   ├── Nom: {user_info.get('name') or username}")
    print(f"   ├── Followers: {user_info.get('followers', 0)}")
    print(f"   └── Public repos: {user_info.get('public_repos', 0)}")

    print(f"\n📦 Récupération des repositories...")
    repos = analyzer.get_repos(username, args.max_repos)
    print(f"   └── {len(repos)} repos récupérés")

    print(f"\n🔬 Analyse des données...")
    languages = analyzer.analyze_languages(repos)
    stats = analyzer.calculate_stats(repos)
    top_repos = analyzer.get_top_repos(repos)
    recent_repos = analyzer.get_recent_repos(repos)

    print(f"   ├── Langages: {', '.join(list(languages.keys())[:5])}")
    print(f"   ├── Total stars: {stats['total_stars']}")
    print(f"   └── Top repo: {top_repos[0]['name'] if top_repos else 'N/A'}")

    # Génération
    print(f"\n📝 Génération du README...")
    generator = ReadmeGenerator(
        user_info, repos, languages, stats, top_repos, recent_repos
    )
    readme_content = generator.generate()

    # Sauvegarde
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"\n✅ README généré: {args.output}")
    print(f"\n📋 Prochaines étapes:")
    print(f"   1. Vérifiez le contenu: cat {args.output}")
    print(f"   2. Créez/mettez à jour le repo: {username}/{username}")
    print(f"   3. Copiez le README dans ce repo")
    print(f"   4. Commit et push!")


if __name__ == "__main__":
    main()
