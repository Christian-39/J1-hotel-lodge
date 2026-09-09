#!/usr/bin/env python3
"""Generate all staff dashboard pages from the shared ops shell in shell.py.

REGRESSION GUARD: The shipped dashboard pages were migrated to the API-driven
pattern (real loading / empty / error states, no demo records, no fake success
toasts). The templates below STILL carry legacy demonstration arrays. Running
this file as-is would regenerate pages with that demo data again — which the
audit forbids. Therefore write() REFUSES to emit a body containing known
demo-data markers, so it fails loudly instead of silently shipping fake records.
Migrate the templates to the API-driven pattern (see the shipped pages) before
removing the guard.
"""
import sys, importlib.util, re
from pathlib import Path
spec = importlib.util.spec_from_file_location("shell", Path(__file__).parent / "shell.py")
shell = importlib.util.module_from_spec(spec); spec.loader.exec_module(shell)

DASH = Path(__file__).parent

# Markers that indicate a template still contains hard-coded demonstration data.
DEMO_PATTERNS = [
    re.compile(r'var\s+(data|arrivals|rooms|items|methods|types|bookings|guests)\s*=\s*\[\s*\{'),
    re.compile(r'J1-2048|J1-2046|J1-2047|Amina Yusuf|Chidi Okafor|Ruth Adebayo'),
    re.compile(r'toast\(".*?(demo state|dev state|checked in successfully|checked out successfully|Booking cancelled\.|Payment recorded successfully)\b'),
    re.compile(r'Math\.random'),
]

def write(name, title, body, scripts=None):
    source = (body or "") + (scripts or "")
    for pat in DEMO_PATTERNS:
        m = pat.search(source)
        if m:
            raise SystemExit(
                f"REFUSED to write {name}.html: template still contains demo data "
                f"({m.group(0)!r}). Migrate the template to the API-driven pattern "
                f"before regenerating (see the shipped page)."
            )
    full = shell.head(title) + body + shell.foot(scripts or "")
    p = DASH / f"{name}.html"
    p.write_text(full, encoding="utf-8")
    print("wrote", p.name)

CSS_LINK = None

# ----------------------------------------------------------------------------
# 1. Dashboard overview
# ----------------------------------------------------------------------------
write("index", "Dashboard", f"""
<section class="kpi-grid">
  <div class="kpi"><div class="kpi-label">Today's check-ins</div><div class="kpi-value" data-kpi="today_checkins">--</div><div class="kpi-sub">2 confirmed</div></div>
  <div class="kpi"><div class="kpi-label">Today's check-outs</div><div class="kpi-value" data-kpi="today_checkouts">--</div><div class="kpi-sub">1 pending</div></div>
  <div class="kpi"><div class="kpi-label">Guests in-house</div><div class="kpi-value" data-kpi="in_house">--</div><div class="kpi-sub">among <span data-kpi="occupied">--</span> occupied rooms</div></div>
  <div class="kpi"><div class="kpi-label">Available rooms</div><div class="kpi-value" data-kpi="available_rooms">--</div><div class="kpi-sub">of <span data-kpi="total_rooms">--</span> total</div></div>
  <div class="kpi"><div class="kpi-label">Pending bookings</div><div class="kpi-value" data-kpi="pending_bookings">--</div><div class="kpi-sub">awaiting confirmation</div></div>
  <div class="kpi"><div class="kpi-label">Today's revenue</div><div class="kpi-value" data-kpi="today_revenue">--</div><div class="kpi-sub">incl. <span data-kpi="outstanding">--</span> outstanding</div></div>
</section>

<section class="panel">
  <div class="panel-head"><h2>Quick actions</h2></div>
  <div class="panel-body">
    <div class="quick-actions">
      <a class="quick-action" href="bookings.html"><span data-icon="plus"></span> New booking</a>
      <a class="quick-action" href="check-in.html"><span data-icon="logOut"></span> Check-in</a>
      <a class="quick-action" href="check-out.html"><span data-icon="logOut"></span> Check-out</a>
      <a class="quick-action" href="guests.html"><span data-icon="search"></span> Search guest</a>
      <a class="quick-action" href="bookings.html"><span data-icon="search"></span> Search booking</a>
      <a class="quick-action" href="payments.html"><span data-icon="wallet"></span> Record payment</a>
    </div>
  </div>
</section>

<div class="panel-grid">
  <section class="panel">
    <div class="panel-head"><h2>Upcoming arrivals</h2><div class="panel-actions"><a class="btn btn-sm btn-outline" href="check-in.html">Open check-in</a></div></div>
    <div class="panel-body no-pad">
      <div class="table-wrap"><table class="table">
        <thead><tr><th>Guest</th><th>Room</th><th>Check-in</th><th>Status</th></tr></thead>
        <tbody data-tbody="arrivals"></tbody>
      </table></div>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>Recent activity</h2></div>
    <div class="panel-body">
      <div class="activity-list" data-activity></div>
    </div>
  </section>
</div>
""", """
(function(){
  var arrivals = [
    {guest:"Amina Yusuf", room:"201", date:"Today", status:"confirmed"},
    {guest:"Chidi Okafor", room:"305", date:"Tomorrow", status:"confirmed"},
    {guest:"Ruth Adebayo", room:"112", date:"Today", status:"pending"},
    {guest:"Emeka Nwosu", room:"402", date:"Sat 12", status:"pending"}
  ];
  var tbody = document.querySelector("[data-tbody=arrivals]");
  if (tbody) tbody.innerHTML = arrivals.map(function(a){
    return "<tr><td>"+JONE.esc(a.guest)+"</td><td>"+JONE.esc(a.room)+"</td><td>"+JONE.esc(a.date)+"</td><td>"+JONE.dashboard.statusPill(a.status)+"</td></tr>";
  }).join("");

  var act = document.querySelector("[data-activity]");
  if (act) act.innerHTML = [
    {i:"checkCircle", t:"Booking J1-2048 confirmed", time:"9:42 AM"},
    {i:"wallet", t:"Payment of ₦60,000 recorded", time:"9:15 AM"},
    {i:"bed", t:"Room 201 checked in", time:"8:58 AM"},
    {i:"users", t:"New guest profile added", time:"8:20 AM"}
  ].map(function(a){
    return '<div class="activity-item"><span class="activity-icon"><span data-icon="'+a.i+'" data-size="18"></span></span><div class="activity-body"><p>'+JONE.esc(a.t)+'</p><div class="activity-time">'+JONE.esc(a.time)+'</div></div></div>';
  }).join("");
  JONE.icons.inject(document);
  // TODO live KPIs via API
})();
""")

