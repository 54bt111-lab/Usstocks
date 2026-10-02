import os
import json
import html
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import time, datetime, timedelta, timezone

# جلب بيانات الاعتماد من GitHub Secrets أو بيئة العمل
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# هوية الطلبات لموقع SEC (مطلوبة منهم) - يفضل وضع بريدك في Secret باسم SEC_USER_AGENT
SEC_HEADERS = {"User-Agent": os.environ.get("SEC_USER_AGENT", "USStockScanner contact@example.com")}

# اسم ملف التخزين الدائم لسجل التنبيهات
HISTORY_FILE = "alerts_history.json"

US_STOCKS = [
    "NB", "RKLB", "LCUT", "QSI", "WWR", "QUBT", "EVLV", "QS", "CSCO", "GRRR", 
    "RZLV", "CMPX", "PANW", "NNE", "S", "AUR", "ARAY", "ASTS", "KOPN", "SATL", 
    "AVGO", "BIRK", "RGTI", "OKTA", "APG", "GEV", "MBOT", "KULR", "TPR", "OSRH", 
    "CORZ", "TEM", "HEI", "IRIX", "ONDS", "BSM", "MLYS", "AGNT", "EBS", "SLI", 
    "USAR", "CRMD", "SMR", "LAMR", "YOU", "WRAP", "AMBA", "ACHR", "NKE", "U", 
    "LEN", "DHI", "NVAX", "ZENA", "MLTX", "SPCX", "MVST", "PL", "CVX", "INDO", 
    "IBRX", "GDRX", "FSLR", "QBTS", "LMT", "HQ", "DVN", "QNC", "COR", "NVO", 
    "CRM", "BBAI", "MSFT", "AA", "MUX", "ANRO", "GMAB", "EONR", "AISP", "TDC", 
    "PLSE", "VRME", "DUOL", "NTSK", "TWST", "ITRG", "CF", "PCLA", "PPSI", "ZETA", 
    "RPD", "DPRO", "BZAI", "APH", "INFQ", "SLDP", "MP", "RMBS", "TE", "ATEC", 
    "INOD", "CMOPF", "YEXT", "LAC", "ALLE", "TYGO", "HIMX", "NVDA", "LAES", "CTMX", "LUNR"
]

# ---------------------------------------------------------------
# إعدادات الإفصاحات (SEC)
# ---------------------------------------------------------------
SEC_FORMS_AR = {
    "8-K": "تقرير حدث",
    "10-Q": "تقرير ربع سنوي",
    "10-K": "تقرير سنوي",
    "SCHEDULE 13G": "ملكية كبار المساهمين",
    "SCHEDULE 13D": "ملكية كبار المساهمين (نشط)",
    "SC 13G": "ملكية كبار المساهمين",
    "SC 13D": "ملكية كبار المساهمين (نشط)",
    "S-1": "تسجيل طرح",
    "S-3": "تسجيل طرح",
    "424B5": "نشرة طرح",
    "6-K": "تقرير أجنبي",
    "20-F": "تقرير سنوي أجنبي",
}

SEC_8K_ITEMS_AR = {
    "1.01": "اتفاقية جوهرية",
    "2.02": "نتائج مالية",
    "2.03": "التزام مالي",
    "3.02": "بيع أسهم غير مسجل",
    "5.02": "تغيير في الإدارة",
    "5.07": "نتائج تصويت",
    "7.01": "إفصاح عادل FD",
    "8.01": "أحداث أخرى",
}

_cik_map = None

def load_alert_history():
    """تحميل سجل التنبيهات السابقة من ملف JSON"""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ خطأ في قراءة ملف الذاكرة: {e}")
            return {}
    return {}

