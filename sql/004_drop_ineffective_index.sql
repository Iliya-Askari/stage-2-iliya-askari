-- The benchmark records whether this low-selectivity index was used. It is
-- intentionally removed after evaluation; it adds write/storage cost to every
-- customer insert and does not serve the dashboard's join/filter predicates.
DROP INDEX IF EXISTS olist.ix_customers_state_candidate;
