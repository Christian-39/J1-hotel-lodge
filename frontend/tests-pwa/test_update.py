"""Verify the SW update lifecycle: new version waits, old caches are purged,
and activation only happens when the page asks for it."""
import re, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

SW = Path("../sw.js")
orig = SW.read_text()
BASE = "http://127.0.0.1:8080"
out = []
def check(n, ok, d=""):
    out.append((n, ok, d))

try:
    with sync_playwright() as pw:
        b = pw.chromium.launch(); ctx = b.new_context(service_workers="allow"); p = ctx.new_page()
        p.goto(BASE + "/index.html", wait_until="load"); p.wait_for_timeout(1500)
        v1 = p.evaluate("async()=> (await caches.keys())")
        check("v1 caches created", any("jone-v1" in k for k in v1), str(v1))

        # Deploy "v2"
        SW.write_text(orig.replace('const CACHE_VERSION = "jone-v1"', 'const CACHE_VERSION = "jone-v2"'))
        time.sleep(0.4)

        state = p.evaluate("""async () => {
            const r = await navigator.serviceWorker.getRegistration();
            await r.update();
            await new Promise(res => setTimeout(res, 1500));
            return { waiting: !!r.waiting, active: r.active && r.active.state,
                     caches: await caches.keys() };
        }""")
        # New worker must WAIT, not take over on its own (no skipWaiting in install).
        check("new SW waits (no self-activation)", state["waiting"] is True, str(state))
        check("old v1 cache still intact while waiting",
              any("jone-v1" in k for k in state["caches"]), str(state["caches"]))

        # Page explicitly authorises the swap.
        p.evaluate("""async () => {
            const r = await navigator.serviceWorker.getRegistration();
            if (r.waiting) r.waiting.postMessage({ type: 'SKIP_WAITING' });
        }""")
        p.wait_for_timeout(2500)
        after = p.evaluate("async()=> (await caches.keys())")
        check("v2 cache created", any("jone-v2" in k for k in after), str(after))
        check("old v1 caches cleaned up", not any("jone-v1" in k for k in after), str(after))

        ver = p.evaluate("""async () => {
            const r = await navigator.serviceWorker.ready;
            return new Promise(res => {
                const ch = new MessageChannel();
                navigator.serviceWorker.addEventListener('message', e => res(e.data), {once:true});
                r.active.postMessage({type:'GET_VERSION'});
                setTimeout(()=>res(null), 1500);
            });
        }""")
        check("SW reports its version", ver and ver.get("version") == "jone-v2", str(ver))
        b.close()
finally:
    SW.write_text(orig)

print("\n".join(f"{'PASS' if o else 'FAIL'}  {n}" + (f"  -> {d}" if d and not o else "") for n,o,d in out))
fails=[n for n,o,_ in out if not o]
print(f"\n{len(out)-len(fails)}/{len(out)} passed")
sys.exit(1 if fails else 0)
