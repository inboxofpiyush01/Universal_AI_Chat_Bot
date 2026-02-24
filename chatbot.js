/**
 * ChatBot SaaS Widget v10.1 - CrewAI Edition
 * Multi-tenant: requires data-client-id and data-api-key
 * New: shows colored agent badge on each response
 */
(function () {
  "use strict";
  if (window.__cbv10) return;
  window.__cbv10 = true;

  var script    = document.currentScript || document.querySelector('script[data-client-id]');
  var CLIENT_ID = script && script.getAttribute("data-client-id");
  var API_KEY   = script && script.getAttribute("data-api-key");
  var API_URL   = (script && script.src || "").replace("/widget/chatbot.js", "") || "http://localhost:8000";
  if (!CLIENT_ID || !API_KEY) return;

  var isOpen = false, isTyping = false, sessionId = null;
  var userId = null;
  var botName = "Assistant", bizName = "Our Store";
  var botColor = "#ff3f6c";  // overridden from config API
  var chatHistory = [];
  var chipIndex = 0;

  try { isOpen = sessionStorage.getItem("_cb_open") === "1"; } catch(e) {}
  try { sessionId = sessionStorage.getItem("_cb_sid"); } catch(e) {}
  try { userId = localStorage.getItem("_cb_uid"); } catch(e) {}
  if (!userId) { userId = "user_" + Math.random().toString(36).substr(2,9); try { localStorage.setItem("_cb_uid", userId); } catch(e) {} }
  try { var sv = sessionStorage.getItem("_cb_h10"); if (sv) chatHistory = JSON.parse(sv); } catch(e) {}

  // No hardcoded products — cards come dynamically from the API (RAG context)
  var AGENT_COLORS = {
    "RAG Search Agent":       "#6366f1",
    "Sales Agent":            "#ff3f6c",
    "Comparison Agent":       "#0ea5e9",
    "Customer Support Agent": "#22c55e"
  };

  var ALL_CHIPS = [
    {i:"🔍",t:"What products do you have?"},{i:"💰",t:"What are your cheapest options?"},
    {i:"⭐",t:"What are your best sellers?"},{i:"💎",t:"Show me premium products"},
    {i:"📦",t:"What is your delivery policy?"},{i:"🔄",t:"What is your return policy?"},
    {i:"🏪",t:"Where are your stores?"},{i:"📞",t:"How can I contact you?"},
    {i:"🤔",t:"Help me choose the right product"},{i:"🔧",t:"Do you offer installation?"},
    {i:"⚡",t:"Any ongoing offers or discounts?"},{i:"📋",t:"What are your product categories?"}
  ];

  function getNextChips() {
    var chips = [];
    for (var i = 0; i < 4; i++) chips.push(ALL_CHIPS[(chipIndex + i) % ALL_CHIPS.length]);
    chipIndex = (chipIndex + 4) % ALL_CHIPS.length;
    return chips;
  }

  function getProducts(apiProds) {
    // Products come directly from the API (extracted from crawled website content)
    // No fallback needed — if API returns nothing, no cards shown
    if (!apiProds || !apiProds.length) return [];
    return apiProds.slice(0, 3).map(function(p) {
      return {
        title: p.title || "",
        price: p.price || "",
        size:  p.size  || "",
        url:   p.url   || "#",
        image: p.image || "",
      };
    });
  }

  function boot() { loadConfig().then(function(){ injectCSS(); buildDOM(); bindEvents(); restoreOrGreet(); if(isOpen) openChat(true); }); }

  async function loadConfig() {
    try {
      var r = await fetch(API_URL + "/api/chat/config/" + CLIENT_ID, {signal: AbortSignal.timeout(4000)});
      if (r.ok) {
        var d = await r.json();
        botName  = d.bot_name      || botName;
        bizName  = d.business_name || bizName;
        botColor = d.bot_color     || botColor;
      }
    } catch(e) {}
  }

  function injectCSS() {
    if (document.getElementById("_cbcss10")) return;
    var c = botColor || "#ff3f6c";
    // Create a slightly lighter version for gradients
    var el = document.createElement("style"); el.id = "_cbcss10";
    el.textContent = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');"
    + "#cb10btn{position:fixed;bottom:24px;right:24px;z-index:2147483647;width:58px;height:58px;border-radius:50%;border:none;cursor:pointer;background:"+c+";color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 20px rgba(0,0,0,.25);transition:transform .2s;animation:cb10pop .5s cubic-bezier(.34,1.56,.64,1)}"
    + "@keyframes cb10pop{from{transform:scale(0)}to{transform:scale(1)}}"
    + "#cb10btn:hover{transform:scale(1.1)}"
    + "#cb10win{position:fixed;bottom:94px;right:24px;z-index:2147483646;width:370px;max-width:calc(100vw - 32px);height:600px;max-height:calc(100vh - 110px);background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 12px 50px rgba(0,0,0,.18);display:flex;flex-direction:column;transform:translateY(12px) scale(.95);opacity:0;pointer-events:none;transition:all .3s cubic-bezier(.34,1.56,.64,1);font-family:'Inter',sans-serif}"
    + "#cb10win.open{transform:none;opacity:1;pointer-events:all}"
    + "#cb10hdr{background:"+c+";padding:14px 16px;display:flex;align-items:center;gap:12px;flex-shrink:0}"
    + "#cb10av{width:42px;height:42px;border-radius:50%;background:rgba(255,255,255,.2);border:2px solid rgba(255,255,255,.4);display:flex;align-items:center;justify-content:center;flex-shrink:0}"
    + "#cb10av svg{width:22px;height:22px}"
    + "#cb10info{flex:1;min-width:0}"
    + "#cb10name{font-size:15px;font-weight:700;color:#fff}"
    + "#cb10status{font-size:12px;color:rgba(255,255,255,.85);display:flex;align-items:center;gap:5px;margin-top:2px}"
    + ".cb10dot{width:7px;height:7px;border-radius:50%;background:#4ade80;animation:cb10pulse 2s infinite}"
    + "@keyframes cb10pulse{0%,100%{opacity:1}50%{opacity:.4}}"
    + "#cb10cls{width:32px;height:32px;border-radius:50%;background:rgba(255,255,255,.2);border:none;color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:background .2s}"
    + "#cb10cls:hover{background:rgba(255,255,255,.35)}"
    + "#cb10msgs{flex:1;overflow-y:auto;overflow-x:hidden;padding:16px 14px;display:flex;flex-direction:column;gap:14px;background:#f8f9fa;width:100%;box-sizing:border-box}"
    + "#cb10msgs::-webkit-scrollbar{width:3px}"
    + "#cb10msgs::-webkit-scrollbar-thumb{background:#ddd;border-radius:2px}"
    + ".cb10row{display:flex;gap:10px;align-items:flex-start;width:100%;box-sizing:border-box}"
    + ".cb10row.user{flex-direction:row-reverse}"
    + ".cb10av{width:30px;height:30px;border-radius:50%;background:"+c+";display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:2px}"
    + ".cb10av svg{width:16px;height:16px}"
    + ".cb10bbl{max-width:calc(100% - 46px);min-width:0}"
    + ".cb10txt{padding:11px 14px;border-radius:4px 16px 16px 16px;font-size:13.5px;line-height:1.65;color:#1a1a1a;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.08);word-break:break-word;overflow-wrap:break-word;display:block}"
    + ".cb10row.user .cb10txt{background:"+c+";color:#fff;border-radius:16px 4px 16px 16px}"
    + ".cb10txt b{font-weight:600;color:"+c+"}"
    + ".cb10row.user .cb10txt b{color:#fff}"
    + ".cb10txt table{width:100%;border-collapse:collapse;margin:8px 0;font-size:12.5px}"
    + ".cb10txt table th{background:#f8f9fa;color:"+c+";font-weight:600;padding:6px 8px;border:1px solid #e0e0e0;text-align:left}"
    + ".cb10txt table td{padding:5px 8px;border:1px solid #f0f0f0}"
    + ".cb10txt table tr:nth-child(even) td{background:#fafafa}"
    + ".cb10txt ul{padding-left:16px;margin:5px 0}"
    + ".cb10txt li{margin:2px 0;line-height:1.5}"
    + ".cb10agent{display:inline-block;font-size:10px;font-weight:600;color:#fff;padding:2px 8px;border-radius:10px;margin-bottom:6px;letter-spacing:.3px}"
    + ".cb10ts{font-size:11px;color:#bbb;margin-top:4px;padding:0 2px}"
    + ".cb10row.user .cb10ts{text-align:right}"
    + ".cb10cards{display:flex;gap:10px;overflow-x:auto;overflow-y:hidden;padding:8px 0 10px;margin-top:10px;scrollbar-width:thin;scrollbar-color:"+c+" #f0f0f0;-webkit-overflow-scrolling:touch;width:100%}"
    + ".cb10cards::-webkit-scrollbar{height:4px}"
    + ".cb10cards::-webkit-scrollbar-track{background:#f0f0f0;border-radius:2px}"
    + ".cb10cards::-webkit-scrollbar-thumb{background:"+c+";border-radius:2px}"
    + ".cb10cardswrap{margin-top:10px}.cb10cardslbl{font-size:10px;font-weight:700;color:#aaa;letter-spacing:1px;text-transform:uppercase;margin-bottom:6px;padding:0 2px}"
    + ".cb10cardimg{width:100%;height:95px;overflow:hidden;background:#f5f5f5;flex-shrink:0}"
    + ".cb10cardimg img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .3s}"
    + ".cb10card:hover .cb10cardimg img{transform:scale(1.05)}"
    + ".cb10card{min-width:158px;width:158px;flex-shrink:0;background:#fff;border-radius:12px;overflow:hidden;border:1.5px solid #f0f0f0;text-decoration:none;color:#1a1a1a;box-shadow:0 2px 8px rgba(0,0,0,.07);transition:transform .2s,box-shadow .2s;display:block}"
    + ".cb10card:hover{transform:translateY(-3px);box-shadow:0 6px 18px rgba(0,0,0,.15);border-color:"+c+"}"
    + ".cb10cardbody{padding:9px 10px 11px}"
    + ".cb10cardname{font-size:12.5px;font-weight:600;color:#1a1a1a;white-space:normal;line-height:1.3;margin-bottom:3px}"
    + ".cb10cardprice{font-size:13px;font-weight:700;color:"+c+";margin-bottom:2px}"
    + ".cb10cardsize{font-size:11px;color:#888;margin-bottom:6px}"
    + ".cb10cardlink{display:flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;color:#fff;background:"+c+";border-radius:6px;padding:5px 8px;text-decoration:none}"
    + ".cb10chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}"
    + ".cb10chip{padding:7px 13px;background:#fff;border:1.5px solid #e8e8e8;border-radius:20px;font-size:12px;color:#555;cursor:pointer;white-space:nowrap;font-family:'Inter',sans-serif;transition:all .15s}"
    + ".cb10chip:hover{border-color:"+c+";color:"+c+";background:#f8f9fa}"
    + ".cb10typing{background:#fff;padding:12px 16px;border-radius:4px 16px 16px 16px;box-shadow:0 1px 4px rgba(0,0,0,.08);display:inline-flex;gap:5px;align-items:center}"
    + ".cb10typing span{width:7px;height:7px;border-radius:50%;background:"+c+";animation:cb10bounce 1.2s infinite}"
    + ".cb10typing span:nth-child(2){animation-delay:.2s}.cb10typing span:nth-child(3){animation-delay:.4s}"
    + "@keyframes cb10bounce{0%,60%,100%{transform:translateY(0)}30%{transform:translateY(-6px)}}"
    + "#cb10foot{padding:10px 12px;background:#fff;border-top:1px solid #eee;display:flex;gap:8px;align-items:center;flex-shrink:0}"
    + "#cb10inp{flex:1;border:1.5px solid #e0e0e0;border-radius:22px;padding:10px 16px;font-size:13.5px;font-family:'Inter',sans-serif;outline:none;resize:none;max-height:80px;line-height:1.5;color:#1a1a1a;background:#f8f9fa;transition:border-color .2s}"
    + "#cb10inp:focus{border-color:"+c+";background:#fff}"
    + "#cb10inp::placeholder{color:#aaa}"
    + "#cb10send{width:40px;height:40px;border-radius:50%;background:"+c+";color:#fff;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;box-shadow:0 3px 10px rgba(0,0,0,.2);transition:transform .2s}"
    + "#cb10send:hover{transform:scale(1.1)}"
    + "#cb10send:disabled{opacity:.4;cursor:not-allowed;transform:none}"
    + "#cb10pwr{text-align:center;font-size:11px;color:#ccc;padding:5px 0 8px;background:#fff;font-family:'Inter',sans-serif;flex-shrink:0}";
    document.head.appendChild(el);
  }

  function getBotSVG() {
    var c = botColor || "#ff3f6c";
    return '<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="8" width="18" height="13" rx="3" fill="white" fill-opacity="0.9"/><circle cx="8.5" cy="14" r="1.5" fill="'+c+'"/><circle cx="15.5" cy="14" r="1.5" fill="'+c+'"/><path d="M9 17.5C9 17.5 10 18.5 12 18.5C14 18.5 15 17.5 15 17.5" stroke="'+c+'" stroke-width="1.2" stroke-linecap="round"/><path d="M12 8V5" stroke="white" stroke-width="1.5" stroke-linecap="round"/><circle cx="12" cy="4" r="1.5" fill="white"/></svg>';
  }
  var CHAT_SVG = '<svg viewBox="0 0 24 24" fill="white"><path d="M20 2H4C2.9 2 2 2.9 2 4V22L6 18H20C21.1 18 22 17.1 22 16V4C22 2.9 21.1 2 20 2ZM9 11H7V9H9V11ZM13 11H11V9H13V11ZM17 11H15V9H17V11Z"/></svg>';
  var SEND_SVG = '<svg width="16" height="16" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
  var X_SVG    = '<svg width="14" height="14" viewBox="0 0 24 24" fill="white"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>';

  function buildDOM() {
    if (document.getElementById("cb10win")) return;
    var wrap = document.createElement("div");
    wrap.innerHTML =
      '<div id="cb10win">'
      + '<div id="cb10hdr">'
        + '<div id="cb10av">' + getBotSVG() + '</div>'
        + '<div id="cb10info">'
          + '<div id="cb10name">' + botName + ' <small style="font-size:10px;opacity:.75;font-weight:400">Multi-Agent AI</small></div>'
          + '<div id="cb10status"><span class="cb10dot"></span>4 specialist agents online</div>'
        + '</div>'
        + '<button id="cb10cls">' + X_SVG + '</button>'
      + '</div>'
      + '<div id="cb10msgs"></div>'
      + '<div id="cb10foot">'
        + '<textarea id="cb10inp" placeholder="Ask me anything about our products..." rows="1"></textarea>'
        + '<button id="cb10send">' + SEND_SVG + '</button>'
      + '</div>'
      + '<div id="cb10pwr">Powered by CrewAI &bull; 4 specialist agents</div>'
      + '</div>'
      + '<button id="cb10btn" title="Chat with ' + botName + '">' + CHAT_SVG + '</button>';
    document.body.appendChild(wrap);
  }

  function bindEvents() {
    g("cb10btn").onclick  = toggle;
    g("cb10cls").onclick  = toggle;
    g("cb10send").onclick = sendMsg;
    var inp = g("cb10inp");
    inp.onkeydown = function(e) { if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMsg();} };
    inp.oninput   = function() { this.style.height="auto"; this.style.height=Math.min(this.scrollHeight,80)+"px"; };
    // Event delegation for chip clicks — works for both fresh and restored chips
    // Uses data-ask attribute so no inline onclick needed in saved HTML
    g("cb10msgs").addEventListener("click", function(e) {
      // Force product card links to open in new tab — prevents host page JS from
      // intercepting and navigating same-tab, which would destroy chat history
      var card = e.target.closest(".cb10card");
      if (card) {
        e.preventDefault();
        e.stopPropagation();
        var href = card.getAttribute("href");
        if (href && href !== "#") window.open(href, "_blank", "noopener,noreferrer");
        return;
      }
      // Chip click handler
      var btn = e.target.closest(".cb10chip");
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        var q = btn.getAttribute("data-ask");
        if (q) window._cb10ask(q);
      }
    });
  }

  function openChat(silent) {
    isOpen=true; try{sessionStorage.setItem("_cb_open","1");}catch(e){}
    g("cb10win").classList.add("open"); g("cb10btn").innerHTML=X_SVG;
    if(!silent) setTimeout(function(){try{g("cb10inp").focus();}catch(e){}},300);
  }
  function closeChat() {
    isOpen=false; try{sessionStorage.setItem("_cb_open","0");}catch(e){}
    g("cb10win").classList.remove("open"); g("cb10btn").innerHTML=CHAT_SVG;
  }
  function toggle() { isOpen?closeChat():openChat(); }

  function restoreOrGreet() {
    var m=g("cb10msgs"); if(!m) return;
    // Load from sessionStorage — clears when tab is closed, persists across same-tab navigation
    try{
      var _stored=sessionStorage.getItem("_cb_h10");
      if(_stored){
        var _parsed=JSON.parse(_stored);
        if(Array.isArray(_parsed) && _parsed.length > 0) chatHistory=_parsed;
      }
    }catch(e){ chatHistory = chatHistory.length ? chatHistory : []; }
    // Only clear DOM AFTER we know the state — prevents flash of empty chat
    m.innerHTML = "";
    if(chatHistory.length>0){
      chatHistory.forEach(function(html){
        var d=document.createElement("div");
        d.innerHTML=html;
        d.querySelectorAll(".cb10chips").forEach(function(el){el.remove();});
        m.appendChild(d);
      });
      var freshChips=getNextChips();
      var chipWrap=document.createElement("div");
      chipWrap.className="cb10chips";
      chipWrap.style.cssText="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px;";
      freshChips.forEach(function(c){
        var btn=document.createElement("button");
        btn.type="button";
        btn.className="cb10chip";
        btn.textContent=c.i+" "+c.t;
        btn.setAttribute("data-ask", c.t);  // caught by event delegation in bindEvents
        chipWrap.appendChild(btn);
      });
      var allBbls=m.querySelectorAll(".cb10bbl .cb10txt");
      if(allBbls.length){allBbls[allBbls.length-1].appendChild(chipWrap);}
      scrollDown();
    } else {
      setTimeout(function(){
        addBot(
          "Hi! I'm <b>"+botName+"</b> for <b>"+bizName+"</b> 👋<br><br>"
          +"I use <b>4 specialist AI agents</b> to help you:<br>"
          +"<span style='color:#6366f1'>&#9679;</span> <b>Search</b> &bull; "
          +"<span style='color:"+botColor+"'>&#9679;</span> <b>Sales</b> &bull; "
          +"<span style='color:#0ea5e9'>&#9679;</span> <b>Compare</b> &bull; "
          +"<span style='color:#22c55e'>&#9679;</span> <b>Support</b><br><br>"
          +"I also <b>remember your preferences</b> across sessions. What are you looking for?",
          getNextChips(), [], null
        );
      }, 600);
    }
  }

  function sendMsg() {
    var inp=g("cb10inp"), txt=inp.value.trim();
    if(!txt||isTyping) return;
    inp.value=""; inp.style.height="auto";
    addUser(txt); setTyping(true); callAPI(txt);
  }

  async function callAPI(txt) {
    var ctrl = new AbortController();
    var timer = setTimeout(function(){ctrl.abort();}, 45000);
    try {
      var r = await fetch(API_URL+"/api/chat/"+CLIENT_ID+"/stream", {
        method: "POST",
        headers: {"Content-Type":"application/json","X-API-Key":API_KEY},
        body: JSON.stringify({message:txt, session_id:sessionId, user_id:userId}),
        signal: ctrl.signal
      });
      clearTimeout(timer);
      if (!r.ok) {
        setTyping(false);
        addBot("Something went wrong. Please try again!", getNextChips(), [], null);
        return;
      }

      // SSE streaming — build response word by word
      var reader  = r.body.getReader();
      var decoder = new TextDecoder();
      var buffer  = "";
      var meta    = null;
      var streamEl = null;  // the span we type into
      var gotFirstToken = false;
      var finalized = false;
      // typing indicator stays ON until first real token arrives

      function processSSELine(line) {
        line = line.trim();
        if (!line.startsWith("data:")) return;
        var raw = line.slice(5).trim();
        if (!raw) return;
        try {
          var evt = JSON.parse(raw);
          if (evt.type === "meta") {
            meta = evt;
            sessionId = evt.session_id || sessionId;
            try{sessionStorage.setItem("_cb_sid",sessionId);}catch(e2){}
          } else if (evt.type === "token" && meta) {
            if (!gotFirstToken) {
              gotFirstToken = true;
              setTyping(false);
              streamEl = _createStreamBubble(meta.agent_used);
            }
            if (streamEl) { streamEl.textContent += evt.text; scrollDown(); }
          } else if (evt.type === "replace" && meta && streamEl) {
            // Mojibake was detected — replace entire bubble text with cleaned version
            streamEl.textContent = evt.text; scrollDown();
          } else if (evt.type === "done") {
            if (!finalized) {
              finalized = true;
              if (meta && streamEl) {
                _finalizeStreamBubble(streamEl, meta);
              } else if (!gotFirstToken) {
                setTyping(false);
              }
            }
          }
        } catch(parseErr) {}
      }

      function processBuffer(buf) {
        var lines = buf.split("\n");
        var remainder = lines.pop(); // last line may be incomplete
        lines.forEach(function(l){ processSSELine(l); });
        return remainder;
      }

      while (true) {
        var chunk = await reader.read();
        // Always decode and process any data in this chunk BEFORE checking done
        if (chunk.value && chunk.value.length) {
          buffer += decoder.decode(chunk.value, {stream: !chunk.done});
          buffer = processBuffer(buffer);
        }
        if (chunk.done) break;
      }

      // Process any remaining data left in buffer after stream ends
      if (buffer.trim()) {
        buffer.split("\n").forEach(function(l){ processSSELine(l); });
      }

      // Safety net: if done event was never received (server crash, network cut)
      // still finalize so the response is saved to history
      if (!finalized && meta && streamEl) {
        finalized = true;
        _finalizeStreamBubble(streamEl, meta);
      }
      if (!gotFirstToken) { setTyping(false); }
      clearTimeout(timer);
    } catch(e) {
      clearTimeout(timer);
      setTyping(false);
      if (e.name === "AbortError") {
        addBot("Taking too long. Please try again!", getNextChips(), [], null);
      } else if (e.message && e.message.indexOf("stream") !== -1) {
        // Stream not supported — fall back to normal endpoint
        _callAPIFallback(txt);
      } else {
        addBot("Connection error. Is the server running?", getNextChips(), [], null);
      }
    }
  }

  function _createStreamBubble(agentName) {
    // Create a bot message bubble with a live-updating text span
    var badge = "";
    if (agentName) {
      var col = AGENT_COLORS[agentName] || "#ff3f6c";
      badge = '<span class="cb10agent" style="background:'+col+'">'+esc(agentName)+'</span><br>';
    }
    var m = g("cb10msgs");
    var outer = document.createElement("div");
    outer.className = "cb10row bot";
    outer.innerHTML = '<div class="cb10av">'+getBotSVG()+'</div><div class="cb10bbl"><div class="cb10txt" id="_cb10live">'+badge+'<span id="_cb10stream"></span></div></div>';
    m.appendChild(outer);
    scrollDown();
    return document.getElementById("_cb10stream");
  }

  function _finalizeStreamBubble(streamEl, meta) {
    // Convert raw text to formatted HTML, add cards + chips
    // Use streamEl.parentElement directly — avoids fragile ID lookup
    var liveDiv = streamEl ? streamEl.parentElement : document.getElementById("_cb10live");
    if (!liveDiv) return;

    var rawText = streamEl ? streamEl.textContent : "";
    var badge = "";
    if (meta.agent_used) {
      var col = AGENT_COLORS[meta.agent_used] || "#ff3f6c";
      badge = '<span class="cb10agent" style="background:'+col+'">'+esc(meta.agent_used)+'</span><br>';
    }

    var prods = getProducts(meta.suggested_products);
    var cards = "";
    if (prods.length) {
      cards = '<div class="cb10cardswrap"><div class="cb10cardslbl">&#128204; Related</div><div class="cb10cards">';
      prods.forEach(function(p){
        cards += '<a class="cb10card" href="'+(p.url||'#')+'" target="_blank" rel="noopener">'
          +'<div class="cb10cardimg"><img src="'+(p.image||'')+'" alt="'+esc(p.title||'')+'" loading="lazy" onerror="this.parentNode.style.background=\'#f5f5f5\'"></div>'
          +'<div class="cb10cardbody">'
          +'<div class="cb10cardname">'+esc(p.title||'')+'</div>'
          +(p.price?'<div class="cb10cardprice">'+esc(p.price)+'</div>':'')
          +(p.size?'<div class="cb10cardsize">&#128207; '+esc(p.size)+'</div>':'')
          +'<span class="cb10cardlink">View Details &#8594;</span>'
          +'</div></a>';
      });
      cards += '</div></div>';
    }
    var chips = getNextChips();
    var chipHtml = '<div class="cb10chips">';
    chips.forEach(function(c){ chipHtml += '<button type="button" class="cb10chip" data-ask="'+esc(c.t)+'">'+c.i+' '+esc(c.t)+'</button>'; });
    chipHtml += '</div>';

    var ts = '<div class="cb10ts">'+now()+'</div>';
    var finalHtml = badge + toHTML(rawText) + cards + chipHtml;
    liveDiv.id = "";  // remove temp id
    liveDiv.innerHTML = finalHtml;
    // append timestamp outside cb10txt
    liveDiv.parentElement.insertAdjacentHTML("beforeend", ts);

    // Save to history — sanitize outerHTML before storing to avoid parse issues
    var fullRow = liveDiv.closest(".cb10row");
    if (fullRow) {
      var rowHtml = fullRow.outerHTML;
      // Strip inline event handlers that aren't needed in restored HTML
      rowHtml = rowHtml.replace(/ onerror="[^"]*"/g, '');
      rowHtml = rowHtml.replace(/ onload="[^"]*"/g, '');
      chatHistory.push(rowHtml);
      if (chatHistory.length > 60) chatHistory = chatHistory.slice(-60);
      _saveHistory();
    }
    scrollDown();
  }

  async function _callAPIFallback(txt) {
    // Non-streaming fallback if SSE is not supported
    try {
      var ctrl = new AbortController();
      setTimeout(function(){ctrl.abort();}, 20000);
      var r = await fetch(API_URL+"/api/chat/"+CLIENT_ID, {
        method:"POST",
        headers:{"Content-Type":"application/json","X-API-Key":API_KEY},
        body:JSON.stringify({message:txt, session_id:sessionId, user_id:userId}),
        signal:ctrl.signal
      });
      if (!r.ok) { addBot("Something went wrong. Please try again!", getNextChips(), [], null); return; }
      var d = await r.json();
      sessionId = d.session_id || sessionId;
      try{sessionStorage.setItem("_cb_sid",sessionId);}catch(e){}
      addBot(d.response, getNextChips(), getProducts(d.suggested_products), d.agent_used);
    } catch(e) {
      addBot(e.name==="AbortError"?"Taking too long. Please try again!":"Connection error.", getNextChips(), [], null);
    }
  }

  function addUser(text) {
    var html='<div class="cb10row user"><div class="cb10bbl"><div class="cb10txt">'+esc(text)+'</div><div class="cb10ts">'+now()+'</div></div></div>';
    save(html);
  }

  function addBot(raw,chips,prods,agentName) {
    var badge="";
    if(agentName){
      var col=AGENT_COLORS[agentName]||"#ff3f6c";
      badge='<span class="cb10agent" style="background:'+col+'">'+esc(agentName)+'</span><br>';
    }
    var body=toHTML(raw), cards="", chipHtml="";
    if(prods&&prods.length){
      cards='<div class="cb10cardswrap"><div class="cb10cardslbl">&#128204; Related</div><div class="cb10cards">';
      prods.forEach(function(p){
        cards+='<a class="cb10card" href="'+(p.url||"#")+'" target="_blank" rel="noopener">'
          +'<div class="cb10cardimg"><img src="'+(p.image||"")+'" alt="'+esc(p.title||"")+'" loading="lazy" onerror="this.parentNode.style.background='+"'#f5f5f5'"+'"></div>'
          +'<div class="cb10cardbody">'
            +'<div class="cb10cardname">'+esc(p.title||"")+'</div>'
            +(p.price?'<div class="cb10cardprice">'+esc(p.price)+'</div>':"")
            +(p.size?'<div class="cb10cardsize">&#128207; '+esc(p.size)+'</div>':"")
            +'<span class="cb10cardlink">View Details &#8594;</span>'
          +'</div></a>';
      });
      cards+='</div></div>';
    }
    if(chips&&chips.length){
      chipHtml='<div class="cb10chips">';
      chips.forEach(function(c){chipHtml+='<button type="button" class="cb10chip" data-ask="'+esc(c.t)+'">'+c.i+' '+esc(c.t)+'</button>';});
      chipHtml+='</div>';
    }
    var html='<div class="cb10row bot"><div class="cb10av">'+getBotSVG()+'</div><div class="cb10bbl"><div class="cb10txt">'+badge+body+cards+chipHtml+'</div><div class="cb10ts">'+now()+'</div></div></div>';
    save(html);
  }

  function _saveHistory() {
    // Central save point — always called after any chatHistory change
    try {
      var serialized = JSON.stringify(chatHistory);
      sessionStorage.setItem("_cb_h10", serialized);
    } catch(e) {
      // If storage fails (quota/security), try saving a trimmed version
      try {
        var trimmed = chatHistory.slice(-10);
        sessionStorage.setItem("_cb_h10", JSON.stringify(trimmed));
        chatHistory = trimmed;
      } catch(e2) { /* storage unavailable, in-memory only */ }
    }
  }

  function save(html) {
    var m=g("cb10msgs"); if(!m) return;
    var d=document.createElement("div"); d.innerHTML=html; m.appendChild(d);
    chatHistory.push(html);
    if(chatHistory.length>60) chatHistory=chatHistory.slice(-60);
    _saveHistory();
    scrollDown();
  }

  function toHTML(t) {
    if(!t) return "";
    if(/<(b|br|ul|li|table)[^>]*>/.test(t)) return t;
    t=t.replace(/\*\*(.+?)\*\*/g,"<b>$1</b>");
    if(t.indexOf("|")>-1&&t.split("|").length>3){
      var lines=t.split("\n"),result=[],inTable=false;
      lines.forEach(function(line){
        if(line.trim().startsWith("|")&&line.trim().endsWith("|")){
          if(!inTable){result.push("<table>");inTable=true;}
          if(line.indexOf("---")>-1) return;
          var cells=line.trim().slice(1,-1).split("|").map(function(c){return c.trim();});
          var isHdr=result.filter(function(r){return r.indexOf("<tr>")>-1;}).length===0;
          result.push("<tr>"+cells.map(function(c){return "<"+(isHdr?"th":"td")+">"+c+"</"+(isHdr?"th":"td")+">";}).join("")+"</tr>");
        } else {
          if(inTable){result.push("</table>");inTable=false;}
          result.push(line);
        }
      });
      if(inTable) result.push("</table>");
      t=result.join("\n");
    }
    t=t.replace(/^[-*] (.+)$/gm,"<li>$1</li>");
    t=t.replace(/(<li>[^<]+<\/li>)+/g,"<ul>$&</ul>");
    t=t.replace(/\n\n+/g,"<br><br>");
    t=t.replace(/\n/g,"<br>");
    return t;
  }

  function setTyping(on){
    isTyping=on; try{g("cb10send").disabled=on;}catch(e){}
    var ex=document.getElementById("_cb10typ"); if(ex) ex.remove();
    if(on){
      var m=g("cb10msgs"); if(!m) return;
      var d=document.createElement("div"); d.id="_cb10typ";
      d.innerHTML='<div class="cb10row bot"><div class="cb10av">'+getBotSVG()+'</div><div class="cb10typing"><span></span><span></span><span></span></div></div>';
      m.appendChild(d); scrollDown();
    }
  }

  function g(id){return document.getElementById(id);}
  function scrollDown(){try{var m=g("cb10msgs");if(m)setTimeout(function(){m.scrollTop=m.scrollHeight;},60);}catch(e){}}
  function now(){try{return new Date().toLocaleTimeString([],{hour:"2-digit",minute:"2-digit"});}catch(e){return "";}}
  function esc(t){var d=document.createElement("div");d.textContent=t||"";return d.innerHTML;}

  window._cb10ask=function(t){try{if(!isOpen)openChat();var i=g("cb10inp");if(i){i.value=t;sendMsg();}}catch(e){}};

  // Save session state before page navigation
  // NOTE: Do NOT save chatHistory here — it is saved after every message already.
  // Writing it here risks overwriting good stored history with an empty array
  // if the script is still initializing (loadConfig hasn't finished yet).
  window.addEventListener("beforeunload", function() {
    if (sessionId) { try { sessionStorage.setItem("_cb_sid", sessionId); } catch(e) {} }
    try { sessionStorage.setItem("_cb_open", isOpen ? "1" : "0"); } catch(e) {}
    // Only persist chatHistory if we actually have messages (never overwrite with [])
    if (chatHistory.length > 0) {
      _saveHistory();
    }
  });

  // sessionStorage clears automatically when the tab is closed — no explicit handler needed.
  // DO NOT add pagehide/beforeunload clear — that would wipe chat on normal page navigation too.

  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",boot);
  else boot();
})();
