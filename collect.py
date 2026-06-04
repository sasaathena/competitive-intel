"""
EIP / CRM 競品情報自動收集腳本
- 來源：Google News RSS（針對各競品品牌）
- 過濾：排除財經/股市新聞（兩層過濾）
- 排序：繁體中文內容優先
- 縮圖：自動抓取 og:image
"""

import os
import json
import hashlib
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ── 監控品牌 ───────────────────────────────────────────────────────────────────
TARGET_SOURCES = {
    # EIP / 人資系統
    "Workday": {
        "system": "EIP",
        "keywords": ["HCM", "HR", "employee experience", "人資", "工作流", "員工體驗", "績效管理"],
    },
    "SAP SuccessFactors": {
        "system": "EIP",
        "keywords": ["SuccessFactors", "員工體驗", "HR", "人才管理", "talent management"],
    },
    "HiBob": {
        "system": "EIP",
        "keywords": ["HRIS", "Modern HR", "人資系統", "HR platform", "employee"],
    },
    "Workday Adaptive": {
        "system": "EIP",
        "keywords": ["adaptive planning", "workforce", "HR analytics", "dashboard"],
    },
    "BambooHR": {
        "system": "EIP",
        "keywords": ["BambooHR", "HR software", "人事", "employee management"],
    },
    # CRM / 客戶關係
    "HubSpot": {
        "system": "CRM",
        "keywords": ["CRM", "行銷自動化", "sales hub", "客服", "客戶關係", "marketing automation"],
    },
    "Salesforce": {
        "system": "CRM",
        "keywords": ["Salesforce CRM", "Sales Cloud", "客戶體驗", "AI CRM", "Einstein"],
    },
    "Pipedrive": {
        "system": "CRM",
        "keywords": ["Pipedrive", "sales pipeline", "CRM", "銷售漏斗"],
    },
    "Zoho CRM": {
        "system": "CRM",
        "keywords": ["Zoho CRM", "客戶管理", "Zia AI", "sales automation"],
    },
    "Freshsales": {
        "system": "CRM",
        "keywords": ["Freshsales", "Freshworks", "CRM", "customer engagement"],
    },
}

# ── 財經黑名單（標題層：命中 1 個即排除）────────────────────────────────────
# 設計原則：用「短語」不用「單詞」避免誤殺正常產品文
# 例：revenue 單獨太廣，改用 "revenue beats/fell/guidance" 等組合
FINANCE_TITLE_BLACKLIST = [
    # 股市行情
    "stock", "stocks", "stock price", "stock up", "stock down",
    "share price", "shares rose", "shares fell", "shares up", "shares down",
    # 財報
    "earnings", "quarterly earnings", "annual earnings",
    "revenue beats", "revenue misses", "revenue fell", "revenue declined",
    "revenue guidance", "revenue outlook", "revenue topped",
    "net income", "operating income", "gross margin miss",
    "q1 results", "q2 results", "q3 results", "q4 results",
    "full-year results", "fiscal year results", "financial results",
    "financial guidance", "fiscal quarter results",
    # 投資人
    "investor day", "investors react", "analyst rating",
    "analyst upgrade", "analyst downgrade", "price target",
    "buy rating", "sell rating", "hold rating",
    "ipo", "spac", "sec filing", "10-k", "10-q",
    "dividend", "buyback", "short seller",
    "nasdaq", "nyse", "dow jones",
    # 中文股市
    "股票", "股價", "股市", "漲停", "跌停", "融資",
    # 中文財報
    "財報", "法說會", "年報", "季報", "財務報告",
    "營收", "淨利", "毛利率", "eps", "每股盈餘",
    "市值", "本益比", "殖利率", "配息", "除權息",
    # 中文投資
    "投資人", "法人", "外資", "散戶",
    "掛牌", "興櫃", "上市",
    "分析師", "目標價", "買進評等", "賣出評等",
    "獲利", "虧損", "轉虧為盈",
]

