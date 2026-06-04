"""
競品情報自動收集腳本
每日透過 GitHub Actions 執行，輸出 data/articles.json
來源：RSS Feeds、Reddit、Product Hunt、Dribbble、Hacker News
"""

import json
import os
import time
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

# ─── 設定區 ──────────────────────────────────────────────────
OUTPUT_PATH = Path("data/articles.json")
HISTORY_PATH = Path("data/seen_ids.json")
MAX_ARTICLES = 300          # 最多保留幾筆
REQUEST_TIMEOUT = 15        # 秒
SLEEP_BETWEEN = 1.5         # 每次請求間隔（秒），避免被封）

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

# ─── 關鍵字分類器 ─────────────────────────────────────────────
SYSTEM_KEYWORDS = {
    "ERP": ["erp", "sap", "oracle erp", "microsoft dynamics", "netsuite", "odoo",
            "sage", "infor", "epicor", "製造", "供應鏈", "supply chain", "inventory",
            "warehouse", "procurement", "生產管理"],
    "CRM": ["crm", "salesforce", "hubspot", "zoho crm", "pipedrive", "freshsales",
            "客戶管理", "sales pipeline", "lead", "customer relationship", "銷售漏斗"],
    "PMS": ["pms", "project management", "jira", "linear", "monday.com", "asana",
            "notion", "clickup", "basecamp", "trello", "專案管理", "task management",
            "roadmap", "gantt", "sprint", "agile", "scrum"],
    "EIP": ["eip", "enterprise portal", "intranet", "sharepoint", "confluence",
            "企業入口", "knowledge base", "員工入口", "workspace", "okta", "sso",
            "企業整合"],
}

TYPE_KEYWORDS = {
    "UIUX": ["ux", "ui", "design", "usability", "user experience", "user interface",
             "accessibility", "interaction", "wireframe", "prototype", "設計",
             "體驗", "介面", "導覽", "navigation", "onboarding"],
    "Dashboard": ["dashboard", "analytics", "data visualization", "chart", "graph",
                  "metrics", "kpi", "報表", "儀表板", "視覺化", "overview"],
    "功能分析": ["feature", "comparison", "review", "vs", "versus", "功能", "比較",
               "評測", "workflow", "automation", "integration", "api"],
    "競品新聞": ["launch", "release", "update", "announcement", "funding", "acquisition",
               "發布", "更新", "融資", "收購", "新功能"],
}

