# -*- coding: utf-8 -*-
import urllib.request, json

# Login
data = json.dumps({"role_id": "总经理", "password": "总经理2026"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8001/api/login", data=data, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
result = json.loads(resp.read())
token = result["token"]

# Detail for 百万加装战 x 公众战区
print("=== Detail: 百万加装战 x 公众战区 ===")
url = "http://127.0.0.1:8001/api/detail/b2/public?token=" + token
req2 = urllib.request.Request(url)
resp2 = urllib.request.urlopen(req2)
detail = json.loads(resp2.read())
print("Basic:", json.dumps(detail.get("basic"), ensure_ascii=False, indent=2))
print("Targets:", json.dumps(detail.get("targets"), ensure_ascii=False, indent=2))
print("Paths:", len(detail.get("paths", [])))
for p in detail.get("paths", []):
    print("  ", json.dumps(p, ensure_ascii=False))

# Path detail for path 1
print("\n=== Path Detail: 1 ===")
url3 = "http://127.0.0.1:8001/api/path-detail/b2/public/1?token=" + token
req3 = urllib.request.Request(url3)
resp3 = urllib.request.urlopen(req3)
pd = json.loads(resp3.read())
print("Path info:", json.dumps(pd.get("path"), ensure_ascii=False))
print("Scenes:", len(pd.get("scenes", [])))
for s in pd.get("scenes", []):
    print("  Scene:", s.get("场景编号"), "-", s.get("场景"))

# Test other roles
print("\n=== Test: 直销 role ===")
data2 = json.dumps({"role_id": "直销", "password": "直销2026"}).encode("utf-8")
req4 = urllib.request.Request("http://127.0.0.1:8001/api/login", data=data2, headers={"Content-Type": "application/json"})
resp4 = urllib.request.urlopen(req4)
result4 = json.loads(resp4.read())
token4 = result4["token"]

url5 = "http://127.0.0.1:8001/api/overview?token=" + token4
req5 = urllib.request.Request(url5)
resp5 = urllib.request.urlopen(req5)
overview5 = json.loads(resp5.read())
print("Battles:", len(overview5["battles"]))
for b in overview5["battles"]:
    print("  -", b["name"])
print("Zones:", len(overview5["zones"]))
for z in overview5["zones"]:
    print("  -", z["name"], "count:", z["count"])
