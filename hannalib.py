# -*- coding: utf-8 -*-
"""한나체 자소 분해·조립 공용 라이브러리.

핵심 개념:
- Contour: TrueType 윤곽선 1개 = [(x, y, onCurve), ...]
- 분리(segment): 음절 글리프의 컨투어들을 초성(L)/중성(V)/종성(T)에 귀속
- 부품(part): 특정 문맥 셀에서 추출한 자소 컨투어 묶음 (절대좌표 유지)
- 합의(consensus): 같은 셀의 여러 donor에서 추출한 부품끼리 모양 유사도를
  비교해 medoid를 대표 부품으로 선정 → 분리 오류를 자동 배제
"""
import numpy as np
from collections import defaultdict
from fontTools.ttLib import TTFont

FONT_PATH = "./source_font.ttf"  # 보완 대상 원본 TTF를 이 이름으로 두거나 경로를 수정하세요

L_LIST = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
V_LIST = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
T_LIST = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ",
          "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ",
          "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"]

VERT = {0, 1, 2, 3, 4, 5, 6, 7, 20}      # ㅏㅐㅑㅒㅓㅔㅕㅖㅣ
HORIZ = {8, 12, 13, 17, 18}              # ㅗㅛㅜㅠㅡ
MIXED = {9, 10, 11, 14, 15, 16, 19}      # ㅘㅙㅚㅝㅞㅟㅢ

# 빈 T-셀 fallback: 해당 모음부류에 donor가 없으면 이 순서로 대체
VCLASS_FALLBACK = {"mixed": ["vert", "horiz"], "vert": ["mixed", "horiz"],
                   "horiz": ["mixed", "vert"]}


def vclass(v):
    return "vert" if v in VERT else ("horiz" if v in HORIZ else "mixed")


def decomp(cp):
    s = cp - 0xAC00
    return s // 588, (s % 588) // 28, s % 28


def compose_cp(l, v, t):
    return 0xAC00 + l * 588 + v * 28 + t


# ---------------------------------------------------------- donor 신뢰 분류

def ksx1001_syllables():
    """KS X 1001 표준 음절 2,350자."""
    out = set()
    for hi in range(0xB0, 0xC9):
        for lo in range(0xA1, 0xFF):
            try:
                ch = bytes([hi, lo]).decode("euc-kr")
                if 0xAC00 <= ord(ch) <= 0xD7A3:
                    out.add(ord(ch))
            except UnicodeDecodeError:
                pass
    return out


def classify_syllables(font):
    """음절을 (신뢰 donor, 음식그림 의심, 빈 글리프)로 분류.

    한나체 Pro 잔재인 음식 일러스트는 bbox가 글자 범위를 크게 벗어남.
    KS X 1001은 전부 신뢰, 추가분은 bbox 검사 통과분만 신뢰.
    """
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    ksx = ksx1001_syllables()
    trusted, food, blank = [], [], []
    for cp in range(0xAC00, 0xD7A4):
        gn = cmap.get(cp)
        if gn is None:
            blank.append(cp)
            continue
        g = glyf[gn]
        if not (g.isComposite() or (g.numberOfContours or 0) > 0):
            blank.append(cp)
            continue
        if cp in ksx:
            trusted.append(cp)
            continue
        x0, y0, x1, y1 = group_bbox(glyph_contours(font, cp))
        if -60 <= x0 and x1 <= 1060 and y0 >= -160 and 250 <= y1 <= 950:
            trusted.append(cp)
        else:
            food.append(cp)
    return trusted, food, blank


# ---------------------------------------------------------------- font I/O

def load_font(path=FONT_PATH):
    return TTFont(path)


def glyph_contours(font, cp):
    """음절 코드포인트 → [contour], contour = [(x, y, flag)] (절대좌표)."""
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    g = glyf[cmap[cp]]
    coords, ends, flags = g.getCoordinates(glyf)
    out, start = [], 0
    for e in ends:
        out.append([(coords[i][0], coords[i][1], flags[i] & 1)
                    for i in range(start, e + 1)])
        start = e + 1
    return out


def bbox(contour):
    xs = [p[0] for p in contour]
    ys = [p[1] for p in contour]
    return min(xs), min(ys), max(xs), max(ys)


