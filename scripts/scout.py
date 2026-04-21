"""
iOS App Idea Scout
Weekly automated research system that collects user problems and trends,
then uses Gemini to synthesize iOS app opportunities.
"""

import os
import json
import time
import datetime
from pathlib import Path
from typing import List, Dict

import requests
import feedparser
import google.generativeai as genai


# ---------- CONFIG ----------

# Reddit subreddits to monitor
# Mix of: (a) direct app-request subs, (b) pain-point rich communities, (c) early-adopter/tech
SUBREDDITS = [
    # Direct app requests & ideas
    "AppIdeas", "SomebodyMakeThis", "lightbulb",
    # iOS / Apple ecosystem
    "iphone", "apple", "iosapps", "shortcuts",
    # Productivity & life pain points (fertile ground for iOS apps)
    "productivity", "getdisciplined", "ADHD", "selfimprovement",
    # Indie / maker signals
    "SideProject", "indiehackers", "Entrepreneur",
    # Niches that pay well on iOS
    "fitness", "running", "loseit", "personalfinance", "Parenting",
]

POSTS_PER_SUB = 7    # top posts of the week per subreddit (was 10)
COMMENTS_PER_POST = 3  # top comments to capture user voice (was 5)

# Hacker News
HN_TOP_COUNT = 15   # was 20

# App Store RSS feeds (US, by genre)
# Genre IDs: 6007=Productivity, 6002=Utilities, 6005=SocialNetworking,
# 6013=HealthFitness, 6023=Food, 6017=Education, 6000=Business, 6012=Lifestyle
APPSTORE_GENRES = {
    "Productivity": 6007,
    "Utilities": 6002,
    "HealthFitness": 6013,
    "Lifestyle": 6012,
    "Education": 6017,
}
APPSTORE_LIMIT = 15  # top N per genre (was 25)

# Review scraping: for each genre, scrape low-star reviews from top apps
# This is where the real gold is — actual users complaining about what existing apps fail at
REVIEW_APPS_PER_GENRE = 3      # scrape reviews for top N apps per genre (was 5)
REVIEW_PAGES_PER_APP = 2        # iTunes RSS paginates; each page = ~50 reviews (was 3)
LOW_STAR_THRESHOLD = 3          # include reviews with rating <= this
MIN_REVIEW_LENGTH = 80          # filter out "meh" one-liners with no signal
MAX_REVIEWS_TOTAL = 60          # hard cap to prevent prompt bloat

# Gemini
# gemini-2.5-flash: 10 RPM, 250 RPD, more generous TPM than Pro on free tier.
# Quality is more than sufficient for this analysis task.
# If you want to try Pro later, switch to "gemini-2.5-pro" (5 RPM, 100 RPD, tighter TPM)
GEMINI_MODEL = "gemini-2.5-flash"


# ---------- COLLECTORS ----------

