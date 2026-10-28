# Olist source CSVs

Place the nine original public Olist CSV files in this directory before running `nyc311 db-load`:

- `olist_customers_dataset.csv`
- `olist_geolocation_dataset.csv`
- `olist_orders_dataset.csv`
- `olist_order_items_dataset.csv`
- `olist_order_payments_dataset.csv`
- `olist_order_reviews_dataset.csv`
- `olist_products_dataset.csv`
- `olist_sellers_dataset.csv`
- `product_category_name_translation.csv`

The CSVs are intentionally excluded from Git because the geolocation file is large. The loader validates that every file exists before opening a database transaction.
