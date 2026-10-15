"""Export the RestoSuite "Common Reports" for every store into a SQLite database.

Pulls the seven reports listed under Common Reports on the back office, at the
finest level each one allows (per order, per order line, per payment, per
discount, or per day), and writes one table per report. Every row carries
shop_id, and the stores themselves are listed in the shops table. Stores are
exported one at a time and each run replaces only that store's rows for the
range it fetched, so it is safe to re-run, and new stores are picked up
automatically when RESTOSUITE_SHOP_IDS is "all" (the default).

    python export_all.py                         # all time, into restosuite.db
    python export_all.py --from 2026-10-01 --to 2026-10-14 --db october.db
    python export_all.py --csv-dir export        # also write one CSV per table
    python export_all.py --days 7 --csv-dir export   # daily job: refresh only the last 7 days

Uses the same .env settings as restosuite_orders.py.
"""
import csv
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import click

from restosuite_orders import ROOT, RestoSuite, load_dotenv, require_env, today

COMPLETED = ["20"]  # order status the report pages filter on by default
PAYMENT_ORDER_TYPES = ["1100", "1200", "1300"]


def report(table, report_id, title, fields, order_by, totals, status=True, extra_filters=()):
    return {
        "table": table,
        "report_id": report_id,
        "title": title,
        # The report pages repeat some fields (e.g. D_shopId); the API rejects nothing
        # but SQLite would get duplicate columns.
        "fields": list(dict.fromkeys(fields)),
        "order_by": order_by,
        "totals": totals,
        "status": status,
        "extra_filters": list(extra_filters),
    }


