-- Pi-hole stats database
-- Run with: sudo mariadb < schema.sql
-- Change the password before running.

CREATE DATABASE IF NOT EXISTS pihole_stats;

CREATE USER IF NOT EXISTS 'pistats'@'localhost' IDENTIFIED BY 'CHANGE_ME';
GRANT SELECT, INSERT ON pihole_stats.* TO 'pistats'@'localhost';
FLUSH PRIVILEGES;

USE pihole_stats;

-- One row per collection run (rolling 24h totals as reported by Pi-hole)
CREATE TABLE IF NOT EXISTS snapshots (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    taken_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_queries    INT NOT NULL,
    blocked_queries  INT NOT NULL,
    percent_blocked  DECIMAL(5,2) NOT NULL,
    unique_domains   INT NOT NULL,
    active_clients   INT NOT NULL,
    gravity_domains  INT NOT NULL,
    INDEX idx_taken_at (taken_at)
);

-- Top blocked domains captured with each snapshot
CREATE TABLE IF NOT EXISTS top_blocked (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    snapshot_id  INT NOT NULL,
    domain       VARCHAR(255) NOT NULL,
    hits         INT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE,
    INDEX idx_domain (domain)
);
