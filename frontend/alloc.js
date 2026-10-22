/* 成本分摊 / 预算管控 */

// ---------------------------------------------------------------- 成本分摊
App.page({
  id: 'alloc', t: '成本分摊',
  render: async (view, st) => {
    const [rules, runs, cd] = await Promise.all([
      App.GET('/api/allocation-rules'), App.GET('/api/allocations?period=' + st.period),
      App.GET('/api/cost-centers?period=' + st.period)]);
    const canWrite = st.user.perms.includes('alloc.write');
    view.innerHTML = `
      <div class="notice">阶梯（顺序）分摊法：辅助中心按分摊顺序依次把「自身归集 + 上游分入」全部摊给顺序更大的中心，
        <b>禁止回分</b>；分摊前后总额必须守恒（校核差应为 0.00）。</div>
      <div class="card" style="margin-bottom:14px">
        <div class="hd"><h3>执行分摊</h3><span class="hint">期间 ${st.period}</span></div>
        <div class="bd">
          <div class="bar">
            ${canWrite ? '<button class="btn pri" id="run">执行本期阶梯分摊</button>' : '<span class="dim">无分摊权限</span>'}
            <span class="dim">分摊基数 = 各中心本期已批准费用归集额</span>
          </div>
        </div>
      </div>

      <div class="card" style="margin-bottom:14px">
        <div class="hd"><h3>分摊规则（${rules.list.length}）</h3>
          <span class="hint">权重按动因量录入，同组内归一化</span>
          ${canWrite ? '<button class="btn" id="addr">+ 新增规则</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'from', t: '分出中心', fmt: r => `${r.from} ${App.esc(r.fromName)}<div class="dim" style="font-size:11.5px">顺序 ${r.fromOrder}</div>`},
          {k: 'to', t: '分入中心', fmt: r => `${r.to} ${App.esc(r.toName)}<div class="dim" style="font-size:11.5px">顺序 ${r.toOrder}</div>`},
          {k: 'driver', t: '动因', cls: 'ctr'},
          {k: 'weight', t: '权重', cls: 'num', fmt: r => App.num(r.weight, 2)},
          {k: 'enabled', t: '启用', cls: 'ctr', fmt: r => r.enabled ? App.tag('启用', App.ST) : App.tag('停用', App.ST)},
          {k: '_op', t: '', cls: 'ctr', fmt: r => canWrite ?
            `<button class="btn gho sm" data-delr="${r.id}">删除</button>` : ''}
        ], rules.list)}</div>
      </div>

      <div class="card">
        <div class="hd"><h3>分摊批次（${runs.list.length}）</h3></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'no', t: '批次号'},
          {k: 'period', t: '期间', cls: 'ctr'},
          {k: 'method', t: '方法', cls: 'ctr'},
          {k: 'baseTotal', t: '分摊前', cls: 'num', fmt: r => App.money(r.baseTotal)},
          {k: 'allocatedTotal', t: '分摊出', cls: 'num', fmt: r => App.money(r.allocatedTotal)},
          {k: 'checkDiff', t: '守恒校核', cls: 'num', fmt: r => Math.abs(r.checkDiff) < 0.02 ?
            `<span class="neg">0.00 ✓</span>` : `<span class="pos">${App.money(r.checkDiff)}</span>`},
          {k: 'operator', t: '执行人', cls: 'ctr'},
          {k: 'createdAt', t: '时间'},
          {k: '_op', t: '', cls: 'ctr', fmt: r => `<button class="btn gho sm" data-run="${r.no}">明细</button>`}
        ], runs.list, {empty: '本期尚未执行分摊'})}</div>
      </div>`;

    if (canWrite) {
      view.querySelector('#run').onclick = () =>
        App.confirmBox('执行阶梯分摊', `将按当前规则对 ${st.period} 重新执行分摊（旧批次保留，报表取最新批次）。确认？`,
          async () => {
            try {
              const r = await App.POST('/api/allocations/run', {period: st.period});
              App.ok(`分摊完成 ${r.no}：总额 ${App.money(r.allocatedTotal)}，校核差 ${App.money(r.checkDiff)}`);
              if (r.orphans && r.orphans.length) App.modal('提示', `<div class="notice warn">以下中心有归集额但未配置分摊规则，其成本保留在本中心：${r.orphans.join('、')}</div>`);
              App.route();
            } catch (e) { App.err(e.message); }
          });
      view.querySelector('#addr').onclick = () => {
        App.modal('新增分摊规则', `<div class="form">
          <div class="f"><label>分出中心（辅助中心）</label><select id="f">${cd.list.map(c => `<option value="${c.code}">${c.code} ${c.name}（顺序${c.allocOrder}）</option>`).join('')}</select></div>
          <div class="f"><label>分入中心</label><select id="t">${cd.list.filter(c => c.ctype === '生产').map(c => `<option value="${c.code}">${c.code} ${c.name}（顺序${c.allocOrder}）</option>`).join('')}</select></div>
          <div class="f"><label>分摊动因</label><select id="dr">${rules.drivers.map(d => `<option>${d}</option>`).join('')}</select></div>
          <div class="f"><label>权重（动因量）</label><input id="w" type="number" step="0.01" value="1"></div>
        </div><div class="notice" style="margin-top:12px">只能从顺序小的中心分给顺序大的中心，否则系统拒绝。</div>`,
          `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`, {after: (m) => {
            m.querySelector('#sv').onclick = async () => {
              try {
                await App.POST('/api/allocation-rules', {from: m.querySelector('#f').value,
                  to: m.querySelector('#t').value, driver: m.querySelector('#dr').value,
                  weight: Number(m.querySelector('#w').value)});
                App.ok('已新增'); App.closeModal(); App.route();
              } catch (e) { App.err(e.message); }
            };
          }});
      };
      view.querySelectorAll('[data-delr]').forEach(b => b.onclick = () =>
        App.confirmBox('删除分摊规则', '删除后需重新执行分摊才生效，确认删除？', async () => {
          try { await App.DEL('/api/allocation-rules/' + b.dataset.delr); App.ok('已删除'); App.route(); }
          catch (e) { App.err(e.message); }
        }, '删除'));
    }
    view.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
      const d = await App.GET('/api/allocations/' + b.dataset.run);
      App.modal(`分摊明细 ${d.run.no}`, `
        <div class="grid g3" style="margin-bottom:14px">
          <div class="kpi"><div class="lb">分摊前合计</div><div class="vl" style="font-size:17px">${App.money(d.run.baseTotal)}</div></div>
          <div class="kpi"><div class="lb">实际分摊出</div><div class="vl" style="font-size:17px">${App.money(d.run.allocatedTotal)}</div></div>
          <div class="kpi ok"><div class="lb">守恒校核差</div><div class="vl" style="font-size:17px">${App.money(d.run.checkDiff)}</div></div>
        </div>
        ${App.table([
          {k: 'step', t: '步骤', cls: 'ctr'},
          {k: 'from', t: '分出中心', fmt: r => `${r.from} ${App.esc(r.fromName)}`},
          {k: 'to', t: '分入中心', fmt: r => `${r.to} ${App.esc(r.toName)}`},
          {k: 'driver', t: '动因', cls: 'ctr'},
          {k: 'weight', t: '权重', cls: 'num'},
          {k: 'baseAmount', t: '待摊金额', cls: 'num', fmt: r => App.money(r.baseAmount)},
          {k: 'amount', t: '分摊额', cls: 'num', fmt: r => `<b>${App.money(r.amount)}</b>`}
        ], d.lines)}`, '<button class="btn pri" data-x>关闭</button>', {wide: true});
    });
  }
});

