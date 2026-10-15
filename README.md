# RestoSuite Report

ดึงข้อมูลยอดขายจาก [RestoSuite back office](https://bo.sea.restosuite.ai) ทั้ง 7 รายงานใน **Common Reports** ลงฐานข้อมูล SQLite ให้อัปเดตเองทุกวันบน VPS และแสดงผลเป็น dashboard บนเว็บที่ต้องล็อกอินก่อนเข้า

```
RestoSuite back office ──(JSON API, ทุกวัน 04:00)──> export_all.py ──> restosuite.db + export/*.csv
                                                                              │
                                    https://report.spicycatgroups.com <── dashboard (Flask, Docker) <── nginx + Let's Encrypt
```

## สารบัญ

1. [ภาพรวมของระบบ](#1-ภาพรวมของระบบ)
2. [สิ่งที่ต้องมี](#2-สิ่งที่ต้องมี)
3. [หา token และ ID จาก RestoSuite](#3-หา-token-และ-id-จาก-restosuite)
4. [ติดตั้งบนเครื่องตัวเอง](#4-ติดตั้งบนเครื่องตัวเอง)
5. [ติดตั้งบน VPS](#5-ติดตั้งบน-vps)
6. [ตั้งให้อัปเดตทุกวัน](#6-ตั้งให้อัปเดตทุกวัน)
7. [ติดตั้ง Dashboard](#7-ติดตั้ง-dashboard)
8. [เปิด Dashboard ผ่านโดเมน (nginx + HTTPS)](#8-เปิด-dashboard-ผ่านโดเมน-nginx--https)
9. [ดูแลระบบประจำ](#9-ดูแลระบบประจำ)
10. [แก้ปัญหา](#10-แก้ปัญหา)
11. [รายละเอียดสคริปต์และฐานข้อมูล](#11-รายละเอียดสคริปต์และฐานข้อมูล)
12. [โครงสร้างไฟล์](#12-โครงสร้างไฟล์)

---

## 1. ภาพรวมของระบบ

| ส่วน | ไฟล์ | ทำอะไร |
|---|---|---|
| ดึงข้อมูลทั้งหมด | `export_all.py` | ดึงทั้ง 7 รายงานลง `restosuite.db` (รายงานละ 1 ตาราง) และ `export/*.csv` แล้วเทียบยอดรวมกับ RestoSuite ทุกครั้ง |
| ดึงรายงาน Orders อย่างเดียว | `restosuite_orders.py` | ดาวน์โหลดรายงาน Orders ของช่วงวันที่ที่เลือก เป็น CSV หรือ Excel |
| งานรายวัน | `deploy/run-daily.sh` | ดึงข้อมูล 7 วันล่าสุดใหม่ แล้วอัปเดตฐานข้อมูล (cron เรียกทุกวัน 04:00 เวลาไทย) |
| Dashboard | `dashboard/` | เว็บ Flask แสดงภาพรวม + 1 หน้าต่อรายงาน กรองช่วงวันที่ได้ และดาวน์โหลด CSV ได้ |
| เปิดเว็บสู่ภายนอก | `deploy/nginx-dashboard.conf`, `deploy/setup-nginx.sh` | ตั้ง nginx + HTTPS ให้ `report.spicycatgroups.com` |

สคริปต์เรียก JSON API ตัวเดียวกับที่หน้า report ของ RestoSuite ใช้ ล็อกอินด้วย token ของบัญชีคุณเอง ดึงทีละ 500 แถวจนครบ และไม่มีการเขียนข้อมูลกลับไปที่ RestoSuite

## 2. สิ่งที่ต้องมี

- **บัญชี RestoSuite** ที่เปิดรายงานใน Common Reports ได้
- **Python 3.9 ขึ้นไป** (บน VPS ใช้ 3.12)
- **สำหรับ VPS:** Ubuntu/Debian ที่เข้าด้วย SSH key ได้, มี `git` และ `python3-venv`, user ที่อยู่ในกลุ่ม `docker`, nginx และ certbot และต้องมีสิทธิ์ `sudo` สำหรับขั้นตั้ง nginx
- **สำหรับโดเมน:** สิทธิ์แก้ DNS ของ `spicycatgroups.com` ใน Cloudflare

## 3. หา token และ ID จาก RestoSuite

ต้องใช้ทั้งหมด 5 ค่า ใส่ไว้ในไฟล์ `.env` (ดูตัวอย่างใน `.env.example`)

**token (`RESTOSUITE_TOKEN`)**
1. ล็อกอิน https://bo.sea.restosuite.ai ใน Chrome
2. กด `F12` แล้วไปที่แท็บ **Console**
3. รัน `localStorage.getItem("vulcan-Token")` แล้วคัดลอกค่าที่ได้ โดยไม่เอาเครื่องหมาย `"` หัวท้าย

**Store ID และ ID ของบัญชี**
1. เปิดรายงาน **Orders** (`/report/report-sales-orders`) แล้วกด `F12` ไปที่แท็บ **Network**
2. กด **Query** บนหน้า report แล้วเลือก request ชื่อ `queryData`
3. ใน **Request Headers** ให้คัดลอกค่าเหล่านี้:

| ตัวแปรใน `.env` | ค่าจาก header |
|---|---|
| `RESTOSUITE_SHOP_IDS` | `Shop-Id` (หลายร้านให้คั่นด้วยจุลภาค) |
| `RESTOSUITE_BRAND_ID` | `Brand-Id` |
| `RESTOSUITE_CORPORATION_ID` | `Corporation-Id` |
| `RESTOSUITE_ORGANIZATION_ID` | `Organization-Id` |

> token ใช้แทนการล็อกอินได้ จึงต้องเก็บเหมือนรหัสผ่าน และ **token จะใช้ไม่ได้ทันทีที่กด Log out** จาก RestoSuite ถ้าจะใช้สคริปต์ต่อ ให้ปิดแท็บไปเฉยๆ อย่ากด Log out

## 4. ติดตั้งบนเครื่องตัวเอง

```bash
git clone https://github.com/thanakarnratt-droid/RestoSuite-Report.git
cd RestoSuite-Report
pip install -r requirements.txt
cp .env.example .env        # แล้วกรอก 5 ค่าจากขั้นที่ 3
```

ลองดึงข้อมูล:

```bash
python restosuite_orders.py --from 2026-10-14                 # ออเดอร์วันเดียว เป็น CSV
python export_all.py --csv-dir export                         # ทุกรายงาน ตั้งแต่วันแรกที่มีข้อมูล ลง restosuite.db
```

ถ้าทุกตารางขึ้นว่า `ยอดรวมเทียบกับ RestoSuite: ตรง` ก็แปลว่าตั้งค่าถูกต้อง

## 5. ติดตั้งบน VPS

ตัวอย่างในคู่มือนี้ใช้ user `dev_sc` และโฟลเดอร์ `~/RestoSuite-Report` ถ้าใช้ชื่ออื่นให้แก้ path ในคำสั่งและในไฟล์ `deploy/` ให้ตรงกัน

### 5.1 ตั้งค่า SSH key (ทำครั้งเดียว บนเครื่องตัวเอง)

สร้าง key ถ้ายังไม่มี:

```bash
ssh-keygen -t ed25519
```

ส่ง public key ขึ้น VPS (ระบบจะถามรหัสผ่าน VPS ครั้งเดียว) บน Windows PowerShell:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh dev_sc@<vps-ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
```

บน macOS/Linux ใช้ `ssh-copy-id dev_sc@<vps-ip>` แทนได้

### 5.2 Clone และติดตั้ง package

```bash
ssh dev_sc@<vps-ip>
git clone https://github.com/thanakarnratt-droid/RestoSuite-Report.git ~/RestoSuite-Report
cd ~/RestoSuite-Report
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r dashboard/requirements.txt
```

### 5.3 ใส่ `.env`

สร้าง `.env` บน VPS แล้วกรอก 5 ค่าจากขั้นที่ 3:

```bash
cp .env.example .env
nano .env
chmod 600 .env              # ให้ dev_sc อ่านได้คนเดียว
```

หรือคัดลอก `.env` จากเครื่องตัวเองขึ้นไป (รันบนเครื่องตัวเอง):

```bash
scp .env dev_sc@<vps-ip>:RestoSuite-Report/
```

### 5.4 ดึงข้อมูลรอบแรก

ดึงข้อมูลทั้งหมดบน VPS (ใช้เวลาไม่กี่นาที):

```bash
cd ~/RestoSuite-Report
.venv/bin/python export_all.py --csv-dir export
```

หรือถ้าเคยดึงไว้บนเครื่องตัวเองแล้ว อัปโหลด `restosuite.db` ขึ้นไปแทนก็ได้:

```bash
scp restosuite.db dev_sc@<vps-ip>:RestoSuite-Report/
```

## 6. ตั้งให้อัปเดตทุกวัน

`deploy/run-daily.sh` ดึงข้อมูล **7 วันล่าสุด** ใหม่ทุกครั้ง (`export_all.py --days 7 --csv-dir export`) เพื่อเก็บการคืนเงินหรือการแก้บิลที่เกิดหลังปิดวันด้วย ข้อมูลที่เก่ากว่านั้นไม่ถูกแตะ สคริปต์ใช้ `flock` กันไม่ให้มีงานรันซ้อนกัน

### แบบ A: cron (ไม่ต้องใช้ sudo) — ใช้อยู่บน VPS ตอนนี้

VPS ตั้งเวลาเป็น UTC ดังนั้น 21:00 UTC = 04:00 เวลาไทย:

```bash
mkdir -p ~/RestoSuite-Report/logs
crontab -e
```

เพิ่มบรรทัดนี้:

```
0 21 * * * PYTHONIOENCODING=utf-8 /home/dev_sc/RestoSuite-Report/deploy/run-daily.sh >> /home/dev_sc/RestoSuite-Report/logs/export.log 2>&1
```

ถ้า VPS ปิดอยู่ตอนถึงเวลา cron จะไม่รันย้อนหลัง แต่รอบถัดไปดึงย้อน 7 วันอยู่แล้ว จึงไม่มีข้อมูลหาย

### แบบ B: systemd timer (ต้องใช้ sudo)

แบบนี้รันย้อนหลังให้ถ้าเครื่องปิดอยู่ตอนถึงเวลา และเก็บ log ไว้ใน journal (ถ้า user หรือโฟลเดอร์ไม่ใช่ `dev_sc` / `~/RestoSuite-Report` ให้แก้ใน `deploy/restosuite-export.service` ก่อน):

```bash
sudo cp deploy/restosuite-export.service deploy/restosuite-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now restosuite-export.timer
systemctl list-timers restosuite-export.timer        # ดูเวลารอบถัดไป
journalctl -u restosuite-export -n 50                # ดู log
```

ให้ใช้แบบใดแบบหนึ่ง ไม่ต้องตั้งทั้งสองแบบ

### ทดสอบ

```bash
~/RestoSuite-Report/deploy/run-daily.sh              # สั่งรันทันที
tail -30 ~/RestoSuite-Report/logs/export.log         # ดูผลรอบล่าสุดของ cron
```

## 7. ติดตั้ง Dashboard

Dashboard มี 8 หน้า: **ภาพรวม** (ยอดขายสุทธิ, ออเดอร์, ยอดเฉลี่ย, ลูกค้า, ส่วนลด พร้อมเทียบกับช่วงก่อนหน้า, กราฟยอดรายวัน/รายชั่วโมง, ช่องทางชำระเงิน, สินค้าขายดี) และหน้าของรายงานแต่ละตัว ทุกหน้ากรองช่วงวันที่ได้ (ปุ่มลัด 7 วัน / 30 วัน / เดือนนี้ / เดือนก่อน / ทั้งหมด) และดาวน์โหลด CSV ของช่วงที่เลือกได้ เว็บอ่านฐานข้อมูลอย่างเดียว ไม่เคยเขียน

### 7.1 ตั้งรหัสผ่าน

```bash
cd ~/RestoSuite-Report
.venv/bin/python dashboard/app.py set-password
```

- ตั้งรหัสผ่านใหม่ขึ้นมาเอง ยาวอย่างน้อย 10 ตัวอักษร (ตอนพิมพ์ตัวอักษรจะไม่แสดงบนจอ)
- ระบบเก็บเป็น hash ไว้ใน `DASHBOARD_PASSWORD_HASH` ใน `.env` และสร้าง `DASHBOARD_SECRET_KEY` ให้ถ้ายังไม่มี
- ถ้ายังไม่ได้ตั้งรหัสผ่าน จะไม่มีใครล็อกอินได้

### 7.2 รันด้วย Docker

user ที่อยู่ในกลุ่ม `docker` ไม่ต้องใช้ sudo container จะ mount โฟลเดอร์ repo เข้าไปเลย จึงเห็นข้อมูลใหม่ทุกวันโดยไม่ต้อง restart และอ่านค่าตั้งค่าจาก `.env` ในโฟลเดอร์นั้น:

```bash
cd ~/RestoSuite-Report
docker build -t restosuite-dashboard -f dashboard/Dockerfile .
docker run -d --name restosuite-dashboard --restart unless-stopped \
  -p 127.0.0.1:5021:5021 -v "$PWD":/app restosuite-dashboard
```

- เปิดให้เข้าได้เฉพาะ `127.0.0.1:5021` คนนอกเข้าได้ผ่าน nginx ในขั้นที่ 8 เท่านั้น
- `--restart unless-stopped` ทำให้ container เปิดเองเมื่อ VPS reboot

ทดสอบว่าเว็บตอบ:

```bash
curl -I http://127.0.0.1:5021/login        # ต้องได้ 200
```

ยังไม่มีโดเมนก็เปิดดูได้ ผ่าน SSH tunnel (รันบนเครื่องตัวเอง แล้วเปิด http://localhost:5021):

```bash
ssh -N -L 5021:127.0.0.1:5021 dev_sc@<vps-ip>
```

### รันบนเครื่องตัวเอง (สำหรับทดลอง)

```bash
pip install -r dashboard/requirements.txt
python dashboard/app.py set-password
python dashboard/app.py                    # http://127.0.0.1:5021
```

## 8. เปิด Dashboard ผ่านโดเมน (nginx + HTTPS)

### 8.1 เพิ่ม DNS ใน Cloudflare

**Cloudflare → spicycatgroups.com → DNS → Add record**

| Type | Name | Content | Proxy status |
|---|---|---|---|
| A | `report` | IP ของ VPS | Proxied (เมฆสีส้ม) เหมือน `cbta` และ `ops` |

### 8.2 ติดตั้ง nginx site และขอ certificate

รอให้ DNS ใช้ได้ก่อน (ปกติไม่กี่นาที) แล้วรันบน VPS:

```bash
cd ~/RestoSuite-Report
sudo sh deploy/setup-nginx.sh
```

สคริปต์จะทำตามลำดับนี้:
1. คัดลอก `deploy/nginx-dashboard.conf` ไปที่ `/etc/nginx/sites-available/restosuite-dashboard` แล้ว link เข้า `sites-enabled`
2. รัน `nginx -t` ถ้าไม่ผ่าน จะลบไฟล์ที่เพิ่งเพิ่มออก ให้ nginx กลับไปเหมือนเดิม site อื่นจึงไม่ได้รับผลกระทบ
3. reload nginx
4. รัน `certbot --nginx -d report.spicycatgroups.com --redirect` เพื่อขอ certificate จาก Let's Encrypt และส่ง http ไป https
5. ถ้ามี site ชื่อนี้อยู่แล้ว สคริปต์จะไม่เขียนทับ

เสร็จแล้วเปิด **https://report.spicycatgroups.com** แล้วล็อกอินด้วยรหัสผ่านจากขั้นที่ 7.1 certbot จะต่ออายุ certificate ให้เอง

## 9. ดูแลระบบประจำ

| งาน | คำสั่ง (บน VPS ในโฟลเดอร์ `~/RestoSuite-Report`) |
|---|---|
| ดูผลงานรายวันล่าสุด | `tail -30 logs/export.log` |
| สั่งอัปเดตข้อมูลทันที | `deploy/run-daily.sh` |
| ดึงย้อนหลังมากกว่า 7 วัน | `deploy/run-daily.sh --days 30` |
| สร้างฐานข้อมูลใหม่ทั้งหมด | `.venv/bin/python export_all.py --csv-dir export` |
| อัปเดต token | แก้ `RESTOSUITE_TOKEN` ใน `.env` แล้วรัน `deploy/run-daily.sh` เพื่อทดสอบ |
| เปลี่ยนรหัสผ่าน dashboard | `.venv/bin/python dashboard/app.py set-password && docker restart restosuite-dashboard` |
| อัปเดตโค้ด | `git pull && docker restart restosuite-dashboard` |
| แก้ `requirements.txt` หรือ `dashboard/Dockerfile` | `docker build -t restosuite-dashboard -f dashboard/Dockerfile .` แล้ว `docker rm -f restosuite-dashboard` และรัน `docker run` ในขั้นที่ 7.2 ใหม่ |
| ดู log ของ dashboard | `docker logs --tail 50 restosuite-dashboard` |
| สำรองฐานข้อมูล | `.venv/bin/python -c "import sqlite3; sqlite3.connect('restosuite.db').backup(sqlite3.connect('restosuite-backup.db'))"` (สำรองได้แม้งานรายวันกำลังรัน) |

**ควรเช็กเป็นระยะ:** ระบบไม่มีการแจ้งเตือนเมื่องานรายวันพัง ถ้าตัวเลขบน dashboard ไม่ขยับ ("ข้อมูลถึง" ใต้หัวข้อหน้าเป็นวันเก่า) ให้ดู `logs/export.log`

## 10. แก้ปัญหา

| อาการ | สาเหตุ | วิธีแก้ |
|---|---|---|
| log ขึ้นว่า `token หมดอายุหรือไม่ถูกต้อง` | มีคน Log out จาก RestoSuite หรือ token ถูกเปลี่ยน | ดึง token ใหม่ (ขั้นที่ 3) ใส่ใน `.env` แล้วรัน `deploy/run-daily.sh` |
| log ขึ้นว่า `RestoSuite ไม่ว่าง รอ ... วินาที` | RestoSuite ตอบว่า `metric-01002 please try again later` | สคริปต์รอแล้วลองใหม่ให้เองสูงสุด 5 ครั้ง ถ้ายังไม่ได้ให้รันใหม่ภายหลัง |
| log ขึ้นว่า `ยอดรวมไม่ตรง` | ข้อมูลที่ดึงมารวมแล้วไม่เท่ากับยอดที่ RestoSuite คำนวณ (เช่น ข้อมูลเปลี่ยนระหว่างดึง) | รัน `deploy/run-daily.sh` ใหม่ ถ้ายังไม่ตรงอีก อาจเป็นเพราะ RestoSuite เปลี่ยน API |
| เปิดเว็บแล้วขึ้น **Cloudflare error 526** | nginx ยังไม่มี site หรือ certificate ของ `report.spicycatgroups.com` จึงส่ง certificate ของ site อื่นไปแทน | รันขั้นที่ 8.2 (`sudo sh deploy/setup-nginx.sh`) |
| เปิดเว็บแล้วขึ้น **502 Bad Gateway** | container ของ dashboard ไม่ได้รัน | `docker ps -a --filter name=restosuite-dashboard` แล้ว `docker start restosuite-dashboard` หรือดู `docker logs restosuite-dashboard` |
| certbot ขอ certificate ไม่สำเร็จ | DNS ยังไม่ใช้ได้ หรือ Cloudflare เปิด "Always Use HTTPS" ทำให้ certbot ยืนยันโดเมนผ่าน http ไม่ได้ | รอ DNS แล้วลบ site ที่สร้างไว้ (`sudo rm /etc/nginx/sites-enabled/restosuite-dashboard /etc/nginx/sites-available/restosuite-dashboard && sudo systemctl reload nginx`) จากนั้นรันขั้นที่ 8.2 ใหม่ |
| ล็อกอินแล้วขึ้น `ยังไม่ได้ตั้ง DASHBOARD_PASSWORD_HASH` | ยังไม่ได้ตั้งรหัสผ่าน | ทำขั้นที่ 7.1 แล้ว `docker restart restosuite-dashboard` |
| หน้าเว็บขึ้น `ไม่พบฐานข้อมูล` | ยังไม่มี `restosuite.db` ในโฟลเดอร์ repo | ทำขั้นที่ 5.4 |
| ข้อความภาษาไทยใน log เพี้ยน | terminal ไม่ได้ใช้ UTF-8 | ใส่ `PYTHONIOENCODING=utf-8` หน้าคำสั่ง (บรรทัด cron ใส่ไว้แล้ว) |

## 11. รายละเอียดสคริปต์และฐานข้อมูล

### `export_all.py`

```bash
python export_all.py                                   # ทั้งหมด ลง restosuite.db
python export_all.py --csv-dir export                  # และเขียน CSV ทุกตารางลง export/
python export_all.py --days 7 --csv-dir export         # อัปเดตเฉพาะ 7 วันล่าสุด (งานรายวัน)
python export_all.py --from 2026-10-01 --to 2026-10-14 --db october.db
python export_all.py --only orders --only order_items  # เฉพาะบางตาราง
```

| ตาราง | รายงานใน RestoSuite | 1 แถว = |
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
- `_columns` บอกว่าแต่ละคอลัมน์มาจาก field ไหนของ RestoSuite และชื่อบนหน้าเว็บคืออะไร
- `_exports` บันทึกช่วงวันที่ จำนวนแถว เวลาที่ดึง และผลเทียบยอดรวมของแต่ละตาราง
- หลังดึงแต่ละตาราง สคริปต์จะเทียบยอดรวม (เช่น Net Sales, จำนวนรายการ) กับยอดที่ RestoSuite คำนวณเอง ถ้าไม่ตรงจะแจ้งและจบด้วย exit code 1
- ถ้าไม่ใส่ `--days` ตารางจะถูกสร้างใหม่ทั้งหมด ถ้าใส่ `--days N` จะลบแล้วดึงใหม่เฉพาะ N วันล่าสุด ทั้งสองแบบรันซ้ำได้โดยไม่เกิดข้อมูลซ้ำ
- CSV ใน `--csv-dir` เป็นข้อมูลทั้งตารางเสมอ บันทึกเป็น UTF-8 BOM จึงเปิดภาษาไทยใน Excel ได้ถูกต้อง
- ดึงเฉพาะออเดอร์ที่สถานะ "เสร็จสิ้น" (status 20) เหมือนค่าเริ่มต้นของหน้า report ออเดอร์ที่ void หรือยกเลิกจะไม่อยู่ในฐานข้อมูล
- "วันนี้" นับตามเวลาไทย (`RESTOSUITE_TIMEZONE`, ค่าเริ่มต้น `Asia/Bangkok`) แม้ server จะตั้งเวลาเป็น UTC

### `restosuite_orders.py`

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
| `--status` | `20` | รหัสสถานะออเดอร์ |
| `--currency` | `THB` | สกุลเงิน |

### ตัวแปรใน `.env`

| ตัวแปร | ต้องมี | ใช้กับ |
|---|---|---|
| `RESTOSUITE_TOKEN` | ✓ | สคริปต์ดึงข้อมูล |
| `RESTOSUITE_SHOP_IDS` | ✓ | สคริปต์ดึงข้อมูล |
| `RESTOSUITE_BRAND_ID`, `RESTOSUITE_CORPORATION_ID`, `RESTOSUITE_ORGANIZATION_ID` | ✓ | สคริปต์ดึงข้อมูล |
| `RESTOSUITE_TIMEZONE` | | เขตเวลาที่ใช้นับ "วันนี้" (ค่าเริ่มต้น `Asia/Bangkok`) |
| `DASHBOARD_PASSWORD_HASH` | ✓ (dashboard) | สร้างด้วย `dashboard/app.py set-password` |
| `DASHBOARD_SECRET_KEY` | ✓ (dashboard) | key สำหรับเซ็น session (`set-password` สร้างให้) |
| `DASHBOARD_SECURE_COOKIE` | | ส่ง cookie ผ่าน HTTPS เท่านั้น (ค่าเริ่มต้น `true`) |
| `RESTOSUITE_DB` | | path ของฐานข้อมูลที่ dashboard อ่าน (ค่าเริ่มต้น `restosuite.db` ใน repo) |

## 12. โครงสร้างไฟล์

```
├── export_all.py                 ดึงทั้ง 7 รายงานลง SQLite + CSV
├── restosuite_orders.py          ดึงรายงาน Orders เป็น CSV/Excel (และโค้ดเรียก API ที่ใช้ร่วมกัน)
├── requirements.txt              click, openpyxl
├── .env.example                  ตัวอย่างค่าตั้งค่า (คัดลอกเป็น .env)
├── dashboard/
│   ├── app.py                    เว็บ Flask (+ คำสั่ง set-password)
│   ├── templates/, static/       หน้าเว็บ, CSS, กราฟ (Chart.js)
│   ├── Dockerfile                image สำหรับรัน dashboard ด้วย gunicorn
│   └── requirements.txt          flask, gunicorn
├── deploy/
│   ├── run-daily.sh              งานรายวัน (ดึง 7 วันล่าสุด)
│   ├── restosuite-export.service ┐ systemd timer (แบบ B)
│   ├── restosuite-export.timer   ┘
│   ├── nginx-dashboard.conf      nginx site ของ report.spicycatgroups.com
│   └── setup-nginx.sh            ติดตั้ง nginx site + certbot (sudo)
│
│  ไฟล์ที่สร้างตอนใช้งาน (ไม่อยู่ใน git):
├── .env                          token, ID, รหัสผ่าน dashboard (hash)
├── restosuite.db                 ฐานข้อมูล
├── export/                       CSV ทุกตาราง
└── logs/export.log               log ของงานรายวัน
```

## ข้อควรรู้

- **อย่า commit `.env`** เพราะมี token ที่ใช้แทนการล็อกอิน RestoSuite ได้ ไฟล์นี้อยู่ใน `.gitignore` แล้ว และ repo นี้เป็น public
- สคริปต์ใช้ API ภายในของหน้าเว็บ RestoSuite ไม่ใช่ API ที่เปิดให้ใช้อย่างเป็นทางการ ถ้า RestoSuite เปลี่ยนระบบ สคริปต์อาจต้องแก้ตาม การเทียบยอดรวมทุกครั้งจะช่วยให้รู้ตัวได้เร็ว
- dashboard ต้องล็อกอินก่อนทุกหน้า และใส่รหัสผิดจะถูกหน่วงเวลาไว้ 1 วินาทีต่อครั้ง ควรตั้งรหัสผ่านที่ยาวและไม่ซ้ำกับระบบอื่น