# ─── RSS 來源清單 ─────────────────────────────────────────────
RSS_FEEDS = [
    # UX / Design
    {"url": "https://uxdesign.cc/feed",             "source": "UX Collective"},
    {"url": "https://www.nngroup.com/feed/rss/",    "source": "Nielsen Norman Group"},
    {"url": "https://www.smashingmagazine.com/feed/","source": "Smashing Magazine"},
    {"url": "https://feeds.feedburner.com/Techcrunch","source": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml","source": "The Verge"},
    # ERP/CRM/EIP 專業媒體
    {"url": "https://www.cio.com/feed/",            "source": "CIO.com"},
    {"url": "https://www.zdnet.com/topic/enterprise-software/rss.xml", "source": "ZDNet Enterprise"},
    {"url": "https://feeds.feedburner.com/venturebeat/SZYF","source": "VentureBeat"},
    # Hacker News (精選)
    {"url": "https://hnrss.org/best?q=ERP+OR+CRM+OR+dashboard+OR+ux&points=50",
     "source": "Hacker News"},
]

# ─── Reddit 來源 ──────────────────────────────────────────────
REDDIT_SUBS = [
    {"sub": "projectmanagement",  "limit": 10},
    {"sub": "Entrepreneur",       "limit": 6},
    {"sub": "devops",             "limit": 5},
    {"sub": "sysadmin",           "limit": 5},
    {"sub": "DataEngineering",    "limit": 5},
]

# ─── Product Hunt 關鍵字 ──────────────────────────────────────
PH_KEYWORDS = ["crm", "project management", "erp", "dashboard", "enterprise"]


# ═══════════════════════════════════════════════════════════════
# 工具函式
# ═══════════════════════════════════════════════════════════════

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def load_seen() -> set:
    if HISTORY_PATH.exists():
        return set(json.loads(HISTORY_PATH.read_text()))
    return set()


def save_seen(seen: set):
    HISTORY_PATH.write_text(json.dumps(list(seen)))


def load_existing() -> list:
    if OUTPUT_PATH.exists():
        raw = json.loads(OUTPUT_PATH.read_text())
        # Support both old plain-list format and new {stats, articles} format
        if isinstance(raw, dict):
            return raw.get("articles", [])
        return raw
    return []


def classify(text: str) -> tuple[list, list]:
    """回傳 (系統標籤[], 類型標籤[])"""
    low = text.lower()
    systems = [k for k, kws in SYSTEM_KEYWORDS.items() if any(w in low for w in kws)]
    types   = [k for k, kws in TYPE_KEYWORDS.items()   if any(w in low for w in kws)]
    return systems or ["其他"], types or ["一般"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_get(url: str, **kwargs) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  ⚠ GET 失敗 {url[:60]}... → {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# 各來源爬取
# ═══════════════════════════════════════════════════════════════

def fetch_rss(seen: set) -> list:
    items = []
    for feed_cfg in RSS_FEEDS:
        url    = feed_cfg["url"]
        source = feed_cfg["source"]
        print(f"  📡 RSS: {source}")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"    ✗ 解析失敗: {e}")
            continue

        for entry in feed.entries[:15]:
            link  = entry.get("link", "")
            title = entry.get("title", "").strip()
            if not link or not title:
                continue

            uid = make_id(link)
            if uid in seen:
                continue

            summary = BeautifulSoup(
                entry.get("summary", entry.get("description", "")), "html.parser"
            ).get_text()[:300]

            combined = f"{title} {summary}"
            systems, types = classify(combined)

            # 只保留與目標系統相關的文章
            if "其他" in systems and len(systems) == 1:
                continue

            pub = entry.get("published", now_iso())

            items.append({
                "id":       uid,
                "title":    title,
                "url":      link,
                "source":   source,
                "summary":  summary.strip(),
                "systems":  systems,
                "types":    types,
                "date":     pub,
                "fetched":  now_iso(),
                "channel":  "rss",
            })
            seen.add(uid)
        time.sleep(SLEEP_BETWEEN)

    print(f"  ✓ RSS 共 {len(items)} 篇")
    return items


def fetch_reddit(seen: set) -> list:
    items = []
    for cfg in REDDIT_SUBS:
        sub   = cfg["sub"]
        limit = cfg["limit"]
        print(f"  🟠 Reddit: r/{sub}")
        r = safe_get(
            f"https://www.reddit.com/r/{sub}/hot.json?limit={limit}",
            headers={**HEADERS, "Accept": "application/json"},
        )
        if not r:
            continue

        posts = r.json().get("data", {}).get("children", [])
        for p in posts:
            d     = p["data"]
            link  = "https://reddit.com" + d.get("permalink", "")
            title = d.get("title", "").strip()
            if not title:
                continue

            uid = make_id(link)
            if uid in seen:
                continue

            text = f"{title} {d.get('selftext','')[:200]}"
            systems, types = classify(text)
            if "其他" in systems and len(systems) == 1:
                continue

            items.append({
                "id":       uid,
                "title":    title,
                "url":      f"https://reddit.com{d['permalink']}",
                "source":   f"Reddit · r/{sub}",
                "summary":  d.get("selftext", "")[:200].strip(),
                "systems":  systems,
                "types":    types,
                "date":     datetime.fromtimestamp(
                                d.get("created_utc", 0), tz=timezone.utc
                            ).isoformat(),
                "fetched":  now_iso(),
                "channel":  "reddit",
                "score":    d.get("score", 0),
                "comments": d.get("num_comments", 0),
            })
            seen.add(uid)
        time.sleep(SLEEP_BETWEEN)

    print(f"  ✓ Reddit 共 {len(items)} 篇")
    return items


def fetch_hn_algolia(seen: set) -> list:
    """透過 Algolia HN Search API 搜尋特定關鍵字"""
    keywords = ["ERP UX", "CRM design", "dashboard UX", "project management tool"]
    items = []
    print("  🟡 Hacker News Algolia Search")
    for kw in keywords:
        r = safe_get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": kw, "tags": "story", "numericFilters": "points>30",
                    "hitsPerPage": 6},
        )
        if not r:
            continue
        for hit in r.json().get("hits", []):
            url   = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
            title = hit.get("title", "").strip()
            uid   = make_id(url)
            if uid in seen or not title:
                continue

            systems, types = classify(f"{title} {kw}")
            if "其他" in systems and len(systems) == 1:
                continue

            items.append({
                "id":       uid,
                "title":    title,
                "url":      url,
                "source":   "Hacker News",
                "summary":  "",
                "systems":  systems,
                "types":    types,
                "date":     hit.get("created_at", now_iso()),
                "fetched":  now_iso(),
                "channel":  "hackernews",
                "score":    hit.get("points", 0),
                "comments": hit.get("num_comments", 0),
            })
            seen.add(uid)
        time.sleep(SLEEP_BETWEEN)

    print(f"  ✓ HN 共 {len(items)} 篇")
    return items