def collect_reddit() -> List[Dict]:
    """
    Pull top weekly posts + top comments using Reddit's public JSON endpoints.

    No API key required — just append .json to any Reddit URL. This works as long
    as we send a proper User-Agent (Reddit throttles generic/default agents harshly).

    Endpoints:
      https://www.reddit.com/r/{sub}/top.json?t=week&limit=N
      https://www.reddit.com/r/{sub}/comments/{post_id}.json?limit=N
    """
    headers = {
        # Reddit requires a unique, descriptive User-Agent or it will block/throttle.
        # Format per Reddit's guidelines: <platform>:<app ID>:<version> (by /u/<username>)
        "User-Agent": "github-actions:ios-idea-scout:1.0 (personal research use)"
    }

    out = []
    for sub_name in SUBREDDITS:
        try:
            # 1) fetch top posts of the week
            posts_url = (
                f"https://www.reddit.com/r/{sub_name}/top.json"
                f"?t=week&limit={POSTS_PER_SUB}"
            )
            r = requests.get(posts_url, headers=headers, timeout=15)
            if r.status_code != 200:
                print(f"[reddit] {sub_name} returned {r.status_code}")
                time.sleep(2)
                continue

            posts = r.json().get("data", {}).get("children", [])
            for post_wrap in posts:
                post = post_wrap.get("data", {})
                if post.get("stickied") or post.get("score", 0) < 5:
                    continue

                post_id = post.get("id")
                permalink = post.get("permalink", "")

                # 2) fetch top comments for this post
                top_comments = []
                if post_id:
                    try:
                        comments_url = (
                            f"https://www.reddit.com/r/{sub_name}/comments/{post_id}.json"
                            f"?limit={COMMENTS_PER_POST}&sort=top"
                        )
                        c_resp = requests.get(comments_url, headers=headers, timeout=15)
                        if c_resp.status_code == 200:
                            # comments endpoint returns [post, comments]
                            c_data = c_resp.json()
                            if len(c_data) > 1:
                                for c_wrap in c_data[1].get("data", {}).get("children", []):
                                    c = c_wrap.get("data", {})
                                    body = c.get("body", "")
                                    if body and len(body) > 20:
                                        top_comments.append(body[:500])
                                    if len(top_comments) >= COMMENTS_PER_POST:
                                        break
                        time.sleep(1)  # be polite
                    except Exception as e:
                        print(f"[reddit] comments for {post_id} failed: {e}")

                out.append({
                    "source": f"r/{sub_name}",
                    "title": post.get("title", ""),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "selftext": (post.get("selftext") or "")[:1000],
                    "url": f"https://reddit.com{permalink}",
                    "top_comments": top_comments,
                })
            time.sleep(2)  # pause between subreddits to stay well within rate limits
        except Exception as e:
            print(f"[reddit] {sub_name} failed: {e}")
            time.sleep(2)

    print(f"[reddit] collected {len(out)} posts")
    return out


def collect_hackernews() -> List[Dict]:
    """Pull current HN top stories."""
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        ).json()[:HN_TOP_COUNT]
    except Exception as e:
        print(f"[hn] top stories failed: {e}")
        return []

    out = []
    for sid in ids:
        try:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=10
            ).json()
            if not item or item.get("type") != "story":
                continue
            out.append({
                "source": "HackerNews",
                "title": item.get("title", ""),
                "score": item.get("score", 0),
                "num_comments": item.get("descendants", 0),
                "url": item.get("url") or f"https://news.ycombinator.com/item?id={sid}",
            })
        except Exception:
            continue
    print(f"[hn] collected {len(out)} stories")
    return out


def collect_appstore() -> List[Dict]:
    """Pull App Store top free apps per genre via RSS."""
    out = []
    for genre_name, genre_id in APPSTORE_GENRES.items():
        url = (
            f"https://itunes.apple.com/us/rss/topfreeapplications/"
            f"limit={APPSTORE_LIMIT}/genre={genre_id}/json"
        )
        try:
            data = requests.get(url, timeout=15).json()
            entries = data.get("feed", {}).get("entry", [])
            for rank, entry in enumerate(entries, 1):
                # Extract app ID from the entry id URL
                # Format: https://apps.apple.com/us/app/name/id1234567890?...
                app_id = ""
                try:
                    id_attrs = entry.get("id", {}).get("attributes", {})
                    app_id = id_attrs.get("im:id", "")
                except Exception:
                    pass

                out.append({
                    "source": f"AppStore-{genre_name}",
                    "genre": genre_name,
                    "rank": rank,
                    "app_id": app_id,
                    "name": entry.get("im:name", {}).get("label", ""),
                    "artist": entry.get("im:artist", {}).get("label", ""),
                    "summary": (entry.get("summary", {}) or {}).get("label", "")[:500],
                })
        except Exception as e:
            print(f"[appstore] {genre_name} failed: {e}")
    print(f"[appstore] collected {len(out)} apps")
    return out


