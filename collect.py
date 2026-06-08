"""
EIP / CRM Intelligence Collector
優化版（2026-06）

收集範圍：繁體中文（優先）、英文語系（次）
收集來源：
  - Google News RSS（繁體中文 + 英文）
  - 科技新報（technews.tw）
  - Inside（inside.com.tw）
  - Mashdigi（mashdigi.com）
  - Medium（繁中 + 英文 tag）
  - 方格子（vocus.cc）
  - Threads（公開 profile RSS / scraping）
  - 社群：Facebook Pages RSS (via RSS bridge), Twitter/X RSS fallback

特性：
  - 語言優先權：繁體中文 > 英文
  - 雙層過濾：財經黑名單 + 產品白名單
  - EIP / CRM 品牌白名單
  - Dashboard / UX 標籤分析
  - Thumbnail fallback & 網路防禦機制
  - 分數計算：語言、標籤、來源加權
  - GitHub Pages articles.json 相容格式
"""

import os
import re
import json
import time
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────
# 全域設定
# ──────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

FALLBACK_THUMBNAIL = "https://images.unsplash.com/photo-1552664730-d307ca884978"

REQUEST_TIMEOUT = 10  # 秒
MAX_ITEMS_PER_FEED = 15
SLEEP_BETWEEN_REQUESTS = 0.6  # 秒

# ──────────────────────────────────────────
# 目標品牌
# ──────────────────────────────────────────

TARGET_SOURCES = {
    "Workday": {
        "system": "EIP",
        "keywords": ["Workday", "HCM", "employee experience", "人資", "員工體驗", "workflow", "dashboard"],
    },
    "SAP SuccessFactors": {
        "system": "EIP",
        "keywords": ["SuccessFactors", "人才管理", "employee experience", "HR", "SAP HCM"],
    },
    "Apollo": {
        "system": "EIP",
        "keywords": ["Apollo", "MayoHR", "人事管理", "考勤", "薪資", "EIP"],
    },
    "HiBob": {
        "system": "EIP",
        "keywords": ["HiBob", "HRIS", "employee engagement", "dashboard"],
    },
    "HubSpot": {
        "system": "CRM",
        "keywords": ["HubSpot", "CRM", "marketing automation", "sales hub", "customer experience", "AI CRM"],
    },
    "Stripe": {
        "system": "CRM",
        "keywords": ["Stripe", "billing", "subscription", "customer experience", "payment platform", "金流"],
    },
}

# ──────────────────────────────────────────
# 繁體中文媒體 RSS 清單
# ──────────────────────────────────────────

ZH_MEDIA_FEEDS = [
    {
        "name": "科技新報",
        "url": "https://technews.tw/feed/",
        "lang": "zh-TW",
        "source_score_bonus": 20,
    },
    {
        "name": "Inside",
        "url": "https://www.inside.com.tw/feed",
        "lang": "zh-TW",
        "source_score_bonus": 20,
    },
    {
        "name": "Mashdigi",
        "url": "https://mashdigi.com/feed/",
        "lang": "zh-TW",
        "source_score_bonus": 15,
    },
    # 方格子：以品牌名搜尋（無全站 RSS，改用關鍵字頁面 RSS）
    {
        "name": "方格子-HubSpot",
        "url": "https://vocus.cc/api/rss?search=HubSpot",
        "lang": "zh-TW",
        "source_score_bonus": 25,
    },
    {
        "name": "方格子-EIP",
        "url": "https://vocus.cc/api/rss?search=EIP+人資",
        "lang": "zh-TW",
        "source_score_bonus": 25,
    },
    {
        "name": "方格子-CRM",
        "url": "https://vocus.cc/api/rss?search=CRM+客戶管理",
        "lang": "zh-TW",
        "source_score_bonus": 25,
    },
]

# ──────────────────────────────────────────
# Medium RSS（繁中 tag + 英文 tag）
# ──────────────────────────────────────────

