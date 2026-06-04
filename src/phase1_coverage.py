# -*- coding: utf-8 -*-
"""Phase 1: 자소 분해 + 벌(bucket) 문맥 분류 + donor 커버리지 매트릭스.

산출물:
  coverage.json   - (자소, 문맥) 셀별 donor 수와 빈 셀 목록
  strategy.json   - 누락 8,654자별 조립 전략 분류 통계
"""
import json
from collections import defaultdict
from fontTools.ttLib import TTFont

FONT = "./source_font.ttf"

L_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")          # 19
V_LIST = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")        # 21
T_LIST = [""] + list("ㄱㄲ") + ["ㄳ"] + list("ㄴ") + ["ㄵ","ㄶ"] + list("ㄷㄹ") + \
         ["ㄺ","ㄻ","ㄼ","ㄽ","ㄾ","ㄿ","ㅀ"] + list("ㅁㅂ") + ["ㅄ"] + list("ㅅㅆㅇㅈㅊㅋㅌㅍㅎ")  # 28

# 모음 부류: 자소 모양이 달라지는 핵심 문맥
VERT = {0,1,2,3,4,5,6,7,20}            # ㅏㅐㅑㅒㅓㅔㅕㅖㅣ  (초성이 왼쪽)
HORIZ = {8,12,13,17,18}                # ㅗㅛㅜㅠㅡ          (초성이 위)
MIXED = {9,10,11,14,15,16,19}          # ㅘㅙㅚㅝㅞㅟㅢ      (혼합)

def vclass(v):
    return "vert" if v in VERT else ("horiz" if v in HORIZ else "mixed")

def decomp(cp):
    s = cp - 0xAC00
    return s // 588, (s % 588) // 28, s % 28

font = TTFont(FONT)
cmap = font.getBestCmap()
glyf = font["glyf"]

def has_outline(cp):
    gn = cmap.get(cp)
    if gn is None:
        return False
    g = glyf[gn]
    return g.isComposite() or (g.numberOfContours or 0) > 0

real = []     # 윤곽선 있는 음절 (donor 후보)
missing = []  # 채워야 할 음절
for cp in range(0xAC00, 0xD7A4):
    (real if has_outline(cp) else missing).append(cp)

print(f"donor(실제 글자): {len(real)}, 누락: {len(missing)}")

# ---- 커버리지 매트릭스 ----
# L-셀: (초성, 모음부류, 받침유무) / V-셀: (중성, 받침유무) / T-셀: (종성, 모음부류)
l_cell = defaultdict(list)
v_cell = defaultdict(list)
t_cell = defaultdict(list)
lv_pair_with_t = defaultdict(list)   # (L,V) 조합이 받침有로 존재하는 donor
lv_pair_no_t = {}                    # (L,V) 조합이 받침無로 존재
vt_pair = defaultdict(list)          # (V,T) 조합 donor (초성 교체용)

for cp in real:
    l, v, t = decomp(cp)
    vc = vclass(v)
    hast = t > 0
    l_cell[(l, vc, hast)].append(cp)
    v_cell[(v, hast)].append(cp)
    if t > 0:
        t_cell[(t, vc)].append(cp)
        lv_pair_with_t[(l, v)].append(cp)
        vt_pair[(v, t)].append(cp)
    else:
        lv_pair_no_t[(l, v)] = cp

# 빈 셀 검사 (누락 글자가 실제로 필요로 하는 셀만)
need_l, need_v, need_t = set(), set(), set()
for cp in missing:
    l, v, t = decomp(cp)
    vc = vclass(v)
    hast = t > 0
    need_l.add((l, vc, hast))
    need_v.add((v, hast))
    if t > 0:
        need_t.add((t, vc))

empty_l = sorted(c for c in need_l if not l_cell.get(c))
empty_v = sorted(c for c in need_v if not v_cell.get(c))
empty_t = sorted(c for c in need_t if not t_cell.get(c))

print("\n=== 빈 셀(donor가 하나도 없는 문맥) ===")
print("L-셀:", [(L_LIST[l], vc, ("받침有" if h else "받침無")) for l, vc, h in empty_l] or "없음")
print("V-셀:", [(V_LIST[v], ("받침有" if h else "받침無")) for v, h in empty_v] or "없음")
print("T-셀:", [(T_LIST[t], vc) for t, vc in empty_t] or "없음")

# ---- 누락 음절별 전략 분류 ----
strategy = defaultdict(list)
for cp in missing:
    l, v, t = decomp(cp)
    if t > 0 and lv_pair_with_t.get((l, v)):
        strategy["A_받침교체"].append(cp)        # 최상: (L,V,받침有) donor 존재
    elif t > 0 and (l, v) in lv_pair_no_t:
        strategy["B_받침추가"].append(cp)        # (L,V,무받침)만 존재 → LV 압축 or 조립
    elif t == 0 and lv_pair_with_t.get((l, v)):
        strategy["B2_받침제거"].append(cp)       # 받침有만 존재하는데 무받침이 누락
    elif t > 0 and vt_pair.get((v, t)):
        strategy["C_초성교체"].append(cp)        # (V,T) 동일 donor 존재 → 초성만 교체
    else:
        strategy["D_완전조립"].append(cp)        # 셋 다 다른 donor에서

print("\n=== 조립 전략 분포 (누락 8,654자) ===")
for k in ["A_받침교체", "B_받침추가", "B2_받침제거", "C_초성교체", "D_완전조립"]:
    lst = strategy.get(k, [])
    sample = " ".join(chr(c) for c in lst[:8])
    print(f"{k}: {len(lst)}자   예: {sample}")

# 스팟: 쫒, 찟
for ch in ["쫒", "찟"]:
    cp = ord(ch)
    for k, lst in strategy.items():
        if cp in lst:
            l, v, t = decomp(cp)
            donors = lv_pair_with_t.get((l, v), [])
            print(f"\n{ch}: 전략={k}, LV donor={[chr(d) for d in donors[:5]]}, "
                  f"T donor 후보={[chr(d) for d in t_cell.get((t, vclass(v)), [])[:5]]}")

# 셀별 donor 수 분포 (최소 donor 수 확인)
min_l = min((len(l_cell[c]) for c in need_l if l_cell.get(c)), default=0)
min_v = min((len(v_cell[c]) for c in need_v if v_cell.get(c)), default=0)
min_t = min((len(t_cell[c]) for c in need_t if t_cell.get(c)), default=0)
print(f"\n필요 셀 중 최소 donor 수: L-셀 {min_l}, V-셀 {min_v}, T-셀 {min_t}")

out = {
    "real_count": len(real),
    "missing_count": len(missing),
    "empty_cells": {"L": empty_l, "V": empty_v, "T": empty_t},
    "strategy_counts": {k: len(v) for k, v in strategy.items()},
    "strategy": {k: [f"U+{c:04X}" for c in v] for k, v in strategy.items()},
}
with open("coverage.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("\ncoverage.json 저장 완료")
