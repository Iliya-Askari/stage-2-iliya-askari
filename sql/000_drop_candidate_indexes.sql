-- Reset only challenge-owned candidate index names so repeated benchmark runs
-- begin from the same unindexed Olist baseline. Does not alter tables or rows.
DROP INDEX IF EXISTS olist.ix_orders_purchase_at;
DROP INDEX IF EXISTS olist.ix_orders_customer_id;
DROP INDEX IF EXISTS olist.ix_order_items_seller_id;
DROP INDEX IF EXISTS olist.ix_order_items_product_id;
DROP INDEX IF EXISTS olist.ix_payments_order_id;
DROP INDEX IF EXISTS olist.ix_reviews_order_id;
DROP INDEX IF EXISTS olist.ix_customers_state_candidate;
-- Names from the earlier draft of this challenge's versioned DDL.
DROP INDEX IF EXISTS olist.ix_customers_state;
DROP INDEX IF EXISTS olist.ix_orders_purchase;
DROP INDEX IF EXISTS olist.ix_orders_delivery_est;
DROP INDEX IF EXISTS olist.ix_items_product;
DROP INDEX IF EXISTS olist.ix_items_seller;
DROP INDEX IF EXISTS olist.ix_reviews_order;
DROP INDEX IF EXISTS olist.ix_geolocation_zip;