// ---------------------------------------------------------------- 预算管控
App.page({
  id: 'budget', t: '预算管控',
  render: async (view, st) => {
    const [d, ex, cd, sd] = await Promise.all([
      App.GET('/api/budgets?period=' + st.period), App.GET('/api/budgets/exec?period=' + st.period),
      App.GET('/api/cost-centers?period=' + st.period), App.GET('/api/subjects')]);
    const canWrite = st.user.perms.includes('budget.write');
    const lv = (l) => App.tag(l, App.ST);
    view.innerHTML = `
      <div class="grid g4" style="margin-bottom:14px">
        <div class="kpi"><div class="lb">预算总额</div><div class="vl">¥${App.wan(ex.total.amount)}</div>
          <div class="ft">${d.list.length} 个预算项</div></div>
        <div class="kpi"><div class="lb">已占用</div><div class="vl">¥${App.wan(ex.total.used)}</div>
          <div class="ft">执行率 ${App.pct(ex.total.rate)}</div></div>
        <div class="kpi ${ex.abnormal.length ? 'warn' : 'ok'}"><div class="lb">预警及以上</div>
          <div class="vl">${ex.abnormal.length}</div><div class="ft">执行率 ≥90% 或超支</div></div>
        <div class="kpi"><div class="lb">可用余额</div><div class="vl">¥${App.wan(ex.total.amount - ex.total.used)}</div>
          <div class="ft">超出 110% 阻断费用提交</div></div>
      </div>
      ${ex.abnormal.length ? `<div class="notice warn">以下预算项已预警或超支：${ex.abnormal.map(a =>
        `${App.esc(a.centerName)}/${App.esc(a.subjectName)}（${App.pct(a.rate)}）`).join('、')}</div>` : ''}
      <div class="card">
        <div class="hd"><h3>预算明细（${d.list.length}）</h3><span class="hint">期间 ${st.period}</span>
          ${canWrite ? '<button class="btn pri" id="set">设定预算</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'center', t: '中心', fmt: r => `${r.center}<div class="dim" style="font-size:11.5px">${App.esc(r.centerName)}</div>`},
          {k: 'subjectName', t: '科目'},
          {k: 'category', t: '类别', cls: 'ctr'},
          {k: 'amount', t: '预算', cls: 'num', fmt: r => App.money(r.amount)},
          {k: 'used', t: '已占用', cls: 'num', fmt: r => App.money(r.used)},
          {k: 'left', t: '余额', cls: 'num', fmt: r => `<span class="${r.left < 0 ? 'pos' : ''}">${App.money(r.left)}</span>`},
          {k: 'rate', t: '执行率', cls: 'num', fmt: r => `<b>${App.pct(r.rate)}</b>`},
          {k: 'level', t: '状态', cls: 'ctr', fmt: r => lv(r.level)}
        ], d.list)}</div>
      </div>`;
    if (canWrite) view.querySelector('#set').onclick = () => {
      App.modal('设定预算', `<div class="form">
        <div class="f"><label>成本中心</label><select id="c">${cd.list.map(c => `<option value="${c.code}">${c.code} ${c.name}</option>`).join('')}</select></div>
        <div class="f"><label>科目</label><select id="s">${sd.list.map(s => `<option value="${s.code}">${s.code} ${s.name}</option>`).join('')}</select></div>
        <div class="f"><label>预算金额（元）</label><input id="a" type="number" step="0.01"></div>
      </div><div class="notice" style="margin-top:12px">同一「期间 + 中心 + 科目」重复设定会覆盖原预算，已占用额按已批准费用重算。</div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`, {after: (m) => {
          m.querySelector('#sv').onclick = async () => {
            try {
              await App.POST('/api/budgets', {period: st.period, center: m.querySelector('#c').value,
                subject: m.querySelector('#s').value, amount: Number(m.querySelector('#a').value)});
              App.ok('已保存'); App.closeModal(); App.route();
            } catch (e) { App.err(e.message); }
          };
        }});
    };
  }
});
