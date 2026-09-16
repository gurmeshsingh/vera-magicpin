"""A browser UI for driving the bot by hand.

Served by the app itself, so the page is same-origin and needs no CORS and no
separate process. It talks to the same five endpoints the judge uses -- there is
no back door and no special-cased demo path, so what you see here is what the
judge would see.

Using it pushes real context into the running instance. On the deployed service
that is contamination: an equal-version push is idempotent by contract, so
leftovers would make the judge's own pushes silent no-ops. The Reset button
calls /v1/teardown, which is the fix, and the page says so when it is not
running against localhost.
"""

from __future__ import annotations

PLAYGROUND_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vera Playground</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500;6..72,600&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@400&display=swap">
<style>
:root{
  --paper:#F6F8F5; --surface:#fff; --surface-2:#EDF1EC; --ink:#131C18;
  --ink-soft:#3C4A43; --ink-faint:#6B7A72; --rule:#D5DED6;
  --jade:#0E6B4F; --jade-soft:#E2EFE8; --amber:#8A5A0B; --amber-soft:#F6EEDC;
  --clay:#8F3324; --clay-soft:#F7E6E2;
  --f-d:"Newsreader",Georgia,serif; --f-b:"Source Sans 3",system-ui,sans-serif;
  --f-m:"JetBrains Mono",ui-monospace,Menlo,monospace;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --paper:#0F1613; --surface:#16201C; --surface-2:#1C2823; --ink:#E8EFE9;
  --ink-soft:#B4C2BA; --ink-faint:#7E8F86; --rule:#2A3832;
  --jade:#5FC79E; --jade-soft:#17322A; --amber:#D9A441; --amber-soft:#2E2618;
  --clay:#E0806E; --clay-soft:#2F1D19;
}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--f-b);
  font-size:16px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding:28px 22px 80px}
header{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:22px;
  display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap}
h1{font-family:var(--f-d);font-size:30px;font-weight:600;margin:0;letter-spacing:-.01em}
.sub{color:var(--ink-faint);font-size:14px;margin:4px 0 0}
.badge{font-family:var(--f-m);font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  padding:4px 9px;border-radius:4px;background:var(--surface-2);color:var(--ink-faint);white-space:nowrap}
.badge.ok{background:var(--jade-soft);color:var(--jade)}
.badge.bad{background:var(--clay-soft);color:var(--clay)}
.warn{background:var(--amber-soft);border-left:3px solid var(--amber);padding:12px 16px;
  border-radius:0 5px 5px 0;margin:0 0 20px;font-size:14.5px}
.warn b{color:var(--amber)}
.grid{display:grid;grid-template-columns:300px minmax(0,1fr);gap:20px}
@media(max-width:820px){.grid{grid-template-columns:1fr}}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:8px;overflow:hidden}
.panel h2{font-family:var(--f-b);font-size:11.5px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-faint);margin:0;padding:11px 15px;border-bottom:1px solid var(--rule);
  background:var(--surface-2);font-weight:600}
.panel .body{padding:15px}
button{font-family:var(--f-b);font-size:14.5px;font-weight:600;padding:9px 15px;border-radius:6px;
  border:1px solid var(--jade);background:var(--jade);color:#fff;cursor:pointer;transition:opacity .12s}
button:hover{opacity:.88}
button.ghost{background:transparent;color:var(--jade)}
button.danger{background:transparent;border-color:var(--clay);color:var(--clay)}
button:disabled{opacity:.45;cursor:not-allowed}
.row{display:flex;gap:9px;flex-wrap:wrap;margin-bottom:12px}
select,input{font-family:var(--f-b);font-size:14.5px;padding:8px 10px;border-radius:6px;
  border:1px solid var(--rule);background:var(--surface);color:var(--ink);width:100%}
label{display:block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-faint);margin:12px 0 5px;font-weight:600}
.msg{background:var(--jade-soft);border-radius:10px 10px 10px 2px;padding:13px 15px;margin:0 0 10px;
  font-size:15.5px;line-height:1.5}
