# -*- coding: utf-8 -*-
"""Phase 3: 누락 8,654자 조립 → TTF 주입.

전략 우선순위 (품질순):
  A 받침교체: (L,V,T') donor의 LV 유지 + 표준 T부품 삽입
  C 초성교체: (L',V,T) donor의 VT 유지 + 표준 L부품 삽입
  B 받침추가: (L,V,무받침) donor를 세로 압축 + T부품 삽입
  D 완전조립: L/V/T 부품을 통계 박스에 배치
배치 좌표·압축률은 같은 중성을 가진 실제 글자들의 통계에서 학습.
"""
import json
import pickle
import statistics
from collections import defaultdict
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphCoordinates
from fontTools.ttLib.tables import ttProgram
import numpy as np
import hannalib as H

SRC = H.FONT_PATH
OUT = "output/BMHANNAPro_Hangul11172.ttf"

font = TTFont(SRC)
cmap = font.getBestCmap()
glyf = font["glyf"]
hmtx = font["hmtx"]
H.init_compat(font)   # C케이스 donor 재검증용 호환 자모 기준

with open("parts_library.pkl", "rb") as f:
    lib = pickle.load(f)
parts, seg_by_cp = lib["parts"], lib["seg_by_cp"]
seg_l_by_cp = lib.get("seg_l_by_cp", {})

trusted, food, blank = H.classify_syllables(font)
real = set(trusted)
missing = [cp for cp in range(0xAC00, 0xD7A4) if cp not in real]
print(f"재조립 대상: {len(missing)}자 (빈 글리프 {len(blank)} + 음식그림 교체 {len(food)})")

contours_cache = {}
def contours_of(cp):
    if cp not in contours_cache:
        contours_cache[cp] = H.glyph_contours(font, cp)
    return contours_cache[cp]

# ---------------- donor 인덱스 ----------------
lv_donors = defaultdict(list)   # (l,v) -> [받침有 donor cp] (T분리 가능)
vt_donors = defaultdict(list)   # (v,t) -> [donor cp] (L분리 가능한 full seg)
vt_unit_donors = defaultdict(list)  # (v,t) -> [donor cp] (L|VT 부분 분리: 융합형)
lv0 = {}                        # (l,v) -> 받침無 donor cp
for cp in sorted(real):
    l, v, t = H.decomp(cp)
    seg = seg_by_cp.get(cp, (None,))[0]
    if t > 0:
        if seg and seg.get("T"):
            lv_donors[(l, v)].append(cp)
        if seg and seg.get("L") and seg.get("V"):
            vt_donors[(v, t)].append(cp)
        if cp in seg_l_by_cp:
            vt_unit_donors[(v, t)].append(cp)
    else:
        lv0[(l, v)] = cp

# ---------------- 배치 통계 (중성별) ----------------
# v별 받침有 문맥: L박스, V박스, T박스, LV묶음박스 / 받침無: 글리프박스
stat_lbox = defaultdict(list)
stat_tbox = defaultdict(list)
stat_lvbox = defaultdict(list)
stat_widths = defaultdict(list)
stat_not_box = defaultdict(list)   # v -> 무받침 음절 전체 bbox
for cp in sorted(real):
    l, v, t = H.decomp(cp)
    if t == 0:
        stat_not_box[v].append(H.group_bbox(contours_of(cp)))
for cp in sorted(real):
    seg = seg_by_cp.get(cp, (None,))[0]
    if not seg:
        continue
    l, v, t = H.decomp(cp)
    cs = contours_of(cp)
    if t > 0:
        if seg.get("T"):
            stat_tbox[v].append(H.group_bbox([cs[i] for i in seg["T"]]))
            lv_idx = seg.get("LV") or (seg.get("L", []) + seg.get("V", []))
            stat_lvbox[v].append(H.group_bbox([cs[i] for i in lv_idx]))
        if seg.get("L"):
            stat_lbox[(v, True)].append(H.group_bbox([cs[i] for i in seg["L"]]))
        stat_widths[(v, True)].append(hmtx[cmap[cp]][0])
    else:
        if seg.get("L"):
            stat_lbox[(v, False)].append(H.group_bbox([cs[i] for i in seg["L"]]))
        stat_widths[(v, False)].append(hmtx[cmap[cp]][0])

