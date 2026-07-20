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
import unicodedata

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from adjustText import adjust_text

from rrg_monitor import CONFIG, compute_latest_summary, generate_situation_summary

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

    # 実際にプロットする範囲(直近tail_days日分)のみを先に切り出す。
    # 軸範囲もこの部分集合から決める — 半年以上前の極値まで含めた全履歴基準で
    # 余白を取ると、実際に描画される直近の軌跡に対して枠が大きくなりすぎ、
    # 上下左右が間延びして見える。
    tails = {
        symbol: sec_df.sort_values("Date").tail(tail_days)
        for symbol, sec_df in valid.groupby("Symbol")
    }
    plotted = pd.concat(tails.values())

    # 軸範囲: X(RS-Ratio)とY(RS-Momentum)は値の散らばり幅が異なるため、
    # 正方形に揃えず個別に余白を決める(片方だけ幅が狭いのに強制的に正方形に
    # すると、狭い方の軸に大きな空白ができてしまう)。
    x_dev = max((plotted["RS_Ratio"] - 100).abs().max() * 1.18, 1.2)
    y_dev = max((plotted["RS_Momentum"] - 100).abs().max() * 1.18, 1.2)
    xlim = (100 - x_dev, 100 + x_dev)
    ylim = (100 - y_dev, 100 + y_dev)

    draw_quadrant_background(ax, xlim, ylim)

    texts = []
    point_xs, point_ys = [], []
    for symbol, sec_df in tails.items():
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
        txt = ax.text(head["RS_Ratio"], head["RS_Momentum"], symbol,
                       fontsize=10, weight="bold", color=color, zorder=4)
        texts.append(txt)
        point_xs.append(head["RS_Ratio"])
        point_ys.append(head["RS_Momentum"])

    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.set_xlabel("RS-Ratio (ベンチマーク比の強さの水準、100が基準)")
    ax.set_ylabel("RS-Momentum (強さの変化率、100が基準)")
    ax.grid(True, color="#EEEEEE", lw=0.6, zorder=0)
    ax.spines[["top", "right"]].set_visible(False)

    # Improving象限など、複数セクターが接近すると先端ラベルが重なって読めなく
    # なるため、adjustTextでラベル同士・ラベルと点の重なりを自動回避する。
    # ラベルが動いた場合は、元の点との対応が分かるよう細い線でつなぐ。
    if texts:
        adjust_text(
            texts, x=point_xs, y=point_ys, ax=ax,
            expand_points=(1.6, 1.8), expand_text=(1.25, 1.35),
            force_text=(0.5, 0.7), force_points=(0.3, 0.4),
            arrowprops=dict(arrowstyle="-", color="#999999", lw=0.7, alpha=0.8, shrinkA=2, shrinkB=4),
        )


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


def draw_ticker_glossary(ax, start_y: float = 0.58):
    """
    凡例(グループ色)の下に、各ティッカーの略称→正式名称を一覧で追記する。
    「XLKって何?」を見た瞬間に確認できるようにするための一覧で、識別は
    引き続き軌跡先端の直接ラベルが主(このリストは補助)。
    """
    groups_order = ["growth", "value", "defensive", "rate_sensitive"]
    by_group = {g: [] for g in groups_order}
    for sec in CONFIG["sectors"]:
        by_group.setdefault(sec["group"], []).append(sec)

    ax.text(1.02, start_y + 0.05, "銘柄一覧 (ティッカー: 正式名称)", transform=ax.transAxes,
            fontsize=8.3, weight="bold", color="#444444", ha="left", va="top")

    y = start_y
    line_h = 0.033
    gap_h = 0.012
    for g in groups_order:
        secs = by_group.get(g, [])
        if not secs:
            continue
        color = GROUP_COLORS.get(g, "#888888")
        ax.text(1.02, y, GROUP_LABELS[g], transform=ax.transAxes, fontsize=8.0,
                weight="bold", color=color, ha="left", va="top")
        y -= line_h
        for sec in secs:
            ax.text(1.03, y, f"{sec['ticker']}: {sec['label']}", transform=ax.transAxes,
                    fontsize=7.8, color="#333333", ha="left", va="top")
            y -= line_h
        y -= gap_h


