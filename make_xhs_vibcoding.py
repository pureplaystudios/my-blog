# -*- coding: utf-8 -*-
"""《Vibcoding：AI 编程无人化》这套图的渲染入口。

内容在 .agents/skills/xhs-text-cards/examples/vibcoding.json，
版式规则在 .agents/skills/xhs-text-cards/SKILL.md。
改文字只改 JSON，别改这个文件。
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SCRIPT = ROOT / ".agents/skills/xhs-text-cards/scripts/render_cards.py"
CONTENT = ROOT / ".agents/skills/xhs-text-cards/examples/vibcoding.json"
OUT = ROOT / "小红书-Vibcoding"

if __name__ == "__main__":
    subprocess.run([sys.executable, str(SCRIPT), "--input", str(CONTENT), "--out", str(OUT)],
                   check=True)