def med_box(boxes):
    if not boxes:
        return None
    return tuple(statistics.median(b[i] for b in boxes) for i in range(4))

def stat_or_vc(stat, v, hast=None):
    """v 단위 통계, 없으면 같은 vclass의 다른 v로 fallback."""
    key = v if hast is None else (v, hast)
    if stat.get(key):
        return stat[key]
    vc = H.vclass(v)
    pool = []
    for v2 in range(21):
        if H.vclass(v2) != vc:
            continue
        k2 = v2 if hast is None else (v2, hast)
        pool.extend(stat.get(k2, []))
    return pool

# 음절 바닥 하한 (T부품이 이보다 내려가면 위로 보정)
floor_y = np.percentile([H.group_bbox(contours_of(cp))[1]
                         for cp in sorted(real)], 1) - 10

# ---------------- 배치 유틸 ----------------
def place_t(t_part, anchor_box, lv_bottom):
    """T부품을 anchor(제거된 T̃ 또는 통계 T박스)에 맞춰 배치."""
    px0, py0, px1, py1 = H.group_bbox(t_part)
    dx = (anchor_box[0] + anchor_box[2]) / 2 - (px0 + px1) / 2
    dy = anchor_box[3] - py1                     # 윗변 정렬
    new_min = py0 + dy
    if new_min < floor_y:                        # 바닥 뚫으면 끌어올림
        dy += floor_y - new_min
        if py1 + dy > lv_bottom - 8:             # LV와 겹치면 맞춰 축소
            avail = (lv_bottom - 8) - floor_y
            ph = py1 - py0
            if avail > 30 and ph > avail:
                s = avail / ph
                cx = (px0 + px1) / 2
                t_part = [[(round(cx + (x - cx) * s),
                            round(floor_y + (y - py0) * s), f)
                           for x, y, f in c] for c in t_part]
                return t_part
    return H.translate(t_part, round(dx), round(dy))

def fit_into(part, box, mode="center"):
    """부품을 box에 배치. 크면 균등 축소, 작으면 그대로 중앙/정렬."""
    px0, py0, px1, py1 = H.group_bbox(part)
    pw, ph = px1 - px0, py1 - py0
    bw, bh = box[2] - box[0], box[3] - box[1]
    s = min(1.0, bw / max(pw, 1), bh / max(ph, 1))
    if s < 0.999:
        part = [[(round(px0 + (x - px0) * s), round(py0 + (y - py0) * s), f)
                 for x, y, f in c] for c in part]
        px0, py0, px1, py1 = H.group_bbox(part)
        pw, ph = px1 - px0, py1 - py0
    dx = box[0] + (bw - pw) / 2 - px0
    dy = box[1] + (bh - ph) / 2 - py0
    return H.translate(part, round(dx), round(dy))

def squeeze_y(contours, src_box, dst_y0, dst_y1):
    """세로 구간 선형 재매핑 (Case B: 무받침 LV → 받침有 비례)."""
    sy0, sy1 = src_box[1], src_box[3]
    k = (dst_y1 - dst_y0) / max(sy1 - sy0, 1)
    return [[(x, round(dst_y0 + (y - sy0) * k), f) for x, y, f in c]
            for c in contours]

def _pick_part(ordered_recs, jamo_ch, good=0.22, limit=0.35):
    """선호순 후보 중 '충분히 좋은' 첫 부품을, 없으면 jd 최소 부품을 선택."""
    best = None
    for rec in ordered_recs:
        if rec is None:
            continue
        d = H.jamo_dist(rec["contours"], jamo_ch)
        if d is None:
            continue
        if d <= good:
            return rec
        if best is None or d < best[0]:
            best = (d, rec)
    if best and best[0] <= limit:
        return best[1]
    return None

def get_l_part(l, vc, hast):
    # 복합모음의 초성 자리는 가로모음과 동일(좌상단) → horiz 문맥 선호
    order = ["horiz", "mixed", "vert"] if vc == "mixed" else [vc] + H.VCLASS_FALLBACK[vc]
    recs = [parts["L"].get((l, c, hast)) for c in order]
    recs += [parts["L"].get((l, c, not hast)) for c in order]
    return _pick_part(recs, H.L_LIST[l])

