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
import os, hashlib, time, secrets, threading
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

app = FastAPI(title="夏收行动部署看板")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# ====== 会话（内存，TTL 8 小时）======
SESSIONS: Dict[str, dict] = {}
SESSION_TTL = 3600 * 8
# 每 10 分钟清理过期会话
def _clean_sessions():
    now = time.time()
    expired = [k for k, v in SESSIONS.items() if now > v["expire"]]
    for k in expired:
        SESSIONS.pop(k, None)
    threading.Timer(600, _clean_sessions).start()
_clean_sessions()

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
    s = SESSIONS.get(token)
    if not s:
        return None
    if time.time() > s["expire"]:
        SESSIONS.pop(token, None)
        return None
    return s


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


def get_user_info(username: str) -> Optional[dict]:
    row = db.query_one(
        "SELECT username,name,role_id,role_name,phone,zone,zone_name,color,is_admin "
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
    }


# ====== 业务辅助 ======
SUBSTANTIVE_COLS = ["warzone_name", "warzone_target", "path_no", "path_name", "path_target",
                    "scene_no", "scene_name", "guide_role", "combat_role",
                    "opportunity_source", "control_cycle", "control_action",
                    "control_target", "policy", "incentive", "standard_talk",
                    "closed_loop_control", "process_flow"]


def has_substantive(r: dict) -> bool:
    """排除只有战役名称、无实质内容的占位行"""
    return any(str(r.get(c, "") or "").strip() for c in SUBSTANTIVE_COLS)


def get_accessible_pairs(s: dict) -> List[tuple]:
    """返回该会话用户能看到的 (battle_id, warzone_id) 列表；总经理返回 None 表示全部"""
    if s.get("is_admin"):
        return None
    rows = db.query_all(
        "SELECT DISTINCT battle_id, warzone_id FROM role_access WHERE role_id=%s",
        (s["role_id"],))
    return [(r["battle_id"], r["warzone_id"]) for r in rows]


def get_role_rows(s: dict) -> List[dict]:
    """返回该用户可见的所有实质性记录
    分局长/客户经理作为战区负责人，自动获得本战区全部数据权限。
    """
    if s.get("is_admin"):
        sql = "SELECT * FROM deployment_records ORDER BY sort_order, id"
        rows = db.query_all(sql)
        return [r for r in rows if has_substantive(r)]
    # 战区负责人（分局长/客户经理）：本战区全部数据
    me = db.query_one("SELECT zone,role_name FROM users WHERE username=%s AND is_active=1", (s["username"],))
    if me and ("分局长" in (me["role_name"] or "") or "客户经理" in (me["role_name"] or "")):
        rows = db.query_all(
            "SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order, id",
            (me["zone"],))
        return [r for r in rows if has_substantive(r)]
    # 普通执行角色：仅 role_access 授权板块
    pairs = get_accessible_pairs(s)
    if not pairs:
        return []
    where = " OR ".join(["(battle_id=%s AND warzone_id=%s)"] * len(pairs))
    args = []
    for b, w in pairs:
        args.extend([b, w])
    sql = f"SELECT * FROM deployment_records WHERE {where} ORDER BY sort_order, id"
    rows = db.query_all(sql, args)
    return [r for r in rows if has_substantive(r)]


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
            guide_roles.add(g)
        if c:
            combat_roles.add(c)
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
        return HTMLResponse(f.read())


@app.get("/admin")
def admin_page():
    p = os.path.join(BASE_DIR, "static", "admin.html")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return HTMLResponse(f.read())
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
    """兼容前端：role_id 或 username 字段任一即可"""
    body = await request.json()
    rid = body.get("role_id") or body.get("username") or ""
    pwd = body.get("password") or ""
    if not rid or not pwd:
        raise HTTPException(400, "参数不完整")
    user = db.query_one("SELECT * FROM users WHERE username=%s AND is_active=1", (rid,))
    if not user or not verify_password(user["password_hash"], user["password_salt"], pwd):
        raise HTTPException(401, "岗位或密码错误")
    info = get_user_info(rid)
    token = secrets.token_hex(32)
    SESSIONS[token] = {
        "username": user["username"],
        "role_id": user["role_id"],
        "is_admin": bool(user["is_admin"]),
        "expire": time.time() + SESSION_TTL,
    }
    return {"token": token, "role": info}


@app.post("/api/logout")
async def logout(request: Request):
    body = await request.json()
    SESSIONS.pop(body.get("token", ""), None)
    return {"ok": True}


