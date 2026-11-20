# -*- coding: utf-8 -*-
"""小红书 3:4 文字图渲染器（极简大字报风）。

用法：
    python3 render_cards.py --input cards.json --out ./小红书-XXX
    python3 render_cards.py --input cards.json --lint     # 只看折行，不落盘

输入 JSON 结构（详见 examples/vibcoding.json）：
{
  "series": "页脚系列名",
  "cover": {"kicker": "...", "title": "两行用 \\n 分隔", "sub": "...", "foot": "左滑读完全文"},
  "cards": [
    {"num": "01", "label": "现象", "title": "标题", "blocks": [["p", "正文"], ["sp", 30]]},
    {"num": "03", "label": "核心疑问", "big": true, "big_text": "金句\\n可多行",
     "blocks": [["p_small", "小字补充"], ["accent_note", "红色一句"]]}
  ]
}

正文里用 [[...]] 标记朱红强调；用 \\n 手动断行（推荐，可控版面节奏）。
依赖：Pillow + 系统字体（macOS 自带）。
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

# ---------------- 设计规范（改这里 = 改全局风格） ----------------
W, H = 1080, 1440          # 3:4，小红书竖图
MARGIN = 100               # 左右安全边距
CONTENT_W = W - MARGIN * 2

BG = (250, 249, 246)       # 暖白
INK = (17, 17, 20)         # 墨黑
INK_SOFT = (105, 103, 99)  # 次级文字
ACCENT = (255, 59, 47)     # 朱红，全图唯一强调色
RULE = (222, 219, 212)     # 细线

SANS = "/System/Library/Fonts/Hiragino Sans GB.ttc"
SERIF = "/System/Library/Fonts/Supplemental/Songti.ttc"
SANS_W3, SANS_W6 = 0, 2    # Hiragino 字重索引
SONG_BLACK = 0             # Songti SC Black

# 字号体系
COVER_TITLE, COVER_KICKER, COVER_SUB, COVER_FOOT = 118, 31, 38, 31
CARD_TITLE, CARD_BODY, CARD_SMALL, CARD_BIG, CARD_NOTE = 74, 56, 46, 76, 42
META, LABEL = 31, 28       # 顶栏编号 / 栏目名
FOOTER_SIZE, PAGE_SIZE = 26, 26
PARA_GAP = 30
BODY_TOP, BODY_BOTTOM = 300, 1240

_cache = {}


def F(path, size, index):
    key = (path, size, index)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(path, size, index=index)
    return _cache[key]


# ---------------- 中文折行 ----------------
NO_LINE_START = set("，。、；：？！）》」』】〉…%”’")
NO_LINE_END = set("（《「『【〈“‘")

# 宁可断在词外：这些双字词不拆
KEEP_TOGETHER = set("""
根本 已经 所以 但是 因为 如果 可以 需要 应该 没有 就是 而且 还是 或者 以及
只能 必须 并且 虽然 尽管 其实 只是 这些 那些 这个 那个 什么 怎么 这样 那样
人工 测试 速度 压力 结果 参数 方案 时候 东西 问题 判断 决定 检验 开发 发布
上线 交付 验证 翻车 数字 数据 磨豆 刀盘 转速 咖啡 味道 科技 科幻 魔幻 现实
觉得 认为 出现 使用 直接 最终 实际 消费 用户 产品 团队 项目 代码 质量 时间
""".split())


def tokenize(text):
    toks, buf = [], ""
    for ch in text:
        if ch.isascii() and not ch.isspace():
            buf += ch
        else:
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(ch)
    if buf:
        toks.append(buf)

    # 引号/括号内的短句整体成 token
    merged, i = [], 0
    OPEN = {"「": "」", "『": "』", "“": "”", "（": "）", "(": ")"}
    while i < len(toks):
        t = toks[i]
        if len(t) == 1 and t in OPEN:
            close = OPEN[t]
            j, acc = i, t
            while j + 1 < len(toks):
                j += 1
                acc += toks[j]
                if toks[j] == close:
                    break
            if acc.endswith(close) and len(acc) <= 9:
                merged.append(acc)
                i = j + 1
                continue
        merged.append(t)
        i += 1
    toks = merged

    out, i = [], 0
    while i < len(toks):
        if (i + 1 < len(toks) and len(toks[i]) == 1 and len(toks[i + 1]) == 1
                and toks[i] + toks[i + 1] in KEEP_TOGETHER):
            out.append(toks[i] + toks[i + 1])
            i += 2
        else:
            out.append(toks[i])
            i += 1
    return out


def _line_w(line, font):
    return sum(font.getlength(t) for t, _ in line)


def wrap(segments, font, max_w):
    """贪心折行 + 避头尾 + 孤字回拉；\\n 为强制断行。"""
    lines, cur, cur_w = [], [], 0.0
    for text, style in segments:
        for tok in tokenize(text):
            if tok == "\n":
                if cur:
                    lines.append(cur)
                cur, cur_w = [], 0.0
                continue
            tw = font.getlength(tok)
            if cur_w + tw > max_w and cur:
                if tok in NO_LINE_START:
                    cur.append((tok, style))
                    lines.append(cur)
                    cur, cur_w = [], 0.0
                    continue
                if cur[-1][0] in NO_LINE_END:
                    moved = cur.pop()
                    lines.append(cur)
                    cur, cur_w = [moved], font.getlength(moved[0])
                else:
                    lines.append(cur)
                    cur, cur_w = [], 0.0
            if tok == " " and cur_w == 0:
                continue
            cur.append((tok, style))
            cur_w += tw
    if cur:
        lines.append(cur)

    if len(lines) >= 2:
        for _ in range(3):
            last = lines[-1]
            lw = _line_w(last, font)
            if lw > max_w * 0.30 or len(lines[-2]) <= 2:
                break
            prev = lines[-2]
            cand = prev[-1]
            if lw + font.getlength(cand[0]) > max_w:
                break
            if cand[0] in NO_LINE_START:
                break
            prev.pop()
            lines[-1] = [cand] + last
    return lines


def parse_rich(s):
    """[[...]] -> 朱红强调片段。"""
    out, i = [], 0
    while True:
        a = s.find("[[", i)
        if a < 0:
            out.append((s[i:], "body"))
            break
        out.append((s[i:a], "body"))
        b = s.find("]]", a + 2)
        if b < 0:
            out.append((s[a + 2:], "accent"))
            break
        out.append((s[a + 2:b], "accent"))
        i = b + 2
    return [(t, st) for t, st in out if t]


class Card:
    def __init__(self):
        self.img = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.img)

    def rule(self, y, x0, x1, color=RULE, width=2):
        self.d.rectangle([x0, y, x1, y + width - 1], fill=color)

    def para_lines(self, s, size):
        return wrap(parse_rich(s), F(SANS, size, SANS_W3), CONTENT_W)

    def para_h(self, s, size, lh_ratio):
        return len(self.para_lines(s, size)) * int(size * lh_ratio)

    def para(self, y, s, size=CARD_BODY, color=INK, lh_ratio=1.74):
        f = F(SANS, size, SANS_W3)
        fa = F(SANS, size, SANS_W6)
        lh = int(size * lh_ratio)
        for line in self.para_lines(s, size):
            x = MARGIN
            for text, style in line:
                if style == "accent":
                    self.d.text((x, y), text, font=fa, fill=ACCENT)
                    x += fa.getlength(text)
                else:
                    self.d.text((x, y), text, font=f, fill=color)
                    x += f.getlength(text)
            y += lh
        return y

    def footer(self, series):
        self.d.text((MARGIN, H - 56), series, font=F(SANS, FOOTER_SIZE, SANS_W3),
                    fill=(150, 147, 141), anchor="ls")

    def page_mark(self, idx, total):
        self.d.text((W - MARGIN, H - 56), f"{idx:02d} / {total:02d}",
                    font=F(SANS, PAGE_SIZE, SANS_W3), fill=INK_SOFT, anchor="rs")

    def save(self, path):
        self.img.save(path, "PNG")
        return path


def build_cover(cover, path, total):
    c = Card()
    fk = F(SANS, COVER_KICKER, SANS_W6)
    ft = F(SERIF, COVER_TITLE, SONG_BLACK)
    fs = F(SANS, COVER_SUB, SANS_W3)
    ff = F(SANS, COVER_FOOT, SANS_W6)

    title_lines = cover["title"].split("\n")
    title_lh = int(COVER_TITLE * 1.5)
    sub_lines = cover["sub"].split("\n")
    sub_lh = int(COVER_SUB * 1.78)

    block_h = 42 + 96 + title_lh * len(title_lines) + 52 + 18 + 62 + sub_lh * len(sub_lines)
    top_area, bot_area = 170, H - 230
    y = top_area + max(0, (bot_area - top_area - block_h)) // 2

    x = MARGIN
    for ch in cover["kicker"]:
        c.d.text((x, y), ch, font=fk, fill=ACCENT)
        x += fk.getlength(ch) + 3
    y += 42 + 96

    for ln in title_lines:
        c.d.text((MARGIN - 8, y), ln, font=ft, fill=INK)
        y += title_lh
    last_w = ft.getlength(title_lines[-1])
    c.d.rectangle([MARGIN - 8, y - title_lh + 172, MARGIN - 8 + last_w, y - title_lh + 190], fill=ACCENT)
    y += 40 + 18 + 62

    for ln in sub_lines:
        c.d.text((MARGIN, y), ln, font=fs, fill=INK_SOFT)
        y += sub_lh

    c.rule(H - 190, MARGIN, W - MARGIN)
    c.d.text((MARGIN, H - 148), cover["foot"], font=ff, fill=INK)
    c.d.text((W - MARGIN, H - 148), "→", font=ff, fill=ACCENT, anchor="ra")
    c.page_mark(1, total)
    return c.save(path)


def build_card(spec, idx, total, path, series):
    """顶栏固定在 y=148/218，正文从 y=300 起，保证多张之间对齐。"""
    c = Card()
    fnum = F(SANS, META, SANS_W6)
    flab = F(SANS, LABEL, SANS_W3)
    ftitle = F(SANS, CARD_TITLE, SANS_W6)
    fbig = F(SANS, CARD_BIG, SANS_W6)
    big_lh = int(CARD_BIG * 1.52)
    title_lh = int(CARD_TITLE * 1.42)

    big = spec.get("big")

    y = BODY_TOP

    # 固定顶部索引行
    c.d.text((MARGIN, 148), spec["num"], font=fnum, fill=ACCENT)
    nx = MARGIN + fnum.getlength(spec["num"]) + 26
    c.d.rectangle([nx, 162, nx + 32, 165], fill=RULE)
    c.d.text((nx + 50, 149), spec["label"], font=flab, fill=INK_SOFT)
    c.rule(218, MARGIN, W - MARGIN, RULE, 2)

    if big:
        for ln in spec["big_text"].split("\n"):
            c.d.text((MARGIN, y), ln, font=fbig, fill=INK)
            y += big_lh
        y += 12
        c.rule(y, MARGIN, MARGIN + 112, ACCENT, 7)
        y += 58
    else:
        for ln in spec["title"].split("\n"):
            c.d.text((MARGIN, y), ln, font=ftitle, fill=INK)
            y += title_lh
        y += 44
        c.rule(y, MARGIN, MARGIN + 108, INK, 4)
        y += 70 - 4

    prev_is_text = False
    for kind, s_ in spec["blocks"]:
        if kind == "sp":
            y += s_
            prev_is_text = False
            continue
        if prev_is_text:
            y += PARA_GAP
        prev_is_text = True
        if kind == "p":
            y = c.para(y, s_, size=CARD_BODY, lh_ratio=1.74)
        elif kind == "p_small":
            y = c.para(y, s_, size=CARD_SMALL, color=INK_SOFT, lh_ratio=1.80)
        elif kind == "accent_note":
            c.d.text((MARGIN, y), s_, font=F(SANS, CARD_NOTE, SANS_W6), fill=ACCENT)
            y += 64

    c.footer(series)
    c.page_mark(idx, total)
    if y > 1250:
        print(f"  ! 内容溢出：{os.path.basename(path)} 到 y={y}")
    return c.save(path)


def lint(doc):
    """只打印折行结果，用来在出图前检查断句与溢行。"""
    print(f"标题风格检查 · 版心宽度 {CONTENT_W}px\n")
    for spec in doc["cards"]:
        print(f"--- {spec['num']} {spec.get('label')}")
        if spec.get("big"):
            f = F(SANS, CARD_BIG, SANS_W6)
            for ln in spec["big_text"].split("\n"):
                print(f"     {f.getlength(ln):6.0f}  {ln}")
        for kind, s_ in spec["blocks"]:
            if kind not in ("p", "p_small"):
                continue
            size = CARD_BODY if kind == "p" else CARD_SMALL
            font = F(SANS, size, SANS_W3)
            for line in wrap(parse_rich(s_), font, CONTENT_W):
                txt = "".join(t for t, _ in line)
                w = sum(font.getlength(t) for t, _ in line)
                flag = "!" if w > CONTENT_W else " "
                print(f"  {flag} {w:6.0f}  {txt}")
    print("\n! 表示该行因标点悬挂略超版心（可接受）；超过 40px 就要改文案。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="内容 JSON")
    ap.add_argument("--out", help="输出目录")
    ap.add_argument("--lint", action="store_true", help="只检查折行，不出图")
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as fh:
        doc = json.load(fh)

    if args.lint:
        lint(doc)
        return

    out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.input)), "out")
    os.makedirs(out, exist_ok=True)
    total = len(doc["cards"]) + 1
    files = [build_cover(doc["cover"], os.path.join(out, "01-封面.png"), total)]
    for i, spec in enumerate(doc["cards"], start=2):
        files.append(build_card(spec, i, total,
                                os.path.join(out, f"{i:02d}-{spec['label']}.png"),
                                doc.get("series", "")))
    for f in files:
        print(f)


if __name__ == "__main__":
    main()
