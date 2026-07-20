# -*- coding: utf-8 -*-
"""
publish_latest.py
==================
output/ にある最新のRRGチャート・モメンタムランキング図・ダッシュボード画像を
固定ファイル名で public/ にコピーし、生成日時を記載した latest.json を書き出す。

あわせて、その日の分を archive/YYYY-MM-DD/ に追加し、保持ポリシー(直近
FULL_RETENTION_DAYS日は毎日分、それより古いものは各月1枚に間引く)を適用
してから、archive/index.html(閲覧用の日付一覧ページ)を再生成する。
最後にarchive/全体をpublic/archive/へコピーし、1回のGitHub Pagesデプロイで
latestとarchiveの両方が公開されるようにする。

archive/ はリポジトリに正式にコミットされる(public/ と違いgitignore対象外)。
Pagesのデプロイは毎回public/を丸ごと置き換える方式のため、過去分を残すには
public/の外 — git履歴として持続するarchive/ — に保存しておき、毎回そこから
public/へコピーし直す必要がある。CI側では、このスクリプト実行後にarchive/の
差分をリポジトリへコミット・pushする一手間が必要(.github/workflows/
publish-rrg.yml参照)。

実行方法(先に run_pipeline.py または個別に各スクリプトを実行しておくこと):
    python publish_latest.py

出力:
    ./public/latest_rrg_chart.png
    ./public/latest_rrg_chart_sub20d.png
    ./public/latest_momentum_ranking_chart.png
    ./public/latest_dashboard.png
    ./public/latest.json
    ./public/archive/ (archive/ のコピー、index.html含む)
    ./archive/YYYY-MM-DD/ (今回分を追加、保持ポリシーを適用済み)
    ./archive/index.html
"""

import console_utf8  # noqa: F401  (文字化け対策。最初にimportする)

import glob
import json
import os
import shutil
import sys
from datetime import date, datetime, timezone

from rrg_monitor import CONFIG

OUTPUT_DIR = CONFIG["output_dir"]
PUBLISH_DIR = "public"
ARCHIVE_DIR = "archive"

# 直近この日数分はアーカイブを毎日分フルに残す。これより古いものは
# 月1枚(各月最後に記録された日)まで間引く。
FULL_RETENTION_DAYS = 180

# (output/ 内のglobパターン, archive内での固定ファイル名)
ARCHIVE_FILES = [
    ("rrg_chart_[0-9]*.png", "rrg_chart.png"),
    ("rrg_chart_sub20d_[0-9]*.png", "rrg_chart_sub20d.png"),
    ("momentum_ranking_chart_[0-9]*.png", "momentum_ranking_chart.png"),
    ("dashboard_[0-9]*.png", "dashboard.png"),
    ("rrg_data_[0-9]*.csv", "rrg_data.csv"),
    ("rrg_summary_[0-9]*.csv", "rrg_summary.csv"),
    ("momentum_ranking_[0-9]*.csv", "momentum_ranking.csv"),
]


def find_latest(pattern: str) -> str:
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"[エラー発生源: find_latest] {pattern} に一致するファイルがありません。"
            " 先に run_pipeline.py (または各スクリプト) を実行してください。"
        )
    return matches[-1]


def publish_latest_files() -> str:
    os.makedirs(PUBLISH_DIR, exist_ok=True)

    rrg_src = find_latest(os.path.join(OUTPUT_DIR, "rrg_chart_[0-9]*.png"))
    rrg_sub_src = find_latest(os.path.join(OUTPUT_DIR, "rrg_chart_sub20d_[0-9]*.png"))
    momentum_src = find_latest(os.path.join(OUTPUT_DIR, "momentum_ranking_chart_[0-9]*.png"))
    dashboard_src = find_latest(os.path.join(OUTPUT_DIR, "dashboard_[0-9]*.png"))

    shutil.copy2(rrg_src, os.path.join(PUBLISH_DIR, "latest_rrg_chart.png"))
    shutil.copy2(rrg_sub_src, os.path.join(PUBLISH_DIR, "latest_rrg_chart_sub20d.png"))
    shutil.copy2(momentum_src, os.path.join(PUBLISH_DIR, "latest_momentum_ranking_chart.png"))
    shutil.copy2(dashboard_src, os.path.join(PUBLISH_DIR, "latest_dashboard.png"))

    stamp = os.path.basename(dashboard_src).replace("dashboard_", "").replace(".png", "")
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_date": stamp,
        "dashboard_url": "latest_dashboard.png",
        "rrg_chart_url": "latest_rrg_chart.png",
        "rrg_chart_sub20d_url": "latest_rrg_chart_sub20d.png",
        "momentum_ranking_chart_url": "latest_momentum_ranking_chart.png",
    }
    manifest_path = os.path.join(PUBLISH_DIR, "latest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[完了] 最新ファイルを {PUBLISH_DIR}/ に書き出しました (データ日付: {stamp})")
    return stamp