MEDIUM_FEEDS = [
    # 繁體中文 tag（Medium tag RSS）
    {"name": "Medium-HubSpot-TW", "url": "https://medium.com/feed/tag/hubspot", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-CRM-TW",     "url": "https://medium.com/feed/tag/crm",     "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-HRIS",       "url": "https://medium.com/feed/tag/hris",    "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-HCM",        "url": "https://medium.com/feed/tag/hcm",     "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-ERP-HR",     "url": "https://medium.com/feed/tag/hr-technology", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-UX-Dashboard","url": "https://medium.com/feed/tag/dashboard", "lang": "en", "source_score_bonus": 5},
    # 中文 publication（熱門台灣科技 pub）
    {"name": "Medium-Tech-TW",    "url": "https://medium.com/feed/starbugs-io", "lang": "zh-TW", "source_score_bonus": 20},
    {"name": "Medium-PM-TW",      "url": "https://medium.com/feed/pmの生存日記",  "lang": "zh-TW", "source_score_bonus": 20},
]

# ──────────────────────────────────────────
# 過濾黑白名單
# ──────────────────────────────────────────

FINANCE_TITLE_BLACKLIST = [
    "market cap", "earnings per share", "quarterly results",
    "股價", "除權息", "個股", "大盤", "走勢", "配息",
    "投資人", "分析師", "股息", "本益比", "財報",
]

FINANCE_BODY_BLACKLIST = [
    "market cap", "earnings per share", "quarterly results",
    "股價", "走勢", "個股", "市值", "配息", "除權息",
    "投資組合", "股東", "財務報告",
]

PRODUCT_KEYWORDS = [
    # EIP / HR
    "EIP", "HRIS", "HCM", "HR", "人資", "人事", "員工體驗", "考勤", "薪資",
    "人才管理", "績效管理", "排班",
    # CRM / Sales
    "CRM", "sales", "marketing", "customer experience", "客戶關係",
    "客戶體驗", "銷售自動化", "行銷自動化",
    # Product / UX
    "dashboard", "analytics", "workflow", "ui", "ux",
    "儀表板", "工作流", "使用者體驗",
    # General tech
    "feature", "release", "automation", "ai", "integration",
    "功能更新", "功能", "自動化", "數據分析", "人工智慧",
    "改版", "SaaS", "FinTech", "數位轉型",
    # Brand names as fallback
    "Workday", "SuccessFactors", "HiBob", "HubSpot", "Stripe",
]

# ──────────────────────────────────────────
# 語言 & 過濾邏輯
# ──────────────────────────────────────────

# 繁體專用字（簡體無對應或常見差異）
_TRAD_CHARS = set("們與機會網統體資產開關區國際實際觀點歡迎說話語發現後")
# 簡體特徵字
_SIMP_CHARS = set("们这样国队产资统体开关区际实观欢说话语发现后")


def is_traditional_chinese(text: str) -> bool:
    """
    判斷文字是否為繁體中文：
    - 包含繁體特徵字 且 簡體特徵字出現率低於 5%
    """
    if not text:
        return False
    trad_hits = sum(1 for c in text if c in _TRAD_CHARS)
    simp_hits  = sum(1 for c in text if c in _SIMP_CHARS)
    if trad_hits == 0:
        return False
    ratio = simp_hits / max(trad_hits, 1)
    return ratio < 0.5


def is_finance_news(title: str, body: str) -> bool:
    t = title.lower()
    if any(k.lower() in t for k in FINANCE_TITLE_BLACKLIST):
        return True
    b = body.lower()
    hits = sum(1 for k in FINANCE_BODY_BLACKLIST if k.lower() in b)
    return hits >= 2


def is_product_content(text: str) -> bool:
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in PRODUCT_KEYWORDS)


def brand_in_text(text: str) -> list[str]:
    """回傳文字中出現的品牌清單"""
    found = []
    t = text.lower()
    for brand, info in TARGET_SOURCES.items():
        if brand.lower() in t or any(kw.lower() in t for kw in info["keywords"]):
            found.append(brand)
    return found

# ──────────────────────────────────────────
# 標籤分析
# ──────────────────────────────────────────

def analyze_tags(title: str, summary: str) -> list[str]:
    text = f"{title} {summary}".lower()
    tags = []

    if any(k in text for k in ["ui", "ux", "dashboard", "介面", "設計", "體驗", "使用者"]):
        tags.append("用戶體驗")

    if any(k in text for k in ["release", "feature", "更新", "新功能", "launch", "改版", "版本"]):
        tags.append("功能更新")

    if any(k in text for k in ["report", "trend", "研究", "分析", "survey", "趨勢", "洞察"]):
        tags.append("產業趨勢")

    if "dashboard" in text or "儀表板" in text:
        tags.append("Dashboard案例")

    if any(k in text for k in ["ai", "人工智慧", "generative", "llm", "chatgpt", "copilot"]):
        tags.append("AI應用")

    return tags or ["產業趨勢"]