def get_v_part(v, hast):
    """V부품과 함께 '요청한 받침 문맥과 일치하는지'를 반환."""
    rec = _pick_part([parts["V"].get((v, hast))], H.V_LIST[v])
    if rec:
        return rec, True
    rec = _pick_part([parts["V"].get((v, not hast))], H.V_LIST[v])
    return rec, False

# ---------------- 케이스별 조립 ----------------
def compose_A(cp):
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    t_rec = H.get_t_part(parts, t, vc)
    if not t_rec:
        return None
    ref_cloud = H.part_pointcloud(t_rec["contours"])
    best = None
    for d in lv_donors.get((l, v), []):
        seg = seg_by_cp[d][0]
        cs = contours_of(d)
        told = [cs[i] for i in seg["T"]]
        lv_idx = seg.get("LV") or (seg.get("L", []) + seg.get("V", []))
        # 제거된 T̃가 그 셀의 표준 부품과 닮았는지 = 분리 신뢰도
        dl, dv, dt = H.decomp(d)
        ref_old = H.get_t_part(parts, dt, vc)
        val = H.chamfer(H.part_pointcloud(told),
                        H.part_pointcloud(ref_old["contours"])) if ref_old else 0.5
        if best is None or val < best[0]:
            best = (val, d, [cs[i] for i in lv_idx], H.group_bbox(told))
    if best is None:
        return None
    val, d, lv_cs, t_anchor = best
    lv_bottom = H.group_bbox(lv_cs)[1]
    new_t = place_t([c[:] for c in t_rec["contours"]], t_anchor, lv_bottom)
    width = hmtx[cmap[d]][0]
    warn = f"A-val={val:.2f}" if val > 0.30 else None
    return lv_cs + new_t, width, f"A:{chr(d)}", warn

def compose_C(cp):
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    l_rec = get_l_part(l, vc, True)
    if not l_rec:
        return None
    for d in vt_donors.get((v, t), []):
        seg = seg_by_cp[d][0]
        cs = contours_of(d)
        v_cs = [cs[i] for i in seg["V"]]
        t_cs = [cs[i] for i in seg.get("T", [])]
        # donor의 중성 분리가 확실한 경우만 사용 (옘류 오분리 차단)
        dv = H.jamo_dist(v_cs, H.V_LIST[v])
        if dv is None or dv > 0.15:
            continue
        lbox_old = H.group_bbox([cs[i] for i in seg["L"]])
        new_l = fit_into([c[:] for c in l_rec["contours"]], lbox_old)
        if H.ink_overlap(new_l, v_cs) > 0.10:   # 초성이 모음을 침범하면 다음 donor
            continue
        return new_l + v_cs + t_cs, hmtx[cmap[d]][0], f"C:{chr(d)}", None
    return None

def compose_C2(cp):
    """융합형 초성교체: 모음+받침이 한 획인 donor의 VT를 통째 유지, 초성만 교체."""
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    l_rec = get_l_part(l, vc, True)
    if not l_rec:
        return None
    for d in vt_unit_donors.get((v, t), []):
        seg = seg_l_by_cp[d]
        cs = contours_of(d)
        vt_cs = [cs[i] for i in seg["VT"]]
        lbox_old = H.group_bbox([cs[i] for i in seg["L"]])
        new_l = fit_into([c[:] for c in l_rec["contours"]], lbox_old)
        if H.ink_overlap(new_l, vt_cs) > 0.12:
            continue
        return new_l + vt_cs, hmtx[cmap[d]][0], f"C2:{chr(d)}", None
    return None


def compose_B(cp):
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    t_rec = H.get_t_part(parts, t, vc)
    d = lv0.get((l, v))
    if not t_rec or d is None:
        return None
    lv_box_t = med_box(stat_or_vc(stat_lvbox, v))
    t_box = med_box(stat_or_vc(stat_tbox, v))
    if not lv_box_t or not t_box:
        return None
    cs = contours_of(d)
    src_box = H.group_bbox(cs)
    lv_cs = squeeze_y(cs, src_box, lv_box_t[1], lv_box_t[3])
    anchor = (src_box[0] + (t_box[0] - lv_box_t[0]),
              t_box[1], src_box[0] + (t_box[2] - lv_box_t[0]), t_box[3])
    new_t = place_t([c[:] for c in t_rec["contours"]], anchor, lv_box_t[1])
    return lv_cs + new_t, hmtx[cmap[d]][0], f"B:{chr(d)}", None

