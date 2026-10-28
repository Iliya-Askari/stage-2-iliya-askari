CREATE SCHEMA IF NOT EXISTS olist;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS factory;

CREATE TABLE IF NOT EXISTS olist.customers (
 customer_id text PRIMARY KEY, customer_unique_id text NOT NULL,
 zip_prefix char(5), city text, state char(2)
);
CREATE TABLE IF NOT EXISTS olist.sellers (
 seller_id text PRIMARY KEY, zip_prefix char(5), city text, state char(2)
);
CREATE TABLE IF NOT EXISTS olist.products (
 product_id text PRIMARY KEY, category_name text,
 name_length smallint CHECK(name_length >= 0), description_length integer CHECK(description_length >= 0),
 photos_qty smallint CHECK(photos_qty >= 0), weight_g integer CHECK(weight_g >= 0),
 length_cm smallint CHECK(length_cm >= 0), height_cm smallint CHECK(height_cm >= 0), width_cm smallint CHECK(width_cm >= 0)
);
CREATE TABLE IF NOT EXISTS olist.category_translation (category_name text PRIMARY KEY, category_name_english text NOT NULL);
CREATE TABLE IF NOT EXISTS olist.orders (
 order_id text PRIMARY KEY, customer_id text NOT NULL REFERENCES olist.customers,
 status text NOT NULL, purchase_at timestamp without time zone, approved_at timestamp without time zone,
 carrier_at timestamp without time zone, delivered_at timestamp without time zone,
 estimated_delivery_at timestamp without time zone,
 CHECK(delivered_at IS NULL OR purchase_at IS NULL OR delivered_at >= purchase_at)
);
CREATE TABLE IF NOT EXISTS olist.order_items (
 order_id text NOT NULL REFERENCES olist.orders, item_number smallint NOT NULL CHECK(item_number > 0),
 product_id text REFERENCES olist.products, seller_id text REFERENCES olist.sellers,
 shipping_limit_at timestamp without time zone, price numeric(12,2) NOT NULL CHECK(price >= 0),
 freight_value numeric(12,2) NOT NULL CHECK(freight_value >= 0), PRIMARY KEY(order_id,item_number)
);
CREATE TABLE IF NOT EXISTS olist.payments (
 order_id text NOT NULL REFERENCES olist.orders, sequence smallint NOT NULL CHECK(sequence > 0),
 payment_type text, installments smallint CHECK(installments >= 0), value numeric(12,2) NOT NULL CHECK(value >= 0),
 PRIMARY KEY(order_id,sequence)
);
CREATE TABLE IF NOT EXISTS olist.reviews (
 review_id text NOT NULL, order_id text NOT NULL REFERENCES olist.orders,
 score smallint CHECK(score BETWEEN 1 AND 5), created_at timestamp without time zone,
 answered_at timestamp without time zone,
 title text, message text, PRIMARY KEY(review_id,order_id)
);
CREATE TABLE IF NOT EXISTS olist.geolocation (
 zip_prefix char(5) NOT NULL, lat double precision, lon double precision,
 city text, state char(2), CHECK(lat IS NULL OR lat BETWEEN -90 AND 90),
 CHECK(lon IS NULL OR lon BETWEEN -180 AND 180)
);

CREATE OR REPLACE VIEW analytics.v_order_delivery AS
SELECT o.order_id, date_trunc('month', o.purchase_at)::date AS order_month,
       c.state AS customer_state, o.delivered_at, o.estimated_delivery_at,
       (o.delivered_at > o.estimated_delivery_at) AS is_late
FROM olist.orders o JOIN olist.customers c USING(customer_id);
CREATE OR REPLACE VIEW analytics.v_item_sales AS
SELECT date_trunc('month', o.purchase_at)::date AS month,
       COALESCE(t.category_name_english, p.category_name, 'unknown') AS category,
       SUM(i.price) AS sales_value, COUNT(DISTINCT o.order_id) AS orders,
       SUM(i.price)/NULLIF(COUNT(DISTINCT o.order_id),0) AS revenue_per_order
FROM olist.order_items i JOIN olist.orders o USING(order_id)
LEFT JOIN olist.products p USING(product_id)
LEFT JOIN olist.category_translation t USING(category_name)
WHERE o.purchase_at IS NOT NULL
GROUP BY 1,2;

CREATE OR REPLACE FUNCTION analytics.late_rate(late_count bigint, eligible_count bigint)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT late_count::numeric / NULLIF(eligible_count,0) $$;

CREATE TABLE IF NOT EXISTS analytics.monthly_sales_snapshot (
 month date NOT NULL, category text NOT NULL, sales_value numeric NOT NULL,
 orders bigint NOT NULL, revenue_per_order numeric, refreshed_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(month,category)
);
CREATE TABLE IF NOT EXISTS analytics.dashboard_config (
 analysis_name text PRIMARY KEY CHECK(analysis_name='monthly_sales'),
 source text NOT NULL CHECK(source IN ('view','snapshot')),
 updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO analytics.dashboard_config(analysis_name,source)
VALUES('monthly_sales','view') ON CONFLICT(analysis_name) DO NOTHING;
CREATE OR REPLACE VIEW analytics.v_dashboard_sales AS
SELECT s.month,s.category,s.sales_value,s.orders,s.revenue_per_order
FROM analytics.monthly_sales_snapshot s
WHERE (SELECT source FROM analytics.dashboard_config WHERE analysis_name='monthly_sales')='snapshot'
UNION ALL
SELECT v.month,v.category,v.sales_value,v.orders,v.revenue_per_order
FROM analytics.v_item_sales v
WHERE (SELECT source FROM analytics.dashboard_config WHERE analysis_name='monthly_sales')='view';
CREATE OR REPLACE PROCEDURE analytics.refresh_monthly_sales(p_month date)
LANGUAGE plpgsql AS $$
BEGIN
  IF p_month IS NULL OR date_trunc('month', p_month)::date <> p_month THEN
    RAISE EXCEPTION 'p_month must be the first day of a month';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext(p_month::text));
  DELETE FROM analytics.monthly_sales_snapshot WHERE month=p_month;
  INSERT INTO analytics.monthly_sales_snapshot(month,category,sales_value,orders,revenue_per_order)
  SELECT month,category,sales_value,orders,revenue_per_order
  FROM analytics.v_item_sales WHERE month=p_month;
END $$;
