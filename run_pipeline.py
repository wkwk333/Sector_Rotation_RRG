# -*- coding: utf-8 -*-
"""
run_pipeline.py
================
rrg_monitor.py -> plot_rrg.py -> plot_momentum_ranking.py を1つのプロセス内で
順番に実行する統合エントリーポイント。Sector_Rotation/run_pipeline.py と
同じ構造(sys.exit(0以外)を検知したらそこで打ち切る)。

backtest_rrg.py / backtest_momentum_ranking.py はここには含めない —
どちらも数分かかるネットワークアクセスを伴う「たまに手動で見返す」検証用
スクリプトであり、毎日の定期実行(このパイプライン)には含めない。

実行方法:
    python run_pipeline.py

出力:
    ./output/ 以下に日次CSV・RRGチャート・モメンタムランキング図一式
"""
import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import sys
import traceback

import rrg_monitor
import plot_rrg
import plot_momentum_ranking


def main():
    steps = [
        ("データ取得・RRG計算・モメンタムランキング計算", rrg_monitor.main),
        ("RRGチャート作成", plot_rrg.main),
        ("モメンタムランキング図作成", plot_momentum_ranking.main),
    ]
    for i, (label, func) in enumerate(steps, start=1):
        print("\n" + "#" * 60)
        print(f"# ステップ {i}/{len(steps)}: {label}")
        print("#" * 60)
        try:
            func()
        except SystemExit as e:
            if e.code not in (0, None):
                print(f"\n[中断] ステップ「{label}」でエラーが発生したため処理を終了します。")
                raise

    print("\n" + "=" * 60)
    print("すべての処理が完了しました。output フォルダを確認してください。")
    print("=" * 60)


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
    except Exception:
        traceback.print_exc()
        exit_code = 1
    sys.exit(exit_code)
