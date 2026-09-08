"""
PMS / CRM / HR / TECH Intelligence Collector
優化版（2026-09，實體 + 內容分類雙軸）

收集範圍：繁體中文（優先） > 英文
收集來源：
  - Google News RSS（繁中 + 英文，品牌驅動）
  - 科技新報、Inside、Mashdigi、方格子（zh-TW）
  - Medium tag / publication（en + zh-TW）
  - 科技趨勢 TECH_FEEDS：AI 前沿、國際科技、台灣科技、設計/UX
  - Threads（公開 profile scraping）

特性：
  - 追蹤範圍：以「公司/產品實體」為單位（PMS/CRM/HR/TECH 四個系統）
  - 內容類型：分類標籤（產品更新/功能發布/融資動態/財報營運/人事異動/產業趨勢/AI 技術/用戶體驗）
  - 不再使用財經黑名單、產品白名單過濾；全部收下由 UI 篩選
  - 收錄門檻：命中任一追蹤實體（品牌 或 TECH 來源）
  - 語言優先權：繁體中文 > 英文
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
    "BambooHR": {
        "system": "HR",
        "keywords": ["BambooHR", "small business HR", "HRIS"],
    },
    "Gusto": {
        "system": "HR",
        "keywords": ["Gusto payroll", "Gusto HR", "Gusto benefits"],
    },
    "Rippling": {
        "system": "HR",
        "keywords": ["Rippling", "workforce management", "employee onboarding"],
    },
    "Deel": {
        "system": "HR",
        "keywords": ["Deel", "global payroll", "EOR", "contractor management"],
    },
    "Personio": {
        "system": "HR",
        "keywords": ["Personio", "European HR", "SMB HRIS"],
    },
    "Paylocity": {
        "system": "HR",
        "keywords": ["Paylocity", "payroll platform", "workforce solutions"],
    },
    "ADP Workforce Now": {
        "system": "HR",
        "keywords": ["ADP Workforce Now", "ADP payroll", "ADP HR"],
    },
    "Ceridian Dayforce": {
        "system": "HR",
        "keywords": ["Ceridian Dayforce", "Dayforce", "Ceridian HCM"],
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
    "Salesforce": {
        "system": "CRM",
        "keywords": ["Salesforce", "Sales Cloud", "Service Cloud", "Marketing Cloud", "Einstein AI"],
    },
    "Zoho CRM": {
        "system": "CRM",
        "keywords": ["Zoho CRM", "Zoho One", "Zoho Bigin"],
    },
    "Pipedrive": {
        "system": "CRM",
        "keywords": ["Pipedrive", "sales pipeline CRM", "deal management"],
    },
    "Zendesk Sell": {
        "system": "CRM",
        "keywords": ["Zendesk Sell", "Zendesk CRM", "Zendesk sales"],
    },
    "Freshsales": {
        "system": "CRM",
        "keywords": ["Freshsales", "Freshworks CRM", "Freshsales Suite"],
    },
    "Monday CRM": {
        "system": "CRM",
        "keywords": ["Monday CRM", "monday.com sales", "monday sales CRM"],
    },
    "Copper CRM": {
        "system": "CRM",
        "keywords": ["Copper CRM", "Copper for Google", "Google Workspace CRM"],
    },
    "Close.com": {
        "system": "CRM",
        "keywords": ["Close CRM", "Close.com", "inside sales CRM"],
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
    "Guesty": {
        "system": "PMS",
        "keywords": ["Guesty", "short-term rental", "vacation rental software"],
    },
    "Hostaway": {
        "system": "PMS",
        "keywords": ["Hostaway", "vacation rental management", "STR software"],
    },
    "WebRezPro": {
        "system": "PMS",
        "keywords": ["WebRezPro", "cloud hotel software"],
    },
    "InnRoad": {
        "system": "PMS",
        "keywords": ["InnRoad", "small hotel PMS"],
    },
    "Sirvoy": {
        "system": "PMS",
        "keywords": ["Sirvoy", "hotel booking system"],
    },
    "roomMaster": {
        "system": "PMS",
        "keywords": ["roomMaster", "InnQuest", "hospitality PMS"],
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
        "url": "https://vocus.cc/api/rss?search=CRM",
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
    # 中文 publication — starbugs-io / pmの生存日記 已停刊/搬遷，改用仍活躍的中文 tag
    {"name": "Medium-CRM-TW",    "url": "https://medium.com/feed/tag/客戶關係管理", "lang": "zh-TW", "source_score_bonus": 15},
]

# ──────────────────────────────────────────
# 科技趨勢 / AI 發展 (TECH_FEEDS) — 主題型來源，非品牌驅動
# 四個子桶，source 名稱以 "TECH/<bucket>·<publication>" 前綴
# 用於前端在「科技趨勢」Tab 底下做子分類（AI 前沿/國際科技/台灣科技/設計UX）
# ──────────────────────────────────────────

TECH_FEEDS = [
    # A. AI 前沿（Anthropic / OpenAI / Figma 已停用 RSS；改用 Google DeepMind + HuggingFace）
    {"name": "TECH/AI·DeepMind",    "url": "https://deepmind.google/blog/rss.xml",          "lang": "en", "source_score_bonus": 20},
    {"name": "TECH/AI·HuggingFace", "url": "https://huggingface.co/blog/feed.xml",          "lang": "en", "source_score_bonus": 15},

    # B. 國際科技
    {"name": "TECH/Global·TechCrunch",   "url": "https://techcrunch.com/feed/",                             "lang": "en", "source_score_bonus": 15},
    {"name": "TECH/Global·TheVerge",     "url": "https://www.theverge.com/rss/index.xml",                   "lang": "en", "source_score_bonus": 15},
    {"name": "TECH/Global·Wired",        "url": "https://www.wired.com/feed/rss",                           "lang": "en", "source_score_bonus": 10},
    {"name": "TECH/Global·MITTechReview","url": "https://www.technologyreview.com/feed/",                   "lang": "en", "source_score_bonus": 15},
    {"name": "TECH/Global·HackerNews",   "url": "https://hnrss.org/frontpage",                              "lang": "en", "source_score_bonus": 10},

    # C. 台灣 / 中文科技（technews/inside/mashdigi 已在 ZH_MEDIA_FEEDS，這裡補新來源；PanX SSL 錯誤已停用）
    {"name": "TECH/TW·iThome",         "url": "https://www.ithome.com.tw/rss",                    "lang": "zh-TW", "source_score_bonus": 25},
    {"name": "TECH/TW·TechOrange",     "url": "https://buzzorange.com/techorange/feed/",          "lang": "zh-TW", "source_score_bonus": 20},
    {"name": "TECH/TW·sspai",          "url": "https://sspai.com/feed",                            "lang": "zh-TW", "source_score_bonus": 15},

    # D. 設計 / UX（呼應本專案 UIUX 導向）
    {"name": "TECH/Design·NNGroup",       "url": "https://www.nngroup.com/feed/rss/",              "lang": "en", "source_score_bonus": 20},
    {"name": "TECH/Design·Smashing",      "url": "https://www.smashingmagazine.com/feed/",         "lang": "en", "source_score_bonus": 15},
    {"name": "TECH/Design·UXCollective",  "url": "https://uxdesign.cc/feed",                       "lang": "en", "source_score_bonus": 15},
]

# 用於判定 source 是否屬於 TECH（未命中品牌白名單也收）
TECH_SOURCE_PREFIX = "TECH/"

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
    回傳 'zh-TW' | 'en'。
    優先序：來源 hint > 繁體字集 > 預設英文。
    （日文來源已停用；日本品牌若被英/中報導仍會被收，語言依內容判定。）
    """
    if source_lang_hint in ("zh-TW", "en"):
        return source_lang_hint

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


