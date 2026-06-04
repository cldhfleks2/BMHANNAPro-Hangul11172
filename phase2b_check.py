# -*- coding: utf-8 -*-
"""Phase 2b: 조립 완전성 검사 — 누락 8,654자 전부에 대해 부품 확보 가능 여부.

우선순위: A(받침교체) > C(초성교체) > B(받침추가/압축) > D(완전조립)
"""
import pickle
from collections import defaultdict
import hannalib as H

font = H.load_font()
cmap = font.getBestCmap()
glyf = font["glyf"]

with open("parts_library.pkl", "rb") as f:
    lib = pickle.load(f)
parts, seg_by_cp = lib["parts"], lib["seg_by_cp"]

trusted, food, blank = H.classify_syllables(font)
real = set(trusted)
missing = [cp for cp in range(0xAC00, 0xD7A4) if cp not in real]

# 인덱스
lv_donors = defaultdict(list)   # (l,v) -> 받침有 donor cps (분리 성공한 것만)
vt_donors = defaultdict(list)   # (v,t) -> donor cps (분리 성공)
lv0 = {}                        # (l,v) -> 받침無 donor cp
for cp in real:
    l, v, t = H.decomp(cp)
    if t > 0:
        if cp in seg_by_cp:
            lv_donors[(l, v)].append(cp)
            vt_donors[(v, t)].append(cp)
    else:
        lv0[(l, v)] = cp

def has_t_part(t, vc):
    return H.get_t_part(parts, t, vc) is not None

def has_l_part(l, vc, hast):
    if (l, vc, hast) in parts["L"]:
        return True
    # vclass fallback
    return any((l, c, hast) in parts["L"] for c in H.VCLASS_FALLBACK[vc])

def has_v_part(v, hast):
    return (v, hast) in parts["V"] or (v, not hast) in parts["V"]

plan = {}
counts = defaultdict(int)
unresolved = []
for cp in missing:
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    if t > 0 and lv_donors.get((l, v)) and has_t_part(t, vc):
        plan[cp] = "A"
    elif t > 0 and vt_donors.get((v, t)) and has_l_part(l, vc, True):
        plan[cp] = "C"
    elif t > 0 and (l, v) in lv0 and has_t_part(t, vc):
        plan[cp] = "B"
    elif t > 0 and has_l_part(l, vc, True) and has_v_part(v, True) and has_t_part(t, vc):
        plan[cp] = "D"
    elif t == 0 and has_l_part(l, vc, False) and has_v_part(v, False):
        plan[cp] = "D0"
    else:
        plan[cp] = "X"
        unresolved.append(cp)
    counts[plan[cp]] += 1

print("=== 조립 계획 분포 ===")
for k in ["A", "C", "B", "D", "D0", "X"]:
    print(f"{k}: {counts.get(k, 0)}자")

if unresolved:
    print("\n=== 미해결 ===")
    for cp in unresolved[:40]:
        l, v, t = H.decomp(cp)
        vc = H.vclass(v)
        why = []
        if t > 0 and not has_t_part(t, vc):
            why.append(f"T부품없음({H.T_LIST[t]},{vc}+fallback)")
        if not has_l_part(l, vc, t > 0):
            why.append(f"L부품없음({H.L_LIST[l]},{vc},{'T' if t>0 else 'noT'})")
        if not has_v_part(v, t > 0):
            why.append(f"V부품없음({H.V_LIST[v]})")
        print(f"  {chr(cp)} U+{cp:04X}: {' / '.join(why) or 'donor만 부족'}")
    print(f"  ... 총 {len(unresolved)}자")

with open("assembly_plan.pkl", "wb") as f:
    pickle.dump(plan, f)
print("\nassembly_plan.pkl 저장")
