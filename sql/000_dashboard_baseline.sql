-- Semantically equivalent starting versions captured before the candidate-index
-- migration. Q4 intentionally uses per-seller correlated aggregates; the final
-- query pre-aggregates each fact once, avoiding repeated scans and join fanout.
-- Q1:
SELECT date_trunc('month',o.purchase_at)::date AS month,
       COALESCE(t.category_name_english,p.category_name,'unknown') AS category,
       sum(i.price) AS sales_value,count(DISTINCT o.order_id) AS orders,
       sum(i.price)/NULLIF(count(DISTINCT o.order_id),0) AS revenue_per_order
FROM olist.order_items i JOIN olist.orders o USING(order_id)
LEFT JOIN olist.products p USING(product_id)
LEFT JOIN olist.category_translation t USING(category_name)
WHERE o.purchase_at IS NOT NULL
GROUP BY 1,2 ORDER BY 1,2;

-- Q2:
SELECT date_trunc('month',o.purchase_at)::date AS order_month,COALESCE(c.state,'??') AS state,
       count(*) AS eligible_orders,count(*) FILTER(WHERE o.delivered_at>o.estimated_delivery_at) AS late_orders,
       analytics.late_rate(count(*) FILTER(WHERE o.delivered_at>o.estimated_delivery_at),count(*)) AS late_rate
FROM olist.orders o JOIN olist.customers c USING(customer_id)
WHERE o.purchase_at IS NOT NULL AND o.delivered_at IS NOT NULL AND o.estimated_delivery_at IS NOT NULL
GROUP BY 1,2 ORDER BY 1,2;

-- Q3:
WITH review_per_order AS (SELECT order_id,avg(score)::numeric AS score FROM olist.reviews WHERE score IS NOT NULL GROUP BY order_id)
SELECT CASE WHEN o.delivered_at>o.estimated_delivery_at THEN 'late' ELSE 'on_time' END AS delivery_group,
       count(*) AS reviewed_orders,avg(r.score) AS mean_score,
       count(*) FILTER(WHERE r.score=1) AS score_1,count(*) FILTER(WHERE r.score=2) AS score_2,
       count(*) FILTER(WHERE r.score=3) AS score_3,count(*) FILTER(WHERE r.score=4) AS score_4,
       count(*) FILTER(WHERE r.score=5) AS score_5
FROM olist.orders o JOIN review_per_order r USING(order_id)
WHERE o.delivered_at IS NOT NULL AND o.estimated_delivery_at IS NOT NULL GROUP BY 1;

-- Q4:
WITH seller_sales AS (SELECT seller_id,sum(price) AS revenue FROM olist.order_items GROUP BY seller_id),
top_sellers AS (SELECT seller_id,revenue FROM seller_sales ORDER BY revenue DESC LIMIT 20)
SELECT s.seller_id,s.revenue,
 rank() OVER(ORDER BY s.revenue DESC) AS revenue_rank,
 (SELECT avg(extract(epoch FROM (o.carrier_at-o.purchase_at))/3600.0)
  FROM (SELECT DISTINCT i.order_id FROM olist.order_items i WHERE i.seller_id=s.seller_id) so
  JOIN olist.orders o USING(order_id)
  WHERE o.purchase_at IS NOT NULL AND o.carrier_at IS NOT NULL AND o.carrier_at>=o.purchase_at) AS prep_hours,
 (SELECT avg(ro.score) FROM
   (SELECT r.order_id,avg(r.score)::numeric score FROM olist.reviews r WHERE r.score IS NOT NULL GROUP BY r.order_id) ro
   JOIN (SELECT DISTINCT seller_id,order_id FROM olist.order_items) si USING(order_id)
   WHERE si.seller_id=s.seller_id) AS mean_review
FROM top_sellers s
ORDER BY revenue DESC;

-- Q5:
WITH order_values AS (SELECT order_id,sum(price+freight_value) AS order_value FROM olist.order_items GROUP BY order_id),
payment_order AS (
 SELECT p.order_id,p.payment_type,p.installments,sum(p.value) AS method_paid,ov.order_value
 FROM olist.payments p JOIN order_values ov USING(order_id)
 GROUP BY p.order_id,p.payment_type,p.installments,ov.order_value)
SELECT payment_type,installments,count(*) AS orders,sum(method_paid) AS paid_value,
       avg(order_value) AS mean_order_value,percentile_cont(0.5) WITHIN GROUP(ORDER BY order_value) AS median_order_value
FROM payment_order GROUP BY 1,2 ORDER BY 1,2;