# ----------------------------------------------------------------------------
# 2. Bookings
# ----------------------------------------------------------------------------
write("bookings", "Bookings", f"""
<section class="panel">
  <div class="filter-bar">
    <div class="field"><label class="field-label" for="bk-q">Search</label><input class="input" id="bk-q" data-filter="q" placeholder="Ref, guest, phone, email"></div>
    <div class="field"><label class="field-label" for="bk-status">Status</label><select class="select" id="bk-status" data-filter="status"><option value="">All</option><option>confirmed</option><option>pending</option><option>cancelled</option><option>checked_in</option><option>checked_out</option></select></div>
    <div class="field"><label class="field-label" for="bk-pay">Payment</label><select class="select" id="bk-pay" data-filter="payment_status"><option value="">All</option><option>paid</option><option>partial</option><option>unpaid</option></select></div>
    <div class="field"><label class="field-label" for="bk-date">From</label><input class="input" type="date" id="bk-date" data-filter="from"></div>
    <div class="filter-actions"><button class="btn btn-sm" data-new-booking>New booking</button></div>
  </div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Reference</th><th class="hide-sm">Guest</th><th class="hide-sm">Room</th><th>Check-in</th><th class="hide-sm">Check-out</th><th>Status</th><th class="hide-sm">Payment</th><th class="hide-sm">Total</th><th></th></tr></thead>
      <tbody data-tbody="bookings"></tbody>
    </table></div>
    <div class="pagination" data-pagination></div>
  </div>
</section>
""", """
(function(){
  var data = [
    {ref:"J1-2048", guest:"Amina Yusuf", phone:"080", room:"201", type:"Deluxe", ci:"2026-09-09", co:"2026-09-11", status:"confirmed", pay:"paid", total:120000},
    {ref:"J1-2047", guest:"Chidi Okafor", phone:"081", room:"305", type:"Standard", ci:"2026-09-12", co:"2026-09-13", status:"pending", pay:"unpaid", total:45000},
    {ref:"J1-2046", guest:"Ruth Adebayo", phone:"070", room:"112", type:"Executive", ci:"2026-09-09", co:"2026-09-15", status:"checked_in", pay:"partial", total:570000},
    {ref:"J1-2045", guest:"Emeka Nwosu", phone:"090", room:"402", type:"Deluxe", ci:"2026-09-08", co:"2026-09-09", status:"checked_out", pay:"paid", total:60000},
    {ref:"J1-2044", guest:"Bola Salami", phone:"080", room:"208", type:"Standard", ci:"2026-09-11", co:"2026-09-12", status:"cancelled", pay:"unpaid", total:45000}
  ];
  function render(list){
    var tbody = document.querySelector("[data-tbody=bookings]");
    if(!tbody) return;
    if(!list.length){ tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><span data-icon="search"></span><h3>No bookings found</h3><p>Adjust your search or filters.</p></div></td></tr>'; JONE.icons.inject(tbody); return; }
    tbody.innerHTML = list.map(function(b){
      return '<tr>'+
        '<td><a class="nav-link" href="booking-details.html?ref='+b.ref+'">'+JONE.esc(b.ref)+'</a></td>'+
        '<td class="hide-sm">'+JONE.esc(b.guest)+'</td>'+
        '<td class="hide-sm">'+JONE.esc(b.room)+' · '+JONE.esc(b.type)+'</td>'+
        '<td>'+JONE.formatDate(b.ci,"mid")+'</td>'+
        '<td class="hide-sm">'+JONE.formatDate(b.co,"mid")+'</td>'+
        '<td>'+JONE.dashboard.statusPill(b.status)+'</td>'+
        '<td class="hide-sm">'+JONE.dashboard.statusPill(b.pay)+'</td>'+
        '<td class="hide-sm num">'+JONE.formatNaira(b.total)+'</td>'+
        '<td><a class="btn btn-sm btn-outline" href="booking-details.html?ref='+b.ref+'">View</a></td>'+
      '</tr>';
    }).join("");
    JONE.icons.inject(tbody);
  }
  function apply(){ render(data); }
  ["bk-q","bk-status","bk-pay","bk-date"].forEach(function(id){
    var el=document.getElementById(id); el && el.addEventListener("change", apply);
  });
  apply();
  var nb=document.querySelector("[data-new-booking]"); nb && nb.addEventListener("click", function(){
    location.href="booking-details.html";
  });
})();
""")

# ----------------------------------------------------------------------------
# 3. Booking details
# ----------------------------------------------------------------------------
write("booking-details", "Booking", f"""
<div class="panel-grid">
    <section class="panel">
      <div class="panel-head">
        <h2 data-bd-ref>Booking</h2>
        <div class="panel-actions">
          <button class="btn btn-sm btn-outline" data-bd-checkin>Check-in</button>
          <button class="btn btn-sm btn-outline" data-bd-record><span data-icon="wallet" data-size="16"></span> Record payment</button>
          <button class="btn btn-sm btn-danger" data-bd-cancel>Cancel</button>
        </div>
      </div>
      <div class="panel-body">
        <div class="review-section"><h4>Guest</h4><p data-bd-guest>--</p><p class="caption" data-bd-contact>--</p></div>
        <div class="review-section"><h4>Stay</h4>
          <div class="flex-between"><span class="muted">Room</span><span data-bd-room>--</span></div>
          <div class="flex-between"><span class="muted">Check-in</span><span data-bd-ci>--</span></div>
          <div class="flex-between"><span class="muted">Check-out</span><span data-bd-co>--</span></div>
          <div class="flex-between"><span class="muted">Nights</span><span data-bd-nights>--</span></div>
        </div>
        <div class="review-section"><h4>Payment</h4>
          <div class="flex-between"><span class="muted">Total</span><span data-bd-total>--</span></div>
          <div class="flex-between"><span class="muted">Paid</span><span data-bd-paid>--</span></div>
          <div class="flex-between"><span class="muted">Balance</span><span data-bd-balance>--</span></div>
          <div class="flex-between"><span class="muted">Status</span><span data-bd-status>--</span></div>
        </div>
        <div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-top:1rem;">
          <a class="btn btn-sm btn-outline" href="receipts.html"><span data-icon="receipt" data-size="16"></span> Receipt</a>
          <button class="btn btn-sm btn-outline" onclick="window.print()"><span data-icon="printer" data-size="16"></span> Print</button>
        </div>
      </div>
    </section>

    <div style="display:grid;gap:1.5rem;">
      <section class="panel">
        <div class="panel-head"><h2>Payment history</h2></div>
        <div class="panel-body no-pad">
          <div class="table-wrap"><table class="table">
            <thead><tr><th>Reference</th><th>Method</th><th class="hide-sm">Date</th><th>Amount</th><th>Status</th></tr></thead>
            <tbody data-tbody="bd-payments"></tbody>
          </table></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h2>Booking history</h2></div>
        <div class="panel-body"><div class="activity-list" data-bd-activity></div></div>
      </section>
    </div>
  </div>
""", """
(function(){
  var params=new URLSearchParams(location.search);
  var ref=params.get("ref")||"J1-2048";
  var b={ref:ref,guest:"Amina Yusuf",contact:"0803 000 0000 · amina@example.com",room:"201 · Deluxe",ci:"2026-09-09",co:"2026-09-11",total:120000,paid:120000,status:"confirmed"};
  function set(k,v){var n=document.querySelector("[data-bd-"+k+"]"); if(n) n.textContent=v;}
  set("ref",b.ref); set("guest",b.guest); set("contact",b.contact); set("room",b.room);
  set("ci",JONE.formatDate(b.ci)); set("co",JONE.formatDate(b.co));
  set("nights", JONE.nightsBetween(b.ci,b.co)+" nights");
  set("total",JONE.formatNaira(b.total)); set("paid",JONE.formatNaira(b.paid));
  set("balance",JONE.formatNaira(b.total-b.paid));
  set("status", b.status.toUpperCase());
  var tbody=document.querySelector("[data-tbody=bd-payments]");
  tbody.innerHTML='<tr><td>PAY-'+ref+'</td><td>Paystack</td><td class="hide-sm">'+JONE.formatDate("2026-09-08","mid")+'</td><td class="num">'+JONE.formatNaira(b.paid)+'</td><td>'+JONE.dashboard.statusPill("paid")+'</td></tr>';
  var act=document.querySelector("[data-bd-activity]");
  act.innerHTML='<div class="activity-item"><span class="activity-icon"><span data-icon="checkCircle" data-size="18"></span></span><div><p>Booking confirmed</p><div class="activity-time">'+JONE.formatDate("2026-09-08","mid")+'</div></div></div>';
  JONE.icons.inject(document);
  var c=document.querySelector("[data-bd-cancel]");
  c && c.addEventListener("click", async function(){
    var ok=await JONE.ui.confirm({title:"Cancel this booking?",message:"The guest will be notified. This cannot be undone.",confirmText:"Cancel booking",danger:true});
    if(ok) JONE.ui.toast("Booking cancelled.","success");
  });
  var r=document.querySelector("[data-bd-record]");
  r && r.addEventListener("click", function(){ JONE.ui.toast("Payment recorded successfully.","success"); });
  var ch=document.querySelector("[data-bd-checkin]");
  ch && ch.addEventListener("click", function(){ JONE.ui.toast("Guest checked in.","success"); });
})();
""")

