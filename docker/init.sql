-- Sample database schema designed to demonstrate optimization opportunities
-- Creates realistic workload patterns that benefit from indexing and query rewrites

CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    total_amount DECIMAL(10, 2) NOT NULL,
    status VARCHAR(50) NOT NULL,
    order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    category VARCHAR(100),
    stock_quantity INTEGER DEFAULT 0
);

-- Insert data volumes that trigger sequential scans
INSERT INTO users (email, username, created_at)
SELECT
    'user' || i || '@example.com',
    'user' || i,
    CURRENT_TIMESTAMP - (random() * INTERVAL '365 days')
FROM generate_series(1, 10000) AS i;

INSERT INTO products (name, price, category, stock_quantity)
SELECT
    'Product ' || i,
    (random() * 1000)::DECIMAL(10, 2),
    CASE (i % 5)
        WHEN 0 THEN 'Electronics'
        WHEN 1 THEN 'Clothing'
        WHEN 2 THEN 'Books'
        WHEN 3 THEN 'Home'
        ELSE 'Sports'
    END,
    (random() * 100)::INTEGER
FROM generate_series(1, 5000) AS i;

INSERT INTO orders (user_id, total_amount, status, order_date)
SELECT
    (random() * 9999 + 1)::INTEGER,
    (random() * 500 + 10)::DECIMAL(10, 2),
    CASE (random() * 3)::INTEGER
        WHEN 0 THEN 'pending'
        WHEN 1 THEN 'shipped'
        ELSE 'delivered'
    END,
    CURRENT_TIMESTAMP - (random() * INTERVAL '180 days')
FROM generate_series(1, 25000) AS i;

-- Update statistics for accurate cost estimation
ANALYZE users;
ANALYZE orders;
ANALYZE products;
