"""時間ビューの軸スケール切替（日/週）: 切替UI・永続化(wbsTimeScale)・週ヘッダの月曜始まり(端は部分週)・
   日精度を保った座標圧縮（バー/土日祝日/マイルストーン線）・リスケ履歴トレイルの継続表示・i18n・全fixtureでの無クラッシュ。
   本日=CLOCK_PIN(2026-06-15=月曜)固定。WEEK_COL_W=70はwbs_viewer.html側の定数と一致させること（週1列=70px→1日=10px）。"""
import json
import pathlib
from datetime import date
from playwright.sync_api import sync_playwright
from common import ROOT, VIEWER, CLOCK_PIN, check, finish, leaf, load_test_json, new_page

WEEK_COL_W = 70
DAY_PX_WEEK = WEEK_COL_W / 7   # =10
DAY_PX_DAY = 22

def x(d, range_start, day_px):
    y, m, dd = map(int, d.split("-"))
    y0, m0, d0 = map(int, range_start.split("-"))
    return (date(y, m, dd) - date(y0, m0, d0)).days * day_px

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 820})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
    pg.goto(VIEWER)

    # ===== 1. 切替UI：時間タブでのみ表示・既定=日・クリックで切替 =====
    SIMPLE = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-10")]}]}
    pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)

    btns = pg.eval_on_selector_all(".tsc-btn", "els=>els.map(e=>({t:e.textContent,scale:e.dataset.scale,on:e.classList.contains('on')}))")
    check(len(btns) == 2, f"時間タブに日/週の2ボタン -> {btns}")
    check(btns[0] == {"t": "日", "scale": "day", "on": True} and btns[1]["scale"] == "week" and not btns[1]["on"],
          f"既定は日がon -> {btns}")

    pg.click('.rtab[data-view="progress"]'); pg.wait_for_timeout(150)
    check(pg.eval_on_selector_all(".tsc-btn", "e=>e.length") == 0, "進捗タブでは日/週ボタンが消える")

    pg.click('.rtab[data-view="time"]'); pg.wait_for_timeout(150)
    on_after_tabswitch = pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale")
    check(on_after_tabswitch == "day", "時間タブに戻ってもスケールは保持(日のまま)")

    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    check(pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale") == "week", "週クリックでonが週へ移動")
    check(pg.evaluate("()=>localStorage.getItem('wbsTimeScale')") == "week", "wbsTimeScaleがlocalStorageへ保存(week)")

    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    check(pg.evaluate("()=>localStorage.getItem('wbsTimeScale')") == "day", "日へ戻すとlocalStorageも更新(day)")

    # ===== 2. リロードで復元 =====
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    pg.reload(); pg.wait_for_timeout(100)
    pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)
    check(pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale") == "week", "リロード後もwbsTimeScale=weekが復元される")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)   # 以降のテストは日から開始

    # ===== 3. 週ヘッダ：月曜始まり・端は部分週（rangeStartが水曜=非月曜のケース） =====
    # plan 6/3(水)〜6/24(水)・実績なし。TODAY(6/15)は範囲内なのでrangeStartは動かない。
    # 期待週セル: 6/1(5日=水〜日) / 6/8(7日) / 6/15(7日) / 6/22(3日=月〜水)
    HEADER_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", HEADER_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)

    cells = pg.eval_on_selector_all("#dates .d", "els=>els.map(e=>({label:e.textContent.trim(), w:Math.round(parseFloat(e.style.width))}))")
    check([c["label"] for c in cells] == ["6/1", "6/8", "6/15", "6/22"],
          f"週セルは月曜始まりでグルーピング(端は部分週) -> {[c['label'] for c in cells]}")
    check([c["w"] for c in cells] == [50, 70, 70, 30],
          f"部分週の幅は実日数×10px(5/7/7/3日) -> {[c['w'] for c in cells]}")

    # ===== 4. 日精度は保持（バー座標は週表示でも1日=10pxで正確） =====
    GEOM_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-10")]}]}
    pg.evaluate("d=>window.renderData(d)", GEOM_DATA); pg.wait_for_timeout(150)
    RS = "2026-06-03"   # planStart=TODAY(6/15)より前なのでrangeStart確定

    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    geo_day = pg.eval_on_selector(".bar.plan", "e=>({left:parseFloat(e.style.left), width:parseFloat(e.style.width)})")
    exp_day = {"left": x(RS, RS, DAY_PX_DAY), "width": (x("2026-06-10", RS, DAY_PX_DAY) - x(RS, RS, DAY_PX_DAY)) + DAY_PX_DAY}
    check(geo_day == exp_day, f"日表示のバー座標(基準) -> {geo_day} exp={exp_day}")

    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    geo_week = pg.eval_on_selector(".bar.plan", "e=>({left:parseFloat(e.style.left), width:parseFloat(e.style.width)})")
    exp_week = {"left": x(RS, RS, DAY_PX_WEEK), "width": (x("2026-06-10", RS, DAY_PX_WEEK) - x(RS, RS, DAY_PX_WEEK)) + DAY_PX_WEEK}
    check(geo_week == exp_week, f"週表示でも同じ日付が1日=10pxで正確に配置(丸め込みなし) -> {geo_week} exp={exp_week}")

    # ===== 5. 土日/祝日オーバーレイ：件数不変・幅だけdayPxへ圧縮 =====
    HOL_DATA = {
        "holidays": ["2026-06-12"],
        "projects": [{"name": "P", "milestones": [], "tasks": [
            leaf("1", "作業", "佐藤", ps="2026-06-01", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", HOL_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    we_day = pg.eval_on_selector_all("#overlay rect.we", "els=>els.map(e=>+e.getAttribute('width'))")
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    we_week = pg.eval_on_selector_all("#overlay rect.we", "els=>els.map(e=>+e.getAttribute('width'))")
    check(len(we_day) > 0 and len(we_day) == len(we_week),
          f"土日/祝日の列数は日/週で不変(日精度のまま) -> day={len(we_day)} week={len(we_week)}")
    check(all(w == DAY_PX_DAY for w in we_day) and all(w == DAY_PX_WEEK for w in we_week),
          f"矩形の幅だけdayPxへ圧縮 -> day={set(we_day)} week={set(we_week)}")

    # ===== 6. マイルストーン線の座標も日精度で圧縮 =====
    MS_DATA = {"projects": [{"name": "P",
        "milestones": [{"date": "2026-06-20", "label": "リリース", "color": "#cc79a7"}],
        "tasks": [leaf("1", "作業", ps="2026-06-01", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", MS_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    ms_x = pg.eval_on_selector("#overlay line", "e=>+e.getAttribute('x1')")
    exp_ms_x = x("2026-06-20", "2026-06-01", DAY_PX_WEEK) + DAY_PX_WEEK / 2
    check(ms_x == exp_ms_x, f"マイルストーン線xも週表示でdayPx基準の日精度 -> {ms_x} exp={exp_ms_x}")

    # ===== 7. リスケ履歴トレイルは週表示でも消えない =====
    rs_data = load_test_json("正常_リスケ履歴.json")
    pg.evaluate("d=>window.renderData(d)", rs_data); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    trail_day = pg.eval_on_selector_all(".rs-seg", "e=>e.length")
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    trail_week = pg.eval_on_selector_all(".rs-seg", "e=>e.length")
    check(trail_day > 0 and trail_day == trail_week,
          f"リスケトレイルの本数が日/週で不変(消えない) -> day={trail_day} week={trail_week}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 8. i18n（ja/en両方でラベルが揃う） =====
    pg.click("#langBtn"); pg.wait_for_timeout(100)
    pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)
    en_labels = pg.eval_on_selector_all(".tsc-btn", "els=>els.map(e=>e.textContent)")
    check(en_labels == ["Day", "Week"], f"英語UIでは Day/Week -> {en_labels}")
    pg.click("#langBtn"); pg.wait_for_timeout(100)   # 日本語へ戻す

    # ===== 9. 全fixtureを週表示で開いてもクラッシュ/NaN無し（test_corpus.pyの週表示版） =====
    FIXTURES = sorted((ROOT / "tests").glob("正常_*.json")) + sorted((ROOT / "tests").glob("異常_*.json"))
    pg.evaluate("()=>localStorage.setItem('wbsTimeScale','week')")
    pg.reload(); pg.wait_for_timeout(100)
    for fx in FIXTURES:
        before = len(errors)
        pg.evaluate("d=>window.renderData(d)", json.loads(fx.read_text(encoding="utf-8")))
        pg.wait_for_timeout(120)
        body_nan = pg.evaluate("()=>document.body.innerText.includes('NaN')")
        poly = pg.evaluate("""()=>{const o=document.querySelector('#overlay polyline');
            if(!o)return false; return (o.getAttribute('points')||'').includes('NaN');}""")
        check(len(errors) == before and not body_nan and not poly, f"週表示でも no-crash/no-NaN: {fx.name}")

    b.close()
finish(errors)
