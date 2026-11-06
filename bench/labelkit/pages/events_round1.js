/* 事件打标 · 第一轮：给一个群的晚上打分（rate evenings). Data: window.DATA from bench.events.label_pack. */
(function () {
  var D = window.DATA, LK = window.LabelKit, el = LK.el;
  var S = LK.store('label:' + D.pack, { recall: {}, recallDone: false, recallDoneAt: null, evenings: {}, picks: {}, who: '' });
  var st = S.state, save = S.save;
  var app = document.getElementById('app');
  var byId = {}; D.evenings.forEach(function (e) { byId[e.id] = e; });

  app.appendChild(el('h1', '', '事件打标 · ' + D.group + ' · 第一轮'));
  var intro = el('div', 'lk-note');
  intro.innerHTML = '<p><b>这页含原名的群聊记录，仅限本人查看，请勿外传。</b>联系方式和长数字已遮盖。进度自动保存在本机浏览器里，做完点最下面的「下载结果」，把文件发回来。</p>' +
    '<p>这一轮看的是「晚上」：北京时间 18:00 到次日 6:00，消息不少于 ' + D.min_msgs + ' 条的晚上，共 ' + D.evenings.length + ' 个。' +
    '用来做「你还记得最乱的那个晚上吗」这类问题的标准答案。</p>' +
    '<p>共三步。<b>第 1 步先凭印象写</b>，写完才显示后面的记录。第 2 步逐个晚上打分，不必每条消息都读，扫一眼时间线和摘要就行。第 3 步从全部晚上里挑出「最……」的那个。</p>';
  app.appendChild(intro);
  var bar = el('div', 'lk-bar'); app.appendChild(bar);

  // Step 1: cue-less recall, before seeing anything.
  app.appendChild(el('h2', '', '第 1 步：不看记录，凭印象写'));
  app.appendChild(el('div', 'lk-note', '想不起来就写「想不起来」或留空。大概的时间（几月、周几、放假前后）也有用。'));
  var RECALL = [
    ['memorable', '这个群里你印象最深的一两个晚上：大概什么时候、发生了什么、为什么记得'],
    ['chaos', '最乱的那个晚上（话题很多、互相打断、刷屏）'],
    ['lively', '最热闹的那个晚上'],
    ['awkward', '最尴尬的一次']
  ];
  RECALL.forEach(function (r) {
    var w = el('div', 'lk-q'); w.appendChild(el('div', 'lk-q-title', r[1]));
    var t = el('textarea'); t.value = st.recall[r[0]] || '';
    t.oninput = function () { st.recall[r[0]] = t.value; save(); };
    w.appendChild(t); app.appendChild(w);
  });
  var doneBtn = el('button', 'lk-btn', '写完了，显示后面的记录'); app.appendChild(doneBtn);
  var doneNote = el('p', 'lk-meta'); app.appendChild(doneNote);

  var later = el('div', 'lk-locked'); app.appendChild(later);
  later.appendChild(el('h2', '', '第 2 步：逐个晚上打分（' + D.evenings.length + ' 个）'));
  later.appendChild(el('div', 'lk-note', '每个晚上三道必选题，标签和一句话可不填。「时间线」按发言顺序显示全部消息，左边的色条表示它属于哪一段话题，色条频繁变换说明几个话题交错进行。'));
  var queueBox = el('div'); later.appendChild(queueBox);
  later.appendChild(el('h2', '', '第 3 步：挑出「最……」的晚上'));
  later.appendChild(el('div', 'lk-note', '从全部晚上里各挑一个。觉得没有特别突出的，就选「没有明显的」。'));
  var picksBox = el('div'); later.appendChild(picksBox);

  app.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = st.who || '';
  who.oninput = function () { st.who = who.value; save(); }; app.appendChild(who);
  var dl = el('button', 'lk-btn', '下载结果'), reset = el('button', 'lk-btn ghost', '清空本机进度');
  app.appendChild(dl); app.appendChild(reset);

  var SCALE = function (lo, hi) { return [['1', '1 ' + lo], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5 ' + hi], ['na', '看不出']]; };
  var TAGS = [['conflict', '吵架或冲突'], ['flood', '刷屏或接龙'], ['meme', '集体玩梗'], ['awkward', '尴尬场面'], ['news', '重要消息或决定'],
    ['joinleave', '有人来或走'], ['help', '求助或情绪低落'], ['media', '大量图片或视频'], ['deep', '深夜长谈'], ['other', '其他（写在下面）']];

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

  var started = false;
  function start() {
    if (started) return; started = true;
    later.classList.remove('lk-locked');
    LK.queue(queueBox, {
      items: D.evenings, answers: st.evenings, save: save,
      questions: [
        { key: 'memory', title: '1. 你对这个晚上有印象吗', options: [['remember', '本来就记得'], ['recognize', '看了才想起来'], ['none', '没印象']] },
        { key: 'chaos', title: '2. 乱不乱（话题交错、互相打断、刷屏）', options: SCALE('很有条理', '非常乱') },
        { key: 'lively', title: '3. 热闹程度', options: SCALE('冷清', '非常热闹') },
        { key: 'tags', title: '4. 这个晚上有什么', options: TAGS, multi: true, required: false },
        { key: 'what', type: 'text', title: '一句话：这个晚上发生了什么', placeholder: '可不填', showWhen: function () { return true; },
          requiredWhen: function (a) { return (a.tags || []).indexOf('other') >= 0; } }
      ],
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
    var PICKS = [['chaos', '最乱的晚上'], ['lively', '最热闹的晚上'], ['awkward', '最尴尬的晚上'], ['memorable', '最难忘的晚上']];
    PICKS.forEach(function (p) {
      var w = el('div', 'lk-q'); w.appendChild(el('div', 'lk-q-title', p[1]));
      var s = el('select');
      [['', '请选择'], ['none', '没有明显的']].concat(D.evenings.map(function (e) { return [e.id, e.label + '（' + e.n + ' 条）']; }))
        .forEach(function (o) { var op = el('option', '', o[1]); op.value = o[0]; s.appendChild(op); });
      var cur = st.picks[p[0]] || {}; s.value = cur.id || '';
      var why = el('input'); why.type = 'text'; why.placeholder = '为什么（可不填）'; why.value = cur.why || '';
      function upd() { st.picks[p[0]] = { id: s.value, why: why.value }; save(); }
      s.onchange = upd; why.oninput = upd;
      w.appendChild(s); w.appendChild(why); picksBox.appendChild(w);
    });
  }
  doneBtn.onclick = function () {
    if (!st.recallDone) { st.recallDone = true; st.recallDoneAt = new Date().toLocaleString(); save(); }
    doneNote.textContent = '已在 ' + st.recallDoneAt + ' 标记写完；之后再改的内容会照样保存。';
    start();
  };
  if (st.recallDone) doneBtn.onclick();

  var QS = [{ key: 'memory' }, { key: 'chaos' }, { key: 'lively' }];
  function refreshBar() {
    var n = D.evenings.filter(function (e) { return LK.complete(QS, st.evenings[e.id] || {}); }).length;
    var p = Object.keys(st.picks).filter(function (k) { return st.picks[k].id; }).length;
    bar.textContent = '第 1 步 ' + (st.recallDone ? '已写' : '未写') + '　第 2 步 ' + n + ' / ' + D.evenings.length + '　第 3 步 ' + p + ' / 4';
  }
  S.onSave(refreshBar); refreshBar();

  dl.onclick = function () {
    LK.download({ pack: D.pack, group: D.group, who: st.who, savedAt: new Date().toISOString(), recallDone: st.recallDone,
      recallDoneAt: st.recallDoneAt, recall: st.recall, evenings: st.evenings, picks: st.picks,
      shown: D.evenings.map(function (e) { return { id: e.id, n: e.n }; }) },
      'labels-' + D.pack + (st.who ? '-' + st.who : '') + '.json');
  };
  reset.onclick = function () { if (confirm('确定清空本机进度？已下载的文件不受影响。')) { S.clear(); location.reload(); } };
})();
