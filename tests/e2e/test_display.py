"""表示マトリクス回帰: 全列のセル表示値＋派生計算（工数=qty×h÷8・親集計）。
   列=No.,名前,数量,時間,工数,担当,予定開始,予定終了,実績開始,実績終了,備考（COLS順）。
   #16でセル生成（表示switch）を書き換える時、出力が1文字でも変わればここが赤くなる。"""
from playwright.sync_api import sync_playwright
from common import VIEWER, check, finish, new_page

# 既知の値の固定データ（期待値を確定するための基準）
FX = {"projects": [{"name": "表示マトリクス", "milestones": [], "tasks": [
    {"id": "1", "name": "集計工程", "children": [
        {"id": "1.1", "name": "完了タスク", "qty": 1, "hours": 8, "assignee": "佐藤",
         "plan": {"start": "2026-06-02", "end": "2026-06-06"},
         "actual": {"start": "2026-06-02", "end": "2026-06-06"},
         "note": "完了の備考", "_ai": {"tokens": 1000}},
        {"id": "1.2", "name": "進行中タスク", "qty": 2, "hours": 16, "assignee": "鈴木",
         "plan": {"start": "2026-06-06", "end": "2026-06-10"},
         "actual": {"start": "2026-06-06", "end": None},
         "note": "資料 https://example.com/x"}]},
    {"id": "2", "name": "未着手タスク", "qty": 1, "hours": 8, "assignee": "田中",
     "plan": {"start": "2026-06-08", "end": "2026-06-12"},
     "actual": {"start": None, "end": None}, "note": ""}
]}]}

# 期待セル列。期間(index5)・進捗(index6)・状況(index7)は派生列なので比較から除外（test_progressで担保）。
# 残り11列 = [No.,名前,数量,時間,工数,担当,予定開始,予定終了,実績開始,実績終了,備考]
def strip(cells):  # 期間・進捗・状況の3列を落とす
    return cells[:5] + cells[8:]
EXPECT = {
    "prow":      ['◆', '▼表示マトリクス', '', '', '6', '', '6/2', '6/12', '', '', ''],              # 親=配下合計工数6・最小最大期間
    "1":         ['1', '▼集計工程', '', '', '5', '', '6/2', '6/10', '6/2', '6/6', ''],              # 集計=1+4・実績は子のmin/max
    "1.1":       ['1.1', '✓ 完了タスク', '1', '8', '1', '佐藤', '6/2', '6/6', '6/2', '6/6', '完了の備考'],  # 工数=1×8÷8=1
    "1.2":       ['2', '16', '4', '鈴木', '6/6', '6/10', '6/6', '進行中'],                           # 数量〜実績終了（工数=2×16÷8=4）
    "2":         ['1', '8', '1', '田中', '6/8', '6/12', '—', '—'],                                  # 未着手=実績は—
}

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 600})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(VIEWER)
    pg.evaluate("d => window.renderData(d)", FX)
    pg.wait_for_timeout(200)

    rows = pg.eval_on_selector_all("#leftRows .lrow", """els=>els.map(r=>({
        cls:[...r.classList].join(' '),
        cells:[...r.querySelectorAll('.c')].map(c=>c.innerText.replace(/\\n.*/s,'')),
        noteHasLink: !!r.querySelector('.c.note a')
    }))""")

    proj, parent, l11, l12, l2 = rows  # 5行ぴったり
    check(strip(proj["cells"]) == EXPECT["prow"], f"プロジェクト行=配下合計\n     {strip(proj['cells'])}")
    check(strip(parent["cells"]) == EXPECT["1"], f"集計ノード=子のmin/max・合計工数\n     {strip(parent['cells'])}")
    check(strip(l11["cells"]) == EXPECT["1.1"] and "done" in l11["cls"], f"完了リーフ（✓・工数1）\n     {strip(l11['cells'])}")
    # 1.2: 数量〜実績終了（進捗・状況を除く）で進行中表示と工数4を確認
    check(strip(l12["cells"])[2:10] == EXPECT["1.2"], f"進行中リーフ（工数4・実績終了=進行中）\n     {strip(l12['cells'])[2:10]}")
    check(strip(l2["cells"])[2:10] == EXPECT["2"], f"未着手リーフ（実績=—）\n     {strip(l2['cells'])[2:10]}")

    # 派生・特殊表示の明示確認
    check(l12["noteHasLink"], "備考のURLが自動リンク化される")
    check("_ai" not in pg.inner_text("#leftRows") and "tokens" not in pg.inner_text("#leftRows"),
          "カスタムキー（_ai）は画面に出ない")

    b.close()
finish(errors)
