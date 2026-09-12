import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# جلب بيانات الاعتماد من GitHub Secrets
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# قائمة الأسهم المحددة حصراً للفحص
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
    """حساب مؤشر القوة النسبية RSI"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Secrets غير معرفة!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": text, 
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def review_market_close():
    print("🔎 جاري مراجعة قائمة الأسهم المحددة (FVG + RSI > 54)...")
    
    send_telegram("📊 **[مراجعة القائمة المحددة]**: جاري فحص 107 أسهم وفق شروط (FVG + RSI > 54)...")

    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="5d", interval="15m", prepost=True)
            
            if df.empty or len(df) < 20:
                continue

            # حساب مؤشر RSI
            df['RSI'] = calculate_rsi(df['Close'], period=14)
            current_rsi = round(df['RSI'].iloc[-1], 2)

            latest_price = round(df['Close'].iloc[-1], 2)
            prev_high = df['High'].iloc[-3]
            current_low = df['Low'].iloc[-1]
            
            # 1. شرط الفجوة السعرية FVG
            has_fvg = current_low >= (prev_high * 0.997)
            
            # 2. شرط RSI فوق 54
            is_rsi_valid = current_rsi > 54

            # حساب CVD
            vol_delta = np.where(df['Close'] >= df['Open'], df['Volume'], -df['Volume'])
            cvd_val = vol_delta.cumsum()[-1]
            cvd_status = "نعم (CVD > 0)" if cvd_val > 0 else "لا (CVD < 0)"

            if has_fvg and is_rsi_valid:
                found_opportunities += 1
                stop_loss = round(df['Low'].iloc[-5:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)
                
                # رابط الشارت المباشر على TradingView
                tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
                
                msg = f"""
🔎 **تنبيه سكنر [L3-MBO + RSI Filter]**

📌 **السهم:** `{ticker}`
📈 **رابط الشارت:** [فتح الشارت على TradingView]({tv_url})
💵 **السعر اللحظي / الممتد:** `${latest_price}`

📊 **مصفوفة المؤشرات والسلوك:**
• FVG / CHOCH: `إشارة تجميع / FVG نشط`
• مؤشر RSI (14): `{current_rsi}` 🟢 *(RSI > 54)*
• خط CVD فوق الصفر: `{cvd_status}`

🎯 **الأهداف:**
• هدف أول: `${target1}`
• 🟢 قد يصل إلى: `${target_max}`

⛔ **وقف الخسارة:**
• وقف خسارة أولي: `${stop_loss}`
"""
                send_telegram(msg)
                print(f"✅ تم إرسال تنبيه للسهم {ticker} (RSI: {current_rsi})")
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

    if found_opportunities == 0:
        send_telegram("ℹ️ **نتيجة المراجعة**: لا توجد أسهم تطابق الشروط حالياً في القائمة المحددة.")

if __name__ == "__main__":
    review_market_close()
