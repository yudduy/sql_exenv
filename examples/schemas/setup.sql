-- Example Database Schema for SQL Optimization Testing
-- This script creates tables with realistic data patterns for testing query optimization

-- Drop tables if they exist (clean setup)
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- Create customers table
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    city VARCHAR(100),
    country VARCHAR(100),
    registration_date DATE DEFAULT CURRENT_DATE,
    total_orders INTEGER DEFAULT 0,
    total_spent DECIMAL(10,2) DEFAULT 0.00
);

-- Create products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    price DECIMAL(10,2) NOT NULL,
    stock_quantity INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create orders table
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    amount DECIMAL(10,2) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    order_date DATE DEFAULT CURRENT_DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create order_items table
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common query patterns
CREATE INDEX idx_customers_country ON customers(country);
CREATE INDEX idx_customers_city ON customers(city);
CREATE INDEX idx_customers_registration_date ON customers(registration_date);
CREATE INDEX idx_products_category ON products(category);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_order_date ON orders(order_date);
CREATE INDEX idx_orders_amount ON orders(amount);
CREATE INDEX idx_order_items_order_id ON order_items(order_id);
CREATE INDEX idx_order_items_product_id ON order_items(product_id);

-- Insert sample data
-- Customers
INSERT INTO customers (name, email, city, country, registration_date, total_orders, total_spent) VALUES
('John Smith', 'john.smith@example.com', 'New York', 'USA', '2022-01-15', 12, 2450.50),
('Jane Doe', 'jane.doe@example.com', 'Los Angeles', 'USA', '2022-03-20', 8, 1820.00),
('Bob Johnson', 'bob.johnson@example.com', 'Chicago', 'USA', '2021-11-10', 15, 3200.75),
('Alice Brown', 'alice.brown@example.com', 'Toronto', 'Canada', '2022-06-05', 6, 1450.25),
('Charlie Wilson', 'charlie.wilson@example.com', 'Vancouver', 'Canada', '2021-09-12', 10, 2100.00),
('Diana Martinez', 'diana.martinez@example.com', 'Mexico City', 'Mexico', '2022-02-28', 9, 1750.50),
('Eve Davis', 'eve.davis@example.com', 'New York', 'USA', '2022-07-15', 4, 890.00),
('Frank Miller', 'frank.miller@example.com', 'Los Angeles', 'USA', '2021-12-03', 11, 2650.25),
('Grace Lee', 'grace.lee@example.com', 'San Francisco', 'USA', '2022-04-18', 7, 1680.75),
('Henry Taylor', 'henry.taylor@example.com', 'Chicago', 'USA', '2022-05-22', 13, 2890.50);

-- Products
INSERT INTO products (name, category, price, stock_quantity) VALUES
('Laptop Pro', 'Electronics', 1299.99, 25),
('Wireless Mouse', 'Electronics', 29.99, 150),
('Office Chair', 'Furniture', 199.99, 45),
('Standing Desk', 'Furniture', 449.99, 15),
('Coffee Maker', 'Appliances', 89.99, 60),
('Water Bottle', 'Accessories', 19.99, 200),
('Notebook Set', 'Stationery', 24.99, 180),
('Monitor 27"', 'Electronics', 349.99, 35),
('Keyboard Mechanical', 'Electronics', 79.99, 85),
('Desk Lamp', 'Furniture', 39.99, 120),
('Headphones', 'Electronics', 149.99, 55),
('Phone Case', 'Accessories', 15.99, 250),
('Power Bank', 'Electronics', 49.99, 95),
('Backpack', 'Accessories', 59.99, 70),
('Webcam HD', 'Electronics', 89.99, 40);

-- Orders
INSERT INTO orders (customer_id, amount, status, order_date) VALUES
(1, 1299.99, 'completed', '2023-01-15'),
(1, 199.99, 'completed', '2023-02-20'),
(2, 349.99, 'completed', '2023-01-25'),
(3, 89.99, 'pending', '2023-03-10'),
(4, 449.99, 'completed', '2023-02-15'),
(5, 79.99, 'completed', '2023-01-30'),
(6, 149.99, 'shipped', '2023-03-05'),
(7, 29.99, 'completed', '2023-02-10'),
(8, 199.99, 'completed', '2023-01-20'),
(9, 59.99, 'pending', '2023-03-12'),
(10, 24.99, 'completed', '2023-02-25'),
(1, 79.99, 'completed', '2023-03-01'),
(2, 149.99, 'completed', '2023-02-05'),
(3, 39.99, 'completed', '2023-01-18'),
(4, 89.99, 'completed', '2023-02-28'),
(5, 1299.99, 'shipped', '2023-03-08'),
(6, 49.99, 'completed', '2023-01-22'),
(7, 199.99, 'pending', '2023-03-15'),
(8, 79.99, 'completed', '2023-02-12'),
(9, 349.99, 'completed', '2023-01-28');

-- Order Items
INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
(1, 1, 1, 1299.99),
(2, 3, 1, 199.99),
(3, 8, 1, 349.99),
(4, 5, 1, 89.99),
(5, 4, 1, 449.99),
(6, 9, 1, 79.99),
(7, 11, 1, 149.99),
(8, 2, 1, 29.99),
(9, 3, 1, 199.99),
(10, 13, 1, 59.99),
(11, 14, 1, 24.99),
(12, 9, 1, 79.99),
(13, 11, 1, 149.99),
(14, 10, 1, 39.99),
(15, 5, 1, 89.99),
(16, 1, 1, 1299.99),
(17, 12, 1, 49.99),
(18, 3, 1, 199.99),
(19, 9, 1, 79.99),
(20, 8, 1, 349.99);

-- Update statistics for better query planning
ANALYZE customers;
ANALYZE products;
ANALYZE orders;
ANALYZE order_items;

-- Verify data was inserted
SELECT 'Customers' as table_name, COUNT(*) as row_count FROM customers
UNION ALL
SELECT 'Products', COUNT(*) FROM products
UNION ALL
SELECT 'Orders', COUNT(*) FROM orders
UNION ALL
SELECT 'Order Items', COUNT(*) FROM order_items;