def save_alert_history(history):
    """حفظ سجل التنبيهات المحدث في ملف JSON"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"⚠️ خطأ في حفظ ملف الذاكرة: {e}")

def calculate_rsi(series, period=14):
    """حساب RSI بتنعيم وايلدر (Wilder's Smoothing) لمطابقة المنصات"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_power_trend_age(df, min_candles=20):
    """حساب عمر Power Trend (EMA20 > SMA50 و Close > EMA20 و RSI > 50)"""
    if len(df) < min_candles:
        return 0

    ema20 = df['Close'].ewm(span=20, adjust=False).mean()
    sma50 = df['Close'].rolling(window=50).mean()
    rsi = calculate_rsi(df['Close'], period=14)

    is_power_trend = (df['Close'] > ema20) & (ema20 > sma50) & (rsi > 50)

    age = 0
    for flag in reversed(is_power_trend.values):
        if flag:
            age += 1
        else:
            break
    return age

def check_choch_change(df_15m):
    """التحقق من حصول CHOCH (تغير هيكل السوق إلى صاعد)"""
    if len(df_15m) < 20:
        return False
    recent_structure_high = df_15m['High'].iloc[-15:-2].max()
    latest_close = df_15m['Close'].iloc[-1]
    return latest_close > recent_structure_high

def get_current_session(last_timestamp):
    """تحديد الجلسة اللحظية (Premarket / Regular Market / Postmarket)"""
    try:
        if last_timestamp.tzinfo is None:
            ny_time = last_timestamp.tz_localize('UTC').tz_convert('America/New_York').time()
        else:
            ny_time = last_timestamp.tz_convert('America/New_York').time()

        if time(4, 0) <= ny_time < time(9, 30):
            return "🌅 Premarket"
        elif time(9, 30) <= ny_time < time(16, 0):
            return "🔔 Regular Market"
        elif time(16, 0) <= ny_time <= time(20, 0):
            return "🌙 Postmarket"
        else:
            return "💤 Extended"
    except Exception:
        return "🌐 Extended"

# ---------------------------------------------------------------
# إفصاحات SEC الحقيقية (من EDGAR الرسمي)
# ---------------------------------------------------------------
def get_cik(ticker):
    """جلب رقم CIK للسهم من ملف SEC الرسمي (يُحمّل مرة واحدة)"""
    global _cik_map
    if _cik_map is None:
        _cik_map = {}
        try:
            r = requests.get("https://www.sec.gov/files/company_tickers.json",
                             headers=SEC_HEADERS, timeout=15)
            r.raise_for_status()
            for item in r.json().values():
                _cik_map[item["ticker"].upper()] = str(item["cik_str"]).zfill(10)
        except Exception as e:
            print(f"⚠️ تعذر تحميل خريطة CIK: {e}")
    return _cik_map.get(ticker.upper().replace("-", "."))

def get_sec_filings(ticker, days=90, limit=4):
    """جلب آخر الإفصاحات المهمة من SEC EDGAR مع رابط كل إفصاح"""
    cik = get_cik(ticker)
    if not cik:
        return []
    try:
        r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                         headers=SEC_HEADERS, timeout=15)
        r.raise_for_status()
        recent = r.json()["filings"]["recent"]
    except Exception as e:
        print(f"⚠️ تعذر جلب إفصاحات {ticker}: {e}")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    cik_int = str(int(cik))
    filings = []
    for i in range(len(recent["form"])):
        form = recent["form"][i]
        date = recent["filingDate"][i]
        if date < cutoff:
            break
        if form not in SEC_FORMS_AR:
            continue
        acc = recent["accessionNumber"][i].replace("-", "")
        doc = recent["primaryDocument"][i]
        items_raw = recent["items"][i] if "items" in recent else ""
        filings.append({
            "form": form,
            "date": date,
            "items": [x.strip() for x in items_raw.split(",") if x.strip()],
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}",
        })
        if len(filings) >= limit:
            break
    return filings

def format_filing_line(f):
    """سطر إفصاح واحد مختصر مع الرابط"""
    label = SEC_FORMS_AR.get(f["form"], f["form"])
    if f["form"] == "8-K":
        names = [SEC_8K_ITEMS_AR[i] for i in f["items"] if i in SEC_8K_ITEMS_AR]
        if names:
            label = " / ".join(names[:2])
    return f'• <a href="{f["url"]}">{html.escape(f["form"])}</a> <code>{f["date"]}</code> {html.escape(label)}'

