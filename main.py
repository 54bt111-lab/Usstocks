import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# جلب بيانات الاعتماد من GitHub Secrets
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# قائمة الأسهم الـ 107 المحددة
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

def scan_us_market():
    print("🚀 بدء المسح المتقدم (RSI 4H > 54 + FVG L3-MBO)...")

    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            
            # 1. جلب بيانات فريم 4 ساعات لشرط RSI
            df_4h = stock.history(period="1mo", interval="1h", prepost=True)
            if df_4h.empty or len(df_4h) < 20:
                continue
            
            # إعادة تجميع البيانات إلى فريم 4 ساعات (4h Resampling)
            df_4h_resampled = df_4h.resample('4h').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()

            df_4h_resampled['RSI'] = calculate_rsi(df_4h_resampled['Close'], period=14)
            rsi_4h = round(df_4h_resampled['RSI'].iloc[-1], 2)

            # التثبت من شرط RSI 4H > 54
            if pd.isna(rsi_4h) or rsi_4h <= 54:
                continue

            # 2. جلب بيانات فريم 15 دقيقة للتنفيذ والـ FVG
            df_15m = stock.history(period="5d", interval="15m", prepost=True)
            if df_15m.empty or len(df_15m) < 5:
                continue

            latest_price = round(df_15m['Close'].iloc[-1], 2)
            prev_high = df_15m['High'].iloc[-3]
            current_low = df_15m['Low'].iloc[-1]
            
            # شرط FVG
            has_fvg = current_low >= (prev_high * 0.997)

            # حساب CVD
            vol_delta = np.where(df_15m['Close'] >= df_15m['Open'], df_15m['Volume'], -df_15m['Volume'])
            cvd_val = vol_delta.cumsum()[-1]
            cvd_status = "نعم (CVD > 0)" if cvd_val > 0 else "لا (CVD < 0)"

            if has_fvg:
                found_opportunities += 1
                stop_loss = round(df_15m['Low'].iloc[-5:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)
                
                tv_url = f"https://www.tradingview.com/chart/?symbol={ticker}"
                
                msg = f"""
⚡ **تنبيه سكنر [L3-MBO + 4H RSI Filter]**

📌 **السهم:** `{ticker}`
📈 **رابط الشارت:** [فتح الشارت على TradingView]({tv_url})
💵 **السعر اللحظي / الممتد:** `${latest_price}`

📊 **مصفوفة المؤشرات والسلوك:**
• FVG / CHOCH: `إشارة تجميع / FVG نشط`
• مؤشر RSI (فاصل 4 ساعات): `{rsi_4h}` 🟢 *(تجاوز 54)*
• خط CVD فوق الصفر: `{cvd_status}`

🎯 **الأهداف:**
• هدف أول: `${target1}`
• 🟢 قد يصل إلى: `${target_max}`

⛔ **وقف الخسارة:**
• وقف خسارة أولي: `${stop_loss}`
"""
                send_telegram(msg)
                print(f"✅ تم إرسال تنبيه للسهم {ticker} (RSI 4H: {rsi_4h})")
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

    if found_opportunities == 0:
        print("ℹ️ لا توجد أسهم تطابق شرط RSI 4H > 54 مع FVG حالياً.")

if __name__ == "__main__":
    scan_us_market()
