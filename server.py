# -*- coding: utf-8 -*-
"""夏收行动部署看板 - FastAPI后端 (并列维度版)
战役和战区为并列耦合筛选条件：
  点击战役 → 按战区分组 → 点击战区 → 数据详情
  点击战区 → 按战役分组 → 点击战役 → 数据详情
权限：按数据行中作战角色/指导角色列匹配过滤
"""
import json, hashlib, time, os, secrets
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

app = FastAPI(title="夏收行动部署看板")

with open(os.path.join(DATA_DIR, "roles.json"), encoding="utf-8") as f:
    ROLES = json.load(f)
with open(os.path.join(DATA_DIR, "warzones.json"), encoding="utf-8") as f:
    WARZONES = json.load(f)
with open(os.path.join(DATA_DIR, "battles.json"), encoding="utf-8") as f:
    BATTLES = json.load(f)
with open(os.path.join(DATA_DIR, "all_records.json"), encoding="utf-8") as f:
    ALL_RECORDS = json.load(f)
with open(os.path.join(DATA_DIR, "columns.json"), encoding="utf-8") as f:
    COLUMNS = json.load(f)

SESSIONS = {}
SESSION_TTL = 3600 * 8

ROLE_KEYWORDS = {
    "分局长（公）": ["分局", "公"],
    "直销": ["直销"],
    "工程师（公）": ["工程师", "公"],
    "营业员": ["营业"],
    "存量专员": ["存量"],
    "渠道经理": ["渠道"],
    "分局长（商）": ["分局", "商"],
    "客户经理（商）": ["客户经理", "商"],
    "特战队": ["特战"],
    "工程师（商）": ["工程师", "商"],
    "分局长（校）": ["分局", "校"],
    "客户经理（校）": ["客户经理", "校"],
    "分局长（行）": ["分局", "行"],
    "客户经理（行）": ["客户经理", "行"],
}
ROLE_EXCLUSIONS = {
    "分局长（公）": ["商", "校", "行", "教科", "行业"],
    "工程师（公）": ["商", "校", "行", "教科", "行业"],
    "分局长（商）": ["公", "校", "行", "公众", "教科", "行业"],
    "工程师（商）": ["公", "校", "行", "公众", "教科", "行业"],
    "分局长（校）": ["公", "商", "行", "公众", "商业", "行业"],
    "客户经理（校）": ["公", "商", "行", "公众", "商业", "行业"],
    "分局长（行）": ["公", "商", "校", "公众", "商业", "教科"],
    "客户经理（行）": ["公", "商", "校", "公众", "商业", "教科"],
}


def verify_password(role_id, pwd):
    for r in ROLES:
        if r["id"] == role_id:
            salt = r["password_salt"]
            h = hashlib.sha256((pwd + salt).encode()).hexdigest()
            return h == r["password_hash"]
    return False


def get_session(token):
    s = SESSIONS.get(token)
    if not s:
        return None
    if time.time() > s["expire"]:
        SESSIONS.pop(token, None)
        return None
    return s


def get_role_info(rid):
    for r in ROLES:
        if r["id"] == rid:
            return {"id": r["id"], "name": r["name"], "zone": r["zone"], "zone_name": r["zone_name"], "color": r["color"]}
    return None


def row_matches_role(row, role_id):
    if role_id == "总经理":
        return True
    keywords = ROLE_KEYWORDS.get(role_id, [role_id])
    exclusions = ROLE_EXCLUSIONS.get(role_id, [])
    check_values = []
    for col in ["作战角色", "指导角色（营销统筹/专员）", "场景（对到话术、作战角色）"]:
        v = str(row.get(col, "")).strip()
        if v:
            check_values.append(v)
    all_text = " ".join(str(v) for v in row.values())
    for cv in check_values:
        if all(kw in cv for kw in keywords):
            if not any(ex in cv for ex in exclusions):
                return True
    if role_id in all_text:
        return True
    return False


def has_substantive_content(row):
    """Check if a row has content beyond the battle-level fields (编号/战役/战役总目标).
    Rows with only battle name but no zone/path/scene content are placeholders."""
    substantive_cols = ["战区", "战区总目标", "路径编号", "路径", "路径目标",
                        "场景编号", "场景（对到话术、作战角色）", "作战角色",
                        "指导角色（营销统筹/专员）", "政策", "激励", "标准话术",
                        "商机来源", "最短管控周期", "最短管控动作（量）",
                        "最短管控目标（积分/金额）", "闭环管控（注：要写清楚融入到531、642、321中去）"]
    return any(str(row.get(col, "")).strip() for col in substantive_cols)


def get_role_rows(rid):
    if rid == "总经理":
        return [r for r in ALL_RECORDS if has_substantive_content(r)]
    return [r for r in ALL_RECORDS if row_matches_role(r, rid) and has_substantive_content(r)]


