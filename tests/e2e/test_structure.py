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

    # --- クリックで依存の連鎖をハイライト（矢印描画の軽量代替） ---
    errors.clear()
    DATA_CHAIN = load_test_json("正常_クリティカルパス.json")
    pg.evaluate("d=>window.renderData(d)", DATA_CHAIN); pg.wait_for_timeout(150)
    pg.click(".rtab[data-view='structure']"); pg.wait_for_timeout(150)

    def bar_classes(pg):
        return pg.evaluate("""()=>Object.fromEntries([...document.querySelectorAll('#strows .bar.struct[data-id]')]
          .map(b=>[b.getAttribute('data-id'), [...b.classList].filter(c=>['sel','pred','succ','faded'].includes(c))]))""")

    check(pg.locator("#strows .bar.struct[data-id='1.3']").count() == 1, "リーフのバーにdata-idが付く")

    tip13 = pg.get_attribute("#strows .bar.struct[data-id='1.3']", "title")
    check("1.1" in tip13 and "1.4" in tip13, f"ツールチップに先行/後続idが出る -> {tip13!r}")

    pg.click("#strows .bar.struct[data-id='1.3']"); pg.wait_for_timeout(100)
    cls = bar_classes(pg)
    check(cls["1.3"] == ["sel"], f"クリックしたタスク自身はsel -> {cls['1.3']}")
    check(cls["1.1"] == ["pred"], f"直接の先行はpred -> {cls['1.1']}")
    check(cls["1.4"] == ["succ"], f"直接の後続はsucc -> {cls['1.4']}")
    check(cls["1.2"] == ["faded"], f"依存関係の無いタスク(兄弟)はfaded -> {cls['1.2']}")
    check(len(errors) == 0, f"クリック後もJSエラー無し -> {errors}")

    pg.click("#strows .bar.struct[data-id='1.3']"); pg.wait_for_timeout(100)
    cls2 = bar_classes(pg)
    check(all(v == [] for v in cls2.values()), f"同じバーの再クリックで全解除される -> {cls2}")

    pg.click("#strows .bar.struct[data-id='1.4']"); pg.wait_for_timeout(100)
    cls3 = bar_classes(pg)
    check(cls3["1.4"] == ["sel"] and set(cls3["1.1"]+cls3["1.2"]+cls3["1.3"]) == {"pred"},
          f"別のタスクをクリックすると選択が切り替わる（1.4は1.1/1.2/1.3すべてに間接的に依存） -> {cls3}")

    # 新規ファイル読込ではない再描画（状態フィルタのトグル）を挟んでも選択状態が保たれ、新しいDOMへ再適用されること
    pg.click("#stateFilter .sf-btn[data-state='todo']"); pg.wait_for_timeout(150)  # render(lastData)を誘発（isNewではない）
    pg.click("#stateFilter .sf-btn[data-state='todo']"); pg.wait_for_timeout(150)  # 元に戻す
    cls4 = bar_classes(pg)
    check(cls4["1.4"] == ["sel"], f"データ再読込を伴わない再描画では選択状態が保たれる -> {cls4['1.4']}")

    # --- Copilot相当のセルフレビューで見つかった2件の回帰確認 ---
    # 1) 他タブ（時間ビュー）でのクリックが構造タブの選択状態を巻き込んで消さないこと
    pg.click("#strows .bar.struct[data-id='1.3']"); pg.wait_for_timeout(100)  # 選択し直す
    pg.click(".rtab[data-view='time']"); pg.wait_for_timeout(150)
    pg.click("#grows"); pg.wait_for_timeout(150)                              # 時間ビューのガント領域をクリック
    pg.click(".rtab[data-view='structure']"); pg.wait_for_timeout(150)
    cls5 = bar_classes(pg)
    check(cls5["1.3"] == ["sel"], f"他タブでのクリックを挟んでも構造タブの選択状態は保たれる -> {cls5}")

    # 2) フィルタで非表示になった先行/後続タスクのidがツールチップに残らないこと
    pg.click(".asg-dd > summary"); pg.wait_for_timeout(150)                   # 担当フィルタを開く（1.1=田中/1.4=田中/1.3=鈴木）
    pg.click(".asg-cb[data-asg='田中']"); pg.wait_for_timeout(200)             # 田中(=1.1と1.4)を非表示に
    check(pg.locator("#strows .bar.struct[data-id='1.1']").count() == 0, "担当フィルタで1.1のバーが非表示になる")
    tip13_filtered = pg.get_attribute("#strows .bar.struct[data-id='1.3']", "title") or ""
    check("1.1" not in tip13_filtered and "1.4" not in tip13_filtered,
          f"非表示の先行/後続はツールチップから除外される -> {tip13_filtered!r}")
    pg.click(".asg-cb[data-asg='田中']"); pg.wait_for_timeout(200)             # 元に戻す
    tip13_restored = pg.get_attribute("#strows .bar.struct[data-id='1.3']", "title") or ""
    check("1.1" in tip13_restored and "1.4" in tip13_restored,
          f"フィルタを解除するとツールチップも復元される -> {tip13_restored!r}")

    check(len(errors) == 0, f"一連の操作でJSエラー無し -> {errors}")
    b.close()

finish(errors)
