-- Q1: item price is merchandise sales; freight excluded. Snapshot is refreshed
-- atomically by the Olist loader from the live database view after each load.
SELECT month, category, sales_value, orders, revenue_per_order
FROM analytics.v_dashboard_sales ORDER BY month, category;

-- Q2: only orders with both delivery timestamps enter denominator; month is purchase month.
SELECT order_month, COALESCE(customer_state,'??') AS state,
       count(*) AS eligible_orders, count(*) FILTER (WHERE is_late) AS late_orders,
       analytics.late_rate(count(*) FILTER (WHERE is_late),count(*)) AS late_rate
FROM analytics.v_order_delivery
WHERE delivered_at IS NOT NULL AND estimated_delivery_at IS NOT NULL
  AND order_month IS NOT NULL
GROUP BY 1,2 ORDER BY 1,2;

-- Q3: orders without review omitted; multiple reviews averaged per order first.
WITH review_per_order AS (
 SELECT order_id, avg(score)::numeric AS score FROM olist.reviews
 WHERE score IS NOT NULL GROUP BY order_id
)
SELECT CASE WHEN d.is_late THEN 'late' ELSE 'on_time' END AS delivery_group,
       count(*) AS reviewed_orders, avg(r.score) AS mean_score,
       count(*) FILTER (WHERE r.score=1) AS score_1,
       count(*) FILTER (WHERE r.score=2) AS score_2,
       count(*) FILTER (WHERE r.score=3) AS score_3,
       count(*) FILTER (WHERE r.score=4) AS score_4,
       count(*) FILTER (WHERE r.score=5) AS score_5
FROM analytics.v_order_delivery d JOIN review_per_order r USING(order_id)
WHERE d.delivered_at IS NOT NULL AND d.estimated_delivery_at IS NOT NULL
GROUP BY 1;

-- Q4: revenue is item merchandise price; preparation is purchase to carrier handoff.
WITH seller_sales AS (
 SELECT seller_id, sum(price) AS revenue, count(*) AS items
 FROM olist.order_items GROUP BY seller_id
), seller_prep AS (
 SELECT seller_id, avg(extract(epoch FROM (carrier_at-purchase_at))/3600.0) AS prep_hours
 FROM (SELECT DISTINCT i.seller_id,o.order_id,o.purchase_at,o.carrier_at
       FROM olist.order_items i JOIN olist.orders o USING(order_id)
       WHERE o.purchase_at IS NOT NULL AND o.carrier_at IS NOT NULL
         AND o.carrier_at >= o.purchase_at) seller_orders GROUP BY seller_id
), seller_reviews AS (
 SELECT seller_id, avg(score)::numeric AS mean_review FROM (
 SELECT DISTINCT i.seller_id,r.order_id,r.score
 FROM (SELECT order_id,avg(score)::numeric score FROM olist.reviews
       WHERE score IS NOT NULL GROUP BY order_id) r
 JOIN olist.order_items i USING(order_id)) seller_order_reviews GROUP BY seller_id
)
SELECT ss.seller_id, ss.revenue, rank() OVER(ORDER BY ss.revenue DESC) AS revenue_rank,
       sp.prep_hours, sr.mean_review
FROM seller_sales ss LEFT JOIN seller_prep sp USING(seller_id)
LEFT JOIN seller_reviews sr USING(seller_id)
ORDER BY ss.revenue DESC LIMIT 20;

-- Q5: monthly payment mix and installment exposure.
WITH order_values AS (
 SELECT order_id, sum(price+freight_value) AS order_value
 FROM olist.order_items GROUP BY order_id
), payment_order AS (
 SELECT p.order_id, p.payment_type, p.installments,
        sum(p.value) AS method_paid, ov.order_value
 FROM olist.payments p JOIN order_values ov USING(order_id)
 GROUP BY p.order_id,p.payment_type,p.installments,ov.order_value
)
SELECT payment_type, installments, count(*) AS orders,
       sum(method_paid) AS paid_value, avg(order_value) AS mean_order_value,
       percentile_cont(0.5) WITHIN GROUP(ORDER BY order_value) AS median_order_value
FROM payment_order GROUP BY 1,2 ORDER BY 1,2;
