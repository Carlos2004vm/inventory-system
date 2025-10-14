-- Script de inicialización de la Base de Datos
-- Se ejecuta automáticamente al crear el contenedor MySQL

-- Usar la base de datos creada por docker-compose
USE inventory_db;

-- ============================================
-- Tabla: users
-- Propósito: Almacenar usuarios del sistema
-- ============================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,  -- Password encriptado (bcrypt)
    full_name VARCHAR(100),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_username (username),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Tabla: categories
-- Propósito: Categorías para organizar productos
-- ============================================
CREATE TABLE IF NOT EXISTS categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Tabla: products
-- Propósito: Inventario de productos
-- ============================================
CREATE TABLE IF NOT EXISTS products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    sku VARCHAR(50) UNIQUE,  -- Código único del producto
    price DECIMAL(10, 2) NOT NULL,  -- Precio con 2 decimales
    stock INT NOT NULL DEFAULT 0,  -- Cantidad disponible
    min_stock INT DEFAULT 5,  -- Stock mínimo para alertas
    category_id INT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
    INDEX idx_sku (sku),
    INDEX idx_category (category_id),
    INDEX idx_stock (stock)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Tabla: sales
-- Propósito: Registro de ventas realizadas
-- ============================================
CREATE TABLE IF NOT EXISTS sales (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,  -- Usuario que realizó la venta
    total_amount DECIMAL(10, 2) NOT NULL,
    sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('completed', 'cancelled', 'pending') DEFAULT 'completed',
    notes TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_user (user_id),
    INDEX idx_date (sale_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Tabla: sale_items
-- Propósito: Detalles de productos en cada venta
-- ============================================
CREATE TABLE IF NOT EXISTS sale_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sale_id INT NOT NULL,
    product_id INT NOT NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,  -- Precio al momento de la venta
    subtotal DECIMAL(10, 2) NOT NULL,  -- quantity * unit_price
    FOREIGN KEY (sale_id) REFERENCES sales(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
    INDEX idx_sale (sale_id),
    INDEX idx_product (product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================
-- Datos iniciales para pruebas
-- ============================================

-- Insertar categorías de ejemplo
INSERT INTO categories (name, description) VALUES
('Electrónica', 'Productos electrónicos y tecnología'),
('Alimentos', 'Productos alimenticios'),
('Ropa', 'Prendas de vestir'),
('Hogar', 'Artículos para el hogar');

-- Insertar productos de ejemplo
INSERT INTO products (name, description, sku, price, stock, min_stock, category_id) VALUES
('Laptop Dell XPS 13', 'Laptop ultraportátil con procesador Intel i7', 'DELL-XPS-001', 1299.99, 15, 5, 1),
('Mouse Logitech MX Master', 'Mouse inalámbrico ergonómico', 'LOG-MX-002', 99.99, 30, 10, 1),
('Café Premium 500g', 'Café molido de altura', 'CAFE-001', 12.50, 100, 20, 2),
('Camisa Polo Azul', 'Camisa polo talla M', 'POLO-AZ-M', 29.99, 50, 15, 3),
('Lámpara LED Escritorio', 'Lámpara ajustable con USB', 'LAMP-LED-001', 45.00, 25, 8, 4);

-- Nota: No insertamos usuarios aquí porque las contraseñas deben ser hasheadas
-- Los usuarios se crearán mediante el endpoint de registro