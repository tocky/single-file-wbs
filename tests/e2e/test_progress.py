"""進捗2軸ビュー（#63 段階2）: 進捗ステッパー±10%・量子化/優先/フォールバック・
   状況列(遅/実/予=EVM SV/EV/PV)・予定終了の締切超過=赤・進捗タブ切替（時間↔進捗で右ペインが入替）。
   本日は CLOCK_PIN=2026-06-15 固定（PV/フォールバックを決定論計算）。"""
import json
from playwright.sync_api import sync_playwright
from common import VIEWER, CLOCK_PIN, granted_handle_init, check, finish

DATA = {"projects": [{"name": "P", "milestones": [], "tasks": [
    {"id": "1", "name": "工程", "children": [
        # override: _progress=40・PV=50(10/20)→slip=10。状況=10/40/50
        {"id": "1.1", "name": "override", "qty": 1, "hours": 8,
         "plan": {"start": "2026-06-05", "end": "2026-06-25"}, "actual": {"start": "2026-06-05", "end": None}, "_progress": 40, "note": ""},
        # quantize: _progress=73→70・PV=48→slip=0→実績のみ
        {"id": "1.2", "name": "quantize", "qty": 1, "hours": 8,
         "plan": {"start": "2026-06-01", "end": "2026-06-30"}, "actual": {"start": "2026-06-01", "end": None}, "_progress": 73, "note": ""},
        # fallback: _progress無→EV=PV=50→slip0
        {"id": "1.3", "name": "fallback", "qty": 1, "hours": 8,
         "plan": {"start": "2026-06-10", "end": "2026-06-20"}, "actual": {"start": "2026-06-10", "end": None}, "note": ""},
        # 締切超過＋遅れ: _progress=60・plan終了06-10<本日・PV=100→slip=40・pe赤
        {"id": "1.4", "name": "overdue", "qty": 1, "hours": 8,
         "plan": {"start": "2026-06-05", "end": "2026-06-10"}, "actual": {"start": "2026-06-05", "end": None}, "_progress": 60, "note": ""},
        # 未着手・未到来: EV0・PV0・slip0・pe赤でない
        {"id": "1.5", "name": "future", "qty": 1, "hours": 8,
         "plan": {"start": "2026-06-20", "end": "2026-06-25"}, "actual": {"start": None, "end": None}, "note": ""},
    ]}
]}]}

# 行名→{prog,stat,overdue}。状況はflexで innerText に改行が入るため textContent。overdueは pe のみに付く
READ = """name=>{for(const r of document.querySelectorAll('#leftRows .lrow')){
  const nm=(r.querySelector('.c.name')||{}).innerText||'';
  if(nm.includes(name)){const v=r.querySelector('.c.prog .v'),s=r.querySelector('.c.stat');
    return {prog:v?v.innerText:'',stat:s?s.textContent:'',overdue:!!r.querySelector('.c.overdue')};}}
  return null;}"""

errors = []
with sync_playwright() as p:
    b = p.chromium.launch()
    # --- 表示（time既定）：進捗%・状況・予定終了の赤 ---
    pg = b.new_page(viewport={"width": 1500, "height": 600})
    pg.add_init_script(CLOCK_PIN)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(VIEWER); pg.evaluate("d => window.renderData(d)", DATA); pg.wait_for_timeout(200)
    def row(nm): return pg.evaluate(READ, nm)
    o = row("override"); check(o["prog"] == "40%" and o["stat"] == "10/40/50", f"override: 40%・状況10/40/50（得 {o}）")
    q = row("quantize"); check(q["prog"] == "70%" and q["stat"] == "70", f"quantize: 73→70%・遅れ無=実績のみ（得 {q}）")
    f = row("fallback"); check(f["prog"] == "50%" and f["stat"] == "50", f"fallback: 時間ベース50%・slip0（得 {f}）")
    d = row("overdue"); check(d["prog"] == "60%" and d["stat"] == "40/60/100" and d["overdue"], f"overdue: 60%・40/60/100・予定終了=赤（得 {d}）")
    u = row("future"); check(u["prog"] == "0%" and u["stat"] == "0" and not u["overdue"], f"future: 0%・slip0・赤でない（得 {u}）")

    # --- 進捗タブ：切替で右ペインが入替（両方同時描画しない）---
    has = lambda sel: pg.evaluate(f"()=>!!document.querySelector('{sel}')")
    check(has("#grows") and not has("#progbody"), "時間タブ: ガント(#grows)あり・進捗(#progbody)なし")
    pg.click('.rtab[data-view="progress"]'); pg.wait_for_timeout(200)
    check(has("#progbody") and not has("#grows"), "進捗タブ: 進捗(#progbody)あり・ガント(#grows)なし（同時描画しない）")
    nbar = pg.evaluate("()=>document.querySelectorAll('#progbody .pbar.short').length")
    check(nbar >= 2, f"進捗バー: 遅れ(赤)不足分が複数行に出る（得 {nbar}）")
    pg.close()

    # --- 編集：ステッパー±10%・着手日自動・0%維持 ---
    ep = b.new_page(viewport={"width": 1500, "height": 600})
    ep.add_init_script(CLOCK_PIN); ep.add_init_script(granted_handle_init(DATA))
    ep.on("pageerror", lambda e: errors.append(str(e))); ep.on("dialog", lambda d: d.accept())
    ep.goto(VIEWER); ep.click("#openBtn"); ep.wait_for_timeout(150); ep.click("#editBtn"); ep.wait_for_timeout(250)

    def leaf(i):
        kids = json.loads(ep.evaluate("()=>window.__file"))["projects"][0]["tasks"][0]["children"]
        return next(c for c in kids if c["id"] == i)
    def step(name, act):
        ep.evaluate("""([name,act])=>{for(const r of document.querySelectorAll('#leftRows .lrow')){
          if(((r.querySelector('.nm-in')||{}).value||'').includes(name)){r.querySelector(`.c.prog [data-act="${act}"]`).click();return;}}}""", [name, act])

    # future(未着手)を ▶ で10% → 着手日=今日
    step("future", "prog-inc"); ep.wait_for_timeout(550)
    n = leaf("1.5")
    check(n.get("_progress") == 10 and n.get("_progressBy") == "manual", f"▶で_progress=10・manual（得 {n.get('_progress')}）")
    check(n.get("actual", {}).get("start") == "2026-06-15", f"未着手→着手日に今日を自動セット（得 {n.get('actual', {}).get('start')}）")
    # ◀ で 0% → 着手日は残る
    step("future", "prog-dec"); ep.wait_for_timeout(550)
    n2 = leaf("1.5")
    check(n2.get("_progress") == 0, f"◀で0%（得 {n2.get('_progress')}）")
    check(n2.get("actual", {}).get("start") == "2026-06-15", f"0%でも着手日は残る（得 {n2.get('actual', {}).get('start')}）")

    b.close()
finish(errors)
