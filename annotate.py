"""为向导截图添加：精确像素化打码 + 红色箭头/序号标注点击流程。"""
import json
from PIL import Image, ImageDraw, ImageFont

IMG = "docs/img/"
RED = (250, 35, 59)
WHITE = (255, 255, 255)


def font(size):
    for name in ("msyh.ttc", "msyh.ttf", "simhei.ttf", "simsun.ttc"):
        try:
            return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def pixelate(im, box, blocks=16):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    region = im.crop((x0, y0, x1, y1))
    small = region.resize((max(1, (x1 - x0) // blocks), max(1, (y1 - y0) // blocks)))
    im.paste(small.resize((x1 - x0, y1 - y0), Image.NEAREST), (x0, y0))


def arrow(draw, start, end, color=RED, w=7, head=22):
    draw.line([start, end], fill=color, width=w)
    import math
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    for s in (1, -1):
        pt = (end[0] - head * math.cos(ang - s * 0.42),
              end[1] - head * math.sin(ang - s * 0.42))
        draw.line([end, pt], fill=color, width=w)
    draw.ellipse([end[0] - 5, end[1] - 5, end[0] + 5, end[1] + 5], fill=color)


def chip(draw, xy, text, f):
    x, y = xy
    tb = draw.textbbox((x, y), text, font=f)
    pad = 9
    draw.rounded_rectangle([tb[0] - pad, tb[1] - pad // 1, tb[2] + pad, tb[3] + pad // 1],
                           radius=13, fill=RED)
    draw.text((x, y), text, font=f, fill=WHITE)


# ---------- 图 1：日历页面（点击按钮位置标注） ----------
im = Image.open(IMG + "page-raw2.png").convert("RGB")
labels = json.load(open(IMG + "page-labels.json", encoding="utf-8"))
rects = json.load(open(IMG + "page-rects.json", encoding="utf-8"))
GENERIC = {"机构", "个人"}
for lb in labels:  # 打码课程名（跳过通用项与复选框区域）
    if lb["text"] in GENERIC:
        continue
    r = lb["rect"]
    pixelate(im, (r["x"] + 24, r["y"] - 2, r["x"] + r["w"] + 2, r["y"] + r["h"] + 2))
for c in rects.get("courseRects", []):  # 其余散落的课程短名（如 Hex）
    if c["text"] in ("Hex",) or any(k in c["text"] for k in ("班", "（202")):
        r = c["rect"]
        pixelate(im, (r["x"] - 2, r["y"] - 2, r["x"] + r["w"] + 2, r["y"] + r["h"] + 2))

d = ImageDraw.Draw(im)
b = rects["button"] if "x" in rects["button"] else rects["button"]["rect"]
bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]
d.rounded_rectangle([bx - 7, by - 7, bx + bw + 7, by + bh + 7], radius=12,
                    outline=RED, width=5)
f28 = font(28)
chip(d, (415, 700), "① 点击「获取外部日程表链接」", f28)
arrow(d, (560, 738), (bx + bw - 28, by - 12))
im.save(IMG + "bb-calendar-page.png")

# ---------- 图 2：弹窗（URL 打码 + 复制指引） ----------
im2 = Image.open(IMG + "dlg-raw2.png").convert("RGB")
dlg = json.load(open(IMG + "dlg-rects.json", encoding="utf-8"))
dd = dlg["dialog"]
clip_x, clip_y = dd["x"] - 25, dd["y"] - 25
# URL 带：弹窗内 y 相对 103~157（上一会话 DOM 实测），转图内坐标
url_box = (252.5 - clip_x, 459.7 - clip_y, 252.5 + 680 - clip_x, 459.7 + 54 - clip_y)
pixelate(im2, url_box)
d2 = ImageDraw.Draw(im2)
d2.rounded_rectangle([url_box[0] - 6, url_box[1] - 4, url_box[2] + 6, url_box[3] + 4],
                     radius=8, outline=RED, width=4)
chip(d2, (30, 22), "② 复制这条 URL（图中已打码）", f28)
arrow(d2, (260, 64), (url_box[0] + 60, url_box[1] - 8))
im2.save(IMG + "bb-calendar-link.png")
print("annotated OK")
