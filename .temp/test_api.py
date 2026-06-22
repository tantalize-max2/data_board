# -*- coding: utf-8 -*-
import urllib.request, json

# Login
data = json.dumps({"role_id": "总经理", "password": "总经理2026"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8001/api/login", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
token = result["token"]
print("Login OK, role:", result["role"]["name"])

# Overview
req2 = urllib.request.Request("http://127.0.0.1:8001/api/overview?token=" + token)
resp2 = urllib.request.urlopen(req2)
overview = json.loads(resp2.read())
print("\n=== Battles ===")
print("Battles count:", len(overview["battles"]))
for b in overview["battles"]:
    print("  -", b["name"], "(id=" + b["id"] + ", count=" + str(b["count"]) + ")")

print("\n=== Zones ===")
print("Zones count:", len(overview["zones"]))
for z in overview["zones"]:
    print("  -", z["name"], "(id=" + z["id"] + ", count=" + str(z["count"]) + ")")

print("\nTotal rows:", overview["total"])

# Test battle-zones for 双线标准ICT固本战
print("\n=== Test battle-zones for 双线标准ICT固本战 ===")
req3 = urllib.request.Request("http://127.0.0.1:8001/api/battle-zones/shuangxian_ict?token=" + token)
try:
    resp3 = urllib.request.urlopen(req3)
    bz = json.loads(resp3.read())
    print("Battle:", bz["battle"]["name"])
    print("Zones with data:", len(bz["zones"]))
    for z in bz["zones"]:
        print("  -", z["name"], "(count=" + str(z["count"]) + ")")
except Exception as e:
    print("ERROR:", e)
