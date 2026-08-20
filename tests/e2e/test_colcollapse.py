"""列折りたたみ（アウトライン式 +/−）：トグルが折りたたみ単位ぶん出る／畳むと列が消えて左が縮む（隙間なし）／+で復元。
常時表示列（No.・作業項目・工数）はトグルを持たない。"""
from playwright.sync_api import sync_playwright
from common import VIEWER, check, finish, leaf, granted_handle_init, new_page

DATA = {"projects": [{"name": "P1", "milestones": [],
        "tasks": [{"id": "1", "name": "工程", "children": [
            leaf("1.1", "作業A", ps="2026-06-01", pe="2026-06-05", asg="ぴぐお")]}]}]}

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 400})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script(granted_handle_init(DATA))
    pg.goto(VIEWER)
    pg.click("#openBtn"); pg.wait_for_timeout(200)

    # 折りたたみ単位＝7（数量時間/進捗/状況/担当/予定/実績/備考）。No.・作業項目・工数は対象外
    units = pg.evaluate("()=>[...document.querySelectorAll('.htab-sp .ctglb')].map(b=>b.getAttribute('data-colcol'))")
    check(set(filter(None, units)) == {"qh", "work", "prog", "stat", "asg", "plan", "act", "note"},
          f"折りたたみトグルは8単位 -> {units}")

    # 列表示プリセット(#16)：3モードが出る・モード適用は決定論的に colCollapsed を再構築
    nPreset = pg.eval_on_selector_all('#filterBar [data-colpreset]', "e=>e.length")
    check(nPreset == 3, f"列表示プリセットは3ボタン -> {nPreset}")
    pg.click('#filterBar [data-colpreset="standard"]'); pg.wait_for_timeout(120)
    std = set(pg.evaluate("()=>JSON.parse(localStorage.getItem('wbsColCollapsed')||'[]')"))
    check(std == {"qh", "prog", "stat", "note"}, f"標準=数量時間/進捗/状況/備考を畳む -> {sorted(std)}")
    check(pg.evaluate("()=>localStorage.getItem('wbsColPreset')") == "standard", "標準モードが保存される")

    pg.click('#filterBar [data-colpreset="full"]'); pg.wait_for_timeout(120)
    full = pg.evaluate("()=>JSON.parse(localStorage.getItem('wbsColCollapsed')||'[]')")
    check(full == [], f"フル=全列表示（畳みなし） -> {full}")

    pg.click('#filterBar [data-colpreset="gantt"]'); pg.wait_for_timeout(120)
    gantt = set(pg.evaluate("()=>JSON.parse(localStorage.getItem('wbsColCollapsed')||'[]')"))
    check(gantt == {"qh", "work", "prog", "stat", "asg", "plan", "act", "note"},
          f"ガント優先=情報列を全畳み -> {sorted(gantt)}")
    # プリセット適用後も +/− 微調整可。手動操作したら custom に落ちる
    pg.click('.htab-sp .ctglb[data-colexp="note"]'); pg.wait_for_timeout(120)
    check(pg.evaluate("()=>localStorage.getItem('wbsColPreset')") == "custom", "手動の+操作でモード表示はcustomに落ちる")
    pg.click('#filterBar [data-colpreset="full"]'); pg.wait_for_timeout(120)  # 既存ケース開始前に全列表示へ戻す

    w0 = pg.evaluate("()=>Math.round(document.getElementById('left').getBoundingClientRect().width)")
    notes0 = pg.evaluate("()=>document.querySelectorAll('#leftRows .c.note').length")
    check(notes0 > 0, "畳む前は備考セルがある")

    # 備考を畳む -> 備考列が消える・左が縮む・隙間スタブは無い・+ が出る
    pg.click(".htab-sp .ctglb[data-colcol='note']"); pg.wait_for_timeout(150)
    check(len(errors) == 0, f"畳んでもJSエラー無し -> {errors}")
    w1 = pg.evaluate("()=>Math.round(document.getElementById('left').getBoundingClientRect().width)")
    check(w1 < w0, f"畳むと左表が縮む ({w0}->{w1})")
    check(pg.evaluate("()=>document.querySelectorAll('#leftRows .c.note').length") == 0, "備考列が消える")
    check(pg.evaluate("()=>document.querySelectorAll('.colstub').length") == 0, "グレーの隙間スタブは無い（アウトライン式＝0幅）")
    check(pg.evaluate("()=>!!document.querySelector(\".htab-sp .ctglb[data-colexp='note']\")"), "備考に + (再展開)が出る")

    # + で復元
    pg.click(".htab-sp .ctglb[data-colexp='note']"); pg.wait_for_timeout(150)
    w2 = pg.evaluate("()=>Math.round(document.getElementById('left').getBoundingClientRect().width)")
    check(w2 == w0, f"+で元の幅に復元 ({w2}=={w0})")
    check(pg.evaluate("()=>document.querySelectorAll('#leftRows .c.note').length") > 0, "備考列が戻る")

    b.close()
finish(errors)