def _wrap_cjk(text: str, max_width: int) -> list:
    """
    全角文字を幅2、半角文字を幅1として数え、max_widthを超える手前で改行する。
    日本語は単語間にスペースが無いため textwrap.fill だと1行が改行されずに
    見た目の幅を超えて突き抜ける(全角文字はフォント上、半角の約2倍幅がある
    ため文字数だけでは折り返し判定できない) — その対策として自前で実装する。
    """
    lines, cur, cur_w = [], "", 0
    for ch in text:
        w = 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
        if cur and cur_w + w > max_width:
            lines.append(cur)
            cur, cur_w = "", 0
        cur += ch
        cur_w += w
    lines.append(cur)
    return lines


def wrap_situation_text(situation_text: str, max_width: int = 148) -> list:
    """状況説明テキストを行ごとに折り返し、表示用の行リストを返す。"""
    out = []
    for line in situation_text.split("\n"):
        out.extend(_wrap_cjk(line, max_width))
    return out


def draw_situation_banner(ax, wrapped_lines: list, last_date: str):
    """データから読み取れる現状を、平易な日本語の短文としてチャート上部に表示する。"""
    ax.axis("off")
    ax.text(0.0, 1.0, f"■ 現状の要約 (データ基準日: {last_date})", transform=ax.transAxes,
            fontsize=11.5, weight="bold", va="top", ha="left")

    ax.text(0.0, 0.80, "\n".join(wrapped_lines), transform=ax.transAxes, fontsize=9.2,
            va="top", ha="left", linespacing=1.6, color="#222222",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#F7F7F7", edgecolor="#DDDDDD"))


def main():
    try:
        df = load_rrg_data()
        summary, last_date_ts = compute_latest_summary(df)
        last_date = last_date_ts.strftime("%Y-%m-%d")
        situation_text = generate_situation_summary(summary)
        wrapped_lines = wrap_situation_text(situation_text)

        # バナー(現状の要約)の高さは、行数に応じて動的に決める。
        # 固定比率だとテキスト量が多い日(例: 1つの象限に大半のセクターが
        # 集中した日)に文字がボックスからはみ出し、下のグラフタイトルと
        # 重なってしまうため。
        main_height_in = 7.6
        header_in = 0.45
        line_height_in = 9.2 * 1.6 / 72
        banner_pad_in = 0.55
        banner_height_in = header_in + len(wrapped_lines) * line_height_in + banner_pad_in
        fig_height_in = banner_height_in + main_height_in

        fig, (ax_banner, ax) = plt.subplots(
            2, 1, figsize=(10, fig_height_in),
            gridspec_kw={"height_ratios": [banner_height_in, main_height_in]},
        )
        fig.suptitle("セクター・ローテーション早期兆候検知 (RRG)", fontsize=15,
                     x=0.0, ha="left", weight="bold")
        draw_situation_banner(ax_banner, wrapped_lines, last_date)
        draw_rrg_scatter(ax, df, CONFIG["tail_days"])
        draw_group_legend(ax)
        draw_ticker_glossary(ax)

        ax.set_title(
            f"直近{CONFIG['tail_days']}営業日の軌跡。左上(Improving)ほど早期ローテーション候補。",
            fontsize=12, loc="left", pad=12,
        )
        fig.text(
            0.0, -0.015,
            "X軸 RS-Ratio: RSP比の63日移動平均に対する「今の強さ」(100が基準、右ほど強い) / "
            "Y軸 RS-Momentum: その強さが5営業日前から「加速しているか」(100が基準、上ほど加速中)",
            fontsize=8.3, color="#555555",
        )
        fig.text(
            0.0, -0.035,
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