@app.get("/api/me")
def me(request: Request):
    """当前登录人信息（前端可据此判断是否显示管理入口）"""
    s = require_session(request)
    return get_user_info(s["username"])


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
    # 一次查询所有战区角色，替代 N+1 循环查询
    zone_roles_map: Dict[str, List[str]] = {}
    for u in db.query_all("SELECT zone, role_name FROM users WHERE is_active=1 AND is_admin=0"):
        zone_roles_map.setdefault(u["zone"], []).append(u["role_name"])
    for zid, cnt in zcount.items():
        w = wl.get(zid)
        if w:
            # 去重
            seen = set()
            roles = [r for r in zone_roles_map.get(zid, []) if not (r in seen or seen.add(r))]
            zone_stats.append({"id": w["id"], "name": w["name"], "color": w["color"],
                               "count": cnt, "roles": roles})

    return {"role": get_user_info(s["username"]), "battles": battle_stats,
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
def role_battles(role_name: str, request: Request):
    """查看某角色的战役信息（兵种标签点击）
    兵种标签显示 users.role_name：
    - 分局长/客户经理：通过战区自动权限查本战区全部数据
    - 其他角色：通过 role_access 表查授权的战役/战区
    """
    s = require_session(request)
    role_name = (role_name or "").strip()
    if not role_name:
        raise HTTPException(400, "角色名不能为空")
    u = db.query_one("SELECT role_id,zone,role_name FROM users WHERE role_name=%s AND is_active=1 LIMIT 1", (role_name,))
    bl, wl = battle_lookup(), warzone_lookup()
    battles = []

    if u:
        urn = u["role_name"] or ""
        is_zone_mgr = "分局长" in urn or "客户经理" in urn

        if is_zone_mgr and u.get("zone"):
            # 分局长/客户经理：本战区全部数据
            rows = db.query_all(
                "SELECT * FROM deployment_records WHERE warzone_id=%s ORDER BY sort_order,id",
                (u["zone"],))
            rows = [r for r in rows if has_substantive(r)]
            battle_map: Dict[str, Dict[str, int]] = {}
            for r in rows:
                bid, zid = r.get("battle_id"), r.get("warzone_id")
                if bid and zid:
                    battle_map.setdefault(bid, {})[zid] = battle_map.get(bid, {}).get(zid, 0) + 1
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
        else:
            # 普通角色：查 role_access 表
            pairs = db.query_all("SELECT DISTINCT battle_id,warzone_id FROM role_access WHERE role_id=%s", (u["role_id"],))
            for p in pairs:
                bid, zid = p["battle_id"], p["warzone_id"]
                cnt_r = db.query_one(
                    "SELECT COUNT(*) c FROM deployment_records WHERE battle_id=%s AND warzone_id=%s",
                    (bid, zid))
                cnt = cnt_r["c"] if cnt_r else 0
                if cnt > 0:
                    b = bl.get(bid)
                    w = wl.get(zid)
                    if b and w:
                        existing = next((x for x in battles if x["id"] == bid), None)
                        if existing:
                            existing["zones"].append({"id": w["id"], "name": w["name"], "color": w["color"], "count": cnt})
                            existing["count"] += cnt
                        else:
                            battles.append({"id": b["id"], "name": b["name"], "color": b["color"],
                                            "count": cnt, "zones": [{"id": w["id"], "name": w["name"], "color": w["color"], "count": cnt}]})

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
    return {"role": get_user_info(s["username"]), "battle": {"id": b["id"], "name": b["name"], "color": b["color"]},
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
def cross_detail(battle_id: str, zone_id: str, request: Request):
    """数据详情：战役+战区交叉过滤"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl, wl = battle_lookup(), warzone_lookup()
    b, w = bl.get(battle_id), wl.get(zone_id)
    if not b or not w:
        raise HTTPException(404, "战役或战区不存在")
    cross = [r for r in rows if r.get("battle_id") == battle_id and r.get("warzone_id") == zone_id]
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
def path_detail(battle_id: str, zone_id: str, path_id: str, request: Request):
    """路径详情：场景列表"""
    s = require_session(request)
    rows = get_role_rows(s)
    bl, wl = battle_lookup(), warzone_lookup()
    b, w = bl.get(battle_id), wl.get(zone_id)
    cross = [r for r in rows if r.get("battle_id") == battle_id and r.get("warzone_id") == zone_id]
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
    require_admin(request)
    u_total = db.query_one("SELECT COUNT(*) c FROM users WHERE is_active=1")["c"]
    r_total = db.query_one("SELECT COUNT(*) c FROM deployment_records")["c"]
    a_total = db.query_one("SELECT COUNT(*) c FROM role_access")["c"]
    battles = db.query_all("SELECT * FROM battles ORDER BY sort_order")
    warzones = db.query_all("SELECT * FROM warzones ORDER BY sort_order")
    # 各战区人员数
    zone_users = db.query_all(
        "SELECT zone, COUNT(*) c FROM users WHERE is_active=1 AND is_admin=0 GROUP BY zone")
    return {
        "users": u_total, "records": r_total, "access_rules": a_total,
        "battles": battles, "warzones": warzones,
        "zone_users": {r["zone"]: r["c"] for r in zone_users},
    }


# ---- 人员管理 ----
@app.get("/api/admin/users")
def admin_users(request: Request, q: str = "", zone: str = ""):
    """人员列表（支持关键词 q 与战区过滤）"""
    require_admin(request)
    sql = ("SELECT id,username,name,role_id,role_name,phone,zone,zone_name,color,is_admin,is_active,"
           "created_at FROM users WHERE 1=1")
    args = []
    if q:
        sql += " AND (name LIKE %s OR role_name LIKE %s OR phone LIKE %s OR username LIKE %s)"
        kw = f"%{q}%"
        args += [kw, kw, kw, kw]
    if zone:
        sql += " AND zone=%s"
        args.append(zone)
    sql += " ORDER BY is_admin DESC, zone, role_name"
    rows = db.query_all(sql, args)
    return {"total": len(rows), "users": rows, "me": get_user_info(require_admin(request)["username"])}


@app.post("/api/admin/users")
async def admin_create_user(request: Request):
    """新增人员"""
    require_admin(request)
    body = await request.json()
    username = (body.get("username") or "").strip()
    role_name = (body.get("role_name") or "").strip()
    zone = (body.get("zone") or "public").strip()
    if not username or not role_name:
        raise HTTPException(400, "登录账号与岗位名必填")
    if db.query_one("SELECT id FROM users WHERE username=%s", (username,)):
        raise HTTPException(400, "登录账号已存在")
    wl = warzone_lookup()
    w = wl.get(zone) or next(iter(wl.values()), {"name": "公众战区", "color": "#1565c0"})
    import secrets as _s
    salt = _s.token_hex(8)
    pwd = (body.get("password") or "123456").strip()
    h = hashlib.sha256((pwd + salt).encode()).hexdigest()
    nid = db.execute(
        "INSERT INTO users(username,name,role_id,role_name,phone,password_hash,password_salt,"
        "zone,zone_name,color,is_admin) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (username, body.get("name") or role_name, username, role_name, body.get("phone", ""),
         h, salt, zone, w["name"], w["color"], 1 if body.get("is_admin") else 0))
    return {"ok": True, "id": nid}


@app.put("/api/admin/users/{uid}")
async def admin_update_user(uid: int, request: Request):
    """编辑人员（支持改密码/电话/姓名/战区/管理员标记）"""
    require_admin(request)
    body = await request.json()
    cur = db.query_one("SELECT * FROM users WHERE id=%s", (uid,))
    if not cur:
        raise HTTPException(404, "人员不存在")
    name = body.get("name", cur["name"])
    phone = body.get("phone", cur["phone"])
    is_admin = 1 if body.get("is_admin") else 0
    zone = body.get("zone", cur["zone"])
    wl = warzone_lookup()
    w = wl.get(zone)
    zone_name = w["name"] if w else cur["zone_name"]
    color = w["color"] if w else cur["color"]
    role_name = body.get("role_name", cur["role_name"])
    if body.get("password"):
        salt = secrets.token_hex(8)
        h = hashlib.sha256((body["password"] + salt).encode()).hexdigest()
        db.execute("UPDATE users SET name=%s,phone=%s,role_name=%s,zone=%s,zone_name=%s,color=%s,"
                   "is_admin=%s,password_hash=%s,password_salt=%s WHERE id=%s",
                   (name, phone, role_name, zone, zone_name, color, is_admin, h, salt, uid))
    else:
        db.execute("UPDATE users SET name=%s,phone=%s,role_name=%s,zone=%s,zone_name=%s,color=%s,"
                   "is_admin=%s WHERE id=%s",
                   (name, phone, role_name, zone, zone_name, color, is_admin, uid))
    return {"ok": True}


@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: int, request: Request):
    """停用人员（软删除，保留数据可追溯）"""
    s = require_admin(request)
    if str(uid) == str(db.query_one("SELECT id FROM users WHERE username=%s", (s["username"],))["id"]):
        raise HTTPException(400, "不能停用自己")
    db.execute("UPDATE users SET is_active=0 WHERE id=%s", (uid,))
    return {"ok": True}


# ---- 权限分配 ----
@app.get("/api/admin/access")
def admin_get_access(request: Request, role_id: str = ""):
    """查询某角色（或全部）的权限矩阵"""
    require_admin(request)
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
    # 角色清单（去重）
    roles = db.query_all(
        "SELECT DISTINCT role_id,role_name,zone_name FROM users WHERE is_admin=0 ORDER BY zone_name,role_name")
    return {
        "battles": battles, "warzones": warzones, "roles": roles,
        "granted": [[g[0], g[1]] for g in granted] if role_id else rules,
    }


@app.put("/api/admin/access")
async def admin_set_access(request: Request):
    """批量设置某角色的可见板块（覆盖式）"""
    require_admin(request)
    body = await request.json()
    role_id = body.get("role_id")
    grants = body.get("grants", [])  # [{battle_id, warzone_id}, ...]
    if not role_id:
        raise HTTPException(400, "role_id 必填")
    db.execute("DELETE FROM role_access WHERE role_id=%s", (role_id,))
    if grants:
        db.executemany("INSERT IGNORE INTO role_access(role_id,battle_id,warzone_id) VALUES(%s,%s,%s)",
                       [(role_id, g["battle_id"], g["warzone_id"]) for g in grants])
    return {"ok": True, "granted": len(grants)}


# ---- 板块记录管理 ----
@app.get("/api/admin/record-schema")
def admin_record_schema(request: Request):
    """记录字段定义（前端据此渲染编辑表单）"""
    require_admin(request)
    return {"fields": [{"key": k, "label": l, "type": t} for k, l, t in RECORD_FIELDS],
            "battles": db.query_all("SELECT * FROM battles ORDER BY sort_order"),
            "warzones": db.query_all("SELECT * FROM warzones ORDER BY sort_order")}


@app.get("/api/admin/records")
def admin_records(request: Request, battle_id: str = "", zone_id: str = ""):
    """记录列表（支持战役/战区筛选）"""
    require_admin(request)
    sql = "SELECT * FROM deployment_records WHERE 1=1"
    args = []
    if battle_id:
        sql += " AND battle_id=%s"; args.append(battle_id)
    if zone_id:
        sql += " AND warzone_id=%s"; args.append(zone_id)
    sql += " ORDER BY battle_id, warzone_id, sort_order, id"
    rows = db.query_all(sql, args)
    return {"total": len(rows), "records": rows}


@app.post("/api/admin/records")
async def admin_create_record(request: Request):
    """新增记录"""
    s = require_admin(request)
    body = await request.json()
    data = {k: (body.get(k, "") or "") for k in RECORD_DB_COLS}
    bname = (data.get("battle_name") or "").replace("（例）", "").strip()
    zname = (data.get("warzone_name") or "").strip()
    bid = _battle_id(bname); zid = _warzone_id(zname)
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
    s = require_admin(request)
    body = await request.json()
    if not db.query_one("SELECT id FROM deployment_records WHERE id=%s", (rid,)):
        raise HTTPException(404, "记录不存在")
    data = {k: (body.get(k, "") or "") for k in RECORD_DB_COLS}
    bname = (data.get("battle_name") or "").replace("（例）", "").strip()
    zname = (data.get("warzone_name") or "").strip()
    bid = _battle_id(bname); zid = _warzone_id(zname)
    sets = ", ".join(f"{c}=%s" for c in RECORD_DB_COLS)
    db.execute(
        f"UPDATE deployment_records SET battle_id=%s,warzone_id=%s,{sets},updated_by=%s WHERE id=%s",
        [bid, zid] + [data[k] for k in RECORD_DB_COLS] + [s["username"], rid])
    return {"ok": True}


@app.delete("/api/admin/records/{rid}")
async def admin_delete_record(rid: int, request: Request):
    require_admin(request)
    db.execute("DELETE FROM deployment_records WHERE id=%s", (rid,))
    return {"ok": True}


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