def fetch_ph_rss(seen: set) -> list:
    """Product Hunt 每日熱門 RSS（官方提供）"""
    print("  🐱 Product Hunt RSS")
    items = []
    r = safe_get("https://www.producthunt.com/feed")
    if not r:
        return items

    feed = feedparser.parse(r.text)
    for entry in feed.entries[:20]:
        link  = entry.get("link", "")
        title = entry.get("title", "").strip()
        uid   = make_id(link)
        if uid in seen or not title:
            continue

        summary = BeautifulSoup(
            entry.get("summary", ""), "html.parser"
        ).get_text()[:300]

        systems, types = classify(f"{title} {summary}")
        if "其他" in systems and len(systems) == 1:
            continue

        items.append({
            "id":       uid,
            "title":    title,
            "url":      link,
            "source":   "Product Hunt",
            "summary":  summary.strip(),
            "systems":  systems,
            "types":    types,
            "date":     entry.get("published", now_iso()),
            "fetched":  now_iso(),
            "channel":  "producthunt",
        })
        seen.add(uid)

    time.sleep(SLEEP_BETWEEN)
    print(f"  ✓ PH 共 {len(items)} 篇")
    return items


def fetch_devto(seen: set) -> list:
    """Dev.to API（免費，不需 key）"""
    tags = ["ux", "productivity", "webdev", "devops"]
    items = []
    print("  💻 Dev.to")
    for tag in tags:
        r = safe_get(
            "https://dev.to/api/articles",
            params={"tag": tag, "per_page": 8, "top": 7},
        )
        if not r:
            continue
        for art in r.json():
            url   = art.get("url", "")
            title = art.get("title", "").strip()
            uid   = make_id(url)
            if uid in seen or not title:
                continue

            desc = art.get("description", "")
            systems, types = classify(f"{title} {desc}")
            if "其他" in systems and len(systems) == 1:
                continue

            items.append({
                "id":       uid,
                "title":    title,
                "url":      url,
                "source":   "Dev.to",
                "summary":  desc[:200],
                "systems":  systems,
                "types":    types,
                "date":     art.get("published_at", now_iso()),
                "fetched":  now_iso(),
                "channel":  "devto",
                "score":    art.get("positive_reactions_count", 0),
            })
            seen.add(uid)
        time.sleep(SLEEP_BETWEEN)

    print(f"  ✓ Dev.to 共 {len(items)} 篇")
    return items


# ═══════════════════════════════════════════════════════════════
# 主程式
# ═══════════════════════════════════════════════════════════════

def main():
    print(f"\n{'='*50}")
    print(f"  競品情報收集開始  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}\n")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    seen     = load_seen()
    existing = load_existing()

    new_items = []
    new_items += fetch_rss(seen)
    new_items += fetch_reddit(seen)
    new_items += fetch_hn_algolia(seen)
    new_items += fetch_ph_rss(seen)
    new_items += fetch_devto(seen)

    # 合併 + 去重 + 依時間排序 + 截斷
    all_articles = new_items + existing
    seen_urls    = set()
    deduped      = []
    for a in all_articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            deduped.append(a)

    deduped = deduped[:MAX_ARTICLES]

    # 統計
    stats = {
        "last_updated": now_iso(),
        "total":        len(deduped),
        "new_today":    len(new_items),
        "by_system":    {},
        "by_type":      {},
        "by_channel":   {},
    }
    for a in deduped:
        for s in a.get("systems", []):
            stats["by_system"][s] = stats["by_system"].get(s, 0) + 1
        for t in a.get("types", []):
            stats["by_type"][t] = stats["by_type"].get(t, 0) + 1
        ch = a.get("channel", "other")
        stats["by_channel"][ch] = stats["by_channel"].get(ch, 0) + 1

    output = {"stats": stats, "articles": deduped}
    OUTPUT_PATH.write_text(
        json.dumps(output, ensure_ascii=False, indent=2)
    )
    save_seen(seen)

    print(f"\n{'='*50}")
    print(f"  ✅ 完成！新增 {len(new_items)} 篇，共 {len(deduped)} 篇")
    print(f"  📁 輸出：{OUTPUT_PATH}")
    print(f"  系統分布：{stats['by_system']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
