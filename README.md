---
AIGC:
  ContentProducer: '001191110102MAD55U9H0F10002'
  ContentPropagator: '001191110102MAD55U9H0F10002'
  Label: '1'
  ProduceID: '2239fee3-3cac-48b3-995e-f5dc22dd8634'
  PropagateID: '2239fee3-3cac-48b3-995e-f5dc22dd8634'
  ReservedCode1: '02529983-b076-4871-a82d-93a1fb85caaa'
  ReservedCode2: '02529983-b076-4871-a82d-93a1fb85caaa'
---

# 夏收行动部署看板

百日攻坚"夏收"行动部署看板，把电信营销战役部署方案按 **战役 → 战区 → 路径 → 场景** 四级层级可视化，并按角色权限分级展示。包含资料中心、辅助工具两大独立模块，总经理可在管理后台检索人员、分配权限、编辑板块内容。

## 技术栈

- 后端：Python 3.11 + FastAPI + Uvicorn
- 数据库：MySQL 8（库名 `xiashou2`，utf8mb4）
- 前端：原生 HTML/CSS/JS（中国风水墨军事主题，无框架）
- 连接池：DBUtils (PooledDB)
- 部署：Docker Compose（MySQL + App + Nginx 三容器编排）

## 目录结构

```
data_board/
├── server.py              # FastAPI 应用（路由 + 业务逻辑）
├── db.py                  # MySQL 连接池与查询辅助
├── init-db.sql            # 数据库初始化（Docker 首次启动自动执行）
├── static/
│   ├── index.html         # 主看板（登录 + 战役/战区浏览 + 资料中心 + 辅助工具）
│   ├── admin.html         # 管理后台
│   ├── css/               # index.css + admin.css
│   └── js/                # index.js + admin.js
├── info/                  # 资料中心文件（Docker 卷持久化，不入库）
├── tools/                 # 辅助工具 HTML 文件与图标（Docker 卷持久化，不入库）
├── Dockerfile             # 应用镜像构建
├── docker-compose.yml     # 三容器编排（MySQL + App + Nginx）
├── nginx.conf             # Nginx 反向代理配置
├── .env.example           # 环境变量模板
└── .temp/                 # 脚本（建表/导入/测试/迁移，不入库）
    ├── migrate_tools.sql  # 辅助工具模块迁移脚本（已部署的库执行）
    ├── init_db.py         # 数据库初始化（建表 + 导入Excel + 初始化用户/权限）
    ├── read_excel.py      # Excel 读取工具
    ├── test_backend.py    # 后端冒烟测试
    └── cleanup.py         # 测试数据清理
```

## 快速开始

### 方式一：Docker Compose 部署（生产推荐）

```bash
# 1. 配置环境变量
cp .env.example .env
vi .env   # 务必修改数据库密码

# 2. 构建并启动
docker compose up -d --build

# 3. 验证
curl http://localhost/api/roles
# 浏览器访问 http://服务器IP/
```

详细部署说明见 [部署文档.md](部署文档.md)。

### 方式二：本地开发

```bash
pip install -r requirements.txt

# MySQL 本地启动，创建空库
mysql -u root -p < init-db.sql

# 启动服务（调试模式）
uvicorn server:app --host 127.0.0.1 --port 8001 --reload
# 访问 http://127.0.0.1:8001/
```

## 登录认证

- 使用 **手机号 + 强密码** 登录（初始密码需含大小写字母+数字+特殊符号）
- 首次登录强制修改密码（`must_change_pwd=1`）
- 会话用 HMAC 签名 token（无状态，8 小时有效，多 worker 共享）
- 默认管理员：账号 `admin` / 密码 `Xs@2026`（首次登录必须改密）

## 权限模型（四级 + 模块/工具双层授权）

### 人员权限层级

| 层级 | 标识 | 能力 |
|---|---|---|
| 全局管理员 | is_admin=1 | 全部数据 + `/admin` 管理后台 |
| 战区管理员 | is_zone_admin=1 | 仅管理本战区人员和数据 |
| 指导员 | is_guide=1 | 可编辑板块内容，无人员增删权限 |
| 普通用户 | — | 仅查看授权范围内的板块 |

### 板块可见性（role_access 表）

普通用户能看到哪些"战役+战区"板块，由 `role_access` 表的 `role_id × battle_id × warzone_id` 三元组决定。总经理在管理后台勾选矩阵即可分配。

### 辅助工具模块/工具双层授权（叠加模式）

- **模块级授权**（`tool_module_access` 表）：授权某角色/个人可看到整个模块下所有工具
- **工具级授权**（`tool_access` 表）：对单个工具单独授权
- **叠加规则**：用户可见某工具 = 模块对该用户授权 **OR** 该工具单独对该用户授权
- 总经理默认可见全部，无需配置

## 数据库表设计（12 张表）

### 核心业务表

| 表 | 说明 |
|---|---|
| users | 用户表（手机号登录 + 岗位 + 战区 + 四级权限标识） |
| role_access | 板块权限规则（角色 × 战役 × 战区） |
| user_extra_roles | 用户额外角色（一人多角色，赋予后拥有该角色视角） |
| deployment_records | 部署记录主表（对应 Excel 20 列，外键关联字典表） |
| battles / warzones | 字典表（6 战役、4 战区） |