def collect_reviews(appstore_data: List[Dict]) -> List[Dict]:
    """
    Scrape low-star reviews for top apps using iTunes RSS customer reviews feed.

    Endpoint (no auth required):
      https://itunes.apple.com/us/rss/customerreviews/page={N}/id={APP_ID}/sortby=mostrecent/json

    Returns list of low-rated reviews with app context — these are raw user complaints
    about existing apps, which are the highest-signal input for finding app gaps.
    """
    # Pick top N apps per genre to scrape
    by_genre: Dict[str, List[Dict]] = {}
    for app in appstore_data:
        by_genre.setdefault(app["genre"], []).append(app)

    targets = []
    for genre, apps in by_genre.items():
        # sort by rank ascending and take top N with a valid app_id
        apps_sorted = sorted(apps, key=lambda x: x["rank"])
        for app in apps_sorted:
            if app.get("app_id"):
                targets.append(app)
                if sum(1 for t in targets if t["genre"] == genre) >= REVIEW_APPS_PER_GENRE:
                    break

    out = []
    for app in targets:
        app_id = app["app_id"]
        app_name = app["name"]
        genre = app["genre"]

        for page in range(1, REVIEW_PAGES_PER_APP + 1):
            url = (
                f"https://itunes.apple.com/us/rss/customerreviews/"
                f"page={page}/id={app_id}/sortby=mostrecent/json"
            )
            try:
                r = requests.get(url, timeout=15)
                if r.status_code != 200:
                    break
                data = r.json()
                entries = data.get("feed", {}).get("entry", [])
                # First entry on page 1 is often the app metadata, not a review — skip if no im:rating
                for entry in entries:
                    rating_obj = entry.get("im:rating")
                    if not rating_obj:
                        continue
                    try:
                        rating = int(rating_obj.get("label", "5"))
                    except (ValueError, TypeError):
                        continue

                    if rating > LOW_STAR_THRESHOLD:
                        continue

                    title = (entry.get("title", {}) or {}).get("label", "")
                    content = (entry.get("content", {}) or {}).get("label", "")

                    if len(content) < MIN_REVIEW_LENGTH:
                        continue

                    out.append({
                        "source": f"Review-{genre}",
                        "app_name": app_name,
                        "app_genre": genre,
                        "rating": rating,
                        "title": title[:150],
                        "content": content[:1000],
                    })
                time.sleep(0.5)  # be polite to Apple's servers
            except Exception as e:
                print(f"[reviews] {app_name} page {page} failed: {e}")
                break

    # Sort by rating (lowest first — 1-stars are richest) then cap total to prevent prompt bloat
    out.sort(key=lambda r: r["rating"])
    if len(out) > MAX_REVIEWS_TOTAL:
        print(f"[reviews] trimming from {len(out)} to {MAX_REVIEWS_TOTAL} (lowest-rated first)")
        out = out[:MAX_REVIEWS_TOTAL]

    print(f"[reviews] collected {len(out)} low-star reviews from {len(targets)} apps")
    return out


def collect_producthunt() -> List[Dict]:
    """Pull this week's Product Hunt launches via public RSS."""
    out = []
    try:
        feed = feedparser.parse("https://www.producthunt.com/feed")
        for entry in feed.entries[:30]:
            out.append({
                "source": "ProductHunt",
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:500],
                "url": entry.get("link", ""),
            })
    except Exception as e:
        print(f"[ph] failed: {e}")
    print(f"[ph] collected {len(out)} launches")
    return out


# ---------- ANALYSIS ----------

