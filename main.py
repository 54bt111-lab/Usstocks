import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import time

# جلب بيانات الاعتماد من GitHub Secrets أو بيئة العمل
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ذاكرة لتتبع التنبيهات المكررة والزخم أثناء تشغيل السكنر
ALERT_HISTORY = {} # {ticker: {'count': int, 'last_price': float}}

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
    """تحديد الجلسة الحالية بناءً على توقيت نيويورك EST/EDT"""
    try:
        if last_timestamp.tzinfo is None:
            ny_time = last_timestamp.tz_localize('UTC').tz_convert('America/New_York').time()
        else:
            ny_time = last_timestamp.tz_convert('America/New_York').time()

        if time(4, 0) <= ny_time < time(9, 30):
            return "ما قبل السوق (Premarket) 🌅"
        elif time(9, 30) <= ny_time < time(16, 0):
            return "السوق الرسمي (Regular Market) 🔔"
        elif time(16, 0) <= ny_time <= time(20, 0):
            return "ما بعد السوق (Postmarket) 🌙"
        else:
            return "خارج أوقات التداول الرسمية 💤"
    except Exception:
        return "تداول ممتد"

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
    print("🚀 بدء المسح المتقدم عبر جميع الجلسات (Premarket + Market + Postmarket)...")

    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. بيانات فريم 4 ساعات (شاملة الفترات الممتدة prepost=True)
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

            # حساب عمر Power Trend لـ 4 ساعات (شرط من 1 إلى 6)
            pt_age_4h = calculate_power_trend_age(df_4h)
            if not (1 <= pt_age_4h <= 6):
                continue

            # 2. بيانات فريم 15 دقيقة (شاملة الفترات الممتدة prepost=True)
            df_15m = stock.history(period="5d", interval="15m", prepost=True)
            if df_15m.empty or len(df_15m) < 20:
                continue

            # تحديد الجلسة الحالية بناءً على الشمعة الأخيرة
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
                choch_line = "\n• تغير السلوك (CHOCH): `اختراق هيكلي صاعد ⚡`" if has_choch else ""

                # جلب معلومات السهم (القطاع وقمة 52 أسبوع)
                info = stock.info or {}
                sector = info.get('sector', 'غير محدد')
                high_52w = info.get('fiftyTwoWeekHigh', df_4h_raw['High'].max())
                high_52w = round(high_52w, 2) if high_52w else "غير متاح"
                
                if isinstance(high_52w, (int, float)) and high_52w > 0:
                    dist_pct = round(((latest_price - high_52w) / high_52w) * 100, 1)
                    week52_str = f"${high_52w} ({dist_pct}% من القمة)"
                else:
                    week52_str = f"${high_52w}"

                # حساب الأهداف ووقف الخسارة
                stop_loss = round(df_15m['Low'].iloc[-5:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)

                # إدارة التنبيه المكرر والزخم / التسارع
                if ticker in ALERT_HISTORY:
                    prev_data = ALERT_HISTORY[ticker]
                    prev_data['count'] += 1
                    price_change = ((latest_price - prev_data['last_price']) / prev_data['last_price']) * 100
                    prev_data['last_price'] = latest_price
                    
                    alert_num = prev_data['count']
                    if price_change >= 2.0:
                        header_tag = f"⚡ **تنبيه ({alert_num}) - تسارع 🔥 +{price_change:.1f}%**"
                    elif price_change >= 1.0:
                        header_tag = f"🚀 **تنبيه ({alert_num}) - زخم ⚡ +{price_change:.1f}%**"
                    else:
                        header_tag = f"🔔 **تنبيه مكرر ({alert_num})**"
                else:
                    ALERT_HISTORY[ticker] = {'count': 1, 'last_price': latest_price}
                    header_tag = "⚡ **تنبيه سكنر [L3-MBO + Power Trend Filter]**"

                tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"

                msg = f"""{header_tag}

📌 **السهم:** `{ticker}`
🕒 **الجلسة:** `{current_session}`
🏢 **القطاع:** `{sector}`
📈 **الشارت:** [TradingView]({tv_url})
💵 **السعر اللحظي:** `${latest_price}`

📊 **مصفوفة المؤشرات والسلوك:**
• مؤشر RSI (فاصل 4 ساعات): `{rsi_4h}` 🟢
• عمر Power Trend (فاصل 4 ساعات): `{pt_age_4h}` شمعة/شمعات ⚡
• عمر Power Trend (فاصل 15 دقيقة): `{pt_age_15m}` شمعة/شمعات ⚡{choch_line}
• قمة 52 أسبوع: `{week52_str}`

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
