"""
EIP / CRM Intelligence Collector
重構版（2026-06）

特性：
- Google News RSS
- 財經新聞雙層過濾
- EIP / CRM 白名單
- Dashboard / UX 標籤分析
- 繁體中文加權
- Thumbnail fallback
- GitHub Pages articles.json 相容格式
"""

import os
import json
import time
import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0"}

FALLBACK_THUMBNAIL = (
    "https://images.unsplash.com/"
    "photo-1552664730-d307ca884978"
)

TARGET_SOURCES = {
    "Workday": {"system": "EIP", "keywords": ["HCM","employee experience","人資","員工體驗","workflow","dashboard"]},
    "SAP SuccessFactors": {"system": "EIP", "keywords": ["SuccessFactors","人才管理","employee experience","HR"]},
    "Apollo": {"system": "EIP", "keywords": ["Apollo","MayoHR","人事管理","考勤","薪資","EIP"]},
    "HiBob": {"system": "EIP", "keywords": ["HiBob","HRIS","employee engagement","dashboard"]},
    "HubSpot": {"system": "CRM", "keywords": ["CRM","marketing automation","sales hub","customer experience","AI CRM"]},
    "Stripe": {"system": "CRM", "keywords": ["Stripe","billing","subscription","customer experience","payment platform"]},
}

FINANCE_TITLE_BLACKLIST = [
    "market cap", "earnings per share", "quarterly results",
    "股價", "除權息", "個股", "大盤", "走勢", "配息"
]

FINANCE_BODY_BLACKLIST = [
    "investor","market cap","earnings per share","quarterly results",
    "股票","股價","走勢","法說會","個股","市值","配息","除權息"
]

PRODUCT_KEYWORDS = [
    "CRM","sales","marketing","customer experience",
    "HR","hris","hcm","employee","talent",
    "dashboard","analytics","workflow","ui","ux",
    "feature","release","automation","ai","integration",
    "人資","員工體驗","客戶體驗","儀表板","工作流","FinTech","改版"
    "功能更新","功能","自動化","數據分析","人工智慧",
    "CRM","EIP","HRIS"
]


def is_finance_news(title, body):
    t = title.lower()
    if any(k.lower() in t for k in FINANCE_TITLE_BLACKLIST):
        return True

    b = body.lower()
    hits = sum(1 for k in FINANCE_BODY_BLACKLIST if k.lower() in b)
    return hits >= 2


def is_product_content(text):
    text = text.lower()
    return any(k.lower() in text for k in PRODUCT_KEYWORDS)


def is_traditional_chinese(text):
    trad = ["們","與","機","會","網","統","體","資"]
    simp = ["们","体","资","这","样"]
    return sum(c in text for c in trad) >= 2 and not any(c in text for c in simp)


def analyze_tags(title, summary):
    text = f"{title} {summary}".lower()
    tags = []

    if any(k in text for k in ["ui","ux","dashboard","介面","設計","體驗"]):
        tags.append("用戶體驗")

    if any(k in text for k in ["release","feature","更新","新功能","launch"]):
        tags.append("功能更新")

    if any(k in text for k in ["report","trend","研究","分析","survey"]):
        tags.append("產業趨勢")

    if "dashboard" in text or "儀表板" in text:
        tags.append("Dashboard案例")

    return tags or ["產業趨勢"]


def resolve_news_url(url):
    try:
        r = requests.get(url, timeout=10, allow_redirects=True, headers=HEADERS)
        return r.url
    except Exception:
        return url


def fetch_thumbnail(url):
    try:
        real_url = resolve_news_url(url)

        r = requests.get(real_url, timeout=10, headers=HEADERS)
        soup = BeautifulSoup(r.text, "html.parser")

        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"]

        tw = soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            return tw["content"]

    except Exception:
        pass

    return FALLBACK_THUMBNAIL


def calculate_score(title, desc, tags, is_zhtw):
    score = 50

    if "功能更新" in tags:
        score += 15

    if "用戶體驗" in tags:
        score += 15

    if "Dashboard案例" in tags:
        score += 10

    if is_zhtw:
        score += 40

    return score


def parse_date(pub):
    try:
        return parsedate_to_datetime(pub).isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def collect_all_intelligence():
    articles = []

    for brand, info in TARGET_SOURCES.items():
        query = " OR ".join(f'"{k}"' for k in info["keywords"])

        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={requests.utils.quote(brand)}+({requests.utils.quote(query)})+when:7d"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        )

        try:
            resp = requests.get(rss_url, timeout=15, headers=HEADERS)
            soup = BeautifulSoup(resp.content, "xml")

            for item in soup.find_all("item")[:12]:

                title_tag = item.find("title")
                link_tag = item.find("link")
                pub_tag = item.find("pubDate")
                desc_tag = item.find("description")

                if not title_tag or not link_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = link_tag.get_text(strip=True)

                pub = pub_tag.get_text(strip=True) if pub_tag else ""

                desc = ""
                if desc_tag:
                    desc = BeautifulSoup(
                        desc_tag.get_text(),
                        "html.parser"
                    ).get_text(" ", strip=True)

                if is_finance_news(title, desc):
                    continue

                if not is_product_content(title + " " + desc):
                    continue

                tags = analyze_tags(title, desc)
                is_zhtw = is_traditional_chinese(title + desc)

                articles.append({
                    "id": "rss_" + hashlib.md5(url.encode()).hexdigest()[:10],
                    "channel": "rss",
                    "source": brand,
                    "title": title,
                    "summary": desc[:280],
                    "url": url,
                    "thumbnail": fetch_thumbnail(url),
                    "date": parse_date(pub),
                    "fetched": datetime.utcnow().isoformat(),
                    "systems": [info["system"]],
                    "types": tags,
                    "is_zhtw": is_zhtw,
                    "score": calculate_score(title, desc, tags, is_zhtw),
                })

                time.sleep(0.3)

        except Exception as e:
            print(f"{brand}: {e}")

    articles.sort(key=lambda x: x["score"], reverse=True)

    os.makedirs("data", exist_ok=True)

    output = {
        "stats": {
            "total": len(articles),
            "new_today": len(articles),
            "last_updated": datetime.utcnow().isoformat(),
            "by_channel": {"rss": len(articles)}
        },
        "articles": articles
    }

    with open("data/articles.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Collected {len(articles)} articles")


if __name__ == "__main__":
    collect_all_intelligence()