REPORTS = [
    report(
        "orders", "888002", "Orders",
        ["D_businessDate", "D_shopId", "D_shopName", "D_posOrderId", "D_orderId",
         "D_Tag_exceptionIdentifier", "D_diningOption", "D_source", "D_Combined_D_source_And_D_callNumber",
         "D_openedTime", "D_startCashierRotas", "D_openedBy",
         "M_Order_SUM_netSales", "M_Order_SUM_excludedRevenueSurcharge", "M_Order_SUM_receivableSales",
         "M_Order_SUM_totalGrossSales", "M_Order_SUM_foodOriginAmount", "M_Order_SUM_surcharge",
         "M_Order_SUM_tax", "M_Order_SUM_tips", "M_Order_SUM_guests", "M_Order_SUM_includedRevenueSurcharge",
         "M_Order_AVG_DiningDuration"],
        [{"D_businessDate": "ASC"}, {"D_posOrderId": "ASC"}],
        ["M_Order_SUM_netSales", "M_Order_SUM_guests"],
    ),
    report(
        "order_items", "211", "Items Breakdown",
        ["D_businessDate", "D_shopId", "D_posOrderId", "D_orderId", "D_itemId", "D_parentItemId", "D_itemCode",
         "D_itemName", "D_parentCategory", "D_category", "D_itemType", "D_unit", "D_itemPrice",
         "D_itemAttributes",
         "M_Item_SUM_netSales", "M_Item_SUM_netQty", "M_Item_SUM_grossSales", "M_Item_SUM_discountProm",
         "M_Item_SUM_refundQty", "M_Item_SUM_refundAmount", "M_Item_SUM_presentQty",
         "M_Item_SUM_presentAmount"],
        # Sort on enough fields that no two rows tie; with ties the API can return a
        # row on two pages and skip another.
        [{"D_businessDate": "ASC"}, {"D_posOrderId": "ASC"}, {"D_itemName": "ASC"}, {"D_itemId": "ASC"},
         {"D_parentItemId": "ASC"}, {"D_itemAttributes": "ASC"}, {"D_unit": "ASC"}, {"D_itemPrice": "ASC"}],
        ["M_Item_SUM_netSales", "M_Item_SUM_netQty"],
        # Same item types the Items Breakdown page selects by default.
        extra_filters=[{"fieldName": "D_itemType", "filterType": "IN", "filterValue": ["0", "2"]}],
    ),
    report(
        "payments", "199", "Payments Detail",
        ["D_businessDate", "D_shopId", "D_shopName", "D_posOrderId", "D_orderId", "D_source", "D_paymentType",
         "D_payerType", "D_startCashierRotas", "D_cashierRotasCheckout", "D_payEndTime",
         "M_OrderPayment_COUNT_count", "M_OrderPayment_SUM_refundAmount",
         "M_OrderPayment_SUM_netPaymentAmount", "M_OrderPayment_SUM_merchantReceiveAmount"],
        [{"D_businessDate": "ASC"}, {"D_posOrderId": "ASC"}],
        ["M_OrderPayment_SUM_netPaymentAmount", "M_OrderPayment_COUNT_count"],
        extra_filters=[{"fieldName": "D_orderType", "filterType": "IN", "filterValue": PAYMENT_ORDER_TYPES}],
    ),
    report(
        "payments_daily", "198", "Payments Breakdown",
        ["D_businessDate", "D_shopId", "D_paymentType", "D_payerType", "D_couponName",
         "M_OrderPayment_COUNT_count", "M_OrderPayment_SUM_refundAmount",
         "M_OrderPayment_SUM_netPaymentAmount", "M_OrderPayment_SUM_merchantReceiveAmount"],
        [{"D_businessDate": "ASC"}, {"D_payerType": "ASC"}],
        ["M_OrderPayment_SUM_netPaymentAmount", "M_OrderPayment_COUNT_count"],
        extra_filters=[{"fieldName": "D_orderType", "filterType": "IN", "filterValue": PAYMENT_ORDER_TYPES}],
    ),
    report(
        "discounts", "100141", "Discount Detail List",
        ["D_businessDate", "D_shopId", "D_shopCode", "D_shopName", "D_source", "D_discountPromotionSubType",
         "D_promotionSubType", "D_discountPromotionName", "D_couponCode", "D_posOrderId", "D_reason",
         "D_discountId", "D_approvedByCodeAndName", "D_appliedByCodeAndName",
         "M_DiscountPromotion_SUM_Amount", "M_DiscountPromotion_COUNT_count", "M_Promotion_COUNT_countOrder",
         "M_Promotion_SUM_drivingAmount", "M_Promotion_SUM_totalGrossSales", "M_Promotion_SUM_Orders",
         "M_Promotion_SUM_guests", "M_DiscountPromotion_promotionRate"],
        [{"D_businessDate": "ASC"}, {"D_posOrderId": "ASC"}],
        ["M_DiscountPromotion_SUM_Amount", "M_DiscountPromotion_COUNT_count"],
        status=False,
    ),
    report(
        "discounts_daily", "100140", "Discount & Promotion",
        ["D_businessDate", "D_shopId", "D_shopName", "D_discountPromotionSubType", "D_promotionSubType",
         "D_discountPromotionName", "D_appliedByCodeAndName", "D_approvedByCodeAndName",
         "M_DiscountPromotion_SUM_Amount", "M_DiscountPromotion_COUNT_count", "M_Promotion_COUNT_countOrder",
         "M_Promotion_SUM_drivingAmount", "M_Promotion_SUM_totalGrossSales"],
        [{"D_businessDate": "ASC"}],
        ["M_DiscountPromotion_SUM_Amount", "M_DiscountPromotion_COUNT_count"],
        status=False,
    ),
    report(
        "sales_daily", "888001", "Sales Summary Report",
        ["D_businessDate", "D_shopId", "D_shopName", "M_Order_COUNT_Orders", "M_Order_SUM_guests",
         "M_Order_SUM_netSales", "M_Order_SUM_totalPromotionAmount", "M_Order_SUM_excludedRevenueSurcharge",
         "M_Order_SUM_RoundingAmount", "M_Order_SUM_receivableSales", "M_Order_SUM_totalGrossSales",
         "M_Order_SUM_surcharge", "M_Order_SUM_includedRevenueSurcharge", "M_Order_AVG_netSalesByOrder",
         "M_Order_AVG_netSalesByGuest"],
        [{"D_businessDate": "ASC"}],
        ["M_Order_SUM_netSales", "M_Order_COUNT_Orders"],
    ),
]

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$")
MONEY_TEXT = re.compile(r"^[฿$]-?[\d,]+(\.\d+)?$")
METRIC = re.compile(r"^M_[A-Za-z]+_(?:SUM|COUNT|AVG|MAX|MIN)_(.+)$")