ANALYSIS_PROMPT = """You are a senior iOS product strategist helping a solo indie developer who ships 1-2 apps per year. Your job is to analyze this week's signals from US-based sources and surface the most promising iOS app opportunities.

# CONTEXT ON THE DEVELOPER
- Solo indie dev, ships 1-2 iOS apps per year
- Market: US
- Can realistically build an MVP in 1-3 months
- Prefers paid-up-front or subscription apps over ad-based
- Wants ideas that leverage iOS-native advantages (HealthKit, Shortcuts, WidgetKit, Live Activities, Apple Intelligence, on-device ML, etc.)

# RAW SIGNALS (this week)

## Reddit posts & user voice
{reddit}

## Hacker News top stories
{hn}

## App Store top charts (what's ranking now)
{appstore}

## LOW-STAR APP STORE REVIEWS (⭐️ HIGHEST SIGNAL — these are people who PAID or DOWNLOADED and are frustrated; every complaint is a potential feature gap or new app opportunity)
{reviews}

## Product Hunt this week
{producthunt}

# YOUR TASK

Produce a weekly intelligence report in the following exact structure. Be specific, ground every claim in the raw signals above, and cite sources inline (e.g., "per r/ADHD thread on X", "AppStore Productivity #3", "1-star review on [AppName]"). Avoid generic advice.

## 1. User Pain Patterns This Week
Identify 5-7 RECURRING, SPECIFIC pain points that appear across multiple sources. For each:
- The pain in one sentence (user's words if possible)
- Which sources mentioned it (with evidence — weight low-star reviews heavily, they reveal what shipped apps are missing)
- Why current solutions fail

## 2. Competitive Weakness Analysis (NEW — from low-star reviews)
Based on the low-star reviews specifically, identify 3-5 top apps that have exploitable weaknesses:
- **App Name** and genre
- **Recurring complaint patterns** from the reviews (quote or paraphrase 2-3 specific review points)
- **What a competitor app could do better** — be specific about the feature/UX gap
- **Is this a whole-app opportunity or just a feature opportunity?**

## 3. Market Signals
- What's climbing the App Store charts and why
- Notable Product Hunt launches and what gap they target
- Tech trends from HN that could enable new iOS app categories

## 4. Top 5 iOS App Opportunities
Rank 5 concrete app ideas best matched to a solo dev with 1-3 month MVP scope. Prioritize ideas that are backed by BOTH a pain pattern AND a competitive weakness from the reviews. For EACH:
- **Name (working title)**
- **One-liner** (what it does)
- **Target user** (specific, not "everyone")
- **Core pain it solves** (tied to signals above — cite the specific reviews/posts)
- **Why iOS-native matters** (specific iOS capability leveraged)
- **MVP scope** (3-5 bullet features achievable in 90 days solo)
- **Monetization** (specific: $X one-time, $Y/mo, freemium with what limit)
- **Signal strength** (Strong / Moderate / Weak) with justification
- **Competition check** (which existing iOS apps are closest? what's the gap based on reviews?)
- **Risks / open questions**

## 5. Ideas to SKIP This Week
2-3 trending topics that look tempting but are bad bets for this dev profile. Explain why.

## 6. This Week's Bet
If forced to start building ONE idea Monday morning, which and why.

Be direct, opinionated, and specific. No hedging like "it depends". This is a working document for a shipping developer."""


def build_prompt(reddit_data, hn_data, appstore_data, ph_data, reviews_data) -> str:
    def fmt_reddit(items):
        lines = []
        for r in items:
            lines.append(f"[{r['source']}] ({r['score']} pts, {r['num_comments']} comments) {r['title']}")
            if r.get("selftext"):
                lines.append(f"  Body: {r['selftext'][:400]}")
            for c in r.get("top_comments", [])[:3]:
                lines.append(f"  Comment: {c[:300]}")
        return "\n".join(lines) if lines else "(no data)"

    def fmt_hn(items):
        return "\n".join(
            f"[{i['score']} pts] {i['title']} — {i.get('url','')}" for i in items
        ) or "(no data)"

    def fmt_appstore(items):
        return "\n".join(
            f"[{i['source']} #{i['rank']}] {i['name']} by {i['artist']}" for i in items
        ) or "(no data)"

    def fmt_ph(items):
        return "\n".join(
            f"{i['title']}: {i['summary'][:200]}" for i in items
        ) or "(no data)"

    def fmt_reviews(items):
        # Group by app so the model can see patterns per app
        by_app: Dict[str, List[Dict]] = {}
        for r in items:
            key = f"{r['app_name']} ({r['app_genre']})"
            by_app.setdefault(key, []).append(r)

        lines = []
        for app_key, reviews in by_app.items():
            lines.append(f"\n### {app_key} — {len(reviews)} low-star reviews")
            for r in reviews:
                lines.append(f"  [{r['rating']}⭐] {r['title']}")
                lines.append(f"    \"{r['content'][:500]}\"")
        return "\n".join(lines) if lines else "(no data)"

    return ANALYSIS_PROMPT.format(
        reddit=fmt_reddit(reddit_data),
        hn=fmt_hn(hn_data),
        appstore=fmt_appstore(appstore_data),
        reviews=fmt_reviews(reviews_data),
        producthunt=fmt_ph(ph_data),
    )


