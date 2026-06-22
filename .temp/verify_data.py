# -*- coding: utf-8 -*-
import json, os

BASE = r"C:\Users\64562\.local\share\TeleAgent\TeleAgent的工作空间\夏收行动看板\data"

with open(os.path.join(BASE, "battles.json"), encoding="utf-8") as f:
    battles = json.load(f)
with open(os.path.join(BASE, "all_records.json"), encoding="utf-8") as f:
    records = json.load(f)
with open(os.path.join(BASE, "warzones.json"), encoding="utf-8") as f:
    warzones = json.load(f)

battle_names = [b["name"] for b in battles]
zone_names = [z["name"] for z in warzones]

print("=== battles.json names ===")
for bn in battle_names:
    print(" ", bn)

print("\n=== Unique 战役 values in all_records ===")
record_battles = set()
for r in records:
    v = str(r.get("战役", "")).strip()
    if v:
        record_battles.add(v)
for rb in sorted(record_battles):
    print(" ", rb)

print("\n=== Match check ===")
for bn in battle_names:
    matched = any(bn in rb for rb in record_battles)
    print(" ", bn, "->", "MATCH" if matched else "NO MATCH")

print("\n=== Unmatched record battles ===")
for rb in sorted(record_battles):
    matched = any(bn in rb for bn in battle_names)
    if not matched:
        print(" ", rb, "-> NO MATCH in battles.json")

print("\n=== Unique 战区 values in all_records ===")
record_zones = set()
for r in records:
    v = str(r.get("战区", "")).strip()
    if v:
        record_zones.add(v)
for rz in sorted(record_zones):
    matched = any(zn in rz for zn in zone_names)
    print(" ", rz, "->", "MATCH" if matched else "NO MATCH")

print("\n=== fill_hierarchy test ===")
# Simulate fill_hierarchy
fill_cols = ["战役编号", "战役", "战役总目标", "战区", "战区总目标", "路径编号", "路径", "路径目标"]
last = {}
filled_count = 0
for r in records:
    for col in fill_cols:
        val = str(r.get(col, "")).strip()
        if val:
            last[col] = val
        elif col in last:
            filled_count += 1
print("Filled", filled_count, "empty cells across", len(records), "rows")

# Check for "..." placeholders
print("\n=== Path placeholder check ===")
dot_paths = 0
for r in records:
    pid = str(r.get("路径编号", "")).strip()
    pname = str(r.get("路径", "")).strip()
    if pid == "..." or pname == "...":
        dot_paths += 1
print("Rows with '...' path:", dot_paths)