# ---------------------------------------------------------------
# الأخبار والمحفزات الحقيقية
# ---------------------------------------------------------------
def get_recent_news(stock, days=7, limit=2):
    """آخر الأخبار الفعلية للسهم من Yahoo Finance مع الرابط (آخر 7 أيام)"""
    out = []
    try:
        items = stock.news or []
    except Exception:
        return out
    now = datetime.now(timezone.utc)
    for it in items:
        try:
            c = it.get("content") or it
            title = c.get("title")
            url = ((c.get("canonicalUrl") or {}).get("url")
                   or (c.get("clickThroughUrl") or {}).get("url")
                   or it.get("link"))
            pub = c.get("pubDate") or it.get("providerPublishTime")
            if isinstance(pub, (int, float)):
                pub_dt = datetime.fromtimestamp(pub, tz=timezone.utc)
            else:
                pub_dt = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            if not title or not url or (now - pub_dt).days > days:
                continue
            source = (c.get("provider") or {}).get("displayName") or it.get("publisher") or ""
            out.append({"title": title, "url": url, "date": pub_dt.strftime("%Y-%m-%d"), "source": source})
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out

def get_catalyst_lines(stock, filings):
    """محفزات مؤكدة فقط: نتائج مالية معلنة في SEC أو موعد نتائج قادم مسجل"""
    lines = []
    today = datetime.now(timezone.utc).date()

    # نتائج مالية أُعلنت مؤخراً (8-K بند 2.02)
    for f in filings:
        if f["form"] == "8-K" and "2.02" in f["items"]:
            age = (today - datetime.strptime(f["date"], "%Y-%m-%d").date()).days
            if age <= 10:
                lines.append(f'⚡ إعلان نتائج مالية/أرباح — <a href="{f["url"]}">8-K</a> <code>{f["date"]}</code>')
                break

    # موعد نتائج قادم (خلال 14 يوماً)
    try:
        cal = stock.calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        for d in (dates or []):
            d = d.date() if hasattr(d, "date") else d
            if 0 <= (d - today).days <= 14:
                lines.append(f"📅 موعد النتائج القادم: <code>{d}</code>")
                break
    except Exception:
        pass
    return lines

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Secrets غير معرفة!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

