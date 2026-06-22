---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: 'e6463047-a675-4e29-a28b-53b7f27e2cbb'
  PropagateID: 'e6463047-a675-4e29-a28b-53b7f27e2cbb'
  ReservedCode1: 'f9df9840-fa50-43d7-9a20-f479f7b2d161'
  ReservedCode2: 'f9df9840-fa50-43d7-9a20-f479f7b2d161'
---

# 夏收行动部署看板

百日攻坚"夏收"行动部署看板，把电信营销战役部署方案按 **战役 → 战区 → 路径 → 场景** 四级层级可视化，并按角色权限分级展示。总经理可在管理后台检索人员、分配权限、编辑板块内容。

## 技术栈

- 后端：Python 3 + FastAPI + Uvicorn
- 数据库：MySQL 8（库名 `xiashou2`）
- 前端：原生 HTML/CSS/JS（中国风水墨军事主题，无框架）
- 连接池：DBUtils (PooledDB)

## 目录结构

```
data_board/
├── server.py              # FastAPI 应用（路由 + 业务逻辑）
├── db.py                  # MySQL 连接池与查询辅助
├── static/
│   ├── index.html         # 主看板（角色登录 + 战役/战区浏览）
│   └── admin.html         # 总经理管理后台
├── 副本夏收工作部署.xlsx   # 数据源（表头即数据库主表字段）
├── data/                  # 历史 JSON 文件（已停用，仅留备份）
└── .temp/                 # 脚本（建表/导入/测试，不入库）
    ├── init_db.py         # 数据库初始化（建表 + 导入Excel + 初始化用户/权限）
    ├── read_excel.py      # Excel 读取工具
    ├── test_backend.py    # 后端冒烟测试
    └── cleanup.py         # 测试数据清理
```

## 快速开始

### 1. 环境准备

```bash
pip install fastapi "uvicorn[standard]" pymysql dbutils openpyxl python-multipart
```

MySQL 本地启动，确认 `root/root` 可登录，创建空库：

```sql
CREATE DATABASE xiashou2 CHARACTER SET utf8mb4;
```

### 2. 初始化数据库

```bash
python .temp/init_db.py
```

脚本会自动完成：
- 建 5 张表（users / battles / warzones / deployment_records / role_access）
- 导入 6 战役、4 战区字典
- 创建 15 个登录账号（默认密码 `123456`）
- 从 `副本夏收工作部署.xlsx` 导入业务记录
- 基于数据中的"作战角色"字段生成默认权限规则

> 脚本可重复执行，非空表会跳过；如需重新导入，先 `TRUNCATE` 对应表。

### 3. 启动服务

```bash
python server.py
# 访问 http://127.0.0.1:8001/
```

## 默认账号

| 角色 | 登录账号 | 密码 | 权限 |
|---|---|---|---|
| 总经理 | `总经理` | `123456` | 全部数据 + 管理后台 |
| 分局长（公）/ 直销 / 工程师（公）/ ... | 同岗位名 | `123456` | 仅授权板块 |

> `users.username` 默认等于中文岗位名，故前端"选角色登录"无需改动。一个岗位将来要支持多人时，新增 username 不同、role_id 一致的记录即可。

## 数据库表设计

### users（用户表）
登录账号 + 岗位 + 战区归属。`phone` 字段已预留，暂不用于登录。

| 字段 | 说明 |
|---|---|
| username | 登录账号（默认=岗位名） |
| name / role_id / role_name | 姓名 / 岗位标识 / 岗位显示名 |
| phone | 电话（预留） |
| password_hash / password_salt | SHA256 加盐 |
| zone / zone_name / color | 所属战区 |
| is_admin | 1=总经理（全权限） |
| is_active | 1=在用，0=停用（软删除） |

### deployment_records（部署记录主表）
直接对应 Excel 的 20 列表头，用 `battle_id`/`warzone_id` 外键精确关联字典表，替代原中文子串匹配。

### role_access（权限规则表）
`role_id × battle_id × warzone_id` 三元组，决定普通角色能看到哪些"战役+战区"板块。总经理在管理后台勾选矩阵即可分配。

### battles / warzones（字典表）
6 战役、4 战区的 id/name/color/sort_order。

## 权限模型

- **总经理**（is_admin=1）：可见全部数据，可访问 `/admin` 管理后台
- **普通角色**：仅可见 `role_access` 中授权的 (战役, 战区) 组合下的记录
- 初始权限由 `init_db.py` 根据数据行的"作战角色"字段自动推断；之后由总经理在管理后台调整

## API 概览

### 业务接口（保持原契约，前端无感迁移）
- `GET /api/roles` — 登录页角色下拉
- `POST /api/login` — 登录（role_id 或 username 任一）
- `GET /api/overview` — 主页概览
- `GET /api/battle-zones/{id}` — 战役下战区列表
- `GET /api/zone-battles/{id}` — 战区下战役列表
- `GET /api/detail/{bid}/{zid}` — 战役+战区交叉详情
- `GET /api/path-detail/{bid}/{zid}/{pid}` — 路径下场景列表

### 管理接口（仅总经理）
- `GET /api/admin/dashboard` — 数据概览
- `GET/POST/PUT/DELETE /api/admin/users` — 人员 CRUD + 检索（参数 q）
- `GET/PUT /api/admin/access` — 权限矩阵读写
- `GET/POST/PUT/DELETE /api/admin/records` — 记录 CRUD
- `GET /api/admin/record-schema` — 记录字段定义（前端动态渲染表单）

## 重构说明（相对旧版）

| 项目 | 旧版 | 新版 |
|---|---|---|
| 数据源 | JSON 文件 | MySQL |
| 权限判定 | 中文子串匹配（误匹配风险） | role_access 表外键关联 |
| 战役名 | 前端硬编码"双线+标准"（错） | 数据库为准"双线标准" |
| 合并单元格填充 | 无差别向下填充（跨战役串数据） | 层级感知填充（战役切换重置下层） |
| 管理能力 | 无 | 总经理可检索人员/分配权限/编辑板块 |