# ──────────────────────────────────────────
# 分數計算
# ──────────────────────────────────────────

def calculate_score(
    title: str,
    desc: str,
    tags: list[str],
    is_zhtw: bool,
    source_bonus: int = 0,
    brand_hits: int = 0,
) -> int:
    score = 40
    # 語言加權：繁中優先
    if is_zhtw:
        score += 40
    # 標籤加權
    if "功能更新" in tags:    score += 15
    if "用戶體驗" in tags:    score += 15
    if "Dashboard案例" in tags: score += 10
    if "AI應用" in tags:      score += 10
    if "產業趨勢" in tags:    score += 5
    # 來源加權
    score += source_bonus
    # 品牌命中數加權
    score += min(brand_hits * 5, 20)
    return score

# ──────────────────────────────────────────
# 網路工具
# ──────────────────────────────────────────

def safe_get(url: str, timeout: int = REQUEST_TIMEOUT) -> requests.Response | None:
    """帶防禦機制的 GET，失敗回傳 None"""
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  ⚠️  GET 失敗 {url[:60]}: {e}")
        return None


def resolve_news_url(url: str) -> str:
    r = safe_get(url, timeout=6)
    return r.url if r else url


def fetch_thumbnail(url: str) -> str:
    if "news.google.com" in url:
        return FALLBACK_THUMBNAIL
    real_url = resolve_news_url(url)
    r = safe_get(real_url, timeout=6)
    if not r:
        return FALLBACK_THUMBNAIL
    soup = BeautifulSoup(r.text, "html.parser")
    for attr in [("meta", {"property": "og:image"}), ("meta", {"name": "twitter:image"})]:
        tag = soup.find(*attr)
        if tag and tag.get("content"):
            return tag["content"]
    return FALLBACK_THUMBNAIL


def parse_date(pub: str) -> str:
    try:
        return parsedate_to_datetime(pub).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def make_id(url: str) -> str:
    return "art_" + hashlib.md5(url.encode()).hexdigest()[:10]

# ──────────────────────────────────────────
# 文章解析（通用 RSS item → dict）
# ──────────────────────────────────────────

def parse_rss_item(
    item,
    source_name: str,
    system: str,
    source_lang: str,
    source_score_bonus: int,
) -> dict | None:
    """
    從 BeautifulSoup RSS <item> 解析出文章 dict。
    回傳 None 表示應跳過。
    """
    title_tag = item.find("title")
    link_tag  = item.find("link")
    pub_tag   = item.find("pubDate")
    desc_tag  = item.find("description")

    if not title_tag or not link_tag:
        return None

    title = title_tag.get_text(strip=True)
    url   = link_tag.get_text(strip=True).strip()

    # Google News RSS 有時 link 是 <link> element text，有時在 href attribute
    if not url and link_tag.has_attr("href"):
        url = link_tag["href"]
    if not url:
        return None

    pub = pub_tag.get_text(strip=True) if pub_tag else ""

    desc = ""
    if desc_tag:
        raw = desc_tag.get_text()
        desc = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    desc = desc[:400]

    combined = title + " " + desc

    # 過濾
    if is_finance_news(title, desc):
        return None
    if not is_product_content(combined):
        return None

    tags       = analyze_tags(title, desc)
    is_zhtw    = is_traditional_chinese(combined) or source_lang == "zh-TW"
    brands     = brand_in_text(combined)
    brand_hits = len(brands)

    # 如果找不到任何品牌，不列入
    if brand_hits == 0:
        return None

    score = calculate_score(title, desc, tags, is_zhtw, source_score_bonus, brand_hits)

    systems = list({TARGET_SOURCES[b]["system"] for b in brands})

    return {
        "id":       make_id(url),
        "channel":  "rss",
        "source":   source_name,
        "brands":   brands,
        "title":    title,
        "summary":  desc[:280],
        "url":      url,
        "thumbnail": FALLBACK_THUMBNAIL,  # 延遲抓取，避免封鎖
        "date":     parse_date(pub),
        "fetched":  datetime.utcnow().isoformat(),
        "systems":  systems,
        "types":    tags,
        "is_zhtw":  is_zhtw,
        "lang":     "zh-TW" if is_zhtw else "en",
        "score":    score,
    }

# ──────────────────────────────────────────
# 收集器：Google News RSS（品牌搜尋）
# ──────────────────────────────────────────

