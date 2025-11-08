-- Sample SQL Queries for Optimization Testing
-- These queries have various optimization opportunities

-- Query 1: Complex JOIN with aggregation (missing indexes)
SELECT 
    c.name,
    c.city,
    COUNT(o.id) as order_count,
    SUM(o.amount) as total_spent,
    AVG(o.amount) as avg_order_value
FROM customers c
JOIN orders o ON c.id = o.customer_id
WHERE c.country = 'USA' 
    AND o.order_date >= '2023-01-01'
    AND o.status = 'completed'
GROUP BY c.id, c.name, c.city
HAVING COUNT(o.id) > 5
ORDER BY total_spent DESC
LIMIT 100;

-- Query 2: Subquery that could be optimized with JOIN
SELECT 
    p.name,
    p.category,
    p.price,
    (SELECT COUNT(*) FROM order_items oi WHERE oi.product_id = p.id) as order_count,
    (SELECT SUM(oi.quantity) FROM order_items oi WHERE oi.product_id = p.id) as total_quantity_sold
FROM products p
WHERE p.stock_quantity < 50
    AND p.price > 100
ORDER BY order_count DESC;

-- Query 3: Multiple nested subqueries
SELECT 
    c.name,
    c.email,
    o.amount,
    o.order_date
FROM customers c
JOIN orders o ON c.id = o.customer_id
WHERE o.amount > (
    SELECT AVG(o2.amount) 
    FROM orders o2 
    WHERE o2.customer_id = c.id
)
    AND c.id IN (
        SELECT DISTINCT o3.customer_id 
        FROM orders o3 
        WHERE o3.order_date > '2023-06-01'
    )
    AND EXISTS (
        SELECT 1 FROM order_items oi 
        WHERE oi.order_id = o.id 
        AND oi.quantity > 5
    );

-- Query 4: Window function with complex filtering
SELECT 
    name,
    city,
    total_orders,
    total_spent,
    AVG(total_spent) OVER (PARTITION BY city) as city_avg,
    ROW_NUMBER() OVER (PARTITION BY city ORDER BY total_spent DESC) as city_rank
FROM customers
WHERE registration_date > '2022-01-01'
    AND total_orders > 10
    AND city IN (
        SELECT city 
        FROM customers 
        GROUP BY city 
        HAVING COUNT(*) > 100
    );

-- Query 5: Expensive DISTINCT with JOIN
SELECT DISTINCT 
    c.country,
    p.category,
    COUNT(DISTINCT o.id) as unique_orders,
    SUM(oi.quantity) as total_items
FROM customers c
JOIN orders o ON c.id = o.customer_id
JOIN order_items oi ON o.id = oi.order_id
JOIN products p ON oi.product_id = p.id
WHERE o.order_date BETWEEN '2023-01-01' AND '2023-12-31'
    AND o.status = 'completed'
GROUP BY c.country, p.category
ORDER BY total_items DESC;

-- Query 6: Correlated subquery (performance issue)
SELECT 
    c.name,
    c.total_spent,
    (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.amount > 500) as large_orders,
    (SELECT MAX(o.order_date) FROM orders o WHERE o.customer_id = c.id) as last_order_date
FROM customers c
WHERE c.total_spent > (
    SELECT AVG(total_spent) FROM customers
)
ORDER BY c.total_spent DESC;

-- Query 7: Complex WHERE clause with OR conditions
SELECT 
    o.id,
    o.amount,
    o.status,
    c.name,
    c.city
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE (o.amount > 500 AND o.status = 'completed')
    OR (o.amount < 100 AND o.status = 'pending')
    OR (c.city = 'New York' AND o.order_date > '2023-07-01')
ORDER BY o.order_date DESC;

-- Query 8: Multiple aggregations in one query
SELECT 
    DATE_TRUNC('month', o.order_date) as month,
    COUNT(*) as total_orders,
    SUM(CASE WHEN o.amount > 500 THEN 1 ELSE 0 END) as large_orders,
    SUM(CASE WHEN o.amount < 100 THEN 1 ELSE 0 END) as small_orders,
    AVG(o.amount) as avg_order_amount,
    MAX(o.amount) as max_order_amount,
    COUNT(DISTINCT o.customer_id) as unique_customers
FROM orders o
WHERE o.order_date >= '2023-01-01'
GROUP BY DATE_TRUNC('month', o.order_date)
HAVING COUNT(*) > 1000
ORDER BY month;
