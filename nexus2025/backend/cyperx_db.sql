-- NEXUS 2025 MySQL schema. These tables match backend/server.py.
CREATE DATABASE IF NOT EXISTS cyperx_1
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE cyperx_1;

CREATE TABLE IF NOT EXISTS registrations (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    reg_id               VARCHAR(20) UNIQUE NOT NULL,
    full_name            VARCHAR(100) NOT NULL,
    email                VARCHAR(100) NOT NULL,
    phone                VARCHAR(15) NOT NULL,
    password_hash        VARCHAR(255) NOT NULL,
    dob                  DATE,
    gender               VARCHAR(20),
    institution_type     VARCHAR(50),
    college_name         VARCHAR(150),
    department           VARCHAR(50),
    year_of_study        VARCHAR(10),
    roll_number          VARCHAR(30),
    linkedin_url         VARCHAR(255),
    cgpa                 DECIMAL(4,2),
    photo_id_path        VARCHAR(255),
    events               JSON,
    tshirt_size          VARCHAR(5),
    meal_preference      VARCHAR(20),
    referral_source      VARCHAR(30),
    team_size            INT DEFAULT 1,
    team_name            VARCHAR(60),
    badge_color          VARCHAR(10),
    special_requirements TEXT,
    fee_category         VARCHAR(20),
    coupon_code          VARCHAR(30),
    on_site              TINYINT(1) DEFAULT 1,
    newsletter           TINYINT(1) DEFAULT 1,
    submitted_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contact_messages (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    email           VARCHAR(100) NOT NULL,
    phone           VARCHAR(15),
    query_type      VARCHAR(50),
    subject         VARCHAR(200) NOT NULL,
    college         VARCHAR(150),
    urgency_level   TINYINT DEFAULT 3,
    message         TEXT NOT NULL,
    subscribe       TINYINT(1) DEFAULT 1,
    attachment_path VARCHAR(255),
    submitted_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS payment_utr_log (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    utr         VARCHAR(50),
    upi_id      VARCHAR(100),
    amount      INT,
    reg_id      VARCHAR(20),
    status      VARCHAR(20) DEFAULT 'pending',
    verified_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Example queries
SELECT reg_id, full_name, email, submitted_at
FROM registrations
ORDER BY id DESC;

SELECT query_type, subject, submitted_at
FROM contact_messages
ORDER BY id DESC;
