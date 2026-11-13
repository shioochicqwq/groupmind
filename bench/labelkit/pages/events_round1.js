/* 事件打标 · 第一轮：给一个群的晚上打分（rate evenings). Data: window.DATA from bench.events.label_pack.
 * Second version of the page (2026-11-11): choices only, notes optional. The first version opened with
 * a free-recall step (write the most memorable evenings before seeing anything) and ended with a pick
 * from a list of dates; both asked for recall from nothing and were dropped at the user's request.
 * The "most ..." picks are now a choice among the evenings the rater scored highest. */
(function () {
  var D = window.DATA, LK = window.LabelKit, el = LK.el;
  var S = LK.store('label:' + D.pack, { evenings: {}, picks: {}, who: '' });
  var st = S.state, save = S.save;
  var app = document.getElementById('app');

  app.appendChild(el('h1', '', '事件打标 · ' + D.group + ' · 第一轮'));
  var intro = el('div', 'lk-note');
  intro.innerHTML = '<p><b>这页含原名的群聊记录，仅限本人查看，请勿外传。</b>联系方式和长数字已遮盖。进度自动保存在本机浏览器里，做完点最下面的「下载结果」，把文件发回来。</p>' +
    '<p>这一轮看的是「晚上」：北京时间 18:00 到次日 6:00，消息不少于 ' + D.min_msgs + ' 条的晚上，共 ' + D.evenings.length + ' 个。' +
    '用来做「你还记得最乱的那个晚上吗」这类问题的标准答案。</p>' +
    '<p>全部是选择题，备注可不填，不需要凭空回想。共两步。第 1 步逐个晚上打分，不必每条消息都读，扫一眼话题摘要和时间线就行。第 2 步从你打分最高的几个晚上里挑出「最……」的那个。</p>';
  app.appendChild(intro);
  var bar = el('div', 'lk-bar'); app.appendChild(bar);

  app.appendChild(el('h2', '', '第 1 步：逐个晚上打分（' + D.evenings.length + ' 个）'));
  app.appendChild(el('div', 'lk-note', '每个晚上三道必选题，标签和备注可不填。「时间线」按发言顺序显示全部消息，左边的色条表示它属于哪一段话题，色条频繁变换说明几个话题交错进行。'));
  var queueBox = el('div'); app.appendChild(queueBox);
  app.appendChild(el('h2', '', '第 2 步：挑出「最……」的晚上'));
  app.appendChild(el('div', 'lk-note', '候选是按你在第 1 步的回答自动列出的，每个晚上下面附了当晚最长的一段话题。第 1 步做得越多，候选越全。觉得没有特别突出的，就选「没有明显的」。'));
  var picksBox = el('div'); app.appendChild(picksBox);

  app.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = st.who || '';
  who.oninput = function () { st.who = who.value; save(); }; app.appendChild(who);
  var dl = el('button', 'lk-btn', '下载结果'), reset = el('button', 'lk-btn ghost', '清空本机进度');
  app.appendChild(dl); app.appendChild(reset);

  var SCALE = function (lo, hi) { return [['1', '1 ' + lo], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5 ' + hi], ['na', '看不出']]; };
  var TAGS = [['conflict', '吵架或冲突'], ['flood', '刷屏或接龙'], ['meme', '集体玩梗'], ['awkward', '尴尬场面'], ['news', '重要消息或决定'],
    ['joinleave', '有人来或走'], ['help', '求助或情绪低落'], ['media', '大量图片或视频'], ['deep', '深夜长谈'], ['other', '其他（可写在备注里）']];

  function hue(i) { return 'hsl(' + ((i * 67) % 360) + ',55%,52%)'; }

  function timeline(ev, box) {
    var order = [];
    ev.segments.forEach(function (s, i) { s.lines.forEach(function (l) { order.push([l, i]); }); });
    order.sort(function (a, b) { return a[0][3] - b[0][3]; });  // true message order
    var sc = el('div', 'lk-scroll');
    order.forEach(function (p) {
      var d = el('div', 'lk-line'); d.style.borderLeftColor = ev.segments[p[1]].block_id ? hue(p[1]) : 'transparent';
      d.appendChild(el('span', 'tm', p[0][0])); d.appendChild(el('b', '', p[0][1] + '：')); d.appendChild(document.createTextNode(p[0][2]));
      sc.appendChild(d);
    });
    box.appendChild(sc);
  }

  function segments(ev, box) {
    ev.segments.forEach(function (s, i) {
      var det = el('details', 'lk-seg'); det.style.borderLeftColor = s.block_id ? hue(i) : 'transparent';
      var sum = el('summary', '', s.start + '–' + s.end + ' · ' + s.n + ' 条 · ' + (s.summary || '（无摘要）'));
      det.appendChild(sum);
      det.ontoggle = function () {
        if (!det.open || det.dataset.done) return; det.dataset.done = '1';
        var sc = el('div', 'lk-scroll');
        s.lines.forEach(function (l) { var d = el('div', 'lk-line'); d.appendChild(el('span', 'tm', l[0])); d.appendChild(el('b', '', l[1] + '：')); d.appendChild(document.createTextNode(l[2])); sc.appendChild(d); });
        det.appendChild(sc);
      };
      box.appendChild(det);
    });
  }

  var QS = [
    { key: 'memory', title: '1. 看了记录：你对这个晚上有印象吗', options: [['remember', '本来就记得'], ['recognize', '看了才想起来'], ['none', '没印象'], ['absent', '当时没看群']] },
    { key: 'chaos', title: '2. 乱不乱（话题交错、互相打断、刷屏）', options: SCALE('很有条理', '非常乱') },
    { key: 'lively', title: '3. 热闹程度', options: SCALE('冷清', '非常热闹') },
    { key: 'tags', title: '4. 这个晚上有什么', options: TAGS, multi: true, required: false },
    { key: 'what', type: 'text', title: '备注', placeholder: '比如一句话说这个晚上发生了什么' }
  ];
  LK.queue(queueBox, {
    items: D.evenings, answers: st.evenings, save: save, questions: QS,
    render: function (ev, box) {
      box.appendChild(el('p', 'lk-big', ev.label));
      box.appendChild(el('p', 'lk-meta', ev.n + ' 条消息，' + ev.segments.filter(function (s) { return s.block_id; }).length + ' 段话题'));
      var tabs = el('div', 'lk-opts'), view = el('div');
      var t1 = el('button', 'lk-opt', '话题摘要'), t2 = el('button', 'lk-opt', '时间线（全部消息）');
      t1.type = t2.type = 'button';
      function show(which) {
        view.innerHTML = ''; t1.setAttribute('aria-pressed', which === 1); t2.setAttribute('aria-pressed', which === 2);
        if (which === 1) segments(ev, view); else timeline(ev, view);
      }
      t1.onclick = function () { show(1); }; t2.onclick = function () { show(2); };
      tabs.appendChild(t1); tabs.appendChild(t2); box.appendChild(tabs); box.appendChild(view); show(1);
    }
  });

  // Step 2: a choice among the evenings the rater's own answers put on top.
  function rated() { return D.evenings.filter(function (e) { return st.evenings[e.id] && LK.complete(QS, st.evenings[e.id]); }); }
  function topScore(key) {
    return function () {
      var rs = rated(), best = 0;
      rs.forEach(function (e) { var v = parseInt(st.evenings[e.id][key], 10); if (v > best) best = v; });
      return best >= 3 ? rs.filter(function (e) { return parseInt(st.evenings[e.id][key], 10) === best; }) : [];
    };
  }
  var PICKS = [
    ['chaos', '最乱的晚上', '候选：你在「乱不乱」上打分最高的晚上', topScore('chaos')],
    ['lively', '最热闹的晚上', '候选：你在「热闹程度」上打分最高的晚上', topScore('lively')],
    ['awkward', '最尴尬的晚上', '候选：你标了「尴尬场面」的晚上', function () {
      return rated().filter(function (e) { return (st.evenings[e.id].tags || []).indexOf('awkward') >= 0; }); }],
    ['memorable', '最难忘的晚上', '候选：你选了「本来就记得」的晚上', function () {
      return rated().filter(function (e) { return st.evenings[e.id].memory === 'remember'; }); }]
  ];
  function cue(e) {
    var best = null;
    e.segments.forEach(function (s) { if (s.block_id && s.summary && (!best || s.n > best.n)) best = s; });
    var mine = (st.evenings[e.id] || {}).what;
    return e.n + ' 条' + (best ? ' · ' + best.summary : '') + (mine ? ' · 你的备注：' + mine : '');
  }
  var shown = {};
  var redraws = PICKS.map(function (p) {
    var w = el('div', 'lk-q'); w.appendChild(el('div', 'lk-q-title', p[1])); w.appendChild(el('p', 'lk-meta', p[2]));
    var list = el('div'), sig = null;
    var why = el('input'); why.type = 'text'; why.placeholder = '备注（可不填）'; why.value = (st.picks[p[0]] || {}).why || '';
    why.oninput = function () { var cur = st.picks[p[0]] = st.picks[p[0]] || { id: '' }; cur.why = why.value; save(); };
    w.appendChild(list); w.appendChild(why); picksBox.appendChild(w);
    return function () {
      var cands = p[3](), cur = st.picks[p[0]] || { id: '' };
      if (cur.id && cur.id !== 'none' && !cands.some(function (e) { return e.id === cur.id; })) { cur.id = ''; st.picks[p[0]] = cur; }  // no longer a candidate
      shown[p[0]] = cands.map(function (e) { return e.id; });
      var now = shown[p[0]].join(',') + '|' + cur.id + '|' + cands.map(cue).join('|');
      if (now === sig) return; sig = now;
      list.innerHTML = '';
      if (!cands.length) list.appendChild(el('p', 'lk-meta', '还没有候选。'));
      cands.map(function (e) { return [e.id, e.label, cue(e)]; }).concat([['none', '没有明显的', '']]).forEach(function (o) {
        var row = el('div'); row.style.margin = '6px 0';
        var b = el('button', 'lk-opt', o[1]); b.type = 'button'; b.setAttribute('aria-pressed', cur.id === o[0] ? 'true' : 'false');
        b.onclick = function () { st.picks[p[0]] = { id: o[0], why: why.value }; save(); };
        row.appendChild(b);
        if (o[2]) { var m = el('span', 'lk-meta', o[2]); m.style.marginLeft = '8px'; row.appendChild(m); }
        list.appendChild(row);
      });
    };
  });

  function refreshBar() {
    redraws.forEach(function (f) { f(); });
    var p = PICKS.filter(function (k) { return (st.picks[k[0]] || {}).id; }).length;
    bar.textContent = '第 1 步 ' + rated().length + ' / ' + D.evenings.length + '　第 2 步 ' + p + ' / ' + PICKS.length;
  }
  S.onSave(refreshBar); refreshBar();

  dl.onclick = function () {
    LK.download({ pack: D.pack, group: D.group, who: st.who, savedAt: new Date().toISOString(), evenings: st.evenings, picks: st.picks,
      candidates: shown, shown: D.evenings.map(function (e) { return { id: e.id, n: e.n }; }) },
      'labels-' + D.pack + (st.who ? '-' + st.who : '') + '.json');
  };
  reset.onclick = function () { if (confirm('确定清空本机进度？已下载的文件不受影响。')) { S.clear(); location.reload(); } };
})();
