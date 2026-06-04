# -*- coding: utf-8 -*-
"""Phase 4b: 시각 QA용 시트 렌더링.

각 시트: 상단 보정행(원본 한나체 글자 20자) + 조립 글자 16행×20열.
각 셀: 조립 글자(한나체 56px) + 아래 회색 참조(시스템 고딕 14px, 자모 검증용).
매핑: sheets/sheet_NN.png 의 (행 r, 열 c) → cps[NN*320 + r*20 + c]
"""
import os
import json
import random
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont

ORIG = "./source_font.ttf"
NEW = "output/BMHANNAPro_Hangul11172.ttf"
COLS, ROWS = 20, 16
CW, CH = 74, 84
PER_SHEET = COLS * ROWS

import hannalib as Hb
real, _food, _blank = Hb.classify_syllables(Hb.load_font())
real_set = set(real)
composed = [cp for cp in range(0xAC00, 0xD7A4) if cp not in real_set]

hanna = ImageFont.truetype(NEW, 54)
ref = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 14)
label_f = ImageFont.truetype("/System/Library/Fonts/AppleSDGothicNeo.ttc", 13)

random.seed(7)
calib = random.sample(real, COLS)

os.makedirs("sheets", exist_ok=True)
MARGIN_L, MARGIN_T = 34, 30
CALIB_H = CH + 24

n_sheets = (len(composed) + PER_SHEET - 1) // PER_SHEET
index = {}
for s in range(n_sheets):
    chunk = composed[s * PER_SHEET:(s + 1) * PER_SHEET]
    W = MARGIN_L + COLS * CW + 10
    Hh = MARGIN_T + CALIB_H + ROWS * CH + 10
    img = Image.new("L", (W, Hh), 255)
    d = ImageDraw.Draw(img)
    d.text((MARGIN_L, 6), "기준(원본 글자) — 이 줄은 정상 스타일 참고용", font=label_f, fill=150)
    for c, cp in enumerate(calib):
        x = MARGIN_L + c * CW
        d.text((x, MARGIN_T), chr(cp), font=hanna, fill=0)
    d.line([(0, MARGIN_T + CALIB_H - 8), (W, MARGIN_T + CALIB_H - 8)], fill=180)
    for i, cp in enumerate(chunk):
        r, c = divmod(i, COLS)
        x = MARGIN_L + c * CW
        y = MARGIN_T + CALIB_H + r * CH
        d.text((x, y), chr(cp), font=hanna, fill=0)
        d.text((x + 2, y + 58), chr(cp), font=ref, fill=170)
        index[f"{s}:{r}:{c}"] = cp
    for r in range(ROWS):
        d.text((4, MARGIN_T + CALIB_H + r * CH + 20), str(r), font=label_f, fill=120)
    for c in range(COLS):
        d.text((MARGIN_L + c * CW + 24, MARGIN_T + CALIB_H - 24), str(c), font=label_f, fill=120)
    img.save(f"sheets/sheet_{s:02d}.png")

json.dump({k: f"U+{v:04X} {chr(v)}" for k, v in index.items()},
          open("sheets/index.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"{n_sheets}개 시트 생성 (조립 글자 {len(composed)}자, 시트당 {PER_SHEET}자)")