def analyze_with_gemini(prompt: str) -> str:
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel(GEMINI_MODEL)

    # Retry with backoff on rate limit errors (free tier is strict on TPM)
    max_retries = 4
    for attempt in range(max_retries):
        try:
            resp = model.generate_content(
                prompt,
                generation_config={"temperature": 0.4, "max_output_tokens": 8192},
            )
            return resp.text
        except Exception as e:
            err_str = str(e)
            # ResourceExhausted / 429 / quota errors — wait and retry
            if any(s in err_str for s in ["429", "ResourceExhausted", "quota", "RATE_LIMIT"]):
                wait = 30 * (attempt + 1)  # 30s, 60s, 90s, 120s
                print(f"[gemini] rate limited (attempt {attempt+1}/{max_retries}), waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Gemini rate limit: max retries exceeded")


# ---------- NOTIFY ----------

def send_telegram(text: str):
    """Optional: send a short summary via Telegram bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("[telegram] skipped (no token)")
        return
    # Telegram caps at 4096 chars per msg
    preview = text[:3800] + "\n\n... (full report in repo)"
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": preview, "parse_mode": "Markdown"},
            timeout=10,
        )
        print("[telegram] sent")
    except Exception as e:
        print(f"[telegram] failed: {e}")


def send_discord(text: str):
    """Optional: post full report to Discord via webhook."""
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("[discord] skipped (no webhook)")
        return
    # Discord caps at 2000 chars per message; chunk it
    chunks = [text[i:i+1900] for i in range(0, len(text), 1900)]
    for i, chunk in enumerate(chunks):
        try:
            requests.post(webhook, json={"content": chunk}, timeout=10)
            time.sleep(1)
        except Exception as e:
            print(f"[discord] chunk {i} failed: {e}")
    print(f"[discord] sent {len(chunks)} chunks")


# ---------- MAIN ----------

def main():
    today = datetime.date.today().isoformat()
    print(f"=== iOS Idea Scout run: {today} ===")

    # 1. Collect
    reddit_data = collect_reddit()
    hn_data = collect_hackernews()
    appstore_data = collect_appstore()
    reviews_data = collect_reviews(appstore_data)
    ph_data = collect_producthunt()

    # 2. Save raw signals for auditability
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    raw_path = reports_dir / f"{today}-raw.json"
    with open(raw_path, "w") as f:
        json.dump({
            "date": today,
            "reddit": reddit_data,
            "hackernews": hn_data,
            "appstore": appstore_data,
            "reviews": reviews_data,
            "producthunt": ph_data,
        }, f, indent=2, ensure_ascii=False)
    print(f"[save] raw signals -> {raw_path}")

    # 3. Analyze
    prompt = build_prompt(reddit_data, hn_data, appstore_data, ph_data, reviews_data)
    print(f"[gemini] prompt size: {len(prompt)} chars")
    report = analyze_with_gemini(prompt)

    # 4. Save report
    report_path = reports_dir / f"{today}-report.md"
    header = f"# iOS App Opportunity Report — {today}\n\n"
    header += f"_Sources: {len(reddit_data)} Reddit posts, {len(hn_data)} HN stories, "
    header += f"{len(appstore_data)} App Store entries, {len(reviews_data)} low-star reviews, "
    header += f"{len(ph_data)} Product Hunt launches_\n\n---\n\n"
    full_report = header + report
    with open(report_path, "w") as f:
        f.write(full_report)
    print(f"[save] report -> {report_path}")

    # 5. Update latest.md for easy linking
    with open(reports_dir / "latest.md", "w") as f:
        f.write(full_report)

    # 6. Notify
    send_telegram(full_report)
    send_discord(full_report)

    print("=== done ===")


if __name__ == "__main__":
    main()
