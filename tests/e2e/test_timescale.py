"""時間ビューの軸スケール切替（日/週/月）: 切替UI・永続化(wbsTimeScale)・週ヘッダの月曜始まり(端は部分週)・
   月ヘッダの年/暦月グルーピング(年境界・うるう年)・日精度を保った座標圧縮（バー/土日祝日/マイルストーン線）・
   リスケ履歴トレイルの継続表示（1日だけの変更でも消えない閾値の回帰）・i18n・全fixtureでの無クラッシュ。
   本日=CLOCK_PIN(2026-06-15=月曜)固定。WEEK_COL_W=70/MONTH_DAY_PX=2はwbs_viewer.html側の定数と一致させること。"""
import json
import pathlib
from datetime import date, timedelta
from playwright.sync_api import sync_playwright
from common import ROOT, VIEWER, CLOCK_PIN, check, finish, leaf, load_test_json, new_page

WEEK_COL_W = 70
DAY_PX_WEEK = WEEK_COL_W / 7   # =10
DAY_PX_DAY = 22
MONTH_DAY_PX = 2

def x(d, range_start, day_px):
    y, m, dd = map(int, d.split("-"))
    y0, m0, d0 = map(int, range_start.split("-"))
    return (date(y, m, dd) - date(y0, m0, d0)).days * day_px

def _parse(s):
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)

def daterange(d0, d1):
    for i in range((d1 - d0).days + 1):
        yield d0 + timedelta(days=i)

def month_groups(rs, re_):
    """独立実装のground truth: [(year, month, days), ...]（暦月でグルーピング。うるう年はdatetimeが自動解決）"""
    groups, cur_key, cur_n = [], None, 0
    for d in daterange(_parse(rs), _parse(re_)):
        key = (d.year, d.month)
        if key != cur_key:
            if cur_key is not None: groups.append((*cur_key, cur_n))
            cur_key, cur_n = key, 0
        cur_n += 1
    groups.append((*cur_key, cur_n))
    return groups

