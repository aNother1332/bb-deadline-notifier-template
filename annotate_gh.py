"""GitHub 令牌创建全流程截图标注：精确打码个人内容 + 红色箭头编号指引。"""
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


def chip(draw, xy, text, f, max_w=None):
    x, y = xy
    tb = draw.textbbox((x, y), text, font=f)
    draw.rounded_rectangle([tb[0] - 10, tb[1] - 6, tb[2] + 10, tb[3] + 6], radius=14, fill=RED)
    draw.text((x, y), text, font=f, fill=WHITE)


def box(draw, rect, pad=6, w=5):
    x, y, rw, rh = rect
    draw.rounded_rectangle([x - pad, y - pad, x + rw + pad, y + rh + pad], radius=10, outline=RED, width=w)


f26 = font(26)

# ---- A 头像抽屉：点 Settings ----
im = Image.open(IMG + "gh-avatar-raw.png").convert("RGB")
dA = json.load(open(IMG + "gh-avatar.json", encoding="utf-8"))
for m in dA["mask"]:
    pixelate(im, (m["x"] - 3, m["y"] - 3, m["x"] + m["w"] + 3, m["y"] + m["h"] + 3))
d = ImageDraw.Draw(im)
box(d, (1001, 396, 240, 32))
chip(d, (700, 300), "① 点击右上角头像 → Settings", f26)
arrow(d, (940, 330), (1040, 390))
im.save(IMG + "gh-step1-avatar.png")

# ---- B 设置页侧栏：点 Developer settings（裁剪至侧栏） ----
im = Image.open(IMG + "gh-settings-raw.png").convert("RGB").crop((0, 0, 310, 720))
d = ImageDraw.Draw(im)
box(d, (16, 559, 272, 33))
chip(d, (30, 460), "② 点击最底部 Developer settings", f26)
arrow(d, (150, 505), (150, 552))
im.save(IMG + "gh-step2-settings.png")

# ---- C Developer settings：点 Fine-grained tokens（裁剪至侧栏） ----
im = Image.open(IMG + "gh-devsettings-raw.png").convert("RGB").crop((0, 0, 310, 720))
d = ImageDraw.Draw(im)
box(d, (16, 171, 272, 32))
chip(d, (30, 60), "③ 点击 Fine-grained tokens", f26)
arrow(d, (150, 110), (150, 166))
im.save(IMG + "gh-step3-devsettings.png")

# ---- D 令牌列表：点 Generate new token（列表整区打码） ----
im = Image.open(IMG + "gh-patlist-raw.png").convert("RGB")
pixelate(im, (1213, 12, 1253, 52))          # 顶栏头像
pixelate(im, (300, 372, 1275, 715))         # 已有令牌列表（名称/日期/仓库全打码）
d = ImageDraw.Draw(im)
box(d, (644, 329, 153, 32))
chip(d, (700, 250), "④ 点击 Generate new token（下方列表已打码）", f26)
arrow(d, (760, 292), (720, 324))
im.save(IMG + "gh-step4-patlist.png")

# ---- E 创建页上半：有效期 + 仓库访问（坐标减去裁剪原点 300,470） ----
im = Image.open(IMG + "gh-new-top-raw.png").convert("RGB")
OX, OY = 300, 470
d = ImageDraw.Draw(im)
box(d, (336 - OX, 543 - OY, 150, 45))       # 有效期标签+下拉区
chip(d, (560, 30), "① 有效期选 No expiration（永久）", f26)
arrow(d, (560, 68), (500, 76))
box(d, (360 - OX, 776 - OY, 300, 24))       # All repositories 单选行
chip(d, (560, 190), "② Repository access 选 All repositories", f26)
arrow(d, (555, 228), (500, 310))
im.save(IMG + "gh-step5-expiry-repo.png")

# ---- F 创建页权限区 ----
im = Image.open(IMG + "gh-new-perm-raw.png").convert("RGB")
d = ImageDraw.Draw(im)
chip(d, (40, 60), "③ Permissions → Repository permissions，逐项添加并设为 Read and write：", f26)
chip(d, (40, 105), "　Administration / Secrets / Actions / Contents / Workflows", f26)
arrow(d, (120, 150), (140, 95))
im.save(IMG + "gh-step6-permissions.png")

print("6 张标注完成")
