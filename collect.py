import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# ── 1. 定義指定核心競品來源與屬性 ──────────────────────────────────────
TARGET_SOURCES = {
    "Workday": {
        "url": "https://www.workday.com/en-hk/homepage.html", 
        "system": "EIP",
        "keywords": ["HCM", "HR", "人資", "工作流", "員工體驗", "績效", "打卡"]
    },
    "SAP SuccessFactors": {
        "url": "https://www.sap.com/taiwan/products/hcm.html", 
        "system": "EIP",
        "keywords": ["SuccessFactors", "員工體驗", "HR", "人資趨勢", "人才管理"]
    },
    "Apollo": {
        "url": "https://www.mayohr.com/tw/product/Apollo", 
        "system": "EIP",
        "keywords": ["人事", "考勤", "薪資", "行動辦公", "EIP", "Mayo"]
    },
    "HiBob": {
        "url": "https://www.hibob.com/", 
        "system": "EIP",
        "keywords": ["Bob", "HRIS", "Culture", "Modern HR", "人資系統"]
    },
    "Stripe": {
        "url": "https://stripe.com/", 
        "system": "CRM",
        "keywords": ["支付", "訂閱", "Billing", "客戶體驗", "功能更新", "金流"]
    },
    "HubSpot": {
        "url": "https://www.hubspot.com/", 
        "system": "CRM",
        "keywords": ["CRM", "行銷自動化", "Sales", "客服", "趨勢", "客戶關係"]
    }
}

# ── 財經新聞排除規則 ──────────────────────────────────────
FINANCE_BLACKLIST = [
    "stock",
    "stocks",
    "earnings",
    "revenue",
    "market cap",
    "investor",
    "share price",
    "financial results",
    "quarterly",

    "股票",
    "股價",
    "財報",
    "營收",
    "法說會",
    "投資人",
    "EPS",
    "獲利",
    "市值",
    "配息",
    "殖利率"
]

# ── EIP / CRM 產品情報白名單 ─────────────────────────────
PRODUCT_KEYWORDS = [
    "dashboard",
    "workflow",
    "employee experience",
    "customer experience",
    "crm",
    "hr",
    "hris",
    "saas",
    "feature",
    "product update",
    "automation",
    "analytics",
    "ai",

    "儀表板",
    "看板",
    "工作流",
    "流程",
    "員工體驗",
    "客戶體驗",
    "功能更新",
    "產品更新",
    "新功能",
    "使用者體驗",
    "ui",
    "ux",
    "人資",
    "crm",
    "數據分析",
    "自動化",
    "人工智慧",
    "ai功能"
]

def is_finance_news(text):
    text = text.lower()
    return any(
        keyword.lower() in text
        for keyword in FINANCE_BLACKLIST
    )

def is_product_content(text):
    text = text.lower()
    return any(
        keyword.lower() in text
        for keyword in PRODUCT_KEYWORDS
    )

# ── 2. 智慧型標籤與情報類型判定 ──────────────────────────────────────
def analyze_tags(title, summary):
    text = (title + summary).lower()
    types = []
    
    # 1. 用戶體驗 (UIUX / Dashboard / 畫面)
    if any(k in text for k in ["ui", "ux", "體驗", "介面", "設計", "dashboard", "畫面", "看板", "視覺", "優化", "流程"]):
        types.append("用戶體驗")
        
    # 2. 功能更新 (改版 / Features / Release)
    if any(k in text for k in ["更新", "release", "新功能", "改版", "功能", "feature", "升級", "發布", "套件", "新上線"]):
        types.append("功能更新")
        
    # 3. 產業趨勢 (Market Trend / Reports)
    if any(k in text for k in ["趨勢", "報告", "未來", "市場", "trend", "report", "產業", "分析", "調查", "白皮書"]):
        types.append("產業趨勢")
        
    # 保底機制：若無明確關鍵字，歸類為產業趨勢
    if not types:
        types.append("產業趨勢")
        
    return types

# ── 3. 繁體中文特徵辨識邏輯（提高權重分數） ─────────────────────────────
def is_traditional_chinese(text):
    # 藉由常見繁體字跟語音助詞進行快速辨識
    trad_signals = ["的", "是", "我", "們", "與", "機", "會", "網", "業", "統", "體", "資", "應"]
    # 排除簡體常用而繁體不用的標記字 (如：体、资、们、应)
    simp_signals = ["体", "资", "们", "应", "发", "业"]
    
    has_trad = any(char in text for char in trad_signals)
    has_simp = any(char in text for char in simp_signals)
    
    return has_trad and not has_simp

# ── 4. 核心情報採集主程式 ──────────────────────────────────────────
def collect_all_intelligence():
    articles = []
    print("🚀 [開始執行] 聚焦 EIP 與 CRM 核心競品情報自動收集任務...")

    # 運用 Google News RSS 抓取各品牌一週內在繁體中文/台灣市場的最新情報動態 (包含官方 Blog 或主流報導轉載)
    for brand, info in TARGET_SOURCES.items():
        print(f"🔍 正在檢索競品：{brand} ({info['system']}) 相關繁中與國際市場動態...")
        
        # 建立雙語或繁中高相關搜尋 Query
        query_keywords = " OR ".join(info["keywords"])

