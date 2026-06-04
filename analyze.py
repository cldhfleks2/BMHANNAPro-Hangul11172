# -*- coding: utf-8 -*-
"""한나체 TTF 한글 커버리지 분석 스크립트.

목적: cmap에 매핑된 한글 음절(U+AC00~U+D7A3) 커버리지, 빈 글리프 여부,
자모 글리프/GSUB 조합 기능 유무를 조사해 누락 글자 보완 전략의 근거를 만든다.
"""
import json
import sys
from fontTools.ttLib import TTFont

FONT = "./source_font.ttf"

font = TTFont(FONT)
cmap = font.getBestCmap()
glyf = font["glyf"] if "glyf" in font else None

print("=== 기본 정보 ===")
print("tables:", sorted(font.keys()))
print("numGlyphs:", font["maxp"].numGlyphs)
print("unitsPerEm:", font["head"].unitsPerEm)
name = font["name"]
for nid in (1, 2, 4, 6):
    rec = name.getDebugName(nid)
    print(f"name[{nid}]:", rec)

def is_blank(gname):
    """outline이 전혀 없는 글리프인지 (glyf 기준)."""
    if glyf is None:
        return False
    g = glyf[gname]
    if g.isComposite():
        return False
    return (g.numberOfContours or 0) <= 0

# 1) 한글 음절 커버리지
total = 0
mapped = []
missing = []
blank_mapped = []
for cp in range(0xAC00, 0xD7A4):
    total += 1
    if cp in cmap:
        gname = cmap[cp]
        if is_blank(gname):
            blank_mapped.append(cp)
        else:
            mapped.append(cp)
    else:
        missing.append(cp)

print("\n=== 한글 음절 (U+AC00-U+D7A3) ===")
print(f"전체: {total}, 정상 매핑: {len(mapped)}, 누락(cmap 없음): {len(missing)}, 매핑됐지만 빈 글리프: {len(blank_mapped)}")

# 예시 확인: 쫒, 찟
for ch in ["쫒", "찟", "쫓", "찢", "값", "힣", "뷁", "쀍"]:
    cp = ord(ch)
    state = "OK" if (cp in cmap and not is_blank(cmap[cp])) else ("BLANK" if cp in cmap else "MISSING")
    print(f"  {ch} U+{cp:04X}: {state}")

# 2) 자모 영역 커버리지
def count_range(lo, hi):
    have = sum(1 for cp in range(lo, hi + 1) if cp in cmap and not is_blank(cmap[cp]))
    return have, hi - lo + 1

for label, lo, hi in [
    ("호환 자모 U+3131-U+318E", 0x3131, 0x318E),
    ("첫가끝 초성 U+1100-U+115F", 0x1100, 0x115F),
    ("첫가끝 중성 U+1160-U+11A7", 0x1160, 0x11A7),
    ("첫가끝 종성 U+11A8-U+11FF", 0x11A8, 0x11FF),
]:
    have, tot = count_range(lo, hi)
    print(f"{label}: {have}/{tot}")

# 3) GSUB 조합 기능(ljmo/vjmo/tjmo/ccmp) 여부
print("\n=== GSUB/GPOS ===")
for tag in ("GSUB", "GPOS"):
    if tag in font:
        t = font[tag].table
        feats = sorted({fr.FeatureTag for fr in (t.FeatureList.FeatureRecord or [])}) if t.FeatureList else []
        print(f"{tag} features:", feats)
    else:
        print(f"{tag}: 없음")

# 4) KS X 1001 2350자와의 관계 추정: 누락 목록 저장
with open("missing_syllables.json", "w", encoding="utf-8") as f:
    json.dump({
        "missing": [f"U+{cp:04X} {chr(cp)}" for cp in missing],
        "blank_mapped": [f"U+{cp:04X} {chr(cp)}" for cp in blank_mapped],
    }, f, ensure_ascii=False, indent=1)
print(f"\n누락 목록 저장: missing_syllables.json (missing {len(missing)}, blank {len(blank_mapped)})")

# 5) 음절 글리프가 composite(부품 조합)인지 단일 outline인지 샘플 확인
print("\n=== 음절 글리프 구조 샘플 ===")
for ch in ["가", "값", "쫓", "찢", "한"]:
    cp = ord(ch)
    if cp in cmap and glyf is not None:
        g = glyf[cmap[cp]]
        kind = "composite" if g.isComposite() else f"simple({g.numberOfContours} contours)"
        print(f"  {ch}: {cmap[cp]} -> {kind}")
