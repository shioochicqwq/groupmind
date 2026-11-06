/* LabelKit: reusable pieces for offline labeling pages (no network, no build step).
 *
 * LabelKit.store(key, defaults)        progress kept in localStorage
 * LabelKit.queue(root, opts)           one card at a time, required questions, auto-advance
 * LabelKit.recall(root, opts)          free-recall list ("write what you remember before looking")
 * LabelKit.people(root, opts)          accounts -> people: same person / maybe / not, aliases, graph
 * LabelKit.download(obj, filename)     save the results as a JSON file
 *
 * Question schema for queue:
 *   {key, title, options: [[value, label], ...], required: true}
 *   {key, title, type: 'text', placeholder, showWhen(answers), requiredWhen(answers)}
 *   {key, title, options, multi: true, required: false}   several choices; never auto-advances
 * A card is complete when every required question is answered and every required text is filled.
 * Clicking the last missing option moves on by itself; when a text box is showing, the page waits
 * for "下一题" (or Enter) so the text can be written.
 */
(function () {
  'use strict';
  var LK = {};

  LK.el = function (tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  var el = LK.el;

  LK.store = function (key, defaults) {
    var state = JSON.parse(JSON.stringify(defaults || {}));
    try { var saved = JSON.parse(localStorage.getItem(key) || 'null'); if (saved) Object.assign(state, saved); } catch (e) { /* private mode */ }
    var listeners = [];
    return {
      state: state,
      save: function () { try { localStorage.setItem(key, JSON.stringify(state)); } catch (e) { /* ignore */ } listeners.forEach(function (f) { f(); }); },
      onSave: function (f) { listeners.push(f); },
      clear: function () { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } }
    };
  };

  LK.download = function (obj, filename) {
    var a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' }));
    a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
  };

  LK.examples = function (box, exs, caption) {
    if (caption) box.appendChild(el('p', 'lk-meta', caption));
    (exs || []).forEach(function (x) {
      var d = el('div', 'lk-ex');
      (x.ctx || []).forEach(function (c) { d.appendChild(el('div', 'c', c)); });
      d.appendChild(el('div', '', x.line));
      box.appendChild(d);
    });
  };

  function visible(q, a) { return !q.showWhen || q.showWhen(a); }
  function needed(q, a) { return visible(q, a) && (q.type === 'text' ? !!(q.requiredWhen && q.requiredWhen(a)) : q.required !== false); }
  function answered(q, a) {
    var v = a[q.key];
    if (q.type === 'text') return !!(v && String(v).trim());
    if (q.multi) return Array.isArray(v) && v.length > 0;
    return v != null && v !== '';
  }
  LK.complete = function (questions, a) { return questions.every(function (q) { return !needed(q, a) || answered(q, a); }); };

  LK.queue = function (root, opts) {
    var items = opts.items, qs = opts.questions, answers = opts.answers, save = opts.save || function () {};
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var idx = Math.max(0, items.findIndex(function (it) { return !LK.complete(qs, answers[it.id] || {}); }));
    if (idx < 0) idx = 0;
    root.innerHTML = '';
    var head = el('div', 'lk-qhead'), count = el('span'), prog = el('div', 'lk-progress'), bar = el('i');
    prog.appendChild(bar); head.appendChild(count); head.appendChild(prog);
    var dots = el('div', 'lk-dots'), stage = el('div', 'lk-stage'), nav = el('div', 'lk-nav');
    var prev = el('button', 'lk-btn ghost', '← 上一题'), next = el('button', 'lk-btn', '下一题 →');
    nav.appendChild(prev); nav.appendChild(next);
    root.appendChild(head); root.appendChild(dots); root.appendChild(stage); root.appendChild(nav);

    function doneCount() { return items.filter(function (it) { return LK.complete(qs, answers[it.id] || {}); }).length; }
    function refreshHead() {
      var d = doneCount();
      count.textContent = (idx < items.length ? '第 ' + (idx + 1) + ' / ' + items.length + ' 题' : '已到末尾') + '　完成 ' + d;
      bar.style.width = (100 * d / Math.max(items.length, 1)) + '%';
      dots.innerHTML = '';
      items.forEach(function (it, i) {
        var b = el('button', 'lk-dot' + (LK.complete(qs, answers[it.id] || {}) ? ' ok' : '') + (i === idx ? ' cur' : ''));
        b.title = '第 ' + (i + 1) + ' 题'; b.onclick = function () { go(i); }; dots.appendChild(b);
      });
      prev.disabled = idx === 0;
      var a = idx < items.length ? (answers[items[idx].id] || {}) : {};
      next.disabled = idx >= items.length || !LK.complete(qs, a);
      next.textContent = idx === items.length - 1 ? '完成 ✓' : '下一题 →';
    }

    function card(i) {
      var box = el('div', 'lk-card lk-slide');
      if (i >= items.length) {
        var left = items.length - doneCount();
        var d = el('div', 'lk-done');
        d.appendChild(el('p', 'lk-big', left ? '还有 ' + left + ' 题没做完' : '这一部分完成了'));
        d.appendChild(el('p', 'lk-meta', left ? '点上面的灰色小方块可以跳回去。' : '可以继续下一部分，或者下载结果。'));
        box.appendChild(d); return box;
      }
      var it = items[i], a = answers[it.id] = answers[it.id] || {};
      opts.render(it, box);
      var texts = [];
      qs.forEach(function (q) {
        var wrap = el('div', 'lk-q');
        var t = el('div', 'lk-q-title', q.title);
        wrap.appendChild(t);
        if (q.type === 'text') {
          var inp = el(q.multiline === false ? 'input' : 'textarea'); if (inp.tagName === 'INPUT') inp.type = 'text';
          inp.placeholder = q.placeholder || ''; inp.value = a[q.key] || '';
          inp.oninput = function () { a[q.key] = inp.value; save(); sync(); };
          inp.onkeydown = function (e) { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (LK.complete(qs, a)) go(i + 1); } };
          wrap.appendChild(inp);
          texts.push({ q: q, wrap: wrap, inp: inp, t: t });
        } else {
          var row = el('div', 'lk-opts');
          q.options.forEach(function (o) {
            var b = el('button', 'lk-opt', o[1]); b.type = 'button';
            var on = function () { return q.multi ? (a[q.key] || []).indexOf(o[0]) >= 0 : a[q.key] === o[0]; };
            b.setAttribute('aria-pressed', on() ? 'true' : 'false');
            if (q.multi) {
              b.onclick = function () {
                var v = (a[q.key] || []).slice(), k = v.indexOf(o[0]);
                if (k >= 0) v.splice(k, 1); else v.push(o[0]);
                a[q.key] = v; save(); b.setAttribute('aria-pressed', on() ? 'true' : 'false'); sync();
              };
              row.appendChild(b);
              return;
            }
            b.onclick = function () {
              a[q.key] = o[0]; save();
              row.querySelectorAll('.lk-opt').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); });
              b.setAttribute('aria-pressed', 'true');
              sync();
              // A visible text box or multi-choice question means the card waits for "下一题".
              var textShowing = texts.some(function (x) { return visible(x.q, a); }) ||
                qs.some(function (x) { return x.multi && visible(x, a); });
              if (LK.complete(qs, a) && !textShowing) setTimeout(function () { if (idx === i) go(i + 1); }, 260);
              else { var need = texts.find(function (x) { return needed(x.q, a) && !answered(x.q, a); }); if (need) need.inp.focus(); }
            };
            row.appendChild(b);
          });
          if (q.required !== false) t.appendChild(el('span', 'req', q.multi ? '必选，可多选' : '必选'));
          else if (q.multi) t.appendChild(el('span', 'req', '可多选，可不选'));
          wrap.appendChild(row);
        }
        box.appendChild(wrap);
      });
      function sync() {
        texts.forEach(function (x) {
          x.wrap.style.display = visible(x.q, a) ? '' : 'none';
          var must = needed(x.q, a);
          x.t.textContent = x.q.title + (must ? '' : '（可不填）');
          if (must) x.t.appendChild(el('span', 'req', '必填'));
          x.inp.classList.toggle('lk-need', must && !answered(x.q, a));
        });
        refreshHead();
      }
      setTimeout(sync, 0);
      return box;
    }

    var current = null;
    function go(i, instant) {
      if (i < 0 || i > items.length) return;
      var forward = i >= idx;
      idx = i;
      var fresh = card(i);
      if (!current || reduce || instant) {
        stage.innerHTML = ''; stage.appendChild(fresh); current = fresh; refreshHead(); return;
      }
      var old = current;
      old.classList.add(forward ? 'out-left' : 'out-right');
      fresh.classList.add(forward ? 'in-right' : 'in-left');
      setTimeout(function () {
        stage.innerHTML = ''; stage.appendChild(fresh); current = fresh;
        void fresh.offsetWidth;
        fresh.classList.remove('in-right', 'in-left');
        refreshHead();
        var top = root.getBoundingClientRect().top;
        if (top < 0) window.scrollBy({ top: top - 50, behavior: reduce ? 'auto' : 'smooth' });
      }, 200);
      refreshHead();
    }
    prev.onclick = function () { go(idx - 1); };
    next.onclick = function () { go(idx + 1); };
    root.addEventListener('keydown', function (e) {
      if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
      if (e.key === 'ArrowRight' && !next.disabled) go(idx + 1);
      if (e.key === 'ArrowLeft') go(idx - 1);
    });
    go(idx, true);
    return { done: doneCount, total: items.length, go: go };
  };

  LK.recall = function (root, opts) {
    var st = opts.state, save = opts.save, kinds = opts.kinds;
    function draw() {
      root.innerHTML = '';
      if (!st.recall.length) for (var i = 0; i < 5; i++) st.recall.push({});
      st.recall.forEach(function (r, i) {
        var c = el('div', 'lk-card'), row = el('div', 'lk-row');
        var w = el('input'); w.type = 'text'; w.placeholder = opts.wordHint || '词或外号'; w.value = r.word || '';
        var m = el('input'); m.type = 'text'; m.placeholder = opts.meaningHint || '含义；外号就写指谁'; m.value = r.meaning || '';
        w.oninput = function () { r.word = w.value; save(); }; m.oninput = function () { r.meaning = m.value; save(); };
        row.appendChild(w); row.appendChild(m); c.appendChild(row);
        var opt = el('div', 'lk-opts');
        kinds.forEach(function (k) {
          var b = el('button', 'lk-opt', k[1]); b.type = 'button'; b.setAttribute('aria-pressed', r.kind === k[0] ? 'true' : 'false');
          b.onclick = function () { r.kind = k[0]; save(); opt.querySelectorAll('.lk-opt').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); }); b.setAttribute('aria-pressed', 'true'); };
          opt.appendChild(b);
        });
        c.appendChild(opt);
        if (r.afterReveal) c.appendChild(el('p', 'lk-meta lk-warn', '这一条是在看过后面内容之后补的'));
        root.appendChild(c);
      });
      var add = el('button', 'lk-btn ghost', '＋ 再加一行');
      add.onclick = function () { st.recall.push(st.recallDone ? { afterReveal: true } : {}); save(); draw(); };
      root.appendChild(add);
    }
    draw();
    return { redraw: draw };
  };

  /* People builder.
   * accounts: [{id, label, names: [{name, first, last, n}], msgs, first, last, samples: [..]}]
   * state.people: {pid: {name, accounts: [id], aliases: [{text, note}]}}
   * state.pairs: [{a, b, rel: 'maybe' | 'not'}]   (a, b are account ids)
   */
  LK.people = function (root, opts) {
    var accounts = opts.accounts, st = opts.state, save = opts.save;
    st.people = st.people || {}; st.pairs = st.pairs || []; st.seq = st.seq || 0;
    var byId = {}; accounts.forEach(function (a) { byId[a.id] = a; });
    var sel = {}, filter = '', focus = null;
    root.innerHTML = '';
    var tools = el('div', 'lk-card');
    var search = el('input'); search.type = 'text'; search.placeholder = '搜索昵称';
    search.oninput = function () { filter = search.value.trim(); drawList(); };
    tools.appendChild(search);
    var acts = el('div', 'lk-opts'); acts.style.marginTop = '8px';
    var bSame = el('button', 'lk-btn', '选中的是同一个人'), bMaybe = el('button', 'lk-btn ghost', '可能是同一个人'),
      bNot = el('button', 'lk-btn ghost', '不是同一个人'), bClear = el('button', 'lk-btn ghost', '取消选择');
    [bSame, bMaybe, bNot, bClear].forEach(function (b) { b.type = 'button'; acts.appendChild(b); });
    tools.appendChild(acts);
    var hint = el('p', 'lk-meta', '点账号可多选。选一个账号再点「加外号」，或在右边的人物卡上加。');
    tools.appendChild(hint);
    var grid = el('div', 'lk-people'), list = el('div', 'lk-acclist'), side = el('div');
    grid.appendChild(list); grid.appendChild(side);
    var graphBox = el('div'); graphBox.style.marginTop = '12px';
    root.appendChild(tools); root.appendChild(grid); root.appendChild(graphBox);

    function ownerOf(aid) { for (var p in st.people) if (st.people[p].accounts.indexOf(aid) >= 0) return p; return null; }
    function selected() { return Object.keys(sel).filter(function (k) { return sel[k]; }); }
    function personFor(aid) {
      var p = ownerOf(aid); if (p) return p;
      var pid = 'p' + (++st.seq); st.people[pid] = { name: byId[aid].label, accounts: [aid], aliases: [] }; return pid;
    }
    function merge(ids) {
      var target = null;
      ids.forEach(function (aid) {
        var p = ownerOf(aid);
        if (!target) { target = personFor(aid); return; }
        if (p === target) return;
        if (p) { var src = st.people[p]; src.accounts.forEach(function (x) { if (st.people[target].accounts.indexOf(x) < 0) st.people[target].accounts.push(x); });
          st.people[target].aliases = st.people[target].aliases.concat(src.aliases); delete st.people[p]; }
        else st.people[target].accounts.push(aid);
      });
      st.pairs = st.pairs.filter(function (r) { return !(ownerOf(r.a) === target && ownerOf(r.b) === target); });
      return target;
    }
    function pairUp(ids, rel) {
      for (var i = 0; i < ids.length; i++) for (var j = i + 1; j < ids.length; j++) {
        var a = ids[i], b = ids[j];
        st.pairs = st.pairs.filter(function (r) { return !((r.a === a && r.b === b) || (r.a === b && r.b === a)); });
        st.pairs.push({ a: a, b: b, rel: rel });
      }
    }
    bSame.onclick = function () { var s = selected(); if (s.length < 2) { hint.textContent = '至少选两个账号。'; return; } focus = merge(s); sel = {}; save(); drawAll(); };
    bMaybe.onclick = function () { var s = selected(); if (s.length < 2) { hint.textContent = '至少选两个账号。'; return; } pairUp(s, 'maybe'); sel = {}; save(); drawAll(); };
    bNot.onclick = function () { var s = selected(); if (s.length < 2) { hint.textContent = '至少选两个账号。'; return; } pairUp(s, 'not'); sel = {}; save(); drawAll(); };
    bClear.onclick = function () { sel = {}; drawList(); };

    function drawList() {
      list.innerHTML = '';
      accounts.filter(function (a) { return !filter || a.names.some(function (n) { return n.name.indexOf(filter) >= 0; }) || a.label.indexOf(filter) >= 0; })
        .forEach(function (a) {
          var row = el('div', 'lk-acc' + (sel[a.id] ? ' sel' : ''));
          var cb = el('input'); cb.type = 'checkbox'; cb.checked = !!sel[a.id];
          var body = el('div');
          body.appendChild(el('div', 'nm', a.label));
          var names = el('div'); a.names.forEach(function (n) { names.appendChild(el('span', 'lk-chip', n.name + (a.names.length > 1 ? '（' + n.first + '–' + n.last + '）' : ''))); });
          body.appendChild(names);
          body.appendChild(el('div', 'lk-meta', a.msgs + ' 条消息　' + a.first + ' – ' + a.last + '　账号尾号 ' + a.tail));
          var p = ownerOf(a.id); if (p) body.appendChild(el('div', 'ow', '已归入：' + st.people[p].name));
          row.appendChild(cb); row.appendChild(body);
          row.onclick = function (e) { if (e.target !== cb) cb.checked = !cb.checked; sel[a.id] = cb.checked; row.classList.toggle('sel', cb.checked); };
          list.appendChild(row);
        });
    }

    function drawSide() {
      side.innerHTML = '';
      var s = selected();
      var add = el('div', 'lk-card');
      add.appendChild(el('div', 'lk-q-title', s.length === 1 ? '给「' + byId[s[0]].label + '」加外号' : '加外号（先在左边选一个账号）'));
      var t = el('input'); t.type = 'text'; t.placeholder = '外号或称呼';
      var n = el('input'); n.type = 'text'; n.placeholder = '备注（来历、谁这么叫，可不填）'; n.style.marginTop = '6px';
      var ok = el('button', 'lk-btn', '加上'); ok.type = 'button';
      ok.onclick = function () {
        var cur = selected(); if (cur.length !== 1 || !t.value.trim()) { hint.textContent = '先选一个账号，再写外号。'; return; }
        var pid = personFor(cur[0]); st.people[pid].aliases.push({ text: t.value.trim(), note: n.value.trim() }); focus = pid; save(); drawAll();
      };
      add.appendChild(t); add.appendChild(n); add.appendChild(ok);
      side.appendChild(add);
      var ids = Object.keys(st.people);
      side.appendChild(el('p', 'lk-meta', '人物 ' + ids.length + ' 个　「可能是」' + st.pairs.filter(function (r) { return r.rel === 'maybe'; }).length + ' 对　「不是」' + st.pairs.filter(function (r) { return r.rel === 'not'; }).length + ' 对'));
      ids.sort(function (x, y) { return (y === focus) - (x === focus); }).forEach(function (pid) {
        var p = st.people[pid], c = el('div', 'lk-card');
        var name = el('input'); name.type = 'text'; name.value = p.name; name.title = '人物的称呼，可以改';
        name.oninput = function () { p.name = name.value; save(); drawGraph(); };
        c.appendChild(name);
        var accs = el('div'); accs.style.marginTop = '6px';
        p.accounts.forEach(function (aid) {
          var ch = el('span', 'lk-chip', byId[aid].label), x = el('button', '', '×'); x.title = '移出这个人物';
          x.onclick = function () { p.accounts = p.accounts.filter(function (y) { return y !== aid; }); if (!p.accounts.length) delete st.people[pid]; save(); drawAll(); };
          ch.appendChild(x); accs.appendChild(ch);
        });
        c.appendChild(accs);
        var al = el('div');
        p.aliases.forEach(function (a, i) {
          var ch = el('span', 'lk-chip alias', a.text + (a.note ? '（' + a.note + '）' : '')), x = el('button', '', '×');
          x.onclick = function () { p.aliases.splice(i, 1); save(); drawAll(); };
          ch.appendChild(x); al.appendChild(ch);
        });
        var t2 = el('input'); t2.type = 'text'; t2.placeholder = '再加一个外号，回车确认'; t2.style.marginTop = '4px';
        t2.onkeydown = function (e) { if (e.key === 'Enter' && t2.value.trim()) { p.aliases.push({ text: t2.value.trim(), note: '' }); focus = pid; save(); drawAll(); } };
        c.appendChild(al); c.appendChild(t2);
        side.appendChild(c);
      });
    }

    function drawGraph() {
      graphBox.innerHTML = '';
      var ids = Object.keys(st.people);
      graphBox.appendChild(el('h3', '', '人物关系图'));
      graphBox.appendChild(el('p', 'lk-meta', '绿色圆是人物，白色圆是账号，绿色字是外号；黄色虚线是「可能是同一人」，红色点线是「不是同一人」。'));
      if (!ids.length) { graphBox.appendChild(el('p', 'lk-meta', '还没有人物。')); return; }
      var W = 260, H = 210, cols = Math.max(1, Math.min(3, Math.floor((graphBox.clientWidth || 800) / W))), rows = Math.ceil(ids.length / cols);
      var NS = 'http://www.w3.org/2000/svg';
      var svg = document.createElementNS(NS, 'svg'); svg.setAttribute('viewBox', '0 0 ' + (cols * W) + ' ' + (rows * H)); svg.setAttribute('class', 'lk-graph');
      function node(tag, attrs, text) { var n = document.createElementNS(NS, tag); for (var k in attrs) n.setAttribute(k, attrs[k]); if (text != null) n.textContent = text; return n; }
      var pos = {};
      var lines = node('g', {}), nodes = node('g', {});
      ids.forEach(function (pid, i) {
        var p = st.people[pid], cx = (i % cols) * W + W / 2, cy = Math.floor(i / cols) * H + 80;
        var g = node('g', { 'class': 'p' });
        var k = p.accounts.length;
        p.accounts.forEach(function (aid, j) {
          var ang = -Math.PI / 2 + (k === 1 ? Math.PI / 2 : (Math.PI * 2 * j) / k), ax = cx + 70 * Math.cos(ang), ay = cy + 48 * Math.sin(ang);
          pos[aid] = [ax, ay];
          lines.appendChild(node('line', { x1: cx, y1: cy, x2: ax, y2: ay }));
          var a = node('g', { 'class': 'a' });
          a.appendChild(node('circle', { cx: ax, cy: ay, r: 6 }));
          a.appendChild(node('text', { x: ax, y: ay + 18, 'text-anchor': 'middle' }, byId[aid].label.slice(0, 8)));
          nodes.appendChild(a);
        });
        g.appendChild(node('circle', { cx: cx, cy: cy, r: 22 }));
        g.appendChild(node('text', { x: cx, y: cy + 4, 'text-anchor': 'middle', 'class': 'n' }, (p.name || '?').slice(0, 4)));
        p.aliases.slice(0, 4).forEach(function (a, j) {
          g.appendChild(node('text', { x: cx, y: cy + 82 + j * 15, 'text-anchor': 'middle', 'class': 'al' }, '「' + a.text.slice(0, 12) + '」'));
        });
        nodes.appendChild(g);
      });
      st.pairs.forEach(function (r) {
        if (pos[r.a] && pos[r.b]) lines.appendChild(node('line', { x1: pos[r.a][0], y1: pos[r.a][1], x2: pos[r.b][0], y2: pos[r.b][1], 'class': r.rel === 'maybe' ? 'maybe' : 'no' }));
      });
      svg.appendChild(lines); svg.appendChild(nodes);
      graphBox.appendChild(svg);
      var loose = st.pairs.filter(function (r) { return !(pos[r.a] && pos[r.b]); });
      if (loose.length) {
        var ul = el('div', 'lk-meta');
        loose.forEach(function (r) { ul.appendChild(el('div', '', byId[r.a].label + (r.rel === 'maybe' ? ' ⇢ 可能是 ⇠ ' : ' ✕ 不是 ✕ ') + byId[r.b].label)); });
        graphBox.appendChild(el('p', 'lk-meta', '下面这些账号对还没有归入人物：')); graphBox.appendChild(ul);
      }
    }
    function drawAll() { drawList(); drawSide(); drawGraph(); }
    list.addEventListener('click', function () { setTimeout(drawSide, 0); });
    drawAll();
  };

  window.LabelKit = LK;
})();
