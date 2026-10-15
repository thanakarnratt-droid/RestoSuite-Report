# RestoSuite Report

สคริปต์ Python สำหรับดึงข้อมูลจาก [RestoSuite back office](https://bo.sea.restosuite.ai): ดึงทั้ง 7 รายงานลงฐานข้อมูล SQLite (`export_all.py`) หรือดาวน์โหลดรายงาน **Orders** (`/report/report-sales-orders`) เป็นไฟล์ CSV หรือ Excel

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

## ดึงข้อมูลทั้งหมดลงฐานข้อมูล (SQLite)

`export_all.py` ดึงทั้ง 7 รายงานใน **Common Reports** ลงฐานข้อมูล SQLite รายงานละ 1 ตาราง และดึงที่ระดับละเอียดที่สุดที่แต่ละรายงานให้ได้ ถ้าไม่ใส่วันที่ จะดึงตั้งแต่วันแรกที่ร้านมีข้อมูลจนถึงวันนี้

```bash
python export_all.py                                   # ทั้งหมด ลง restosuite.db
python export_all.py --csv-dir export                  # และเขียน CSV ทุกตารางลง export/
python export_all.py --from 2026-10-01 --to 2026-10-14 --db october.db
python export_all.py --only orders --only order_items  # เฉพาะบางตาราง
```

| ตาราง | รายงาน | 1 แถว = |
|---|---|---|
| `orders` | Orders | 1 ออเดอร์ |
| `order_items` | Items Breakdown | 1 รายการสินค้าในออเดอร์ |
| `payments` | Payments Detail | 1 การชำระเงินของออเดอร์ |
| `payments_daily` | Payments Breakdown | วัน × ช่องทางชำระเงิน |
| `discounts` | Discount Detail List | 1 ส่วนลดในออเดอร์ |
| `discounts_daily` | Discount & Prom | วัน × ส่วนลด/โปรโมชั่น |
| `sales_daily` | Sales Summary Report | 1 วัน |

- ตารางที่เป็นระดับออเดอร์เชื่อมกันด้วย `pos_order_id` (และ `order_id`)
- วันที่เก็บแบบ ISO (`2026-10-14`, `2026-10-14 10:15:58`) จำนวนเงินเก็บเป็นตัวเลข ช่องที่ RestoSuite มีทั้งรหัสและชื่อ เช่น `dining_option` จะเก็บชื่อไว้ และเก็บรหัสในคอลัมน์ `*_code`
- `_columns` บอกว่าแต่ละคอลัมน์มาจาก field ไหน และชื่อบนหน้าเว็บคืออะไร
- `_exports` บันทึกช่วงวันที่ จำนวนแถว และผลเทียบยอดรวม
- หลังดึงแต่ละตาราง สคริปต์จะเทียบยอดรวม เช่น Net Sales กับยอดที่ RestoSuite คำนวณเอง ถ้าไม่ตรงจะแจ้งและจบด้วย exit code 1
- ทุกครั้งที่รัน ตารางจะถูกสร้างใหม่ทั้งหมด รันซ้ำได้โดยไม่เกิดข้อมูลซ้ำ
- ดึงเฉพาะออเดอร์ที่สถานะ "เสร็จสิ้น" (status 20) เหมือนค่าเริ่มต้นของหน้า report

## ข้อควรรู้

- token จะใช้ไม่ได้เมื่อ log out จาก RestoSuite ถ้าสคริปต์บอกว่า token หมดอายุ ให้ล็อกอินใหม่แล้วอัปเดต `RESTOSUITE_TOKEN`
- เก็บ token เหมือนรหัสผ่าน `.env` อยู่ใน `.gitignore` แล้ว อย่า commit
- สคริปต์ใช้ API ภายในของหน้าเว็บ ไม่ใช่ API ที่ RestoSuite เปิดให้ใช้อย่างเป็นทางการ ถ้า RestoSuite เปลี่ยนระบบ สคริปต์อาจต้องแก้ตาม
