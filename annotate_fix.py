"""修复版：step1 整体打码仅留 Settings 行；step2/3 加宽画布、箭头直指链接中心。"""
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


def pixelate(im, box, blocks=14):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(im.size[0], x1), min(im.size[1], y1)
    if x1 <= x0 or y1 <= y0:
        return
    region = im.crop((x0, y0, x1, y1))
    small = region.resize((max(1, (x1 - x0) // blocks), max(1, (y1 - y0) // blocks)))
    im.paste(small.resize((x1 - x0, y1 - y0), Image.NEAREST), (x0, y0))


def arrow(draw, start, end, color=RED, w=7, head=20):
    draw.line([start, end], fill=color, width=w)
    import math
    ang = math.atan2(end[1] - start[1], end[0] - start[0])
    for s in (1, -1):
        pt = (end[0] - head * math.cos(ang - s * 0.42), end[1] - head * math.sin(ang - s * 0.42))
        draw.line([end, pt], fill=color, width=w)
    draw.ellipse([end[0] - 5, end[1] - 5, end[0] + 5, end[1] + 5], fill=color)


def chip(draw, xy, text, f):
    x, y = xy
    tb = draw.textbbox((x, y), text, font=f)
    draw.rounded_rectangle([tb[0] - 10, tb[1] - 6, tb[2] + 10, tb[3] + 6], radius=14, fill=RED)
    draw.text((x, y), text, font=f, fill=WHITE)


f22 = font(22)

# ---- Step1：裁剪至抽屉区域，整体打码，仅恢复 Settings 行 ----
raw = Image.open(IMG + "gh-avatar-raw.png").convert("RGB")
dA = json.load(open(IMG + "gh-avatar.json", encoding="utf-8"))
CX = 930                                   # 裁剪起点 x
im = raw.crop((CX, 0, 1280, 720))
s = dA["settings"]                          # 页面坐标
strip = raw.crop((s["x"] - 10, s["y"] - 8, s["x"] + s["w"] + 10, s["y"] + s["h"] + 8))
pixelate(im, (0, 0, im.size[0], im.size[1]))                      # 全部打码
im.paste(strip, (s["x"] - 10 - CX, s["y"] - 8))                   # 恢复 Settings 行
d = ImageDraw.Draw(im)
d.rounded_rectangle([s["x"] - 10 - CX, s["y"] - 8, s["x"] + s["w"] + 10 - CX, s["y"] + s["h"] + 8],
                    radius=10, outline=RED, width=5)
chip(d, (30, 24), "① 头像 → Settings", f22)
arrow(d, (110, 70), (s["x"] + 40 - CX, s["y"] - 14))
im.save(IMG + "gh-step1-avatar.png")

# ---- Step2：设置页侧栏（画布 470 宽，文字完整） ----
dB = json.load(open(IMG + "gh-settings.json", encoding="utf-8"))["dev"]
im2 = Image.open(IMG + "gh-settings-raw.png").convert("RGB").crop((0, 0, 470, 720))
d2 = ImageDraw.Draw(im2)
d2.rounded_rectangle([dB["x"] - 7, dB["y"] - 7, dB["x"] + dB["w"] + 7, dB["y"] + dB["h"] + 7],
                     radius=10, outline=RED, width=5)
chip(d2, (18, dB["y"] - 90), "② Developer settings（侧栏最底部）", f22)
arrow(d2, (140, dB["y"] - 36), (140, dB["y"] - 10))
im2.save(IMG + "gh-step2-settings.png")

# ---- Step3：Fine-grained tokens（画布 470 宽） ----
dC = json.load(open(IMG + "gh-devsettings.json", encoding="utf-8"))["fine"]["rect"]
im3 = Image.open(IMG + "gh-devsettings-raw.png").convert("RGB").crop((0, 0, 470, 720))
d3 = ImageDraw.Draw(im3)
d3.rounded_rectangle([dC["x"] - 7, dC["y"] - 7, dC["x"] + dC["w"] + 7, dC["y"] + dC["h"] + 7],
                     radius=10, outline=RED, width=5)
chip(d3, (18, dC["y"] - 90), "③ Fine-grained tokens", f22)
arrow(d3, (140, dC["y"] - 36), (140, dC["y"] - 10))
im3.save(IMG + "gh-step3-devsettings.png")

print("step1/2/3 修复完成")