def snake(name):
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).replace("__", "_").lower()


def column_name(field):
    m = METRIC.match(field)
    if m:
        return snake(m.group(1))
    if field.startswith("D_Combined_"):
        return snake(field[len("D_Combined_"):].replace("D_", ""))
    return snake(field[2:])


def column_names(fields):
    names, used = {}, set()
    for f in fields:
        name = column_name(f)
        if name in used:
            name = snake(f)  # e.g. two metrics that end in "_count"
        used.add(name)
        names[f] = name
    return names


def month_chunks(start, end):
    """Split [start, end] into calendar months so no single query gets too large."""
    cur = start
    while cur <= end:
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        yield cur, min(end, nxt - timedelta(days=1))
        cur = nxt


def metric_value(raw):
    if raw in (None, ""):
        return None
    try:
        return int(raw) if re.fullmatch(r"-?\d+", raw) else float(raw)
    except ValueError:
        return raw


def dim_values(item):
    """(stored value, raw code or None) for a dimension cell."""
    if not item:
        return None, None
    value, display = item.get("value"), item.get("displayValue")
    if value and ISO_DATE.match(value):
        return value.replace("T", " "), None
    if display and MONEY_TEXT.match(display):
        return float(display[1:].replace(",", "")), None  # e.g. item price "฿155.00"
    text = display if display not in (None, "", "[]") else (value if value not in ("", "[]") else None)
    raw = value if value not in (None, "", "[]") and value != display else None
    return text, raw


def fetch_report(api, cfg, start, end, shop_ids, currency):
    order_by = cfg["order_by"]
    rows = []
    for a, b in month_chunks(start, end):
        click.echo(f"  {a} ถึง {b}", err=True)
        rows.extend(api.query_rows(cfg["report_id"], cfg["fields"], build_filters(cfg, a, b, shop_ids, currency),
                                   order_by))
    return rows


def build_filters(cfg, start, end, shop_ids, currency):
    filters = [{"fieldName": "D_businessDate", "filterType": "RANGE",
                "filterValue": [start.isoformat(), end.isoformat()]}]
    if cfg["status"]:
        filters.append({"fieldName": "D_orderStatus", "filterType": "IN", "filterValue": COMPLETED})
    filters += cfg["extra_filters"]
    filters += [
        {"fieldName": "D_currency", "filterType": "EQ", "filterValue": [currency]},
        {"fieldName": "D_shopId", "filterType": "IN", "filterValue": shop_ids},
    ]
    return filters


