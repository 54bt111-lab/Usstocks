import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

# جلب بيانات الاعتماد من GitHub Secrets
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# قائمة أهم أسهم السوق الأمريكي للمراقبة
US_STOCKS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "AMZN", "META", "GOOGL"]

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Secrets غير معرفة!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def scan_us_market():
    print("🚀 بدء مسح السوق الأمريكي...")
    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(period="5d", interval="15m")
            
            if df.empty or len(df) < 5:
                continue

            latest_price = round(df['Close'].iloc[-1], 2)
            prev_high = df['High'].iloc[-3]
            current_low = df['Low'].iloc[-1]
            
            # رصد FVG (Fair Value Gap)
            has_fvg = current_low > prev_high
            
            # حساب CVD تقريبي
            vol_delta = np.where(df['Close'] >= df['Open'], df['Volume'], -df['Volume'])
            cvd_val = vol_delta.cumsum()[-1]
            cvd_status = "نعم (CVD > 0)" if cvd_val > 0 else "لا (CVD < 0)"

            if has_fvg:
                stop_loss = round(df['Low'].iloc[-3:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)
                
                msg = f"""
⚡ **تنبيه سكنر السوق الأمريكي [L3-MBO]** ⚡

📌 **السهم:** `{ticker}`
💵 **السعر اللحظي:** `${latest_price}`

📊 **مصفوفة سلوك السعر:**
• FVG / CHOCH: `Bullish FVG (مكتشف)`
• خط CVD فوق الصفر: `{cvd_status}`

🎯 **الأهداف:**
• هدف أول: `${target1}`
• 🟢 قد يصل إلى: `${target_max}`

⛔ **وقف الخسارة:**
• وقف خسارة أولي: `${stop_loss}`
"""
                send_telegram(msg)
                print(f"✅ تم إرسال تنبيه للسهم {ticker}")
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

if __name__ == "__main__":
    scan_us_market()
