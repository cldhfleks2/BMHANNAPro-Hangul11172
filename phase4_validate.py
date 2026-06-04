# -*- coding: utf-8 -*-
"""Phase 4a: 자동 전수 검증.

1) 11,172자 전부 FreeType 렌더링 → 빈 글자 0개 확인
2) 기존 2,518자가 원본과 픽셀 단위로 동일한지 확인 (불변 보장)
3) 잉크 비율 이상치 탐지 (조립 실패 의심 글자)
4) 스팟 샘플 이미지 생성 (쫒·찟 + 케이스별 샘플)
"""
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ORIG = "./source_font.ttf"
NEW = "output/BMHANNAPro_Hangul11172.ttf"
SIZE = 48

f_orig = ImageFont.truetype(ORIG, SIZE)
f_new = ImageFont.truetype(NEW, SIZE)

import hannalib as H
trusted, food, blank0 = H.classify_syllables(H.load_font())
real = set(trusted)

def mask_array(font, ch):
    m = font.getmask(ch, mode="1")
    if m.size[0] == 0 or m.size[1] == 0:
        return None
    return np.frombuffer(bytes(m), dtype=np.uint8).reshape(m.size[1], m.size[0])

blank = []
changed_real = []
ink_ratios = {}
for cp in range(0xAC00, 0xD7A4):
    ch = chr(cp)
    a = mask_array(f_new, ch)
    if a is None or a.max() == 0:
        blank.append(cp)
        continue
    ink_ratios[cp] = float((a > 0).mean())
    if cp in real:
        b = mask_array(f_orig, ch)
        if b is None or a.shape != b.shape or not np.array_equal(a, b):
            changed_real.append(cp)

print(f"빈 글자: {len(blank)}개", [f"{chr(c)}" for c in blank[:20]])
print(f"기존 글자 변경됨(0이어야 함): {len(changed_real)}개",
      [chr(c) for c in changed_real[:20]])

real_ratios = np.array([ink_ratios[c] for c in ink_ratios if c in real])
comp_cps = [c for c in ink_ratios if c not in real]
comp_ratios = np.array([ink_ratios[c] for c in comp_cps])
lo, hi = np.percentile(real_ratios, [0.1, 99.9])
margin = 0.35
outliers = [c for c in comp_cps
            if ink_ratios[c] < lo * (1 - margin) or ink_ratios[c] > hi * (1 + margin)]
print(f"잉크비율 정상범위(원본 기준): {lo:.3f}~{hi:.3f}")
print(f"조립 글자 이상치: {len(outliers)}개", [chr(c) for c in outliers[:30]])

json.dump({"blank": blank, "changed_real": changed_real,
           "outliers": [f"U+{c:04X} {chr(c)}" for c in outliers]},
          open("validate_report.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# ---- 스팟 샘플 이미지 ----
import random
random.seed(42)
demo_rows = [
    ("요청 글자 + 문장", "쫒 찟 · 쫒기다 찟어버리다"),
    ("원본 글자(비교용)", "쫓 찢 · 한나체는 원래 이런 모양"),
]
missing_sorted = [c for c in range(0xAC00, 0xD7A4) if c not in real]
random.shuffle(missing_sorted)
demo_rows.append(("무작위 조립 글자 1", " ".join(chr(c) for c in missing_sorted[:16])))
demo_rows.append(("무작위 조립 글자 2", " ".join(chr(c) for c in missing_sorted[16:32])))
demo_rows.append(("무작위 조립 글자 3", " ".join(chr(c) for c in missing_sorted[32:48])))

W, ROW_H, PAD = 1200, 90, 16
img = Image.new("L", (W, ROW_H * len(demo_rows) + PAD * 2), 255)
d = ImageDraw.Draw(img)
big = ImageFont.truetype(NEW, 56)
try:
    label_f = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 15)
except OSError:
    label_f = ImageFont.load_default()
for i, (label, text) in enumerate(demo_rows):
    y = PAD + i * ROW_H
    d.text((PAD, y), label, font=label_f, fill=120)
    d.text((PAD, y + 20), text, font=big, fill=0)
img.save("spot_check.png")
print("spot_check.png 저장")