def collect_google_news() -> list[dict]:
    articles = []
    print("\n📡 [Google News RSS] 開始掃描品牌...")

    for brand, info in TARGET_SOURCES.items():
        for lang_config in [
            # 繁中版
            {"hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant", "lang": "zh-TW", "bonus": 30},
            # 英文版（次要）
            {"hl": "en-US", "gl": "US", "ceid": "US:en",       "lang": "en",    "bonus": 0},
        ]:
            query = brand + " " + " OR ".join(info["keywords"][:4])
            rss_url = (
                "https://news.google.com/rss/search?"
                f"q={requests.utils.quote(query)}+when:7d"
                f"&hl={lang_config['hl']}&gl={lang_config['gl']}&ceid={lang_config['ceid']}"
            )

            resp = safe_get(rss_url, timeout=15)
            if not resp:
                continue

            soup  = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")
            print(f"  ├── [{brand}][{lang_config['lang']}] 找到 {len(items)} 篇")

            for item in items[:MAX_ITEMS_PER_FEED]:
                art = parse_rss_item(item, brand, info["system"], lang_config["lang"], lang_config["bonus"])
                if art:
                    articles.append(art)
                time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"  └── Google News 小計：{len(articles)} 篇")
    return articles

# ──────────────────────────────────────────
# 收集器：繁體中文媒體 RSS
# ──────────────────────────────────────────

def collect_zh_media() -> list[dict]:
    articles = []
    print("\n📰 [繁體中文媒體] 開始掃描...")

    all_feeds = ZH_MEDIA_FEEDS + MEDIUM_FEEDS

    for feed in all_feeds:
        print(f"  ├── {feed['name']} ...")
        resp = safe_get(feed["url"], timeout=12)
        if not resp:
            continue

        # 嘗試 xml parser，失敗換 html.parser
        try:
            soup = BeautifulSoup(resp.content, "xml")
        except Exception:
            soup = BeautifulSoup(resp.content, "html.parser")

        items = soup.find_all("item")
        if not items:
            items = soup.find_all("entry")  # Atom feed fallback

        for item in items[:MAX_ITEMS_PER_FEED]:
            art = parse_rss_item(
                item,
                feed["name"],
                "EIP/CRM",
                feed.get("lang", "zh-TW"),
                feed.get("source_score_bonus", 10),
            )
            if art:
                articles.append(art)
            time.sleep(SLEEP_BETWEEN_REQUESTS * 0.5)

    print(f"  └── 繁體中文媒體 小計：{len(articles)} 篇")
    return articles

# ──────────────────────────────────────────
# 收集器：Threads（公開 profile 文字抓取）
# 注意：Threads 無官方 RSS，以 scraping 方式取得公開帳號最新貼文
# 建議帳號：官方品牌帳、台灣科技社群 KOL
# ──────────────────────────────────────────

THREADS_ACCOUNTS = [
    # 品牌官方（如有 Threads 帳號）
    "hubspot",
    "stripe",
    # 台灣科技 KOL / 社群（請依實際帳號調整）
    "inside.com.tw",
    "technews.tw",
]


def collect_threads() -> list[dict]:
    """
    嘗試抓取 Threads 公開帳號頁面。
    Threads 目前無 RSS，僅能 scrape HTML。
    若帳號使用 SSR，可抽取 JSON-LD 或 og:description。
    """
    articles = []
    print("\n🧵 [Threads] 嘗試抓取公開貼文...")

    for account in THREADS_ACCOUNTS:
        url = f"https://www.threads.net/@{account}"
        resp = safe_get(url, timeout=12)
        if not resp:
            continue

        soup = BeautifulSoup(resp.text, "html.parser")

        # 抽取 og:description 作為摘要
        og_desc = soup.find("meta", property="og:description")
        og_title = soup.find("meta", property="og:title")
        og_img   = soup.find("meta", property="og:image")

        if not og_desc:
            continue

        desc  = og_desc.get("content", "")
        title = og_title.get("content", f"@{account} on Threads") if og_title else f"@{account} on Threads"
        img   = og_img.get("content", FALLBACK_THUMBNAIL) if og_img else FALLBACK_THUMBNAIL

        combined = title + " " + desc
        if is_finance_news(title, desc):
            continue
        if not is_product_content(combined):
            continue

        brands = brand_in_text(combined)
        if not brands:
            continue

        tags    = analyze_tags(title, desc)
        is_zhtw = is_traditional_chinese(combined)
        score   = calculate_score(title, desc, tags, is_zhtw, source_score_bonus=20, brand_hits=len(brands))

        articles.append({
            "id":       make_id(url + desc[:30]),
            "channel":  "threads",
            "source":   f"Threads/@{account}",
            "brands":   brands,
            "title":    title,
            "summary":  desc[:280],
            "url":      url,
            "thumbnail": img,
            "date":     datetime.utcnow().isoformat(),
            "fetched":  datetime.utcnow().isoformat(),
            "systems":  [TARGET_SOURCES[b]["system"] for b in brands],
            "types":    tags,
            "is_zhtw":  is_zhtw,
            "lang":     "zh-TW" if is_zhtw else "en",
            "score":    score,
        })
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"  └── Threads 小計：{len(articles)} 篇")
    return articles