# ----------------------------------------------------------------------------
# 4. Guests
# ----------------------------------------------------------------------------
write("guests", "Guests", f"""
<section class="panel">
  <div class="filter-bar">
    <div class="field"><label class="field-label" for="g-q">Search</label><input class="input" id="g-q" placeholder="Name, phone, email"></div>
    <div class="filter-actions"><button class="btn btn-sm" data-new-guest>Add guest</button></div>
  </div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Guest</th><th class="hide-sm">Contact</th><th class="hide-sm">Stays</th><th>Last stay</th><th></th></tr></thead>
      <tbody data-tbody="guests"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {name:"Amina Yusuf",contact:"0803 000 0000",stays:3,last:"2026-09-09"},
    {name:"Chidi Okafor",contact:"0812 000 0000",stays:1,last:"2026-09-12"},
    {name:"Ruth Adebayo",contact:"0705 000 0000",stays:5,last:"2026-09-09"},
    {name:"Emeka Nwosu",contact:"0906 000 0000",stays:2,last:"2026-09-08"}
  ];
  var tbody=document.querySelector("[data-tbody=guests]");
  function render(list){
    if(!list.length){tbody.innerHTML='<tr><td colspan="5"><div class="empty-state"><span data-icon="users"></span><h3>No guests found</h3></div></td></tr>';JONE.icons.inject(tbody);return;}
    tbody.innerHTML=list.map(function(g){
      return '<tr><td><strong>'+JONE.esc(g.name)+'</strong></td><td class="hide-sm">'+JONE.esc(g.contact)+'</td><td class="hide-sm">'+g.stays+'</td><td>'+JONE.formatDate(g.last,"mid")+'</td><td><a class="btn btn-sm btn-outline" href="bookings.html">History</a></td></tr>';
    }).join("");
  }
  var q=document.getElementById("g-q");
  q.addEventListener("input", JONE.debounce(function(){render(data.filter(function(g){return g.name.toLowerCase().includes(q.value.toLowerCase())||g.contact.includes(q.value);}));},200));
  render(data);
  var add=document.querySelector("[data-new-guest]");
  add.addEventListener("click",function(){JONE.ui.toast("Guest profile created (demo state).","success");});
})();
""")

# ----------------------------------------------------------------------------
# 5. Rooms
# ----------------------------------------------------------------------------
write("rooms", "Rooms", f"""
<section class="panel">
  <div class="panel-head"><h2>Room status</h2><div class="panel-actions"><select class="select" id="rm-filter" style="min-width:180px;padding:0.5em 0.8em;font-size:var(--fs-sm);"><option value="">All statuses</option><option>available</option><option>reserved</option><option>occupied</option><option>cleaning</option><option>maintenance</option></select></div></div>
  <div class="panel-body">
    <div class="room-board" data-room-board></div>
  </div>
</section>
<section class="panel">
  <div class="panel-head"><h2>Room types</h2><div class="panel-actions"><a class="btn btn-sm btn-outline" href="room-details.html">Manage types</a></div></div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Type</th><th>Rate / night</th><th class="hide-sm">Capacity</th><th>Available</th><th>Occupied</th></tr></thead>
      <tbody data-tbody="roomtypes"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var rooms=[
    {no:"101",type:"Standard",status:"available"},{no:"102",type:"Standard",status:"cleaning"},
    {no:"103",type:"Standard",status:"available"},{no:"201",type:"Deluxe",status:"occupied"},
    {no:"202",type:"Deluxe",status:"reserved"},{no:"205",type:"Deluxe",status:"available"},
    {no:"112",type:"Executive",status:"occupied"},{no:"305",type:"Standard",status:"reserved"},
    {no:"402",type:"Deluxe",status:"maintenance"},{no:"410",type:"Executive",status:"available"},
    {no:"207",type:"Standard",status:"reserved"},{no:"311",type:"Deluxe",status:"cleaning"}
  ];
  var board=document.querySelector("[data-room-board]");
  function render(){
    var f=document.getElementById("rm-filter").value;
    var list=rooms.filter(function(r){return !f||r.status===f;});
    board.innerHTML=list.map(function(r){
      return '<div class="room-tile"><div class="room-no">'+JONE.esc(r.no)+'</div><div class="room-type">'+JONE.esc(r.type)+'</div><div style="margin-top:0.5rem;">'+JONE.dashboard.statusPill(r.status)+'</div></div>';
    }).join("") || '<div class="empty-state" style="grid-column:1/-1;border:0;"><h3>No rooms</h3></div>';
  }
  render();
  document.getElementById("rm-filter").addEventListener("change",render);
  var types=[
    {name:"Standard",rate:45000,cap:2,av:4,occ:2},{name:"Deluxe",rate:60000,cap:2,av:3,occ:3},{name:"Executive",rate:95000,cap:3,av:2,occ:1}
  ];
  var tb=document.querySelector("[data-tbody=roomtypes]");
  tb.innerHTML=types.map(function(t){return '<tr><td>'+JONE.esc(t.name)+'</td><td class="num">'+JONE.formatNaira(t.rate)+'</td><td class="hide-sm">'+t.cap+'</td><td>'+JONE.dashboard.statusPill("available")+' · '+t.av+'</td><td>'+JONE.dashboard.statusPill("occupied")+' · '+t.occ+'</td></tr>';}).join("");
})();
""")

