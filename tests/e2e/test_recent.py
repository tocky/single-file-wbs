"""最近開いたファイル(#20)：IndexedDB に直近5件・新しい順・重複は先頭移動・再オープン・許可不可時の startIn ピッカー・消失・削除/クリア・永続・IDB不可

FileSystemFileHandle は IndexedDB に入れるため structured clone 可能な本物が要る（フェイクの関数付きオブジェクトは保存不可）。
file:// では OPFS が使えないので、このスイートだけローカル HTTP で配信し OPFS の本物ハンドルを使う（実ファイルには書かない）。
"""
import functools
import http.server
import json
import threading
from playwright.sync_api import sync_playwright
from common import ROOT, check, finish, leaf, new_page

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
handler.func.log_message = lambda *a, **k: None
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/wbs_viewer.html"

def data(name):
    return json.dumps({"projects": [{"name": name, "milestones": [],
        "tasks": [leaf("1", "A", ps="2026-06-01", pe="2026-06-05")]}]}, ensure_ascii=False)

NAMES = [f"f{i}.json" for i in range(1, 7)]

def items(pg):
    return pg.eval_on_selector_all("#recentList .rc-open", "els=>els.map(e=>e.textContent)")

def shown(pg, proj):
    return pg.evaluate("p=>document.getElementById('leftRows').innerText.includes(p)", proj)

def open_via_picker(pg, name):
    pg.evaluate("""async n=>{const d=await navigator.storage.getDirectory();const h=await d.getFileHandle(n);
      window.showOpenFilePicker=async()=>[h];}""", name)
    pg.click("#openBtn"); pg.wait_for_timeout(250)

def open_recent(pg, idx):
    pg.click("#recentSum"); pg.click(f'#recentList [data-rc="{idx}"]'); pg.wait_for_timeout(300)