def classify_systems(brands: list[str], text: str, source_name: str = "") -> list[str]:
    """
    先從品牌回推 system，再用文字關鍵字補強；
    若來源屬 TECH_FEEDS 且未命中任何品牌，標記為 TECH。
    多命中則多標（PMS/HR/CRM/TECH 可共存）。
    """
    systems = {TARGET_SOURCES[b]["system"] for b in brands if b in TARGET_SOURCES}
    lower = text.lower()
    for sys_name, kws in SYSTEMS_KEYWORDS.items():
        if any(k.lower() in lower for k in kws):
            systems.add(sys_name)
    if source_name.startswith(TECH_SOURCE_PREFIX):
        systems.add("TECH")
    return sorted(systems)

# ──────────────────────────────────────────
# 內容類型分類（實體 + 內容分類雙軸的分類軸）
# 意圖為主的 8 類，取代舊 5 類黑白名單策略
# ──────────────────────────────────────────

CONTENT_TYPE_RULES: list[tuple[str, list[str]]] = [
    # 產品更新：產品層級公告
    ("產品更新", [
        "release", "launch", "unveils", "rolls out", "ships", "ga release",
        "推出", "上線", "改版", "版本", "發表", "問世",
    ]),
    # 功能發布：feature 顆粒度
    ("功能發布", [
        "new feature", "feature update", "adds", "introduces", "now supports", "brings",
        "新增", "新功能", "支援", "加入", "上新",
    ]),
    # 融資動態：早期到成長期資金
    ("融資動態", [
        "funding", "raises", "raised", "series a", "series b", "series c", "series d",
        "seed round", "valuation", "closes round", "venture round",
        "融資", "募資", "估值", "投資", "獲投", "輪次",
    ]),
    # 財報 / 營運數據：財務相關
    ("財報營運", [
        "earnings", "revenue", "quarterly", "guidance", "arr ", "mrr ", "profit",
        "fiscal", "gaap", "financial results",
        "財報", "營收", "季報", "業績", "毛利", "獲利", "營業額",
    ]),
    # 人事異動：高管、招募
    ("人事異動", [
        "ceo", "cto", "cfo", "cpo", "hires", "appoints", "joins", "resigns", "steps down",
        "chief officer", "chairman", "chairwoman", "president",
        "上任", "離任", "出任", "接任", "空降", "挖角", "任命", "辭任",
    ]),
    # 產業趨勢：分析型
    ("產業趨勢", [
        "market", "trend", "report", "forecast", "study", "survey", "analysis",
        "趨勢", "研究", "調查", "洞察", "報告", "分析",
    ]),
    # AI 技術
    ("AI 技術", [
        "ai ", " ai,", "artificial intelligence", "llm", "gpt", "claude", "gemini",
        "generative", "copilot", "agent ", "agentic", "openai", "anthropic",
        "人工智慧", "生成式", "大模型", "智能體",
    ]),
    # 用戶體驗：UX/設計向（延續 UIUX 專案主線）
    ("用戶體驗", [
        "ux", "ui/", "user experience", "usability", "redesign", "design system",
        "dashboard", "onboarding", "interface",
        "介面", "體驗", "設計", "重新設計", "儀表板", "使用者",
    ]),
]


