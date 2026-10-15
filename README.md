# RestoSuite Report

สคริปต์ Python สำหรับดาวน์โหลดรายงาน **Orders** (`/report/report-sales-orders`) จาก [RestoSuite back office](https://bo.sea.restosuite.ai) เป็นไฟล์ CSV หรือ Excel

- ดึง**ครบทุกออเดอร์**ในช่วงวันที่ โดยเรียก JSON API ตัวเดียวกับที่หน้าเว็บใช้ ครั้งละ 500 ออเดอร์จนครบ
- column เหมือนที่หน้า Orders แสดงเป็นค่าเริ่มต้น และหัวตารางใช้ชื่อเดียวกับหน้าเว็บ
- ช่องจำนวนเงินเก็บเป็นตัวเลข จึงเอาไปรวมใน Excel ได้ทันที ส่วน CSV บันทึกเป็น UTF-8 BOM เพื่อให้เปิดภาษาไทยใน Excel ได้ถูกต้อง
- ถ้าเชื่อมต่อผิดพลาดชั่วคราว สคริปต์จะลองใหม่เอง และถ้า token หมดอายุจะแจ้งให้รู้

## ติดตั้ง

ต้องใช้ Python 3.9 ขึ้นไป

```bash
pip install -r requirements.txt
cp .env.example .env
```

แล้วกรอกค่าใน `.env`:

| ตัวแปร | หาได้จาก |
|---|---|
| `RESTOSUITE_TOKEN` | ล็อกอิน back office เปิด DevTools > Console แล้วรัน `localStorage.getItem("vulcan-Token")` |
| `RESTOSUITE_SHOP_IDS` | Store ID คั่นด้วยจุลภาค |
| `RESTOSUITE_BRAND_ID`, `RESTOSUITE_CORPORATION_ID`, `RESTOSUITE_ORGANIZATION_ID` | DevTools > Network: เปิดรายงาน Orders กด Query แล้วดู request header ของ `queryData` |

## ใช้งาน

```bash
python restosuite_orders.py                                    # เมื่อวาน, CSV
python restosuite_orders.py --from 2026-10-01 --to 2026-10-14 --format xlsx
python restosuite_orders.py --from 2026-10-01 --to 2026-10-31 --out october.xlsx --format xlsx
```

| ตัวเลือก | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `--from` | เมื่อวาน | วันเริ่ม (YYYY-MM-DD) |
| `--to` | เท่ากับ `--from` | วันสิ้นสุด |
| `--shop` | `RESTOSUITE_SHOP_IDS` | Store ID ใส่ซ้ำได้หลายร้าน |
| `--format` | `csv` | `csv` หรือ `xlsx` |
| `--out` | `restosuite-orders-<from>_<to>.<format>` | ชื่อไฟล์ผลลัพธ์ |
| `--status` | `20` | รหัสสถานะออเดอร์ (ค่าเดียวกับที่หน้า report ใช้เป็นค่าเริ่มต้น) |
| `--currency` | `THB` | สกุลเงิน |

## ข้อควรรู้

- token จะใช้ไม่ได้เมื่อ log out จาก RestoSuite ถ้าสคริปต์บอกว่า token หมดอายุ ให้ล็อกอินใหม่แล้วอัปเดต `RESTOSUITE_TOKEN`
- เก็บ token เหมือนรหัสผ่าน `.env` อยู่ใน `.gitignore` แล้ว อย่า commit
- สคริปต์ใช้ API ภายในของหน้าเว็บ ไม่ใช่ API ที่ RestoSuite เปิดให้ใช้อย่างเป็นทางการ ถ้า RestoSuite เปลี่ยนระบบ สคริปต์อาจต้องแก้ตาม
