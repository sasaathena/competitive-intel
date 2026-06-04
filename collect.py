import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

TARGET_SOURCES = {
    "Workday": {
        "url": "https://www.workday.com/en-hk/homepage.html",
        "system": "EIP",
        "keywords": ["HCM", "HR", "人資", "工作流", "員工體驗", "績效"]
    },
    "SAP SuccessFactors": {
        "url": "https://www.sap.com/taiwan/products/hcm.html",
        "system": "EIP",
        "keywords": ["SuccessFactors", "員工體驗", "HR", "人才管理"]
    },
    "Apollo": {
        "url": "https://www.mayohr.com/tw/product/Apollo",
        "system": "EIP",
        "keywords": ["人事", "考勤", "薪資", "行動辦公", "EIP"]
    },
    "HiBob": {
        "url": "https://www.hibob.com/",
        "system": "EIP",
        "keywords": ["HRIS", "Modern HR", "人資系統"]
    },
    "Stripe": {
        "url": "https://stripe.com/",
        "system": "CRM",
        "keywords": ["支付", "訂閱", "Billing", "客戶體驗", "金流"]
    },
    "HubSpot": {
        "url": "https://www.hubspot.com/",
        "system": "CRM",
        "keywords": ["CRM", "行銷自動化", "Sales", "客服", "客戶關係"]
    }
}

# ── 財經黑名單（分兩層）────────────────────────────────────────────────────────
#
# 設計原則：
#   標題層  → 精準短語，命中 1 個就排除（財報/股市新聞的標題特徵詞）
#   內文層  → 較寬鬆的單詞，需命中 2 個以上才排除
#             （避免誤殺「產品帶動營收成長」這類正常產品文章）
#
# 邊界案例說明：
#   ❌ "revenue" 單獨不放標題層 → "CRM revenue growth driven by features" 會被誤殺
#   ✅ 改用 "revenue beats/misses/fell/declined" 等組合短語
#   ✅ "Q2 Results" / "Investor Day" / "earnings" 這類詞組在產品文幾乎不出現，可放標題層

FINANCE_TITLE_BLACKLIST = [
    # 英文 — 股市行情
    "stock", "stocks", "stock price", "stock up", "stock down",
    "share price", "shares rose", "shares fell", "shares up", "shares down",
    "market cap surges", "market cap falls",
    # 英文 — 財報關鍵詞組（單 revenue 不夠精準，改用組合）
    "earnings", "quarterly earnings", "annual earnings",
    "revenue beats", "revenue misses", "revenue topped", "revenue fell",
    "revenue declined", "revenue guidance", "revenue outlook",
    "net income", "operating income", "gross margin miss",
    "q1 results", "q2 results", "q3 results", "q4 results",
    "full-year results", "fiscal year results", "fiscal quarter results",
    "financial results", "financial guidance",
    # 英文 — 投資人相關
    "investor day", "investors", "analyst rating", "analyst upgrade", "analyst downgrade",
    "price target", "buy rating", "sell rating", "hold rating",
    "ipo", "spac", "sec filing", "10-k", "10-q",
    "dividend", "buyback", "short seller",
    "hedge fund", "private equity",
    "nasdaq", "nyse", "dow jones",
    # 中文 — 股市
    "股票", "股價", "股市", "漲停", "跌停", "融資融券",
    # 中文 — 財報
    "財報", "法說會", "年報", "季報", "財務報告",
    "營收", "淨利", "毛利率", "eps", "每股盈餘",
    "市值", "本益比", "殖利率", "配息", "除權息",
    # 中文 — 投資人
    "投資人", "法人", "外資", "散戶", "主力",
    "掛牌", "興櫃", "上市",
    "分析師", "目標價", "買進評等", "賣出評等",
    "獲利", "虧損", "轉虧為盈",
]

# 內文層：命中 2 個以上才排除
FINANCE_BODY_BLACKLIST = [
    "stock price", "share price", "earnings per share",
    "quarterly results", "fiscal quarter", "revenue guidance",
    "investor", "analyst rating", "market cap",
    "dividend", "buyback", "nasdaq", "nyse",
    "股票", "股價", "財報", "營收", "法說會",
    "投資人", "eps", "市值", "配息", "殖利率",
]

PRODUCT_KEYWORDS = [
    "crm", "sales", "marketing", "customer",
    "hr", "hris", "hcm", "employee", "workforce",
    "dashboard", "analytics", "workflow", "ui", "ux",
    "feature", "release", "update", "automation", "ai",
    "人資", "員工體驗", "客戶體驗", "儀表板", "看板",
    "工作流", "流程", "產品更新", "功能更新", "新功能",
    "自動化", "數據分析", "人工智慧", "人才管理",
    "數位轉型", "企業流程", "CRM", "EIP"
]


