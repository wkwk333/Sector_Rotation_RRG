# -*- coding: utf-8 -*-
"""
backtest_momentum_ranking.py
==============================
plot_momentum_ranking.py の「活用方法」欄で案内している運用ルール
(上位N銘柄を均等保有し、月次でリバランス)を、このツール自身の
11セクターSPDRの実データに対してシミュレーションし、累積リターン・CAGR・
シャープレシオ・最大ドローダウンをRSP買い持ちと比較する。

Moskowitz & Grinblatt (1999) やQuantpedia「Sector Momentum - Rotational
System」(1928-2009年、米国株全体が対象)は他人の研究・他のユニバースでの
結果であり、このツール固有の「11セクターSPDR・直近10年」という条件でも
同じように機能するかはこれまで未検証だった。backtest_rrg.py がRRG側の
簡易バックテストだったのに対し、これはモメンタムランキング側の簡易
バックテストで、Phase Bの最後の検証項目にあたる。

手法:
    各月末時点で、直近lookback_monthsヶ月(既定12ヶ月)の月次トレイリング
    リターンで全セクターを順位付けし、上位top_n銘柄を均等保有。
    翌月末まで保有してそのリターンを記録し、翌月末に再度順位付けして
    入れ替える(=月次リバランス)。これをデータ全期間で繰り返して連結し、
    CAGR・年率ボラティリティ・シャープレシオ・最大ドローダウンを求める。

    XLC(通信サービス、2018年設定)のように取得期間中に未上場の月がある
    銘柄は、その月のランキング対象から自然に除外される(simulate_top_n内で
    NaNの銘柄をスキップするだけで、期間全体をXLC上場後に絞るような特別
    処理はしていない)。

これも簡易バックテストであり、取引コスト・スリッページ・税金・配当再投資の
細部は考慮していない。過去のある1期間の結果であり、将来の性能を保証しない。
シャープレシオも無リスク金利を引かない簡易版(平均超過リターン/ボラティリティ
ではなく、平均リターン/ボラティリティ)であることに注意。

実行方法(rrg_monitor.py / backtest_rrg.py とは独立に単独実行できる):
    python backtest_momentum_ranking.py

出力:
    ./output/momentum_backtest_results_YYYYMMDD.csv
    コンソールにも同じ内容を表示する
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import os
import sys
import traceback
from datetime import datetime

import numpy as np
import pandas as pd

from rrg_monitor import CONFIG, download_prices

BACKTEST_CONFIG = {
    # yfinanceで安定して取れる範囲でできるだけ長く取る。XLC(2018年設定)は
    # この期間の前半は自然に対象外になるだけで、エラーにはならない。
    "period": "10y",
    "lookback_months": 12,
    # plot_momentum_ranking.pyの活用方法欄で案内している「上位3〜4銘柄」と
    # 揃える — 実際に案内している運用ルールをそのまま検証するため。
    "top_n_variants": [3, 4],
    # 日本の上場株式等の譲渡益・配当に対する税率(所得税15% + 復興特別所得税
    # 0.315% + 住民税5%、申告分離課税)。NISA等の非課税枠は考慮しない
    # (課税口座での運用を仮定)。
    "tax_rate": 0.20315,
}


def build_monthly_close(close: pd.DataFrame) -> pd.DataFrame:
    """日次終値を月末値にリサンプルする(月次リバランスのシミュレーション用)。"""
    monthly = close.resample("ME").last()
    monthly.index.name = "Date"
    return monthly


def simulate_top_n(
    monthly: pd.DataFrame, sector_tickers: list, lookback_months: int, top_n: int,
) -> pd.DataFrame:
    """
    各月末に、直近lookback_monthsヶ月のトレイリングリターン上位top_n銘柄を
    均等保有したと仮定し、翌月のポートフォリオリターンを月次で記録する。
    """
    records = []
    n_rows = len(monthly)
    for i in range(lookback_months, n_rows - 1):
        base = monthly.iloc[i - lookback_months]
        latest = monthly.iloc[i]
        nxt = monthly.iloc[i + 1]

        trailing_returns = {}
        for t in sector_tickers:
            if t not in monthly.columns:
                continue
            b, l = base.get(t), latest.get(t)
            if pd.isna(b) or pd.isna(l):
                continue
            trailing_returns[t] = l / b - 1

        if len(trailing_returns) < top_n:
            continue  # まだ十分な銘柄が上場していない月(例: XLC設定前)はスキップ

        ranked = sorted(trailing_returns.items(), key=lambda kv: kv[1], reverse=True)
        selected = [t for t, _ in ranked[:top_n]]

        fwd_returns = []
        for t in selected:
            p_now, p_next = latest.get(t), nxt.get(t)
            if pd.isna(p_now) or pd.isna(p_next):
                continue
            fwd_returns.append(p_next / p_now - 1)
        if not fwd_returns:
            continue

        records.append({
            "Date": monthly.index[i + 1],
            "PortfolioReturn": float(np.mean(fwd_returns)),
            "Selected": ",".join(selected),
        })

    return pd.DataFrame(records)


def simulate_top_n_minimal_turnover_after_tax(
    monthly: pd.DataFrame, sector_tickers: list, lookback_months: int, top_n: int, tax_rate: float,
) -> pd.DataFrame:
    """
    apply_monthly_tax()の「毎月全額を一度精算」という保守的前提とは違い、
    「その月に上位から外れた銘柄だけを売却・課税し、継続保有銘柄は一切
    売買しない」というより現実的な最小回転の運用を、税引き後の資産推移として
    直接シミュレートする(simulate_top_n()の税引き前シミュレーションとは
    別の実装 — こちらは銘柄ごとの取得原価をportfolio状態として保持する
    必要があるため、月次リターンの平均を取るだけでは表現できない)。

    期間の最後には残っている保有銘柄もすべて売却・課税し、税引き後の
    最終資産で公平に(買い持ちの「最後に1回だけ売却」と同条件で)比較できる
    ようにする。
    """
    positions = {}  # ticker -> {"cost": 取得原価, "value": 現在価値, "ref_price": 直近の評価に使った価格}
    cash = 0.0
    history = []
    n_rows = len(monthly)

    for i in range(lookback_months, n_rows - 1):
        base = monthly.iloc[i - lookback_months]
        latest = monthly.iloc[i]
        nxt = monthly.iloc[i + 1]

        trailing_returns = {}
        for t in sector_tickers:
            if t not in monthly.columns:
                continue
            b, l = base.get(t), latest.get(t)
            if pd.isna(b) or pd.isna(l):
                continue
            trailing_returns[t] = l / b - 1
        if len(trailing_returns) < top_n:
            continue

        ranked = sorted(trailing_returns.items(), key=lambda kv: kv[1], reverse=True)
        selected = set(t for t, _ in ranked[:top_n])

        if not positions and cash == 0.0:
            cash = 1.0  # 初回のみ元手を投入

        held = set(positions.keys())
        to_sell = held - selected
        for t in to_sell:
            pos = positions.pop(t)
            gain = pos["value"] - pos["cost"]
            tax = max(gain, 0) * tax_rate
            cash += pos["value"] - tax

        to_buy = selected - held
        if to_buy and cash > 0:
            per_ticker_cash = cash / len(to_buy)
            for t in to_buy:
                price = latest.get(t)
                if pd.isna(price):
                    continue
                positions[t] = {"cost": per_ticker_cash, "value": per_ticker_cash, "ref_price": price}
            cash = 0.0

        # 保有継続中の全ポジション(今買ったばかりの銘柄も含む)を、
        # 翌月末の価格まで値洗いする(ここでは売買しないので課税なし)。
        for t, pos in positions.items():
            next_price = nxt.get(t)
            if pd.isna(next_price) or pd.isna(pos["ref_price"]):
                continue
            pos["value"] *= next_price / pos["ref_price"]
            pos["ref_price"] = next_price

        total_value = cash + sum(p["value"] for p in positions.values())
        history.append({"Date": monthly.index[i + 1], "Value": total_value})

    if not history:
        return pd.DataFrame(columns=["Date", "Value", "NetReturn"])

    # 最終月に残っているポジションもすべて売却・課税し、公平な最終資産にする
    # (このシミュレーションの直前の状態ではcashは常に0 — 毎月、売却で得た
    # 現金はその月のうちに全額再投資しているため)。
    final_value = cash
    for pos in positions.values():
        gain = pos["value"] - pos["cost"]
        tax = max(gain, 0) * tax_rate
        final_value += pos["value"] - tax
    history[-1]["Value"] = final_value

    hist_df = pd.DataFrame(history)
    hist_df["NetReturn"] = hist_df["Value"].pct_change()
    hist_df.loc[hist_df.index[0], "NetReturn"] = hist_df["Value"].iloc[0] / 1.0 - 1
    return hist_df


def apply_monthly_tax(returns: pd.Series, tax_rate: float) -> pd.Series:
    """
    「毎月フルに一度精算(100%回転)し、含み益にその都度課税してから
    翌月に繰り越す」という保守的な前提で、税引き後の月次リターン列を作る。

    simulate_top_n()のPortfolioReturnは「毎月、上位N銘柄に均等配分し直す」
    計算(=継続銘柄も含め理論上は毎月組み直す)ことと整合させるため、この
    税引き後モデルも同じく毎月全額売却・課税・再投資すると仮定している。
    現実には継続保有銘柄まで毎月売る必要はなく、最小限の入れ替えだけで
    運用すれば税負担はもっと軽くなる — つまりこれは「税負担を多めに見積もる
    保守的なシナリオ」であることに注意(下記CLAUDE.mdにも明記)。
    損益通算(その年の他の譲渡損との相殺)は考慮せず、各月の利益に単純に
    課税する(損失側の節税効果を見込まない、これも保守的)。
    """
    value = 1.0
    net_returns = []
    for gross_ret in returns:
        gain = value * gross_ret
        tax = max(gain, 0) * tax_rate
        new_value = value + gain - tax
        net_returns.append(new_value / value - 1)
        value = new_value
    return pd.Series(net_returns, index=returns.index)


def apply_buyhold_tax(returns: pd.Series, tax_rate: float) -> dict:
    """
    買い持ち(期間中一度も売らず、最後にまとめて売却)を仮定し、
    税引き後のCAGR等を返す。累積した含み益にまとめて1回だけ課税するため、
    毎月課税されるapply_monthly_tax()より税の繰延効果が大きい。
    """
    gross_final_value = float((1 + returns).prod())
    gain = gross_final_value - 1.0
    tax = max(gain, 0) * tax_rate
    after_tax_final_value = 1.0 + gain - tax

    n = len(returns)
    years = n / 12
    cagr = after_tax_final_value ** (1 / years) - 1 if years > 0 else np.nan
    return {"CAGR": cagr, "税引き前最終資産倍率": gross_final_value, "税引き後最終資産倍率": after_tax_final_value}


def compute_stats(returns: pd.Series, periods_per_year: int = 12) -> dict:
    """月次リターン列からCAGR・年率ボラティリティ・簡易シャープ・最大DDを求める。"""
    returns = returns.dropna()
    n = len(returns)
    if n == 0:
        return {"CAGR": np.nan, "Vol": np.nan, "Sharpe": np.nan, "MaxDrawdown": np.nan, "件数": 0}

    cum = (1 + returns).cumprod()
    total_return = cum.iloc[-1] - 1
    years = n / periods_per_year
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else np.nan

    vol = returns.std() * np.sqrt(periods_per_year)
    sharpe = (returns.mean() * periods_per_year) / vol if vol and vol > 0 else np.nan

    running_max = cum.cummax()
    drawdown = cum / running_max - 1
    max_dd = drawdown.min()

    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MaxDrawdown": max_dd, "件数": n}


def print_stats(label: str, stats: dict):
    print(f"--- {label} ---")
    print(
        f"  CAGR: {stats['CAGR']*100:+.2f}%  年率ボラティリティ: {stats['Vol']*100:.2f}%  "
        f"簡易シャープレシオ: {stats['Sharpe']:.2f}  最大ドローダウン: {stats['MaxDrawdown']*100:.2f}%  "
        f"サンプル数: {stats['件数']}ヶ月"
    )


def main():
    try:
        print("=" * 70)
        print("モメンタムランキング運用ルールの簡易バックテスト (上位N銘柄・月次リバランス)")
        print(f"  取得期間: {BACKTEST_CONFIG['period']} / トレイリング期間: {BACKTEST_CONFIG['lookback_months']}ヶ月")
        print(f"  検証する上位銘柄数: {BACKTEST_CONFIG['top_n_variants']}")
        print("=" * 70)

        sector_tickers = [s["ticker"] for s in CONFIG["sectors"]]
        benchmark = CONFIG["benchmark"]
        all_tickers = sorted(set(sector_tickers) | {benchmark})
        close = download_prices(all_tickers, BACKTEST_CONFIG["period"])
        print(f"[情報] 価格データ取得完了: {close.shape[0]}営業日 × {close.shape[1]}銘柄")

        monthly = build_monthly_close(close)
        print(f"[情報] 月次にリサンプル完了: {monthly.shape[0]}ヶ月分\n")

        bench_returns = monthly[benchmark].pct_change().dropna()
        bench_stats = compute_stats(bench_returns)
        print_stats(f"ベンチマーク: {benchmark} 買い持ち", bench_stats)

        all_rows = [{"variant": f"benchmark_{benchmark}", **bench_stats}]
        sims = {}

        for top_n in BACKTEST_CONFIG["top_n_variants"]:
            sim = simulate_top_n(monthly, sector_tickers, BACKTEST_CONFIG["lookback_months"], top_n)
            print()
            if sim.empty:
                print(f"--- 上位{top_n}銘柄・月次リバランス ---\n  [警告] シミュレーション結果が空です。")
                continue
            stats = compute_stats(sim["PortfolioReturn"])
            print_stats(f"上位{top_n}銘柄・月次リバランス", stats)
            all_rows.append({"variant": f"top_{top_n}", **stats})
            sims[top_n] = sim

        # --- 日本の税率を考慮した場合の比較 ---
        tax_rate = BACKTEST_CONFIG["tax_rate"]
        print(f"\n{'=' * 70}")
        print(f"税引き後(日本の譲渡益課税 {tax_rate*100:.3f}%、申告分離課税・NISA等は考慮せず)の比較")
        print(f"{'=' * 70}")

        bench_after_tax = apply_buyhold_tax(bench_returns, tax_rate)
        print(f"\n--- ベンチマーク: {benchmark} 買い持ち (最後に1回だけ売却) ---")
        print(
            f"  税引き前CAGR: {bench_stats['CAGR']*100:+.2f}%  →  "
            f"税引き後CAGR: {bench_after_tax['CAGR']*100:+.2f}%  "
            f"(税引き前資産倍率{bench_after_tax['税引き前最終資産倍率']:.2f}倍 → "
            f"税引き後{bench_after_tax['税引き後最終資産倍率']:.2f}倍。売却は期間終了時の1回のみ)"
        )
        tax_rows = [{
            "variant": f"benchmark_{benchmark}", "課税方式": "買い持ち(最後に1回売却)",
            "税引き前CAGR": bench_stats["CAGR"], "税引き後CAGR": bench_after_tax["CAGR"],
        }]

        for top_n, sim in sims.items():
            pretax_ret = sim["PortfolioReturn"]
            aftertax_ret = apply_monthly_tax(pretax_ret, tax_rate)
            pretax_stats = compute_stats(pretax_ret)
            aftertax_stats = compute_stats(aftertax_ret)
            print(f"\n--- 上位{top_n}銘柄・月次リバランス [保守的: 毎月フル入れ替え・毎月課税] ---")
            print(
                f"  税引き前CAGR: {pretax_stats['CAGR']*100:+.2f}%  →  "
                f"税引き後CAGR: {aftertax_stats['CAGR']*100:+.2f}%  "
                f"(課税イベント: 毎月、{pretax_stats['件数']}回)"
            )
            tax_rows.append({
                "variant": f"top_{top_n}", "課税方式": "月次リバランス(保守的: 毎月フル入れ替え)",
                "税引き前CAGR": pretax_stats["CAGR"], "税引き後CAGR": aftertax_stats["CAGR"],
            })

            # より現実的な想定: 入れ替えられた銘柄だけ売却・課税し、継続保有銘柄は
            # 一切売買しない(最小回転)。上の「毎月フル入れ替え」より税負担は軽くなるはず。
            minimal = simulate_top_n_minimal_turnover_after_tax(
                monthly, sector_tickers, BACKTEST_CONFIG["lookback_months"], top_n, tax_rate,
            )
            if minimal.empty:
                print(f"  [警告] 最小回転版のシミュレーション結果が空です。")
                continue
            minimal_stats = compute_stats(minimal["NetReturn"])
            print(f"--- 上位{top_n}銘柄・月次リバランス [現実的: 入れ替え銘柄のみ売却・最小回転] ---")
            print(
                f"  税引き後CAGR: {minimal_stats['CAGR']*100:+.2f}%  "
                f"(継続保有銘柄は売買しないため無課税、外れた銘柄のみ売却時に課税)"
            )
            tax_rows.append({
                "variant": f"top_{top_n}", "課税方式": "月次リバランス(現実的: 最小回転)",
                "税引き前CAGR": np.nan, "税引き後CAGR": minimal_stats["CAGR"],
            })

        print(
            "\n[税引き後比較の読み方] 月次リバランス戦略は入れ替えのたびに含み益へ課税されるのに対し、"
            "買い持ちは最後の1回しか課税されない(税の繰延効果)。このため税引き前で見るより、"
            "税引き後では両者の差が縮む(場合によっては逆転しうる)方向に働きます。"
            "「保守的」シナリオは継続保有銘柄も含め毎月全額を一度精算する前提で税負担を多めに見積もり、"
            "「現実的」シナリオは実際に入れ替えられた銘柄だけを売却する前提です。"
            "実際の運用は後者に近くなるはずです。"
        )

        result_df = pd.DataFrame(all_rows)
        tax_df = pd.DataFrame(tax_rows)
        stamp = datetime.now().strftime("%Y%m%d")
        out_path = os.path.join(CONFIG["output_dir"], f"momentum_backtest_results_{stamp}.csv")
        tax_out_path = os.path.join(CONFIG["output_dir"], f"momentum_backtest_aftertax_{stamp}.csv")
        os.makedirs(CONFIG["output_dir"], exist_ok=True)
        result_df.to_csv(out_path, encoding="utf-8-sig", index=False)
        tax_df.to_csv(tax_out_path, encoding="utf-8-sig", index=False)
        print(f"\n[完了] 結果を保存しました: {out_path}")
        print(f"[完了] 税引き後比較を保存しました: {tax_out_path}")
        print(
            "\n[読み方の注意] 取引コスト・スリッページは考慮していない簡易バックテストです。"
            "シャープレシオも無リスク金利を引かない簡易版です。過去1期間の結果であり、"
            "将来の性能を保証しません。"
        )

    except Exception as e:
        print("\n[エラー] 処理が中断されました。")
        print(f"  内容: {e}")
        print("  --- 詳細トレースバック ---")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
