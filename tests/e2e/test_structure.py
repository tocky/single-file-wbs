"""構造ビュー（依存関係/クリティカルパス・#66）: _deps からのCP計算（トポロジカルソート＋最長路）が
   期待どおりハイライトされること・循環依存等の壊れた入力でもクラッシュしないこと・3つ目のタブとして
   切替できることを確認する。"""
from playwright.sync_api import sync_playwright
from common import VIEWER, check, finish, load_test_json, new_page


def struct_rows(pg):
    return pg.evaluate("""()=>[...document.querySelectorAll('#strows > .grow')].map(g=>({
      cls:[...g.classList].join(' '),
      crit:!!g.querySelector('.bar.struct.crit'),
      dim:!!g.querySelector('.bar.struct.dim'),
    }))""")


errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 900})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(VIEWER)

    # --- 3つ目のタブとして切替できること ---
    DATA_EMPTY = load_test_json("正常_クリティカルパス.json")
    pg.evaluate("d=>window.renderData(d)", DATA_EMPTY); pg.wait_for_timeout(150)
    check(pg.locator(".rtab[data-view='structure']").count() == 1, "「構造」タブのボタンが存在する")
    pg.click(".rtab[data-view='structure']"); pg.wait_for_timeout(150)
    check("on" in (pg.get_attribute(".rtab[data-view='structure']", "class") or ""), "クリックでアクティブになる")
    check(pg.locator("#strows").count() == 1, "#strowsがDOMに注入される")
    check(len(errors) == 0, f"タブ切替でJSエラー無し -> {errors}")

    # --- 正常系：分岐する依存チェーン（短い枝=非クリティカル／長い枝=クリティカル） ---
    # 行順序: [0]プロジェクト行 [1]工程(親) [2]1.1 [3]1.2(短い枝) [4]1.3(長い枝) [5]1.4
    rows = struct_rows(pg)
    check(len(rows) == 6, f"行数が期待どおり(6) -> {len(rows)}")
    expect_crit = [True, True, True, False, True, True]  # proj/親/1.1/1.2/1.3/1.4
    got_crit = [r["crit"] for r in rows]
    check(got_crit == expect_crit,
          f"長い枝(1.1→1.3→1.4)だけがクリティカル・短い枝(1.2)は非クリティカル -> {got_crit} (期待 {expect_crit})")
    check(rows[3]["dim"] and not rows[3]["crit"], "非クリティカル行はdimクラス")
    check(rows[1]["crit"] and rows[0]["crit"], "配下にクリティカルなリーフがあれば親・プロジェクト行にも伝播する")

    cpinfo = pg.inner_text("#cpinfo")
    check("25" in cpinfo and "3" in cpinfo, f"#cpinfoに合計日数(25)と件数(3)が出る -> {cpinfo!r}")

    # --- 異常系：自己参照・存在しないid参照・非配列・循環依存でクラッシュしないこと ---
    errors.clear()
    DATA_BROKEN = load_test_json("異常_依存関係.json")
    pg.evaluate("d=>window.renderData(d)", DATA_BROKEN); pg.wait_for_timeout(150)
    pg.click(".rtab[data-view='structure']"); pg.wait_for_timeout(150)
    check(len(errors) == 0, f"壊れたJSONを読み込んでもJSエラー無し -> {errors}")

    rows2 = struct_rows(pg)
    # 行順序: [0]proj [1]工程(親) [2]1.1(自己参照) [3]1.2(不正id参照) [4]1.3(非配列)
    #         [5]2.1 [6]2.2 [7]2.3(循環) [8]3.1(独立・最長10日)
    check(len(rows2) == 9, f"行数が期待どおり(9) -> {len(rows2)}")
    cyclic_crit = [rows2[5]["crit"], rows2[6]["crit"], rows2[7]["crit"]]
    check(cyclic_crit == [False, False, False], f"循環依存のタスクはクリティカル判定されない -> {cyclic_crit}")
    broken_deps_crit = [rows2[2]["crit"], rows2[3]["crit"], rows2[4]["crit"]]
    check(broken_deps_crit == [False, False, False],
          f"自己参照/不正id参照/非配列は依存無しとして扱われ、それだけではクリティカルにならない -> {broken_deps_crit}")
    check(rows2[8]["crit"], "循環と無関係の独立タスク(3.1)はCP計算の対象として扱われる")

    nan_check = pg.evaluate("""()=>document.getElementById('cpinfo').textContent.includes('NaN')""")
    check(not nan_check, "#cpinfoにNaNが出ない")

    check(len(errors) == 0, f"一連の操作でJSエラー無し -> {errors}")
    b.close()

finish(errors)
