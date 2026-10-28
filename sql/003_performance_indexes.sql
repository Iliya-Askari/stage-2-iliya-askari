-- Apply only after capturing the baseline in notebooks/dba_benchmark.ipynb.
-- Candidate indexes selected for FK joins and selective date filtering.
CREATE INDEX IF NOT EXISTS ix_orders_purchase_at ON olist.orders(purchase_at);
CREATE INDEX IF NOT EXISTS ix_orders_customer_id ON olist.orders(customer_id);
CREATE INDEX IF NOT EXISTS ix_order_items_seller_id ON olist.order_items(seller_id);
CREATE INDEX IF NOT EXISTS ix_order_items_product_id ON olist.order_items(product_id);
CREATE INDEX IF NOT EXISTS ix_payments_order_id ON olist.payments(order_id);
CREATE INDEX IF NOT EXISTS ix_reviews_order_id ON olist.reviews(order_id);
-- Deliberately evaluated as a low-selectivity candidate; the benchmark drops it.
CREATE INDEX IF NOT EXISTS ix_customers_state_candidate ON olist.customers(state);
ANALYZE olist.customers;
ANALYZE olist.orders;
ANALYZE olist.order_items;
ANALYZE olist.payments;
ANALYZE olist.reviews;
