# -*- coding: utf-8 -*-
"""Phase 2: 부품 라이브러리 구축 + 분리 품질 리포트 + 부품 시트 렌더링."""
import pickle
from PIL import Image, ImageDraw
import hannalib as H

font = H.load_font()
cmap = font.getBestCmap()
glyf = font["glyf"]

real, food, blank = H.classify_syllables(font)
print(f"신뢰 donor {len(real)}자 (음식그림 {len(food)}자 제외)에서 부품 추출 중...")
parts, seg_by_cp, seg_l_by_cp, stats, low_consensus = H.extract_parts(font, real)

print(f"pass1 성공: {stats['pass1_ok']}/{stats['total']}, "
      f"guided 구제: {stats['rescued']}, T-전용 구제: {stats['t_only']}, "
      f"L-전용 구제: {stats['l_only']}, 최종 미분리: {stats['unsegmented']}")

# 겹받침 합성 fallback (모든 vclass에 부품이 없는 셀만)
needed_t_cells = set()
real_set = set(real)
for cp in range(0xAC00, 0xD7A4):
    if cp in real_set:
        continue
    l, v, t = H.decomp(cp)
    if t > 0:
        needed_t_cells.add((t, H.vclass(v)))
synth_added = H.synth_double_finals(parts, needed_t_cells)
print(f"겹받침 합성으로 생성된 T셀: {[(H.T_LIST[t], vc) for t, vc in synth_added] or '없음'}")
for kind in ("L", "V", "T"):
    print(f"{kind} 부품 셀: {len(parts[kind])}개")
print(f"합의도 낮은 셀(요주의): {len(low_consensus)}개")
for kind, cell, score in sorted(low_consensus, key=lambda x: -x[2])[:15]:
    if kind == "T":
        label = f"종성 {H.T_LIST[cell[0]]} ({cell[1]})"
    elif kind == "L":
        label = f"초성 {H.L_LIST[cell[0]]} ({cell[1]}, {'받침有' if cell[2] else '받침無'})"
    else:
        label = f"중성 {H.V_LIST[cell[0]]} ({'받침有' if cell[1] else '받침無'})"
    print(f"  {label}: score={score:.3f} (src={chr(parts[kind][cell]['src_cp'])})")

with open("parts_library.pkl", "wb") as f:
    pickle.dump({"parts": parts, "seg_by_cp": seg_by_cp,
                 "seg_l_by_cp": seg_l_by_cp}, f)
print("parts_library.pkl 저장 (부품 + donor별 분리 결과)")

# ---------------- 부품 시트 렌더링 ----------------
CELL = 80

def render_part(contours, size=CELL):
    """부품을 even-odd(XOR) 채움으로 셀 이미지에 렌더."""
    import PIL.ImageChops as IC
    if not contours:
        return Image.new("L", (size, size), 255)
    x0, y0, x1, y1 = H.group_bbox(contours)
    w, h = max(x1 - x0, 1), max(y1 - y0, 1)
    s = (size - 12) / max(w, h)
    ox = (size - w * s) / 2
    oy = (size - h * s) / 2
    acc = Image.new("1", (size, size), 0)
    for c in contours:
        poly = H.flatten_contour(c)
        pts = [(ox + (x - x0) * s, size - (oy + (y - y0) * s)) for x, y in poly]
        mask = Image.new("1", (size, size), 0)
        ImageDraw.Draw(mask).polygon(pts, fill=1)
        acc = IC.logical_xor(acc, mask)
    return Image.eval(acc.convert("L"), lambda v: 255 - v)

def sheet(items, cols, path, label_fn):
    """items: [(label, contours)] → 그리드 PNG."""
    rows = (len(items) + cols - 1) // cols
    img = Image.new("L", (cols * CELL, rows * (CELL + 14)), 255)
    d = ImageDraw.Draw(img)
    for i, (label, contours) in enumerate(items):
        r, c = divmod(i, cols)
        y = r * (CELL + 14)
        if contours:
            img.paste(render_part(contours), (c * CELL, y))
        d.text((c * CELL + 2, y + CELL), label, fill=0)
    img.save(path)
    print(f"{path} 저장 ({len(items)}부품)")

t_items = []
for vc in ("vert", "horiz", "mixed"):
    for t in range(1, 28):
        rec = parts["T"].get((t, vc))
        t_items.append((f"{H.T_LIST[t]}/{vc[0]}", rec["contours"] if rec else None))
sheet(t_items, 27, "parts_T.png", None)

l_items = []
for hast in (False, True):
    for vc in ("vert", "horiz", "mixed"):
        for l in range(19):
            rec = parts["L"].get((l, vc, hast))
            l_items.append((f"{H.L_LIST[l]}/{vc[0]}{'T' if hast else ''}",
                            rec["contours"] if rec else None))
sheet(l_items, 19, "parts_L.png", None)

v_items = []
for hast in (False, True):
    for v in range(21):
        rec = parts["V"].get((v, hast))
        v_items.append((f"{H.V_LIST[v]}{'/T' if hast else ''}",
                        rec["contours"] if rec else None))
sheet(v_items, 21, "parts_V.png", None)