# 財經黑名單（內文層：命中 ≥ 2 個才排除，避免誤殺提到數字的產品文）
FINANCE_BODY_BLACKLIST = [
    "stock price", "share price", "earnings per share",
    "quarterly results", "fiscal quarter", "revenue guidance",
    "investor", "analyst rating", "market cap",
    "dividend", "buyback", "nasdaq", "nyse",
    "股票", "股價", "財報", "法說會",
    "投資人", "eps", "市值", "配息", "殖利率",
]

# ── 產品相關關鍵字（至少命中 1 個才保留）────────────────────────────────────
PRODUCT_KEYWORDS = [
    # 英文
    "crm", "sales", "marketing", "customer experience", "customer success",
    "hr", "hris", "hcm", "employee", "workforce", "talent",
    "dashboard", "analytics", "workflow", "ui", "ux", "design",
    "feature", "release", "update", "automation", "ai", "integration",
    "onboarding", "usability", "interface", "product",
    # 中文
    "人資", "員工體驗", "客戶體驗", "儀表板", "看板",
    "工作流", "流程", "產品更新", "功能更新", "新功能",
    "自動化", "數據分析", "人工智慧", "人才管理",
    "數位轉型", "企業軟體", "介面設計", "用戶體驗",
    "CRM", "EIP", "HRIS", "功能", "設計",
]


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def is_finance_news(title: str, body: str) -> bool:
    title_lower = title.lower()
    if any(kw in title_lower for kw in FINANCE_TITLE_BLACKLIST):
        return True
    body_lower = body.lower()
    hits = sum(1 for kw in FINANCE_BODY_BLACKLIST if kw in body_lower)
    return hits >= 2


def is_product_content(text: str) -> bool:
    text = text.lower()
    return any(k.lower() in text for k in PRODUCT_KEYWORDS)


def is_traditional_chinese(text: str) -> bool:
    """偵測是否含繁體中文（用於優先排序）"""
    trad = ["們", "與", "機", "會", "網", "統", "體", "資", "務", "來", "國"]
    simp = ["们", "体", "资", "应", "样", "这", "时", "产"]
    has_trad = sum(1 for c in trad if c in text) >= 2
    has_simp = any(c in text for c in simp)
    return has_trad and not has_simp


def analyze_tags(title: str, summary: str) -> list:
    text = (title + " " + summary).lower()
    tags = []
    if any(k in text for k in [
        "ui", "ux", "體驗", "dashboard", "看板", "介面", "設計",
        "usability", "accessibility", "navigation", "onboarding", "user experience"
    ]):
        tags.append("用戶體驗")
    if any(k in text for k in [
        "更新", "release", "新功能", "feature", "升級", "發布", "launch",
        "introduce", "rollout", "now available", "新增"
    ]):
        tags.append("功能更新")
    if any(k in text for k in [
        "趨勢", "報告", "trend", "report", "分析", "白皮書",
        "survey", "研究", "insight", "benchmark", "forecast", "調查"
    ]):
        tags.append("產業趨勢")
    if any(k in text for k in [
        "dashboard", "case study", "案例", "儀表板", "data viz", "visualization"
    ]):
        if "Dashboard案例" not in tags:
            tags.append("Dashboard案例")
    return tags if tags else ["產業趨勢"]