# ----------------------------------------------------------------------------
# 6. Availability calendar
# ----------------------------------------------------------------------------
write("availability", "Availability", f"""
<section class="panel">
  <div class="panel-head">
    <h2>Room availability</h2>
    <div class="panel-actions">
      <button class="btn btn-sm btn-outline" data-av-prev>‹ Prev</button>
      <input class="input" type="date" id="av-from" style="width:150px;padding:0.5em 0.8em;font-size:var(--fs-sm);">
      <button class="btn btn-sm btn-outline" data-av-next>Next ›</button>
    </div>
  </div>
  <div class="panel-body no-pad">
    <div class="avo-legend">
      <span><i style="background:var(--color-success-bg);border:1px solid var(--color-border);"></i> Available</span>
      <span><i style="background:var(--color-warning-bg);border:1px solid var(--color-border);"></i> Reserved</span>
      <span><i style="background:var(--color-info-bg);border:1px solid var(--color-border);"></i> Occupied</span>
      <span><i style="background:var(--color-danger-bg);border:1px solid var(--color-border);"></i> Maintenance</span>
    </div>
    <div class="avo-scroller"><table class="avo-table" data-avo></table></div>
  </div>
</section>
""", """
(function(){
  var state={from:JONE.todayISO(0)};
  var rooms=["101","102","103","201","202","205","112","305","402","410","207","311"];
  var types={101:"Std",102:"Std",103:"Std",201:"Dlx",202:"Dlx",205:"Dlx",112:"Exe",305:"Std",402:"Dlx",410:"Exe",207:"Std",311:"Dlx"};
  var statuses=["free","free","reserved","free","occupied","free","occupied","reserved","maintenance","free","reserved","cleaning"];
  function render(){
    var table=document.querySelector("[data-avo]");
    var rowName=rooms.map(function(r){ return '<th style="text-align:left;min-width:70px;">'+r+' <span style="color:var(--color-text-faint);font-weight:400;">'+types[r]+'</span></th>'; }).join("");
    var cols=7;
    var header='<tr><th style="text-align:left;min-width:130px;">Room</th>'+rowName+'</tr>';
    var body="";
    for(var d=0;d<cols;d++){
      var dt=new Date(state.from); dt.setDate(dt.getDate()+d);
      var wd=dt.toLocaleDateString("en-GB",{weekday:"short"});
      var num=dt.getDate();
      body+='<tr><th style="text-align:left;color:var(--color-text-muted);">'+wd+' '+num+'</th>';
      body+=rooms.map(function(r,i){
        // naive demo pattern
        var st=statuses[(i+d)%statuses.length];
        return '<td><span class="avo-cell '+st+'" title="'+JONE.esc(st)+'"></span></td>';
      }).join("");
      body+='</tr>';
    }
    table.innerHTML=header+body;
  }
  var inp=document.getElementById("av-from");
  inp.value=state.from;
  inp.addEventListener("change",function(){state.from=inp.value;render();});
  document.querySelector("[data-av-prev]").addEventListener("click",function(){var d=new Date(state.from);d.setDate(d.getDate()-7);state.from=d.toISOString().slice(0,10);inp.value=state.from;render();});
  document.querySelector("[data-av-next]").addEventListener("click",function(){var d=new Date(state.from);d.setDate(d.getDate()+7);state.from=d.toISOString().slice(0,10);inp.value=state.from;render();});
  render();
})();
""")

# ----------------------------------------------------------------------------
# 7. Check-in
# ----------------------------------------------------------------------------
write("check-in", "Check-in", f"""
<section class="panel">
  <div class="panel-head"><h2>Today's arrivals</h2></div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Reference</th><th>Guest</th><th class="hide-sm">Room</th><th>Arrival</th><th class="hide-sm">Balance</th><th></th></tr></thead>
      <tbody data-tbody="checkin"></tbody>
    </table></div>
  </div>
</section>
<section class="panel">
  <div class="panel-head"><h2>Find a booking to check in</h2></div>
  <div class="panel-body">
    <div class="form-grid fg-2">
      <div class="field"><label class="field-label" for="chi-q">Booking reference or guest name</label><input class="input" id="chi-q" placeholder="e.g. J1-2048"></div>
      <div class="field" style="display:flex;align-items:end;"><button class="btn" data-chi-search style="width:100%;">Search</button></div>
    </div>
  </div>
</section>
""", """
(function(){
  var data=[
    {ref:"J1-2046",guest:"Ruth Adebayo",room:"112",arrival:"Today",balance:0},
    {ref:"J1-2048",guest:"Amina Yusuf",room:"201",arrival:"Today",balance:0},
    {ref:"J1-2044",guest:"Emeka Nwosu",room:"402",arrival:"Today",balance:45000}
  ];
  var tbody=document.querySelector("[data-tbody=checkin]");
  function render(list){
    tbody.innerHTML=list.map(function(b){
      return '<tr><td>'+JONE.esc(b.ref)+'</td><td>'+JONE.esc(b.guest)+'</td><td class="hide-sm">'+JONE.esc(b.room)+'</td><td>'+JONE.esc(b.arrival)+'</td><td class="hide-sm num">'+(b.balance?JONE.formatNaira(b.balance):"<span class='text-success'>Settled</span>")+'</td><td><button class="btn btn-sm btn-accent" data-checkin-btn="'+b.ref+'">Check in</button></td></tr>';
    }).join("") || '<tr><td colspan="6"><div class="empty-state"><span data-icon="logOut"></span><h3>No arrivals today</h3></div></td></tr>';
    JONE.icons.inject(tbody);
  }
  render(data);
  document.querySelector("[data-chi-search]").addEventListener("click",function(){
    var q=document.getElementById("chi-q").value.trim();
    render(data.filter(function(b){return b.ref.toLowerCase().includes(q.toLowerCase())||b.guest.toLowerCase().includes(q.toLowerCase());}));
  });
  document.addEventListener("click",function(e){
    var btn=e.target.closest("[data-checkin-btn]");
    if(btn){JONE.ui.toast("Guest checked into room successfully.","success");}
  });
})();
""")

