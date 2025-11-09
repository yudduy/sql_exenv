-- Example queries demonstrating optimization opportunities
-- Run these through sql_exenv to see autonomous optimization in action

-- Query 1: Email lookup without index (sequential scan on 10k rows)
-- Expected: CREATE INDEX on users(email)
SELECT * FROM users WHERE email = 'user5000@example.com';

-- Query 2: Range query with multiple filters (benefits from composite index)
-- Expected: CREATE INDEX on orders(status, order_date)
SELECT * FROM orders
WHERE status = 'pending'
  AND order_date > CURRENT_DATE - INTERVAL '30 days'
ORDER BY order_date DESC;

-- Query 3: Join without foreign key index (nested loop performance issue)
-- Expected: CREATE INDEX on orders(user_id)
SELECT u.username, COUNT(o.id) as order_count, SUM(o.total_amount) as total_spent
FROM users u
LEFT JOIN orders o ON u.id = o.user_id
GROUP BY u.id, u.username
HAVING COUNT(o.id) > 5
ORDER BY total_spent DESC;

-- Query 4: Category filter with no index (sequential scan on products)
-- Expected: CREATE INDEX on products(category)
SELECT * FROM products
WHERE category = 'Electronics'
  AND stock_quantity > 0
ORDER BY price DESC;

-- Query 5: Correlated subquery (performance issue - runs subquery per row)
-- Expected: Query rewrite to use JOIN instead
SELECT
    u.username,
    u.email,
    (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) as order_count,
    (SELECT MAX(o.order_date) FROM orders o WHERE o.user_id = u.id) as last_order
FROM users u
WHERE (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) > 3;

-- Query 6: OR conditions requiring multiple index scans
-- Expected: CREATE INDEX on orders(status) and possible query rewrite
SELECT * FROM orders
WHERE (status = 'pending' AND total_amount > 500)
   OR (status = 'shipped' AND order_date < CURRENT_DATE - INTERVAL '7 days')
   OR (user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com'))
ORDER BY order_date DESC;

-- Query 7: Window function with unindexed partition
-- Expected: CREATE INDEX on orders(status, order_date)
SELECT
    status,
    order_date,
    total_amount,
    AVG(total_amount) OVER (PARTITION BY status) as status_avg,
    ROW_NUMBER() OVER (PARTITION BY status ORDER BY total_amount DESC) as status_rank
FROM orders
WHERE order_date > CURRENT_DATE - INTERVAL '90 days';

-- Query 8: Multiple aggregations with date truncation
-- Expected: CREATE INDEX on orders(order_date) or consider materialized view
SELECT
    DATE_TRUNC('month', order_date) as month,
    COUNT(*) as total_orders,
    SUM(CASE WHEN total_amount > 500 THEN 1 ELSE 0 END) as large_orders,
    AVG(total_amount) as avg_amount,
    COUNT(DISTINCT user_id) as unique_customers
FROM orders
WHERE order_date >= '2024-01-01'
GROUP BY DATE_TRUNC('month', order_date)
HAVING COUNT(*) > 100
ORDER BY month;
