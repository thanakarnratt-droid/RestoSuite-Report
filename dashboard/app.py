"""Sales dashboard over restosuite.db (built by export_all.py).

One page per RestoSuite Common Report plus an overview, all filtered by a
business-date range. Read-only: it never writes to the database, so it can run
while the daily export updates it.

Settings (.env in the repository root, or environment):

    DASHBOARD_PASSWORD_HASH   required; set with: python dashboard/app.py set-password
    DASHBOARD_SECRET_KEY      session signing key (set-password creates one)
    RESTOSUITE_DB             database path (default: restosuite.db next to export_all.py)
    DASHBOARD_SECURE_COOKIE   "true" when served over HTTPS (default true)

Run locally:  python dashboard/app.py            (http://127.0.0.1:5021)
Production:   gunicorn --preload -b 127.0.0.1:5021 dashboard.app:app (see dashboard/Dockerfile)
"""
import csv
import io
import math
import os
import secrets
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import (Flask, Response, abort, g, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from restosuite_orders import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("DASHBOARD_SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("DASHBOARD_SECURE_COOKIE", "true").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
DB_PATH = Path(os.environ.get("RESTOSUITE_DB") or ROOT / "restosuite.db")
PAGE_SIZE = 50

# Navigation: (endpoint key, Thai title, RestoSuite report name)
PAGES = [
    ("overview", "ภาพรวม", "Overview"),
    ("orders", "ออเดอร์", "Orders"),
    ("sales", "สรุปยอดขาย", "Sales Summary Report"),
    ("items", "สินค้า", "Items Breakdown"),
    ("payments", "รายการชำระเงิน", "Payments Detail"),
    ("payment-mix", "ช่องทางชำระเงิน", "Payments Breakdown"),
    ("discounts", "รายการส่วนลด", "Discount Detail List"),
    ("promotions", "ส่วนลดและโปรโมชั่น", "Discount & Prom"),
]


# --- database -----------------------------------------------------------------

def db():
    if "db" not in g:
        if not DB_PATH.exists():
            abort(503, f"ไม่พบฐานข้อมูล {DB_PATH} ให้รัน export_all.py ก่อน")
        g.db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def q(sql, params=()):
    return db().execute(sql, params).fetchall()


def q1(sql, params=()):
    row = db().execute(sql, params).fetchone()
    return row[0] if row else None


def labels_for(table):
    return {r["column_name"]: r["label"] for r in q("SELECT column_name, label FROM _columns WHERE table_name = ?",
                                                     (table,))}


# --- auth ---------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("ok"):
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        pw_hash = os.environ.get("DASHBOARD_PASSWORD_HASH", "")
        if pw_hash and check_password_hash(pw_hash, request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["ok"] = True
            nxt = request.args.get("next", "")
            # Only follow local paths, never an absolute URL from the query string.
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("overview"))
        time.sleep(1)  # slow down password guessing
        error = "รหัสผ่านไม่ถูกต้อง" if pw_hash else "ยังไม่ได้ตั้ง DASHBOARD_PASSWORD_HASH"
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# --- filters ------------------------------------------------------------------

BANGKOK = timezone(timedelta(hours=7))  # no daylight saving in Thailand


def store_today():
    return datetime.now(BANGKOK).date()


def last_complete_day():
    """The latest business day that has finished: today's sales are still coming in."""
    scope, sp = shop_scope()
    last = q1(f"SELECT MAX(business_date) FROM sales_daily{scope} {'AND' if scope else 'WHERE'} business_date < ?",
              (*sp, store_today().isoformat()))
    return date.fromisoformat(last) if last else store_today() - timedelta(days=1)


def date_range():
    """(start, end) from ?from=&to=, defaulting to the 30 days up to the last finished day."""
    try:
        end = date.fromisoformat(request.args["to"]) if request.args.get("to") else last_complete_day()
        start = date.fromisoformat(request.args["from"]) if request.args.get("from") else end - timedelta(days=29)
    except ValueError:
        abort(400, "วันที่ไม่ถูกต้อง")
    if start > end:
        start, end = end, start
    return start, end


def prev_range(start, end):
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


def page_context(key, start, end, **extra):
    scope, sp = shop_scope()
    first = q1(f"SELECT MIN(business_date) FROM sales_daily{scope}", sp)
    last = q1(f"SELECT MAX(business_date) FROM sales_daily{scope}", sp)
    exported = q1(f"SELECT MAX(exported_at) FROM _exports{scope if 'shop_id' in export_cols() else ''}",
                  sp if "shop_id" in export_cols() else ())
    title = next(t for k, t, _ in PAGES if k == key)
    report = next(r for k, _, r in PAGES if k == key)
    shop = selected_shop()
    specs = list(CHART_SPECS.get(key, []))
    if key == "overview" and len(shops()) > 1 and not shop:
        specs.insert(1, ("by_shop", "ยอดขายสุทธิตามสาขา", "hbar", "money"))
    today = store_today()
    return dict(pages=PAGES, active=key, title=title, report=report, specs=specs, shops=shops(), shop=shop,
                shop_name=dict(shops()).get(shop) if shop else None,
                start=start.isoformat(), end=end.isoformat(), first=first, last=last,
                last_complete=last_complete_day().isoformat(), includes_today=start <= today <= end,
                exported=exported, **extra)


def export_cols():
    return [r[1] for r in q("PRAGMA table_info(_exports)")]


def table_page(table, where, params, order, columns=None, search_col=None):
    """Rows for a paginated table plus paging info."""
    labels = labels_for(table)
    # Store name only matters when several stores are shown together.
    hidden = {"shop_id", "shop_code", "guests", "net_sales_by_guest"} | (
        {"shop_name"} if selected_shop() or len(shops()) < 2 else set())
    cols = [c for c in (columns or [c for c in labels if not c.endswith("_code")]) if c not in hidden]
    search = request.args.get("q", "").strip()
    if search and search_col:
        where += f' AND "{search_col}" LIKE ?'
        params = (*params, f"%{search}%")
    total = q1(f'SELECT COUNT(*) FROM "{table}" WHERE {where}', params)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = min(max(1, request.args.get("page", 1, type=int)), pages)
    rows = q(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}" WHERE {where} '
             f'ORDER BY {order} LIMIT ? OFFSET ?', (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE))
    return dict(cols=[(c, labels.get(c, c)) for c in cols], rows=rows, total=total, page=page, pages=pages,
                search=search, search_col=search_col, table=table)


def shops():
    """Stores that have data: [(shop_id, shop_name)], named from the shops table when it exists."""
    if "shops" not in g:
        names = {}
        if q1("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'shops'"):
            names = {r["shop_id"]: r["shop_name"] for r in q("SELECT shop_id, shop_name FROM shops")}
        g.shops = [(r["shop_id"], names.get(r["shop_id"]) or r["name"] or r["shop_id"])
                   for r in q("SELECT shop_id, MAX(shop_name) AS name FROM sales_daily GROUP BY shop_id ORDER BY name")]
    return g.shops


def selected_shop():
    """The store picked in ?shop=, or None for all stores."""
    shop = request.args.get("shop", "")
    return shop if shop in dict(shops()) else None


def where(start, end):
    """SQL condition + params for the chosen date range and store."""
    sql, params = "business_date BETWEEN ? AND ?", [start.isoformat(), end.isoformat()]
    shop = selected_shop()
    if shop:
        sql += " AND shop_id = ?"
        params.append(shop)
    return sql, tuple(params)


def shop_scope():
    shop = selected_shop()
    return (" WHERE shop_id = ?", (shop,)) if shop else ("", ())

# Charts per page: (data key, title, "bar" columns or "hbar" ranked bars, "money" or "count")
CHART_SPECS = {
    "overview": [("daily", "ยอดขายสุทธิรายวัน", "bar", "money"),
                 ("hourly", "ยอดขายสุทธิตามชั่วโมงที่เปิดบิล", "bar", "money"),
                 ("mix", "ยอดชำระตามช่องทาง", "hbar", "money"),
                 ("top", "สินค้าขายดี 10 อันดับ (ยอดขายสุทธิ)", "hbar", "money")],
    "orders": [("hourly", "จำนวนออเดอร์ตามชั่วโมงที่เปิดบิล", "bar", "count"),
               ("dining", "จำนวนออเดอร์ตามประเภทการรับประทาน", "hbar", "count")],
    "sales": [("daily", "ยอดขายสุทธิรายวัน", "bar", "money"),
              ("orders", "จำนวนออเดอร์รายวัน", "bar", "count")],
    "items": [("top_qty", "สินค้าขายดี 15 อันดับ (จำนวน)", "hbar", "count"),
              ("category", "ยอดขายสุทธิตามหมวดหมู่", "hbar", "money")],
    "payments": [("count", "จำนวนรายการตามช่องทางชำระเงิน", "hbar", "count")],
    "payment-mix": [("amount", "ยอดชำระสุทธิตามช่องทาง", "hbar", "money")],
    "discounts": [("daily", "ยอดส่วนลดรายวัน", "bar", "money")],
    "promotions": [("amount", "ยอดส่วนลดตามรายการส่วนลด/โปรโมชั่น", "hbar", "money")],
}


def series(rows, key, value):
    return {"labels": [r[key] if r[key] is not None else "-" for r in rows], "values": [r[value] or 0 for r in rows]}


def hourly(start, end):
    w, p = where(start, end)
    rows = q(f"""SELECT CAST(substr(opened_time, 12, 2) AS INTEGER) AS h, COUNT(*) AS n, SUM(net_sales) AS s
                 FROM orders WHERE {w} AND opened_time IS NOT NULL GROUP BY h ORDER BY h""", p)
    by_h = {r["h"]: r for r in rows}
    hours = range(min(by_h, default=10), max(by_h, default=22) + 1)
    return {"labels": [f"{h:02d}:00" for h in hours],
            "orders": [by_h[h]["n"] if h in by_h else 0 for h in hours],
            "sales": [by_h[h]["s"] if h in by_h else 0 for h in hours]}


def daily_sales(start, end):
    w, p = where(start, end)
    return q(f"""SELECT business_date AS d, SUM(net_sales) AS net, SUM(orders) AS orders
                 FROM sales_daily WHERE {w} GROUP BY d ORDER BY d""", p)


def kpis(start, end):
    # No guest count: the POS records one guest per bill, so it would just repeat the order count.
    w, p = where(start, end)
    row = db().execute(f"""SELECT COALESCE(SUM(net_sales), 0) AS net, COALESCE(SUM(orders), 0) AS orders,
                                  COALESCE(SUM(total_gross_sales), 0) AS gross
                           FROM sales_daily WHERE {w}""", p).fetchone()
    disc = q1(f"SELECT COALESCE(SUM(amount), 0) FROM discounts_daily WHERE {w}", p)
    items = q1(f"SELECT COALESCE(SUM(net_qty), 0) FROM order_items WHERE {w}", p)
    days = q1(f"SELECT COUNT(DISTINCT business_date) FROM sales_daily WHERE {w} AND orders > 0", p) or 0
    return {"net": row["net"], "orders": row["orders"], "items_sold": items, "gross": row["gross"],
            "discount": disc, "avg_order": row["net"] / row["orders"] if row["orders"] else 0,
            "per_day": row["net"] / days if days else 0, "days": days}


# --- pages --------------------------------------------------------------------

@app.route("/")
@login_required
def overview():
    start, end = date_range()
    w, p = where(start, end)
    cur, prev = kpis(start, end), kpis(*prev_range(start, end))
    daily = daily_sales(start, end)
    mix = q(f"""SELECT COALESCE(payer_type, payment_type) AS k, SUM(net_payment_amount) AS v
                FROM payments_daily WHERE {w} GROUP BY k ORDER BY v DESC""", p)
    top = q(f"""SELECT item_name AS k, SUM(net_sales) AS v FROM order_items WHERE {w}
                GROUP BY k ORDER BY v DESC LIMIT 10""", p)
    h = hourly(start, end)
    charts = {"daily": series(daily, "d", "net"), "hourly": {"labels": h["labels"], "values": h["sales"]},
              "mix": series(mix, "k", "v"), "top": series(top, "k", "v")}
    if len(shops()) > 1 and not selected_shop():
        names = dict(shops())
        by_shop = q(f"""SELECT shop_id AS k, SUM(net_sales) AS v FROM sales_daily WHERE {w}
                        GROUP BY k ORDER BY v DESC""", p)
        charts["by_shop"] = {"labels": [names.get(r["k"], r["k"]) for r in by_shop],
                             "values": [r["v"] or 0 for r in by_shop]}
    return render_template("overview.html", cur=cur, prev=prev, charts=charts,
                           **page_context("overview", start, end))


@app.route("/orders")
@login_required
def orders():
    start, end = date_range()
    w, p = where(start, end)
    dining = q(f"""SELECT dining_option AS k, COUNT(*) AS v FROM orders WHERE {w}
                   GROUP BY k ORDER BY v DESC""", p)
    h = hourly(start, end)
    charts = {"hourly": {"labels": h["labels"], "values": h["orders"]}, "dining": series(dining, "k", "v")}
    tbl = table_page("orders", w, p, "business_date DESC, opened_time DESC", search_col="pos_order_id")
    return render_template("report.html", charts=charts, tbl=tbl, kind="orders",
                           summary=kpis(start, end), **page_context("orders", start, end))


@app.route("/sales")
@login_required
def sales():
    start, end = date_range()
    w, p = where(start, end)
    daily = daily_sales(start, end)
    charts = {"daily": series(daily, "d", "net"), "orders": series(daily, "d", "orders")}
    tbl = table_page("sales_daily", w, p, "business_date DESC")
    return render_template("report.html", charts=charts, tbl=tbl, kind="sales",
                           summary=kpis(start, end), **page_context("sales", start, end))


@app.route("/items")
@login_required
def items():
    start, end = date_range()
    w, p = where(start, end)
    by_item = q(f"""SELECT item_name, category, SUM(net_qty) AS net_qty, SUM(net_sales) AS net_sales,
                           SUM(gross_sales) AS gross_sales, SUM(discount_prom) AS discount_prom,
                           SUM(refund_qty) AS refund_qty, SUM(present_qty) AS present_qty
                    FROM order_items WHERE {w} GROUP BY item_name, category ORDER BY net_sales DESC""", p)
    by_cat = q(f"""SELECT category AS k, SUM(net_sales) AS v FROM order_items WHERE {w}
                   GROUP BY k ORDER BY v DESC""", p)
    top_qty = sorted(by_item, key=lambda r: r["net_qty"] or 0, reverse=True)[:15]
    charts = {"top_qty": series(top_qty, "item_name", "net_qty"), "category": series(by_cat, "k", "v")}
    labels = labels_for("order_items")
    cols = ["item_name", "category", "net_qty", "net_sales", "gross_sales", "discount_prom", "refund_qty",
            "present_qty"]
    agg = dict(cols=[(c, labels.get(c, c)) for c in cols], rows=by_item)
    return render_template("report.html", charts=charts, agg=agg, kind="items",
                           **page_context("items", start, end))


@app.route("/payments")
@login_required
def payments():
    start, end = date_range()
    w, p = where(start, end)
    tbl = table_page("payments", w, p, "business_date DESC, pay_end_time DESC", search_col="pos_order_id")
    by_type = q(f"""SELECT COALESCE(payer_type, payment_type) AS k, COUNT(*) AS v FROM payments WHERE {w}
                    GROUP BY k ORDER BY v DESC""", p)
    charts = {"count": series(by_type, "k", "v")}
    return render_template("report.html", charts=charts, tbl=tbl, kind="payments",
                           **page_context("payments", start, end))


@app.route("/payment-mix")
@login_required
def payment_mix():
    start, end = date_range()
    w, p = where(start, end)
    rows = q(f"""SELECT payment_type, payer_type, SUM(count) AS count, SUM(refund_amount) AS refund_amount,
                        SUM(net_payment_amount) AS net_payment_amount,
                        SUM(merchant_receive_amount) AS merchant_receive_amount
                 FROM payments_daily WHERE {w} GROUP BY payment_type, payer_type
                 ORDER BY net_payment_amount DESC""", p)
    by_type = q(f"""SELECT COALESCE(payer_type, payment_type) AS k, SUM(net_payment_amount) AS v
                    FROM payments_daily WHERE {w} GROUP BY k ORDER BY v DESC""", p)
    charts = {"amount": series(by_type, "k", "v")}
    labels = labels_for("payments_daily")
    cols = ["payment_type", "payer_type", "count", "net_payment_amount", "merchant_receive_amount",
            "refund_amount"]
    agg = dict(cols=[(c, labels.get(c, c)) for c in cols], rows=rows)
    return render_template("report.html", charts=charts, agg=agg, kind="payment-mix",
                           **page_context("payment-mix", start, end))


@app.route("/discounts")
@login_required
def discounts():
    start, end = date_range()
    w, p = where(start, end)
    tbl = table_page("discounts", w, p, "business_date DESC, pos_order_id DESC", search_col="pos_order_id",
                     columns=["business_date", "shop_name", "pos_order_id", "discount_promotion_name", "discount_promotion_sub_type",
                              "promotion_sub_type", "reason", "applied_by_code_and_name",
                              "approved_by_code_and_name", "amount", "total_gross_sales"])
    daily = q(f"""SELECT business_date AS k, SUM(amount) AS v FROM discounts WHERE {w}
                  GROUP BY k ORDER BY k""", p)
    charts = {"daily": series(daily, "k", "v")}
    return render_template("report.html", charts=charts, tbl=tbl, kind="discounts",
                           **page_context("discounts", start, end))


@app.route("/promotions")
@login_required
def promotions():
    start, end = date_range()
    w, p = where(start, end)
    rows = q(f"""SELECT discount_promotion_name, discount_promotion_sub_type, SUM(count) AS count,
                        SUM(count_order) AS count_order, SUM(amount) AS amount,
                        SUM(total_gross_sales) AS total_gross_sales
                 FROM discounts_daily WHERE {w} GROUP BY discount_promotion_name, discount_promotion_sub_type
                 ORDER BY amount DESC""", p)
    charts = {"amount": series(rows, "discount_promotion_name", "amount")}
    labels = labels_for("discounts_daily")
    cols = ["discount_promotion_name", "discount_promotion_sub_type", "count", "count_order", "amount",
            "total_gross_sales"]
    agg = dict(cols=[(c, labels.get(c, c)) for c in cols], rows=rows)
    return render_template("report.html", charts=charts, agg=agg, kind="promotions",
                           **page_context("promotions", start, end))


DOWNLOADS = {"orders", "order_items", "payments", "payments_daily", "discounts", "discounts_daily", "sales_daily"}


@app.route("/download/<table>.csv")
@login_required
def download(table):
    if table not in DOWNLOADS:
        abort(404)
    start, end = date_range()
    labels = labels_for(table)
    w, p = where(start, end)
    cur = db().execute(f'SELECT * FROM "{table}" WHERE {w} ORDER BY business_date, rowid', p)
    names = [d[0] for d in cur.description]
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel reads Thai correctly
    writer = csv.writer(buf)
    writer.writerow([labels.get(n, n) for n in names])
    writer.writerows(cur)
    return Response(buf.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{table}-{selected_shop() or "all"}-{start}_{end}.csv"'})


# --- template helpers -----------------------------------------------------------

MONEY_COLS = {"net_sales", "gross_sales", "discount_prom", "refund_amount", "net_payment_amount",
              "merchant_receive_amount", "amount", "total_gross_sales", "receivable_sales", "food_origin_amount",
              "excluded_revenue_surcharge", "included_revenue_surcharge", "surcharge", "tax", "tips",
              "present_amount", "total_promotion_amount", "rounding_amount", "net_sales_by_order",
              "net_sales_by_guest", "driving_amount", "item_price"}


@app.template_filter("cell")
def cell(value, col):
    if value is None:
        return "–"
    if isinstance(value, (int, float)):
        if col in MONEY_COLS:
            return f"฿{value:,.2f}"
        return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
    return value


@app.template_filter("baht")
def baht(value, digits=0):
    return f"฿{(value or 0):,.{digits}f}"


@app.template_filter("num")
def num(value):
    return f"{(value or 0):,.0f}"


@app.template_global()
def delta(cur, prev):
    """Percent change vs the previous period, or None when there is nothing to compare."""
    if not prev:
        return None
    return (cur - prev) / prev * 100


@app.template_global()
def page_url(**changes):
    args = request.args.to_dict()
    args.update({k: v for k, v in changes.items() if v is not None})
    return url_for(request.endpoint, **args)


def set_env(path, key, value):
    """Replace or append KEY=value in a .env file."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    lines = [line for line in lines if not line.startswith(key + "=")] + [f"{key}={value}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_password():
    """Ask for a password and store its hash (plus a session key, if missing) in .env."""
    import getpass
    pw = getpass.getpass("รหัสผ่าน dashboard ใหม่: ")
    if len(pw) < 10:
        sys.exit("รหัสผ่านต้องยาวอย่างน้อย 10 ตัวอักษร")
    if pw != getpass.getpass("ยืนยันรหัสผ่าน: "):
        sys.exit("รหัสผ่านไม่ตรงกัน")
    env = ROOT / ".env"
    set_env(env, "DASHBOARD_PASSWORD_HASH", generate_password_hash(pw))
    if not os.environ.get("DASHBOARD_SECRET_KEY"):
        set_env(env, "DASHBOARD_SECRET_KEY", secrets.token_hex(32))
    env.chmod(0o600)
    print(f"บันทึกลง {env} แล้ว ให้ restart dashboard เพื่อใช้รหัสผ่านใหม่")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "set-password":
        set_password()
        return
    app.config["SESSION_COOKIE_SECURE"] = False  # local http
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5021)), debug=os.environ.get("FLASK_DEBUG") == "1")


if __name__ == "__main__":
    main()
