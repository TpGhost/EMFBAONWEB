# EMFBA Football Analytics — Web V1

เว็บไซต์เดียว: Dashboard, Team Search, Prediction Audit (placeholder). ไม่เชื่อม Telegram หรือ Apps Script ที่ใช้งานจริง.

## ติดตั้งและทดลอง
1. สร้าง repository **Private** บน GitHub และอัปโหลด `app.py`, `requirements.txt`, `.gitignore` และไฟล์ตัวอย่าง `.streamlit/secrets.toml.example` (ไม่ต้องอัปโหลดคีย์จริง)
2. เปิด https://share.streamlit.io/ แล้วเชื่อม GitHub เลือก repo และ main file `app.py` (ตรวจเงื่อนไขโฮสต์ฟรีล่าสุดก่อนใช้งาน)
3. ที่ App settings > Secrets เพิ่ม:

```toml
API_FOOTBALL_KEY = "YOUR_KEY"
FOOTBALL_DATA_KEY = "YOUR_KEY"
```

4. Save / Reboot app และเปิด URL ที่ Streamlit ให้มา

สำหรับทดลองในเครื่อง: `pip install -r requirements.txt` แล้ว `streamlit run app.py`. เก็บคีย์ใน `.streamlit/secrets.toml` บนเครื่องเท่านั้น (ไฟล์นี้ถูก .gitignore)

## ข้อจำกัดที่ต้องรู้
- API-Football ฟรีมีโควตาจำกัดและรายการแข่งขัน/สถิติที่เปิดให้ดูอาจไม่ครอบคลุมทั้งหมด
- Dashboard V1 ประเมิน **สูงสุด 10 คู่แรกตามเวลา** หลังคลิก ไม่ใช่การสแกนทุกคู่ทั่วโลกแล้วเลือก 10 ที่ดีที่สุด (เพื่อป้องกันการใช้โควตาฟรีเกิน)
- โมเดล V1 เป็น Poisson แบบ shrinkage จากประตูย้อนหลัง ยังไม่ผ่าน calibration หรือ ROI backtest. Ranking = model probability **ไม่ใช่** EV/value
- ตลาด Asian Handicap และ Over/Under ยังไม่มี odds feed ฟรีถาวรที่ตรวจสอบได้ จึงไม่มี EV/ราคาจริง
- football-data.org ใช้เป็นแหล่งโปรแกรมสำรอง; โมเดลต้องใช้ API-Football Team IDs เพื่ออ่านประวัติทีม
- Team Search แสดงแมตช์ใน **วันที่เลือก** เท่านั้น ไม่ใช่โปรแกรมทั้งหมดในฤดูกาล
- Prediction Audit ยังไม่ใช้งานจริง ต้องมีที่เก็บข้อมูลถาวรที่เหมาะสมก่อน
- Streamlit Community Cloud เป็นโฮสต์ฟรีที่อาจ sleep/restart และไม่รับประกัน uptime 24/7
- หาก API Keys เคยแชร์ในแชต ควร rotate keys ก่อน deploy และห้ามใส่คีย์ลง GitHub
