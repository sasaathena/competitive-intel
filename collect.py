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

FINANCE_BLACKLIST = [
    "stock", "stocks", "earnings", "revenue", "market cap",
    "investor", "share price", "financial results", "quarterly",
    "股票", "股價", "財報", "營收", "法說會",
    "投資人", "eps", "獲利", "市值", "配息", "殖利率"
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


def is_finance_news(text):
    text = text.lower()
    return any(k.lower() in text for k in FINANCE_BLACKLIST)


def is_product_content(text):
    text = text.lower()
    return any(k.lower() in text for k in PRODUCT_KEYWORDS)


def analyze_tags(title, summary):
    text = (title + " " + summary).lower()
    tags = []

    if any(k in text for k in ["ui", "ux", "體驗", "dashboard", "看板", "流程"]):
        tags.append("用戶體驗")

    if any(k in text for k in ["更新", "release", "新功能", "feature", "升級", "發布"]):
        tags.append("功能更新")

    if any(k in text for k in ["趨勢", "報告", "trend", "report", "分析", "白皮書"]):
        tags.append("產業趨勢")

    if not tags:
        tags.append("產業趨勢")

    return tags


def is_traditional_chinese(text):
    trad_signals = ["們", "與", "機", "會", "網", "統", "體", "資"]
    simp_signals = ["们", "体", "资", "应"]
    return any(x in text for x in trad_signals) and not any(x in text for x in simp_signals)


def calculate_score(title, description, tags):
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

    print("🚀 開始收集 EIP / CRM 情報")

    for brand, info in TARGET_SOURCES.items():
        print(f"🔍 {brand}")

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

            for item in items[:8]:
                title = item.title.text.strip() if item.title else ""
                url = item.link.text.strip() if item.link else ""
                pub_date = item.pubDate.text.strip() if item.pubDate else ""

                description = ""
                if item.description:
                    description = BeautifulSoup(
                        item.description.text,
                        "html.parser"
                    ).get_text(" ", strip=True)

                full_text = f"{title} {description}"

                if is_finance_news(full_text):
                    continue

                if not is_product_content(full_text):
                    continue

                try:
                    date_iso = datetime.strptime(
                        pub_date,
                        "%a, %d %b %Y %H:%M:%S %Z"
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

        except Exception as e:
            print(f"❌ {brand} 失敗: {e}")

    data_dir = "data"
    os.makedirs(data_dir, exist_ok=True)

    output = {
        "stats": {
            "total": len(articles),
            "last_updated": datetime.utcnow().isoformat()
        },
        "articles": sorted(
            articles,
            key=lambda x: x["date"],
            reverse=True
        )
    }

    with open(
        os.path.join(data_dir, "articles.json"),
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ 完成，共 {len(articles)} 筆")


if __name__ == "__main__":
    collect_all_intelligence()