lv_full = defaultdict(list)   # (l) -> [무받침 full-seg donor cp] (모음교체용)
for cp in sorted(real):
    l, v, t = H.decomp(cp)
    seg = seg_by_cp.get(cp, (None,))[0]
    if t == 0 and seg and seg.get("L") and seg.get("V"):
        lv_full[l].append(cp)


def compose_V(cp):
    """모음 교체 (무받침): 같은 초성의 실제 글자에서 모음만 바꿈 (뺴=빼의 ㅐ→ㅒ)."""
    l, v, t = H.decomp(cp)
    if t != 0:
        return None
    vc = H.vclass(v)
    v_rec, _ = get_v_part(v, False)
    if not v_rec:
        return None
    # donor: 같은 초성·같은 모음부류·같은 세로획 구조 우선
    bars = H.TALL_BARS.get(v)
    cands = []
    for d in lv_full.get(l, []):
        dv = H.decomp(d)[1]
        if H.vclass(dv) != vc:
            continue
        cands.append((0 if H.TALL_BARS.get(dv) == bars else 1, d))
    for _, d in sorted(cands):
        seg = seg_by_cp[d][0]
        cs = contours_of(d)
        l_cs = [cs[i] for i in seg["L"]]
        old_v = H.group_bbox([cs[i] for i in seg["V"]])
        new_v = [c[:] for c in v_rec["contours"]]
        nb = H.group_bbox(new_v)
        # 왼쪽 변·세로 중심을 기존 모음 자리에 정렬
        new_v = H.translate(new_v, round(old_v[0] - nb[0]),
                            round((old_v[1] + old_v[3]) / 2 - (nb[1] + nb[3]) / 2))
        if H.ink_overlap(l_cs, new_v) > 0.10:
            continue
        nb = H.group_bbox(new_v)
        width = hmtx[cmap[d]][0] + round((nb[2] - nb[0]) - (old_v[2] - old_v[0]))
        return l_cs + new_v, max(width, 400), f"V:{chr(d)}", None
    return None


def compose_B2(cp):
    """무받침 누락자: (L,V,받침有) donor의 LV만 추출해 무받침 비례로 확장."""
    l, v, t = H.decomp(cp)
    if t != 0:
        return None
    target = med_box(stat_or_vc(stat_not_box, v))
    if not target:
        return None
    for d in lv_donors.get((l, v), []):
        seg = seg_by_cp[d][0]
        cs = contours_of(d)
        lv_idx = seg.get("LV") or (seg.get("L", []) + seg.get("V", []))
        lv_cs = [cs[i] for i in lv_idx]
        src = H.group_bbox(lv_cs)
        out = squeeze_y(lv_cs, src, target[1], target[3])
        ws = stat_or_vc(stat_widths, v, False)
        width = round(statistics.median(ws)) if ws else hmtx[cmap[d]][0]
        return out, width, f"B2:{chr(d)}", None
    return None


