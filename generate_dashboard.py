# -*- coding: utf-8 -*-
"""
generate_dashboard.py
======================
plot_rrg.py / plot_momentum_ranking.py が出力した最新のRRGチャートと
モメンタムランキング図を、PILで縦に合成して1枚の「デイリーダッシュボード」
画像にする。

matplotlibで新しい図をゼロから組むのではなく、既に個別に検証済みの2枚の
PNGをそのまま画像として貼り合わせるだけにしている — 各チャート自身の
レイアウト(バナー・凡例・折り返し等)をここで壊さずに再利用するため。
2枚は横幅が異なる(RRGチャートとモメンタムランキング図で図の内容が違う
ため)ので、共通の横幅にリサイズしてから縦に並べる。

実行方法(先に plot_rrg.py と plot_momentum_ranking.py を実行しておくこと):
    python generate_dashboard.py

出力:
    ./output/dashboard_YYYYMMDD.png
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import glob
import os
import sys

from PIL import Image, ImageDraw, ImageFont

from rrg_monitor import CONFIG

OUTPUT_DIR = CONFIG["output_dir"]
TARGET_WIDTH = 1600
GAP_PX = 24
BANNER_HEIGHT_PX = 90
BG_COLOR = (255, 255, 255)


def find_latest(pattern: str) -> str:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"[エラー発生源: find_latest] {pattern} に一致するファイルがありません。"
            " 先に plot_rrg.py / plot_momentum_ranking.py を実行してください。"
        )
    return matches[-1]


def resize_to_width(im: Image.Image, width: int) -> Image.Image:
    if im.width == width:
        return im
    ratio = width / im.width
    height = round(im.height * ratio)
    return im.resize((width, height), Image.LANCZOS)


def load_jp_font(size: int) -> ImageFont.FreeTypeFont:
    """
    matplotlibと同じ候補フォントをPIL側でも探す(文字化け対策)。
    どれも見つからなければPILのデフォルトビットマップフォント(日本語非対応)
    にフォールバックするが、その場合はバナー文字が表示されないだけで
    エラーにはならない。
    """
    candidates = [
        "YuGothM.ttc", "yugothm.ttc", "meiryo.ttc", "Meiryo.ttc",
        "msgothic.ttc", "MSGOTHIC.TTC",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    try:
        rrg_path = find_latest(os.path.join(OUTPUT_DIR, "rrg_chart_[0-9]*.png"))
        momentum_path = find_latest(os.path.join(OUTPUT_DIR, "momentum_ranking_chart_[0-9]*.png"))

        rrg_im = Image.open(rrg_path).convert("RGB")
        momentum_im = Image.open(momentum_path).convert("RGB")

        rrg_im = resize_to_width(rrg_im, TARGET_WIDTH)
        momentum_im = resize_to_width(momentum_im, TARGET_WIDTH)

        total_height = BANNER_HEIGHT_PX + rrg_im.height + GAP_PX + momentum_im.height
        canvas = Image.new("RGB", (TARGET_WIDTH, total_height), BG_COLOR)

        draw = ImageDraw.Draw(canvas)
        title_font = load_jp_font(28)
        stamp = os.path.basename(rrg_path).replace("rrg_chart_", "").replace(".png", "")
        date_str = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}" if len(stamp) == 8 else stamp
        draw.text((20, 24), f"セクター・ローテーション デイリーダッシュボード ({date_str})",
                  fill=(20, 20, 20), font=title_font)

        canvas.paste(rrg_im, (0, BANNER_HEIGHT_PX))
        canvas.paste(momentum_im, (0, BANNER_HEIGHT_PX + rrg_im.height + GAP_PX))

        save_path = os.path.join(OUTPUT_DIR, f"dashboard_{stamp}.png")
        canvas.save(save_path)

        print(f"[完了] ダッシュボード画像を保存しました: {save_path}")

    except Exception as e:
        print(f"[エラー] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
