"""Export the RestoSuite "Orders" report (report-sales-orders) to CSV or Excel.

Calls the same JSON API the back office page uses, page by page, so it returns
every order in the date range instead of only what is shown on screen.

Settings come from environment variables or a .env file next to this script:

    RESTOSUITE_TOKEN       value of localStorage["vulcan-Token"] after logging in
                           at https://bo.sea.restosuite.ai (see README)
    RESTOSUITE_SHOP_IDS    comma-separated store IDs, e.g. 406937599
    RESTOSUITE_BRAND_ID, RESTOSUITE_CORPORATION_ID,
    RESTOSUITE_ORGANIZATION_ID   request headers the page sends for your account

Examples:

    python restosuite_orders.py                       # yesterday, CSV
    python restosuite_orders.py --from 2026-10-01 --to 2026-10-14 --format xlsx
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import click

BASE_URL = "https://bo.sea.restosuite.ai"
REPORT_ID = "888002"  # Orders
PAGE_SIZE = 500

# Columns shown by default on the report page, in the same order.
DEFAULT_FIELDS = [
    "D_businessDate",
    "D_shopName",
    "D_posOrderId",
    "D_Tag_exceptionIdentifier",
    "D_diningOption",
    "D_source",
    "D_Combined_D_source_And_D_callNumber",
    "D_openedTime",
    "D_startCashierRotas",
    "D_openedBy",
    "M_Order_SUM_netSales",
    "M_Order_SUM_excludedRevenueSurcharge",
    "M_Order_SUM_receivableSales",
    "M_Order_SUM_totalGrossSales",
    "M_Order_SUM_foodOriginAmount",
    "M_Order_SUM_surcharge",
    "M_Order_SUM_tax",
    "M_Order_SUM_tips",
    "M_Order_SUM_guests",
    "M_Order_SUM_includedRevenueSurcharge",
    "M_Order_AVG_DiningDuration",
    "D_shopId",
]

ROOT = Path(__file__).resolve().parent


def load_dotenv(path):
    """Fill os.environ from a KEY=value file without overriding existing values."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise click.ClickException(f"ยังไม่ได้ตั้งค่า {name} (ใส่ใน .env หรือ environment)")
    return value