errors, dialogs = [], []
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    pg.goto(URL)
    pg.evaluate("""async files=>{const d=await navigator.storage.getDirectory();
      for(const [n,txt] of files){const h=await d.getFileHandle(n,{create:true});const w=await h.createWritable();await w.write(txt);await w.close();}}""",
                [[n, data("P-" + n)] for n in NAMES])
    check(items(pg) == [] and pg.eval_on_selector("#recentDd", "e=>e.classList.contains('none')"), "初期は履歴なし（薄表示）")

    for n in NAMES:
        open_via_picker(pg, n)
    check(items(pg) == ["f6.json", "f5.json", "f4.json", "f3.json", "f2.json"], f"直近5件・新しい順・6件目以降は切り捨て -> {items(pg)}")

    open_via_picker(pg, "f3.json")
    check(items(pg) == ["f3.json", "f6.json", "f5.json", "f4.json", "f2.json"], f"同じファイルは重複せず先頭へ移動 -> {items(pg)}")

    pg.click("#refreshBtn"); pg.wait_for_timeout(250)
    check(items(pg)[0] == "f3.json" and len(items(pg)) == 5, "「更新」では並び順を変えない")

    pg.reload(); pg.wait_for_timeout(400)
    check(items(pg) == ["f3.json", "f6.json", "f5.json", "f4.json", "f2.json"], f"リロード後も履歴が残る（IndexedDB） -> {items(pg)}")

    open_recent(pg, 3)
    check(shown(pg, "P-f4.json") and items(pg)[0] == "f4.json", "一覧クリックで該当ファイルを読込・先頭へ")
    check(not pg.eval_on_selector("#recentDd", "e=>e.open"), "選択後はドロップダウンを閉じる")
    pg.evaluate("""async()=>{const d=await navigator.storage.getDirectory();const h=await d.getFileHandle('f4.json');
      const w=await h.createWritable();await w.write(%s);await w.close();}""" % json.dumps(data("P-f4-updated")))
    pg.click("#refreshBtn"); pg.wait_for_timeout(250)
    check(shown(pg, "P-f4-updated"), "再オープン後の「更新」がそのファイルを再読込")

    # 許可が得られない（file:// 相当でプロンプト不可）→ そのファイルのフォルダを起点にピッカー
    pg.evaluate("""()=>{window.__startIn=null;
      FileSystemHandle.prototype.queryPermission=async()=>'prompt';
      FileSystemHandle.prototype.requestPermission=async()=>{throw new Error('not allowed');};
      window.showOpenFilePicker=async o=>{window.__startIn=o&&o.startIn&&o.startIn.name;
        const d=await navigator.storage.getDirectory();return [await d.getFileHandle('f5.json')];};}""")
    idx = items(pg).index("f5.json")
    open_recent(pg, idx)
    check(pg.evaluate("window.__startIn") == "f5.json", f"許可不可は startIn=元ファイルでピッカー -> {pg.evaluate('window.__startIn')}")
    check(shown(pg, "P-f5.json") and items(pg)[0] == "f5.json", "フォールバックのピッカーで選んだファイルを読込")
    check(not pg.evaluate("document.getElementById('notice').classList.contains('show')"), "読込後は案内バーを消す")
    pg.evaluate("""()=>{window.showOpenFilePicker=async()=>{throw new DOMException('cancel','AbortError');};}""")
    dialogs.clear(); open_recent(pg, 1)
    check(not dialogs and len(items(pg)) == 5, "フォールバックのキャンセルは無言・履歴は不変")
    pg.reload(); pg.wait_for_timeout(400)

    # 未保存の編集が書き込めない時は切替を中止（編集を捨てない）
    open_recent(pg, 0); cur = items(pg)[0]                         # リロード直後は未読込＝まずハンドル付きで開く
    pg.click("#editBtn"); pg.wait_for_timeout(200)
    pg.evaluate("()=>{FileSystemFileHandle.prototype.createWritable=async()=>{throw new DOMException('disk full','NotReadableError');};}")
    pg.fill('input[data-path="0/0"][data-field="assignee"]', "山田")
    pg.dispatch_event('input[data-path="0/0"][data-field="assignee"]', "change")
    pg.wait_for_timeout(700)   # デバウンス保存が失敗＝dirty のまま
    dialogs.clear(); open_recent(pg, 1)
    check(any("切り替えませんでした" in d for d in dialogs), f"書込失敗のまま切替しようとすると警告 -> {dialogs}")
    kept = pg.evaluate("""()=>{const i=document.querySelector('input[data-path="0/0"][data-field="assignee"]');
      return !!i && i.value==='山田' && document.getElementById('editBtn').classList.contains('on');}""")
    check(kept and items(pg)[0] == cur, "書込失敗時はファイルを切り替えない（編集モード・入力値を保持）")
    pg.reload(); pg.wait_for_timeout(400)

    # 一覧の変更は直列化：追加の処理中にクリアが割り込んでも削除済みが復活しない／連続追加を取りこぼさない
    pg.evaluate("""async()=>{const d=await navigator.storage.getDirectory();
      const slow=FileSystemHandle.prototype.isSameEntry;
      FileSystemHandle.prototype.isSameEntry=async function(o){await new Promise(r=>setTimeout(r,60));return slow.call(this,o);};
      const h1=await d.getFileHandle('f1.json');
      window.showOpenFilePicker=async()=>[h1];}""")
    pg.click("#openBtn"); pg.wait_for_timeout(30)                 # f1 の追加が isSameEntry 待ちの間に
    pg.click("#recentSum"); pg.click("#recentList .rc-clear")    # クリアを割り込ませる
    pg.wait_for_timeout(800)
    prev = items(pg)
    check(set(prev) <= {"f1.json"}, f"追加中のクリアは順に適用（クリア前の履歴が復活しない） -> {prev}")
    pg.evaluate("""async()=>{const d=await navigator.storage.getDirectory();
      const hs=[await d.getFileHandle('f3.json'),await d.getFileHandle('f4.json')]; let k=0;
      window.showOpenFilePicker=async()=>[hs[k++]];}""")
    pg.click("#openBtn"); pg.click("#openBtn"); pg.wait_for_timeout(1000)
    check(items(pg) == ["f4.json", "f3.json"] + prev, f"連続追加を取りこぼさない -> {items(pg)}")
    pg.reload(); pg.wait_for_timeout(400)
    check(items(pg) == ["f4.json", "f3.json"] + prev, f"直列化後の一覧がそのまま永続 -> {items(pg)}")

    # 消失したファイル → 履歴から削除して通知
    pg.evaluate("async()=>{const d=await navigator.storage.getDirectory();await d.removeEntry('f3.json');}")
    dialogs.clear(); open_recent(pg, items(pg).index("f3.json"))
    check("f3.json" not in items(pg) and any("f3.json" in d for d in dialogs), f"消失ファイルは履歴から削除して通知 -> {dialogs}")

    for n in ["f5.json", "f6.json"]:                               # ✕→クリアを確かめるため2件以上にそろえる
        open_via_picker(pg, n)
    n0 = len(items(pg))
    pg.click("#recentSum"); pg.click('#recentList [data-rcdel="0"]')
    check(len(items(pg)) == n0 - 1, "✕で個別削除")
    pg.click("#recentList .rc-clear")
    check(items(pg) == [], "履歴をクリアで全削除")
    pg.wait_for_timeout(200)   # IndexedDB への書込完了を待ってからリロード
    pg.reload(); pg.wait_for_timeout(400)
    check(items(pg) == [], "クリアはリロード後も保持")

    pg.click("#langBtn")
    check(pg.inner_text("#recentSum").startswith("Recent"), "英語 UI で文言切替")
    pg.click("#langBtn")

    # 外側クリックで閉じる
    pg.click("#recentSum"); pg.click("#main", position={"x": 5, "y": 5})
    check(not pg.eval_on_selector("#recentDd", "e=>e.open"), "外側クリックで閉じる")

    # IndexedDB 不可でもクラッシュしない（D&D 読込は通常どおり）
    pg2 = new_page(b)
    pg2.on("pageerror", lambda e: errors.append(str(e)))
    pg2.add_init_script("Object.defineProperty(window,'indexedDB',{get(){throw new Error('blocked');}});")
    pg2.goto(URL); pg2.wait_for_timeout(200)
    pg2.evaluate("""txt=>{const dt=new DataTransfer();dt.items.add(new File([txt],'x.json',{type:'application/json'}));
      document.getElementById('openBtn').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));}""", data("P-x"))
    pg2.wait_for_timeout(250)
    check(shown(pg2, "P-x"), "IndexedDB 不可でも読込・描画できる（JS エラー無し）")
    b.close()
srv.shutdown()
finish(errors)