# ----------------------------------------------------------------------------
# 8. Check-out
# ----------------------------------------------------------------------------
write("check-out", "Check-out", f"""
<section class="panel">
  <div class="panel-head"><h2>Today's departures</h2></div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Reference</th><th>Guest</th><th class="hide-sm">Room</th><th>Total</th><th class="hide-sm">Paid</th><th>Balance</th><th></th></tr></thead>
      <tbody data-tbody="checkout"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {ref:"J1-2043",guest:"Bola Salami",room:"208",total:60000,paid:60000},
    {ref:"J1-2040",guest:"Tunde Bakare",room:"311",total:120000,paid:60000}
  ];
  var tbody=document.querySelector("[data-tbody=checkout]");
  function render(list){
    tbody.innerHTML=list.map(function(b){
      var bal=b.total-b.paid;
      return '<tr><td>'+JONE.esc(b.ref)+'</td><td>'+JONE.esc(b.guest)+'</td><td class="hide-sm">'+JONE.esc(b.room)+'</td><td class="num">'+JONE.formatNaira(b.total)+'</td><td class="hide-sm num">'+JONE.formatNaira(b.paid)+'</td><td class="num '+(bal?"text-danger":"text-success")+'">'+JONE.formatNaira(bal)+'</td><td><button class="btn btn-sm btn-accent" data-checkout-btn="'+b.ref+'">Check out</button></td></tr>';
    }).join("") || '<tr><td colspan="7"><div class="empty-state"><span data-icon="logOut"></span><h3>No departures today</h3></div></td></tr>';
    JONE.icons.inject(tbody);
  }
  render(data);
  document.addEventListener("click",function(e){
    var btn=e.target.closest("[data-checkout-btn]");
    if(btn){JONE.ui.toast("Guest checked out successfully.","success");}
  });
})();
""")

# ----------------------------------------------------------------------------
# 9. Payments
# ----------------------------------------------------------------------------
write("payments", "Payments", f"""
<section class="panel">
  <div class="filter-bar">
    <div class="field"><label class="field-label" for="p-q">Search</label><input class="input" id="p-q" placeholder="Reference, guest"></div>
    <div class="field"><label class="field-label" for="p-method">Method</label><select class="select" id="p-method"><option value="">All</option><option>paystack</option><option>cash</option><option>pos</option><option>bank_transfer</option></select></div>
    <div class="field"><label class="field-label" for="p-status">Status</label><select class="select" id="p-status"><option value="">All</option><option>paid</option><option>pending</option><option>failed</option></select></div>
  </div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Payment ref</th><th>Booking</th><th class="hide-sm">Guest</th><th>Method</th><th class="hide-sm">Date</th><th>Amount</th><th>Status</th><th class="hide-sm">By</th></tr></thead>
      <tbody data-tbody="payments"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {ref:"PAY-8821",booking:"J1-2048",guest:"Amina Yusuf",method:"paystack",date:"2026-09-08",amount:120000,status:"paid",by:"Online"},
    {ref:"PAY-8819",booking:"J1-2047",guest:"Chidi Okafor",method:"cash",date:"2026-09-09",amount:45000,status:"paid",by:"Reception"},
    {ref:"PAY-8815",booking:"J1-2046",guest:"Ruth Adebayo",method:"bank_transfer",date:"2026-09-07",amount:285000,status:"partial",by:"M. Johns"}
  ];
  var tbody=document.querySelector("[data-tbody=payments]");
  function render(list){
    if(!list.length){tbody.innerHTML='<tr><td colspan="8"><div class="empty-state"><span data-icon="creditCard"></span><h3>No payments found</h3></div></td></tr>';JONE.icons.inject(tbody);return;}
    tbody.innerHTML=list.map(function(p){
      return '<tr><td>'+JONE.esc(p.ref)+'</td><td><a href="booking-details.html?ref='+p.booking+'">'+JONE.esc(p.booking)+'</a></td><td class="hide-sm">'+JONE.esc(p.guest)+'</td><td>'+JONE.esc(p.method.replace(/_/g," "))+'</td><td class="hide-sm">'+JONE.formatDate(p.date,"mid")+'</td><td class="num">'+JONE.formatNaira(p.amount)+'</td><td>'+JONE.dashboard.statusPill(p.status)+'</td><td class="hide-sm">'+JONE.esc(p.by)+'</td></tr>';
    }).join("");
  }
  render(data);
})();
""")

# ----------------------------------------------------------------------------
# 10. Receipts
# ----------------------------------------------------------------------------
write("receipts", "Receipts", f"""
<section class="panel">
  <div class="filter-bar">
    <div class="field"><label class="field-label" for="rc-q">Search</label><input class="input" id="rc-q" placeholder="Booking ref, receipt no."></div>
  </div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Receipt</th><th>Booking</th><th class="hide-sm">Guest</th><th>Amount</th><th class="hide-sm">Issued</th><th></th></tr></thead>
      <tbody data-tbody="receipts"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {no:"RCT-1023",booking:"J1-2048",guest:"Amina Yusuf",amount:120000,issued:"2026-09-08"},
    {no:"RCT-1021",booking:"J1-2046",guest:"Ruth Adebayo",amount:285000,issued:"2026-09-07"}
  ];
  var tbody=document.querySelector("[data-tbody=receipts]");
  tbody.innerHTML=data.map(function(r){
    return '<tr><td>'+JONE.esc(r.no)+'</td><td>'+JONE.esc(r.booking)+'</td><td class="hide-sm">'+JONE.esc(r.guest)+'</td><td class="num">'+JONE.formatNaira(r.amount)+'</td><td class="hide-sm">'+JONE.formatDate(r.issued,"mid")+'</td><td><a class="btn btn-sm btn-outline" href="receipts.html"><span data-icon="printer" data-size="15"></span> View</a></td></tr>';
  }).join("");
  JONE.icons.inject(tbody);
})();
""")

# ----------------------------------------------------------------------------
# 11. Reports
# ----------------------------------------------------------------------------
write("reports", "Reports", f"""
<section class="panel">
  <div class="filter-bar">
    <label class="field-label" style="align-self:center;">Period:</label>
    <div class="field"><select class="select" id="rp-range"><option>Today</option><option>Yesterday</option><option>This week</option><option selected>This month</option><option>Custom</option></select></div>
    <div class="field"><label class="field-label" for="rp-from">From</label><input class="input" type="date" id="rp-from"></div>
    <div class="field"><label class="field-label" for="rp-to">To</label><input class="input" type="date" id="rp-to"></div>
  </div>
  <div class="panel-body">
    <div class="kpi-grid">
      <div class="kpi"><div class="kpi-label">Revenue</div><div class="kpi-value">₦1.28m</div><div class="kpi-sub"><span class="up">▲ 12%</span> vs last month</div></div>
      <div class="kpi"><div class="kpi-label">Bookings</div><div class="kpi-value">46</div><div class="kpi-sub">38 online · 8 manual</div></div>
      <div class="kpi"><div class="kpi-label">Occupancy</div><div class="kpi-value">78%</div><div class="kpi-sub">available 4 · occupied 12</div></div>
      <div class="kpi"><div class="kpi-label">Outstanding</div><div class="kpi-value">₦96,500</div><div class="kpi-sub">3 partial payments</div></div>
    </div>

    <div class="panel-grid" style="margin-top:1.5rem;">
      <section class="panel" style="border:1px solid var(--color-border);">
        <div class="panel-head"><h3>Revenue by method</h3></div>
        <div class="panel-body no-pad"><div class="table-wrap"><table class="table">
          <thead><tr><th>Method</th><th>Amount</th><th class="hide-sm">Share</th></tr></thead>
          <tbody data-tbody="report-methods"></tbody>
        </table></div></div>
      </section>
      <section class="panel" style="border:1px solid var(--color-border);">
        <div class="panel-head"><h3>Bookings summary</h3></div>
        <div class="panel-body no-pad"><div class="table-wrap"><table class="table">
          <thead><tr><th>Metric</th><th>Count</th></tr></thead>
          <tbody data-tbody="report-bookings"></tbody>
        </table></div></div>
      </section>
    </div>
    <div style="margin-top:1.5rem;display:flex;gap:0.75rem;">
      <button class="btn btn-sm btn-outline" onclick="JONE.ui.toast('Export started (CSV).','success')"><span data-icon="download" data-size="16"></span> Export CSV</button>
    </div>
  </div>
</section>
""", """
(function(){
  var methods=[{m:"Paystack",a:842000,s:"66%"},{m:"Cash",a:205000,s:"16%"},{m:"POS",a:158000,s:"12%"},{m:"Bank transfer",a:75000,s:"6%"}];
  document.querySelector("[data-tbody=report-methods]").innerHTML=methods.map(function(x){return '<tr><td>'+JONE.esc(x.m)+'</td><td class="num">'+JONE.formatNaira(x.a)+'</td><td class="hide-sm">'+x.s+'</td></tr>';}).join("");
  var bk=[["Total bookings","46"],["Online","38"],["Manual","8"],["Cancelled","3"],["No-shows","1"],["Check-ins","34"],["Check-outs","29"]];
  document.querySelector("[data-tbody=report-bookings]").innerHTML=bk.map(function(x){return '<tr><td>'+JONE.esc(x[0])+'</td><td class="num">'+x[1]+'</td></tr>';}).join("");
  JONE.icons.inject(document);
})();
""")