class RestoSuite:
    def __init__(self, token, shop_ids):
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "vulcan-Token": token,
            "Language-Code": os.environ.get("RESTOSUITE_LANGUAGE", "en_US"),
            "Accept-Timezone": os.environ.get("RESTOSUITE_TIMEZONE", "Asia/Bangkok"),
            "Brand-Id": require_env("RESTOSUITE_BRAND_ID"),
            "Corporation-Id": require_env("RESTOSUITE_CORPORATION_ID"),
            "Organization-Id": require_env("RESTOSUITE_ORGANIZATION_ID"),
            "Organization-Type": os.environ.get("RESTOSUITE_ORGANIZATION_TYPE", "7"),
            "Shop-Id": shop_ids[0],
        }

    def post(self, path, payload, retries=3):
        body = json.dumps(payload).encode()
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(BASE_URL + path, data=body, headers=self.headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.load(resp)
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    raise click.ClickException("token หมดอายุหรือไม่ถูกต้อง ให้ล็อกอินใหม่แล้วอัปเดต RESTOSUITE_TOKEN")
                if attempt == retries or e.code < 500:
                    raise click.ClickException(f"{path}: HTTP {e.code}")
            except urllib.error.URLError as e:
                if attempt == retries:
                    raise click.ClickException(f"{path}: {e.reason}")
            time.sleep(2 * attempt)
        if data.get("code") != "000":
            # Expired sessions come back as HTTP 200 with an error code.
            raise click.ClickException(f"{path}: {data.get('code')} {data.get('msg')}")
        return data["data"]

    def field_labels(self):
        meta = self.post("/api/report/metadata/get", {"reportId": REPORT_ID})
        return {f["reportFieldName"]: f["displayText"] for f in meta["dimList"] + meta["metricsList"]}

    def iter_orders(self, start, end, shop_ids, fields, statuses, currency):
        payload = {
            "metricsByDimQryV2": [],
            "reportId": REPORT_ID,
            "selectFields": fields,
            "aggFilters": [],
            "proportionProperty": {"enable": False},
            "dimAdditionalStrategy": [],
            "filters": [
                {"fieldName": "D_businessDate", "filterType": "RANGE", "filterValue": [start, end]},
                {"fieldName": "D_orderStatus", "filterType": "IN", "filterValue": statuses},
                {"fieldName": "D_currency", "filterType": "EQ", "filterValue": [currency]},
                {"fieldName": "D_shopId", "filterType": "IN", "filterValue": shop_ids},
            ],
            "orderBy": [{"D_businessDate": "ASC"}, {"D_shopName": "ASC"}, {"D_posOrderId": "ASC"}],
        }
        page_no = 1
        while True:
            payload["page"] = {"pageNo": page_no, "pageSize": PAGE_SIZE}
            data = self.post("/api/report/data/queryData", payload)
            page = data["page"]
            click.echo(f"  หน้า {page_no}/{max(page['pageCount'], 1)} ({page['total']} ออเดอร์)", err=True)
            yield from data["rows"]
            if page_no >= page["pageCount"]:
                break
            page_no += 1


def cell(row, field):
    """Numbers stay numeric for metrics; dimensions use the text shown on the page."""
    item = row.get(field)
    if not item:
        return ""
    if field.startswith("M_"):
        try:
            return float(item["value"]) if "." in item["value"] else int(item["value"])
        except (TypeError, ValueError):
            return item.get("displayValue", "")
    text = item.get("displayValue") or item.get("value") or ""
    return "" if text == "[]" else text  # empty tag lists come back as "[]"


def write_csv(path, headers, rows):
    # utf-8-sig so Excel opens Thai text correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows([f"{v:.2f}" if isinstance(v, float) else v for v in r] for r in rows)


def write_xlsx(path, headers, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A2"
    for col in ws.columns:
        width = max(len(str(c.value or "")) for c in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 10), 40)
    wb.save(path)


@click.command()
@click.option("--from", "start", help="วันเริ่ม YYYY-MM-DD (ค่าเริ่มต้น: เมื่อวาน)")
@click.option("--to", "end", help="วันสิ้นสุด YYYY-MM-DD (ค่าเริ่มต้น: เท่ากับ --from)")
@click.option("--shop", "shops", multiple=True, help="Store ID (ใส่ซ้ำได้) แทน RESTOSUITE_SHOP_IDS")
@click.option("--format", "fmt", type=click.Choice(["csv", "xlsx"]), default="csv", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), help="ไฟล์ผลลัพธ์")
@click.option("--status", "statuses", multiple=True, default=["20"], show_default=True,
              help="รหัสสถานะออเดอร์ (20 = ค่าที่หน้า report ใช้เป็นค่าเริ่มต้น)")
@click.option("--currency", default="THB", show_default=True)
def main(start, end, shops, fmt, out, statuses, currency):
    """Download the RestoSuite Orders report for a date range."""
    load_dotenv(ROOT / ".env")
    start = start or (date.today() - timedelta(days=1)).isoformat()
    end = end or start
    for d in (start, end):
        try:
            date.fromisoformat(d)
        except ValueError:
            raise click.BadParameter(f"วันที่ไม่ถูกต้อง: {d} (ใช้ YYYY-MM-DD)")
    shop_ids = list(shops) or [s.strip() for s in require_env("RESTOSUITE_SHOP_IDS").split(",") if s.strip()]

    api = RestoSuite(require_env("RESTOSUITE_TOKEN"), shop_ids)
    labels = api.field_labels()
    click.echo(f"ดึงออเดอร์ {start} ถึง {end} ร้าน {', '.join(shop_ids)}", err=True)
    rows = [[cell(r, f) for f in DEFAULT_FIELDS]
            for r in api.iter_orders(start, end, shop_ids, DEFAULT_FIELDS, list(statuses), currency)]
    headers = [labels.get(f, f) for f in DEFAULT_FIELDS]

    out = out or Path(f"restosuite-orders-{start}_{end}.{fmt}")
    (write_xlsx if fmt == "xlsx" else write_csv)(out, headers, rows)
    click.echo(f"บันทึก {len(rows)} ออเดอร์ลง {out}", err=True)


if __name__ == "__main__":
    # Windows consoles default to cp874/cp1252, which garbles the Thai messages.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
