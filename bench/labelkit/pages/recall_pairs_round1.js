/* 回忆对比盲评 · 第一轮 (blind pairs: frozen memory vs impressions). Data: window.DATA from bench.recall.pair_pack. */
(function () {
  var D = window.DATA, LK = window.LabelKit, el = LK.el;
  var S = LK.store('label:' + D.pack, { known: {}, absent: {}, who: '' });
  var st = S.state, save = S.save;
  var app = document.getElementById('app');

  app.appendChild(el('h1', '', '回忆对比盲评 · ' + D.group + ' · 第一轮'));
  var intro = el('div', 'lk-note');
  intro.innerHTML = '<p><b>这页含原名和群聊内容，仅限本人查看，请勿外传。</b>进度自动保存在本机浏览器里，做完点最下面的「下载结果」，把文件发回来。</p>' +
    '<p>每题是一个关于群里旧事的问题，和两个回答（甲、乙）。两个回答出自同一个模型、同一句指令，区别只在给它的「记忆」不同：一种是现在的检索直接给原文，一种是按「当时留下的印象」给。哪个是哪个每题随机，页面里没有答案。</p>' +
    '<p>全部是选择题，备注可不填。回答下面附了当时的原文（绿色底的是问题问到的那几句），不需要自己凭空回想。</p>' +
    '<p>「像不像人」和「有没有用」请分开判断：一个回答可以很有用但像在查记录，也可以很像人但没帮上忙。</p>';
  app.appendChild(intro);
  var bar = el('div', 'lk-bar'); app.appendChild(bar);

  var PAIR = [['a', '甲'], ['b', '乙'], ['same', '差不多']];
  // Recognition with the original in view; the first page asked for recall before showing anything.
  var Q_SEEN = { key: 'seen', title: '对照上面的原文：这件事你有印象吗',
    options: [['深', '一看就认得，连原话都还记得'], ['中', '记得有这回事，大意对得上'], ['浅', '看了才隐约想起来'], ['无', '看了也没印象'], ['不在', '当时没看到']] };
  var Q_HUMAN = { key: 'human', title: '哪个更像一个真人群友在回想', options: PAIR };
  var Q_USE = { key: 'useful', title: '哪个对提问的人更有用', options: PAIR };
  var Q_ODD = { key: 'odd', title: '有没有不对劲的地方', multi: true, required: false,
    options: [['a_made_up', '甲说了没有的事'], ['b_made_up', '乙说了没有的事'], ['a_lookup', '甲像在念聊天记录'], ['b_lookup', '乙像在念聊天记录'],
      ['a_blank', '甲不该不记得'], ['b_blank', '乙不该不记得']] };
  var Q_NOTE = { key: 'note', type: 'text', title: '备注', placeholder: '比如：这件事谁都该记得 / 这种细节没人会记得' };
  function numbered(qs) { return qs.map(function (q, i) { var c = Object.assign({}, q); c.title = (i + 1) + '. ' + c.title; return c; }); }
  var Q1 = numbered([Q_HUMAN, Q_USE, Q_ODD, Q_SEEN, Q_NOTE]);
  var Q2 = numbered([Q_HUMAN, Q_USE, Q_ODD, Q_NOTE]);

  function show(it, box) {
    box.appendChild(el('p', 'lk-big', it.question));
    if (it.when) box.appendChild(el('p', 'lk-meta', '这件事发生在' + it.when + '（以聊天记录的最后一天为「现在」）'));
    [['甲', it.a], ['乙', it.b]].forEach(function (p) {
      var d = el('div', 'lk-line'); d.appendChild(el('b', '', p[0] + '：')); d.appendChild(document.createTextNode(p[1])); box.appendChild(d);
    });
    if (it.reference) box.appendChild(el('p', 'lk-meta', '出题时的参考答案：' + it.reference));
    if (it.origin && it.origin.length) {
      box.appendChild(el('p', 'lk-meta', '当时的原文'));
      var sc = el('div', 'lk-scroll');
      it.origin.forEach(function (l) {
        var d = el('div', 'lk-line');
        if (!l[1]) { d.textContent = l[2]; d.style.color = 'var(--mut)'; sc.appendChild(d); return; }
        if (l[3]) { d.style.borderLeftColor = 'var(--acc)'; d.style.background = 'var(--acc-soft)'; d.style.fontWeight = '600'; }
        d.appendChild(el('span', 'tm', l[0])); d.appendChild(el('b', '', l[1] + '：')); d.appendChild(document.createTextNode(l[2]));
        sc.appendChild(d);
      });
      box.appendChild(sc);
    }
  }

  app.appendChild(el('h2', '', '第 1 部分：群里聊过的事（' + D.known.length + ' 题）'));
  var box1 = el('div'); app.appendChild(box1);
  LK.queue(box1, { items: D.known, questions: Q1, answers: st.known, save: save, render: show });

  app.appendChild(el('h2', '', '第 2 部分：还没发生的事（' + D.absent.length + ' 题）'));
  app.appendChild(el('div', 'lk-note', '这几题把「现在」拨回到这件事发生之前再问，那时还没有可记的东西，正确的反应是说不知道或不记得。'));
  var box2 = el('div'); app.appendChild(box2);
  LK.queue(box2, { items: D.absent, questions: Q2, answers: st.absent, save: save, render: show });

  app.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = st.who || '';
  who.oninput = function () { st.who = who.value; save(); }; app.appendChild(who);
  var dl = el('button', 'lk-btn', '下载结果'), reset = el('button', 'lk-btn ghost', '清空本机进度');
  app.appendChild(dl); app.appendChild(reset);

  function done(items, qs, ans) { return items.filter(function (it) { return LK.complete(qs, ans[it.id] || {}); }).length; }
  function refreshBar() {
    bar.textContent = '第 1 部分 ' + done(D.known, Q1, st.known) + ' / ' + D.known.length + '　第 2 部分 ' + done(D.absent, Q2, st.absent) + ' / ' + D.absent.length;
  }
  S.onSave(refreshBar); refreshBar();

  dl.onclick = function () {
    LK.download({ pack: D.pack, group: D.group, who: st.who, savedAt: new Date().toISOString(), known: st.known, absent: st.absent,
      shown: { known: D.known.map(function (x) { return x.id; }), absent: D.absent.map(function (x) { return x.id; }) } },
      'labels-' + D.pack + (st.who ? '-' + st.who : '') + '.json');
  };
  reset.onclick = function () { if (confirm('确定清空本机进度？已下载的文件不受影响。')) { S.clear(); location.reload(); } };
})();