def scan_us_market():
    print("🚀 بدء المسح المتقدم عبر جميع الجلسات...")

    alert_history = load_alert_history()
    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. بيانات فريم 4 ساعات (شاملة جميع الجلسات)
            df_4h_raw = stock.history(period="3mo", interval="1h", prepost=True)
            if df_4h_raw.empty or len(df_4h_raw) < 50:
                continue
            
            df_4h = df_4h_raw.resample('4h').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            df_4h['RSI'] = calculate_rsi(df_4h['Close'], period=14)
            rsi_4h = round(df_4h['RSI'].iloc[-1], 2)

            # شرط RSI 4H > 54
            if pd.isna(rsi_4h) or rsi_4h <= 54:
                continue

            # حساب عمر Power Trend لـ 4 ساعات
            pt_age_4h = calculate_power_trend_age(df_4h)
            if pt_age_4h < 1:
                continue

            if pt_age_4h > 6:
                pt_4h_display = f"{pt_age_4h} شمعة ⚠️ متقدم"
            else:
                pt_4h_display = f"{pt_age_4h} شمعة ⚡"

            # 2. بيانات فريم 15 دقيقة
            df_15m = stock.history(period="5d", interval="15m", prepost=True)
            if df_15m.empty or len(df_15m) < 20:
                continue

            current_session = get_current_session(df_15m.index[-1])
            pt_age_15m = calculate_power_trend_age(df_15m)

            latest_price = round(df_15m['Close'].iloc[-1], 2)
            prev_high = df_15m['High'].iloc[-3]
            current_low = df_15m['Low'].iloc[-1]
            
            # شرط FVG
            has_fvg = current_low >= (prev_high * 0.997)

            if has_fvg:
                found_opportunities += 1
                
                # فحص تغير سلوك CHOCH
                has_choch = check_choch_change(df_15m)
                choch_line = "\n⚡ CHOCH: اختراق هيكلي صاعد" if has_choch else ""

                # جلب معلومات السهم
                info = stock.info or {}
                sector = info.get('sector', 'غير محدد')
                
                # قمة 52 أسبوع
                high_52w = info.get('fiftyTwoWeekHigh', df_4h_raw['High'].max())
                if high_52w and isinstance(high_52w, (int, float)) and high_52w > 0:
                    high_pct = round(((latest_price - high_52w) / high_52w) * 100, 1)
                    high_52w_str = f"${round(high_52w, 2)} ({high_pct}%)"
                else:
                    high_52w_str = "غير متاح"
                
                # قاع 52 أسبوع
                low_52w = info.get('fiftyTwoWeekLow', df_4h_raw['Low'].min())
                if low_52w and isinstance(low_52w, (int, float)) and low_52w > 0:
                    low_pct = round(((latest_price - low_52w) / low_52w) * 100, 1)
                    low_sign = "+" if low_pct > 0 else ""
                    low_52w_str = f"${round(low_52w, 2)} ({low_sign}{low_pct}%)"
                else:
                    low_52w_str = "غير متاح"

                # حساب الأهداف ووقف الخسارة
                stop_loss = round(df_15m['Low'].iloc[-5:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)

                # حساب الترقيم وتصنيف الحركة اللحظية
                if ticker in alert_history:
                    prev_data = alert_history[ticker]
                    alert_num = prev_data['count'] + 1
                    prev_price = prev_data['last_price']
                    price_change = ((latest_price - prev_price) / prev_price) * 100
                    
                    if price_change >= 3.0:
                        alert_line = f"🚀 <b>تنبيه ({alert_num}) - زخم ⚡ +{price_change:.1f}%</b>"
                    elif price_change >= 2.0:
                        alert_line = f"⚡ <b>تنبيه ({alert_num}) - تسارع 🔥 +{price_change:.1f}%</b>"
                    elif price_change >= 1.0:
                        alert_line = f"📈 <b>تنبيه ({alert_num}) - ارتفاع 🟢 +{price_change:.1f}%</b>"
                    else:
                        alert_line = f"🔔 <b>تنبيه ({alert_num}) - مكرر</b>"
                        
                    alert_history[ticker] = {'count': alert_num, 'last_price': latest_price}
                else:
                    alert_history[ticker] = {'count': 1, 'last_price': latest_price}
                    alert_line = "⚡ <b>تنبيه (1)</b>"

                # حفظ السجل فوراً
                save_alert_history(alert_history)

                tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"

                # --- الأخبار والمحفزات وإفصاحات SEC (بيانات حقيقية فقط) ---
                filings = get_sec_filings(ticker)
                catalyst_lines = get_catalyst_lines(stock, filings)
                news_items = get_recent_news(stock)

                extra_parts = []
                if catalyst_lines or news_items:
                    block = ["<b>📰 المحفزات والأخبار</b>"]
                    block.extend(catalyst_lines)
                    for n in news_items:
                        src = f" · {html.escape(n['source'])}" if n['source'] else ""
                        block.append(f'• <a href="{n["url"]}">{html.escape(n["title"][:90])}</a> <code>{n["date"]}</code>{src}')
                    extra_parts.append("\n".join(block))
                if filings:
                    block = ["<b>📄 إفصاحات SEC</b>"]
                    block.extend(format_filing_line(f) for f in filings)
                    sec_browse = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={ticker}&type=&dateb=&owner=include&count=40"
                    block.append(f'🔗 <a href="{sec_browse}">كل الإفصاحات</a> | <a href="{tv_url}">TradingView</a>')
                    extra_parts.append("\n".join(block))
                extra_text = ("\n\n" + "\n\n".join(extra_parts)) if extra_parts else ""

                # صياغة الرسالة النهائية (مرتبة ومختصرة)
                msg = f"""{current_session} | {alert_line}

<b>{html.escape(ticker)}</b> · {html.escape(str(sector))}
💵 <code>${latest_price}</code> · <a href="{tv_url}">📈 TradingView</a>

📊 <b>المؤشرات</b>
<code>RSI 4H : {rsi_4h} 🟢
PT 4H  : {pt_4h_display}
PT 15M : {pt_age_15m} شمعة ⚡
52W هـ : {high_52w_str}
52W ق  : {low_52w_str}</code>{choch_line}

🎯 <b>الأهداف</b>  <code>${target1}</code> ← <code>${target_max}</code>
⛔ <b>وقف الخسارة</b>  <code>${stop_loss}</code>{extra_text}"""

                send_telegram(msg)
                print(f"✅ تم إرسال تنبيه للسهم {ticker} | الجلسة: {current_session} | سعر: ${latest_price}")
        
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

    if found_opportunities == 0:
        print("ℹ️ لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    scan_us_market()