def analyze_tags(title: str, summary: str) -> list[str]:
    """
    以內容意圖為主的分類，一篇文章可命中多類。
    未命中任何規則 → 預設歸為「產業趨勢」（fallback）。
    """
    text = f" {title} {summary} ".lower()
    tags: list[str] = []
    for tag, kws in CONTENT_TYPE_RULES:
        if any(k in text for k in kws):
            tags.append(tag)
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
    # 語言加權：繁中 > 英文
    if lang == "zh-TW":
        score += 40
    # 標籤加權（新 8 類）
    if "產品更新" in tags:  score += 15
    if "功能發布" in tags:  score += 15
    if "用戶體驗" in tags:  score += 15
    if "AI 技術" in tags:   score += 12
    if "人事異動" in tags:  score += 8
    if "融資動態" in tags:  score += 8
    if "產業趨勢" in tags:  score += 5
    if "財報營運" in tags:  score -= 5   # 不擋、只降權
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

    tags       = analyze_tags(title, desc)
    lang       = detect_lang(combined, source_lang)
    is_zhtw    = (lang == "zh-TW")
    brands     = brand_in_text(combined)
    brand_hits = len(brands)

    is_tech_source = source_name.startswith(TECH_SOURCE_PREFIX)

    # 收錄門檻（實體制）：命中任一追蹤品牌，或來源為 TECH 主題來源。
    # 兩者皆非 → 丟。這是唯一的過濾閘門，取代舊的財經/產品雙層黑白名單。
    if brand_hits == 0 and not is_tech_source:
        return None

    systems = classify_systems(brands, combined, source_name)
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
    """抓取繁中媒體 + 英文 Medium + TECH 主題 RSS。"""
    articles = []
    print("\n📰 [多語系媒體 RSS] 開始掃描...")

    all_feeds = ZH_MEDIA_FEEDS + MEDIUM_FEEDS + TECH_FEEDS

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

        brands = brand_in_text(combined)
        if not brands:
            # Threads 屬品牌帳號抓取，未命中任一追蹤品牌即略過
            continue

        systems = classify_systems(brands, combined, source_name=f"Threads/@{account}")
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

LANG_PRIORITY = {"zh-TW": 2, "en": 1}


def collect_all_intelligence():
    print("🚀 開始執行競品情報收集（2026-09 · PMS/CRM/HR/TECH）")
    print(f"   收錄軸：實體（品牌）+ 內容分類（8 類）")
    print(f"   語言優先：繁體中文 > 英文")
    print(f"   收集時間：{datetime.utcnow().isoformat()} UTC\n")

    all_articles: list[dict] = []

    # 1. Google News RSS（繁中 + 英文，品牌驅動）
    all_articles += collect_google_news()

    # 2. 媒體 RSS（zh-TW 主流 + Medium 標籤 + TECH 主題）
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
    print(f"   系統分布: {by_system}")
    print(f"   類型分布: {by_type}")
    print(f"   輸出   : data/articles.json")


if __name__ == "__main__":
    collect_all_intelligence()