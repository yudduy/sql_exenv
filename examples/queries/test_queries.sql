-- Test Query 1: Simple Join with Filters
-- Scenario: Query filtering on country and order status
-- Expected: Agent should identify index opportunities on filter columns
-- Tables: customers, orders (exist in your database)

SELECT 
    c.id,
    c.name,
    c.email,
    COUNT(o.id) as order_count,
    MAX(o.order_date) as last_order_date
FROM customers c
JOIN orders o ON c.id = o.customer_id
WHERE c.country = 'USA'
  AND o.status = 'completed'
  AND o.order_date >= '2024-01-01'
GROUP BY c.id, c.name, c.email
HAVING COUNT(o.id) > 0
ORDER BY last_order_date DESC
LIMIT 50;

-- Test Query 2: Sequential Scan Challenge (Multi-table)
-- Scenario: Query with multiple joins and aggregations
-- Expected: Might create indexes but planner may still prefer seq scan
-- Good test of adaptive iteration control!
-- Tables: orders, order_items, products

SELECT
    o.customer_id,
    COUNT(DISTINCT o.id) as order_count,
    COUNT(oi.id) as total_items,
    SUM(oi.quantity * oi.unit_price) as total_value,
    AVG(oi.quantity * oi.unit_price) as avg_item_value
FROM orders o
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE o.status = 'completed'
  AND o.order_date >= '2023-01-01'
GROUP BY o.customer_id
HAVING SUM(oi.quantity * oi.unit_price) > 500
ORDER BY total_value DESC
LIMIT 100;

-- Test Query 3: Window Functions with CTE
-- Scenario: CTE with window functions and ranking
-- Expected: Agent may optimize subqueries or suggest materialized views
-- Tables: customers, orders, order_items

WITH customer_spend AS (
    SELECT
        o.customer_id,
        SUM(oi.quantity * oi.unit_price) as total_spent,
        COUNT(DISTINCT o.id) as order_count,
        MAX(o.order_date) as last_order_date
    FROM orders o
    JOIN order_items oi ON o.id = oi.order_id
    WHERE o.status = 'completed'
      AND o.order_date >= '2024-01-01'
    GROUP BY o.customer_id
)
SELECT
    c.id,
    c.name,
    c.email,
    cs.total_spent,
    cs.order_count,
    cs.last_order_date,
    RANK() OVER (ORDER BY cs.total_spent DESC) as spend_rank,
    PERCENT_RANK() OVER (ORDER BY cs.total_spent DESC) as spend_percentile
FROM customers c
JOIN customer_spend cs ON c.id = cs.customer_id
WHERE cs.order_count >= 5
ORDER BY spend_rank
LIMIT 50;
