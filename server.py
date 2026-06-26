# -*- coding: utf-8 -*-
"""夏收行动部署看板 - FastAPI后端 (MySQL版)

重构要点：
  1. 数据源从 JSON 文件改为 MySQL（库 xiashou2）
  2. 用户表 users 含 phone 字段（暂不用于登录）
  3. 权限模型：role_access 表（角色 × 战役 × 战区），弃用中文子串匹配
  4. 总经理(is_admin=1) 可见全部，并能检索人员、分配权限、编辑板块
  5. 普通角色只能看到 role_access 中授权的 (战役,战区) 板块

API 兼容：原有 6 个业务接口签名不变，前端无需改动调用方式。
新增：/api/roles, /api/admin/* 一组管理接口。
"""
import os, hashlib, time, hmac, base64, json, secrets, threading, shutil, urllib.parse, re
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

app = FastAPI(title="夏收行动部署看板")

# 静态文件禁缓存中间件（开发环境避免浏览器缓存 JS/CSS）
@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# ====== 签名 Token（无状态，多 worker 共享）======
# 格式: base64(payload).base64(hmac_signature)
# payload: {username, role_id, is_admin, expire}
TOKEN_TTL = 3600 * 8  # 8 小时
_TOKEN_SECRET = os.getenv("TOKEN_SECRET", "xiashou-secret-2026")

def _sign(payload: dict) -> str:
    """生成 HMAC-SHA256 签名 token"""
    payload_b = base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode())
    sig = hmac.new(_TOKEN_SECRET.encode(), payload_b, hashlib.sha256).digest()
    sig_b = base64.urlsafe_b64encode(sig)
    return f"{payload_b.decode()}.{sig_b.decode()}"

def _verify(token: str) -> Optional[dict]:
    """验证签名 token，返回 payload 或 None"""
    if not token or '.' not in token:
        return None
    try:
        payload_b, sig_b = token.split('.', 1)
        expected_sig = hmac.new(_TOKEN_SECRET.encode(), payload_b.encode(), hashlib.sha256).digest()
        expected_sig_b = base64.urlsafe_b64encode(expected_sig).decode()
        if not hmac.compare_digest(sig_b, expected_sig_b):
            return None
        payload = json.loads(base64.urlsafe_b64decode(payload_b))
        if time.time() > payload.get("expire", 0):
            return None
        return payload
    except Exception:
        return None

# ====== 简易内存缓存（线程安全）======
_CACHE: Dict[str, tuple] = {}  # key → (value, expire_time)
_CACHE_LOCK = threading.Lock()

def cache_get(key: str, ttl: int = 60):
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and time.time() < item[1]:
            return item[0]
        _CACHE.pop(key, None)
    return None

def cache_set(key: str, value, ttl: int = 60):
    with _CACHE_LOCK:
        _CACHE[key] = (value, time.time() + ttl)

def cache_invalidate(prefix: str = ""):
    """使以 prefix 开头的所有缓存失效"""
    with _CACHE_LOCK:
        if not prefix:
            _CACHE.clear()
        else:
            keys = [k for k in _CACHE if k.startswith(prefix)]
            for k in keys:
                del _CACHE[k]


# ====== 认证辅助 ======
def verify_password(stored_hash: str, salt: str, pwd: str) -> bool:
    h = hashlib.sha256((pwd + salt).encode()).hexdigest()
    return h == stored_hash


def get_session(token: str) -> Optional[dict]:
    """验证签名 token，返回 payload 或 None（多 worker 共享，无需内存存储）"""
    return _verify(token)


def require_session(request: Request) -> dict:
    """从 query 或 header 取 token，未登录抛 401"""
    token = request.query_params.get("token") or request.headers.get("X-Token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录或会话已过期")
    return s


def require_admin(request: Request) -> dict:
    """仅总经理放行"""
    s = require_session(request)
    if not s.get("is_admin"):
        raise HTTPException(403, "需要总经理权限")
    return s


def require_zone_admin(request: Request) -> dict:
    """总经理或战区指导放行，返回 session（含 zone 限制信息）"""
    s = require_session(request)
    if s.get("is_admin"):
        return s
    if s.get("is_zone_admin"):
        return s
    raise HTTPException(403, "需要管理权限")


def require_edit(request: Request) -> dict:
    """放行可编辑内容的人员：管理员、战区管理员、指导员。返回 session
    同时查数据库确保权限即时生效（无需重新登录）"""
    s = require_session(request)
    if s.get("is_admin") or s.get("is_zone_admin"):
        return s
    if s.get("is_guide"):
        return s
    # 权限即时生效：session 中没有 is_guide，再查数据库确认
    u = db.query_one("SELECT is_guide FROM users WHERE username=%s AND is_active=1", (s["username"],))
    if u and u.get("is_guide"):
        s["is_guide"] = True
        return s
    raise HTTPException(403, "无编辑权限")


def get_zone_filter_edit(s: dict) -> Optional[str]:
    """编辑权限的战区过滤：管理员返回None(全部)，其余返回自身战区"""
    if s.get("is_admin"):
        return None
    return s.get("zone", "")


def get_zone_filter(s: dict) -> Optional[str]:
    """战区指导返回其 zone，总经理返回 None（不限战区）"""
    if s.get("is_admin"):
        return None
    if s.get("is_zone_admin"):
        return s.get("zone", "")
    return None


def get_user_info(username: str) -> Optional[dict]:
    row = db.query_one(
        "SELECT username,name,role_id,role_name,phone,zone,zone_name,color,is_admin,is_zone_admin,is_guide,must_change_pwd "
        "FROM users WHERE username=%s AND is_active=1", (username,))
    if not row:
        return None
    return {
        "id": row["role_id"],          # 兼容前端 role.id
        "username": row["username"],
        "name": row["name"],
        "role_id": row["role_id"],
        "role_name": row["role_name"],
        "phone": row["phone"] or "",
        "zone": row["zone"],
        "zone_name": row["zone_name"],
        "color": row["color"],
        "is_admin": bool(row["is_admin"]),
        "is_zone_admin": bool(row.get("is_zone_admin", 0)),
        "is_guide": bool(row.get("is_guide", 0)),
        "must_change_pwd": bool(row.get("must_change_pwd", 0)),
    }


# ====== 强密码校验 ======
def validate_strong_password(pwd: str) -> Optional[str]:
    """校验强密码：>=8位，含大小写字母+数字+特殊符号。返回 None=通过，否则返回错误描述"""
    if len(pwd) < 8:
        return "密码至少8位"
    if not re.search(r'[A-Z]', pwd):
        return "密码需包含大写字母"
    if not re.search(r'[a-z]', pwd):
        return "密码需包含小写字母"
    if not re.search(r'[0-9]', pwd):
        return "密码需包含数字"
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', pwd):
        return "密码需包含特殊符号(!@#$%^&*等)"
    return None


# ====== 作战角色正则匹配 ======
def match_combat_role(user_role_name: str, combat_role: str) -> bool:
    """判断用户的角色名是否包含在作战角色字段中。
    combat_role 格式可能为 'A'、'A+B+C'、'A、B、C' 等。
    匹配策略：按 + 或 、 分割后，用户角色精确匹配或被包含（只允许角色名包含part）。
    """
    if not user_role_name or not combat_role:
        return False
    parts = re.split(r'[+、，,]', combat_role)
    parts = [p.strip() for p in parts if p.strip()]
    for p in parts:
        # 精确匹配，或角色名是 part 的完整扩展（part 是角色名的子串，但不做反向）
        if user_role_name == p or p in user_role_name:
            return True
    return False


# ====== 日志辅助 ======
def _get_client_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def log_login(username: str, name: str, role_name: str, request: Request,
              success: bool, fail_reason: str = ""):
    """写入登录日志"""
    try:
        db.execute(
            "INSERT INTO login_logs(username,name,role_name,ip,user_agent,success,fail_reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (username, name, role_name, _get_client_ip(request),
             request.headers.get("User-Agent", "")[:256],
             1 if success else 0, fail_reason))
    except Exception:
        pass


def log_access(operator: str, operator_name: str, action: str,
               target_type: str, target_id: str, detail: str, request: Request):
    """写入权限操作日志"""
    try:
        db.execute(
            "INSERT INTO access_logs(operator,operator_name,action,target_type,target_id,detail,ip) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (operator, operator_name, action, target_type, target_id, detail,
             _get_client_ip(request)))
    except Exception:
        pass


# ====== 业务辅助 ======
SUBSTANTIVE_COLS = ["warzone_name", "warzone_target", "path_no", "path_name", "path_target",
                    "scene_no", "scene_name", "guide_role", "combat_role",
                    "opportunity_source", "control_cycle", "control_action",
                    "control_target", "policy", "incentive", "standard_talk",
                    "closed_loop_control", "process_flow"]