def add_to_archive(stamp: str) -> str:
    """stamp(YYYYMMDD)の当日分を archive/YYYY-MM-DD/ にコピーする。"""
    if len(stamp) != 8:
        raise ValueError(f"[エラー発生源: add_to_archive] 日付形式が想定外です: {stamp}")
    dated = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
    dest_dir = os.path.join(ARCHIVE_DIR, dated)
    os.makedirs(dest_dir, exist_ok=True)

    copied = []
    for pattern, dest_name in ARCHIVE_FILES:
        matches = sorted(glob.glob(os.path.join(OUTPUT_DIR, pattern)))
        if not matches:
            continue
        src = next((m for m in matches if stamp in os.path.basename(m)), matches[-1])
        shutil.copy2(src, os.path.join(dest_dir, dest_name))
        copied.append(dest_name)

    print(f"[完了] {dated} 分をアーカイブしました ({len(copied)}ファイル): {dest_dir}")
    return dated


def apply_retention_policy(reference_date: date = None):
    """
    直近FULL_RETENTION_DAYS日は毎日分を残し、それより古い日付は各(年,月)ごとに
    最新の1日だけ残して間引く(そのフォルダをshutil.rmtreeで削除する)。
    """
    if not os.path.isdir(ARCHIVE_DIR):
        return

    reference_date = reference_date or date.today()
    entries = []
    for name in os.listdir(ARCHIVE_DIR):
        path = os.path.join(ARCHIVE_DIR, name)
        if not os.path.isdir(path):
            continue
        try:
            d = datetime.strptime(name, "%Y-%m-%d").date()
        except ValueError:
            continue  # 日付形式でない名前(将来何か置かれても)は無視
        entries.append((d, path))

    old_entries = [(d, p) for d, p in entries if (reference_date - d).days > FULL_RETENTION_DAYS]

    by_month = {}
    for d, p in old_entries:
        by_month.setdefault((d.year, d.month), []).append((d, p))

    removed = 0
    for group in by_month.values():
        group.sort(key=lambda dp: dp[0])
        keep_date, _ = group[-1]  # その月で最後に記録された日だけ残す
        for d, p in group:
            if d != keep_date:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1

    if removed:
        print(
            f"[完了] 保持ポリシーを適用し、{removed}件の古いアーカイブ日を間引きました"
            f"(直近{FULL_RETENTION_DAYS}日より前は月1件に集約)。"
        )


def build_archive_index():
    """
    archive/ 配下の日付一覧を新しい順に並べ、閲覧用のHTML一覧ページと、
    SectorRotationAndroidアプリ(履歴タブ)が読み込むためのindex.jsonの
    両方を作る。片方だけ更新して他方が古いまま、という食い違いを避けるため、
    日付一覧の取得(os.listdir + フィルタ + ソート)は1回だけ行い、
    HTML/JSONどちらもそこから生成する。
    """
    if not os.path.isdir(ARCHIVE_DIR):
        return

    dates = []
    for name in os.listdir(ARCHIVE_DIR):
        path = os.path.join(ARCHIVE_DIR, name)
        if not os.path.isdir(path):
            continue
        try:
            datetime.strptime(name, "%Y-%m-%d")
        except ValueError:
            continue
        dates.append(name)
    dates.sort(reverse=True)

    index_json = {"dates": dates}
    with open(os.path.join(ARCHIVE_DIR, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index_json, f, ensure_ascii=False, indent=2)

    rows = "\n".join(f'<li><a href="{d}/dashboard.png">{d}</a></li>' for d in dates)
    html = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>過去のダッシュボード一覧</title>
<style>
body {{ font-family: sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.3rem; }}
ul {{ line-height: 1.9; }}
</style>
</head>
<body>
<h1>過去のダッシュボード一覧</h1>
<p>直近{FULL_RETENTION_DAYS}日は毎日分、それ以前は月1回分を保持しています。</p>
<ul>
{rows}
</ul>
</body>
</html>
"""
    with open(os.path.join(ARCHIVE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)

    print(
        f"[完了] アーカイブ一覧を作成しました ({len(dates)}件): "
        f"{ARCHIVE_DIR}/index.html (閲覧用), {ARCHIVE_DIR}/index.json (アプリ用)"
    )


def copy_archive_into_public():
    """
    1回のPagesデプロイでlatestとarchiveの両方が公開されるよう、
    archive/ を public/archive/ へコピーする
    (archive/自体はgit管理、public/は毎回使い捨てのデプロイ用ディレクトリ)。
    """
    if not os.path.isdir(ARCHIVE_DIR):
        return
    dest = os.path.join(PUBLISH_DIR, "archive")
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    shutil.copytree(ARCHIVE_DIR, dest)
    print(f"[完了] アーカイブを {dest}/ にコピーしました。")


def main():
    try:
        stamp = publish_latest_files()
        add_to_archive(stamp)
        apply_retention_policy()
        build_archive_index()
        copy_archive_into_public()

        print("\n[完了] 公開用ファイルの準備が整いました。")

    except Exception as e:
        print(f"\n[エラー] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