def fill_hierarchy(rows):
    result = []
    last = {}
    fill_cols = ["战役编号", "战役", "战役总目标", "战区", "战区总目标", "路径编号", "路径", "路径目标"]
    for r in rows:
        new_row = dict(r)
        for col in fill_cols:
            val = str(new_row.get(col, "")).strip()
            if val:
                last[col] = val
                new_row[col] = val
            elif col in last:
                new_row[col] = last[col]
        result.append(new_row)
    return result


def group_paths_from_rows(rows):
    paths = {}
    for r in rows:
        pid = str(r.get("路径编号", "")).strip()
        pname = str(r.get("路径", "")).strip()
        ptarget = str(r.get("路径目标", "")).strip()
        if not pid or not pname:
            continue
        # Skip placeholder paths like "..."
        if pid == "..." or pname == "...":
            continue
        if pid not in paths:
            paths[pid] = {"path_id": pid, "path_name": pname, "path_target": ptarget, "scene_count": 0}
        sid = str(r.get("场景编号", "")).strip()
        if sid:
            paths[pid]["scene_count"] += 1
    return list(paths.values())


def get_battle_basic_info(rows):
    for r in rows:
        if str(r.get("战役", "")).strip():
            return {
                "战役编号": str(r.get("战役编号", "")).strip(),
                "战役": str(r.get("战役", "")).strip(),
                "战区": str(r.get("战区", "")).strip(),
                "指导角色（营销统筹/专员）": str(r.get("指导角色（营销统筹/专员）", "")).strip(),
                "作战角色": str(r.get("作战角色", "")).strip(),
            }
    return None


def get_battle_targets(rows):
    for r in rows:
        if str(r.get("战役", "")).strip():
            return {
                "战役总目标": str(r.get("战役总目标", "")).strip(),
                "战区总目标": str(r.get("战区总目标", "")).strip(),
            }
    return None


def get_scenes_for_path(rows, path_id):
    scenes = []
    for r in rows:
        pid = str(r.get("路径编号", "")).strip()
        if pid != path_id:
            continue
        sid = str(r.get("场景编号", "")).strip()
        if not sid:
            continue
        scenes.append({
            "场景编号": sid,
            "场景": str(r.get("场景（对到话术、作战角色）", "")).strip(),
            "政策": str(r.get("政策", "")).strip(),
            "激励": str(r.get("激励", "")).strip(),
            "标准话术": str(r.get("标准话术", "")).strip(),
            "商机来源": str(r.get("商机来源", "")).strip(),
            "最短管控周期": str(r.get("最短管控周期", "")).strip(),
            "最短管控动作（量）": str(r.get("最短管控动作（量）", "")).strip(),
            "最短管控目标（积分/金额）": str(r.get("最短管控目标（积分/金额）", "")).strip(),
            "闭环管控": str(r.get("闭环管控（注：要写清楚融入到531、642、321中去）", "")).strip(),
        })
    return scenes


# ====== 页面 ======