def has_substantive(r: dict) -> bool:
    """排除只有战役名称、无实质内容的占位行"""
    return any(str(r.get(c, "") or "").strip() for c in SUBSTANTIVE_COLS)


def get_user_all_roles(username: str) -> List[str]:
    """获取用户的所有角色名（主角色 + 额外赋予的角色）"""
    me = db.query_one("SELECT role_name FROM users WHERE username=%s AND is_active=1", (username,))
    if not me:
        return []
    roles = [me["role_name"]] if me["role_name"] else []
    extras = db.query_all("SELECT role_name FROM user_extra_roles WHERE username=%s", (username,))
    for r in extras:
        if r["role_name"] not in roles:
            roles.append(r["role_name"])
    return roles


def get_accessible_pairs(s: dict) -> List[tuple]:
    """返回该会话用户能看到的 (battle_id, warzone_id) 列表（基于角色名）；管理员返回 None"""
    if s.get("is_admin"):
        return None
    my_roles = get_user_all_roles(s["username"])
    if not my_roles:
        return []
    placeholders = ",".join(["%s"] * len(my_roles))
    rows = db.query_all(
        f"SELECT DISTINCT battle_id, warzone_id FROM role_access WHERE role_id IN ({placeholders})",
        my_roles)
    return [(r["battle_id"], r["warzone_id"]) for r in rows]


def get_role_rows(s: dict) -> List[dict]:
    """返回该用户可见的所有实质性记录
    权限层级：
      1. 管理员(is_admin)：全部数据
      2. 战区管理员(is_zone_admin)：本战区全部数据
      3. 普通人员：作战角色(combat_role)包含自己角色的场景 + role_access额外授权
    """
    if s.get("is_admin"):
        sql = "SELECT * FROM deployment_records ORDER BY sort_order, id"
        rows = db.query_all(sql)
        return [r for r in rows if has_substantive(r)]
    # 战区管理员：本战区全部数据
    if s.get("is_zone_admin"):
        rows = db.query_all(
            "SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order, id",
            (s.get("zone", ""),))
        return [r for r in rows if has_substantive(r)]
    # 指导员：本战区全部数据（可编辑内容，但无管理后台和增删权限）
    if s.get("is_guide"):
        rows = db.query_all(
            "SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order, id",
            (s.get("zone", ""),))
        return [r for r in rows if has_substantive(r)]
    # 普通人员：查自己的所有角色（主角色 + 额外角色）
    me = db.query_one("SELECT zone,role_name FROM users WHERE username=%s AND is_active=1", (s["username"],))
    if not me:
        return []
    user_zone = me["zone"]
    user_roles = get_user_all_roles(s["username"])
    if not user_roles:
        return []

    # 只查用户所属战区的记录（战区隔离）
    all_rows = db.query_all(
        "SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order, id",
        (user_zone,))
    result = []
    seen_ids = set()
    for r in all_rows:
        if not has_substantive(r):
            continue
        combat = str(r.get("combat_role", "") or "")
        if any(match_combat_role(ur, combat) for ur in user_roles):
            result.append(r)
            seen_ids.add(r["id"])

    # 2) role_access 额外授权（战役×战区组合）
    pairs = get_accessible_pairs(s)
    if pairs:
        for r in all_rows:
            if r["id"] in seen_ids:
                continue
            if not has_substantive(r):
                continue
            bid, wid = r.get("battle_id"), r.get("warzone_id")
            if (bid, wid) in pairs:
                result.append(r)
                seen_ids.add(r["id"])

    return result


def battle_lookup() -> Dict[str, dict]:
    v = cache_get("battles", 120)
    if v is not None:
        return v
    v = {b["id"]: b for b in db.query_all("SELECT * FROM battles ORDER BY sort_order")}
    cache_set("battles", v, 120)
    return v


def warzone_lookup() -> Dict[str, dict]:
    v = cache_get("warzones", 120)
    if v is not None:
        return v
    v = {w["id"]: w for w in db.query_all("SELECT * FROM warzones ORDER BY sort_order")}
    cache_set("warzones", v, 120)
    return v


def group_paths(rows: List[dict]) -> List[dict]:
    """从记录行聚合出路径列表（保持原 API 结构）"""
    paths = {}
    for r in rows:
        pid = str(r.get("path_no", "") or "").strip()
        pname = str(r.get("path_name", "") or "").strip()
        ptarget = str(r.get("path_target", "") or "").strip()
        if not pid or not pname or pid == "..." or pname == "...":
            continue
        if pid not in paths:
            paths[pid] = {"path_id": pid, "path_name": pname, "path_target": ptarget, "scene_count": 0}
        if str(r.get("scene_no", "") or "").strip():
            paths[pid]["scene_count"] += 1
    return list(paths.values())


def get_battle_basic(rows: List[dict]) -> Optional[dict]:
    first = None
    guide_roles = set()
    combat_roles = set()
    for r in rows:
        if not r.get("battle_name"):
            continue
        if first is None:
            first = r
        g = str(r.get("guide_role", "") or "").strip()
        c = str(r.get("combat_role", "") or "").strip()
        if g:
            for part in re.split(r'[/+、，,;；]', g):
                part = part.strip()
                if part:
                    guide_roles.add(part)
        if c:
            for part in re.split(r'[+、，,;；]', c):
                part = part.strip()
                if part:
                    combat_roles.add(part)
    if first is None:
        return None
    return {
        "战役编号": first.get("battle_no", ""),
        "战役": first["battle_name"],
        "战区": first.get("warzone_name", ""),
        "指导角色（营销统筹/专员）": "、".join(sorted(guide_roles)),
        "作战角色": "、".join(sorted(combat_roles)),
    }


def get_battle_targets(rows: List[dict]) -> Optional[dict]:
    bt = set()
    zt = set()
    for r in rows:
        if not r.get("battle_name"):
            continue
        b = str(r.get("battle_target", "") or "").strip()
        w = str(r.get("warzone_target", "") or "").strip()
        if b:
            bt.add(b)
        if w:
            zt.add(w)
    if not bt and not zt:
        return None
    return {
        "战役总目标": "、".join(sorted(bt)),
        "战区总目标": "、".join(sorted(zt)),
    }


def get_scenes(rows: List[dict], path_no: str) -> List[dict]:
    """路径下的场景列表（保持原字段名供前端直接渲染）"""
    scenes = []
    for r in rows:
        if str(r.get("path_no", "") or "").strip() != path_no:
            continue
        sid = str(r.get("scene_no", "") or "").strip()
        if not sid:
            continue
        scenes.append({
            "id": r.get("id"),
            "场景编号": sid,
            "场景名称": r.get("scene_title", ""),
            "场景（对到话术、作战角色）": r.get("scene_name", ""),
            "指导角色（营销统筹/专员）": r.get("guide_role", ""),
            "作战角色": r.get("combat_role", ""),
            "商机来源": r.get("opportunity_source", ""),
            "最短管控周期": r.get("control_cycle", ""),
            "最短管控动作（量）": r.get("control_action", ""),
            "最短管控目标（积分/金额）": r.get("control_target", ""),
            "政策": r.get("policy", ""),
            "激励": r.get("incentive", ""),
            "标准话术": r.get("standard_talk", ""),
            "闭环管控": r.get("closed_loop_control", ""),
            "受理到交付的流程": r.get("process_flow", ""),
        })
    return scenes


