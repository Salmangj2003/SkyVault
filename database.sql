
-- =====================================
-- SKYVAULT DATABASE
-- =====================================
CREATE DATABASE IF NOT EXISTS pg_cloud_drive;
USE pg_cloud_drive;

-- =====================================
-- USERS TABLE
-- =====================================
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    avatar VARCHAR(255) DEFAULT 'default.png',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- =====================================
-- FILES TABLE
-- =====================================
CREATE TABLE IF NOT EXISTS files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    filepath VARCHAR(500) NOT NULL,
    size BIGINT DEFAULT 0,
    filetype VARCHAR(100),
    downloads INT DEFAULT 0,
    deleted TINYINT(1) DEFAULT 0,
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_files_user_id (user_id),

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- =====================================
-- SHARES TABLE
-- =====================================
CREATE TABLE IF NOT EXISTS shares (
    id INT AUTO_INCREMENT PRIMARY KEY,
    file_id INT NOT NULL,
    token VARCHAR(255) UNIQUE NOT NULL,
    expiry DATETIME,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_shares_file_id (file_id),

    FOREIGN KEY (file_id)
        REFERENCES files(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;

-- =====================================
-- TRASH TABLE
-- =====================================
CREATE TABLE IF NOT EXISTS trash (
    id INT AUTO_INCREMENT PRIMARY KEY,
    file_id INT NOT NULL,
    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (file_id)
        REFERENCES files(id)
        ON DELETE CASCADE
) ENGINE=InnoDB;
