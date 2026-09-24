import os
import json
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import time

# جلب بيانات الاعتماد من GitHub Secrets أو بيئة العمل
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

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

def load_alert_history():
    """تحميل سجل التنبيهات السابقة من ملف JSON لحفظ الترقيم عبر الجلسات"""
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
    """تحديد الجلسة (Premarket / Regular Market / Postmarket)"""
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

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Secrets غير معرفة!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

def scan_us_market():
    print("🚀 بدء المسح المتقدم عبر جميع الجلسات (Premarket + Regular Market + Postmarket)...")

    alert_history = load_alert_history()
    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. بيانات فريم 4 ساعات (يشمل ما قبل وما بعد السوق)
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

            # التمييز البصري إذا كان الاتجاه متقدماً (أكثر من 6 شمعات)
            if pt_age_4h > 6:
                pt_4h_display = f"`{pt_age_4h} شمعة` ⚠️ (اتجاه متقدم)"
            else:
                pt_4h_display = f"`{pt_age_4h} شمعة` ⚡"

            # 2. بيانات فريم 15 دقيقة
            df_15m = stock.history(period="5d", interval="15m", prepost=True)
            if df_15m.empty or len(df_15m) < 20:
                continue

            # تحديد نوع الجلسة اللحظية
            current_session = get_current_session(df_15m.index[-1])

            # حساب عمر Power Trend لـ 15 دقيقة
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
                choch_line = "\n• CHOCH: `اختراق هيكلي صاعد` ⚡" if has_choch else ""

                # جلب معلومات السهم (القطاع، قمة وقاع 52 أسبوع)
                info = stock.info or {}
                sector = info.get('sector', 'غير محدد')
                
                # حساب قمة 52 أسبوع والنسبة المئوية
                high_52w = info.get('fiftyTwoWeekHigh', df_4h_raw['High'].max())
                if high_52w and isinstance(high_52w, (int, float)) and high_52w > 0:
                    high_pct = round(((latest_price - high_52w) / high_52w) * 100, 1)
                    high_52w_str = f"${round(high_52w, 2)} ({high_pct}%)"
                else:
                    high_52w_str = "غير متاح"
                
                # حساب قاع 52 أسبوع والنسبة المئوية
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

                # إدارة ترقيم التنبيه وتصنيف الحركة عبر جميع الجلسات
                if ticker in alert_history:
                    prev_data = alert_history[ticker]
                    alert_num = prev_data['count'] + 1
                    price_change = ((latest_price - prev_data['last_price']) / prev_data['last_price']) * 100
                    
                    if price_change >= 3.0:
                        alert_line = f"\n🚀 **تنبيه ({alert_num}) - زخم ⚡ +{price_change:.1f}%**"
                    elif price_change >= 2.0:
                        alert_line = f"\n⚡ **تنبيه ({alert_num}) - تسارع 🔥 +{price_change:.1f}%**"
                    elif price_change >= 1.0:
                        alert_line = f"\n📈 **تنبيه ({alert_num}) - ارتفاع 🟢 +{price_change:.1f}%**"
                    else:
                        alert_line = f"\n🔔 **تنبيه ({alert_num}) - مكرر**"
                        
                    alert_history[ticker] = {'count': alert_num, 'last_price': latest_price}
                else:
                    alert_history[ticker] = {'count': 1, 'last_price': latest_price}
                    alert_line = "\n⚡ **تنبيه (1)**"

                # حفظ التحديث مباشرة لملف JSON لتأمين الذاكرة
                save_alert_history(alert_history)

                tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"

                # صياغة الرسالة النهائية
                msg = f"""{current_session}{alert_line}

📌 السهم: **{ticker}**
🏢 القطاع: {sector}
📈 الشارت: [TradingView]({tv_url})
💵 السعر اللحظي: `${latest_price}`

• RSI (4H): `{rsi_4h}` 🟢
• Power Trend 4H: {pt_4h_display}
• Power Trend 15M: `{pt_age_15m} شمعة` ⚡{choch_line}
• قمة 52 أسبوع: `{high_52w_str}`
• قاع 52 أسبوع: `{low_52w_str}`

🎯 **الأهداف:**
• هدف أول: `${target1}`
• 🟢 قد يصل إلى: `${target_max}`

⛔ **وقف الخسارة:**
• وقف خسارة أولي: `${stop_loss}`"""

                send_telegram(msg)
                print(f"✅ تم إرسال تنبيه للسهم {ticker} | الجلسة: {current_session} | سعر: ${latest_price}")
        
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

    if found_opportunities == 0:
        print("ℹ️ لا توجد أسهم تطابق الشروط حالياً.")

if __name__ == "__main__":
    scan_us_market()