def group_bbox(contours):
    bs = [bbox(c) for c in contours]
    return (min(b[0] for b in bs), min(b[1] for b in bs),
            max(b[2] for b in bs), max(b[3] for b in bs))


def translate(contours, dx, dy):
    return [[(x + dx, y + dy, f) for x, y, f in c] for c in contours]


# ------------------------------------------------------- contour flattening

def flatten_contour(contour, steps=6):
    """TrueType 2차 곡선 → 폴리라인. 암시적 on-curve 중점 처리 포함."""
    pts = contour
    n = len(pts)
    # 시작점을 on-curve로 정규화
    if not pts[0][2]:
        if pts[-1][2]:
            pts = pts[-1:] + pts[:-1]
        else:
            mid = ((pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2, 1)
            pts = [mid] + pts
        n = len(pts)
    poly = []
    i = 0
    while i < n:
        x, y, on = pts[i]
        if on:
            poly.append((x, y))
            i += 1
            continue
        # off-curve: 직전 on-curve(poly[-1])와 다음 on-curve 사이 2차 곡선
        x0, y0 = poly[-1]
        nxt = pts[(i + 1) % n]
        if nxt[2]:
            x2, y2 = nxt[0], nxt[1]
            i += 2
        else:  # 연속 off-curve → 암시적 중점
            x2, y2 = (x + nxt[0]) / 2, (y + nxt[1]) / 2
            i += 1
        for s in range(1, steps + 1):
            t = s / steps
            mt = 1 - t
            poly.append((mt * mt * x0 + 2 * mt * t * x + t * t * x2,
                         mt * mt * y0 + 2 * mt * t * y + t * t * y2))
    return poly


def part_pointcloud(contours, n_points=96):
    """부품(컨투어 묶음) → bbox 정규화된 점군 (모양 유사도용)."""
    polys = [flatten_contour(c) for c in contours]
    allpts = [p for poly in polys for p in poly]
    x0, y0 = min(p[0] for p in allpts), min(p[1] for p in allpts)
    x1, y1 = max(p[0] for p in allpts), max(p[1] for p in allpts)
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    scale = max(w, h)  # 종횡비 유지
    pts = np.array([((p[0] - x0) / scale, (p[1] - y0) / scale) for p in allpts])
    if len(pts) > n_points:
        idx = np.linspace(0, len(pts) - 1, n_points).astype(int)
        pts = pts[idx]
    return pts


def chamfer(a, b):
    """대칭 chamfer 거리 (작을수록 유사)."""
    d = np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)
    return float(d.min(axis=1).mean() + d.min(axis=0).mean())


# ------------------------------------------- 호환 자모 기준 분리 채점

_COMPAT = {}


def init_compat(font):
    """폰트에 내장된 호환 자모(U+3131~)를 분리 채점의 절대 기준으로 로드."""
    cmap = font.getBestCmap()
    glyf = font["glyf"]
    for ch in set(L_LIST) | set(V_LIST) | set(T_LIST[1:]):
        cp = ord(ch)
        gn = cmap.get(cp)
        if gn and (glyf[gn].isComposite() or (glyf[gn].numberOfContours or 0) > 0):
            _COMPAT[ch] = part_pointcloud(glyph_contours(font, cp))
    return len(_COMPAT)


def jamo_dist(part_contours, ch):
    """부품과 호환 자모의 모양 거리. 기준 없으면 None."""
    ref = _COMPAT.get(ch)
    if ref is None or not part_contours:
        return None
    return chamfer(part_pointcloud(part_contours), ref)


# ----------------------------------------------------- 구조 제약 (모음 획수)

# 중성별 기대 '키 큰 세로획' 개수 (vert·mixed만 검증)
TALL_BARS = {0: 1, 1: 2, 2: 1, 3: 2, 4: 1, 5: 2, 6: 1, 7: 2,   # ㅏㅐㅑㅒㅓㅔㅕㅖ
             9: 1, 10: 2, 11: 1, 14: 1, 15: 2, 16: 1, 19: 1,    # ㅘㅙㅚㅝㅞㅟㅢ
             20: 1}                                              # ㅣ


