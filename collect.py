"""
PMS / CRM / HR Intelligence Collector
優化版（2026-09）

收集範圍：繁體中文（優先） > 英文 > 日文
收集來源：
  - Google News RSS（繁中 + 英文 + 日文）
  - 科技新報、Inside、Mashdigi、方格子（zh-TW）
  - Medium tag / publication（en + zh-TW）
  - 日本媒體：ITmedia、ASCII.jp、Impress Watch（ja）
  - Threads（公開 profile scraping）

特性：
  - 語言優先權：繁體中文 > 英文 > 日文
  - 雙層過濾：財經域名黑名單 + 標題財經關鍵字 + 產品白名單
  - PMS / CRM / HR 品牌白名單（旅宿 Property Management + Channel Manager）
  - Dashboard / UX / AI 標籤分析
  - Thumbnail fallback & 網路防禦機制
  - 分數計算：語言、標籤、來源加權
  - GitHub Pages articles.json 相容格式
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

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
    # ── HR / EIP（EIP 併入 HR）───────────────────────────────
    "Workday": {
        "system": "HR",
        "keywords": ["Workday", "HCM", "employee experience", "人資", "員工體驗", "workflow", "dashboard"],
    },
    "SAP SuccessFactors": {
        "system": "HR",
        "keywords": ["SuccessFactors", "人才管理", "employee experience", "HR", "SAP HCM"],
    },
    "Apollo": {
        "system": "HR",
        "keywords": ["Apollo HR", "MayoHR", "人事管理", "考勤", "薪資", "EIP"],
    },
    "HiBob": {
        "system": "HR",
        "keywords": ["HiBob", "HRIS", "employee engagement", "dashboard"],
    },
    # ── CRM ─────────────────────────────────────────────
    "HubSpot": {
        "system": "CRM",
        "keywords": ["HubSpot", "CRM", "marketing automation", "sales hub", "customer experience", "AI CRM"],
    },
    # Stripe 收緊：需同時出現主題字才收（於 parse_rss_item 判斷）
    "Stripe": {
        "system": "CRM",
        "keywords": ["Stripe billing", "Stripe subscription", "Stripe Atlas", "Stripe CRM", "Stripe payroll"],
        "narrow": True,
    },
    # ── PMS（旅宿 Property Management + Channel Manager）───
    "Cloudbeds": {
        "system": "PMS",
        "keywords": ["Cloudbeds", "property management", "hotel management", "旅宿", "客房管理"],
    },
    "Mews": {
        "system": "PMS",
        "keywords": ["Mews", "hospitality cloud", "hotel platform", "PMS"],
    },
    "Opera PMS": {
        "system": "PMS",
        "keywords": ["Opera PMS", "Oracle Hospitality", "Opera Cloud"],
    },
    "Little Hotelier": {
        "system": "PMS",
        "keywords": ["Little Hotelier", "small hotel software", "民宿管理"],
    },
    "SiteMinder": {
        "system": "PMS",
        "keywords": ["SiteMinder", "channel manager", "OTA connectivity", "通路管理"],
    },
    "Guestline": {
        "system": "PMS",
        "keywords": ["Guestline", "hotel PMS", "hospitality software"],
    },
    "RMS Cloud": {
        "system": "PMS",
        "keywords": ["RMS Cloud", "hotel property management"],
    },
    "protel": {
        "system": "PMS",
        "keywords": ["protel PMS", "protel hospitality"],
    },
    "STAAH": {
        "system": "PMS",
        "keywords": ["STAAH", "channel manager", "booking engine"],
    },
    "RateGain": {
        "system": "PMS",
        "keywords": ["RateGain", "hospitality distribution", "rate management"],
    },
    # ── 亞太 / 日系 PMS ───────────────────────────────────
    "tripla": {
        "system": "PMS",
        "keywords": ["tripla", "宿泊予約", "予約管理"],
    },
    "Tabist": {
        "system": "PMS",
        "keywords": ["Tabist", "ホテル運営", "宿泊施設"],
    },
    "手間いらず": {
        "system": "PMS",
        "keywords": ["手間いらず", "宿泊管理", "TEMAIRAZU"],
    },
    "TL-リンカーン": {
        "system": "PMS",
        "keywords": ["TL-リンカーン", "TLリンカーン", "TL-Lincoln"],
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
    {"name": "Medium-HubSpot",   "url": "https://medium.com/feed/tag/hubspot", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-CRM",       "url": "https://medium.com/feed/tag/crm",     "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-HRIS",      "url": "https://medium.com/feed/tag/hris",    "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-HCM",       "url": "https://medium.com/feed/tag/hcm",     "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-HR-Tech",   "url": "https://medium.com/feed/tag/hr-technology", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-PMS",       "url": "https://medium.com/feed/tag/property-management", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-Hospitality","url": "https://medium.com/feed/tag/hospitality-technology", "lang": "en", "source_score_bonus": 10},
    {"name": "Medium-UX-Dashboard","url": "https://medium.com/feed/tag/dashboard", "lang": "en", "source_score_bonus": 5},
    # 中文 publication（熱門台灣科技 pub）
    {"name": "Medium-Tech-TW",   "url": "https://medium.com/feed/starbugs-io", "lang": "zh-TW", "source_score_bonus": 20},
    {"name": "Medium-PM-TW",     "url": "https://medium.com/feed/pmの生存日記",  "lang": "zh-TW", "source_score_bonus": 20},
]

# ──────────────────────────────────────────
# 日文媒體 RSS
# ──────────────────────────────────────────

JP_MEDIA_FEEDS = [
    {
        "name": "ITmedia エンタープライズ",
        "url": "https://rss.itmedia.co.jp/rss/2.0/enterprise.xml",
        "lang": "ja",
        "source_score_bonus": 15,
    },
    {
        "name": "ITmedia ビジネス",
        "url": "https://rss.itmedia.co.jp/rss/2.0/business_ent.xml",
        "lang": "ja",
        "source_score_bonus": 15,
    },
    {
        "name": "ASCII.jp ビジネス",
        "url": "https://ascii.jp/rss.xml",
        "lang": "ja",
        "source_score_bonus": 10,
    },
    {
        "name": "Impress Internet Watch",
        "url": "https://internet.watch.impress.co.jp/data/rss/1.0/iw/feed.rdf",
        "lang": "ja",
        "source_score_bonus": 10,
    },
]

# ──────────────────────────────────────────
# 過濾黑白名單
# ──────────────────────────────────────────

# 財經 / 投資類域名黑名單（子字串比對，命中即丟）
FINANCE_DOMAIN_BLACKLIST = {
    # 中文財經
    "cnyes.com", "money.udn.com", "wealth.com.tw", "moneydj.com",
    "ctee.com.tw", "wantrich.chinatimes.com", "fund.cnyes.com",
    "stock.yahoo.com", "tw.stock.yahoo.com", "histock.tw", "wantgoo.com",
    # 英文財經
    "bloomberg.com", "reuters.com/business", "ft.com", "wsj.com",
    "marketwatch.com", "seekingalpha.com", "investing.com",
    "barrons.com", "fool.com", "benzinga.com",
    # 日文財經
    "zaikei.co.jp", "diamond.jp/zai", "toyokeizai.net",
    "kabutan.jp", "minkabu.jp", "traders.co.jp",
}

# 標題財經關鍵字（命中即丟，多語）
FINANCE_TITLE_KEYWORDS = [
    # zh
    "股價", "財報", "營收", "毛利", "EPS", "IPO", "上市", "上櫃", "上市櫃",
    "增資", "私募", "配息", "除權息", "殖利率", "本益比", "分析師目標價",
    "個股", "大盤", "股息", "市值", "投資人", "分析師日", "投資人日",
    "金融分析師", "法說會", "股東會",
    # en
    "earnings beat", "earnings miss", "revenue beat", "guidance",
    "IPO filing", "analyst rating", "price target", "dividend",
    "market cap", "earnings per share", "quarterly results",
    "stock forecast", "stock upgrade", "stock downgrade",
    "financial analyst day", "analyst day", "investor day",
    # ja
    "決算", "増資", "株価", "配当", "上場", "IPO", "業績予想",
    "アナリスト", "格付け",
]

# 產品範圍關鍵字（白名單）— 命中才收
PRODUCT_KEYWORDS = [
    # ── PMS / Property Management（旅宿）
    "PMS", "property management", "hotel management", "channel manager",
    "booking engine", "revenue management", "hospitality",
    "旅宿", "客房管理", "訂房系統", "民宿管理", "通路管理", "飯店管理",
    "予約管理", "宿泊管理", "ホテル管理", "宿泊施設", "客室管理",
    # ── HR / EIP
    "EIP", "HRIS", "HCM", "HR", "人資", "人事", "員工體驗", "考勤", "薪資",
    "人才管理", "績效管理", "排班", "員工",
    "人事システム", "勤怠", "労務", "人事管理",
    # ── CRM / Sales / Marketing
    "CRM", "sales", "marketing", "customer experience", "客戶關係",
    "客戶體驗", "銷售自動化", "行銷自動化", "顧客管理",
    "顧客関係", "営業支援", "マーケティングオートメーション",
    # ── Product / UX
    "dashboard", "analytics", "workflow", "ui", "ux",
    "儀表板", "工作流", "使用者體驗", "ユーザー体験", "ダッシュボード",
    # ── General tech
    "feature", "release", "automation", "ai", "integration",
    "功能更新", "功能", "自動化", "數據分析", "人工智慧",
    "改版", "SaaS", "數位轉型", "デジタルトランスフォーメーション",
    "機能追加", "リリース", "導入事例",
    # ── Brand names as fallback
    "Workday", "SuccessFactors", "HiBob", "HubSpot",
    "Cloudbeds", "Mews", "Opera PMS", "SiteMinder",
]

# ──────────────────────────────────────────
# 語言 & 過濾邏輯
# ──────────────────────────────────────────

# 繁體專用字（簡體無對應或常見差異）
_TRAD_CHARS = set("們與機會網統體資產開關區國際實際觀點歡迎說話語發現後")
# 簡體特徵字
_SIMP_CHARS = set("们这样国队产资统体开关区际实观欢说话语发现后")


def _has_japanese_kana(text: str) -> bool:
    """
    偵測日文假名（平假名 U+3040-309F、片假名 U+30A0-30FF）。
    含假名的文字幾乎必為日文（漢字則中日共用，不足以區分）。
    """
    if not text:
        return False
    return any("぀" <= c <= "ヿ" for c in text)


def detect_lang(text: str, source_lang_hint: str | None = None) -> str:
    """
    回傳 'zh-TW' | 'en' | 'ja'。
    優先序：來源 hint > 假名（日文）> 繁體字集 > 預設英文。
    """
    if source_lang_hint in ("zh-TW", "en", "ja"):
        if source_lang_hint == "zh-TW" and not is_traditional_chinese(text):
            # 來源標繁中但內容其實含日文假名 → 判日文
            if _has_japanese_kana(text):
                return "ja"
        return source_lang_hint

    if _has_japanese_kana(text):
        return "ja"
    if is_traditional_chinese(text):
        return "zh-TW"
    return "en"


def is_traditional_chinese(text: str) -> bool:
    """
    判斷文字是否為繁體中文：
    - 含日文假名 → False（避免把日文誤判為繁中）
    - 包含繁體特徵字 且 簡體特徵字比率 < 50%
    """
    if not text:
        return False
    if _has_japanese_kana(text):
        return False
    trad_hits = sum(1 for c in text if c in _TRAD_CHARS)
    simp_hits = sum(1 for c in text if c in _SIMP_CHARS)
    if trad_hits == 0:
        return False
    ratio = simp_hits / max(trad_hits, 1)
    return ratio < 0.5


def is_finance_noise(url: str, title: str, body: str = "") -> bool:
    """
    財經 / 投資雜訊過濾：
    1) 域名黑名單命中 → 丟
    2) 標題財經關鍵字命中 → 丟
    """
    host = (urlparse(url).netloc or "").lower()
    path = (urlparse(url).path or "").lower()
    full = host + path
    if any(bad in full for bad in FINANCE_DOMAIN_BLACKLIST):
        return True
    t = title.lower()
    if any(kw.lower() in t for kw in FINANCE_TITLE_KEYWORDS):
        return True
    return False


def is_product_content(text: str) -> bool:
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in PRODUCT_KEYWORDS)


def brand_in_text(text: str) -> list[str]:
    """
    回傳文字中出現的品牌清單。
    narrow=True 的品牌（如 Stripe）需完整 keyword phrase 命中，
    避免通用品牌名把大量金流雜訊拉進來。
    """
    found = []
    lower = text.lower()
    for brand, info in TARGET_SOURCES.items():
        if info.get("narrow"):
            # 必須命中至少一個窄化 keyword phrase
            if any(kw.lower() in lower for kw in info["keywords"]):
                found.append(brand)
        else:
            if brand.lower() in lower or any(kw.lower() in lower for kw in info["keywords"]):
                found.append(brand)
    return found


# ──────────────────────────────────────────
# 系統分類（PMS / HR / CRM）— 除了品牌回推，也用關鍵字直接分類
# ──────────────────────────────────────────

SYSTEMS_KEYWORDS = {
    "PMS": [
        "pms", "property management", "channel manager", "booking engine",
        "revenue management", "hospitality",
        "旅宿", "客房管理", "訂房系統", "民宿管理", "飯店管理", "通路管理",
        "予約管理", "宿泊管理", "ホテル管理", "宿泊施設", "客室管理",
    ],
    "HR": [
        "hr", "hris", "hcm", "eip", "payroll",
        "人資", "人事", "員工", "考勤", "薪資", "人才管理", "績效", "排班",
        "人事システム", "勤怠", "労務", "人事管理",
    ],
    "CRM": [
        "crm", "customer relationship", "sales hub", "marketing automation",
        "客戶關係", "客戶體驗", "銷售自動化", "行銷自動化", "顧客管理",
        "顧客関係", "営業支援", "マーケティングオートメーション",
    ],
}


def classify_systems(brands: list[str], text: str) -> list[str]:
    """
    先從品牌回推 system，再用文字關鍵字補強。
    多命中則多標（PMS/HR/CRM 可共存）。
    """
    systems = {TARGET_SOURCES[b]["system"] for b in brands if b in TARGET_SOURCES}
    lower = text.lower()
    for sys_name, kws in SYSTEMS_KEYWORDS.items():
        if any(k.lower() in lower for k in kws):
            systems.add(sys_name)
    return sorted(systems)

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
    lang: str,
    source_bonus: int = 0,
    brand_hits: int = 0,
) -> int:
    score = 40
    # 語言加權：繁中 > 日文 > 英文
    if lang == "zh-TW":
        score += 40
    elif lang == "ja":
        score += 20
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

    # 過濾：財經雜訊（域名 + 標題關鍵字）
    if is_finance_noise(url, title, desc):
        return None
    # 過濾：非產品範圍
    if not is_product_content(combined):
        return None

    tags       = analyze_tags(title, desc)
    lang       = detect_lang(combined, source_lang)
    is_zhtw    = (lang == "zh-TW")
    brands     = brand_in_text(combined)
    brand_hits = len(brands)

    # 如果找不到任何品牌，不列入
    if brand_hits == 0:
        return None

    systems = classify_systems(brands, combined)
    if not systems:
        return None

    score = calculate_score(title, desc, tags, lang, source_score_bonus, brand_hits)

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
        "lang":     lang,
        "score":    score,
    }

# ──────────────────────────────────────────
# 收集器：Google News RSS（品牌搜尋）
# ──────────────────────────────────────────

def collect_google_news() -> list[dict]:
    articles = []
    print("\n📡 [Google News RSS] 開始掃描品牌...")

    lang_configs = [
        # 繁中版（優先）
        {"hl": "zh-TW", "gl": "TW", "ceid": "TW:zh-Hant", "lang": "zh-TW", "bonus": 30},
        # 英文版（次要）
        {"hl": "en-US", "gl": "US", "ceid": "US:en",       "lang": "en",    "bonus": 0},
        # 日文版
        {"hl": "ja",    "gl": "JP", "ceid": "JP:ja",       "lang": "ja",    "bonus": 15},
    ]

    for brand, info in TARGET_SOURCES.items():
        for lang_config in lang_configs:
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
                art = parse_rss_item(item, brand, lang_config["lang"], lang_config["bonus"])
                if art:
                    articles.append(art)
                time.sleep(SLEEP_BETWEEN_REQUESTS)

    print(f"  └── Google News 小計：{len(articles)} 篇")
    return articles

# ──────────────────────────────────────────
# 收集器：繁體中文媒體 RSS
# ──────────────────────────────────────────

def collect_media_feeds() -> list[dict]:
    """抓取繁中 + 英文 Medium + 日文媒體 RSS。"""
    articles = []
    print("\n📰 [多語系媒體 RSS] 開始掃描...")

    all_feeds = ZH_MEDIA_FEEDS + MEDIUM_FEEDS + JP_MEDIA_FEEDS

    for feed in all_feeds:
        print(f"  ├── [{feed.get('lang','?')}] {feed['name']} ...")
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
                feed.get("lang", "zh-TW"),
                feed.get("source_score_bonus", 10),
            )
            if art:
                articles.append(art)
            time.sleep(SLEEP_BETWEEN_REQUESTS * 0.5)

    print(f"  └── 媒體 RSS 小計：{len(articles)} 篇")
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
        if is_finance_noise(url, title, desc):
            continue
        if not is_product_content(combined):
            continue

        brands = brand_in_text(combined)
        if not brands:
            continue

        systems = classify_systems(brands, combined)
        if not systems:
            continue

        tags = analyze_tags(title, desc)
        lang = detect_lang(combined)
        is_zhtw = (lang == "zh-TW")
        score = calculate_score(title, desc, tags, lang, source_bonus=20, brand_hits=len(brands))

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
            "systems":  systems,
            "types":    tags,
            "is_zhtw":  is_zhtw,
            "lang":     lang,
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

LANG_PRIORITY = {"zh-TW": 3, "ja": 2, "en": 1}


def collect_all_intelligence():
    print("🚀 開始執行競品情報收集（2026-09 · PMS/CRM/HR）")
    print(f"   語言優先：繁體中文 > 英文 > 日文")
    print(f"   收集時間：{datetime.utcnow().isoformat()} UTC\n")

    all_articles: list[dict] = []

    # 1. Google News RSS（繁中 + 英文 + 日文）
    all_articles += collect_google_news()

    # 2. 多語系媒體 RSS（zh-TW + Medium + 日媒）
    all_articles += collect_media_feeds()

    # 3. Threads（公開貼文 scraping）
    all_articles += collect_threads()

    # 去重
    all_articles = deduplicate(all_articles)
    print(f"\n🔍 去重後：{len(all_articles)} 篇")

    # 排序：語言優先（繁中>日>英），再依 score
    all_articles.sort(
        key=lambda x: (LANG_PRIORITY.get(x.get("lang", "en"), 0), x.get("score", 0)),
        reverse=True,
    )

    # 補抓 thumbnail（控制速率）
    all_articles = enrich_thumbnails(all_articles, limit=30)

    # 統計
    zhtw_count = sum(1 for a in all_articles if a.get("lang") == "zh-TW")
    ja_count   = sum(1 for a in all_articles if a.get("lang") == "ja")
    en_count   = sum(1 for a in all_articles if a.get("lang") == "en")
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
            "lang_breakdown": {"zh_TW": zhtw_count, "en": en_count, "ja": ja_count},
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
    print(f"   日文   : {ja_count} 篇")
    print(f"   輸出   : data/articles.json")


if __name__ == "__main__":
    collect_all_intelligence()