@app.get("/")
async def index():
    with open(os.path.join(BASE_DIR, "static", "index.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


# ====== API ======

@app.post("/api/login")
async def login(request: Request):
    body = await request.json()
    rid, pwd = body.get("role_id", ""), body.get("password", "")
    if not rid or not pwd:
        raise HTTPException(400, "参数不完整")
    if not verify_password(rid, pwd):
        raise HTTPException(401, "岗位或密码错误")
    token = secrets.token_hex(32)
    SESSIONS[token] = {"role_id": rid, "expire": time.time() + SESSION_TTL}
    return {"token": token, "role": get_role_info(rid)}


@app.post("/api/logout")
async def logout(request: Request):
    body = await request.json()
    SESSIONS.pop(body.get("token", ""), None)
    return {"ok": True}


@app.get("/api/overview")
async def overview(request: Request):
    """主页概览：只返回该角色有数据的战役和战区"""
    token = request.query_params.get("token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录")
    rid = s["role_id"]
    rows = get_role_rows(rid)
    filled = fill_hierarchy(rows)

    battle_stats = []
    for b in BATTLES:
        b_rows = [r for r in filled if b["name"] in str(r.get("战役", ""))]
        if b_rows:
            battle_stats.append({"id": b["id"], "name": b["name"], "color": b["color"], "count": len(b_rows)})

    zone_stats = []
    for wz in WARZONES:
        z_rows = [r for r in filled if wz["name"] in str(r.get("战区", ""))]
        if z_rows:
            zone_stats.append({"id": wz["id"], "name": wz["name"], "color": wz["color"], "count": len(z_rows), "roles": wz.get("roles", [])})

    return {"role": get_role_info(rid), "battles": battle_stats, "zones": zone_stats, "total": len(filled)}


@app.get("/api/battle-zones/{battle_id}")
async def battle_zones(battle_id: str, request: Request):
    """战役子页面：展示该战役下有哪些战区有数据"""
    token = request.query_params.get("token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录")
    rid = s["role_id"]
    rows = get_role_rows(rid)
    filled = fill_hierarchy(rows)

    battle_info = None
    for b in BATTLES:
        if b["id"] == battle_id:
            battle_info = {"id": b["id"], "name": b["name"], "color": b["color"]}
            break
    if not battle_info:
        raise HTTPException(404, "战役不存在")

    b_rows = [r for r in filled if battle_info["name"] in str(r.get("战役", ""))]

    # 按战区分组
    zone_list = []
    for wz in WARZONES:
        z_rows = [r for r in b_rows if wz["name"] in str(r.get("战区", ""))]
        if z_rows:
            zone_list.append({
                "id": wz["id"], "name": wz["name"], "color": wz["color"],
                "count": len(z_rows), "roles": wz.get("roles", [])
            })

    return {"role": get_role_info(rid), "battle": battle_info, "zones": zone_list, "total": len(b_rows)}


@app.get("/api/zone-battles/{zone_id}")
async def zone_battles(zone_id: str, request: Request):
    """战区子页面：展示该战区下有哪些战役有数据"""
    token = request.query_params.get("token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录")
    rid = s["role_id"]
    rows = get_role_rows(rid)
    filled = fill_hierarchy(rows)

    zone_info = None
    for wz in WARZONES:
        if wz["id"] == zone_id:
            zone_info = {"id": wz["id"], "name": wz["name"], "color": wz["color"], "roles": wz.get("roles", [])}
            break
    if not zone_info:
        raise HTTPException(404, "战区不存在")

    z_rows = [r for r in filled if zone_info["name"] in str(r.get("战区", ""))]

    # 按战役分组
    battle_list = []
    for b in BATTLES:
        b_rows = [r for r in z_rows if b["name"] in str(r.get("战役", ""))]
        if b_rows:
            battle_list.append({"id": b["id"], "name": b["name"], "color": b["color"], "count": len(b_rows)})

    return {"role": get_role_info(rid), "zone": zone_info, "battles": battle_list, "total": len(z_rows)}


@app.get("/api/detail/{battle_id}/{zone_id}")
async def cross_detail(battle_id: str, zone_id: str, request: Request):
    """数据详情：战役+战区交叉过滤，展示基本信息+目标+路径列表"""
    token = request.query_params.get("token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录")
    rid = s["role_id"]
    rows = get_role_rows(rid)
    filled = fill_hierarchy(rows)

    battle_info = None
    for b in BATTLES:
        if b["id"] == battle_id:
            battle_info = {"id": b["id"], "name": b["name"], "color": b["color"]}
            break

    zone_info = None
    for wz in WARZONES:
        if wz["id"] == zone_id:
            zone_info = {"id": wz["id"], "name": wz["name"], "color": wz["color"], "roles": wz.get("roles", [])}
            break

    # 交叉过滤
    cross_rows = [r for r in filled
                  if battle_info and battle_info["name"] in str(r.get("战役", ""))
                  and zone_info and zone_info["name"] in str(r.get("战区", ""))]

    basic = get_battle_basic_info(cross_rows)
    targets = get_battle_targets(cross_rows)
    paths = group_paths_from_rows(cross_rows)

    return {
        "role": get_role_info(rid),
        "battle": battle_info,
        "zone": zone_info,
        "basic": basic,
        "targets": targets,
        "paths": paths,
        "total": len(cross_rows)
    }


@app.get("/api/path-detail/{battle_id}/{zone_id}/{path_id}")
async def path_detail(battle_id: str, zone_id: str, path_id: str, request: Request):
    """路径详情：战役+战区+路径 过滤，展示场景列表"""
    token = request.query_params.get("token", "")
    s = get_session(token)
    if not s:
        raise HTTPException(401, "未登录")
    rid = s["role_id"]
    rows = get_role_rows(rid)
    filled = fill_hierarchy(rows)

    battle_info = None
    for b in BATTLES:
        if b["id"] == battle_id:
            battle_info = {"id": b["id"], "name": b["name"], "color": b["color"]}
            break

    zone_info = None
    for wz in WARZONES:
        if wz["id"] == zone_id:
            zone_info = {"id": wz["id"], "name": wz["name"], "color": wz["color"]}
            break

    cross_rows = [r for r in filled
                  if battle_info and battle_info["name"] in str(r.get("战役", ""))
                  and zone_info and zone_info["name"] in str(r.get("战区", ""))]

    path_info = None
    for r in cross_rows:
        if str(r.get("路径编号", "")).strip() == path_id:
            path_info = {
                "path_id": path_id,
                "path_name": str(r.get("路径", "")).strip(),
                "path_target": str(r.get("路径目标", "")).strip(),
            }
            break

    scenes = get_scenes_for_path(cross_rows, path_id)

    return {
        "role": get_role_info(rid),
        "battle": battle_info,
        "zone": zone_info,
        "path": path_info,
        "scenes": scenes,
        "total": len(scenes)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
