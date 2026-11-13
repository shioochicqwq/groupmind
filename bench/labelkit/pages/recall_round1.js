/* 回忆标注核对 · 第一轮 (check of the recall labelling). Data: window.DATA from bench.recall.label_pack. */
(function () {
  var D = window.DATA, LK = window.LabelKit, el = LK.el;
  var S = LK.store('label:' + D.pack, { labels: {}, links: {}, who: '' });
  var st = S.state, save = S.save;
  var app = document.getElementById('app');

  app.appendChild(el('h1', '', '回忆标注核对 · ' + D.group + ' · 第一轮'));
  var intro = el('div', 'lk-note');
  intro.innerHTML = '<p><b>这页含原名的群聊记录，仅限本人查看，请勿外传。</b>联系方式和长数字已遮盖。进度自动保存在本机浏览器里，做完点最下面的「下载结果」，把文件发回来。</p>' +
    '<p>目的：模型从群聊里找出了「群友在回忆」的句子并做了分类，这里请你独立判断一遍，用来算模型标得准不准。页面不显示模型的答案。</p>' +
    '<p>「回忆」指：讲述、提到、询问或确认一件过去的事，或过去有人说过的话。提醒将来的事（记得带伞）、忘了去做某事（忘了吃饭）、就在眼前这几条里刚发生的事，都不算。</p>';
  app.appendChild(intro);
  var bar = el('div', 'lk-bar'); app.appendChild(bar);

  function chat(lines, box) {
    var sc = el('div', 'lk-scroll'), hit = null;
    lines.forEach(function (l) {
      var d = el('div', 'lk-line');
      if (l[3]) { d.style.borderLeftColor = 'var(--acc)'; d.style.background = 'var(--acc-soft)'; d.style.fontWeight = '600'; hit = d; }
      d.appendChild(el('span', 'tm', l[0])); d.appendChild(el('b', '', l[1] + '：')); d.appendChild(document.createTextNode(l[2]));
      sc.appendChild(d);
    });
    box.appendChild(sc);
    if (hit) setTimeout(function () { sc.scrollTop = Math.max(0, hit.offsetTop - sc.offsetTop - sc.clientHeight / 2); }, 0);
  }

  var isRecall = function (a) { return a.recall === 'yes'; };
  var Q1 = [
    { key: 'recall', title: '1. 标出的这句是在回忆吗', options: [['yes', '是'], ['no', '不是'], ['unsure', '拿不准']] },
    { key: 'target', title: '2. 回忆的是什么（是回忆才答）', showWhen: isRecall,
      options: [['群内聊天', '这个群以前聊过的内容'], ['群外经历', '群外的亲身经历'], ['作品或知识', '看过玩过学过的东西'], ['不确定', '分不清']] },
    { key: 'form', title: '3. 怎么说的（是回忆才答）', showWhen: isRecall,
      options: [['引原话', '复述了原话'], ['说大意', '用自己的话说了大意'], ['只提到有这回事', '只提到有这回事'], ['没有内容', '在问别人或只说忘了']] },
    { key: 'certainty', title: '4. 说得有多肯定（是回忆才答）', showWhen: isRecall,
      options: [['确定', '肯定'], ['不确定', '不太确定（好像、是不是）'], ['想不起来', '想不起来']] }
  ];
  var found = function (a) { return a.same === 'line' || a.same === 'chat'; };
  var Q2 = [
    { key: 'same', title: '1. 下面这段是被回忆的那次聊天吗',
      options: [['line', '是，就是标出的这句'], ['chat', '是这次聊天，但不是标出的这句'], ['no', '不是'], ['unsure', '拿不准']] },
    { key: 'fidelity', title: '2. 回忆的内容和原文比（找到了才答）', showWhen: found,
      options: [['一致', '一致'], ['部分一致', '部分一致'], ['不一致', '不一致'], ['无法比较', '回忆里没有具体内容']] },
    { key: 'surface', title: '3. 用词和原话比（找到了才答）', showWhen: found,
      options: [['接近原话', '接近原话'], ['换了说法', '换了说法'], ['只是提到', '只是提到有这回事']] },
    { key: 'who', title: '4. 回忆的人有没有说是谁说的（找到了才答）', showWhen: found,
      options: [['说对了', '说了，说对了'], ['说错了', '说了，说错了'], ['没提是谁', '没说是谁']] }
  ];

  app.appendChild(el('h2', '', '第 1 部分：这句是不是回忆（' + D.labels.length + ' 条）'));
  app.appendChild(el('div', 'lk-note', '绿色底的是要判断的那一句，前后是上下文。'));
  var box1 = el('div'); app.appendChild(box1);
  LK.queue(box1, { items: D.labels, questions: Q1, answers: st.labels, save: save,
    render: function (it, box) { chat(it.lines, box); } });

  app.appendChild(el('h2', '', '第 2 部分：找到的原文对不对（' + D.links.length + ' 对）'));
  app.appendChild(el('div', 'lk-note', '上面是回忆时的聊天，绿色底的是回忆的那句。下面是模型找到的更早的一段，绿色底的是它认为的原话。同一句回忆可能出现两次，配的是不同的原文。'));
  var box2 = el('div'); app.appendChild(box2);
  LK.queue(box2, { items: D.links, questions: Q2, answers: st.links, save: save,
    render: function (it, box) {
      box.appendChild(el('p', 'lk-meta', '回忆时的聊天'));
      chat(it.recall, box);
      box.appendChild(el('p', 'lk-meta', '更早的一段（在回忆之前约 ' + it.gap + '）'));
      chat(it.origin, box);
    } });

  app.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = st.who || '';
  who.oninput = function () { st.who = who.value; save(); }; app.appendChild(who);
  var dl = el('button', 'lk-btn', '下载结果'), reset = el('button', 'lk-btn ghost', '清空本机进度');
  app.appendChild(dl); app.appendChild(reset);

  function done(items, qs, ans) { return items.filter(function (it) { return ans[it.id] && ans[it.id][qs[0].key] && LK.complete(qs, ans[it.id]); }).length; }
  function refreshBar() {
    bar.textContent = '第 1 部分 ' + done(D.labels, Q1, st.labels) + ' / ' + D.labels.length + '　第 2 部分 ' + done(D.links, Q2, st.links) + ' / ' + D.links.length;
  }
  S.onSave(refreshBar); refreshBar();

  dl.onclick = function () {
    LK.download({ pack: D.pack, group: D.group, who: st.who, savedAt: new Date().toISOString(), labels: st.labels, links: st.links,
      shown: { labels: D.labels.map(function (x) { return x.id; }), links: D.links.map(function (x) { return x.id; }) } },
      'labels-' + D.pack + (st.who ? '-' + st.who : '') + '.json');
  };
  reset.onclick = function () { if (confirm('确定清空本机进度？已下载的文件不受影响。')) { S.clear(); location.reload(); } };
})();
