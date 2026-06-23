-- 夏收行动部署看板 - 数据库初始化
-- Docker 首次启动时自动执行

SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS xiashou2 DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE xiashou2;

-- 战役表
CREATE TABLE IF NOT EXISTS battles (
  id VARCHAR(32) PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  color VARCHAR(20) DEFAULT '#1565c0',
  sort_order INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 战区表
CREATE TABLE IF NOT EXISTS warzones (
  id VARCHAR(32) PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  color VARCHAR(20) DEFAULT '#2e7d32',
  sort_order INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户表
CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,
  name VARCHAR(64) DEFAULT '',
  role_id VARCHAR(64) DEFAULT '',
  role_name VARCHAR(64) DEFAULT '',
  phone VARCHAR(20) DEFAULT '',
  password_hash VARCHAR(128) NOT NULL,
  password_salt VARCHAR(64) NOT NULL,
  zone VARCHAR(32) DEFAULT 'public',
  zone_name VARCHAR(64) DEFAULT '公众战区',
  color VARCHAR(20) DEFAULT '#1565c0',
  is_admin TINYINT DEFAULT 0,
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by VARCHAR(64) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 角色权限表
CREATE TABLE IF NOT EXISTS role_access (
  id INT AUTO_INCREMENT PRIMARY KEY,
  role_id VARCHAR(64) NOT NULL,
  battle_id VARCHAR(32) NOT NULL,
  warzone_id VARCHAR(32) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_role_bw (role_id, battle_id, warzone_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 部署记录表
CREATE TABLE IF NOT EXISTS deployment_records (
  id INT AUTO_INCREMENT PRIMARY KEY,
  battle_id VARCHAR(32) DEFAULT NULL,
  battle_no VARCHAR(32) DEFAULT '',
  battle_name VARCHAR(128) DEFAULT '',
  battle_target TEXT,
  warzone_id VARCHAR(32) DEFAULT NULL,
  warzone_name VARCHAR(64) DEFAULT '',
  warzone_target TEXT,
  path_no VARCHAR(32) DEFAULT '',
  path_name VARCHAR(256) DEFAULT '',
  path_target TEXT,
  scene_no VARCHAR(32) DEFAULT '',
  scene_title VARCHAR(256) DEFAULT '',
  scene_name TEXT,
  guide_role VARCHAR(256) DEFAULT '',
  combat_role VARCHAR(256) DEFAULT '',
  opportunity_source TEXT,
  control_cycle VARCHAR(128) DEFAULT '',
  control_action TEXT,
  control_target TEXT,
  policy TEXT,
  incentive TEXT,
  standard_talk TEXT,
  closed_loop_control TEXT,
  process_flow TEXT,
  sort_order INT DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by VARCHAR(64) DEFAULT '',
  INDEX idx_battle (battle_id),
  INDEX idx_warzone (warzone_id),
  INDEX idx_path (path_no),
  INDEX idx_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始战役数据
INSERT IGNORE INTO battles (id, name, color, sort_order) VALUES
('b1', '一号工程战', '#8B1A1A', 1),
('b2', '百万加装战', '#C0392B', 2),
('b3', '高价值新增战', '#A63A3A', 3),
('b4', '双线标准ICT固本战', '#2E7D32', 4),
('b5', '项目掘金战', '#1565c0', 5),
('b6', '细分市场战', '#7b1fa2', 6);

-- 初始战区数据
INSERT IGNORE INTO warzones (id, name, color, sort_order) VALUES
('public', '公众战区', '#1565c0', 1),
('business', '商业战区', '#2e7d32', 2),
('education', '校园战区', '#7b1fa2', 3),
('industry', '行业战区', '#e65100', 4);

-- 管理员默认账号（密码 123456）
-- salt: a1b2c3d4  hash: sha256("123456a1b2c3d4")
INSERT IGNORE INTO users (username, name, role_id, role_name, password_hash, password_salt, zone, zone_name, color, is_admin)
VALUES ('admin', '管理员', 'admin', '总经理', '8c96bf56c80f8a4c6c1a6c2f1e5d3a7b9f0e2c4d6a8b0d2f4e6a8c0b2d4f6e8', 'a1b2c3d4', 'public', '公众战区', '#ffd980', 1);
