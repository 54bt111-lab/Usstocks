import os
import requests
import pandas as pd
import numpy as np
import yfinance as yf

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# قائمة توسيعية لمراجعة عينة أكبر من أسهم السوق الأمريكي
US_STOCKS = ["NVDA", "AAPL", "TSLA", "AMD", "MSFT", "AMZN", "META", "GOOGL", "NFLX", "PLTR", "INDA", "SMCI"]

def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Secrets غير معرفة!")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}
    requests.post(url, json=payload)

def review_market_close():
    print("🔎 جاري مراجعة إغلاق السوق والأجواء اللحظية...")
    
    # تنبيه إشارة البدء
    send_telegram("📊 **[مراجعة بعد الإغلاق]**: جاري فحص الفرص والسيولة المتبقية في السوق الأمريكي...")

    found_opportunities = 0

    for ticker in US_STOCKS:
        try:
            stock = yf.Ticker(ticker)
            # جلب حركة آخر يومين على فريم 15 دقيقة مع الساعات الممتدة
            df = stock.history(period="2d", interval="15m", prepost=True)
            
            if df.empty or len(df) < 5:
                continue

            latest_price = round(df['Close'].iloc[-1], 2)
            prev_high = df['High'].iloc[-3]
            current_low = df['Low'].iloc[-1]
            
            # شرط مريح للمراجعة: رصد اقتراب السعر أو تكوين FVG
            has_fvg = current_low >= (prev_high * 0.997)
            
            # حساب CVD تقريبي
            vol_delta = np.where(df['Close'] >= df['Open'], df['Volume'], -df['Volume'])
            cvd_val = vol_delta.cumsum()[-1]
            cvd_status = "نعم (CVD > 0)" if cvd_val > 0 else "لا (CVD < 0)"

            if has_fvg:
                found_opportunities += 1
                stop_loss = round(df['Low'].iloc[-5:].min(), 2)
                target1 = round(latest_price * 1.02, 2)
                target_max = round(latest_price * 1.05, 2)
                
                msg = f"""
🔎 **مراجعة إغلاق السوق [L3-MBO Audit]**

📌 **السهم:** `{ticker}`
💵 **سعر الإغلاق / الممتد:** `${latest_price}`

📊 **حالة سلوك السعر:**
• FVG / CHOCH: `إشارة تجميع / FVG نشط`
• خط CVD فوق الصفر: `{cvd_status}`

🎯 **مستويات الأهداف المقترحة:**
• هدف أول: `${target1}`
• 🟢 قد يصل إلى: `${target_max}`

⛔ **وقف الخسارة:**
• وقف خسارة أولي: `${stop_loss}`
"""
                send_telegram(msg)
                print(f"✅ تم إرسال مراجعة لسهم {ticker}")
        except Exception as e:
            print(f"❌ خطأ في فحص {ticker}: {e}")

    if found_opportunities == 0:
        send_telegram("ℹ️ **نتيجة المراجعة**: لا توجد نماذج FVG واضحة متكونة عند الإغلاق حالياً.")

if __name__ == "__main__":
    review_market_close()
