"""列幅ドラッグリサイズ（#12）：作業項目に加え、担当・備考もドラッグで幅調整でき、
ダブルクリックで既定幅に戻り、localStorageに永続化されることを確認する。
下限/上限クランプ・列折りたたみとの共存・作業項目列の既存動作（今回のリファクタ対象）の
回帰なしもあわせて確認する。"""
from playwright.sync_api import sync_playwright
from common import VIEWER, check, finish, leaf, granted_handle_init, new_page

DATA = {"projects": [{"name": "P1", "milestones": [],
        "tasks": [{"id": "1", "name": "工程", "children": [
            leaf("1.1", "作業A", ps="2026-06-01", pe="2026-06-05", asg="ぴぐお")]}]}]}
DATA["projects"][0]["tasks"][0]["children"][0]["note"] = "長めの備考テキストの例"

DEFAULTS = {"name": 200, "asg": 64, "note": 200}
RANGES = {"name": (100, 560), "asg": (40, 200), "note": (100, 640)}
LS_KEYS = {"name": "wbsNameW", "asg": "wbsAsgW", "note": "wbsNoteW"}


def handle_box(pg, key):
    return pg.query_selector(f'.colrs[data-colrs="{key}"]').bounding_box()


def header_w(pg, key):
    # inline style の width をそのまま読む（getBoundingClientRectはflexのサブピクセル丸めでずれることがあるため、
    # JSが実際に書き込んだ値そのものを検証対象にする）
    return pg.evaluate(f"()=>parseInt(document.querySelector('#leftHead .h.{key}').style.width,10)")


def drag(pg, key, dx):
    box = handle_box(pg, key)
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    pg.mouse.move(x + dx, y, steps=5)
    pg.mouse.up()
    pg.wait_for_timeout(200)


errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 400})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.add_init_script(granted_handle_init(DATA))
    pg.goto(VIEWER)
    pg.click("#openBtn"); pg.wait_for_timeout(200)

    # --- 担当・備考にもドラッグハンドルが出る ---
    for key in ("name", "asg", "note"):
        check(pg.locator(f'#leftHead .colrs[data-colrs="{key}"]').count() == 1, f"{key}列にドラッグハンドルがある")

    # --- 担当列：ドラッグで拡大 -> localStorage永続化 ---
    w0 = header_w(pg, "asg")
    check(w0 == DEFAULTS["asg"], f"担当列の初期幅は既定値 -> {w0}")
    drag(pg, "asg", 40)
    w1 = header_w(pg, "asg")
    check(w1 > w0, f"ドラッグで担当列が広がる ({w0}->{w1})")
    check(pg.evaluate("()=>localStorage.getItem('wbsAsgW')") == str(w1), "担当列の幅がlocalStorageに保存される")
    check(pg.evaluate("()=>parseInt(document.querySelector('#leftRows .lrow.leaf .c.asg').style.width,10)") == w1,
          "担当セルの幅もヘッダと一致")

    # --- 担当列：ダブルクリックで既定幅に戻る ---
    h = pg.query_selector('.colrs[data-colrs="asg"]')
    h.dblclick(); pg.wait_for_timeout(200)
    w2 = header_w(pg, "asg")
    check(w2 == DEFAULTS["asg"], f"ダブルクリックで担当列が既定幅に戻る -> {w2}")
    check(pg.evaluate("()=>localStorage.getItem('wbsAsgW')") == str(DEFAULTS["asg"]), "既定幅もlocalStorageに反映される")

    # --- 担当列：下限/上限クランプ ---
    drag(pg, "asg", -1000)
    check(header_w(pg, "asg") == RANGES["asg"][0], f"担当列は下限でクランプされる -> {header_w(pg,'asg')}")
    h = pg.query_selector('.colrs[data-colrs="asg"]'); h.dblclick(); pg.wait_for_timeout(150)  # 既定に戻す
    drag(pg, "asg", 1000)
    check(header_w(pg, "asg") == RANGES["asg"][1], f"担当列は上限でクランプされる -> {header_w(pg,'asg')}")
    h = pg.query_selector('.colrs[data-colrs="asg"]'); h.dblclick(); pg.wait_for_timeout(150)  # 既定に戻す

    # --- 備考列：ドラッグで拡大・ダブルクリックで既定幅・localStorage永続化 ---
    w0n = header_w(pg, "note")
    check(w0n == DEFAULTS["note"], f"備考列の初期幅は既定値 -> {w0n}")
    drag(pg, "note", 60)
    w1n = header_w(pg, "note")
    check(w1n > w0n, f"ドラッグで備考列が広がる ({w0n}->{w1n})")
    check(pg.evaluate("()=>localStorage.getItem('wbsNoteW')") == str(w1n), "備考列の幅がlocalStorageに保存される")
    hn = pg.query_selector('.colrs[data-colrs="note"]'); hn.dblclick(); pg.wait_for_timeout(200)
    check(header_w(pg, "note") == DEFAULTS["note"], "ダブルクリックで備考列が既定幅に戻る")

    # --- 作業項目列：既存動作の回帰確認（今回リファクタした共通ハンドラ経由） ---
    leftW0 = pg.evaluate("()=>parseInt(document.getElementById('left').style.width,10)")
    drag(pg, "name", 50)
    nameW1 = header_w(pg, "name")
    check(nameW1 == DEFAULTS["name"] + 50, f"作業項目列も引き続きドラッグで広がる -> {nameW1}")
    leftW1 = pg.evaluate("()=>parseInt(document.getElementById('left').style.width,10)")
    check(leftW1 == leftW0 + 50, f"#left全体の幅も作業項目列の変化ぶん追従する ({leftW0}->{leftW1})")
    hnm = pg.query_selector('.colrs[data-colrs="name"]'); hnm.dblclick(); pg.wait_for_timeout(200)
    check(header_w(pg, "name") == DEFAULTS["name"], "作業項目列もダブルクリックで既定幅に戻る")
    leftW2 = pg.evaluate("()=>parseInt(document.getElementById('left').style.width,10)")
    check(leftW2 == leftW0, f"#left全体の幅も既定幅リセットに追従して戻る ({leftW2}=={leftW0})")

    check(len(errors) == 0, f"一連のドラッグ操作でJSエラー無し -> {errors}")

    # --- 列の折りたたみとの共存：担当を畳んでも壊れず、展開後は再びリサイズできる ---
    pg.click(".htab-sp .ctglb[data-colcol='asg']"); pg.wait_for_timeout(150)
    check(len(errors) == 0, f"担当列を畳んでもJSエラー無し -> {errors}")
    check(pg.locator('#leftHead .colrs[data-colrs="asg"]').count() == 0, "畳むとハンドルごと消える")
    pg.click(".htab-sp .ctglb[data-colexp='asg']"); pg.wait_for_timeout(150)
    check(pg.locator('#leftHead .colrs[data-colrs="asg"]').count() == 1, "展開するとハンドルが戻る")
    w0r = header_w(pg, "asg")
    drag(pg, "asg", 30)
    check(header_w(pg, "asg") == w0r + 30, "展開後も担当列のリサイズが機能する")

    check(len(errors) == 0, f"折りたたみ+リサイズの一連の操作でJSエラー無し -> {errors}")

    # --- セルフレビューで見つかった2件の回帰確認 ---
    # 1) 保留中の遅延再描画（フィールド編集直後）の発火タイミング(350ms)をマウスボタンを押したまま跨いでも、
    #    liveElsが失効せずドラッグ追従が壊れない（mouseupより前に保留タイマーが発火するケースを直接再現する）
    pg.click("#editBtn"); pg.wait_for_timeout(200)
    note_in = pg.query_selector('#leftRows input[data-field="note"]')
    note_in.fill("編集した備考テキスト")
    note_in.evaluate("el=>el.blur()")  # change発火 -> deferRender()が350msの保留タイマーを仕込む
    pg.wait_for_timeout(50)  # タイマーが発火する前（<350ms）にドラッグを始める
    w0e = header_w(pg, "note")
    box = handle_box(pg, "note")
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y); pg.mouse.down()
    pg.mouse.move(x + 20, y, steps=3); pg.wait_for_timeout(100)   # ここまでで blur から約150ms（まだタイマー前）
    check(header_w(pg, "note") == w0e + 20, f"タイマー発火前は普通にドラッグ追従する -> {header_w(pg,'note')}")
    pg.wait_for_timeout(400)                                      # ここでblurから約550ms経過＝ボタンを押したまま保留タイマー(350ms)を跨ぐ
    check(len(errors) == 0, f"ドラッグ中に保留タイマーが発火してもJSエラー無し -> {errors}")
    pg.mouse.move(x + 40, y, steps=3); pg.wait_for_timeout(100)   # タイマー通過後もドラッグ追従が生きているか
    check(header_w(pg, "note") == w0e + 40, f"保留タイマーがドラッグ中に発火してもliveElsが失効せず追従し続ける -> {header_w(pg,'note')}")
    pg.mouse.up(); pg.wait_for_timeout(200)
    check(header_w(pg, "note") == w0e + 40, f"mouseup後も幅は確定どおり -> {header_w(pg,'note')}")
    hnote = pg.query_selector('.colrs[data-colrs="note"]'); hnote.dblclick(); pg.wait_for_timeout(200)  # 既定に戻す
    pg.click("#editBtn"); pg.wait_for_timeout(150)  # 編集モードOFF

    # 2) 列をまたいで連続でドラッグしても状態が食い違わない（再入防止ガード）
    hasg = pg.query_selector('.colrs[data-colrs="asg"]'); hasg.dblclick(); pg.wait_for_timeout(150)  # 両方を既定幅に揃えてから始める
    hnote2 = pg.query_selector('.colrs[data-colrs="note"]'); hnote2.dblclick(); pg.wait_for_timeout(150)
    asg0 = header_w(pg, "asg")
    drag(pg, "asg", 30)
    wasg = header_w(pg, "asg")
    check(wasg == asg0 + 30, f"担当列を先にドラッグすると期待どおり広がる -> {wasg}")
    note0 = header_w(pg, "note")
    drag(pg, "note", 50)
    wnote = header_w(pg, "note")
    check(wnote == note0 + 50, f"続けて備考列をドラッグしても備考列だけが広がる -> {wnote}")
    check(header_w(pg, "asg") == wasg, f"備考列をドラッグしても担当列の幅は食い違わずそのまま -> {header_w(pg,'asg')}")
    check(pg.evaluate("()=>localStorage.getItem('wbsAsgW')") == str(wasg), "連続ドラッグ後も担当列のlocalStorageが正しい")
    check(pg.evaluate("()=>localStorage.getItem('wbsNoteW')") == str(wnote), "連続ドラッグ後も備考列のlocalStorageが正しい")

    check(len(errors) == 0, f"セルフレビュー指摘の回帰確認でJSエラー無し -> {errors}")
    b.close()
finish(errors)