def convert_rows(cfg, labels, rows):
    fields = cfg["fields"]
    names = column_names(fields)
    dims = [f for f in fields if f.startswith("D_")]
    metrics = [f for f in fields if f.startswith("M_")]

    converted, raw_seen = [], set()
    for row in rows:
        rec = {}
        for f in dims:
            text, raw = dim_values(row.get(f))
            rec[names[f]] = text
            if raw is not None:
                rec[names[f] + "_code"] = raw
                raw_seen.add(f)
        for f in metrics:
            rec[names[f]] = metric_value((row.get(f) or {}).get("value"))
        converted.append(rec)

    # (column, type, source field, label); codes sit right after the text they belong to.
    columns = []
    for f in fields:
        if f.startswith("D_"):
            # Money shown as text (e.g. item price "฿155.00") was converted to a number above;
            # a REAL column keeps it one, where TEXT affinity would turn it back into "155.0".
            values = [r[names[f]] for r in converted if r[names[f]] is not None]
            numeric = bool(values) and all(isinstance(v, float) for v in values)
            columns.append((names[f], "REAL" if numeric else "TEXT", f, labels.get(f, f)))
            if f in raw_seen:
                columns.append((names[f] + "_code", "TEXT", f, labels.get(f, f) + " (code)"))
        else:
            is_int = all(isinstance(r[names[f]], int) or r[names[f]] is None for r in converted)
            columns.append((names[f], "INTEGER" if is_int else "REAL", f, labels.get(f, f)))

    return columns, converted


def retype_columns(db, table, real_cols):
    """Rebuild a table so the given TEXT columns become REAL (SQLite cannot ALTER a column's type).

    Databases exported before price fields were numeric stored item_price as text.
    """
    info = [(r[1], r[2]) for r in db.execute(f'PRAGMA table_info("{table}")')]
    cols = ", ".join(f'"{c}" {"REAL" if c in real_cols else t}' for c, t in info)
    select = ", ".join(f'CAST("{c}" AS REAL)' if c in real_cols else f'"{c}"' for c, _ in info)
    db.execute(f'CREATE TABLE "{table}__new" ({cols})')
    db.execute(f'INSERT INTO "{table}__new" SELECT {select} FROM "{table}"')
    db.execute(f'DROP TABLE "{table}"')  # also drops its indexes; ensure_table recreates them
    db.execute(f'ALTER TABLE "{table}__new" RENAME TO "{table}"')


def ensure_table(db, table, columns):
    """Create the table, or add any columns it is missing (e.g. a code column that first shows up later)."""
    if not table_exists(db, table):
        db.execute(f'CREATE TABLE "{table}" (' + ", ".join(f'"{c}" {t}' for c, t, _, _ in columns) + ")")
        db.execute("DELETE FROM _columns WHERE table_name = ?", (table,))
        db.executemany("INSERT INTO _columns VALUES (?, ?, ?, ?, ?)",
                       [(table, i, c, f, label) for i, (c, _, f, label) in enumerate(columns)])
    else:
        info = {r[1]: r[2] for r in db.execute(f'PRAGMA table_info("{table}")')}
        stale = {c for c, t, *_ in columns if t == "REAL" and info.get(c) == "TEXT"}
        if stale:
            retype_columns(db, table, stale)
        existing = list(info)
        position = len(existing)
        for c, t, f, label in columns:
            if c not in existing:
                db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{c}" {t}')
                db.execute("INSERT INTO _columns VALUES (?, ?, ?, ?, ?)", (table, position, c, f, label))
                position += 1
    # Every query filters by store and date, so index them together.
    db.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_shop_date" ON "{table}" ("shop_id", "business_date")')
    for col in ("pos_order_id", "order_id"):
        if any(c == col for c, *_ in columns):
            db.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_{col}" ON "{table}" ("{col}")')
    # The views join order-level tables on (shop_id, pos_order_id); without this the planner
    # can pick the (shop_id, business_date) index and scan a whole store per row.
    if any(c == "pos_order_id" for c, *_ in columns):
        db.execute(f'CREATE INDEX IF NOT EXISTS "ix_{table}_shop_order" ON "{table}" ("shop_id", "pos_order_id")')


def replace_rows(db, table, columns, converted, shop_id, start=None, end=None):
    """Swap in one store's rows: for [start, end] only, or its whole history when no range is given.

    Other stores' rows are never touched, so stores can be exported one at a time.
    """
    ensure_table(db, table, columns)
    if start:
        db.execute(f'DELETE FROM "{table}" WHERE shop_id = ? AND business_date BETWEEN ? AND ?',
                   (shop_id, start.isoformat(), end.isoformat()))
    else:
        db.execute(f'DELETE FROM "{table}" WHERE shop_id = ?', (shop_id,))
    insert(db, table, columns, converted)