# ----------------------------------------------------------------------------
# 12. Facilities (content mgmt)
# ----------------------------------------------------------------------------
write("facilities", "Facilities", f"""
<section class="panel">
  <div class="panel-head"><h2>Facilities</h2><div class="panel-actions"><button class="btn btn-sm" data-fac-add>Add facility</button></div></div>
  <div class="panel-body">
    <div class="facility-grid" data-facility-grid></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {name:"Restaurant",desc:"Daily meals and room service.",status:"active"},
    {name:"Wi-Fi",desc:"High-speed internet in rooms and common areas.",status:"active"},
    {name:"Parking",desc:"Secure parking on site.",status:"active"},
    {name:"Laundry",desc:"Same-day laundry service.",status:"active"},
    {name:"Event hall",desc:"Space for gatherings and functions.",status:"inactive"}
  ];
  var grid=document.querySelector("[data-facility-grid]");
  function render(){
    grid.innerHTML=data.map(function(f,i){
      return '<div class="facility-item" style="flex-direction:column;"><div class="flex-between"><div class="facility-icon"><span data-icon="building" data-size="22"></span></div>'+JONE.dashboard.statusPill(f.status)+'</div><div><h4>'+JONE.esc(f.name)+'</h4><p>'+JONE.esc(f.desc)+'</p></div><div style="display:flex;gap:0.5rem;"><button class="btn btn-sm btn-outline" data-fac-edit="'+i+'">Edit</button><button class="btn btn-sm btn-danger" data-fac-del="'+i+'">Delete</button></div></div>';
    }).join("");
    JONE.icons.inject(grid);
  }
  render();
  document.addEventListener("click",function(e){
    var del=e.target.closest("[data-fac-del]");
    if(del){JONE.ui.confirm({title:"Remove this facility?",message:"The facility will be removed from the site.",confirmText:"Delete",danger:true}).then(function(ok){if(ok){data.splice(+del.dataset.facDel,1);render();JONE.ui.toast("Facility removed.","success");}});}
    var edit=e.target.closest("[data-fac-edit]");
    if(edit){JONE.ui.toast("Edit facility (dev state).","info");}
  });
  var add=document.querySelector("[data-fac-add]");
  add.addEventListener("click",function(){JONE.ui.toast("Add facility (dev state).","info");});
})();
""")

# ----------------------------------------------------------------------------
# 13. Gallery (content mgmt)
# ----------------------------------------------------------------------------
write("gallery", "Gallery", f"""
<section class="panel">
  <div class="panel-head"><h2>Gallery &amp; media</h2><div class="panel-actions"><button class="btn btn-sm" data-gal-upload>Upload media</button></div></div>
  <div class="panel-body">
    <div class="gallery-grid" data-gallery-grid></div>
  </div>
</section>
""", """
(function(){
  var items=[
    {src:"assets/images/hero.jpg",cat:"Rooms",cap:"Deluxe room",status:"active"},
    {src:"assets/images/intro.jpg",cat:"Hotel",cap:"Lobby",status:"active"},
    {src:"assets/images/experience.jpg",cat:"Facilities",cap:"Restaurant",status:"active"},
    {src:"assets/images/location.jpg",cat:"Exterior",cap:"Entrance",status:"active"}
  ];
  var grid=document.querySelector("[data-gallery-grid]");
  grid.innerHTML=items.map(function(g,i){
    var img=g.src?'<img src="'+g.src+'" alt="'+JONE.esc(g.cap)+'">':'<div class="placeholder-placeholder"><span data-icon="image"></span></div>';
    return '<div class="media wide" style="position:relative;"><div class="media" style="position:absolute;inset:0;aspect-ratio:auto;">'+img+'</div><div class="media-actions" style="position:absolute;top:0.5rem;right:0.5rem;z-index:2;display:flex;gap:0.4rem;"><button class="btn-icon btn-sm btn-outline" style="background:var(--color-surface);" data-gal-edit="'+i+'" aria-label="Edit"><span data-icon="edit" data-size="16"></span></button><button class="btn-icon btn-sm btn-danger" data-gal-del="'+i+'" aria-label="Delete"><span data-icon="trash" data-size="16"></span></button></div>'+(g.status==="inactive"?'<span class="badge" style="position:absolute;bottom:0.5rem;left:0.5rem;z-index:2;">Inactive</span>':'')+'</div>';
  }).join("");
  JONE.icons.inject(grid);
  document.addEventListener("click",function(e){
    var del=e.target.closest("[data-gal-del]");
    if(del){JONE.ui.confirm({title:"Delete this image?",message:"This will remove the media from the gallery.",danger:true}).then(function(ok){if(ok){items.splice(+del.dataset.galDel,1);location.reload();}});}
  });
  var up=document.querySelector("[data-gal-upload]");
  up.addEventListener("click",function(){JONE.ui.toast("Upload interface (dev state).","info");});
})();
""")

