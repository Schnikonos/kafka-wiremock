-- MySQL initialisation for kafka-wiremock examples
-- Executed automatically by the mysql container on first start.

-- Create the application database (also set by MYSQL_DATABASE env, but kept here for clarity)
CREATE DATABASE IF NOT EXISTS orders_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create the application user and grant access
-- Password is set via MYSQL_PASSWORD env var; we use a placeholder that matches docker-compose
CREATE USER IF NOT EXISTS 'orders_user'@'%' IDENTIFIED BY 'orders_pass';
GRANT ALL PRIVILEGES ON orders_db.* TO 'orders_user'@'%';
FLUSH PRIVILEGES;

USE orders_db;

-- ──────────────────────────────────────────────────────────────────────────────
-- products table  (used by db-example.test.yaml: seed_product / fetch_product)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id    INT          NOT NULL AUTO_INCREMENT,
    name  VARCHAR(255) NOT NULL,
    price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ──────────────────────────────────────────────────────────────────────────────
-- orders table  (used by db-example.test.yaml: verify_order / cleanup_order)
-- Written to by the "service under test" (mocked by the kafka-wiremock rule)
-- ──────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orders (
    id         INT          NOT NULL AUTO_INCREMENT,
    product_id INT          NOT NULL,
    status     VARCHAR(50)  NOT NULL DEFAULT 'PENDING',
    created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_product_id (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