.msg.them{background:var(--surface-2);border-radius:10px 10px 2px 10px;margin-left:44px}
.meta{font-family:var(--f-m);font-size:11.5px;color:var(--ink-faint);margin:0 0 14px;line-height:1.5}
.meta b{color:var(--jade);font-weight:400}
.empty{color:var(--ink-faint);font-size:14.5px;padding:8px 0}
.chat{max-height:330px;overflow-y:auto;margin-bottom:12px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.chip{font-size:12.5px;padding:5px 10px;border:1px solid var(--rule);border-radius:99px;
  background:var(--surface);color:var(--ink-soft);cursor:pointer}
.chip:hover{border-color:var(--jade);color:var(--jade)}
pre{font-family:var(--f-m);font-size:12px;background:var(--surface-2);padding:11px;
  border-radius:6px;overflow-x:auto;margin:0;max-height:220px;color:var(--ink-soft)}
.spin{display:inline-block;width:11px;height:11px;border:2px solid var(--rule);
  border-top-color:var(--jade);border-radius:50%;animation:s .7s linear infinite;vertical-align:-1px}
@keyframes s{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.spin{animation:none}}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div>
    <h1>Vera Playground</h1>
    <p class="sub">Drive the bot through the same five endpoints the judge uses.</p>
  </div>
  <div><span class="badge" id="status">checking…</span></div>
</header>

<div class="warn" id="livewarn" style="display:none">
  <b>This is the deployed instance.</b> Anything you load here stays in its memory,
  and a leftover context at the same version makes the judge's own push a silent
  no-op. Hit <b>Reset</b> when you are done.
</div>

<div class="grid">
  <div>
    <div class="panel">
      <h2>1 · Load a merchant</h2>
      <div class="body">
        <div class="row">
          <button id="load">Load demo data</button>
          <button class="ghost" id="reset">Reset</button>
        </div>
        <label for="pick">Merchant</label>
        <select id="pick" disabled><option>load data first</option></select>
        <div class="row" style="margin:12px 0 0">
          <button id="go" disabled>What would Vera say?</button>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-top:18px">
      <h2>Service</h2>
      <div class="body"><pre id="health">—</pre></div>
    </div>
  </div>

  <div>
    <div class="panel">
      <h2>2 · The conversation</h2>
      <div class="body">
        <div class="chat" id="chat"><div class="empty">Load the demo data, pick a merchant, and ask what Vera would say.</div></div>
        <div class="chips" id="chips" style="display:none">
          <span class="chip" data-m="Ok lets do it. Whats next?">Ok lets do it</span>
          <span class="chip" data-m="How much will this cost me?">How much?</span>
          <span class="chip" data-m="where did you get those numbers?">Where's that from?</span>
          <span class="chip" data-m="Thank you for contacting us! Our team will respond shortly.">(auto-reply)</span>
          <span class="chip" data-m="Stop messaging me. This is useless spam.">Not interested</span>
          <span class="chip" data-m="can you also help me file my GST?">Off-topic</span>
        </div>
        <div class="row" id="replyrow" style="display:none">
          <input id="reply" placeholder="Reply as the merchant…" style="flex:1;min-width:200px">
          <button id="send">Send</button>
        </div>
      </div>
    </div>

    <div class="panel" style="margin-top:18px">
      <h2>3 · Why it said that</h2>
      <div class="body"><pre id="rationale">—</pre></div>
    </div>
  </div>
</div>
</div>

<script>
const $ = s => document.querySelector(s);
const api = (p, b) => fetch(p, b ? {method:'POST', headers:{'Content-Type':'application/json'},
  body: JSON.stringify(b)} : {}).then(r => r.json());
let convId = null, merchantId = null;

if (!['localhost','127.0.0.1'].includes(location.hostname)) $('#livewarn').style.display = 'block';

async function health(){
  try{
    const h = await api('/v1/healthz');
    const c = h.contexts_loaded, n = c.category + c.merchant + c.customer + c.trigger;
    $('#status').textContent = n ? `live · ${n} contexts` : 'live · empty';
    $('#status').className = 'badge ok';
    $('#health').textContent = JSON.stringify(h, null, 1);
    return n;
  }catch(e){ $('#status').textContent = 'unreachable'; $('#status').className='badge bad'; return 0; }
}

function bubble(text, mine, cls){
  const d = document.createElement('div');
  d.className = 'msg' + (mine ? '' : ' them') + (cls || '');
  d.textContent = text;
  $('#chat').appendChild(d); $('#chat').scrollTop = 1e6;
}

$('#load').onclick = async () => {
  $('#load').disabled = true; $('#load').innerHTML = 'loading <span class="spin"></span>';
  const r = await api('/v1/_demo', {});
  const sel = $('#pick'); sel.innerHTML = '';
  r.merchants.forEach(m => {
    const o = document.createElement('option');
    o.value = m.id; o.textContent = `${m.name} · ${m.category}`;
    sel.appendChild(o);
  });
  sel.disabled = false; $('#go').disabled = false;
  $('#load').disabled = false; $('#load').textContent = 'Reload demo data';
  health();
};

$('#reset').onclick = async () => {
  await api('/v1/teardown', {});
  $('#chat').innerHTML = '<div class="empty">Reset. Load the demo data to start again.</div>';
  $('#rationale').textContent = '—'; $('#pick').innerHTML = '<option>load data first</option>';
  $('#pick').disabled = true; $('#go').disabled = true;
  $('#chips').style.display='none'; $('#replyrow').style.display='none';
  $('#load').textContent = 'Load demo data';
  health();
};

$('#go').onclick = async () => {
  merchantId = $('#pick').value;
  $('#chat').innerHTML = ''; $('#go').disabled = true;
  const r = await api('/v1/tick', {now: new Date().toISOString(),
                                   available_triggers: ['trg_' + merchantId]});
  $('#go').disabled = false;
  if (!r.actions || !r.actions.length){
    bubble('(Vera chose to say nothing — nothing here clears the bar this tick.)', true);
    $('#rationale').textContent = 'No action. Silence is a legitimate, rewarded output.';
    return;
  }
  const a = r.actions[0];
  convId = a.conversation_id;
  bubble(a.body, true);
  $('#rationale').textContent =
    `angle       ${a.template_name}\\nsend_as     ${a.send_as}\\ncta         ${a.cta}\\n` +
    `suppression ${a.suppression_key}\\n\\n${a.rationale}`;
  $('#chips').style.display='flex'; $('#replyrow').style.display='flex';
  health();
};

async function send(text){
  if (!text || !convId) return;
  bubble(text, false); $('#reply').value = '';
  const r = await api('/v1/reply', {conversation_id: convId, merchant_id: merchantId,
    from_role: 'merchant', message: text, received_at: new Date().toISOString(), turn_number: 2});
  if (r.action === 'send') bubble(r.body, true);
  else if (r.action === 'wait') bubble(`(waiting ${r.wait_seconds}s before saying more)`, true);
  else bubble('(Vera ended the conversation)', true);
  $('#rationale').textContent = `action      ${r.action}\\n\\n${r.rationale || ''}`;
}

$('#send').onclick = () => send($('#reply').value.trim());
$('#reply').onkeydown = e => { if (e.key === 'Enter') send($('#reply').value.trim()); };
document.querySelectorAll('.chip').forEach(c => c.onclick = () => send(c.dataset.m));

health();
</script>
</body>
</html>
"""
