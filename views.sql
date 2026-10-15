-- Cleaned views for dashboards and BI tools (Power BI, Excel, SQL).
-- export_all.py drops and recreates them on every run, so edit this file, not the database.
--
-- What they add on top of the raw report tables:
--   channel        sales channel, from how the order was placed and paid (dining_option is
--                  "In Store Dining" for almost every order, delivery included, so it is not used)
--   shift_label    the POS shift names (一班..六班) in Thai with their time range
--   order_kind     ขาย (sale) / คืนเงิน (refund, negative net) / ยกเลิก-0 บาท (void or zero bill)
--   is_test        1 when the order was paid with the TEST payer, 0 otherwise
--   opened_time / pay_end_time always as "YYYY-MM-DD HH:MM:SS" (some rows arrive without seconds)
--   is_complete_day in v_sales_daily: 0 for today (Bangkok time), whose sales are still coming in
--
-- The guests column is left out: the POS records 1 guest for nearly every bill, so it is not a
-- real customer count. Order counts that match RestoSuite come from v_sales_daily.orders.

-- Map POS shift codes to readable labels. Unknown codes fall through unchanged.
CREATE VIEW v_shift_labels AS
          SELECT '一班' AS code, 1 AS shift_no, 'กะ 1 (09:00–10:00)' AS shift_label
UNION ALL SELECT '二班', 2, 'กะ 2 (10:00–11:00)'
UNION ALL SELECT '三班', 3, 'กะ 3 (11:00–14:00)'
UNION ALL SELECT '四班', 4, 'กะ 4 (14:00–17:00)'
UNION ALL SELECT '五班', 5, 'กะ 5 (17:00–21:00)'
UNION ALL SELECT '六班', 6, 'กะ 6 (21:00–ปิดร้าน)';

-- One sales channel per order. An order with several payments takes the most specific one.
-- Correlated EXISTS lookups (served by the pos_order_id index) instead of GROUP BY, so SQLite
-- can fold this view into the queries that join it rather than re-aggregating per row.
CREATE VIEW v_order_channel AS
SELECT o.shop_id, o.pos_order_id,
       CASE
           WHEN o.source = 'Online Ordering-H5' THEN 'สั่งออนไลน์ (H5)'
           WHEN EXISTS (SELECT 1 FROM payments p WHERE p.pos_order_id = o.pos_order_id
                        AND p.shop_id = o.shop_id AND p.payer_type = 'lineman') THEN 'LINE MAN'
           WHEN EXISTS (SELECT 1 FROM payments p WHERE p.pos_order_id = o.pos_order_id
                        AND p.shop_id = o.shop_id AND p.payer_type = 'Delivery') THEN 'Delivery'
           WHEN EXISTS (SELECT 1 FROM payments p WHERE p.pos_order_id = o.pos_order_id
                        AND p.shop_id = o.shop_id AND p.payer_type = 'VIP/KOL') THEN 'VIP/KOL'
           ELSE 'หน้าร้าน'
       END AS channel,
       EXISTS (SELECT 1 FROM payments p WHERE p.pos_order_id = o.pos_order_id
               AND p.shop_id = o.shop_id AND p.payer_type = 'TEST') AS is_test
FROM orders o;

CREATE VIEW v_orders AS
SELECT o.business_date, o.shop_id, s.shop_name, o.pos_order_id, o.order_id,
       CASE WHEN length(o.opened_time) = 16 THEN o.opened_time || ':00' ELSE o.opened_time END AS opened_time,
       CAST(substr(o.opened_time, 12, 2) AS INTEGER) AS opened_hour,
       c.channel, o.source,
       o.start_cashier_rotas AS shift_code, COALESCE(l.shift_label, o.start_cashier_rotas) AS shift_label,
       CASE WHEN o.net_sales < 0 THEN 'คืนเงิน' WHEN o.net_sales = 0 THEN 'ยกเลิก-0 บาท' ELSE 'ขาย' END AS order_kind,
       c.is_test,
       o.tag_exception_identifier AS exceptions,
       o.net_sales, o.receivable_sales, o.receivable_sales - o.net_sales AS discount_amount,
       o.total_gross_sales, o.food_origin_amount, o.surcharge, o.tax, o.tips