### 辅助工具模块

| 表 | 说明 |
|---|---|
| tool_modules | 工具模块（分类，可新建） |
| tools | 工具项（HTML 文件 / 外部链接 + 描述 + 图标 + 打开方式） |
| tool_module_access | 模块级权限（赋予到角色 / 赋予到个人） |
| tool_access | 工具级权限（赋予到角色 / 赋予到个人） |

### 审计日志

| 表 | 说明 |
|---|---|
| login_logs | 登录日志（成功/失败 + IP + UA） |
| access_logs | 权限操作日志（操作人/类型/目标 + IP） |

## 功能模块

### 主看板

- 角色登录后，主页展示六大战役、四大战区、兵种概览
- 资料中心：多级目录浏览、文件上传/下载/预览、拖拽排序、重命名
- 辅助工具：按权限展示工具卡片（HTML 内嵌预览 / 链接新窗口打开），自定义风格统一 Tooltip

### 管理后台（/admin）

- **数据概览**：人员、记录、权限规则、战役等统计
- **人员管理**：人员 CRUD + 检索、岗位管理、一人多角色配置、启用/停用
- **权限分配**：角色 × 战役 × 战区 权限矩阵（支持角色搜索）
- **内容编辑**：板块记录 CRUD（动态表单）
- **辅助工具**：模块管理、工具增删改、HTML/图标上传、模块级与工具级双层权限配置

## API 概览

### 业务接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/roles` | 登录页角色下拉 |
| POST | `/api/login` | 登录（手机号 + 密码） |
| POST | `/api/logout` | 退出 |
| GET | `/api/me` | 当前用户信息 |
| POST | `/api/change-password` | 修改密码 |
| GET | `/api/overview` | 主页概览 |
| GET | `/api/search` | 检索指导角色/作战角色 |
| GET | `/api/role-battles/{role_name}` | 角色可见战役 |
| GET | `/api/battle-zones/{id}` | 战役下战区列表 |
| GET | `/api/zone-battles/{id}` | 战区下战役列表 |
| GET | `/api/detail/{bid}/{zid}` | 战役+战区交叉详情 |
| GET | `/api/path-detail/{bid}/{zid}/{pid}` | 路径下场景列表 |
| GET | `/api/info/list[/{folder}]` | 资料中心目录列表 |
| GET | `/api/info/file/{path}` | 资料中心文件下载/预览 |
| GET | `/api/info/zip/{path}` | ZIP 文件内容列表 |
| GET | `/api/tools` | 辅助工具列表（按权限） |
| GET | `/api/tool-file/{path}` | 工具 HTML 文件访问 |
| GET | `/api/tool-icon/{path}` | 工具图标图片访问 |

### 管理接口（仅总经理/战区管理员）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/admin/dashboard` | 数据概览 |
| CRUD | `/api/admin/users` | 人员管理 + 检索（参数 q） |
| PUT | `/api/admin/users/{uid}/activate` | 启用/停用 |
| GET/PUT | `/api/admin/user-roles/{uid}` | 用户多角色配置 |
| CRUD | `/api/admin/positions` | 岗位管理 |
| GET/PUT | `/api/admin/access` | 板块权限矩阵读写 |
| CRUD | `/api/admin/records` | 板块记录管理 |
| PUT | `/api/admin/records/{rid}/field` | 单字段编辑 |
| GET | `/api/admin/record-schema` | 记录字段定义（动态表单） |
| POST/PUT/DELETE | `/api/admin/info/*` | 资料中心目录/文件管理（上传、新建、重命名、排序、删除） |
| CRUD | `/api/admin/tool-modules` | 辅助工具模块管理 |
| CRUD | `/api/admin/tools` | 工具项管理（含 HTML/图标上传） |
| GET/PUT | `/api/admin/tool-access/{mid}` | 模块级权限配置 |
| GET/PUT | `/api/admin/tool-item-access/{tid}` | 工具级权限配置 |

## 已部署系统的升级

代码更新后重新部署（数据库和文件数据不丢失）：

```bash
cd /部署路径/data_board
git pull origin main
docker compose up -d --build app
```

如本次更新包含数据库表结构变更，需额外执行迁移脚本：

```bash
docker exec -i xiashou-mysql mysql -u root -p你的密码 xiashou2 < .temp/migrate_tools.sql
```

## 重构说明（相对旧版）

| 项目 | 旧版 | 新版 |
|---|---|---|
| 数据源 | JSON 文件 | MySQL |
| 登录方式 | 岗位名 + 固定密码 | 手机号 + 强密码（首次强制改密） |
| 权限层级 | 管理员/普通 两级 | 全局管理员/战区管理员/指导员/普通 四级 |
| 权限判定 | 中文子串匹配（误匹配风险） | role_access 表外键关联 |
| 战役名 | 前端硬编码"双线+标准"（错） | 数据库为准"双线标准" |
| 合并单元格填充 | 无差别向下填充（跨战役串数据） | 层级感知填充（战役切换重置下层） |
| 管理能力 | 无 | 人员/岗位/权限/内容/资料/工具 全管理 |
| 资料中心 | 无 | 多级目录 + 文件管理 |
| 辅助工具 | 无 | HTML/链接展示 + 双层权限 + 图标上传 |
| 部署 | 手动 | Docker Compose 三容器编排 |