def year_groups(rs, re_):
    """独立実装のground truth: [(year, days), ...]（年でグルーピング）"""
    groups, cur_key, cur_n = [], None, 0
    for d in daterange(_parse(rs), _parse(re_)):
        if d.year != cur_key:
            if cur_key is not None: groups.append((cur_key, cur_n))
            cur_key, cur_n = d.year, 0
        cur_n += 1
    groups.append((cur_key, cur_n))
    return groups

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = new_page(b, viewport={"width": 1500, "height": 820})
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
    pg.goto(VIEWER)

    # ===== 1. 切替UI：時間タブでのみ表示・既定=日・クリックで切替（3ボタン：日/週/月） =====
    SIMPLE = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-10")]}]}
    pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)

    btns = pg.eval_on_selector_all(".tsc-btn", "els=>els.map(e=>({t:e.textContent,scale:e.dataset.scale,on:e.classList.contains('on')}))")
    check(len(btns) == 3, f"時間タブに日/週/月の3ボタン -> {btns}")
    check([b["scale"] for b in btns] == ["day", "week", "month"], f"ボタンの並び順=日/週/月 -> {btns}")
    check(btns[0] == {"t": "日", "scale": "day", "on": True}, f"既定は日がon -> {btns}")
    check(not btns[1]["on"] and not btns[2]["on"], f"週/月はoffで開始 -> {btns}")

    pg.click('.rtab[data-view="progress"]'); pg.wait_for_timeout(150)
    check(pg.eval_on_selector_all(".tsc-btn", "e=>e.length") == 0, "進捗タブでは日/週/月ボタンが消える")

    pg.click('.rtab[data-view="time"]'); pg.wait_for_timeout(150)
    on_after_tabswitch = pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale")
    check(on_after_tabswitch == "day", "時間タブに戻ってもスケールは保持(日のまま)")

    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)
    check(pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale") == "week", "週クリックでonが週へ移動")
    check(pg.evaluate("()=>localStorage.getItem('wbsTimeScale')") == "week", "wbsTimeScaleがlocalStorageへ保存(week)")

    pg.click('.tsc-btn[data-scale="month"]'); pg.wait_for_timeout(150)
    check(pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale") == "month", "月クリックでonが月へ移動")
    check(pg.evaluate("()=>localStorage.getItem('wbsTimeScale')") == "month", "wbsTimeScaleがlocalStorageへ保存(month)")

    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    check(pg.evaluate("()=>localStorage.getItem('wbsTimeScale')") == "day", "日へ戻すとlocalStorageも更新(day)")

    # ===== 2. リロードで復元（週・月それぞれ） =====
    for scale in ["week", "month"]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        pg.reload(); pg.wait_for_timeout(100)
        pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)
        check(pg.eval_on_selector(".tsc-btn.on", "e=>e.dataset.scale") == scale,
              f"リロード後もwbsTimeScale={scale}が復元される")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)   # 以降のテストは日から開始

    # ===== 3. 週ヘッダ：月曜始まり・端は部分週（rangeStartが水曜=非月曜のケース） =====
    HEADER_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", HEADER_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="week"]'); pg.wait_for_timeout(150)

    cells = pg.eval_on_selector_all("#dates .d", "els=>els.map(e=>({label:e.textContent.trim(), w:Math.round(parseFloat(e.style.width))}))")
    check([c["label"] for c in cells] == ["6/1", "6/8", "6/15", "6/22"],
          f"週セルは月曜始まりでグルーピング(端は部分週) -> {[c['label'] for c in cells]}")
    check([c["w"] for c in cells] == [50, 70, 70, 30],
          f"部分週の幅は実日数×10px(5/7/7/3日) -> {[c['w'] for c in cells]}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 3b. 月ヘッダ：年境界(2026→2027→2028)×2回・うるう年2月(29日)と平年2月(28日)の対比・端は部分月 =====
    # ps=TODAY(6/15=月曜、CLOCK_PIN)固定なのでrangeStartが確定する。pe=2028-03-15まで伸ばして年境界2回+2028うるう年Febを含める。
    RS_MONTH, RE_MONTH = "2026-06-15", "2028-03-15"
    HEADER_DATA_MONTH = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps=RS_MONTH, pe=RE_MONTH)]}]}
    pg.evaluate("d=>window.renderData(d)", HEADER_DATA_MONTH); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="month"]'); pg.wait_for_timeout(150)

    yr_cells = pg.eval_on_selector_all("#ym .seg", "els=>els.map(e=>({label:e.textContent.trim(), w:Math.round(parseFloat(e.style.width))}))")
    exp_yr = [(f"{y}年", n * MONTH_DAY_PX) for y, n in year_groups(RS_MONTH, RE_MONTH)]
    check([(c["label"], c["w"]) for c in yr_cells] == exp_yr,
          f"年セグメントが年境界(2026→2027→2028)で正しく分割 -> {[(c['label'],c['w']) for c in yr_cells]} exp={exp_yr}")

    mo_cells = pg.eval_on_selector_all("#dates .d", "els=>els.map(e=>({label:e.textContent.trim(), w:Math.round(parseFloat(e.style.width))}))")
    exp_mo = [(f"{m}月", n * MONTH_DAY_PX) for _, m, n in month_groups(RS_MONTH, RE_MONTH)]
    check([(c["label"], c["w"]) for c in mo_cells] == exp_mo,
          f"月セルが暦月でグルーピング(うるう年2028/02=29日・平年2027/02=28日を含む) -> "
          f"{[(c['label'],c['w']) for c in mo_cells]}\n     exp={exp_mo}")
    # 2027年2月(平年28日)・2028年2月(うるう年29日)の対比を明示確認
    feb27 = next(n for y, m, n in month_groups(RS_MONTH, RE_MONTH) if (y, m) == (2027, 2))
    feb28 = next(n for y, m, n in month_groups(RS_MONTH, RE_MONTH) if (y, m) == (2028, 2))
    check(feb27 == 28 and feb28 == 29, f"平年2月=28日・うるう年2月=29日(datetimeが自動解決) -> 2027/02={feb27} 2028/02={feb28}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 4. 日精度は保持（バー座標は週/月表示でも1日=dayPxで正確・丸め込みなし） =====
    GEOM_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "作業", ps="2026-06-03", pe="2026-06-10")]}]}
    pg.evaluate("d=>window.renderData(d)", GEOM_DATA); pg.wait_for_timeout(150)
    RS = "2026-06-03"   # planStart=TODAY(6/15)より前なのでrangeStart確定

    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    geo_day = pg.eval_on_selector(".bar.plan", "e=>({left:parseFloat(e.style.left), width:parseFloat(e.style.width)})")
    exp_day = {"left": x(RS, RS, DAY_PX_DAY), "width": (x("2026-06-10", RS, DAY_PX_DAY) - x(RS, RS, DAY_PX_DAY)) + DAY_PX_DAY}
    check(geo_day == exp_day, f"日表示のバー座標(基準) -> {geo_day} exp={exp_day}")

    for scale, day_px, label in [("week", DAY_PX_WEEK, "週"), ("month", MONTH_DAY_PX, "月")]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        geo = pg.eval_on_selector(".bar.plan", "e=>({left:parseFloat(e.style.left), width:parseFloat(e.style.width)})")
        exp = {"left": x(RS, RS, day_px), "width": (x("2026-06-10", RS, day_px) - x(RS, RS, day_px)) + day_px}
        check(geo == exp, f"{label}表示でも同じ日付が1日={day_px}pxで正確に配置(丸め込みなし) -> {geo} exp={exp}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 5. 土日/祝日オーバーレイ：件数不変・幅だけdayPxへ圧縮（日/週/月） =====
    HOL_DATA = {
        "holidays": ["2026-06-12"],
        "projects": [{"name": "P", "milestones": [], "tasks": [
            leaf("1", "作業", "佐藤", ps="2026-06-01", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", HOL_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    we_day = pg.eval_on_selector_all("#overlay rect.we", "els=>els.map(e=>+e.getAttribute('width'))")
    for scale, day_px, label in [("week", DAY_PX_WEEK, "週"), ("month", MONTH_DAY_PX, "月")]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        we = pg.eval_on_selector_all("#overlay rect.we", "els=>els.map(e=>+e.getAttribute('width'))")
        check(len(we_day) > 0 and len(we_day) == len(we),
              f"土日/祝日の列数は日/{label}で不変(日精度のまま) -> day={len(we_day)} {label}={len(we)}")
        check(all(w == day_px for w in we), f"矩形の幅が{label}表示ではdayPx={day_px}へ圧縮 -> {set(we)}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 6. マイルストーン線の座標も日精度で圧縮（週/月） =====
    MS_DATA = {"projects": [{"name": "P",
        "milestones": [{"date": "2026-06-20", "label": "リリース", "color": "#cc79a7"}],
        "tasks": [leaf("1", "作業", ps="2026-06-01", pe="2026-06-24")]}]}
    pg.evaluate("d=>window.renderData(d)", MS_DATA); pg.wait_for_timeout(150)
    for scale, day_px, label in [("week", DAY_PX_WEEK, "週"), ("month", MONTH_DAY_PX, "月")]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        ms_x = pg.eval_on_selector("#overlay line", "e=>+e.getAttribute('x1')")
        exp_ms_x = x("2026-06-20", "2026-06-01", day_px) + day_px / 2
        check(ms_x == exp_ms_x, f"マイルストーン線xも{label}表示でdayPx基準の日精度 -> {ms_x} exp={exp_ms_x}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 7. リスケ履歴トレイルは週/月表示でも消えない =====
    rs_data = load_test_json("正常_リスケ履歴.json")
    pg.evaluate("d=>window.renderData(d)", rs_data); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    trail_day = pg.eval_on_selector_all(".rs-seg", "e=>e.length")
    for scale, label in [("week", "週"), ("month", "月")]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        trail = pg.eval_on_selector_all(".rs-seg", "e=>e.length")
        check(trail_day > 0 and trail_day == trail, f"リスケトレイルの本数が日/{label}で不変(消えない) -> day={trail_day} {label}={trail}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 7b. リスケ閾値の回帰テスト（重要）：1日だけの予定変更でも、月表示(dayPx=2<旧閾値3)で消えないこと =====
    ONE_DAY_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [{
        "id": "1", "name": "1日だけ変更", "qty": 1, "hours": 8, "assignee": "",
        "plan": {"start": "2026-06-01", "end": "2026-06-21"},
        "actual": {"start": None, "end": None}, "note": "",
        "_planLog": [{"at": "2026-06-01T00:00:00Z",
                      "from": {"start": "2026-06-01", "end": "2026-06-20"},
                      "to": {"start": "2026-06-01", "end": "2026-06-21"},
                      "by": "manual", "reason": "1日だけ後ろ倒し"}]
    }]}]}
    pg.evaluate("d=>window.renderData(d)", ONE_DAY_DATA); pg.wait_for_timeout(150)
    for scale, day_px, label in [("day", DAY_PX_DAY, "日"), ("week", DAY_PX_WEEK, "週"), ("month", MONTH_DAY_PX, "月")]:
        pg.click(f'.tsc-btn[data-scale="{scale}"]'); pg.wait_for_timeout(150)
        n = pg.eval_on_selector_all(".rs-seg", "e=>e.length")
        check(n == 1, f"1日だけの予定変更でも{label}表示(dayPx={day_px})でトレイルが消えない(旧閾値3px固定だと月表示で消えていたバグの回帰) -> {n}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)

    # ===== 8. i18n（ja/en両方でラベルが揃う。年/月ラベルも確認） =====
    pg.click("#langBtn"); pg.wait_for_timeout(100)
    pg.evaluate("d=>window.renderData(d)", SIMPLE); pg.wait_for_timeout(150)
    en_labels = pg.eval_on_selector_all(".tsc-btn", "els=>els.map(e=>e.textContent)")
    check(en_labels == ["Day", "Week", "Month"], f"英語UIでは Day/Week/Month -> {en_labels}")

    EN_YM_DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
        leaf("1", "task", ps="2026-06-01", pe="2026-07-15")]}]}
    pg.evaluate("d=>window.renderData(d)", EN_YM_DATA); pg.wait_for_timeout(150)
    pg.click('.tsc-btn[data-scale="month"]'); pg.wait_for_timeout(150)
    en_yr = pg.eval_on_selector("#ym .seg", "e=>e.textContent.trim()")
    en_mo = pg.eval_on_selector_all("#dates .d", "els=>els.map(e=>e.textContent.trim())")
    check(en_yr == "2026", f"英語の年ラベルは接尾辞なし -> {en_yr!r}")
    check(en_mo == ["Jun", "Jul"], f"英語の月ラベルは短縮月名 -> {en_mo}")
    pg.click('.tsc-btn[data-scale="day"]'); pg.wait_for_timeout(150)
    pg.click("#langBtn"); pg.wait_for_timeout(100)   # 日本語へ戻す

    # ===== 9. 全fixtureを週/月表示で開いてもクラッシュ/NaN無し（test_corpus.pyの週/月表示版） =====
    FIXTURES = sorted((ROOT / "tests").glob("正常_*.json")) + sorted((ROOT / "tests").glob("異常_*.json"))
    for scale in ["week", "month"]:
        pg.evaluate("s=>localStorage.setItem('wbsTimeScale',s)", scale)
        pg.reload(); pg.wait_for_timeout(100)
        for fx in FIXTURES:
            before = len(errors)
            pg.evaluate("d=>window.renderData(d)", json.loads(fx.read_text(encoding="utf-8")))
            pg.wait_for_timeout(120)
            body_nan = pg.evaluate("()=>document.body.innerText.includes('NaN')")
            poly = pg.evaluate("""()=>{const o=document.querySelector('#overlay polyline');
                if(!o)return false; return (o.getAttribute('points')||'').includes('NaN');}""")
            check(len(errors) == before and not body_nan and not poly, f"{scale}表示でも no-crash/no-NaN: {fx.name}")

    b.close()
finish(errors)
