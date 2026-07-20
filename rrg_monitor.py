# -*- coding: utf-8 -*-
"""
rrg_monitor.py
==============
S&P500の11セクターSPDR ETFについて、Relative Rotation Graph (RRG) の
JdK RS-Ratio / JdK RS-Momentum を計算し、4象限(Leading/Weakening/
Lagging/Improving)への分類と、補助指標である順位加速度(rank
acceleration)を算出して日次CSVに出力する。

【手法の要点】
「強さの水準」ではなく「強さの変化率」を見ることで、水準がまだ弱いうちに
変化率だけが先に反転する Improving 象限入りを検知する。これが「次に資金が
向かう可能性がある早期候補」のシグナル。

  RS_raw(i,t)      = Close(i,t) / Close(benchmark,t)
  RS_smooth(i,t)   = EMA(RS_raw(i), span=EMA_SPAN)
  RS_Ratio(i,t)    = 100 + (RS_smooth - その63日移動平均) / その63日標準偏差
  RS_Momentum(i,t) = 100 + zscore_63d( RS_Ratio(i,t) - RS_Ratio(i,t-5) )

ベンチマークはRSP(等ウェイトS&P500)を採用。SPY(時価総額加重)だと
XLK等の大型セクター自体が指数の大部分を占め、「自分自身に対する相対強度」に
近くなってしまう歪みがあるため。

【RS_Ratioが「2段階」であることの補足(誤解しやすいので明記)】
「セクター単体の63日平均からの乖離」と「RSP単体の63日平均からの乖離」を
別々に計算して両者を比較しているのではない。そうではなく、
  (1) まずセクター÷RSPの割り算を1回行い、「セクターとRSPを合成した
      1本の比率」にしてしまう(=これが「RSPに対して」の意味。市場全体の
      値動きをこの時点で相殺し、セクター側の超過/劣後分だけを残す)
  (2) その合成済み1本の比率(RS_smooth)について、直近63日間の"その比率
      自身の平均・標準偏差"と比べて今日が高いか低いかをz-score化する
      (=セクターとRSP、2つの独立した「自分の平均」を比較しているのでは
      なく、既に1本化された比率の自分史上の位置を見ているだけ)
先に割り算(1)で市場全体の動きを消してから、その残差の変化(2)を見る、
という順序が本質。

これはJdKの公開されていない正確な係数の再現ではなく、同じ考え方に基づく
自己流の近似実装であることに留意。

【Phase Bの簡易バックテストで判明した限界(重要)】
backtest_rrg.py で日足・週足・複数パラメータ・RankAccelによる絞り込みを
試したが、Improving象限入りがその後の相対リターン改善に一貫してつながる
という統計的な優位性は確認できなかった(詳細はCLAUDE.md参照)。Web調査でも
RRGは学術的に「早期予測」が検証された指標ではなく、EMA平滑化により実際には
「既に転換した後に反応する」同時〜遅行指標に近いという指摘が複数見つかった。
このため、本スクリプトのImproving象限の扱いは「参考情報・要目視確認」に
留め、断定的な「早期候補」という表現は避けている。

代わりに、学術的な再現性が確認されている「業種モメンタム」
(Moskowitz & Grinblatt, 1999, Journal of Finance)に基づく
compute_momentum_ranking() を追加した。これは平滑化やz-score化をせず、
直近12ヶ月(既定252営業日)のトレイリングリターンでセクターを単純に
順位付けするだけの、RRGよりずっと素朴な指標。効果は月次程度の緩やかな
リバランス前提で確認されたものなので、日々の細かい変動を追いかけるための
指標ではないことに注意。

必要ライブラリ:
    pip install yfinance pandas numpy matplotlib

実行方法:
    python rrg_monitor.py

出力:
    ./output/rrg_data_YYYYMMDD.csv         (全セクター×全日付の詳細データ)
    ./output/rrg_summary_YYYYMMDD.csv      (直近日のセクター別サマリー)
    ./output/momentum_ranking_YYYYMMDD.csv (直近12ヶ月モメンタムランキング)
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import os
import sys
import time
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("[致命的エラー] yfinance がインストールされていません。")
    print("  対処: pip install yfinance を実行してください。")
    sys.exit(1)

# ============================================================
# 設定セクション
# ============================================================
CONFIG = {
    # S&P500 11セクターSPDR。groupはチャートの配色グループ(4分類)に対応。
    "sectors": [
        {"ticker": "XLK", "label": "情報技術", "group": "growth"},
        {"ticker": "XLY", "label": "一般消費財・サービス", "group": "growth"},
        {"ticker": "XLC", "label": "通信サービス", "group": "growth"},
        {"ticker": "XLF", "label": "金融", "group": "value"},
        {"ticker": "XLI", "label": "資本財・サービス", "group": "value"},
        {"ticker": "XLB", "label": "素材", "group": "value"},
        {"ticker": "XLP", "label": "生活必需品", "group": "defensive"},
        {"ticker": "XLU", "label": "公益事業", "group": "defensive"},
        {"ticker": "XLV", "label": "ヘルスケア", "group": "defensive"},
        {"ticker": "XLE", "label": "エネルギー", "group": "rate_sensitive"},
        {"ticker": "XLRE", "label": "不動産", "group": "rate_sensitive"},
    ],
    # ベンチマーク (等ウェイトS&P500)
    "benchmark": "RSP",
    # 取得期間。momentum_ranking_lookback_days(既定252営業日)を計算するため
    # 最低でも252営業日+αが必要なため、1yでは足りない(1yは実測で約251営業日
    # しか返らず、直近日の252日前リターンが計算できない)。2yなら十分な余裕。
    "period": "2y",
    # RS平滑化のEMAスパン
    "ema_span": 5,
    # RS-Ratio / RS-Momentum のz-score正規化ウィンドウ (営業日)
    "window": 63,
    # RS-Momentum算出時の変化率ウィンドウ (営業日)
    "momentum_lookback": 5,
    # 順位加速度算出時の速度ウィンドウ (営業日)
    "rank_lookback": 5,
    # チャートの彗星の尾の長さ (営業日)。メインはこちら。
    # 20営業日で試した結果、密集した象限で軌跡同士が絡み合い、同じ色
    # (グループ単位のため複数銘柄が共有)の尾が交差すると追いにくくなる
    # ことを確認済みのため、通常表示は10営業日を採用している。
    "tail_days": 10,
    # 参考用サブ表示の尾の長さ (営業日)。メインより長い期間の推移を
    # 必要なときだけ見られるよう、plot_rrg.pyがメインとは別ファイルで
    # もう1枚出力する。
    "tail_days_sub": 20,
    # 業種モメンタムランキング(compute_momentum_ranking)のトレイリング
    # リターン算出期間 (営業日)。252営業日≈12ヶ月は、Moskowitz & Grinblatt
    # (1999, Journal of Finance)以来の業種モメンタム文献で効果が再現されて
    # いる代表的なフォーメーション期間に合わせている(自己流の値ではない)。
    "momentum_ranking_lookback_days": 252,
    # データ取得リトライ回数と待機秒数
    "max_retries": 3,
    "retry_wait_sec": 5,
    # 出力ディレクトリ
    "output_dir": "output",
}

# 4マクログループの配色・ラベル。plot_rrg.py / plot_momentum_ranking.py の
# 両方が同じグループ分けを使い回すため、ここ(データ側)に置いて共有する。
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
# ============================================================


def download_prices(tickers: list, period: str) -> pd.DataFrame:
    """
    yfinance で調整後終値を取得し、列=ティッカーの DataFrame を返す。
    (sector_rotation_monitor.py の同名関数と同じロジックを移植)
    """
    last_err = None
    for attempt in range(1, CONFIG["max_retries"] + 1):
        try:
            raw = yf.download(
                tickers,
                period=period,
                auto_adjust=True,
                progress=False,
                group_by="column",
            )
            if raw is None or raw.empty:
                raise ValueError("yf.download が空のデータを返しました")
            break
        except Exception as e:
            last_err = e
            print(f"[警告] データ取得失敗 (試行 {attempt}/{CONFIG['max_retries']}): {e}")
            if attempt < CONFIG["max_retries"]:
                time.sleep(CONFIG["retry_wait_sec"])
    else:
        raise RuntimeError(
            f"[エラー発生源: download_prices] {CONFIG['max_retries']}回の試行後も"
            f"データ取得に失敗しました。最終エラー: {last_err}\n"
            "  対処: ネットワーク接続、ティッカー名、yfinanceのバージョンを確認してください。"
        )

    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"].copy()
        else:
            raise KeyError(
                "[エラー発生源: download_prices] MultiIndex 列に 'Close' が見つかりません。"
                f" 実際の列: {list(raw.columns.get_level_values(0).unique())}"
            )
    else:
        if "Close" in raw.columns:
            close = raw[["Close"]].copy()
            close.columns = [tickers[0]] if len(tickers) == 1 else close.columns
        else:
            raise KeyError(
                "[エラー発生源: download_prices] 列に 'Close' が見つかりません。"
                f" 実際の列: {list(raw.columns)}"
            )

    if isinstance(close, pd.Series):
        close = close.to_frame(name=tickers[0])

    missing = [t for t in tickers if t not in close.columns]
    if missing:
        print(f"[警告] 次のティッカーは取得できませんでした: {missing}")

    all_nan = [c for c in close.columns if close[c].isna().all()]
    if all_nan:
        print(f"[警告] 全期間 NaN のため除外: {all_nan}")
        close = close.drop(columns=all_nan)

    if close.empty or close.shape[1] == 0:
        raise ValueError(
            "[エラー発生源: download_prices] 有効な価格データが1本もありません。"
        )

    close.index.name = "Date"
    close = close.ffill()
    return close


def classify_quadrant(rs_ratio, rs_momentum):
    """RS-Ratio/RS-Momentumから4象限を判定する。"""
    if pd.isna(rs_ratio) or pd.isna(rs_momentum):
        return None
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    if rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    if rs_ratio < 100 and rs_momentum < 100:
        return "Lagging"
    return "Improving"


def compute_rrg(
    close: pd.DataFrame,
    benchmark: str = None,
    ema_span: int = None,
    window: int = None,
    momentum_lookback: int = None,
    rank_lookback: int = None,
) -> pd.DataFrame:
    """
    全セクターのRS-Ratio/RS-Momentum/象限/順位加速度を計算し、
    long形式 (Date, Symbol, ...) のDataFrameを返す。

    引数を省略するとCONFIGの値を使う(通常の日次実行はこちら)。
    backtest_rrg.py がベンチマークや窓幅を変えて同じ計算式を再利用できる
    よう、明示的に上書きできるようにしている — 本番実行とバックテストで
    計算ロジックが分岐して食い違うのを避けるため、数式自体はここ1箇所のみ。
    """
    benchmark = CONFIG["benchmark"] if benchmark is None else benchmark
    ema_span = CONFIG["ema_span"] if ema_span is None else ema_span
    window = CONFIG["window"] if window is None else window
    momentum_lookback = CONFIG["momentum_lookback"] if momentum_lookback is None else momentum_lookback
    rank_lookback = CONFIG["rank_lookback"] if rank_lookback is None else rank_lookback

    if benchmark not in close.columns:
        raise ValueError(
            f"[エラー発生源: compute_rrg] ベンチマーク {benchmark} の価格データがありません。"
        )
    bench_close = close[benchmark]

    per_sector_frames = []
    rs_ratio_wide = {}

    for sec in CONFIG["sectors"]:
        ticker = sec["ticker"]
        if ticker not in close.columns:
            print(f"[警告] {ticker} の価格データが無いため、この銘柄をスキップします。")
            continue

        rs_raw = close[ticker] / bench_close
        rs_smooth = rs_raw.ewm(span=ema_span, adjust=False).mean()

        roll_mean = rs_smooth.rolling(window, min_periods=window).mean()
        roll_std = rs_smooth.rolling(window, min_periods=window).std()
        rs_ratio = 100 + (rs_smooth - roll_mean) / roll_std

        roc = rs_ratio - rs_ratio.shift(momentum_lookback)
        roc_mean = roc.rolling(window, min_periods=window).mean()
        roc_std = roc.rolling(window, min_periods=window).std()
        rs_momentum = 100 + (roc - roc_mean) / roc_std

        df_sec = pd.DataFrame({
            "Close": close[ticker],
            "RS_raw": rs_raw,
            "RS_smooth": rs_smooth,
            "RS_Ratio": rs_ratio,
            "RS_Momentum": rs_momentum,
        })
        df_sec["Symbol"] = ticker
        df_sec["Label"] = sec["label"]
        df_sec["Group"] = sec["group"]
        df_sec["Quadrant"] = [
            classify_quadrant(r, m) for r, m in zip(df_sec["RS_Ratio"], df_sec["RS_Momentum"])
        ]
        per_sector_frames.append(df_sec)
        rs_ratio_wide[ticker] = rs_ratio

    if not per_sector_frames:
        raise RuntimeError("[エラー発生源: compute_rrg] 計算できたセクターが1つもありません。")

    long_df = pd.concat(per_sector_frames)
    long_df.index.name = "Date"
    long_df = long_df.reset_index()

    # --- 順位加速度 (セクター横断のランキングの2階差分) ---
    rs_ratio_wide_df = pd.DataFrame(rs_ratio_wide)
    rs_ratio_wide_df.index.name = "Date"
    rs_ratio_wide_df.columns.name = "Symbol"

    rank = rs_ratio_wide_df.rank(axis=1, ascending=True)
    rank_velocity = rank - rank.shift(rank_lookback)
    rank_accel = rank_velocity - rank_velocity.shift(rank_lookback)

    rank_df = pd.concat(
        [rank.stack(), rank_velocity.stack(), rank_accel.stack()],
        axis=1, keys=["Rank", "RankVelocity", "RankAccel"],
    ).reset_index()

    long_df = long_df.merge(rank_df, on=["Date", "Symbol"], how="left")
    return long_df


def compute_latest_summary(long_df: pd.DataFrame):
    """long形式データから直近日だけを抜き出し、RankAccel降順のサマリーを返す。"""
    valid = long_df.dropna(subset=["RS_Ratio", "RS_Momentum"])
    if valid.empty:
        raise ValueError(
            "[エラー発生源: compute_latest_summary] RS-Ratio/RS-Momentumが計算できた行がありません。"
            " 取得期間(period)がウィンドウ幅(window)に対して短すぎる可能性があります。"
        )
    last_date = valid["Date"].max()
    summary = valid[valid["Date"] == last_date].copy()
    summary = summary.sort_values("RankAccel", ascending=False)
    summary = summary[[
        "Symbol", "Label", "Group", "Quadrant", "RS_Ratio", "RS_Momentum",
        "Rank", "RankVelocity", "RankAccel",
    ]]
    return summary, last_date


def generate_situation_summary(summary: pd.DataFrame) -> str:
    """
    直近日のサマリーから、現在の状況を平易な日本語で説明する短文を生成する。
    象限(Leading/Improving/Weakening/Lagging)ごとにセクターを振り分け、
    Improving象限は順位加速度(RankAccel)が大きい順に並べて、その中でも
    どこが特に加速しているかが分かるようにする。ただしバックテストで
    優位性が確認できていないため「早期候補」と断定する表現は避けている。
    """
    def fmt(tickers):
        return "、".join(
            f"{t}({summary.set_index('Symbol').loc[t, 'Label']})" for t in tickers
        )

    by_quadrant = {q: [] for q in ("Leading", "Improving", "Weakening", "Lagging")}
    for _, row in summary.iterrows():
        if row["Quadrant"] in by_quadrant:
            by_quadrant[row["Quadrant"]].append(row)

    # Improving はRankAccel(既にsummary全体でRankAccel降順)の順のまま使う
    improving_syms = [r["Symbol"] for r in by_quadrant["Improving"]]
    leading_syms = [r["Symbol"] for r in by_quadrant["Leading"]]
    weakening_syms = [r["Symbol"] for r in by_quadrant["Weakening"]]
    lagging_syms = [r["Symbol"] for r in by_quadrant["Lagging"]]

    lines = []
    if improving_syms:
        top = improving_syms[0]
        top_label = summary.set_index("Symbol").loc[top, "Label"]
        lines.append(
            f"☆勢いが好転し始めた銘柄(Improving、参考情報): {fmt(improving_syms)}。"
            f"中でも{top}({top_label})は順位の加速度(RankAccel)が最大。"
            f"※簡易バックテストではこの象限入りとその後の相対リターン改善に一貫した関係は確認できていません。"
        )
    if leading_syms:
        lines.append(f"◆現在の主役(Leading): {fmt(leading_syms)}。既に強く、勢いも続いている。")
    if weakening_syms:
        lines.append(f"▽勢い鈍化(Weakening): {fmt(weakening_syms)}。強いが失速し始めており、利益確定を検討する局面。")
    if lagging_syms:
        lines.append(f"・様子見(Lagging): {fmt(lagging_syms)}。弱く、まだ転換の兆しなし。")
    if not lines:
        lines.append("十分なデータがないため、状況を判定できません。")
    return "\n".join(lines)


def format_rank_leaderboard(summary: pd.DataFrame, top_n: int = 5) -> str:
    """
    順位加速度(RankAccel)の上位/下位をリーダーボード形式のテキストにする。
    RRGの63日ウィンドウはまだ反応しきっていない急な順位変化を捉える補助
    指標のため、Improving象限の中の順位付けだけでなく全銘柄を対象にする
    (加速度が大きい銘柄がImproving以外の象限にいることもあるため)。
    """
    ranked = summary.sort_values("RankAccel", ascending=False).reset_index(drop=True)
    n = min(top_n, len(ranked))

    lines = ["[順位加速度(RankAccel)リーダーボード] (11銘柄中、上位/下位を表示)"]
    lines.append(f"  加速度が大きい順(急上昇): ")
    for i in range(n):
        row = ranked.iloc[i]
        lines.append(
            f"    {i + 1}. {row['Symbol']}({row['Label']}) "
            f"RankAccel={row['RankAccel']:+.1f}  順位={row['Rank']:.0f}位  象限={row['Quadrant']}"
        )
    lines.append(f"  加速度が小さい順(急降下):")
    for i in range(n):
        row = ranked.iloc[-(i + 1)]
        lines.append(
            f"    {i + 1}. {row['Symbol']}({row['Label']}) "
            f"RankAccel={row['RankAccel']:+.1f}  順位={row['Rank']:.0f}位  象限={row['Quadrant']}"
        )
    return "\n".join(lines)


def compute_momentum_ranking(
    close: pd.DataFrame, benchmark: str = None, lookback_days: int = None,
) -> pd.DataFrame:
    """
    Moskowitz & Grinblatt (1999)以来、業種モメンタムとして再現性が確認されて
    いる手法に基づき、直近lookback_days(既定252営業日≈12ヶ月)のトレイリング
    リターンでセクターを順位付けする。

    RRG(compute_rrg)と違ってEMA平滑化・63日ウィンドウでのz-score化を一切
    行わない — その平滑化・正規化こそが、Phase Bのバックテストで確認された
    「反応が遅れる」問題の一因だったため、ここではあえて生のトレイリング
    リターンをそのまま使う、素朴な設計にしている。

    RelativeReturn(ベンチマーク比の超過リターン)を表示・保存はするが、
    ランキングの順序自体は素のTrailingReturnで並べても同じになる(全銘柄から
    同じベンチマークリターンを引くだけなので、引き算は順位に影響しない)。
    RelativeReturnは「市場全体に対してどれだけ勝っているか」を数値で見せる
    ための表示用の値。
    """
    benchmark = CONFIG["benchmark"] if benchmark is None else benchmark
    lookback_days = CONFIG["momentum_ranking_lookback_days"] if lookback_days is None else lookback_days

    if len(close) <= lookback_days:
        raise ValueError(
            f"[エラー発生源: compute_momentum_ranking] 取得データが{len(close)}営業日分しかなく、"
            f"lookback_days={lookback_days}日の計算に足りません。CONFIGのperiodを長くしてください。"
        )

    latest = close.iloc[-1]
    base = close.iloc[-1 - lookback_days]
    latest_date = close.index[-1]

    if benchmark not in close.columns:
        raise ValueError(
            f"[エラー発生源: compute_momentum_ranking] ベンチマーク {benchmark} の価格データがありません。"
        )
    bench_return = latest[benchmark] / base[benchmark] - 1

    rows = []
    for sec in CONFIG["sectors"]:
        ticker = sec["ticker"]
        if ticker not in close.columns:
            print(f"[警告] {ticker} の価格データが無いため、モメンタムランキングから除外します。")
            continue
        sec_return = latest[ticker] / base[ticker] - 1
        rows.append({
            "Symbol": ticker,
            "Label": sec["label"],
            "Group": sec["group"],
            "TrailingReturn": sec_return,
            "RelativeReturn": sec_return - bench_return,
        })

    if not rows:
        raise RuntimeError("[エラー発生源: compute_momentum_ranking] 計算できたセクターが1つもありません。")

    df = pd.DataFrame(rows).sort_values("RelativeReturn", ascending=False).reset_index(drop=True)
    df.insert(0, "Rank", df.index + 1)
    df.insert(0, "Date", latest_date)
    return df


def save_outputs(long_df: pd.DataFrame, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")

    data_path = os.path.join(out_dir, f"rrg_data_{stamp}.csv")
    long_df.to_csv(data_path, encoding="utf-8-sig", index=False)

    summary, last_date = compute_latest_summary(long_df)
    summary_path = os.path.join(out_dir, f"rrg_summary_{stamp}.csv")
    summary.to_csv(summary_path, encoding="utf-8-sig", index=False)

    return data_path, summary_path, summary, last_date


def main():
    print("=" * 60)
    print("S&P500 セクター・ローテーション早期兆候検知 (RRG)")
    print(f"  対象: {[s['ticker'] for s in CONFIG['sectors']]}")
    print(f"  ベンチマーク: {CONFIG['benchmark']}")
    print(f"  期間: {CONFIG['period']} / window={CONFIG['window']}日 / "
          f"momentum={CONFIG['momentum_lookback']}日 / rank={CONFIG['rank_lookback']}日")
    print("=" * 60)

    try:
        all_tickers = sorted({s["ticker"] for s in CONFIG["sectors"]} | {CONFIG["benchmark"]})
        close = download_prices(all_tickers, CONFIG["period"])
        print(f"[情報] 価格データ取得完了: {close.shape[0]}営業日 × {close.shape[1]}銘柄")

        long_df = compute_rrg(close)
        data_path, summary_path, summary, last_date = save_outputs(long_df, CONFIG["output_dir"])

        print(f"\n[完了] 詳細データ: {data_path}")
        print(f"[完了] サマリー  : {summary_path}")
        print(f"\n直近データ日: {last_date.strftime('%Y-%m-%d') if hasattr(last_date, 'strftime') else last_date}")
        print(summary.to_string(index=False))

        print("\n[現状の要約]")
        print(generate_situation_summary(summary))

        print()
        print(format_rank_leaderboard(summary))

        momentum_df = compute_momentum_ranking(close)
        stamp = datetime.now().strftime("%Y%m%d")
        momentum_path = os.path.join(CONFIG["output_dir"], f"momentum_ranking_{stamp}.csv")
        momentum_df.to_csv(momentum_path, encoding="utf-8-sig", index=False)
        print(f"\n[完了] 業種モメンタムランキング: {momentum_path}")
        print(
            f"[12ヶ月モメンタムランキング(対{CONFIG['benchmark']}、学術的裏付けのある手法。"
            f"月次程度のリバランス前提)]"
        )
        print(momentum_df.drop(columns="Date").to_string(index=False))

        print("\n[次のステップ] plot_rrg.py を実行すると彗星チャートを、"
              "plot_momentum_ranking.py を実行するとモメンタムランキング図を作成できます。")

    except Exception as e:
        print("\n[エラー] 処理が中断されました。")
        print(f"  内容: {e}")
        print("  --- 詳細トレースバック ---")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