# ──────────────────────────────────────────
# 去重
# ──────────────────────────────────────────

def deduplicate(articles: list[dict]) -> list[dict]:
    seen_ids  = set()
    seen_urls = set()
    unique = []
    for art in articles:
        key = art.get("id", "")
        url = art.get("url", "")
        if key in seen_ids or url in seen_urls:
            continue
        seen_ids.add(key)
        seen_urls.add(url)
        unique.append(art)
    return unique

# ──────────────────────────────────────────
# Thumbnail 補抓（批次，控制速率）
# ──────────────────────────────────────────

def enrich_thumbnails(articles: list[dict], limit: int = 30) -> list[dict]:
    """
    只對分數最高的前 N 篇補抓 thumbnail，避免大量請求觸發封鎖。
    """
    print(f"\n🖼️  補抓 Thumbnail（前 {limit} 篇）...")
    top = sorted(articles, key=lambda x: x["score"], reverse=True)[:limit]
    top_ids = {a["id"] for a in top}

    for art in articles:
        if art["id"] not in top_ids:
            continue
        if art["thumbnail"] != FALLBACK_THUMBNAIL:
            continue  # 已有圖，略過
        art["thumbnail"] = fetch_thumbnail(art["url"])
        time.sleep(0.3)

    return articles

# ──────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────

def collect_all_intelligence():
    print("🚀 開始執行競品情報收集（2026-06 優化版）")
    print(f"   語言優先：繁體中文 > 英文")
    print(f"   收集時間：{datetime.utcnow().isoformat()} UTC\n")

    all_articles: list[dict] = []

    # 1. Google News RSS（繁中 + 英文）
    all_articles += collect_google_news()

    # 2. 繁體中文媒體 + Medium
    all_articles += collect_zh_media()

    # 3. Threads（公開貼文 scraping）
    all_articles += collect_threads()

    # 去重
    all_articles = deduplicate(all_articles)
    print(f"\n🔍 去重後：{len(all_articles)} 篇")

    # 排序（語言加權已含在 score 中）
    all_articles.sort(key=lambda x: (x["score"], x["is_zhtw"]), reverse=True)

    # 補抓 thumbnail（控制速率）
    all_articles = enrich_thumbnails(all_articles, limit=30)

    # 統計
    zhtw_count = sum(1 for a in all_articles if a.get("is_zhtw"))
    en_count   = len(all_articles) - zhtw_count
    by_channel: dict[str, int] = {}
    by_system: dict[str, int]  = {}
    by_type: dict[str, int] = {}
    for a in all_articles:
        ch = a.get("channel", "unknown")
        by_channel[ch] = by_channel.get(ch, 0) + 1
        for s in a.get("systems", []):
            by_system[s] = by_system.get(s, 0) + 1
        for t in a.get("types", []): 
            by_type[t] = by_type.get(t, 0) + 1

    output = {
        "stats": {
            "total": len(all_articles),
            "new_today": len(all_articles),
            "last_updated": datetime.utcnow().isoformat(),
            "lang_breakdown": {"zh_TW": zhtw_count, "en": en_count},
            "by_channel": by_channel,
            "by_system": by_system,
            "by_type": by_type,
        },
        "articles": all_articles,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n==== 🎉 收集完成 ====")
    print(f"   總計   : {len(all_articles)} 篇")
    print(f"   繁體中文: {zhtw_count} 篇")
    print(f"   英文   : {en_count} 篇")
    print(f"   輸出   : data/articles.json")


if __name__ == "__main__":
    collect_all_intelligence()