def insert(db, table, columns, converted):
    col_list = ", ".join(f'"{c}"' for c, *_ in columns)
    marks = ", ".join("?" for _ in columns)
    db.executemany(f'INSERT INTO "{table}" ({col_list}) VALUES ({marks})',
                   [[r.get(c) for c, *_ in columns] for r in converted])


def table_exists(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()


def dump_csv(db, table, path):
    """Write the whole table (not just this run's rows) with the report's column labels."""
    labels = dict(db.execute("SELECT column_name, label FROM _columns WHERE table_name = ?", (table,)))
    cur = db.execute(f'SELECT * FROM "{table}" ORDER BY business_date, rowid')
    names = [d[0] for d in cur.description]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([labels.get(n, n) for n in names])
        writer.writerows(cur)


def first_business_date(api, shop_id, currency):
    """The store's first business day with data, or None if it has none yet."""
    cfg = next(r for r in REPORTS if r["table"] == "sales_daily")
    filters = build_filters(cfg, date(2000, 1, 1), today(), [shop_id], currency)
    for row in api.query_rows(cfg["report_id"], ["D_businessDate", "M_Order_COUNT_Orders"], filters,
                              [{"D_businessDate": "ASC"}]):
        return date.fromisoformat(row["D_businessDate"]["value"])
    return None


def resolve_shops(api, requested, currency):
    """Stores to export: the given IDs, or every store the account can see ("all" / unset)."""
    want_all = not requested or requested == ["all"]
    try:
        known = {s["shop_id"]: s for s in api.list_shops() if s["currency"] == currency}
    except click.ClickException as e:
        if want_all:
            raise
        click.echo(f"  ดึงรายชื่อสาขาไม่ได้ ({e.message}) ใช้ Store ID ที่ระบุไว้แทน", err=True)
        known = {}
    if want_all:
        if not known:
            raise click.ClickException("บัญชีนี้ไม่เห็นสาขาไหนเลย")
        return list(known.values())
    return [known.get(sid, {"shop_id": sid, "shop_name": None, "currency": currency}) for sid in requested]


SCHEMA = """
    CREATE TABLE IF NOT EXISTS _columns (
        table_name TEXT, position INTEGER, column_name TEXT, field TEXT, label TEXT);
    CREATE TABLE IF NOT EXISTS _exports (
        table_name TEXT, shop_id TEXT, report_id TEXT, report_title TEXT, date_from TEXT, date_to TEXT,
        row_count INTEGER, exported_at TEXT, totals_check TEXT, PRIMARY KEY (table_name, shop_id));
    CREATE TABLE IF NOT EXISTS shops (
        shop_id TEXT PRIMARY KEY, shop_name TEXT, currency TEXT,
        first_business_date TEXT, last_business_date TEXT, updated_at TEXT);
"""


def prepare_db(db):
    # Views are rebuilt at the end of every run; dropping them first means a table rebuild
    # (see retype_columns) never trips over a view that points at it.
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'view'").fetchall():
        db.execute(f'DROP VIEW "{name}"')
    # Databases from before multi-store support kept one _exports row per table.
    cols = [r[1] for r in db.execute("PRAGMA table_info(_exports)")]
    if cols and "shop_id" not in cols:
        db.execute("DROP TABLE _exports")
    db.executescript(SCHEMA)


def create_views(db):
    """Create the cleaned v_* views from views.sql once every table they read exists."""
    if not all(table_exists(db, r["table"]) for r in REPORTS):
        click.echo("ยังไม่ครบทุกตาราง ข้ามการสร้าง view", err=True)
        return
    db.executescript((ROOT / "views.sql").read_text(encoding="utf-8"))
    db.execute("ANALYZE")  # table statistics so SQLite picks good join plans for the views


def update_shops(db, shops):
    now = datetime.now().isoformat(timespec="seconds")
    for s in shops:
        first, last, name = None, None, s["shop_name"]
        if table_exists(db, "sales_daily"):
            first, last, data_name = db.execute(
                "SELECT MIN(business_date), MAX(business_date), MAX(shop_name) FROM sales_daily WHERE shop_id = ?",
                (s["shop_id"],)).fetchone()
            name = name or data_name
        db.execute("""INSERT INTO shops VALUES (?, ?, ?, ?, ?, ?)
                      ON CONFLICT(shop_id) DO UPDATE SET shop_name = COALESCE(excluded.shop_name, shop_name),
                        currency = excluded.currency, first_business_date = excluded.first_business_date,
                        last_business_date = excluded.last_business_date, updated_at = excluded.updated_at""",
                   (s["shop_id"], name, s["currency"], first, last, now))


@click.command()
@click.option("--from", "start", help="วันเริ่ม YYYY-MM-DD (ค่าเริ่มต้น: วันแรกที่ร้านมีข้อมูล)")
@click.option("--to", "end", help="วันสิ้นสุด YYYY-MM-DD (ค่าเริ่มต้น: วันนี้)")
@click.option("--days", type=click.IntRange(min=1),
              help="อัปเดตเฉพาะ N วันล่าสุดในฐานข้อมูลเดิม (สำหรับงานรายวัน) ใช้แทน --from")
@click.option("--shop", "shops", multiple=True,
              help="Store ID (ใส่ซ้ำได้) แทน RESTOSUITE_SHOP_IDS (ค่าเริ่มต้น: ทุกสาขาที่บัญชีเห็น)")
@click.option("--db", "db_path", type=click.Path(dir_okay=False, path_type=Path),
              default=Path("restosuite.db"), show_default=True, help="ไฟล์ SQLite")
@click.option("--csv-dir", type=click.Path(file_okay=False, path_type=Path), help="เขียน CSV ทุกตารางลงโฟลเดอร์นี้ด้วย")
@click.option("--only", multiple=True, type=click.Choice([r["table"] for r in REPORTS]),
              help="เลือกเฉพาะบางตาราง (ใส่ซ้ำได้)")
@click.option("--rebuild", is_flag=True, help="ลบตารางแล้วสร้างใหม่ทั้งหมด (ทุกสาขา)")
@click.option("--currency", default="THB", show_default=True)
def main(start, end, days, shops, db_path, csv_dir, only, rebuild, currency):
    """Export the RestoSuite Common Reports into a SQLite database."""
    if days and start:
        raise click.UsageError("ใช้ --days กับ --from พร้อมกันไม่ได้")
    load_dotenv(ROOT / ".env")
    api = RestoSuite(require_env("RESTOSUITE_TOKEN"))
    requested = list(shops) or [s.strip() for s in os.environ.get("RESTOSUITE_SHOP_IDS", "all").split(",")
                                if s.strip()]
    targets = resolve_shops(api, requested, currency)

    end_d = date.fromisoformat(end) if end else today()
    db = sqlite3.connect(db_path)
    prepare_db(db)
    in_db = set()
    if table_exists(db, "sales_daily") and not rebuild:
        in_db = {r[0] for r in db.execute("SELECT DISTINCT shop_id FROM sales_daily")}

    # Per store: (start, whether only that range is replaced). Without --from/--days a store's
    # whole history is fetched again and replaces what the database has for it. A store that is
    # new to the database gets its whole history even in --days mode, so a newly opened or newly
    # granted branch arrives complete on the next daily run.
    ranges = {}
    for s in targets:
        if days and s["shop_id"] in in_db:
            ranges[s["shop_id"]] = (end_d - timedelta(days=days - 1), True)
        elif start:
            ranges[s["shop_id"]] = (date.fromisoformat(start), True)
        else:
            api.use_shop(s["shop_id"])
            first = first_business_date(api, s["shop_id"], currency)
            if first:
                ranges[s["shop_id"]] = (first, False)
        label = f"{s['shop_name'] or s['shop_id']} ({s['shop_id']})"
        if s["shop_id"] in ranges:
            click.echo(f"สาขา {label}: {ranges[s['shop_id']][0]} ถึง {end_d}", err=True)
        else:
            click.echo(f"สาขา {label}: ยังไม่มีข้อมูลยอดขาย ข้าม", err=True)
    targets = [s for s in targets if s["shop_id"] in ranges]

    if rebuild:
        for cfg in REPORTS:
            if not only or cfg["table"] in only:
                db.execute(f'DROP TABLE IF EXISTS "{cfg["table"]}"')
                db.execute("DELETE FROM _columns WHERE table_name = ?", (cfg["table"],))
                db.execute("DELETE FROM _exports WHERE table_name = ?", (cfg["table"],))
        db.commit()
    if csv_dir:
        csv_dir.mkdir(parents=True, exist_ok=True)

    problems = []
    for cfg in REPORTS:
        table = cfg["table"]
        if only and table not in only:
            continue
        click.echo(f"[{table}] {cfg['title']} (report {cfg['report_id']})", err=True)
        labels = api.field_labels(cfg["report_id"])
        names = column_names(cfg["fields"])
        for s in targets:
            shop_id = s["shop_id"]
            start_d, windowed = ranges[shop_id]
            api.use_shop(shop_id)
            rows = fetch_report(api, cfg, start_d, end_d, [shop_id], currency)
            columns, converted = convert_rows(cfg, labels, rows)
            replace_rows(db, table, columns, converted, shop_id, *((start_d, end_d) if windowed else ()))

            # Compare our sums with the totals RestoSuite computes for the same store and range.
            expected = api.query_totals(cfg["report_id"], cfg["totals"],
                                        build_filters(cfg, start_d, end_d, [shop_id], currency))
            check = {}
            for m in cfg["totals"]:
                got = sum(Decimal(str(r[names[m]])) for r in converted if r[names[m]] is not None)
                want = Decimal(expected.get(m) or "0")
                check[m] = {"expected": str(want), "exported": str(got), "ok": got == want}
                if got != want:
                    problems.append(f"{table}.{names[m]} ({shop_id}): RestoSuite {want} แต่ได้ {got}")
            # What the table holds for this store, which can reach further back than this run.
            first_in_db, row_count = db.execute(
                f'SELECT MIN(business_date), COUNT(*) FROM "{table}" WHERE shop_id = ?', (shop_id,)).fetchone()
            date_from = min(first_in_db, start_d.isoformat()) if first_in_db else start_d.isoformat()
            db.execute("INSERT OR REPLACE INTO _exports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (table, shop_id, cfg["report_id"], cfg["title"], date_from, end_d.isoformat(), row_count,
                        datetime.now().isoformat(timespec="seconds"), json.dumps(check)))
            db.commit()
            status = "ตรง" if all(c["ok"] for c in check.values()) else "ไม่ตรง!"
            click.echo(f"  {s['shop_name'] or shop_id}: {len(converted)} แถว (ทั้งหมดของสาขา {row_count}), "
                       f"ยอดรวมเทียบกับ RestoSuite: {status}", err=True)
        if csv_dir and table_exists(db, table):
            dump_csv(db, table, csv_dir / f"{table}.csv")
    update_shops(db, targets)
    db.commit()
    create_views(db)
    db.commit()
    db.close()

    click.echo(f"บันทึกลง {db_path}" + (f" และ CSV ใน {csv_dir}" if csv_dir else ""), err=True)
    if problems:
        click.echo("ยอดรวมไม่ตรง:\n  " + "\n  ".join(problems), err=True)
        sys.exit(1)


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8")
    main()