def fetch_thumbnail(url: str, timeout: int = 8) -> str:
    """嘗試抓取頁面的 og:image 作為縮圖，失敗回傳空字串"""
    try:
        r = requests.get(url, timeout=timeout, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        soup = BeautifulSoup(r.content, "html.parser")

        # 優先 og:image
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            img = og["content"].strip()
            if img.startswith("http"):
                return img

        # 次選 twitter:image
        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            img = tw["content"].strip()
            if img.startswith("http"):
                return img

    except Exception:
        pass
    return ""


def calculate_score(title: str, description: str, tags: list, is_zhtw: bool) -> int:
    score = 50
    if "功能更新" in tags:
        score += 15
    if "用戶體驗" in tags:
        score += 15
    if "Dashboard案例" in tags:
        score += 10
    full = (title + " " + description).lower()
    if any(k in full for k in ["dashboard", "儀表板", "ux", "ui", "設計", "體驗"]):
        score += 20
    if is_zhtw:
        score += 40   # 繁中大幅加權
    return score


# ── 主程式 ────────────────────────────────────────────────────────────────────

def collect_all_intelligence():
    articles = []
    skipped_finance = 0
    skipped_irrelevant = 0

    print("🚀 開始收集 EIP / CRM 情報\n")

    for brand, info in TARGET_SOURCES.items():
        print(f"🔍 {brand}")
        query = " OR ".join(f'"{k}"' for k in info["keywords"])
        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={requests.utils.quote(brand)}+({requests.utils.quote(query)})+when:7d"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )

        try:
            resp = requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(resp.content, "xml")
            items = soup.find_all("item")

            brand_count = 0
            for item in items[:12]:
                title = (item.title.text or "").strip()
                url   = (item.link.text or "").strip()
                pub   = (item.pubDate.text or "").strip()
                desc  = ""
                if item.description:
                    desc = BeautifulSoup(item.description.text, "html.parser").get_text(" ", strip=True)

                if not title or not url:
                    continue

                # 財經過濾
                if is_finance_news(title, desc):
                    skipped_finance += 1
                    print(f"  ⛔ {title[:55]}")
                    continue

                # 相關性過濾
                if not is_product_content(title + " " + desc):
                    skipped_irrelevant += 1
                    continue

                # 日期解析
                try:
                    date_iso = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z").isoformat()
                except Exception:
                    date_iso = datetime.utcnow().isoformat()

                is_zhtw = is_traditional_chinese(title + desc)
                tags    = analyze_tags(title, desc)
                summary = desc[:280] if desc else f"{brand} 最新產品情報"

                # 縮圖（有流量限制時可關閉：thumbnail = ""）
                thumbnail = fetch_thumbnail(url)
                time.sleep(0.5)   # 禮貌性間隔

                uid = "rss_" + hashlib.md5(url.encode()).hexdigest()[:10]

                articles.append({
                    "id":        uid,
                    "channel":   "rss",
                    "source":    brand,
                    "title":     title,
                    "summary":   summary,
                    "url":       url,
                    "thumbnail": thumbnail,
                    "date":      date_iso,
                    "fetched":   datetime.utcnow().isoformat(),
                    "systems":   [info["system"]],
                    "types":     tags,
                    "is_zhtw":   is_zhtw,
                    "score":     calculate_score(title, desc, tags, is_zhtw),
                })
                brand_count += 1
                print(f"  ✓ {'🇹🇼 ' if is_zhtw else '  '}{title[:52]}")

            print(f"  → {brand_count} 筆\n")
            time.sleep(1)

        except Exception as e:
            print(f"  ❌ 失敗: {e}\n")

    # 統計
    by_system  = {}
    by_type    = {}
    zhtw_count = 0
    for a in articles:
        for s in a["systems"]:
            by_system[s] = by_system.get(s, 0) + 1
        for t in a["types"]:
            by_type[t] = by_type.get(t, 0) + 1
        if a.get("is_zhtw"):
            zhtw_count += 1

    os.makedirs("data", exist_ok=True)
    output = {
        "stats": {
            "total":              len(articles),
            "new_today":          len(articles),
            "last_updated":       datetime.utcnow().isoformat(),
            "skipped_finance":    skipped_finance,
            "skipped_irrelevant": skipped_irrelevant,
            "zhtw_count":         zhtw_count,
            "by_system":          by_system,
            "by_type":            by_type,
            "by_channel":         {"rss": len(articles)},
        },
        "articles": sorted(articles, key=lambda x: x["score"], reverse=True),
    }

    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("=" * 48)
    print(f"  ✅ 保留    {len(articles):>4} 筆（繁中 {zhtw_count} 筆）")
    print(f"  ⛔ 財經排除 {skipped_finance:>3} 筆")
    print(f"  ⚪ 不相關   {skipped_irrelevant:>3} 筆")
    print("=" * 48)


if __name__ == "__main__":
    collect_all_intelligence()