FROM orders o
JOIN v_order_channel c ON c.shop_id = o.shop_id AND c.pos_order_id = o.pos_order_id
LEFT JOIN v_shift_labels l ON l.code = o.start_cashier_rotas
LEFT JOIN shops s ON s.shop_id = o.shop_id;

CREATE VIEW v_order_items AS
SELECT i.business_date, i.shop_id, s.shop_name, i.pos_order_id,
       i.item_code, i.item_name,
       CASE WHEN i.category = 'Toppings Toppings' THEN 'Toppings' ELSE i.category END AS category,
       i.unit, CAST(i.item_price AS REAL) AS item_price, i.item_attributes,
       c.channel, c.is_test,
       i.net_qty, i.net_sales, i.gross_sales, i.discount_prom,
       i.refund_qty, i.refund_amount, i.present_qty, i.present_amount
FROM order_items i
LEFT JOIN v_order_channel c ON c.shop_id = i.shop_id AND c.pos_order_id = i.pos_order_id
LEFT JOIN shops s ON s.shop_id = i.shop_id;

CREATE VIEW v_payments AS
SELECT p.business_date, p.shop_id, s.shop_name, p.pos_order_id,
       CASE WHEN length(p.pay_end_time) = 16 THEN p.pay_end_time || ':00' ELSE p.pay_end_time END AS pay_end_time,
       CASE p.payer_type
           WHEN 'lineman' THEN 'LINE MAN'
           WHEN 'master' THEN 'Mastercard'
           WHEN 'Union pay' THEN 'UnionPay'
           ELSE p.payer_type
       END AS payment_method,
       p.payment_type, c.channel, (p.payer_type = 'TEST') AS is_test,
       p.count, p.net_payment_amount, p.merchant_receive_amount, p.refund_amount
FROM payments p
LEFT JOIN v_order_channel c ON c.shop_id = p.shop_id AND c.pos_order_id = p.pos_order_id
LEFT JOIN shops s ON s.shop_id = p.shop_id;

CREATE VIEW v_discounts AS
SELECT d.business_date, d.shop_id, s.shop_name, d.pos_order_id,
       CASE d.discount_promotion_name WHEN '买一送一' THEN 'ซื้อ 1 แถม 1' ELSE d.discount_promotion_name END
           AS discount_name,
       d.discount_promotion_sub_type AS discount_type, d.promotion_sub_type,
       NULLIF(trim(d.reason), '') AS reason, d.applied_by_code_and_name AS applied_by,
       d.approved_by_code_and_name AS approved_by,
       d.amount, d.total_gross_sales
FROM discounts d
LEFT JOIN shops s ON s.shop_id = d.shop_id;

-- Daily totals as RestoSuite reports them, plus how much of each day came from TEST payments.
CREATE VIEW v_sales_daily AS
SELECT d.business_date, d.shop_id, s.shop_name,
       (d.business_date < date('now', '+7 hours')) AS is_complete_day,
       d.orders, d.net_sales, d.total_promotion_amount AS discount_amount,
       d.receivable_sales, d.total_gross_sales, d.net_sales_by_order AS avg_order_value,
       COALESCE(t.test_sales, 0) AS test_sales,
       d.net_sales - COALESCE(t.test_sales, 0) AS net_sales_excl_test
FROM sales_daily d
LEFT JOIN shops s ON s.shop_id = d.shop_id
LEFT JOIN (SELECT shop_id, business_date, SUM(net_payment_amount) AS test_sales
           FROM payments WHERE payer_type = 'TEST' GROUP BY 1, 2) t
       ON t.shop_id = d.shop_id AND t.business_date = d.business_date;
