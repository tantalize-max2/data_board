# -*- coding: utf-8 -*-
import urllib.request, json

# Login as 总经理
data = json.dumps({"role_id": "总经理", "password": "总经理2026"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8001/api/login", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
token = result["token"]

# Test detail for 百万加装战 + 公众战区 (this has the real data)
print("=== Detail: 百万加装战 x 公众战区 ===")
url = "http://127.0.0.1:8001/api/detail/b2/public?token=" + token
req2 = urllib.request.Request(url)
resp2 = urllib.request.urlopen(req2)
detail = json.loads(resp2.read())
print("Basic:", json.dumps(detail.get("basic"), ensure_ascii=False, indent=2))
print("Targets:", json.dumps(detail.get("targets"), ensure_ascii=False, indent=2))
print("Paths:")
for p in detail.get("paths", []):
    print("  ", json.dumps(p, ensure_ascii=False))

# Test path detail for each path
for p in detail.get("paths", []):
    pid = p["path_id"]
    print("\n=== Path Detail:", pid, "===")
    url3 = "http://127.0.0.1:8001/api/path-detail/b2/public/" + pid + "?token=" + token
    req3 = urllib.request.Request(url3)
    try:
        resp3 = urllib.request.urlopen(req3)
        pd = json.loads(resp3.read())
        print("Path info:", json.dumps(pd.get("path"), ensure_ascii=False))
        print("Scenes:", len(pd.get("scenes", [])))
        for s in pd.get("scenes", []):
            print("  Scene:", s.get("场景编号"), "-", s.get("场景"))
    except Exception as e:
        print("ERROR:", e)

# Now test detail for 一号工程战 + 公众战区 (this likely has "..." placeholder)
print("\n=== Detail: 一号工程战 x 公众战区 ===")
url4 = "http://127.0.0.1:8001/api/detail/b1/public?token=" + token
req4 = urllib.request.Request(url4)
try:
    resp4 = urllib.request.urlopen(req4)
    detail2 = json.loads(resp4.read())
    print("Basic:", json.dumps(detail2.get("basic"), ensure_ascii=False))
    print("Targets:", json.dumps(detail2.get("targets"), ensure_ascii=False))
    print("Paths:")
    for p in detail2.get("paths", []):
        print("  ", json.dumps(p, ensure_ascii=False))
except Exception as e:
    print("ERROR:", e)

# Test all other battles too
for bid, bname in [("b3", "高价值新增战"), ("b4", "双线标准ICT固本战"), ("b5", "项目掘金战"), ("b6", "细分市场战")]:
    print("\n=== Detail:", bname, "x 公众战区 ===")
    url5 = "http://127.0.0.1:8001/api/detail/" + bid + "/public?token=" + token
    req5 = urllib.request.Request(url5)
    try:
        resp5 = urllib.request.urlopen(req5)
        detail3 = json.loads(resp5.read())
        print("Basic:", json.dumps(detail3.get("basic"), ensure_ascii=False))
        print("Paths:", len(detail3.get("paths", [])))
        for p in detail3.get("paths", []):
            print("  ", json.dumps(p, ensure_ascii=False))
    except Exception as e:
        print("ERROR:", e)
