/* 梗表与人物 · 第一轮（slang table and people, round 1). Data: window.DATA from the generator. */
(function () {
  var D = window.DATA, LK = window.LabelKit, el = LK.el;
  var S = LK.store('label:' + D.pack, { recall: [], recallDone: false, recallDoneAt: null, terms: {}, rejected: {}, people: {}, pairs: [], seq: 0, who: '' });
  var st = S.state, save = S.save;
  var app = document.getElementById('app');

  app.appendChild(el('h1', '', '梗表与人物 · 第一轮'));
  var intro = el('div', 'lk-note');
  intro.innerHTML = '<p><b>这页含原名的群聊片段，仅限本人查看，请勿外传。</b>联系方式和长数字已遮盖。进度自动保存在本机浏览器里，做完点最下面的「下载结果」，把文件发回来。</p>' +
    '<p>共四步。<b>第 1 步一定要先做</b>：不看后面的内容，凭记忆列出这个群的梗和外号。点「我列完了」之后，第 2–4 步才会显示。这样才能测出表里<b>漏了</b>多少。</p>';
  app.appendChild(intro);
  var bar = el('div', 'lk-bar'); app.appendChild(bar);

  app.appendChild(el('h2', '', '第 1 步：凭记忆列出这个群的梗、黑话、外号'));
  app.appendChild(el('div', 'lk-note', '能想到多少写多少，20–50 个最好。外号写「外号 → 指谁」。不确定含义也可以先写词。'));
  var recallBox = el('div'); app.appendChild(recallBox);
  var KINDS = [['local', '本群的梗或黑话'], ['general', '圈内或网上通用的说法'], ['nick', '外号或人名'], ['catch', '口头禅或固定句式']];
  LK.recall(recallBox, { state: st, save: save, kinds: KINDS });
  var doneBtn = el('button', 'lk-btn', '我列完了，显示后面的步骤'); app.appendChild(doneBtn);
  var doneNote = el('p', 'lk-meta'); app.appendChild(doneNote);

  var later = el('div', 'lk-locked'); app.appendChild(later);
  later.appendChild(el('h2', '', '第 2 步：人物表'));
  later.appendChild(el('div', 'lk-note', '左边是群里所有发过言的账号，带历史群昵称。勾选几个账号，标注它们是不是同一个人；选一个账号再加外号。这一步不要求做完，做多少算多少。'));
  var peopleBox = el('div'); later.appendChild(peopleBox);

  later.appendChild(el('h2', '', '第 3 步：判断表里的词（' + D.terms.length + ' 个）'));
  later.appendChild(el('div', 'lk-note', '上一轮已经被两个人以上打过的 ' + D.skipped + ' 个词不再出现。每个词两道必选题：它是什么、机器写的含义对不对。选了「不正确」必须写正确的意思。选完会自动跳到下一题。'));
  var termBox = el('div'); later.appendChild(termBox);

  later.appendChild(el('h2', '', '第 4 步：被机器丢掉的候选（' + D.rejected.length + ' 个）'));
  later.appendChild(el('div', 'lk-note', '这些词在建表时被丢掉了：有的出现次数不够，有的被模型判断为「不是梗」。如果其实是梗或外号，请写出含义或指谁。'));
  var rejBox = el('div'); later.appendChild(rejBox);

  app.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = st.who || '';
  who.oninput = function () { st.who = who.value; save(); }; app.appendChild(who);
  var dl = el('button', 'lk-btn', '下载结果'), reset = el('button', 'lk-btn ghost', '清空本机进度');
  app.appendChild(dl); app.appendChild(reset);

  var SRC = { model: '模型提取', stats: '统计初筛' };
  var WHY = { model_judged_no: '模型提取，但写词条时被判为「不是梗」', model_failed_gate: '模型提取，但出现次数、人数或天数不够', stats_judged_no: '统计初筛，但写词条时被判为「不是梗」' };
  var TYPE = [['local', '本群的梗或黑话'], ['general', '圈内或网上通用'], ['nick', '外号或人名'], ['catch', '口头禅或固定句式'], ['not', '不是梗'], ['unknown', '不了解']];
  var CORRECT = [['right', '正确'], ['partial', '部分正确'], ['wrong', '不正确'], ['unknown', '无法判断']];

  var started = false;
  function start() {
    if (started) return; started = true;
    later.classList.remove('lk-locked');
    LK.people(peopleBox, { accounts: D.accounts, state: st, save: save });
    LK.queue(termBox, {
      items: D.terms, answers: st.terms, save: save,
      questions: [
        { key: 'type', title: '1. 它是什么', options: TYPE },
        { key: 'correct', title: '2. 机器写的含义对吗', options: CORRECT },
        { key: 'fix', type: 'text', title: '正确的意思', placeholder: '写出这个词在群里真正的意思',
          showWhen: function (a) { return a.correct === 'wrong' || a.correct === 'partial'; },
          requiredWhen: function (a) { return a.correct === 'wrong'; } }
      ],
      render: function (t, box) {
        box.appendChild(el('p', 'lk-big', t.term));
        box.appendChild(el('p', 'lk-meta', '来源：' + t.sources.map(function (x) { return SRC[x]; }).join(' + ')));
        t.senses.forEach(function (x, j) {
          box.appendChild(el('p', '', (t.senses.length > 1 ? '机器写的含义（' + SRC[t.sources[j]] + '）：' : '机器写的含义：') + x.meaning));
          if (x.usage) box.appendChild(el('p', 'lk-meta', '用法：' + x.usage + (x.confidence ? '　置信度：' + x.confidence : '')));
        });
        LK.examples(box, t.examples, '例句（建表所用时间段内随机抽取，共出现 ' + t.uses + ' 次）：');
      }
    });
    LK.queue(rejBox, {
      items: D.rejected, answers: st.rejected, save: save,
      questions: [
        { key: 'type', title: '它是什么', options: TYPE },
        { key: 'meaning', type: 'text', title: '含义，或者外号指谁', placeholder: '是梗就写意思，是外号就写指谁',
          showWhen: function (a) { return ['local', 'general', 'nick', 'catch'].indexOf(a.type) >= 0; },
          requiredWhen: function (a) { return ['local', 'nick'].indexOf(a.type) >= 0; } }
      ],
      render: function (t, box) {
        box.appendChild(el('p', 'lk-big', t.term));
        box.appendChild(el('p', 'lk-meta', WHY[t.why] || t.why));
        LK.examples(box, t.examples, '例句（共出现 ' + t.uses + ' 次）：');
      }
    });
  }
  doneBtn.onclick = function () {
    if (!st.recallDone) { st.recallDone = true; st.recallDoneAt = new Date().toLocaleString(); save(); }
    doneNote.textContent = '已在 ' + st.recallDoneAt + ' 标记列完；之后再补的词会单独标出。';
    start();
  };
  if (st.recallDone) doneBtn.onclick();

  function refreshBar() {
    var r = st.recall.filter(function (x) { return (x.word || '').trim(); }).length;
    var t = D.terms.filter(function (x) { return LK.complete([{ key: 'type' }, { key: 'correct' }], st.terms[x.id] || {}) && !((st.terms[x.id] || {}).correct === 'wrong' && !((st.terms[x.id] || {}).fix || '').trim()); }).length;
    bar.textContent = '第 1 步 ' + r + ' 个　第 2 步 人物 ' + Object.keys(st.people || {}).length + ' 个　第 3 步 ' + t + ' / ' + D.terms.length + '　第 4 步 ' + Object.keys(st.rejected).filter(function (k) { return st.rejected[k].type; }).length + ' / ' + D.rejected.length;
  }
  S.onSave(refreshBar); refreshBar();

  dl.onclick = function () {
    LK.download({ pack: D.pack, group: D.group, who: st.who, savedAt: new Date().toISOString(), recallDone: st.recallDone, recallDoneAt: st.recallDoneAt,
      recall: st.recall.filter(function (r) { return (r.word || '').trim(); }), people: st.people, pairs: st.pairs,
      terms: st.terms, rejected: st.rejected, counts: D.counts, skipped: D.skipped_terms },
      'labels-' + D.pack + (st.who ? '-' + st.who : '') + '.json');
  };
  reset.onclick = function () { if (confirm('确定清空本机进度？已下载的文件不受影响。')) { S.clear(); location.reload(); } };
})();