def is_finance_news(title: str, body: str) -> bool:
    """
    兩層過濾邏輯：
      層一：標題含黑名單短語 → 直接排除
      層二：內文命中黑名單詞 ≥ 2 個 → 排除
    回傳 True 表示「這是財經新聞，應排除」
    """
    title_lower = title.lower()
    if any(kw in title_lower for kw in FINANCE_TITLE_BLACKLIST):
        return True

    body_lower = body.lower()
    hits = sum(1 for kw in FINANCE_BODY_BLACKLIST if kw in body_lower)
    return hits >= 2


def is_product_content(text: str) -> bool:
    text = text.lower()
    return any(k.lower() in text for k in PRODUCT_KEYWORDS)


def analyze_tags(title: str, summary: str) -> list:
    text = (title + " " + summary).lower()
    tags = []

    if any(k in text for k in [
        "ui", "ux", "體驗", "dashboard", "看板", "流程", "介面", "設計",
        "usability", "accessibility", "navigation", "onboarding"
    ]):
        tags.append("用戶體驗")

    if any(k in text for k in [
        "更新", "release", "新功能", "feature", "升級", "發布", "launch",
        "introduce", "rollout", "now available"
    ]):
        tags.append("功能更新")

    if any(k in text for k in [
        "趨勢", "報告", "trend", "report", "分析", "白皮書", "survey",
        "研究", "insight", "benchmark", "forecast"
    ]):
        tags.append("產業趨勢")

    if not tags:
        tags.append("產業趨勢")

    return tags


def is_traditional_chinese(text: str) -> bool:
    trad_signals = ["們", "與", "機", "會", "網", "統", "體", "資"]
    simp_signals = ["们", "体", "资", "应"]
    return any(x in text for x in trad_signals) and not any(x in text for x in simp_signals)


def calculate_score(title: str, description: str, tags: list) -> int:
    score = 60

    if "功能更新" in tags:
        score += 15
    if "用戶體驗" in tags:
        score += 15

    full_text = f"{title} {description}".lower()
    if any(k in full_text for k in ["dashboard", "儀表板", "analytics", "ux", "ui"]):
        score += 20
    if is_traditional_chinese(title + description):
        score += 40

    return score


def collect_all_intelligence():
    articles = []
    skipped_finance = 0
    skipped_irrelevant = 0

    print("🚀 開始收集 EIP / CRM 情報")

    for brand, info in TARGET_SOURCES.items():
        print(f"\n🔍 {brand}")

        query = " OR ".join(info["keywords"])
        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={brand}+({query})+when:7d"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )

        try:
            response = requests.get(
                rss_url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            soup = BeautifulSoup(response.content, "xml")
            items = soup.find_all("item")

            brand_count = 0
            for item in items[:12]:
                title = item.title.text.strip() if item.title else ""
                url = item.link.text.strip() if item.link else ""
                pub_date = item.pubDate.text.strip() if item.pubDate else ""

                description = ""
                if item.description:
                    description = BeautifulSoup(
                        item.description.text, "html.parser"
                    ).get_text(" ", strip=True)

                # 層一＋層二財經過濾
                if is_finance_news(title, description):
                    skipped_finance += 1
                    print(f"  ⛔ 財經排除：{title[:55]}")
                    continue

                # 產品相關性過濾
                if not is_product_content(f"{title} {description}"):
                    skipped_irrelevant += 1
                    continue

                try:
                    date_iso = datetime.strptime(
                        pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                    ).isoformat()
                except Exception:
                    date_iso = datetime.utcnow().isoformat()

                summary = description[:300] if description else f"{brand} 最新產品情報"
                tags = analyze_tags(title, description)

                articles.append({
                    "id": f"rss_{hash(url)}",
                    "channel": "rss",
                    "source": brand,
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "date": date_iso,
                    "fetched": datetime.utcnow().isoformat(),
                    "systems": [info["system"]],
                    "types": tags,
                    "score": calculate_score(title, description, tags)
                })
                brand_count += 1
                print(f"  ✓ {title[:55]}")

            print(f"  → 收入 {brand_count} 筆")

        except Exception as e:
            print(f"  ❌ 失敗: {e}")

    # 輸出統計
    os.makedirs("data", exist_ok=True)

    by_system = {}
    by_type = {}
    for a in articles:
        for s in a["systems"]:
            by_system[s] = by_system.get(s, 0) + 1
        for t in a["types"]:
            by_type[t] = by_type.get(t, 0) + 1

    output = {
        "stats": {
            "total": len(articles),
            "new_today": len(articles),
            "last_updated": datetime.utcnow().isoformat(),
            "skipped_finance": skipped_finance,
            "skipped_irrelevant": skipped_irrelevant,
            "by_system": by_system,
            "by_type": by_type,
            "by_channel": {"rss": len(articles)},
        },
        "articles": sorted(articles, key=lambda x: x["date"], reverse=True)
    }

    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*45}")
    print(f"  ✅ 保留 {len(articles)} 筆")
    print(f"  ⛔ 財經排除 {skipped_finance} 筆")
    print(f"  ⚪ 不相關排除 {skipped_irrelevant} 筆")
    print(f"{'='*45}")


if __name__ == "__main__":
    collect_all_intelligence()
