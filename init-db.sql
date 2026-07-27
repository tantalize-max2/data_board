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

-- 用户表（username=手机号，手机号+密码登录）
CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL UNIQUE,   -- 手机号
  name VARCHAR(64) DEFAULT '',
  role_id VARCHAR(64) DEFAULT '',          -- 兼容旧逻辑，= username
  role_name VARCHAR(64) DEFAULT '',        -- 角色名称（分局长/客户经理/工程师...）
  phone VARCHAR(20) DEFAULT '',            -- 手机号（=username）
  password_hash VARCHAR(128) NOT NULL,
  password_salt VARCHAR(64) NOT NULL,
  must_change_pwd TINYINT DEFAULT 1,       -- 1=首次登录强制改密
  zone VARCHAR(32) DEFAULT 'public',
  zone_name VARCHAR(64) DEFAULT '公众战区',
  color VARCHAR(20) DEFAULT '#1565c0',
  is_admin TINYINT DEFAULT 0,              -- 全局管理员
  is_zone_admin TINYINT DEFAULT 0,         -- 战区管理员（分局长）
  is_guide TINYINT DEFAULT 0,              -- 指导员（可编辑内容，无管理后台和增删权限）
  is_active TINYINT DEFAULT 1,
  is_placeholder TINYINT DEFAULT 0,        -- 1=占位人员（岗位管理创建的，非真实用户）
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by VARCHAR(64) DEFAULT ''
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 角色权限表（角色级授权：角色名 × 战役 × 战区）
CREATE TABLE IF NOT EXISTS role_access (
  id INT AUTO_INCREMENT PRIMARY KEY,
  role_id VARCHAR(64) NOT NULL,            -- = users.role_name（角色名称，如"客户经理"）
  battle_id VARCHAR(32) NOT NULL,
  warzone_id VARCHAR(32) NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_role_bw (role_id, battle_id, warzone_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 用户额外角色表（赋予一个人其它角色，赋予后拥有该角色视角）
CREATE TABLE IF NOT EXISTS user_extra_roles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL,           -- 手机号
  role_name VARCHAR(64) NOT NULL,          -- 额外角色名称
  zone VARCHAR(32) DEFAULT '',             -- 角色所属战区（区分跨战区同名角色）
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_user_zone_role (username, zone, role_name),
  INDEX idx_username (username)
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
  combat_role VARCHAR(256) DEFAULT '',       -- 作战角色，如"客户经理+工程师+存量专员"
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

-- 登录日志表
CREATE TABLE IF NOT EXISTS login_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) DEFAULT '',          -- 手机号
  name VARCHAR(64) DEFAULT '',              -- 姓名
  role_name VARCHAR(64) DEFAULT '',         -- 角色
  ip VARCHAR(64) DEFAULT '',
  user_agent VARCHAR(256) DEFAULT '',
  success TINYINT DEFAULT 0,                -- 1=成功 0=失败
  fail_reason VARCHAR(128) DEFAULT '',      -- 失败原因
  login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_username (username),
  INDEX idx_time (login_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 权限操作日志表
CREATE TABLE IF NOT EXISTS access_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  operator VARCHAR(64) DEFAULT '',          -- 操作人手机号
  operator_name VARCHAR(64) DEFAULT '',     -- 操作人姓名
  action VARCHAR(32) DEFAULT '',            -- 操作类型：create/update/delete/access/grant
  target_type VARCHAR(32) DEFAULT '',       -- 目标类型：user/role_access/record
  target_id VARCHAR(64) DEFAULT '',         -- 目标ID
  detail TEXT,                              -- 详细信息（JSON）
  ip VARCHAR(64) DEFAULT '',
  op_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_operator (operator),
  INDEX idx_time (op_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ====== 辅助工具模块 ======
-- 工具模块（分类，类似资料中心的板块，可新建）
CREATE TABLE IF NOT EXISTS tool_modules (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(128) NOT NULL,               -- 模块名称
  description VARCHAR(512) DEFAULT '',       -- 模块描述
  sort_order INT DEFAULT 0,                  -- 排序
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 工具项（HTML 文件 或 外部链接，带描述）
CREATE TABLE IF NOT EXISTS tools (
  id INT AUTO_INCREMENT PRIMARY KEY,
  module_id INT NOT NULL,                    -- 所属模块
  name VARCHAR(128) NOT NULL,                -- 工具名称
  description TEXT,                          -- 工具描述/介绍
  tool_type VARCHAR(16) DEFAULT 'html',      -- html=上传HTML文件, link=外部链接
  url VARCHAR(1024) DEFAULT '',              -- link 类型的链接地址
  file_path VARCHAR(512) DEFAULT '',         -- html 类型的文件存储相对路径
  icon VARCHAR(64) DEFAULT '',               -- 图标标识（可选）
  open_mode VARCHAR(16) DEFAULT 'iframe',    -- iframe=内嵌预览, newtab=新窗口打开
  sort_order INT DEFAULT 0,
  is_active TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  updated_by VARCHAR(64) DEFAULT '',
  INDEX idx_module (module_id),
  INDEX idx_sort (sort_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 辅助工具模块权限（模块级授权：赋予到角色 / 赋予到个人）
CREATE TABLE IF NOT EXISTS tool_module_access (
  id INT AUTO_INCREMENT PRIMARY KEY,
  module_id INT NOT NULL,                    -- 授权的模块
  grant_type VARCHAR(16) NOT NULL,           -- 'role'=赋予到角色, 'user'=赋予到个人
  grant_value VARCHAR(128) NOT NULL,         -- role 时=角色名, user 时=用户名(手机号)
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_module_grant (module_id, grant_type, grant_value),
  INDEX idx_module (module_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 辅助工具权限（工具级授权：赋予到角色 / 赋予到个人）
-- 叠加逻辑：用户可见某工具 = 其可见该模块 OR 该工具被单独授权
CREATE TABLE IF NOT EXISTS tool_access (
  id INT AUTO_INCREMENT PRIMARY KEY,
  tool_id INT NOT NULL,                     -- 授权的工具
  grant_type VARCHAR(16) NOT NULL,          -- 'role'=赋予到角色, 'user'=赋予到个人
  grant_value VARCHAR(128) NOT NULL,        -- role 时=角色名, user 时=用户名(手机号)
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_tool_grant (tool_id, grant_type, grant_value),
  INDEX idx_tool (tool_id)
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
('business', '商客战区', '#2e7d32', 2),
('education', '校园战区', '#7b1fa2', 3),
('industry', '行业战区', '#e65100', 4);

-- 管理员默认账号（初始密码 Xs@2026）
-- 首次登录强制改密（must_change_pwd=0 表示管理员已设好无需改）
INSERT IGNORE INTO users (username, name, role_id, role_name, phone, password_hash, password_salt,
  must_change_pwd, zone, zone_name, color, is_admin)
VALUES ('admin', '系统管理员', 'admin', '总经理', 'admin',
  'ca4b86e18c2ec68f17e8c34b8c1c0f6e9d8a7b6c5e4f3d2s1a0b9c8d7e6f5a4b',
  'a1b2c3d4', 0, 'public', '公众战区', '#ffd980', 1);
