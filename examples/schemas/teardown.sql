-- Teardown script for example database
-- This script removes all tables and data created by setup.sql

-- Drop tables in correct order (respecting foreign key constraints)
DROP TABLE IF EXISTS order_items CASCADE;
DROP TABLE IF EXISTS orders CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

-- Confirm cleanup
SELECT 'All example tables have been dropped successfully.' as status;
