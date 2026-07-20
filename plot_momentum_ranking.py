# -*- coding: utf-8 -*-
"""
plot_momentum_ranking.py
=========================
rrg_monitor.py が出力した最新の momentum_ranking_YYYYMMDD.csv を読み込み、
直近12ヶ月(既定)のセクター別トレイリングモメンタムを横棒グラフで描画する。

RRGチャート(plot_rrg.py)との違い:
    RRGはEMA平滑化・63日ウィンドウでのz-score化を行った「変化率」を見る、
    やや手の込んだ指標。Phase Bの簡易バックテスト(backtest_rrg.py)では、
    その平滑化・正規化が「早期に反応する」という狙いに反して、むしろ反応を
    遅らせている可能性が示唆された(CLAUDE.md参照)。
    このチャートは対照的に、平滑化を一切せず直近12ヶ月の素のリターンで
    セクターを単純に順位付けするだけ — Moskowitz & Grinblatt (1999,
    Journal of Finance) 以来、業種モメンタムとして再現性が確認されている
    素朴な手法に基づく。効果は月次程度の緩やかなリバランス前提で確認された
    ものなので、このランキングも数日単位の細かい変動ではなく、月単位の
    傾向として眺めることを想定している。

実行方法(先に rrg_monitor.py を実行しておくこと):
    python plot_momentum_ranking.py

出力:
    ./output/momentum_ranking_chart_YYYYMMDD.png
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

from rrg_monitor import CONFIG, GROUP_COLORS, GROUP_LABELS

OUTPUT_DIR = CONFIG["output_dir"]

# --- 日本語フォントの自動選択 (文字化け対策) ---
_JP_FONT_CANDIDATES = ["Yu Gothic", "Meiryo", "MS Gothic", "Noto Sans CJK JP"]
_available = {f.name for f in fm.fontManager.ttflist}
for _name in _JP_FONT_CANDIDATES:
    if _name in _available:
        plt.rcParams["font.family"] = _name
        break
plt.rcParams["axes.unicode_minus"] = False


def find_latest_csv(pattern: str) -> str:
    candidates = sorted(glob.glob(pattern))
    if not candidates:
        raise FileNotFoundError(
            f"[エラー発生源: find_latest_csv] {pattern} に一致するCSVが見つかりません。"
            " 先に rrg_monitor.py を実行してください。"
        )
    return candidates[-1]


def load_momentum_ranking() -> pd.DataFrame:
    path = find_latest_csv(os.path.join(OUTPUT_DIR, "momentum_ranking_[0-9]*.csv"))
    df = pd.read_csv(path, encoding="utf-8-sig", parse_dates=["Date"])
    return df


def draw_momentum_bars(ax, df: pd.DataFrame, lookback_days: int, benchmark: str):
    """RelativeReturn(対ベンチマーク超過リターン)の横棒グラフを描く。上が最強。"""
    # 横棒は上から強い順に見せたいので、描画時は逆順(下から積む)にする。
    plot_df = df.sort_values("RelativeReturn", ascending=True).reset_index(drop=True)
    colors = [GROUP_COLORS.get(g, "#888888") for g in plot_df["Group"]]
    y_pos = range(len(plot_df))

    ax.barh(y_pos, plot_df["RelativeReturn"] * 100, color=colors, height=0.62, zorder=2)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels([f"{r.Symbol} ({r.Label})" for r in plot_df.itertuples()], fontsize=10)

    for y, val in zip(y_pos, plot_df["RelativeReturn"] * 100):
        ha = "left" if val >= 0 else "right"
        pad = 0.4 if val >= 0 else -0.4
        ax.text(val + pad, y, f"{val:+.1f}%", va="center", ha=ha, fontsize=9, color="#333333", zorder=3)

    ax.axvline(0, color="#888888", lw=1.0, zorder=1)
    ax.set_xlabel(f"直近{lookback_days}営業日(約12ヶ月)のトレイリングリターン — 対{benchmark}超過分 (%)")
    ax.grid(True, axis="x", color="#EEEEEE", lw=0.6, zorder=0)
    ax.spines[["top", "right", "left"]].set_visible(False)

    xmax = max(abs(plot_df["RelativeReturn"].min()), abs(plot_df["RelativeReturn"].max())) * 100
    pad = max(xmax * 0.25, 2.0)
    ax.set_xlim(-(xmax + pad), xmax + pad)


def draw_group_legend(ax):
    handles = [
        plt.Line2D([0], [0], marker="s", color="w", markerfacecolor=color, markersize=11, label=GROUP_LABELS[g])
        for g, color in GROUP_COLORS.items()
    ]
    leg = ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.02, 1.0),
                    frameon=True, fontsize=8.5, title="色 (参考:\nマクロ・グループ)")
    leg.get_frame().set_facecolor("white")
    leg.get_frame().set_edgecolor("#DDDDDD")
    leg.get_frame().set_alpha(0.9)


def draw_usage_note(ax, start_y: float = 0.60):
    """
    凡例の下に、検証された具体的な活用手順(月次リバランス)を追記する。
    Quantpedia「Sector Momentum - Rotational System」等で確認されている、
    「上位数銘柄を均等保有し、月1回だけ入れ替える」という運用に近い使い方を
    案内する — 日々・週次で細かく反応することを推奨しない旨とセットで示す。
    """
    steps = [
        "① 月1回程度、このランキングを確認",
        "② 上位3〜4銘柄を目安に保有を検討",
        "③ 保有中は基本的に見直さない",
        "④ 次回確認まで約1ヶ月空ける",
    ]
    ax.text(1.02, start_y, "■ 活用方法(検証された運用に近い使い方)", transform=ax.transAxes,
            fontsize=8.3, weight="bold", color="#444444", ha="left", va="top")

    body = "\n".join(steps) + "\n(日々・週次の細かい変動への追随は非推奨)"
    ax.text(1.02, start_y - 0.05, body, transform=ax.transAxes, fontsize=8.0,
            color="#333333", ha="left", va="top", linespacing=1.6,
            bbox=dict(boxstyle="round,pad=0.45", facecolor="#F7F7F7", edgecolor="#DDDDDD"))


def main():
    try:
        df = load_momentum_ranking()
        last_date = df["Date"].max()
        last_date_str = last_date.strftime("%Y-%m-%d") if hasattr(last_date, "strftime") else str(last_date)
        lookback_days = CONFIG["momentum_ranking_lookback_days"]
        benchmark = CONFIG["benchmark"]

        fig, ax = plt.subplots(figsize=(9.5, 6.0))
        fig.suptitle("セクター・モメンタムランキング (12ヶ月)", fontsize=15,
                     x=0.02, ha="left", weight="bold")
        ax.set_title(
            f"データ基準日: {last_date_str}。上ほど直近12ヶ月の相対的な強さが大きい。",
            fontsize=11, loc="left", pad=10,
        )

        draw_momentum_bars(ax, df, lookback_days, benchmark)
        draw_group_legend(ax)
        draw_usage_note(ax)

        fig.text(
            0.02, -0.04,
            "※ Moskowitz & Grinblatt (1999, Journal of Finance) 以来、業種モメンタムとして"
            "再現性が確認されている考え方に基づく素朴なランキングです(EMA平滑化やz-score化は行っていません)。\n"
            "効果は月次程度の緩やかなリバランス前提で確認されたものであり、日々の細かい変動を追う指標ではありません。"
            "個別のトレード判断を保証するものではありません。",
            fontsize=8, color="#777777",
        )

        stamp = os.path.basename(find_latest_csv(
            os.path.join(OUTPUT_DIR, "momentum_ranking_[0-9]*.csv")
        )).replace("momentum_ranking_", "").replace(".csv", "")
        save_path = os.path.join(OUTPUT_DIR, f"momentum_ranking_chart_{stamp}.png")
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
        plt.close(fig)

        print(f"[完了] モメンタムランキング図を保存しました: {save_path}")

    except Exception as e:
        print(f"[エラー] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