def _count_bars(contours_list, lv_h):
    """모음 세로획(키 크고 폭이 좁은 컨투어) 개수. ㄱ·ㅂ 같은 자음은 제외."""
    n = 0
    for c in contours_list:
        b = bbox(c)
        h_c, w_c = b[3] - b[1], b[2] - b[0]
        if h_c > 0.68 * lv_h and w_c < 0.75 * h_c:
            n += 1
    return n


def _sane_l_group(l_contours, lv_contours):
    """초성 그룹의 구조 새니티: 납작한 띠 한 줄이거나 전체 폭을 다 차지하면 오분할."""
    lb = group_bbox(l_contours)
    gb = group_bbox(lv_contours)
    lv_h = max(gb[3] - gb[1], 1)
    gw = max(gb[2] - gb[0], 1)
    if (lb[3] - lb[1]) < 0.22 * lv_h:      # 띠 조각
        return False
    if (lb[2] - lb[0]) > 0.85 * gw:        # 폭 전체 점유
        return False
    return True


def valid_lv_split(v, l_contours, v_contours):
    """L|V 분할이 모음 구조와 맞는지 검증 (ㅖ가 ㅣ로 쪼개지는 류의 오류 차단).

    V쪽 세로획 개수만 검사한다 — L쪽 제약은 세로로 긴 초성(ㄱㄲㅋ)을
    오판해 donor를 전멸시키므로 두지 않는다.
    """
    if v not in TALL_BARS:
        return True  # horiz 모음은 미검증
    all_c = l_contours + v_contours
    gy0 = min(bbox(c)[1] for c in all_c)
    gy1 = max(bbox(c)[3] for c in all_c)
    lv_h = max(gy1 - gy0, 1)
    if _count_bars(v_contours, lv_h) != TALL_BARS[v]:
        return False
    if v in MIXED:
        # 복합모음은 넓적한 가로 요소(ㅗ/ㅜ/ㅡ 부분)도 가져야 함
        gw = (max(bbox(c)[2] for c in all_c) - min(bbox(c)[0] for c in all_c)) or 1
        has_flat = any((bbox(c)[2] - bbox(c)[0]) > 0.5 * gw and
                       (bbox(c)[3] - bbox(c)[1]) < 0.5 * lv_h
                       for c in v_contours)
        if not has_flat:
            return False
    return True


# --------------------------------------------------------- 잉크 충돌 검사