rss_url = (
    "https://news.google.com/rss/search?"
    f"q={brand}+({query_keywords})+when:7d"
    "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)
        
        try:
            r = requests.get(rss_url, timeout=12)
            soup = BeautifulSoup(r.content, "xml")
            items = soup.find_all("item")
            
            for item in items[:6]:  # 每家競品精選前 6 筆
              title = item.title.text
url = item.link.text
pub_date = item.pubDate.text

description = ""
if item.description:
    description = item.description.text
                
                # 時間轉換
                try:
                    date_iso = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %Z").isoformat()
                except:
                    date_iso = datetime.utcnow().isoformat()

                summary = f"追蹤自指定核心競品
                types = analyze_tags(title, description)
                
                # 初始權重分數
                base_score = 60

# 指定品牌加權
base_score += 10

# 功能更新優先
if "功能更新" in types:
    base_score += 15

# 用戶體驗優先
if "用戶體驗" in types:
    base_score += 15

# Dashboard 相關優先
if any(k in full_text.lower() for k in [
    "dashboard",
    "儀表板",
    "看板",
    "analytics"
]):
    base_score += 20
                
                # 繁體中文優先加權 (加 40 分，使其在排序時能頂到最前)
                if is_traditional_chinese(title):
                    base_score += 40
                
                articles.append({
                    "id": f"rss_{hash(url)}",
                    "channel": "rss",
                    "source": f"{brand} 官方/相關動態",
                    "title": title,
                    "summary": summary,
                    "url": url,
                    "date": date_iso,
                    "fetched": datetime.utcnow().isoformat(),
                    "systems": [info["system"]],
                    "types": types,
                    "score": base_score
                })
        except Exception as e:
            print(f"❌ 抓取 {brand} 動態失敗: {e}")

   # ── 5. 動態自動抓取 Threads 精確文章連結 ────────────────────────────
    print("🧵 正在透過 RSSHub 橋接器自動抓取 Threads 精確文章...")
    
    # 您可以收集一些經常發布 UIUX、SaaS 產品體驗或 EIP/CRM 觀點的 Threads 帳號
    # 格式：https://rsshub.app/threads/user/帳號名稱
    THREADS_USERS = ["ux_design_share", "saas_taiwan"] 
    
    for user in THREADS_USERS:
        threads_rss_url = f"https://rsshub.app/threads/user/{user}"
        try:
            res = requests.get(threads_rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                soup = BeautifulSoup(res.content, "xml")
                items = soup.find_all("item")
                
                for item in items[:3]: # 每個帳號取最新 3 篇
                    title = item.title.text if item.title else "Threads 體驗分享"
                    # 💡 重點：RSSHub 解析出來的 link 就是該篇文章的精確網址！
                    url = item.link.text 
                    description = BeautifulSoup(item.description.text, "html.parser").get_text() if item.description else ""
                    
                    # 判斷這篇社群貼文是關於 EIP 還是 CRM
                    system_tags = []
                    if any(k in description.lower() for k in ["hubspot", "crm", "stripe", "客戶"]):
                        system_tags.append("CRM")
                    if any(k in description.lower() for k in ["workday", "sap", "hibob", "apollo", "hr", "人資", "eip"]):
                        system_tags.append("EIP")
                    
                    if not system_tags:
                        continue # 如果跟您的核心系統完全無關，就過濾掉
                        
                    types = analyze_tags(title, description)
                    
                    articles.append({
                        "id": f"threads_{hash(url)}",
                        "channel": "threads",
                        "source": f"Threads @{user}",
                        "title": title[:50] + "..." if len(title) > 50 else title,
                        "summary": description[:120] + "..." if len(description) > 120 else description,
                        "url": url, # 這邊就會是精確的 https://www.threads.net/@user/post/...
                        "date": datetime.utcnow().isoformat(),
                        "fetched": datetime.utcnow().isoformat(),
                        "systems": system_tags,
                        "types": types,
                        "score": 85 if is_traditional_chinese(title + description) else 55
                    })
        except Exception as e:
            print(f"⚠ 透過 RSSHub 抓取 Threads 用戶 @{user} 失敗 (社群平台限制較嚴格): {e}")

    # ── 6. 讀取歷史資料並進行智慧去重與合併 ──────────────────────────
    data_dir = "data"
    data_path = os.path.join(data_dir, "articles.json")
    os.makedirs(data_dir, exist_ok=True)
    
    existing_articles = []
    if os.path.exists(data_path):
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                existing_articles = old_data if isinstance(old_data, list) else old_data.get("articles", [])
        except Exception as e:
            print(f"⚠ 讀取原有 JSON 失敗，將重新建立: {e}")

    # 以 URL 作為唯一 Key 去重
    known_urls = {a["url"] for a in existing_articles}
    new_count = 0
    
    for a in articles:
        if a["url"] not in known_urls:
            existing_articles.append(a)
            new_count += 1

    # 排序：最新日期在最前面
    existing_articles.sort(key=lambda x: x.get("date", ""), reverse=True)
    # 限制快取總量，避免 JSON 過於臃腫
    existing_articles = existing_articles[:200]

    # ── 7. 計算統計數據並更新 JSON ─────────────────────────────────
    stats = {
        "total": len(existing_articles),
        "new_today": new_count,
        "last_updated": datetime.utcnow().isoformat(),
        "by_system": {"EIP": 0, "CRM": 0},
        "by_type": {"用戶體驗": 0, "功能更新": 0, "產業趨勢": 0},
        "by_channel": {"rss": 0, "threads": 0, "reddit": 0}
    }

    for a in existing_articles:
        for s in a.get("systems", []):
            if s in stats["by_system"]: stats["by_system"][s] += 1
        for t in a.get("types", []):
            if t in stats["by_type"]: stats["by_type"][t] += 1
        ch = a.get("channel", "rss")
        if ch in stats["by_channel"]: stats["by_channel"][ch] += 1

    final_output = {
        "stats": stats,
        "articles": existing_articles
    }

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
        
    print(f"✨ [任務完成] 新增 {new_count} 筆，累積快取 {len(existing_articles)} 筆。資料已儲存至 {data_path}。")

if __name__ == "__main__":
    collect_all_intelligence()