# ----------------------------------------------------------------------------
# 14. Offers (content mgmt)
# ----------------------------------------------------------------------------
write("offers", "Offers", f"""
<section class="panel">
  <div class="panel-head"><h2>Offers</h2><div class="panel-actions"><button class="btn btn-sm" data-of-add>Create offer</button></div></div>
  <div class="panel-body">
    <div class="room-grid" data-offer-grid></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {title:"Early-bird weekend",desc:"Save on weekend stays booked 7 days ahead.",disc:"10%",status:"active",ahead:"2026-09-30"},
    {title:"Long-stay reward",desc:"A discounted rate for stays of 5+ nights.",disc:"15%",status:"active",ahead:"2026-12-31"},
    {title:"Summer special",desc:"Limited-time seasonal offer.",disc:"20%",status:"expired",ahead:"2026-08-31"}
  ];
  var grid=document.querySelector("[data-offer-grid]");
  grid.innerHTML=data.map(function(o,i){
    return '<article class="card card-hover"><div class="card-pad"><div class="flex-between" style="margin-bottom:1rem;"><span class="offer-tag">'+JONE.esc(o.disc||"")+'</span>'+JONE.dashboard.statusPill(o.status)+'</div><h3 style="font-size:var(--fs-lg);">'+JONE.esc(o.title)+'</h3><p class="caption">'+JONE.esc(o.desc)+'</p><p class="caption">Ends '+JONE.formatDate(o.ahead,"mid")+'</p><div style="display:flex;gap:0.5rem;margin-top:1rem;"><button class="btn btn-sm btn-outline" data-of-edit="'+i+'">Edit</button><button class="btn btn-sm btn-danger" data-of-del="'+i+'">Delete</button></div></div></article>';
  }).join("");
  document.addEventListener("click",function(e){
    var del=e.target.closest("[data-of-del]");
    if(del){JONE.ui.confirm({title:"Delete this offer?",danger:true}).then(function(ok){if(ok){data.splice(+del.dataset.ofDel,1);location.reload();}});}
  });
  window.OFFERS=data;
  document.querySelector("[data-of-add]").addEventListener("click",function(){
    JONE.ui.modal.open({title:"Create offer",body:JONE.el("div",{}, "", document.createTextNode("Form fields: title, description, discount, date range, image."))});
  });
})();
""")

# ----------------------------------------------------------------------------
# 15. Enquiries
# ----------------------------------------------------------------------------
write("enquiries", "Enquiries", f"""
<section class="panel">
  <div class="panel-head"><h2>Enquiries</h2><div class="panel-actions"><select class="select" id="en-status" style="min-width:160px;font-size:var(--fs-sm);padding:0.5em 0.8em;"><option value="">All</option><option>new</option><option>replied</option><option>archived</option></select></div></div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Name</th><th class="hide-sm">Contact</th><th>Subject</th><th class="hide-sm">Received</th><th>Status</th><th></th></tr></thead>
      <tbody data-tbody="enquiries"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {name:"Blessing Okoro",contact:"0701 000 0000",subject:"Room availability",date:"2026-09-09 09:10",status:"new"},
    {name:"Daniel Eze",contact:"0905 000 0000",subject:"Event hall booking",date:"2026-09-08 16:45",status:"replied"},
    {name:"Ngozi Umeh",contact:"0806 000 0000",subject:"Long-stay discount",date:"2026-09-07 11:20",status:"new"}
  ];
  var tbody=document.querySelector("[data-tbody=enquiries]");
  function render(list){
    tbody.innerHTML=list.map(function(e,i){
      return '<tr><td><strong>'+JONE.esc(e.name)+'</strong></td><td class="hide-sm">'+JONE.esc(e.contact)+'</td><td>'+JONE.esc(e.subject)+'</td><td class="hide-sm">'+JONE.formatDateTime(e.date)+'</td><td>'+JONE.dashboard.statusPill(e.status)+'</td><td><div style="display:flex;gap:0.4rem;"><button class="btn btn-sm btn-outline" data-en-view="'+i+'">View</button><button class="btn btn-sm btn-ghost" data-en-meta="'+i+'"></button></div></td></tr>';
    }).join("") || '<tr><td colspan="6"><div class="empty-state"><span data-icon="inbox"></span><h3>No enquiries</h3><p>You are all caught up.</p></div></td></tr>';
    JONE.icons.inject(tbody);
  }
  render(data);
  document.addEventListener("click",function(e){
    var v=e.target.closest("[data-en-view]");
    if(v){JONE.ui.toast("Enquiry opened.","info");}
  });
})();
""")

# ----------------------------------------------------------------------------
# 16. Notifications
# ----------------------------------------------------------------------------
write("notifications", "Notifications", f"""
<section class="panel">
  <div class="panel-head"><h2>Notifications</h2><div class="panel-actions"><button class="btn btn-sm btn-outline" data-notif-all>Mark all read</button></div></div>
  <div class="notif-list" data-notif-list></div>
</section>
""", """
(function(){
  var data=[
    {icon:"calendar",title:"New booking J1-2050",msg:"A new booking was confirmed for 12 Sep.",time:"5 minutes ago",unread:true},
    {icon:"wallet",title:"Payment received",msg:"₦60,000 was recorded for J1-2048.",time:"1 hour ago",unread:true},
    {icon:"message",title:"New enquiry",msg:"Blessing Okoro asked about availability.",time:"2 hours ago",unread:false},
    {icon:"logOut",title:"Check-in due",msg:"Room 201 check-in is due today.",time:"4 hours ago",unread:false}
  ];
  var list=document.querySelector("[data-notif-list]");
  function render(){
    var unread=data.filter(function(n){return n.unread;}).length;
    list.innerHTML=data.map(function(n,i){
      return '<div class="notif-item'+(n.unread?" unread":"")+'"><span class="notif-icon"><span data-icon="'+n.icon+'" data-size="18"></span></span><div class="notif-body"><p class="notif-title">'+JONE.esc(n.title)+'</p><p>'+JONE.esc(n.msg)+'</p><div class="notif-meta">'+JONE.esc(n.time)+'</div></div></div>';
    }).join("") || '<div class="empty-state" style="margin:1.5rem;"><span data-icon="bell"></span><h3>You are all caught up</h3></div>';
    JONE.icons.inject(list);
  }
  render();
  document.querySelector("[data-notif-all]").addEventListener("click",function(){data.forEach(function(n){n.unread=false;});render();JONE.ui.toast("All notifications marked as read.","success");});
})();
""")

