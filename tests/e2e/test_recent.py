"""IndexedDB-backed recent file history and handle-less load behavior."""
import json
from playwright.sync_api import sync_playwright
from common import VIEWER, check, finish

INIT = """
(() => {
  const handles = new Map();
  for (let n=1;n<=6;n++) {
    const id='f'+n, name='file'+n+'.json';
    const state={permission:'granted',missing:false};
    handles.set(id, {
      kind:'file', name, __id:id,
      getFile:async()=>{if(state.missing)throw new DOMException('missing','NotFoundError');
        return new File([JSON.stringify({projects:[{name:id,tasks:[]}]})],name,{lastModified:n});},
      queryPermission:async()=>state.permission,
      requestPermission:async()=>state.permission,
      isSameEntry:async other=>other.__id===id,
      __state:state
    });
  }
  window.__handles=handles;
  window.__picked='f1';
  window.__startIn=null;
  window.showOpenFilePicker=async options=>{
    window.__startIn=options.startIn?.__id||null;
    return [handles.get(window.__picked)];
  };
  const history=()=>JSON.parse(localStorage.getItem('mockRecent')||'[]')
    .map(({name,id})=>({name,handle:handles.get(id)}));
  const db={
    objectStoreNames:{contains:()=>true},
    createObjectStore:()=>{},
    transaction:()=>{
      const tx={oncomplete:null};
      tx.objectStore=()=>({
        get:()=>{const req={};setTimeout(()=>{req.result=history();req.onsuccess?.();},0);return req;},
        put:value=>{const req={};localStorage.setItem('mockRecent',JSON.stringify(
          value.map(e=>({name:e.name,id:e.handle.__id}))));
          setTimeout(()=>{req.onsuccess?.();tx.oncomplete?.();},0);return req;}
      });
      return tx;
    }
  };
  Object.defineProperty(window,'indexedDB',{configurable:true,value:{open:()=>{
    const req={};setTimeout(()=>{req.result=db;req.onupgradeneeded?.();req.onsuccess?.();},0);return req;
  }}});
})();
"""

errors, dialogs = [], []
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page()
    pg.add_init_script(INIT)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    pg.goto(VIEWER)
    pg.wait_for_timeout(150)
    check(pg.inner_text("#recentSummary") == "最近 ▼", "recent dropdown is shown in Japanese")

    for n in range(1, 7):
        pg.evaluate("(n)=>window.__picked='f'+n", n)
        pg.click("#openBtn")
        pg.wait_for_function("(n)=>document.querySelectorAll('#recentList [data-recent-open]').length===Math.min(n,5)", arg=n)
        pg.wait_for_timeout(80)
    names = pg.locator("#recentList [data-recent-open]").all_text_contents()
    check(names == ["file6.json", "file5.json", "file4.json", "file3.json", "file2.json"],
          f"most recent five are newest first -> {names}")
    pg.click("#refreshBtn")
    pg.wait_for_timeout(120)
    check(pg.locator("#recentList [data-recent-open]").all_text_contents() == names,
          "refresh does not reorder history")
    pg.click("#langBtn")
    check(pg.inner_text("#recentSummary") == "Recent ▼", "recent dropdown is localized in English")
    pg.click("#langBtn")

    pg.reload()
    pg.wait_for_timeout(150)
    after_reload = pg.locator("#recentList [data-recent-open]").all_text_contents()
    check(after_reload == ["file6.json", "file5.json", "file4.json", "file3.json", "file2.json"],
          f"history survives reload -> {after_reload}")

    pg.locator("#recentSummary").click()
    pg.evaluate("""()=>{
      const h=window.__handles.get('f3');
      h.__state.permission='prompt';
      h.requestPermission=async()=> 'denied';
      window.__picked='f3';
    }""")
    pg.locator("#recentList [data-recent-open]").nth(3).click()
    pg.wait_for_function("document.querySelector('#leftRows').innerText.includes('f3')")
    check(pg.evaluate("()=>window.__startIn") == "f3", "permission denial opens picker from recent file location")
    names = pg.locator("#recentList [data-recent-open]").all_text_contents()
    check(names[0] == "file3.json" and names.count("file3.json") == 1,
          f"reopening moves duplicate to front -> {names}")

    pg.locator("#recentSummary").click()
    pg.evaluate("()=>window.__handles.get('f6').__state.missing=true")
    pg.locator("#recentList [data-recent-open]").nth(1).click()
    pg.wait_for_function("!JSON.parse(localStorage.getItem('mockRecent')||'[]').some(e=>e.id==='f6')")
    pg.wait_for_timeout(50)
    check(any("file6.json" in message and "見つかりません" in message for message in dialogs),
          f"missing file is removed and reported -> {dialogs}")

    pg.locator("#recentSummary").click()
    pg.wait_for_function("!document.querySelector('#recentList').innerText.includes('file6.json')")
    pg.locator("#recentList [data-recent-remove]").nth(1).click()
    pg.wait_for_function("document.querySelectorAll('#recentList [data-recent-open]').length===3")
    check("file5.json" not in pg.locator("#recentList").inner_text(), "individual removal works")
    pg.locator("[data-recent-clear]").click()
    pg.wait_for_function("document.querySelector('#recentList').innerText.includes('履歴はありません')")
    check(pg.locator("#recentList [data-recent-open]").count() == 0, "clear history works")

    pg.evaluate("""()=>{
      const dt=new DataTransfer();dt.items.add(new File([
        JSON.stringify({projects:[{name:'dropped',tasks:[]}]})
      ],'dropped.json'));
      document.getElementById('openBtn').dispatchEvent(
        new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:dt}));
    }""")
    pg.wait_for_function("document.querySelector('#leftRows').innerText.includes('dropped')")
    check(pg.locator("#recentList [data-recent-open]").count() == 0,
          "handle-less drag-and-drop fallback is not recorded")

    broken = b.new_page()
    broken.add_init_script("Object.defineProperty(window,'indexedDB',{get(){throw new Error('disabled')}})")
    broken.on("pageerror", lambda e: errors.append(str(e)))
    broken.goto(VIEWER)
    broken.wait_for_timeout(100)
    check(broken.inner_text("#recentSummary") == "最近 ▼", "unavailable IndexedDB degrades without a JS error")
    b.close()
finish(errors)