def compose_D(cp):
    l, v, t = H.decomp(cp)
    vc = H.vclass(v)
    hast = t > 0
    l_rec = get_l_part(l, vc, hast)
    v_rec, v_ctx_ok = get_v_part(v, hast)
    if not l_rec or not v_rec:
        return None
    # V부품은 출처 음절의 절대좌표 유지 (가장 자연스러움)
    v_cs = [c[:] for c in v_rec["contours"]]
    if hast and not v_ctx_ok:
        # 무받침 문맥 V부품 → 받침 영역 위까지만 바닥을 끌어올림 (위는 고정)
        t_box_stat = med_box(stat_or_vc(stat_tbox, v))
        if t_box_stat:
            vb = H.group_bbox(v_cs)
            target_bottom = t_box_stat[3] + 20
            if vb[1] < target_bottom:
                v_cs = squeeze_y(v_cs, vb, target_bottom, vb[3])
    lbox = med_box(stat_or_vc(stat_lbox, v, hast))
    if not lbox:
        return None
    # 초성·모음 충돌 시 임계 완화 → 초성 축소(좌상단 고정) 순으로 재시도
    new_l = None
    for scale, thr in ((1.0, 0.10), (1.0, 0.25), (0.8, 0.25), (0.65, 0.30)):
        box = (lbox[0], lbox[3] - (lbox[3] - lbox[1]) * scale,
               lbox[0] + (lbox[2] - lbox[0]) * scale, lbox[3])
        cand = fit_into([c[:] for c in l_rec["contours"]], box)
        if H.ink_overlap(cand, v_cs) <= thr:
            new_l = cand
            break
    if new_l is None:
        return None
    out = new_l + v_cs
    warn = None
    if hast:
        t_rec = H.get_t_part(parts, t, vc)
        if not t_rec:
            return None
        t_box = med_box(stat_or_vc(stat_tbox, v))
        if not t_box:
            return None
        lv_bottom = H.group_bbox(out)[1]
        new_t = place_t([c[:] for c in t_rec["contours"]], t_box, lv_bottom)
        # 받침이 모음 하단과 충돌하면 아래로 밀고, 그래도 안 되면 축소
        for _ in range(4):
            if H.ink_overlap(new_t, out) <= 0.06:
                break
            tb = H.group_bbox(new_t)
            shift = max(20, (tb[3] - lv_bottom) // 2)
            if tb[1] - shift >= floor_y:
                new_t = H.translate(new_t, 0, -shift)
            else:
                tb = H.group_bbox(new_t)
                cx = (tb[0] + tb[2]) / 2
                new_t = [[(round(cx + (x - cx) * 0.85),
                           round(tb[3] - (tb[3] - y) * 0.85), f)
                          for x, y, f in c] for c in new_t]
        out = out + new_t
    ws = stat_or_vc(stat_widths, v, hast)
    width = round(statistics.median(ws)) if ws else 940
    return out, width, "D", warn

# ---------------- 글리프 주입 ----------------
def build_glyph(contours):
    g = Glyph()
    coords, flags, ends = [], [], []
    n = 0
    for c in contours:
        for x, y, f in c:
            coords.append((round(x), round(y)))
            flags.append(1 if f else 0)
        n += len(c)
        ends.append(n - 1)
    g.numberOfContours = len(contours)
    g.coordinates = GlyphCoordinates(coords)
    g.flags = bytearray(flags)
    g.endPtsOfContours = ends
    g.program = ttProgram.Program()
    g.program.fromBytecode(b"")
    return g

report = {"counts": defaultdict(int), "by_case": defaultdict(list),
          "warnings": [], "failed": [], "src_by_cp": {}}
for cp in missing:
    l, v, t = H.decomp(cp)
    # 복합모음은 L|V 분리가 불필요한 B(무받침 압축)를 C/D보다 우선
    if t == 0:
        chain = (compose_V, compose_D, compose_B2)
    elif H.vclass(v) == "mixed":
        chain = (compose_A, compose_B, compose_C, compose_D)
    else:
        chain = (compose_A, compose_C, compose_C2, compose_B, compose_D)
    result = None
    for fn in chain:
        result = fn(cp)
        if result:
            break
    if not result:
        report["failed"].append(f"U+{cp:04X} {chr(cp)}")
        continue
    contours, width, src, warn = result
    gname = cmap[cp]
    glyf[gname] = build_glyph(contours)
    xmin = min(p[0] for c in contours for p in c)
    hmtx[gname] = (width, round(xmin))
    case = src.split(":")[0]
    report["src_by_cp"][chr(cp)] = src
    report["counts"][case] += 1
    report["by_case"][case].append(chr(cp))
    if warn:
        report["warnings"].append(f"{chr(cp)}: {warn} ({src})")

print("=== 조립 결과 ===")
for k in ("A", "C", "B", "D"):
    print(f"{k}: {report['counts'].get(k, 0)}자")
print(f"실패: {len(report['failed'])}자", report["failed"][:10])
print(f"경고(분리 신뢰도 낮음): {len(report['warnings'])}건")

import os
os.makedirs("output", exist_ok=True)
font.save(OUT)
print(f"저장: {OUT}")

with open("compose_report.json", "w", encoding="utf-8") as f:
    json.dump({"counts": dict(report["counts"]),
               "warnings": report["warnings"],
               "failed": report["failed"],
               "src_by_cp": report["src_by_cp"]}, f, ensure_ascii=False, indent=1)