# ----------------------------------------------------------------------------
# 17. Audit logs
# ----------------------------------------------------------------------------
write("audit-logs", "Audit Logs", f"""
<section class="panel">
  <div class="panel-head"><h2>Audit log</h2><div class="panel-actions"><select class="select" id="al-filter" style="min-width:180px;font-size:var(--fs-sm);padding:0.5em 0.8em;"><option value="">All actions</option><option>booking_created</option><option>payment_recorded</option><option>check_in</option><option>check_out</option><option>booking_cancelled</option></select></div></div>
  <div class="panel-body no-pad">
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Time</th><th>User</th><th>Action</th><th class="hide-sm">Detail</th><th class="hide-sm">IP</th></tr></thead>
      <tbody data-tbody="audit"></tbody>
    </table></div>
  </div>
</section>
""", """
(function(){
  var data=[
    {t:"2026-09-09 09:42",u:"Reception",a:"payment_recorded",d:"₦120,000 for J1-2048",ip:"192.168.1.4"},
    {t:"2026-09-09 08:58",u:"Reception",a:"check_in",d:"Room 201 · J1-2048",ip:"192.168.1.4"},
    {t:"2026-09-09 08:20",u:"Manager",a:"booking_created",d:"J1-2050",ip:"192.168.1.7"},
    {t:"2026-09-08 19:15",u:"Admin",a:"settings_changed",d:"Updated check-out time",ip:"192.168.1.9"}
  ];
  var tbody=document.querySelector("[data-tbody=audit]");
  tbody.innerHTML=data.map(function(e){
    return '<tr><td class="caption">'+JONE.formatDateTime(e.t)+'</td><td>'+JONE.esc(e.u)+'</td><td><span class="badge">'+JONE.esc(e.a.replace(/_/g," "))+'</span></td><td class="hide-sm">'+JONE.esc(e.d)+'</td><td class="hide-sm caption">'+JONE.esc(e.ip)+'</td></tr>';
  }).join("");
  JONE.icons.inject(tbody);
  document.getElementById("al-filter").addEventListener("change",function(e){
    var f=e.target.value;
    document.querySelectorAll("[data-tbody=audit] tr").forEach(function(tr){
      tr.style.display=(!f||tr.textContent.toLowerCase().includes(f.replace(/_/g," ")))?"":"none";
    });
  });
})();
""")

# ----------------------------------------------------------------------------
# 18. Settings
# ----------------------------------------------------------------------------
write("settings", "Settings", f"""
<section class="panel">
  <div class="panel-head"><h2>Hotel information</h2><button class="btn btn-sm" data-settings-save>Save</button></div>
  <div class="panel-body">
    <div class="field"><label class="field-label" for="s-name">Hotel name</label><input class="input" id="s-name" value="J-ONE HOTEL &amp; LODGE"></div>
    <div class="field"><label class="field-label" for="s-addr">Address</label><input class="input" id="s-addr" value="Plot 566 Mgbowo Street, off Ezike Street"></div>
    <div class="form-grid fg-2" style="margin-bottom:1rem;">
      <div class="field"><label class="field-label" for="s-phone">Phone</label><input class="input" id="s-phone" value="+234 803 211 2874"></div>
      <div class="field"><label class="field-label" for="s-email">Email</label><input class="input" id="s-email" value="jonathanonu76@gmail.com"></div>
    </div>
    <div class="field"><label class="field-label" for="s-maps">Google Maps URL</label><input class="input" id="s-maps" value="https://www.google.com/maps"></div>
  </div>
</section>
<section class="panel">
  <div class="panel-head"><h2>Stay &amp; policies</h2><button class="btn btn-sm" data-settings-save>Save</button></div>
  <div class="panel-body">
    <div class="form-grid fg-3">
      <div class="field"><label class="field-label" for="s-ci">Check-in time</label><input class="input" id="s-ci" type="time" value="14:00"></div>
      <div class="field"><label class="field-label" for="s-co">Check-out time</label><input class="input" id="s-co" type="time" value="12:00"></div>
      <div class="field"><label class="field-label" for="s-min">Minimum stay (nights)</label><input class="input" id="s-min" type="number" value="1"></div>
    </div>
    <div class="field"><label class="field-label" for="s-pol">Cancellation policy</label><textarea class="textarea" id="s-pol">Free cancellation up to 24 hours before check-in.</textarea></div>
    <div class="field"><label class="field-label" for="s-ref">Refund policy</label><textarea class="textarea" id="s-ref">Refunds are processed to the original payment method within 5–7 business days.</textarea></div>
  </div>
</section>
""", """
(function(){
  document.querySelectorAll("[data-settings-save]").forEach(function(b){
    b.addEventListener("click",function(){JONE.ui.toast("Settings saved successfully.","success");});
  });
})();
""")

# ----------------------------------------------------------------------------
# 19. Profile
# ----------------------------------------------------------------------------
write("profile", "Profile", f"""
<section class="panel" style="max-width:640px;">
  <div class="panel-head"><h2>My profile</h2></div>
  <div class="panel-body">
    <div class="field"><label class="field-label" for="pf-name">Full name</label><input class="input" id="pf-name" value="Reception Staff"></div>
    <div class="field"><label class="field-label" for="pf-email">Email</label><input class="input" id="pf-email" type="email" value="staff@j-onehotel.com"></div>
    <div class="field"><label class="field-label" for="pf-pass">New password</label><input class="input" id="pf-pass" type="password" placeholder="Leave blank to keep current"></div>
    <button class="btn" data-profile-save>Save changes</button>
  </div>
</section>
""", """
(function(){
  document.querySelector("[data-profile-save]").addEventListener("click",function(){JONE.ui.toast("Profile updated.","success");});
})();
""")

# ----------------------------------------------------------------------------
# 20. Room details (staff view of room type)
# ----------------------------------------------------------------------------
write("room-details", "Room Type", f"""
<section class="panel">
  <div class="panel-head"><h2>Room type &amp; pricing</h2><div class="panel-actions"><a class="btn btn-sm btn-outline" href="rooms.html">Back to rooms</a></div></div>
  <div class="panel-body">
    <div class="form-grid fg-3">
      <div class="field"><label class="field-label" for="rd-name">Name</label><input class="input" id="rd-name" value="Deluxe Room"></div>
      <div class="field"><label class="field-label" for="rd-rate">Rate / night (₦)</label><input class="input" id="rd-rate" type="number" value="60000"></div>
      <div class="field"><label class="field-label" for="rd-cap">Capacity</label><input class="input" id="rd-cap" type="number" value="2"></div>
    </div>
    <div class="field"><label class="field-label" for="rd-size">Size</label><input class="input" id="rd-size" value="24 m²"></div>
    <div class="field"><label class="field-label" for="rd-desc">Description</label><textarea class="textarea" id="rd-desc">A calm, spacious room with a king bed, work desk and en-suite bathroom.</textarea></div>
    <button class="btn" data-room-save>Save room type</button>
  </div>
</section>
""", """
(function(){
  document.querySelector("[data-room-save]").addEventListener("click",function(){JONE.ui.toast("Room type updated.","success");});
})();
""")

# ----------------------------------------------------------------------------
# 21. 403
# ----------------------------------------------------------------------------
write("403", "Access Denied", f"""
<section style="text-align:center;padding:4rem 1rem;">
  <div style="font-family:var(--font-display);font-size:5rem;color:var(--color-heading);">403</div>
  <h2>You don't have permission</h2>
  <p class="lede" style="max-width:46ch;margin:1rem auto 2rem;">This area is restricted. Ask an administrator to grant access, or return to your dashboard.</p>
  <div style="display:flex;gap:0.75rem;justify-content:center;flex-wrap:wrap;">
    <a class="btn" href="index.html">Back to dashboard</a>
    <a class="btn btn-outline" href="../login.html">Sign out</a>
  </div>
</section>
""")

print("All dashboard pages generated.")
