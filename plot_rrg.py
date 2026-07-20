# -*- coding: utf-8 -*-
"""
plot_rrg.py
===========
rrg_monitor.py が出力した最新の rrg_data_YYYYMMDD.csv を読み込み、
Relative Rotation Graph (RRG) の彗星(コメット)チャートを描画する。

読み方 (詳細は rrg_guide.txt を参照予定):
    横軸 RS-Ratio    : ベンチマーク(RSP)に対する相対的な強さの水準 (100が基準)
    縦軸 RS-Momentum : その強さの「変化率」(100が基準)
    右上 Leading    : 強く、さらに強まっている (既に人気化した本命)
    右下 Weakening  : 強いが、勢いが鈍り始めた (利益確定を検討する局面)
    左下 Lagging    : 弱く、さらに弱まっている (様子見)
    左上 Improving  : まだ弱いが、勢いは好転し始めた ★早期ローテーション候補★
各セクターの直近10営業日分の軌跡を尾として描き、新しいほど不透明にする。
色は個別銘柄の識別ではなく、4つのマクロ・グループを示す副次情報。
銘柄そのものの識別は軌跡の先端に付けたティッカーラベルで行う。

実行方法(先に rrg_monitor.py を実行しておくこと):
    python plot_rrg.py

出力:
    ./output/rrg_chart_YYYYMMDD.png
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import glob
import os
import sys

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from rrg_monitor import CONFIG

OUTPUT_DIR = CONFIG["output_dir"]

# --- 日本語フォントの自動選択 (文字化け対策) ---
_JP_FONT_CANDIDATES = ["Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP"]
_available = {f.name for f in fm.fontManager.ttflist}
for _name in _JP_FONT_CANDIDATES:
    if _name in _available:
        plt.rcParams["font.family"] = _name
        break
plt.rcParams["axes.unicode_minus"] = False

# --- 配色: 4つのマクロ・グループ (色覚多様性を考慮し、識別は直接ラベルが主) ---
GROUP_COLORS = {
    "growth": "#2E5EAA",          # 景気敏感/グロース: 青
    "value": "#2E8B4F",           # バリュー/資本財: 緑
    "defensive": "#C9902A",       # ディフェンシブ: 琥珀
    "rate_sensitive": "#7B4FA3",  # 金利敏感/その他: 紫
}
GROUP_LABELS = {
    "growth": "景気敏感/グロース",
    "value": "バリュー/資本財",
    "defensive": "ディフェンシブ",
    "rate_sensitive": "金利敏感/その他",
}
QUADRANT_TINT = "#666666"  # 象限背景は状態色ではなく、位置を示すだけの淡いグレー


def find_latest_csv(pattern: str) -> str:
    candidates = sorted(glob.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            f"[エラー発生源: find_latest_csv] {pattern} に一致するCSVが見つかりません。"
            " 先に rrg_monitor.py を実行してください。"
        )
    return candidates[-1]


def load_rrg_data() -> pd.DataFrame:
    path = find_latest_csv(os.path.join(OUTPUT_DIR, "rrg_data_[0-9]*.csv"))
    df = pd.read_csv(path, encoding="utf-8-sig", parse_dates=["Date"])
    return df


def draw_quadrant_background(ax, xlim, ylim):
    """象限を淡いグレーの濃淡で塗り分け、四隅にラベルを置く(状態色は使わない)。"""
    x0, x1 = xlim
    y0, y1 = ylim
    quadrants = [
        # (x範囲, y範囲, alpha, ラベル, ラベル位置)
        ((100, x1), (100, y1), 0.10, "Leading\n(強・加速)", (x1, y1)),
        ((100, x1), (y0, 100), 0.03, "Weakening\n(強・減速)", (x1, y0)),
        ((x0, 100), (y0, 100), 0.06, "Lagging\n(弱・減速)", (x0, y0)),
        ((x0, 100), (100, y1), 0.14, "Improving ★\n(弱→加速中)", (x0, y1)),
    ]
    for (xr, yr, alpha, label, (lx, ly)) in quadrants:
        ax.axvspan(xr[0], xr[1], ymin=(yr[0] - y0) / (y1 - y0), ymax=(yr[1] - y0) / (y1 - y0),
                   color=QUADRANT_TINT, alpha=alpha, lw=0, zorder=0)
        ha = "right" if lx == x1 else "left"
        va = "top" if ly == y1 else "bottom"
        pad_x = -0.015 * (x1 - x0) if ha == "right" else 0.015 * (x1 - x0)
        pad_y = -0.02 * (y1 - y0) if va == "top" else 0.02 * (y1 - y0)
        ax.text(lx + pad_x, ly + pad_y, label, fontsize=9, color="#777777",
                ha=ha, va=va, linespacing=1.3, zorder=1)

    ax.axhline(100, color="#AAAAAA", lw=1.0, zorder=1)
    ax.axvline(100, color="#AAAAAA", lw=1.0, zorder=1)


def draw_rrg_scatter(ax, df: pd.DataFrame, tail_days: int):
    """全セクター分の彗星(直近tail_days日分の軌跡+先端ラベル)を描く。"""
    valid = df.dropna(subset=["RS_Ratio", "RS_Momentum"])
    if valid.empty:
        raise ValueError(
            "[エラー発生源: draw_rrg_scatter] RS-Ratio/RS-Momentumが計算できたデータがありません。"
        )

    # 軸範囲: 全銘柄・全期間の実データ + 余白から決める (100を中心にできるだけ対称に)
    max_dev = max(
        (valid["RS_Ratio"] - 100).abs().max(),
        (valid["RS_Momentum"] - 100).abs().max(),
    )
    max_dev = max(max_dev * 1.25, 3.0)  # 最低限の余白を確保
    xlim = (100 - max_dev, 100 + max_dev)
    ylim = (100 - max_dev, 100 + max_dev)

    draw_quadrant_background(ax, xlim, ylim)

    for symbol, sec_df in valid.groupby("Symbol"):
        sec_df = sec_df.sort_values("Date").tail(tail_days)
        if sec_df.empty:
            continue
        group = sec_df["Group"].iloc[-1]
        color = GROUP_COLORS.get(group, "#888888")
        n = len(sec_df)

        # 尾: 古いほど薄く
        for i in range(n - 1):
            alpha = 0.15 + 0.55 * (i / max(n - 2, 1))
            ax.plot(
                sec_df["RS_Ratio"].iloc[i:i + 2], sec_df["RS_Momentum"].iloc[i:i + 2],
                color=color, lw=1.6, alpha=alpha, zorder=2, solid_capstyle="round",
            )

        # 先端 (最新日)
        head = sec_df.iloc[-1]
        ax.scatter(head["RS_Ratio"], head["RS_Momentum"], color=color, s=70,
                   zorder=3, edgecolors="white", linewidths=1.2)
        ax.annotate(
            symbol, (head["RS_Ratio"], head["RS_Momentum"]),
            xytext=(6, 6), textcoords="offset points",
            fontsize=10, weight="bold", color=color, zorder=4,
        )

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("RS-Ratio (ベンチマーク比の強さの水準、100が基準)")
    ax.set_ylabel("RS-Momentum (強さの変化率、100が基準)")
    ax.grid(True, color="#EEEEEE", lw=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)


def draw_group_legend(ax):
    # 四隅は象限ラベルが占有しているため、プロット外(右側)に配置する。
    handles = [
        plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=9, label=GROUP_LABELS[g])
        for g, color in GROUP_COLORS.items()
    ]
    leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1.0),
                    frameon=True, fontsize=8.5, title="色 (参考:\nマクロ・グループ)")
    leg.get_frame().set_facecolor("white")
    leg.get_frame().set_edgecolor("#DDDDDD")
    leg.get_frame().set_alpha(0.9)


def main():
    try:
        df = load_rrg_data()
        last_date = df["Date"].max().strftime("%Y-%m-%d")

        fig, ax = plt.subplots(figsize=(10, 9))
        draw_rrg_scatter(ax, df, CONFIG["tail_days"])
        draw_group_legend(ax)

        ax.set_title(
            f"セクター・ローテーション早期兆候検知 (RRG) — データ基準日: {last_date}\n"
            f"直近{CONFIG['tail_days']}営業日の軌跡。左上(Improving)ほど早期ローテーション候補。",
            fontsize=13, loc="left", pad=14,
        )
        fig.text(
            0.0, -0.02,
            "※ JdK RS-Ratio/RS-Momentumの考え方に基づく自己流の近似実装です(公開されていない正確な係数の再現ではありません)。"
            "ベンチマークはRSP(等ウェイトS&P500)。",
            fontsize=8, color="#777777",
        )

        stamp = os.path.basename(find_latest_csv(
            os.path.join(OUTPUT_DIR, "rrg_data_[0-9]*.csv")
        )).replace("rrg_data_", "").replace(".csv", "")
        save_path = os.path.join(OUTPUT_DIR, f"rrg_chart_{stamp}.png")
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        print(f"[完了] RRGチャートを保存しました: {save_path}")

    except Exception as e:
        print(f"[エラー] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
