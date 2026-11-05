"""Deterministic 3D orthogonal bin-packing heuristic with overlap and access checks.

Coordinates are centimetres. Cargo door is at x=0; x increases toward the front wall.
Earlier delivery stops are placed closer to the door to reduce unload blocking.
This is a heuristic, not a proof of globally optimal packing.
"""
from itertools import permutations
from typing import Any


def _orientations(package: dict) -> list[tuple[float, float, float]]:
    l, w, h = package["length_cm"], package["width_cm"], package["height_cm"]
    if package.get("allowed_rotations", "ALL") == "UPRIGHT":
        return [(l, w, h), (w, l, h)]
    return list(dict.fromkeys(permutations((l, w, h), 3)))


def _overlap(a: dict, b: dict) -> bool:
    return not (a["x"] + a["length_cm"] <= b["x"] or b["x"] + b["length_cm"] <= a["x"] or
                a["y"] + a["width_cm"] <= b["y"] or b["y"] + b["width_cm"] <= a["y"] or
                a["z"] + a["height_cm"] <= b["z"] or b["z"] + b["height_cm"] <= a["z"])


def pack_packages(vehicle: dict, packages: list[dict], delivery_order: dict[str, int] | None = None,
                  apply_accessibility: bool = True) -> dict[str, Any]:
    L, W, H = vehicle["cargo_length_cm"], vehicle["cargo_width_cm"], vehicle["cargo_height_cm"]
    payload = vehicle.get("max_payload_kg", vehicle.get("capacity_kg", 0))
    total_weight = sum(float(p["weight_kg"]) for p in packages)
    total_volume = sum(float(p["length_cm"])*float(p["width_cm"])*float(p["height_cm"]) for p in packages)
    capacity_volume = L * W * H
    base = {"feasible": False, "placements": [], "unpacked": [], "total_weight_kg": round(total_weight, 2),
            "payload_capacity_kg": payload, "total_volume_cm3": round(total_volume, 2),
            "cargo_volume_cm3": round(capacity_volume, 2), "volume_utilization": round(total_volume/capacity_volume, 4) if capacity_volume else 0,
            "accessibility": {"checked": apply_accessibility, "valid": True, "issues": []}}
    if total_weight > payload:
        base["unpacked"] = [{"package_id": p["id"], "reason": "combined package weight exceeds payload capacity"} for p in packages]
        base["failure_reason"] = f"Total package weight {total_weight:.2f} kg exceeds payload capacity {payload:.2f} kg."
        return base
    # Place earlier deliveries first; among equal stops, place larger items first.
    order = delivery_order or {}
    sorted_packages = sorted(packages, key=lambda p: (order.get(p.get("delivery_id") or "", 10**6),
        -(float(p["length_cm"])*float(p["width_cm"])*float(p["height_cm"]))))
    placed: list[dict] = []
    failures = []
    for p in sorted_packages:
        found = None
        # Extreme points derived from placed item boundaries; deterministic and compact.
        points = {(0.0, 0.0, 0.0)}
        for q in placed:
            points.add((q["x"] + q["length_cm"], q["y"], q["z"]))
            points.add((q["x"], q["y"] + q["width_cm"], q["z"]))
            points.add((q["x"], q["y"], q["z"] + q["height_cm"]))
        points = sorted(points, key=lambda t: (t[0], t[2], t[1]))
        for dims in _orientations(p):
            pl, pw, ph = dims
            if pl > L or pw > W or ph > H:
                continue
            for x, y, z in points:
                if x + pl > L or y + pw > W or z + ph > H:
                    continue
                candidate = {"package_id": p["id"], "delivery_id": p.get("delivery_id"), "x": x, "y": y, "z": z,
                             "length_cm": pl, "width_cm": pw, "height_cm": ph, "weight_kg": p["weight_kg"],
                             "orientation_cm": [pl, pw, ph]}
                if all(not _overlap(candidate, q) for q in placed):
                    found = candidate
                    break
            if found:
                break
        if found:
            placed.append(found)
        else:
            failures.append({"package_id": p["id"], "reason": "no non-overlapping orientation/position fits the remaining cargo bay"})
    issues = []
    if apply_accessibility:
        # Door is at x=0. For a package with an earlier stop, later-stop cargo must not sit
        # between it and the door at the same z band and overlapping y band.
        for a in placed:
            stop_a = order.get(a.get("delivery_id") or "", 10**6)
            for b in placed:
                if a is b:
                    continue
                stop_b = order.get(b.get("delivery_id") or "", 10**6)
                if stop_b > stop_a and b["x"] < a["x"] and b["x"] + b["length_cm"] > 0:
                    y_overlap = a["y"] < b["y"] + b["width_cm"] and b["y"] < a["y"] + a["width_cm"]
                    z_overlap = a["z"] < b["z"] + b["height_cm"] and b["z"] < a["z"] + a["height_cm"]
                    if y_overlap and z_overlap:
                        issues.append({"package_id": a["package_id"], "blocked_by": b["package_id"], "reason": "earlier-stop package is behind a later-stop package relative to the cargo door"})
    base.update({"placements": placed, "unpacked": failures, "feasible": not failures and not issues,
                 "accessibility": {"checked": apply_accessibility, "valid": not issues, "issues": issues}})
    if failures:
        base["failure_reason"] = "One or more packages could not be placed without overlap and within cargo dimensions."
    elif issues:
        base["failure_reason"] = "Packing fits geometrically, but cargo accessibility rules are violated."
    else:
        base["failure_reason"] = None
    return base