# ====== 页面 ======
@app.get("/")
def index():
    with open(os.path.join(BASE_DIR, "static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@app.get("/admin")
def admin_page():
    p = os.path.join(BASE_DIR, "static", "admin.html")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return HTMLResponse(f.read(), headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
    raise HTTPException(404, "管理页面未生成")


# ====== 公开 API ======
@app.get("/api/roles")
def roles():
    """登录页角色下拉数据源（含电话字段，暂不展示）"""
    rows = db.query_all(
        "SELECT username,role_id,role_name,zone,zone_name,color,is_admin "
        "FROM users WHERE is_active=1 ORDER BY is_admin DESC, zone, role_name")
    groups = {}
    for r in rows:
        g = "管理层" if r["is_admin"] else r["zone_name"]
        groups.setdefault(g, []).append({
            "id": r["role_id"], "name": r["role_name"],
            "zone": r["zone"], "zone_name": r["zone_name"], "color": r["color"],
        })
    return groups


@app.post("/api/login")
async def login(request: Request):
    """手机号+密码登录"""
    body = await request.json()
    phone = (body.get("phone") or body.get("username") or body.get("role_id") or "").strip()
    pwd = body.get("password") or ""
    if not phone or not pwd:
        raise HTTPException(400, "请输入手机号和密码")
    user = db.query_one("SELECT * FROM users WHERE phone=%s AND is_active=1", (phone,))
    if not user:
        # 兼容 admin 账号
        user = db.query_one("SELECT * FROM users WHERE username=%s AND is_active=1", (phone,))
    if not user or not verify_password(user["password_hash"], user["password_salt"], pwd):
        log_login(phone, "", "", request, False, "手机号或密码错误")
        raise HTTPException(401, "手机号或密码错误")
    info = get_user_info(user["username"])
    token = _sign({
        "username": user["username"],
        "role_id": user["role_id"],
        "is_admin": bool(user["is_admin"]),
        "is_zone_admin": bool(user.get("is_zone_admin", 0)),
        "is_guide": bool(user.get("is_guide", 0)),
        "zone": user.get("zone", ""),
        "must_change_pwd": bool(user.get("must_change_pwd", 0)),
        "expire": time.time() + TOKEN_TTL,
    })
    log_login(user["username"], user["name"], user["role_name"], request, True)
    return {"token": token, "role": info}


@app.post("/api/logout")
async def logout(request: Request):
    # 无状态 token，服务端无需删除，客户端丢弃即可
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    """当前登录人信息（前端可据此判断是否显示管理入口）"""
    s = require_session(request)
    return get_user_info(s["username"])


@app.post("/api/change-password")
async def change_password(request: Request):
    """修改自己的密码（首次登录强制改密 / 所有人可随时改密）"""
    s = require_session(request)
    body = await request.json()
    old_pwd = body.get("old_password") or ""
    new_pwd = body.get("new_password") or ""
    if not old_pwd or not new_pwd:
        raise HTTPException(400, "请输入旧密码和新密码")
    user = db.query_one("SELECT * FROM users WHERE username=%s AND is_active=1", (s["username"],))
    if not user or not verify_password(user["password_hash"], user["password_salt"], old_pwd):
        raise HTTPException(400, "旧密码错误")
    err = validate_strong_password(new_pwd)
    if err:
        raise HTTPException(400, err)
    if new_pwd == old_pwd:
        raise HTTPException(400, "新密码不能与旧密码相同")
    salt = secrets.token_hex(8)
    h = hashlib.sha256((new_pwd + salt).encode()).hexdigest()
    db.execute("UPDATE users SET password_hash=%s,password_salt=%s,must_change_pwd=0 WHERE username=%s",
               (h, salt, s["username"]))
    return {"ok": True}


# ====== 业务 API（保持原前端契约）======

@app.get("/api/overview")
def overview(request: Request):
    """主页概览：该角色有数据的战役和战区"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl = battle_lookup()
    wl = warzone_lookup()

    battle_stats = []
    bcount: Dict[str, int] = {}
    for r in rows:
        bid = r.get("battle_id")
        if bid:
            bcount[bid] = bcount.get(bid, 0) + 1
    for bid, cnt in bcount.items():
        b = bl.get(bid)
        if b:
            battle_stats.append({"id": b["id"], "name": b["name"], "color": b["color"], "count": cnt})

    zone_stats = []
    zcount: Dict[str, int] = {}
    for r in rows:
        zid = r.get("warzone_id")
        if zid:
            zcount[zid] = zcount.get(zid, 0) + 1
    # 普通用户和战区管理员只显示自己战区的兵种，管理员显示全部
    user_zone = None
    if not s.get("is_admin"):
        me = db.query_one("SELECT zone FROM users WHERE username=%s AND is_active=1", (s["username"],))
        if me:
            user_zone = me["zone"]
    # 查询兵种角色（过滤空 role_name）
    zone_roles_map: Dict[str, List[str]] = {}
    if user_zone:
        for u in db.query_all("SELECT zone, role_name FROM users WHERE is_active=1 AND is_admin=0 AND zone=%s AND role_name!=''", (user_zone,)):
            zone_roles_map.setdefault(u["zone"], []).append(u["role_name"])
    else:
        for u in db.query_all("SELECT zone, role_name FROM users WHERE is_active=1 AND is_admin=0 AND role_name!=''"):
            zone_roles_map.setdefault(u["zone"], []).append(u["role_name"])
    # 普通用户只返回本战区，管理员返回全部
    visible_zones = [user_zone] if user_zone else list(zcount.keys())
    for zid in visible_zones:
        cnt = zcount.get(zid, 0)
        w = wl.get(zid)
        if w and cnt > 0:
            # 获取该战区所有兵种名（去重）
            seen = set()
            all_roles = [r for r in zone_roles_map.get(zid, []) if not (r in seen or seen.add(r))]
            # 只保留有匹配数据的兵种（combat_role 匹配）
            zone_records = [r for r in rows if r.get("warzone_id") == zid]
            visible_roles = []
            for role in all_roles:
                has_data = any(match_combat_role(role, str(r.get("combat_role", "") or "")) for r in zone_records)
                if has_data:
                    visible_roles.append(role)
            zone_stats.append({"id": w["id"], "name": w["name"], "color": w["color"],
                               "count": cnt, "roles": visible_roles})

    return {"role": get_user_info(s["username"]),
            "my_roles": get_user_all_roles(s["username"]) if not s.get("is_admin") else [],
            "battles": battle_stats,
            "zones": zone_stats, "total": len(rows)}


@app.get("/api/search")
def search(request: Request, keyword: str = ""):
    """按指导角色/作战角色检索部署记录（结果按当前用户权限过滤）"""
    s = require_session(request)
    kw = (keyword or "").strip()
    if not kw:
        return {"keyword": "", "results": [], "total": 0}
    rows = get_role_rows(s)
    bl, wl = battle_lookup(), warzone_lookup()
    matched = []
    for r in rows:
        guide = str(r.get("guide_role", "") or "")
        combat = str(r.get("combat_role", "") or "")
        scene = str(r.get("scene_name", "") or "")
        if kw in guide or kw in combat or kw in scene:
            b = bl.get(r.get("battle_id"), {})
            w = wl.get(r.get("warzone_id"), {})
            matched.append({
                "battle_id": r.get("battle_id", ""),
                "battle_name": r.get("battle_name", ""),
                "warzone_id": r.get("warzone_id", ""),
                "warzone_name": r.get("warzone_name", ""),
                "path_no": r.get("path_no", ""),
                "path_name": r.get("path_name", ""),
                "scene_no": r.get("scene_no", ""),
                "scene_name": r.get("scene_name", ""),
                "guide_role": guide,
                "combat_role": combat,
                "policy": r.get("policy", ""),
                "battle_color": b.get("color", ""),
                "warzone_color": w.get("color", ""),
            })
    return {"keyword": kw, "results": matched, "total": len(matched)}


@app.get("/api/role-battles/{role_name}")
def role_battles(role_name: str, request: Request, zone: str = ""):
    """查看某角色的战役信息（兵种标签点击）
    根据角色名，查询 combat_role 包含该角色的部署记录，
    返回战役×战区分布。zone 参数指定战区（管理员点击非本战区兵种时）。
    """
    s = require_session(request)
    role_name = (role_name or "").strip()
    if not role_name:
        raise HTTPException(400, "角色名不能为空")

    bl, wl = battle_lookup(), warzone_lookup()
    # 有 zone 参数时按指定战区查询（管理员点击跨战区兵种）
    if zone:
        rows = db.query_all("SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order,id", (zone,))
    elif s.get("is_admin"):
        rows = db.query_all("SELECT * FROM deployment_records ORDER BY sort_order,id")
    elif s.get("is_zone_admin"):
        rows = db.query_all("SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order,id",
                            (s.get("zone", ""),))
    else:
        rows = get_role_rows(s)

    rows = [r for r in rows if has_substantive(r)]
    # 按 combat_role 匹配过滤
    matched = [r for r in rows if match_combat_role(role_name, str(r.get("combat_role", "") or ""))]

    battle_map: Dict[str, Dict[str, int]] = {}
    for r in matched:
        bid, zid = r.get("battle_id"), r.get("warzone_id")
        if bid and zid:
            battle_map.setdefault(bid, {})[zid] = battle_map.get(bid, {}).get(zid, 0) + 1

    battles = []
    for bid in sorted(battle_map.keys()):
        b = bl.get(bid)
        if not b:
            continue
        zones = []
        total = 0
        for zid, zcnt in battle_map[bid].items():
            w = wl.get(zid)
            if w:
                zones.append({"id": w["id"], "name": w["name"], "color": w["color"], "count": zcnt})
                total += zcnt
        battles.append({"id": b["id"], "name": b["name"], "color": b["color"],
                        "count": total, "zones": zones})

    return {"role_name": role_name, "battles": battles, "total": sum(b["count"] for b in battles)}


@app.get("/api/battle-zones/{battle_id}")
def battle_zones(battle_id: str, request: Request):
    """战役子页面：该战役下有哪些战区有数据"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl = battle_lookup()
    wl = warzone_lookup()
    b = bl.get(battle_id)
    if not b:
        raise HTTPException(404, "战役不存在")
    b_rows = [r for r in rows if r.get("battle_id") == battle_id]

    zone_list = []
    zcount: Dict[str, int] = {}
    for r in b_rows:
        zid = r.get("warzone_id")
        if zid:
            zcount[zid] = zcount.get(zid, 0) + 1
    for zid, cnt in zcount.items():
        w = wl.get(zid)
        if w:
            zone_list.append({"id": w["id"], "name": w["name"], "color": w["color"], "count": cnt})
    battle_target = ""
    bt_count: Dict[str, int] = {}
    for r in b_rows:
        bt = str(r.get("battle_target", "") or "").strip()
        if bt and bt != "-":
            bt_count[bt] = bt_count.get(bt, 0) + 1
    if bt_count:
        battle_target = max(bt_count, key=bt_count.get)
    return {"role": get_user_info(s["username"]),
            "battle": {"id": b["id"], "name": b["name"], "color": b["color"], "target": battle_target},
            "zones": zone_list, "total": len(b_rows)}


@app.get("/api/zone-battles/{zone_id}")
def zone_battles(zone_id: str, request: Request):
    """战区子页面：该战区下有哪些战役有数据"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl = battle_lookup()
    wl = warzone_lookup()
    w = wl.get(zone_id)
    if not w:
        raise HTTPException(404, "战区不存在")
    z_rows = [r for r in rows if r.get("warzone_id") == zone_id]

    battle_list = []
    bcount: Dict[str, int] = {}
    for r in z_rows:
        bid = r.get("battle_id")
        if bid:
            bcount[bid] = bcount.get(bid, 0) + 1
    for bid, cnt in bcount.items():
        b = bl.get(bid)
        if b:
            battle_list.append({"id": b["id"], "name": b["name"], "color": b["color"], "count": cnt})
    # 兵种角色：从 users 表获取
    roles = [u["role_name"] for u in db.query_all(
        "SELECT DISTINCT role_name FROM users WHERE zone=%s AND is_active=1 AND is_admin=0", (zone_id,))]
    return {"role": get_user_info(s["username"]),
            "zone": {"id": w["id"], "name": w["name"], "color": w["color"], "roles": roles},
            "battles": battle_list, "total": len(z_rows)}


@app.get("/api/detail/{battle_id}/{zone_id}")
def cross_detail(battle_id: str, zone_id: str, request: Request, role: str = ""):
    """数据详情：战役+战区交叉过滤。role 参数按作战角色过滤"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl, wl = battle_lookup(), warzone_lookup()
    b, w = bl.get(battle_id), wl.get(zone_id)
    if not b or not w:
        raise HTTPException(404, "战役或战区不存在")
    cross = [r for r in rows if r.get("battle_id") == battle_id and r.get("warzone_id") == zone_id]
    if role:
        role = role.strip()
        cross = [r for r in cross if match_combat_role(role, str(r.get("combat_role", "") or ""))]
    return {
        "role": get_user_info(s["username"]),
        "battle": {"id": b["id"], "name": b["name"], "color": b["color"]},
        "zone": {"id": w["id"], "name": w["name"], "color": w["color"]},
        "basic": get_battle_basic(cross),
        "targets": get_battle_targets(cross),
        "paths": group_paths(cross),
        "total": len(cross),
    }


@app.get("/api/path-detail/{battle_id}/{zone_id}/{path_id}")
def path_detail(battle_id: str, zone_id: str, path_id: str, request: Request, role: str = ""):
    """路径详情：场景列表。role 参数按作战角色过滤"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl, wl = battle_lookup(), warzone_lookup()
    b, w = bl.get(battle_id), wl.get(zone_id)
    cross = [r for r in rows if r.get("battle_id") == battle_id and r.get("warzone_id") == zone_id]
    if role:
        role = role.strip()
        cross = [r for r in cross if match_combat_role(role, str(r.get("combat_role", "") or ""))]
    path_info = None
    for r in cross:
        if str(r.get("path_no", "") or "").strip() == path_id:
            path_info = {"path_id": path_id, "path_name": r.get("path_name", ""),
                         "path_target": r.get("path_target", "")}
            break
    scenes = get_scenes(cross, path_id)
    return {
        "role": get_user_info(s["username"]),
        "battle": {"id": b["id"], "name": b["name"], "color": b["color"]} if b else None,
        "zone": {"id": w["id"], "name": w["name"], "color": w["color"]} if w else None,
        "path": path_info, "scenes": scenes, "total": len(scenes),
    }


# ====== 管理 API（仅总经理）======

# 记录字段定义（DB列名 → 中文标签 → 控件类型），供前端动态渲染编辑表单
RECORD_FIELDS = [
    ("battle_no", "战役编号", "text"),
    ("battle_name", "战役", "text"),
    ("battle_target", "战役总目标", "textarea"),
    ("warzone_name", "战区", "select_warzone"),
    ("warzone_target", "战区总目标", "textarea"),
    ("path_no", "路径编号", "text"),
    ("path_name", "路径", "text"),
    ("path_target", "路径目标", "textarea"),
    ("scene_no", "场景编号", "text"),
    ("scene_title", "场景名称", "text"),
    ("scene_name", "场景（对到话术、作战角色）", "textarea"),
    ("guide_role", "指导角色（营销统筹/专员）", "text"),
    ("combat_role", "作战角色", "text"),
    ("opportunity_source", "商机来源", "text"),
    ("control_cycle", "最短管控周期", "text"),
    ("control_action", "最短管控动作（量）", "textarea"),
    ("control_target", "最短管控目标（积分/金额）", "textarea"),
    ("policy", "政策", "textarea"),
    ("incentive", "激励", "textarea"),
    ("standard_talk", "标准话术", "textarea"),
    ("closed_loop_control", "闭环管控（注：要写清楚融入到531、642、321中去）", "textarea"),
    ("process_flow", "受理到交付的流程", "textarea"),
]
RECORD_DB_COLS = [f[0] for f in RECORD_FIELDS]


@app.get("/api/admin/dashboard")
def admin_dashboard(request: Request):
    """管理首页统计"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    u_total = db.query_one("SELECT COUNT(*) c FROM users WHERE is_active=1" + (" AND zone=%s" if zf else ""), (zf,) if zf else ())["c"]
    r_total = db.query_one("SELECT COUNT(*) c FROM deployment_records" + (" WHERE warzone_id=%s" if zf else ""), (zf,) if zf else ())["c"]
    a_total = db.query_one("SELECT COUNT(*) c FROM role_access")["c"]
    battles = db.query_all("SELECT * FROM battles ORDER BY sort_order")
    warzones = db.query_all("SELECT * FROM warzones ORDER BY sort_order")
    # 各战区人员数
    if zf:
        zone_users = db.query_all(
            "SELECT zone, COUNT(*) c FROM users WHERE is_active=1 AND is_admin=0 AND zone=%s GROUP BY zone", (zf,))
    else:
        zone_users = db.query_all(
            "SELECT zone, COUNT(*) c FROM users WHERE is_active=1 AND is_admin=0 GROUP BY zone")
    return {
        "users": u_total, "records": r_total, "access_rules": a_total,
        "battles": battles, "warzones": warzones, "is_zone_admin": bool(zf),
        "zone_name": s.get("zone_name","") if zf else "",
        "zone_users": {r["zone"]: r["c"] for r in zone_users},
    }


# ---- 人员管理 ----
@app.get("/api/admin/users")
def admin_users(request: Request, q: str = "", zone: str = ""):
    """人员列表（支持关键词 q 与战区过滤）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    sql = ("SELECT id,username,name,role_id,role_name,phone,zone,zone_name,color,is_admin,is_zone_admin,is_guide,is_active,must_change_pwd,"
           "created_at FROM users WHERE 1=1")
    args = []
    # 战区指导只能看本战区人员
    if zf:
        sql += " AND zone=%s"; args.append(zf)
    if q:
        sql += " AND (name LIKE %s OR role_name LIKE %s OR phone LIKE %s OR username LIKE %s)"
        kw = f"%{q}%"
        args += [kw, kw, kw, kw]
    if zone and not zf:
        sql += " AND zone=%s"
        args.append(zone)
    sql += " ORDER BY is_admin DESC, is_zone_admin DESC, zone, role_name"
    rows = db.query_all(sql, args)
    return {"total": len(rows), "users": rows, "me": get_user_info(s["username"]), "is_zone_admin": bool(zf)}


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    """新增人员"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    username = (body.get("username") or "").strip()  # 手机号
    role_name = (body.get("role_name") or "").strip()
    zone = (body.get("zone") or "public").strip()
    if not username or not role_name:
        raise HTTPException(400, "手机号与角色必填")
    # 战区管理员只能在所属战区新增人员
    if zf and zone != zf:
        raise HTTPException(403, "只能在所属战区新增人员")
    if db.query_one("SELECT id FROM users WHERE username=%s OR phone=%s", (username, username)):
        raise HTTPException(400, "该手机号已存在")
    wl = warzone_lookup()
    w = wl.get(zone) or next(iter(wl.values()), {"name": "公众战区", "color": "#1565c0"})
    salt = secrets.token_hex(8)
    pwd = (body.get("password") or "Xs@2026").strip()
    # 新增人员时校验强密码
    err = validate_strong_password(pwd)
    if err:
        raise HTTPException(400, f"初始密码不符合规范：{err}")
    h = hashlib.sha256((pwd + salt).encode()).hexdigest()
    is_zone_admin = 1 if body.get("is_zone_admin") else 0
    is_guide = 1 if body.get("is_guide") else 0
    # 战区管理员不能创建全局管理员
    is_admin = 1 if body.get("is_admin") and not zf else 0
    nid = db.execute(
        "INSERT INTO users(username,name,role_id,role_name,phone,password_hash,password_salt,must_change_pwd,"
        "zone,zone_name,color,is_admin,is_zone_admin,is_guide) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (username, body.get("name") or role_name, username, role_name, username,
         h, salt, 1, zone, w["name"], w["color"], is_admin, is_zone_admin, is_guide))
    log_access(s["username"], s.get("name", ""), "create", "user", str(nid),
               json.dumps({"username": username, "name": body.get("name"), "role_name": role_name, "zone": zone}, ensure_ascii=False),
               request)
    return {"ok": True, "id": nid}


@app.put("/api/admin/users/{uid}")
async def admin_update_user(uid: int, request: Request):
    """编辑人员（支持改密码/电话/姓名/战区/角色/管理员标记）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    cur = db.query_one("SELECT * FROM users WHERE id=%s", (uid,))
    if not cur:
        raise HTTPException(404, "人员不存在")
    # 战区管理员只能编辑本战区人员
    if zf and cur["zone"] != zf:
        raise HTTPException(403, "只能编辑所属战区的人员")
    name = body.get("name", cur["name"])
    phone = body.get("phone", cur["phone"]) or body.get("username", cur["username"])
    zone = body.get("zone", cur["zone"])
    # 战区管理员不能把人员转到其他战区
    if zf and zone != zf:
        raise HTTPException(403, "不能转移到其他战区")
    # 权限标记：战区管理员不能提升为全局管理员
    if zf:
        is_admin = cur["is_admin"]  # 保持不变
    else:
        is_admin = 1 if body.get("is_admin") else 0
    is_zone_admin = 1 if body.get("is_zone_admin") else 0
    # 战区管理员不能修改其他人的 is_zone_admin（避免互相提权）
    if zf and is_zone_admin and cur["is_zone_admin"] == 0:
        is_zone_admin = 0  # 普通管理员创建的不能设为战区管理员
    if not zf:
        is_zone_admin = 1 if body.get("is_zone_admin") else 0
    wl = warzone_lookup()
    w = wl.get(zone)
    zone_name = w["name"] if w else cur["zone_name"]
    color = w["color"] if w else cur["color"]
    role_name = body.get("role_name", cur["role_name"])
    # 指导员标记：全局管理员和战区管理员都可设置
    is_guide = 1 if body.get("is_guide") else 0
    # 有 zf 时战区管理员提升管理员标记有限制
    if body.get("password"):
        err = validate_strong_password(body["password"])
        if err:
            raise HTTPException(400, f"密码不符合规范：{err}")
        salt = secrets.token_hex(8)
        h = hashlib.sha256((body["password"] + salt).encode()).hexdigest()
        db.execute("UPDATE users SET name=%s,phone=%s,username=%s,role_name=%s,zone=%s,zone_name=%s,color=%s,"
                   "is_admin=%s,is_zone_admin=%s,is_guide=%s,password_hash=%s,password_salt=%s,must_change_pwd=1 WHERE id=%s",
                   (name, phone, phone, role_name, zone, zone_name, color,
                    is_admin, is_zone_admin, is_guide, h, salt, uid))
    else:
        db.execute("UPDATE users SET name=%s,phone=%s,username=%s,role_name=%s,zone=%s,zone_name=%s,color=%s,"
                   "is_admin=%s,is_zone_admin=%s,is_guide=%s WHERE id=%s",
                   (name, phone, phone, role_name, zone, zone_name, color,
                    is_admin, is_zone_admin, is_guide, uid))
    log_access(s["username"], s.get("name", ""), "update", "user", str(uid),
               json.dumps({"name": name, "role_name": role_name, "zone": zone,
                           "is_admin": is_admin, "is_zone_admin": is_zone_admin, "is_guide": is_guide}, ensure_ascii=False),
               request)
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: int, request: Request, hard: int = 0):
    """停用人员（软删除，is_active=0）；hard=1 时物理删除"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    me = db.query_one("SELECT id FROM users WHERE username=%s", (s["username"],))
    if str(uid) == str(me["id"]):
        raise HTTPException(400, "不能删除/停用自己")
    target = db.query_one("SELECT name,zone FROM users WHERE id=%s", (uid,))
    if not target:
        raise HTTPException(404, "人员不存在")
    if zf and target.get("zone") != zf:
        raise HTTPException(403, "只能删除所属战区的人员")
    target_name = target.get("name", "")
    if hard:
        db.execute("DELETE FROM users WHERE id=%s", (uid,))
    else:
        db.execute("UPDATE users SET is_active=0 WHERE id=%s", (uid,))
    log_access(s["username"], s.get("name", ""), "delete", "user", str(uid),
               json.dumps({"hard": hard, "target_name": target_name}, ensure_ascii=False), request)
    return {"ok": True}


# ---- 角色权限分配（按角色名） ----
@app.get("/api/admin/access")
def admin_get_access(request: Request, role_id: str = "", q: str = ""):
    """查询角色权限矩阵。role_id=角色名（如"客户经理"），q=搜索关键词"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    battles = db.query_all("SELECT * FROM battles ORDER BY sort_order")
    warzones = db.query_all("SELECT * FROM warzones ORDER BY sort_order")
    if role_id:
        rules = db.query_all("SELECT battle_id,warzone_id FROM role_access WHERE role_id=%s", (role_id,))
    else:
        rules = db.query_all("SELECT role_id,battle_id,warzone_id FROM role_access")
    granted = set()
    for r in rules:
        if role_id:
            granted.add((r["battle_id"], r["warzone_id"]))
    # 获取所有唯一角色名（按战区分组）
    if zf:
        raw_roles = db.query_all(
            "SELECT DISTINCT role_name, zone, zone_name FROM users WHERE is_admin=0 AND is_zone_admin=0 AND is_active=1 "
            "AND zone=%s AND role_name!='' ORDER BY zone_name, role_name", (zf,))
    else:
        raw_roles = db.query_all(
            "SELECT DISTINCT role_name, zone, zone_name FROM users WHERE is_admin=0 AND is_zone_admin=0 AND is_active=1 "
            "AND role_name!='' ORDER BY zone_name, role_name")
    # 搜索过滤
    if q:
        ql = q.lower()
        raw_roles = [r for r in raw_roles if ql in r["role_name"].lower()]
    # 按战区分组
    roles_grouped = {}
    for r in raw_roles:
        z = r["zone"]
        if z not in roles_grouped:
            roles_grouped[z] = {"zone": z, "zone_name": r["zone_name"], "roles": []}
        roles_grouped[z]["roles"].append(r["role_name"])
    roles_grouped_list = list(roles_grouped.values())
    # 兼容旧格式
    roles_flat = [{"role_id": rn, "role_name": rn} for grp in roles_grouped_list for rn in grp["roles"]]
    return {
        "battles": battles, "warzones": warzones,
        "roles": roles_flat,
        "roles_grouped": roles_grouped_list,
        "granted": [[g[0], g[1]] for g in granted] if role_id else rules,
        "zone_filter": zf,
    }


@app.put("/api/admin/access")
async def admin_set_access(request: Request):
    """批量设置某角色的可见板块（覆盖式）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    role_id = body.get("role_id")
    grants = body.get("grants", [])  # [{battle_id, warzone_id}, ...]
    if not role_id:
        raise HTTPException(400, "role_id（角色名）必填")
    # 战区管理员只能修改本战区存在的角色的权限
    if zf:
        exists = db.query_one(
            "SELECT id FROM users WHERE role_name=%s AND zone=%s AND is_active=1 LIMIT 1",
            (role_id, zf))
        if not exists:
            raise HTTPException(403, "只能分配本战区角色的权限")
    db.execute("DELETE FROM role_access WHERE role_id=%s", (role_id,))
    if grants:
        db.executemany("INSERT IGNORE INTO role_access(role_id,battle_id,warzone_id) VALUES(%s,%s,%s)",
                       [(role_id, g["battle_id"], g["warzone_id"]) for g in grants])
    operator_info = db.query_one("SELECT name FROM users WHERE username=%s", (s["username"],))
    log_access(s["username"], (operator_info or {}).get("name", ""), "grant", "role_access", role_id,
               json.dumps({"grants": len(grants)}, ensure_ascii=False), request)
    return {"ok": True, "granted": len(grants)}


# ---- 岗位管理 ----
@app.get("/api/admin/positions")
def admin_get_positions(request: Request):
    """查询各战区的岗位列表"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    if zf:
        rows = db.query_all(
            "SELECT role_name, zone, zone_name, SUM(is_placeholder=0) as cnt FROM users "
            "WHERE is_active=1 AND role_name!='' AND zone=%s "
            "GROUP BY role_name, zone, zone_name ORDER BY zone_name, role_name", (zf,))
    else:
        rows = db.query_all(
            "SELECT role_name, zone, zone_name, SUM(is_placeholder=0) as cnt FROM users "
            "WHERE is_active=1 AND role_name!='' "
            "GROUP BY role_name, zone, zone_name ORDER BY zone_name, role_name")
    grouped = {}
    for r in rows:
        z = r["zone"]
        if z not in grouped:
            grouped[z] = {"zone": z, "zone_name": r["zone_name"], "positions": []}
        grouped[z]["positions"].append({"role_name": r["role_name"], "count": r["cnt"]})
    return {"grouped": list(grouped.values())}


@app.post("/api/admin/positions")
async def admin_create_position(request: Request):
    """新增岗位（创建一个占位人员，用于后续分配权限/分配给用户）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    zone = body.get("zone", "")
    role_name = (body.get("role_name") or "").strip()
    if not zone or not role_name:
        raise HTTPException(400, "战区和岗位名必填")
    if zf and zone != zf:
        raise HTTPException(403, "只能管理本战区")
    wl = warzone_lookup()
    w = wl.get(zone)
    if not w:
        raise HTTPException(400, "战区不存在")
    # 检查是否已有该岗位
    exists = db.query_one(
        "SELECT id FROM users WHERE zone=%s AND role_name=%s AND is_active=1 LIMIT 1",
        (zone, role_name))
    if exists:
        raise HTTPException(400, "该战区已存在此岗位")
    # 创建占位人员（is_active=1 以便在岗位管理和兵种中可见）
    import time as _t
    placeholder_phone = f"pos_{zone}_{int(_t.time()*1000)%1000000}"
    salt = secrets.token_hex(8)
    h = hashlib.sha256(("PosPlaceholder" + salt).encode()).hexdigest()
    nid = db.execute(
        "INSERT INTO users(username,name,role_id,role_name,phone,password_hash,password_salt,must_change_pwd,"
        "zone,zone_name,color,is_admin,is_zone_admin,is_active,is_placeholder) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,1)",
        (placeholder_phone, role_name, placeholder_phone, role_name, placeholder_phone,
         h, salt, 1, zone, w["name"], w["color"], 0, 0))
    log_access(s["username"], s.get("name", ""), "create", "position", role_name,
               json.dumps({"zone": zone, "role_name": role_name}, ensure_ascii=False), request)
    return {"ok": True, "id": nid}


@app.put("/api/admin/positions")
async def admin_update_position(request: Request):
    """编辑岗位名（批量更新该战区下所有该岗位人员的 role_name）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    zone = body.get("zone", "")
    old_name = body.get("old_name", "")
    new_name = (body.get("new_name") or "").strip()
    if not zone or not old_name or not new_name:
        raise HTTPException(400, "参数不完整")
    if zf and zone != zf:
        raise HTTPException(403, "只能管理本战区")
    if old_name == new_name:
        return {"ok": True, "updated": 0}
    # 检查新名称是否冲突
    exists = db.query_one(
        "SELECT id FROM users WHERE zone=%s AND role_name=%s AND is_active=1 LIMIT 1",
        (zone, new_name))
    if exists:
        raise HTTPException(400, "该战区已存在同名岗位")
    n = db.execute(
        "UPDATE users SET role_name=%s WHERE zone=%s AND role_name=%s AND is_active=1",
        (new_name, zone, old_name))
    # 同步更新 role_access（角色名变了，权限规则也跟着变）
    db.execute("UPDATE role_access SET role_id=%s WHERE role_id=%s", (new_name, old_name))
    log_access(s["username"], s.get("name", ""), "update", "position", old_name,
               json.dumps({"zone": zone, "old": old_name, "new": new_name, "affected": n}, ensure_ascii=False), request)
    return {"ok": True, "updated": n}


@app.delete("/api/admin/positions")
def admin_delete_position(request: Request, zone: str, role_name: str):
    """删除岗位（清空该战区下该岗位人员的 role_name，或物理删除占位人员）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    if zf and zone != zf:
        raise HTTPException(403, "只能管理本战区")
    # 删除 role_access 中的相关权限
    db.execute("DELETE FROM role_access WHERE role_id=%s", (role_name,))
    # 清空该战区下所有该岗位人员的 role_name
    n = db.execute(
        "UPDATE users SET role_name='' WHERE zone=%s AND role_name=%s AND is_active=1",
        (zone, role_name))
    log_access(s["username"], s.get("name", ""), "delete", "position", role_name,
               json.dumps({"zone": zone, "role_name": role_name, "cleared": n}, ensure_ascii=False), request)
    return {"ok": True, "cleared": n}


# ---- 用户额外角色管理 ----
@app.get("/api/admin/user-roles/{uid}")
def admin_get_user_roles(uid: int, request: Request):
    """查询某用户的额外角色"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    user = db.query_one("SELECT * FROM users WHERE id=%s", (uid,))
    if not user:
        raise HTTPException(404, "人员不存在")
    if zf and user["zone"] != zf:
        raise HTTPException(403, "只能管理本战区人员")
    extras = db.query_all("SELECT role_name FROM user_extra_roles WHERE username=%s ORDER BY role_name",
                          (user["username"],))
    # 所有可选角色名（按战区分组）
    if zf:
        raw = db.query_all(
            "SELECT DISTINCT role_name, zone, zone_name FROM users "
            "WHERE is_active=1 AND role_name!='' AND zone=%s ORDER BY zone_name, role_name", (zf,))
    else:
        raw = db.query_all(
            "SELECT DISTINCT role_name, zone, zone_name FROM users "
            "WHERE is_active=1 AND role_name!='' ORDER BY zone_name, role_name")
    # 按 zone 分组
    zones_map = {}
    for r in raw:
        z = r["zone"]
        if z not in zones_map:
            zones_map[z] = {"zone": z, "zone_name": r["zone_name"], "roles": []}
        if r["role_name"] not in zones_map[z]["roles"]:
            zones_map[z]["roles"].append(r["role_name"])
    all_roles_grouped = list(zones_map.values())
    return {
        "username": user["username"],
        "name": user["name"],
        "primary_role": user["role_name"],
        "user_zone": user["zone"],
        "user_zone_name": user["zone_name"],
        "extra_roles": [r["role_name"] for r in extras],
        "all_roles": [r["role_name"] for r in raw],  # 兼容旧格式
        "all_roles_grouped": all_roles_grouped,
    }


@app.put("/api/admin/user-roles/{uid}")
async def admin_set_user_roles(uid: int, request: Request):
    """设置某用户的额外角色（覆盖式）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    user = db.query_one("SELECT * FROM users WHERE id=%s", (uid,))
    if not user:
        raise HTTPException(404, "人员不存在")
    if zf and user["zone"] != zf:
        raise HTTPException(403, "只能管理本战区人员")
    body = await request.json()
    roles = body.get("roles", [])
    username = user["username"]
    db.execute("DELETE FROM user_extra_roles WHERE username=%s", (username,))
    if roles:
        valid_roles = set()
        if zf:
            rows = db.query_all("SELECT DISTINCT role_name FROM users WHERE is_active=1 AND zone=%s", (zf,))
        else:
            rows = db.query_all("SELECT DISTINCT role_name FROM users WHERE is_active=1")
        valid_roles = {r["role_name"] for r in rows if r["role_name"]}
        clean = [r for r in roles if r in valid_roles and r != user["role_name"]]
        if clean:
            db.executemany("INSERT IGNORE INTO user_extra_roles(username,role_name) VALUES(%s,%s)",
                           [(username, r) for r in clean])
    log_access(s["username"], s.get("name", ""), "update", "user_roles", username,
               json.dumps({"extra_roles": roles}, ensure_ascii=False), request)
    return {"ok": True}


# ---- 启用用户 ----
@app.put("/api/admin/users/{uid}/activate")
def admin_activate_user(uid: int, request: Request):
    """启用已停用的用户"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    user = db.query_one("SELECT * FROM users WHERE id=%s", (uid,))
    if not user:
        raise HTTPException(404, "人员不存在")
    if zf and user["zone"] != zf:
        raise HTTPException(403, "只能操作本战区人员")
    db.execute("UPDATE users SET is_active=1 WHERE id=%s", (uid,))
    log_access(s["username"], s.get("name", ""), "activate", "user", str(uid),
               json.dumps({"name": user.get("name", "")}, ensure_ascii=False), request)
    return {"ok": True}


# ---- 板块记录管理 ----
@app.get("/api/admin/record-schema")
def admin_record_schema(request: Request):
    """记录字段定义（前端据此渲染编辑表单）"""
    require_zone_admin(request)
    return {"fields": [{"key": k, "label": l, "type": t} for k, l, t in RECORD_FIELDS],
            "battles": db.query_all("SELECT * FROM battles ORDER BY sort_order"),
            "warzones": db.query_all("SELECT * FROM warzones ORDER BY sort_order")}


@app.get("/api/admin/records")
def admin_records(request: Request, battle_id: str = "", zone_id: str = ""):
    """记录列表（支持战役/战区筛选）"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    sql = "SELECT * FROM deployment_records WHERE 1=1"
    args = []
    if zf:
        sql += " AND warzone_id=%s"; args.append(zf)
    if battle_id:
        sql += " AND battle_id=%s"; args.append(battle_id)
    if zone_id and not zf:
        sql += " AND warzone_id=%s"; args.append(zone_id)
    sql += " ORDER BY battle_id, warzone_id, sort_order, id"
    rows = db.query_all(sql, args)
    return {"total": len(rows), "records": rows}


@app.post("/api/admin/records")
async def admin_create_record(request: Request):
    """新增记录"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    data = {k: (body.get(k, "") or "") for k in RECORD_DB_COLS}
    bname = (data.get("battle_name") or "").replace("（例）", "").strip()
    zname = (data.get("warzone_name") or "").strip()
    bid = _battle_id(bname); zid = _warzone_id(zname)
    # 战区指导只能创建本战区记录
    if zf and zid != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    max_sort = db.query_one(
        "SELECT COALESCE(MAX(sort_order),0) m FROM deployment_records")["m"]
    nid = db.execute(
        f"INSERT INTO deployment_records(battle_id,warzone_id,{','.join(RECORD_DB_COLS)},sort_order,updated_by) "
        f"VALUES(%s,%s,{','.join(['%s']*len(RECORD_DB_COLS))},%s,%s)",
        [bid, zid] + [data[k] for k in RECORD_DB_COLS] + [max_sort + 1, s["username"]])
    return {"ok": True, "id": nid}


@app.put("/api/admin/records/{rid}")
async def admin_update_record(rid: int, request: Request):
    """编辑记录"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    rec = db.query_one("SELECT id,warzone_id FROM deployment_records WHERE id=%s", (rid,))
    if not rec:
        raise HTTPException(404, "记录不存在")
    if zf and rec["warzone_id"] != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    data = {k: (body.get(k, "") or "") for k in RECORD_DB_COLS}
    bname = (data.get("battle_name") or "").replace("（例）", "").strip()
    zname = (data.get("warzone_name") or "").strip()
    bid = _battle_id(bname); zid = _warzone_id(zname)
    if zf and zid != zf:
        raise HTTPException(403, "不能转移到其他战区")
    sets = ", ".join(f"{c}=%s" for c in RECORD_DB_COLS)
    db.execute(
        f"UPDATE deployment_records SET battle_id=%s,warzone_id=%s,{sets},updated_by=%s WHERE id=%s",
        [bid, zid] + [data[k] for k in RECORD_DB_COLS] + [s["username"], rid])
    return {"ok": True}


@app.delete("/api/admin/records/{rid}")
async def admin_delete_record(rid: int, request: Request):
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    rec = db.query_one("SELECT id,warzone_id FROM deployment_records WHERE id=%s", (rid,))
    if not rec:
        raise HTTPException(404, "记录不存在")
    if zf and rec["warzone_id"] != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    db.execute("DELETE FROM deployment_records WHERE id=%s", (rid,))
    return {"ok": True}


@app.put("/api/admin/records/{rid}/field")
async def admin_update_field(rid: int, request: Request):
    """单字段更新记录。body: {"field": "policy", "value": "新内容"}"""
    s = require_edit(request)
    zf = get_zone_filter_edit(s)
    rec = db.query_one("SELECT id,warzone_id FROM deployment_records WHERE id=%s", (rid,))
    if not rec:
        raise HTTPException(404, "记录不存在")
    if zf and rec["warzone_id"] != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    body = await request.json()
    field = body.get("field", "").strip()
    value = body.get("value", "")
    # 白名单校验，防注入
    allowed_fields = {f[0] for f in RECORD_FIELDS}
    if field not in allowed_fields:
        raise HTTPException(400, f"不允许修改字段: {field}")
    db.execute(f"UPDATE deployment_records SET {field}=%s, updated_by=%s WHERE id=%s",
               (value, s["username"], rid))
    return {"ok": True}


@app.put("/api/admin/path/update")
async def admin_update_path(request: Request):
    """批量更新某路径下所有记录的路径信息。
    body: {"battle_id":"b1","warzone_id":"public","path_no":"1","path_name":"新名称","path_target":"新目标"}
    """
    s = require_edit(request)
    zf = get_zone_filter_edit(s)
    body = await request.json()
    bid = body.get("battle_id", "")
    wid = body.get("warzone_id", "")
    pno = body.get("path_no", "")
    if zf and wid != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    updates = {}
    if body.get("path_name") is not None:
        updates["path_name"] = body["path_name"]
    if body.get("path_target") is not None:
        updates["path_target"] = body["path_target"]
    if not updates:
        raise HTTPException(400, "没有需要更新的字段")
    sets = ", ".join(f"{k}=%s" for k in updates) + ", updated_by=%s"
    args = list(updates.values()) + [s["username"]]
    args.extend([bid, wid, pno])
    n = db.execute(
        f"UPDATE deployment_records SET {sets} WHERE battle_id=%s AND warzone_id=%s AND path_no=%s",
        args)
    return {"ok": True, "updated": n}


@app.get("/api/admin/check-no")
def admin_check_no(request: Request, bid: str, zid: str, pno: str = "", scene_no: str = ""):
    """检查路径编号或场景编号是否重复"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    if zf and zid != zf:
        raise HTTPException(403, "只能检查本战区")
    if scene_no:
        cnt = db.query_one(
            "SELECT COUNT(*) c FROM deployment_records WHERE battle_id=%s AND warzone_id=%s AND path_no=%s AND scene_no=%s",
            (bid, zid, pno, scene_no))
    else:
        cnt = db.query_one(
            "SELECT COUNT(*) c FROM deployment_records WHERE battle_id=%s AND warzone_id=%s AND path_no=%s",
            (bid, zid, pno))
    return {"duplicate": cnt["c"] > 0, "count": cnt["c"]}


@app.get("/api/admin/next-no")
def admin_next_no(request: Request, bid: str, zid: str, pno: str = ""):
    """获取下一个可用的路径编号或场景编号"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    if zf and zid != zf:
        raise HTTPException(403, "只能操作本战区")
    if pno:
        # 查询该路径下最大场景编号
        rows = db.query_all(
            "SELECT scene_no FROM deployment_records WHERE battle_id=%s AND warzone_id=%s AND path_no=%s AND scene_no REGEXP '^[0-9]+$'",
            (bid, zid, pno))
        max_no = max((int(r["scene_no"]) for r in rows), default=0)
        return {"next_no": str(max_no + 1)}
    else:
        # 查询最大路径编号
        rows = db.query_all(
            "SELECT path_no FROM deployment_records WHERE battle_id=%s AND warzone_id=%s AND path_no REGEXP '^[0-9]+$'",
            (bid, zid))
        max_no = max((int(r["path_no"]) for r in rows), default=0)
        return {"next_no": str(max_no + 1)}


@app.delete("/api/admin/path/delete")
async def admin_delete_path(request: Request):
    """删除整条路径及其下所有场景"""
    s = require_zone_admin(request)
    zf = get_zone_filter(s)
    body = await request.json()
    bid, wid, pno = body.get("battle_id", ""), body.get("warzone_id", ""), body.get("path_no", "")
    if zf and wid != zf:
        raise HTTPException(403, "只能管理本战区的记录")
    n = db.execute(
        "DELETE FROM deployment_records WHERE battle_id=%s AND warzone_id=%s AND path_no=%s",
        (bid, wid, pno))
    return {"ok": True, "deleted": n}


def _battle_id(name: str) -> Optional[str]:
    if not name:
        return None
    r = db.query_one("SELECT id FROM battles WHERE name=%s", (name,))
    if r:
        return r["id"]
    r = db.query_one("SELECT id FROM battles WHERE name LIKE %s OR %s LIKE CONCAT(name,'%%')", (f"{name}%", name))
    return r["id"] if r else None


def _warzone_id(name: str) -> Optional[str]:
    if not name:
        return None
    r = db.query_one("SELECT id FROM warzones WHERE name=%s", (name,))
    return r["id"] if r else None


# ====== 资料中心（info 目录文件管理，支持子目录）======
INFO_DIR = os.path.join(BASE_DIR, "info")

# 可直接在浏览器预览的扩展名
_PREVIEW_EXTS = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.txt', '.md'}
# 允许上传的扩展名
_ALLOWED_EXTS = _PREVIEW_EXTS | {'.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
                                  '.zip', '.rar', '.7z', '.csv', '.mp4', '.mp3'}

import re as _re

def _strip_order_prefix(name: str) -> str:
    """去掉文件夹名前面的排序前缀 'NN_' 或 'NN.'"""
    return _re.sub(r'^\d{2}[._]\s*', '', name)


def _safe_info_path(subpath: str = "") -> str:
    """安全解析 info 子路径，防止路径穿越。
    自动匹配带排序前缀的实际文件名（如 '合规' → '00_合规'）。
    """
    base = os.path.normpath(INFO_DIR)
    sub = subpath.strip().strip('/').strip('\\')
    if not sub:
        return base
    current = base
    for segment in sub.replace('\\', '/').split('/'):
        if not segment:
            continue
        # 先精确匹配
        candidate = os.path.normpath(os.path.join(current, segment))
        if os.path.exists(candidate):
            current = candidate
            continue
        # 再尝试匹配去掉前缀后的名称（如 '合规' → '00_合规'）
        if os.path.isdir(current):
            matched = False
            for name in os.listdir(current):
                if _strip_order_prefix(name) == segment:
                    current = os.path.normpath(os.path.join(current, name))
                    matched = True
                    break
            if matched:
                continue
        # 都没匹配上，用原始路径（后续会 404）
        current = candidate
    if not current.startswith(base):
        raise HTTPException(400, "路径非法")
    return current


@app.get("/api/info/list")
@app.get("/api/info/list/{folder:path}")
def info_list(request: Request, folder: str = ""):
    """列出目录内容（子目录 + 文件），所有角色可访问"""
    require_session(request)
    dp = _safe_info_path(folder) if folder else INFO_DIR
    if not os.path.isdir(dp):
        raise HTTPException(404, "目录不存在")
    dirs, files = [], []
    all_items = os.listdir(dp)
    # 子目录按排序前缀排序，文件按名称排序
    dir_names = sorted([n for n in all_items if os.path.isdir(os.path.join(dp, n))])
    file_names = sorted([n for n in all_items if os.path.isfile(os.path.join(dp, n))])
    for name in dir_names:
        full = os.path.join(dp, name)
        # 统计该子目录下所有文件数（含子目录递归）
        count = sum(len(fs) for _, _, fs in os.walk(full))
        dirs.append({"name": _strip_order_prefix(name), "raw_name": name, "type": "dir", "count": count})
    for name in file_names:
        fp = os.path.join(dp, name)
        ext = os.path.splitext(name)[1].lower()
        files.append({
            "name": name, "size": os.path.getsize(fp), "ext": ext,
            "preview": ext in _PREVIEW_EXTS,
        })
    return {"path": folder.strip('/'), "dirs": dirs, "files": files}


@app.get("/api/info/file/{filepath:path}")
def info_file(filepath: str, request: Request):
    """下载或预览文件，所有角色可访问"""
    require_session(request)
    fp = _safe_info_path(filepath)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    fn = os.path.basename(fp)
    ext = os.path.splitext(fn)[1].lower()
    inline = ext in _PREVIEW_EXTS
    encoded = urllib.parse.quote(fn)
    return FileResponse(fp, filename=fn,
        headers={"Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{encoded}"})


@app.get("/api/info/zip/{filepath:path}")
def info_zip_list(filepath: str, request: Request):
    """列出 ZIP 文件内容"""
    require_session(request)
    import zipfile as _zip
    fp = _safe_info_path(filepath)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    try:
        with _zip.ZipFile(fp, 'r') as zf:
            entries = [{"name": i.filename, "size": i.file_size}
                       for i in zf.infolist() if not i.is_dir()]
            return {"name": os.path.basename(fp), "entries": entries, "total": len(entries)}
    except _zip.BadZipFile:
        raise HTTPException(400, "不是有效的ZIP文件")


@app.post("/api/admin/info/dir/{folder:path}")
def admin_mkdir(folder: str, request: Request):
    """创建目录（支持多级）"""
    require_zone_admin(request)
    dp = _safe_info_path(folder)
    if os.path.exists(dp):
        raise HTTPException(400, "目录已存在")
    os.makedirs(dp, exist_ok=True)
    return {"ok": True}


@app.put("/api/admin/info/rename/{folder:path}")
async def admin_rename(folder: str, request: Request):
    """重命名目录。body: {"new_name": "新名称"}"""
    require_zone_admin(request)
    body = await request.json()
    new_name = (body.get("new_name") or "").strip()
    if not new_name or '/' in new_name or '\\' in new_name or '..' in new_name:
        raise HTTPException(400, "新名称非法")
    dp = _safe_info_path(folder)
    if not os.path.isdir(dp):
        raise HTTPException(404, "目录不存在")
    if dp == os.path.normpath(INFO_DIR):
        raise HTTPException(400, "不能重命名根目录")
    new_path = os.path.join(os.path.dirname(dp), new_name)
    if os.path.exists(new_path):
        raise HTTPException(400, "名称已存在")
    os.rename(dp, new_path)
    return {"ok": True, "new_path": "/".join(folder.split("/")[:-1] + [new_name])}


@app.delete("/api/admin/info/dir/{folder:path}")
def admin_rmdir(folder: str, request: Request):
    """删除目录（递归删除内容）"""
    require_zone_admin(request)
    dp = _safe_info_path(folder)
    if not os.path.isdir(dp):
        raise HTTPException(404, "目录不存在")
    if dp == os.path.normpath(INFO_DIR):
        raise HTTPException(400, "不能删除根目录")
    shutil.rmtree(dp)
    return {"ok": True}


@app.put("/api/admin/info/reorder")
async def admin_reorder(request: Request):
    """重新排序同级目录。body: {"parent": "父路径", "items": ["raw_name1","raw_name2",...]}
    用数字前缀实现排序，已有前缀的会被覆盖。
    """
    require_zone_admin(request)
    body = await request.json()
    parent = (body.get("parent") or "").strip('/')
    items = body.get("items") or []
    if not items:
        raise HTTPException(400, "排序列表为空")
    base = _safe_info_path(parent) if parent else INFO_DIR
    if not os.path.isdir(base):
        raise HTTPException(404, "目录不存在")

    import re
    # 第一步：去掉所有已有前缀，还原原始名称
    rename_map = {}  # old_raw -> display_name
    for raw in items:
        raw = os.path.basename(raw)
        old_path = os.path.join(base, raw)
        if not os.path.isdir(old_path):
            continue
        display = re.sub(r'^\d{2}[._]\s*', '', raw)
        rename_map[raw] = display

    # 第二步：全部先重命名为唯一临时名（用 pid 防冲突）
    import tempfile
    tmp_dir = tempfile.mkdtemp(dir=base)
    tmp_map = {}  # display -> tmp_path
    for raw, display in rename_map.items():
        tmp_path = os.path.join(tmp_dir, display)
        os.rename(os.path.join(base, raw), tmp_path)
        tmp_map[display] = tmp_path

    # 第三步：从临时目录按新顺序移回，加前缀
    for idx, display in enumerate(rename_map.values()):
        prefix = f"{idx:02d}_"
        new_path = os.path.join(base, prefix + display)
        os.rename(tmp_map[display], new_path)

    # 清理临时目录
    os.rmdir(tmp_dir)
    return {"ok": True}


@app.post("/api/admin/info/upload")
@app.post("/api/admin/info/upload/{folder:path}")
async def admin_upload(folder: str = "", request: Request = None, file: UploadFile = File(...)):
    """上传文件到指定目录"""
    require_zone_admin(request)
    dp = _safe_info_path(folder) if folder else INFO_DIR
    if not os.path.isdir(dp):
        raise HTTPException(404, "目录不存在")
    fn = os.path.basename(file.filename or "unnamed")
    if '..' in fn or '/' in fn or '\\' in fn:
        raise HTTPException(400, "文件名非法")
    ext = os.path.splitext(fn)[1].lower()
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(400, f"不支持的文件类型: {ext}")
    fp = os.path.join(dp, fn)
    with open(fp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"ok": True, "name": fn, "size": os.path.getsize(fp)}


@app.delete("/api/admin/info/file/{filepath:path}")
def admin_delete_file(filepath: str, request: Request):
    """删除文件"""
    require_zone_admin(request)
    fp = _safe_info_path(filepath)
    if not os.path.isfile(fp):
        raise HTTPException(404, "文件不存在")
    os.remove(fp)
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