def ink_mask(contours, box, size=64):
    """컨투어 실루엣(OR 채움) 비트맵. 충돌 검사용 — 속구멍은 무시."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    s = size / max(x1 - x0, y1 - y0, 1)
    acc = Image.new("1", (size, size), 0)
    d = ImageDraw.Draw(acc)
    for c in contours:
        poly = flatten_contour(c)
        d.polygon([((x - x0) * s, size - (y - y0) * s) for x, y in poly], fill=1)
    return np.array(acc, dtype=bool)


def ink_overlap(a_contours, b_contours):
    """두 부품의 잉크 겹침 비율 (작은 쪽 잉크 기준)."""
    ba, bb = group_bbox(a_contours), group_bbox(b_contours)
    box = (min(ba[0], bb[0]), min(ba[1], bb[1]),
           max(ba[2], bb[2]), max(ba[3], bb[3]))
    ma = ink_mask(a_contours, box)
    mb = ink_mask(b_contours, box)
    inter = (ma & mb).sum()
    return inter / max(min(ma.sum(), mb.sum()), 1)


# ------------------------------------------------------------ segmentation

def _split_by_gap(items, axis_lo, axis_hi, threshold_ratio=0.5):
    """컨투어들을 축 구간 [lo,hi] 사이 최대 간극으로 2분할.
    items: [(idx, lo_val, hi_val)] / 반환: (아래/왼쪽 그룹, 위/오른쪽 그룹, gap크기)"""
    order = sorted(items, key=lambda it: (it[1] + it[2]) / 2)
    best_gap, best_i = -1, None
    for i in range(len(order) - 1):
        lo_group_max = max(it[2] for it in order[:i + 1])
        hi_group_min = min(it[1] for it in order[i + 1:])
        gap = hi_group_min - lo_group_max
        if gap > best_gap:
            best_gap, best_i = gap, i
    if best_i is None:
        return [it[0] for it in order], [], 0
    return ([it[0] for it in order[:best_i + 1]],
            [it[0] for it in order[best_i + 1:]], best_gap)


def segment(cp, contours):
    """음절 컨투어를 L/V/T 인덱스 그룹으로 분리. 실패 시 None."""
    l, v, t = decomp(cp)
    vc = vclass(v)
    bs = [bbox(c) for c in contours]
    n = len(contours)
    gx0, gy0, gx1, gy1 = group_bbox(contours)
    h = gy1 - gy0

    idxs = list(range(n))
    t_idx = []
    if t > 0:
        # 종성: 세로 최대 간극으로 하단 분리
        items = [(i, bs[i][1], bs[i][3]) for i in idxs]
        low, high, gap = _split_by_gap(items, gy0, gy1)
        # 하단 그룹이 종성: 전체 높이의 45% 미만 영역 + 간극이 충분해야 함
        low_bb = group_bbox([contours[i] for i in low])
        if gap < 8 or low_bb[3] > gy0 + 0.50 * h or len(low) > 6:
            return None
        t_idx = low
        idxs = high
    if not idxs:
        return None

    def pick_best(cands, dv_max):
        """[(L그룹, V그룹)] 후보를 호환 자모 거리로 채점해 최적 선택.

        초성·중성이 한 획으로 융합된 글자(예: 똑의 ㄸ+ㅗ)는 어떤 분할도
        잉크가 서로 포함돼 버리므로 ink_overlap 게이트로 거부한다.
        """
        best = None
        for l_grp, v_grp in cands:
            if not l_grp or not v_grp:
                continue
            if not _sane_l_group([contours[i] for i in l_grp],
                                 [contours[i] for i in l_grp + v_grp]):
                continue
            dv = jamo_dist([contours[i] for i in v_grp], V_LIST[v])
            if dv is None or dv > dv_max:
                continue
            dl = jamo_dist([contours[i] for i in l_grp], L_LIST[l]) or 0.0
            score = dv + 0.3 * dl
            if best is None or score < best[0]:
                best = (score, l_grp, v_grp)
        if best is None:
            return None
        if ink_overlap([contours[i] for i in best[1]],
                       [contours[i] for i in best[2]]) > 0.30:
            return None
        return {"L": best[1], "V": best[2], "T": t_idx}

    if vc == "vert":
        # 초성 왼쪽 | 중성 오른쪽: x순 prefix 후보를 자모 기준으로 채점
        order = sorted(idxs, key=lambda i: (bs[i][0] + bs[i][2]) / 2)
        cands = []
        for k in range(1, len(order)):
            right = order[k:]
            rb = group_bbox([contours[i] for i in right])
            if (rb[3] - rb[1]) < 0.4 * h:
                continue
            cands.append((order[:k], right))
        return pick_best(cands, dv_max=0.22)

    if vc == "horiz":
        # 초성 위 | 중성 아래: y순 prefix 후보 채점
        order = sorted(idxs, key=lambda i: (bs[i][1] + bs[i][3]) / 2)
        cands = [(order[k:], order[:k]) for k in range(1, len(order))]
        return pick_best(cands, dv_max=0.30)

    # mixed (ㅘㅙㅚㅝㅞㅟㅢ): 휴리스틱 초기안 + 1-flip 변형들을 채점
    rem_bb = group_bbox([contours[i] for i in idxs])
    rx0, ry0, rx1, ry1 = rem_bb
    rw, rh = max(rx1 - rx0, 1), max(ry1 - ry0, 1)
    init_v = []
    for i in idxs:
        b = bs[i]
        cx = (b[0] + b[2]) / 2
        tall = (b[3] - b[1]) > 0.5 * rh
        wide_flat = (b[2] - b[0]) > 0.55 * rw and (b[3] - b[1]) < 0.45 * rh
        if (cx > rx0 + 0.62 * rw and tall) or wide_flat:
            init_v.append(i)
    cands = []
    base_l = [i for i in idxs if i not in init_v]
    if init_v and base_l:
        cands.append((base_l, init_v))
    for flip in idxs:
        nv = [i for i in init_v if i != flip] if flip in init_v else init_v + [flip]
        nl = [i for i in idxs if i not in nv]
        if nv and nl:
            cands.append((nl, nv))
    return pick_best(cands, dv_max=0.25)


# ------------------------------------------------- T-only segmentation

def segment_t(cp, contours, ref_t=None):
    """종성만 분리 (L|V 분할 불필요한 Case A용). 반환: ({"T","LV"}, score)|None.

    ㄱ+ㅗ처럼 초성·중성이 한 획으로 붙은 글자도 처리 가능.
    """
    l, v, t = decomp(cp)
    if t == 0:
        return None
    n = len(contours)
    if n < 2:
        return None
    bs = [bbox(c) for c in contours]
    gx0, gy0, gx1, gy1 = group_bbox(contours)
    h = max(gy1 - gy0, 1)
    order = sorted(range(n), key=lambda i: (bs[i][1] + bs[i][3]) / 2)
    cands = []
    for k in range(1, min(6, n)):
        grp, rest = order[:k], order[k:]
        gb = group_bbox([contours[i] for i in grp])
        if gb[3] > gy0 + 0.55 * h:
            break
        rest_min = min(bs[i][1] for i in rest)
        gap = rest_min - gb[3]
        if gap < 10:
            continue
        cands.append((grp, rest, gap))
    if not cands:
        return None
    if ref_t is not None:
        scored = sorted(
            (chamfer(part_pointcloud([contours[i] for i in grp]),
                     part_pointcloud(ref_t["contours"])), grp, rest)
            for grp, rest, _ in cands)
        d, grp, rest = scored[0]
        if d > 0.35:
            return None
        return {"T": grp, "LV": rest}, d
    grp, rest, gap = max(cands, key=lambda x: x[2])
    return {"T": grp, "LV": rest}, None


# ------------------------------------------- L | (V+T 융합) 부분 분리

def segment_l(cp, contours):
    """초성만 분리 (모음+받침이 융합된 가로/복합모음 글자용).

    반환: {"L": [...], "VT": [...]} 또는 None.
    쭉(ㅜ+ㄱ 융합)처럼 V|T 분리가 불가능해도 초성 교체는 가능하게 한다.
    """
    l, v, t = decomp(cp)
    vc = vclass(v)
    if vc != "horiz":
        # mixed는 모음 세로획이 글자 위까지 닿아 '상단=초성' 가정이 깨짐
        return None
    n = len(contours)
    if n < 2:
        return None
    bs = [bbox(c) for c in contours]
    # 가로모음 글자의 초성은 상단 → centerY 내림차순 prefix
    order = sorted(range(n), key=lambda i: -(bs[i][1] + bs[i][3]) / 2)
    gx0, gy0, gx1, gy1 = group_bbox(contours)
    h = max(gy1 - gy0, 1)
    best = None
    for k in range(1, n):
        l_grp, rest = order[:k], order[k:]
        l_cs = [contours[i] for i in l_grp]
        lb = group_bbox(l_cs)
        # 초성은 상부에만: ㄱ+ㅠ처럼 모음까지 융합된 덩어리를 L로 오인 방지
        if (lb[3] - lb[1]) > 0.55 * h or (lb[1] - gy0) < 0.35 * h:
            continue
        rb = group_bbox([contours[i] for i in rest])
        if (rb[3] - gy0) < 0.45 * h:   # VT가 받침뿐이면 모음 실종
            continue
        # 모음 영역(상부 밴드)의 VT 잉크는 넓어야 함 — 구멍 컨투어만 있으면 거부
        band_lo = gy0 + 0.45 * h
        band = [bbox(contours[i]) for i in rest
                if bbox(contours[i])[3] > band_lo]
        if not band:
            continue
        band_w = max(b[2] for b in band) - min(b[0] for b in band)
        if band_w < 0.5 * (gx1 - gx0):
            continue
        d = jamo_dist(l_cs, L_LIST[l])
        if d is None or d > 0.30:
            continue
        if ink_overlap(l_cs, [contours[i] for i in rest]) > 0.15:
            continue
        if best is None or d < best[0]:
            best = (d, l_grp, rest)
    if best is None:
        return None
    return {"L": best[1], "VT": best[2]}


# ------------------------------------------------- 겹받침 합성 fallback

# 겹받침 → (왼쪽 단일받침 T인덱스, 오른쪽 단일받침 T인덱스)
DOUBLES = {3: (1, 19), 5: (4, 22), 6: (4, 27), 9: (8, 1), 10: (8, 16),
           11: (8, 17), 12: (8, 19), 13: (8, 25), 14: (8, 26), 15: (8, 27),
           18: (17, 19)}


def split_double_part(contours):
    """겹받침 부품을 x-간극으로 좌/우 컴포넌트 분할. 붙어 있으면 None."""
    if len(contours) < 2:
        return None
    bs = [bbox(c) for c in contours]
    order = sorted(range(len(contours)), key=lambda i: (bs[i][0] + bs[i][2]) / 2)
    best = (None, -1)
    for k in range(1, len(order)):
        lmax = max(bs[i][2] for i in order[:k])
        rmin = min(bs[i][0] for i in order[k:])
        if rmin - lmax > best[1]:
            best = (k, rmin - lmax)
    k, gap = best
    if k is None or gap < 5:
        return None
    return ([contours[i] for i in order[:k]], [contours[i] for i in order[k:]])


def scale_to_box(contours, box):
    """부품을 종횡비 유지한 채 box 안에 중앙 배치."""
    x0, y0, x1, y1 = group_bbox(contours)
    cw, ch = max(x1 - x0, 1), max(y1 - y0, 1)
    bw, bh = box[2] - box[0], box[3] - box[1]
    s = min(bw / cw, bh / ch)
    ox = box[0] + (bw - cw * s) / 2
    oy = box[1] + (bh - ch * s) / 2
    return [[(round(ox + (x - x0) * s), round(oy + (y - y0) * s), f)
             for x, y, f in c] for c in contours]


def synth_double_finals(parts, needed_t_cells):
    """모든 vclass에서 부품이 없는 겹받침 셀을 좌/우 컴포넌트 합성으로 생성."""
    added = []
    for (t, vc) in sorted(needed_t_cells):
        if get_t_part(parts, t, vc) or t not in DOUBLES:
            continue
        a, b = DOUBLES[t]
        # 좌/우 박스 템플릿: 분할 가능한 기존 겹받침
        tmpl = None
        for c in [vc] + VCLASS_FALLBACK[vc]:
            for t2 in DOUBLES:
                rec = parts["T"].get((t2, c))
                if rec:
                    sp = split_double_part(rec["contours"])
                    if sp:
                        tmpl = sp
                        break
            if tmpl:
                break
        if not tmpl:
            continue
        lbox, rbox = group_bbox(tmpl[0]), group_bbox(tmpl[1])

        def find_comp(single_t, side):
            # 같은 컴포넌트를 가진 기존 겹받침에서 절반 추출 (비례 자연스러움)
            for c in [vc] + VCLASS_FALLBACK[vc]:
                for t2, (a2, b2) in DOUBLES.items():
                    if (a2 if side == 0 else b2) != single_t:
                        continue
                    rec = parts["T"].get((t2, c))
                    if rec:
                        sp = split_double_part(rec["contours"])
                        if sp:
                            return sp[side]
            rec = get_t_part(parts, single_t, vc)  # 단일받침 축소 fallback
            return rec["contours"] if rec else None

        left, right = find_comp(a, 0), find_comp(b, 1)
        if left is None or right is None:
            continue
        contours = scale_to_box(left, lbox) + scale_to_box(right, rbox)
        parts["T"][(t, vc)] = {"contours": contours, "src_cp": None,
                               "score": None, "n": 0, "synth": True}
        added.append((t, vc))
    return added


# ------------------------------------------------- guided segmentation

def _part_dist(contours_part, ref_record):
    if not contours_part or ref_record is None:
        return 9.9
    return chamfer(part_pointcloud(contours_part),
                   part_pointcloud(ref_record["contours"]))


def guided_segment(cp, contours, parts):
    """기준 부품(parts)과의 유사도로 최적 분할을 탐색하는 2-pass 분리.

    반환: (seg dict, score) 또는 (None, None). score가 작을수록 신뢰 높음.
    """
    l, v, t = decomp(cp)
    vc = vclass(v)
    n = len(contours)
    if n < 2:
        return None, None
    idx_all = list(range(n))
    bs = [bbox(c) for c in contours]
    gx0, gy0, gx1, gy1 = group_bbox(contours)
    h = max(gy1 - gy0, 1)

    ref_t = get_t_part(parts, t, vc) if t > 0 else None
    ref_l = parts["L"].get((l, vc, t > 0))
    ref_v = parts["V"].get((v, t > 0))

    # 종성 후보: centerY 오름차순 누적 prefix (하단 45% 안에서)
    t_candidates = [([], idx_all)]
    if t > 0:
        order = sorted(idx_all, key=lambda i: (bs[i][1] + bs[i][3]) / 2)
        for k in range(1, min(6, n)):
            grp = order[:k]
            gb = group_bbox([contours[i] for i in grp])
            if gb[3] > gy0 + 0.55 * h:
                break
            t_candidates.append((grp, order[k:]))
        t_candidates = t_candidates[1:]  # T 필수
        if not t_candidates:
            return None, None

    best = (None, 1e9)
    for t_grp, rest in t_candidates:
        if not rest:
            continue
        d_t = _part_dist([contours[i] for i in t_grp], ref_t) if t > 0 else 0.0
        # L|V 분할 후보 생성
        lv_splits = []
        if vc == "vert":
            order = sorted(rest, key=lambda i: (bs[i][0] + bs[i][2]) / 2)
            for k in range(1, len(order)):
                lv_splits.append((order[:k], order[k:]))
        elif vc == "horiz":
            order = sorted(rest, key=lambda i: (bs[i][1] + bs[i][3]) / 2)
            for k in range(1, len(order)):
                lv_splits.append((order[k:], order[:k]))  # 위=L, 아래=V
        else:  # mixed: 휴리스틱 초기화 + 1-flip 탐색
            rb = group_bbox([contours[i] for i in rest])
            rw = max(rb[2] - rb[0], 1)
            rh = max(rb[3] - rb[1], 1)
            init_v = []
            for i in rest:
                b = bs[i]
                cx = (b[0] + b[2]) / 2
                tall = (b[3] - b[1]) > 0.5 * rh
                wide_flat = (b[2] - b[0]) > 0.55 * rw and (b[3] - b[1]) < 0.45 * rh
                if (cx > rb[0] + 0.62 * rw and tall) or wide_flat:
                    init_v.append(i)
            base_l = [i for i in rest if i not in init_v]
            cands = []
            if init_v and base_l:
                cands.append((base_l, init_v))
            for flip in rest:  # 1-flip 변형
                nv = [i for i in init_v if i != flip] if flip in init_v \
                    else init_v + [flip]
                nl = [i for i in rest if i not in nv]
                if nv and nl:
                    cands.append((nl, nv))
            lv_splits = cands
        for l_grp, v_grp in lv_splits:
            if not _sane_l_group([contours[i] for i in l_grp],
                                 [contours[i] for i in l_grp + v_grp]):
                continue
            dv_compat = jamo_dist([contours[i] for i in v_grp], V_LIST[v])
            if dv_compat is not None and dv_compat > 0.25:
                continue
            d_l = _part_dist([contours[i] for i in l_grp], ref_l)
            d_v = _part_dist([contours[i] for i in v_grp], ref_v)
            score = d_t + d_l + d_v
            if score < best[1]:
                best = ({"L": l_grp, "V": v_grp, "T": t_grp}, score)
    if best[0] is None:
        return None, None
    seg = best[0]
    if seg.get("L") and seg.get("V"):
        if ink_overlap([contours[i] for i in seg["L"]],
                       [contours[i] for i in seg["V"]]) > 0.30:
            return None, None
    return best


# --------------------------------------------------- part library building

def _consensus(cells, max_donors=14):
    """셀별 후보들에서 medoid 대표 부품 선정."""
    parts = {"T": {}, "L": {}, "V": {}}
    low_consensus = []
    for kind in ("T", "L", "V"):
        for cell, recs in cells[kind].items():
            recs = recs[:max_donors]
            cands = []
            for cp, contours, seg in recs:
                part = [contours[i] for i in seg.get(kind, [])]
                if part:
                    cands.append((cp, part))
            if not cands:
                continue
            if len(cands) == 1:
                cp, part = cands[0]
                parts[kind][cell] = {"contours": part, "src_cp": cp,
                                     "score": None, "n": 1}
                continue
            clouds = [part_pointcloud(p) for _, p in cands]
            m = len(cands)
            dist = np.zeros((m, m))
            for i in range(m):
                for j in range(i + 1, m):
                    d = chamfer(clouds[i], clouds[j])
                    dist[i][j] = dist[j][i] = d
            med = int(np.argmin(dist.sum(axis=1)))
            others = dist[med][dist[med] > 0]
            score = float(np.median(others)) if others.size else 0.0
            cp, part = cands[med]
            parts[kind][cell] = {"contours": part, "src_cp": cp,
                                 "score": score, "n": m}
            if score > 0.08:
                low_consensus.append((kind, cell, score))
    return parts, low_consensus


def _add_to_cells(cells, cp, contours, seg):
    l, v, t = decomp(cp)
    vc = vclass(v)
    rec = (cp, contours, seg)
    if t > 0 and seg.get("T"):
        cells["T"][(t, vc)].append(rec)
    if seg.get("L"):
        cells["L"][(l, vc, t > 0)].append(rec)
    if seg.get("V"):
        cells["V"][(v, t > 0)].append(rec)


def extract_parts(font, real_cps, max_donors=14, guided_threshold=0.40):
    """2-pass 부품 추출.

    pass1: 기하 휴리스틱 분리 성공분으로 1차 합의 부품 구축
    pass2: 실패 donor를 1차 부품 기준 guided_segment로 재시도

    반환: parts, seg_by_cp({cp: (seg, score|None)}), stats
    """
    n_compat = init_compat(font)
    cells = {"T": defaultdict(list), "L": defaultdict(list), "V": defaultdict(list)}
    seg_by_cp = {}
    failed = []
    contours_by_cp = {}
    for cp in real_cps:
        contours = glyph_contours(font, cp)
        contours_by_cp[cp] = contours
        seg = segment(cp, contours)
        if seg is None:
            failed.append(cp)
            continue
        seg_by_cp[cp] = (seg, None)
        _add_to_cells(cells, cp, contours, seg)

    parts, _ = _consensus(cells, max_donors)

    rescued = 0
    for cp in failed:
        seg, score = guided_segment(cp, contours_by_cp[cp], parts)
        if seg is not None and score < guided_threshold:
            seg_by_cp[cp] = (seg, score)
            _add_to_cells(cells, cp, contours_by_cp[cp], seg)
            rescued += 1

    parts, _ = _consensus(cells, max_donors)

    # pass3: 여전히 미분리인 받침有 donor → T-전용 분리 (Case A·T셀 보강)
    t_only = 0
    for cp in failed:
        if cp in seg_by_cp:
            continue
        l, v, t = decomp(cp)
        if t == 0:
            continue
        ref = get_t_part(parts, t, vclass(v))
        res = segment_t(cp, contours_by_cp[cp], ref)
        if res is None and ref is not None:  # ref가 나빠 거부됐을 수 있음 → 구조만으로 재시도
            res = segment_t(cp, contours_by_cp[cp], None)
        if res is not None:
            seg, score = res
            seg_by_cp[cp] = (seg, score)
            _add_to_cells(cells, cp, contours_by_cp[cp], seg)
            t_only += 1

    # pass4: 초성|나머지 부분 분리 — 모음·받침 융합 글자도 L부품 donor +
    # 초성교체(C2) donor로 활용
    seg_l_by_cp = {}
    l_only = 0
    for cp in real_cps:
        seg_full = seg_by_cp.get(cp, (None,))[0]
        if seg_full and seg_full.get("L"):
            continue
        seg = segment_l(cp, contours_by_cp[cp])
        if seg is not None:
            seg_l_by_cp[cp] = seg
            _add_to_cells(cells, cp, contours_by_cp[cp], seg)
            l_only += 1

    parts, low_consensus = _consensus(cells, max_donors)
    stats = {"total": len(real_cps), "pass1_ok": len(real_cps) - len(failed),
             "rescued": rescued, "t_only": t_only, "l_only": l_only,
             "unsegmented": len(failed) - rescued - t_only}
    return parts, seg_by_cp, seg_l_by_cp, stats, low_consensus


def get_t_part(parts, t, vc):
    """T부품 조회 (빈 셀이면 모음부류 fallback)."""
    for c in [vc] + VCLASS_FALLBACK[vc]:
        if (t, c) in parts["T"]:
            return parts["T"][(t, c)]
    return None
