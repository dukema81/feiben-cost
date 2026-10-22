/* 差异分析 / 报表中心 / 期间结账 */

// ---------------------------------------------------------------- 差异分析
App.page({
  id: 'variance', t: '差异分析',
  render: async (view, st) => {
    const d = await App.GET('/api/variances?period=' + st.period);
    const canCalc = st.user.perms.includes('report.read');
    const sum = d.list.reduce((a, x) => {
      a.total += x.totalVar; a.price += x.priceVar; a.qty += x.qtyVar;
      a.rate += x.rateVar; a.eff += x.effVar; a.exp += x.expenseVar; return a;
    }, {total: 0, price: 0, qty: 0, rate: 0, eff: 0, exp: 0});
    const cell = (v) => `<span class="${v > 0 ? 'pos' : v < 0 ? 'neg' : ''}">${App.sign(v)}${App.money(v)}</span>`;
    view.innerHTML = `
      <div class="notice">两因素法分解：材料 <b>价差 =(实际单价−标准单价)×实际量</b>，<b>量差 =(实际量−标准量)×标准价</b>；
        人工 <b>工资率差 =(实际工资率−标准)×实际工时</b>，<b>效率差 =(实际工时−标准工时)×标准工资率</b>。
        五项之和必须等于总差异（校核差 0.00），尾差已归入材料量差。</div>
      <div class="card">
        <div class="hd"><h3>成本差异（${d.list.length}）</h3><span class="hint">期间 ${st.period}</span>
          ${canCalc ? '<button class="btn pri" id="calc">计算本期差异</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'product', t: '产品', fmt: r => `${r.product}<div class="dim" style="font-size:11.5px">${App.esc(r.productName)}</div>`},
          {k: 'qty', t: '产量', cls: 'num', fmt: r => App.num(r.qty, 0)},
          {k: 'stdUnitCost', t: '标准单价', cls: 'num', fmt: r => App.money(r.stdUnitCost)},
          {k: 'actUnitCost', t: '实际单价', cls: 'num', fmt: r => App.money(r.actUnitCost)},
          {k: 'stdTotal', t: '标准总额', cls: 'num', fmt: r => App.money(r.stdTotal)},
          {k: 'actTotal', t: '实际总额', cls: 'num', fmt: r => App.money(r.actTotal)},
          {k: 'totalVar', t: '总差异', cls: 'num', fmt: r => `<b>${cell(r.totalVar)}</b>`},
          {k: 'priceVar', t: '材料价差', cls: 'num', fmt: r => cell(r.priceVar)},
          {k: 'qtyVar', t: '材料量差', cls: 'num', fmt: r => cell(r.qtyVar)},
          {k: 'rateVar', t: '工资率差', cls: 'num', fmt: r => cell(r.rateVar)},
          {k: 'effVar', t: '效率差', cls: 'num', fmt: r => cell(r.effVar)},
          {k: 'checkDiff', t: '校核', cls: 'num', fmt: r => Math.abs(r.checkDiff) < 0.02 ?
            '<span class="neg">✓</span>' : `<span class="pos">${App.money(r.checkDiff)}</span>`},
          {k: 'level', t: '等级', cls: 'ctr', fmt: r => App.tag(r.level, App.ST)},
          {k: '_op', t: '', cls: 'ctr', fmt: r => `<button class="btn gho sm" data-x="${r.product}">分解</button>`}
        ], d.list, {empty: '本期尚未计算差异，点击右上角「计算本期差异」'})}</div>
      </div>
      ${d.list.length ? `<div class="card" style="margin-top:14px"><div class="hd"><h3>差异构成合计</h3></div>
        <div class="bd"><div class="grid g4">
          <div class="kpi ${sum.total > 0 ? 'bad' : 'ok'}"><div class="lb">总差异</div><div class="vl" style="font-size:18px">${App.sign(sum.total)}${App.money(sum.total)}</div></div>
          <div class="kpi"><div class="lb">材料价差</div><div class="vl" style="font-size:18px">${App.sign(sum.price)}${App.money(sum.price)}</div></div>
          <div class="kpi"><div class="lb">材料量差</div><div class="vl" style="font-size:18px">${App.sign(sum.qty)}${App.money(sum.qty)}</div></div>
          <div class="kpi"><div class="lb">工资率差</div><div class="vl" style="font-size:18px">${App.sign(sum.rate)}${App.money(sum.rate)}</div></div>
          <div class="kpi"><div class="lb">效率差</div><div class="vl" style="font-size:18px">${App.sign(sum.eff)}${App.money(sum.eff)}</div></div>
        </div></div></div>` : ''}`;

    if (canCalc) view.querySelector('#calc').onclick = () =>
      App.confirmBox('计算成本差异', `将按 ${st.period} 已完工工单与当期标准成本计算全部产品差异。确认？`, async () => {
        try {
          const r = await App.POST('/api/variances/calc', {period: st.period});
          App.ok(`已计算 ${r.count} 个产品`);
          if (r.warnings && r.warnings.length) App.modal('提示', r.warnings.map(w => `<div class="check">⚠ ${App.esc(w)}</div>`).join(''));
          App.route();
        } catch (e) { App.err(e.message); }
      });
    view.querySelectorAll('[data-x]').forEach(b => b.onclick = () => {
      const x = d.list.find(r => r.product === b.dataset.x);
      App.modal(`差异分解 · ${x.product} ${x.productName}`, `
        <div class="kv">
          <span class="k">产量</span><span>${App.num(x.qty, 0)}</span>
          <span class="k">单位标准成本</span><span>${App.money(x.stdUnitCost)}</span>
          <span class="k">单位实际成本</span><span>${App.money(x.actUnitCost)}</span>
          <span class="k">标准总额</span><span>${App.money(x.stdTotal)}</span>
          <span class="k">实际总额</span><span>${App.money(x.actTotal)}</span>
          <span class="k">总差异</span><span class="${x.totalVar > 0 ? 'pos' : 'neg'}">${App.sign(x.totalVar)}${App.money(x.totalVar)}</span>
        </div>
        <div class="card" style="margin-top:14px"><div class="hd"><h3>逐项分解</h3></div><div class="bd nopad">
        ${App.table([{k: 'n', t: '差异项'}, {k: 'v', t: '金额', cls: 'num', fmt: r => cell(r.v)},
                     {k: 'f', t: '公式'}], [
          {n: '材料价差', v: x.priceVar, f: '(实际单价 − 标准单价) × 实际用量'},
          {n: '材料量差', v: x.qtyVar, f: '(实际用量 − 标准用量) × 标准单价（含取整尾差）'},
          {n: '工资率差', v: x.rateVar, f: '(实际工资率 − 标准工资率) × 实际工时'},
          {n: '效率差', v: x.effVar, f: '(实际工时 − 标准工时) × 标准工资率'},
          {n: '制费耗费差', v: x.expenseVar, f: '实际制费 − 实际工时 × 标准分配率（预定分配率法下为 0）'}
        ])}</div></div>
        <div class="notice" style="margin-top:12px">等级判定：差异率 ≥10% 为重大，1%~10% 为一般，&lt;1% 为微小；
          正数为不利差异（超支），负数为有利差异（节约）。</div>`,
        '<button class="btn pri" data-x>关闭</button>', {wide: true});
    });
  }
});

// ---------------------------------------------------------------- 报表中心
App.page({
  id: 'report', t: '报表中心',
  render: async (view, st) => {
    const tab = st.repTab || 'center';
    const tabs = [['center', '成本中心汇总'], ['product', '产品成本卡'],
                  ['vtop', '差异 TOP10'], ['trend', '成本趋势']];
    const head = `<div class="tabs">${tabs.map(([k, t]) =>
      `<button class="${tab === k ? 'on' : ''}" data-tab="${k}">${t}</button>`).join('')}</div>`;
    let html = '';
    if (tab === 'center') {
      const d = await App.GET('/api/reports/center-summary?period=' + st.period);
      html = `<div class="grid g4" style="margin-bottom:14px">
          <div class="kpi"><div class="lb">直接归集</div><div class="vl">¥${App.wan(d.total.direct)}</div></div>
          <div class="kpi"><div class="lb">分入合计</div><div class="vl">¥${App.wan(d.total.allocIn)}</div></div>
          <div class="kpi"><div class="lb">分出合计</div><div class="vl">¥${App.wan(d.total.allocOut)}</div></div>
          <div class="kpi ok"><div class="lb">净成本合计</div><div class="vl">¥${App.wan(d.total.net)}</div></div>
        </div>
        <div class="card"><div class="hd"><h3>成本中心汇总 · ${st.period}</h3>
          <a class="btn sm" href="api/reports/centers.csv?period=${st.period}&token=${localStorage.getItem('fb_token')}">导出 CSV</a></div>
          <div class="bd nopad scroll">${App.table([
            {k: 'code', t: '编码'}, {k: 'name', t: '中心'},
            {k: 'ctype', t: '类型', cls: 'ctr'},
            {k: 'direct', t: '直接归集', cls: 'num', fmt: r => App.money(r.direct)},
            {k: 'allocIn', t: '分入', cls: 'num', fmt: r => App.money(r.allocIn)},
            {k: 'allocOut', t: '分出', cls: 'num', fmt: r => App.money(r.allocOut)},
            {k: 'total', t: '净成本', cls: 'num', fmt: r => `<b>${App.money(r.total)}</b>`},
            {k: 'budget', t: '预算', cls: 'num', fmt: r => App.money(r.budget)},
            {k: 'rate', t: '预算执行', cls: 'num', fmt: r => r.budget ? App.pct(r.rate) : '<span class="dim">—</span>'},
            {k: 'orderCount', t: '工单', cls: 'ctr'}
          ], d.list)}</div></div>`;
    } else if (tab === 'product') {
      const d = await App.GET('/api/reports/product-cost?period=' + st.period);
      html = `<div class="grid g4" style="margin-bottom:14px">
          <div class="kpi"><div class="lb">标准成本合计</div><div class="vl">¥${App.wan(d.total.std)}</div></div>
          <div class="kpi"><div class="lb">实际成本合计</div><div class="vl">¥${App.wan(d.total.act)}</div></div>
          <div class="kpi ${d.total.var > 0 ? 'warn' : 'ok'}"><div class="lb">差异合计</div>
            <div class="vl">${App.sign(d.total.var)}¥${App.wan(d.total.var)}</div>
            <div class="ft">差异率 ${App.pct(d.total.std ? d.total.var / d.total.std : 0)}</div></div>
          <div class="kpi"><div class="lb">测算毛利率（均值）</div>
            <div class="vl">${App.pct(d.list.length ? d.list.reduce((a, x) => a + x.grossRate, 0) / d.list.length : 0)}</div></div>
        </div>
        <div class="card"><div class="hd"><h3>产品成本卡 · ${st.period}</h3>
          <a class="btn sm" href="api/reports/products.csv?period=${st.period}&token=${localStorage.getItem('fb_token')}">导出 CSV</a></div>
          <div class="bd nopad scroll">${App.table([
            {k: 'product', t: '产品', fmt: r => `${r.product}<div class="dim" style="font-size:11.5px">${App.esc(r.productName)}</div>`},
            {k: 'qty', t: '产量', cls: 'num', fmt: r => App.num(r.qty, 0)},
            {k: 'stdUnit', t: '单位标准', cls: 'num', fmt: r => App.money(r.stdUnit)},
            {k: 'actUnit', t: '单位实际', cls: 'num', fmt: r => App.money(r.actUnit)},
            {k: 'stdTotal', t: '标准总额', cls: 'num', fmt: r => App.money(r.stdTotal)},
            {k: 'actTotal', t: '实际总额', cls: 'num', fmt: r => App.money(r.actTotal)},
            {k: 'var', t: '差异', cls: 'num', fmt: r => `<span class="${r.var > 0 ? 'pos' : 'neg'}">${App.sign(r.var)}${App.money(r.var)}</span>`},
            {k: 'varRate', t: '差异率', cls: 'num', fmt: r => App.pct(r.varRate)},
            {k: 'level', t: '等级', cls: 'ctr', fmt: r => App.tag(r.level, App.ST)},
            {k: 'listPrice', t: '售价', cls: 'num', fmt: r => App.money(r.listPrice)},
            {k: 'grossRate', t: '毛利率', cls: 'num', fmt: r => App.pct(r.grossRate)}
          ], d.list, {empty: '本期没有已完工工单'})}</div></div>`;
    } else if (tab === 'vtop') {
      const d = await App.GET('/api/reports/variance-top?period=' + st.period + '&n=10');
      html = `<div class="card"><div class="hd"><h3>差异 TOP10 · ${st.period}</h3>
        <span class="hint">按差异绝对值排序</span></div>
        <div class="bd">${d.list.length ? App.bars(d.list.map(x => ({
          name: x.product, amount: x.totalVar, color: x.totalVar > 0 ? '#e07a5f' : '#0a8f4d'})),
          {key: 'name', val: 'amount'}) : '<div class="empty">暂无数据</div>'}</div>
        <div class="bd nopad">${App.table([
          {k: 'product', t: '产品'},
          {k: 'productName', t: '名称'},
          {k: 'totalVar', t: '总差异', cls: 'num', fmt: r => `<span class="${r.totalVar > 0 ? 'pos' : 'neg'}">${App.sign(r.totalVar)}${App.money(r.totalVar)}</span>`},
          {k: 'priceVar', t: '价差', cls: 'num', fmt: r => App.money(r.priceVar)},
          {k: 'qtyVar', t: '量差', cls: 'num', fmt: r => App.money(r.qtyVar)},
          {k: 'rateVar', t: '工资率差', cls: 'num', fmt: r => App.money(r.rateVar)},
          {k: 'effVar', t: '效率差', cls: 'num', fmt: r => App.money(r.effVar)},
          {k: 'level', t: '等级', cls: 'ctr', fmt: r => App.tag(r.level, App.ST)}
        ], d.list)}</div></div>`;
    } else {
      const d = await App.GET('/api/reports/trend?months=12&period=' + st.period);
      html = `<div class="card"><div class="hd"><h3>12 期成本趋势</h3>
        <span class="hint">标准 / 实际 / 直接归集</span></div>
        <div class="bd">${App.lineChart([
          {name: '标准成本', data: d.list.map(x => x.standard), color: '#1f6feb'},
          {name: '实际成本', data: d.list.map(x => x.actual), color: '#f2994a'},
          {name: '直接归集', data: d.list.map(x => x.direct), color: '#0a8f4d'}
        ], d.list.map(x => x.period.slice(2)))}</div>
        <div class="bd nopad">${App.table([
          {k: 'period', t: '期间'}, {k: 'qty', t: '产量', cls: 'num'},
          {k: 'standard', t: '标准成本', cls: 'num', fmt: r => App.money(r.standard)},
          {k: 'actual', t: '实际成本', cls: 'num', fmt: r => App.money(r.actual)},
          {k: 'variance', t: '差异', cls: 'num', fmt: r => `<span class="${r.variance > 0 ? 'pos' : 'neg'}">${App.sign(r.variance)}${App.money(r.variance)}</span>`},
          {k: 'varRate', t: '差异率', cls: 'num', fmt: r => App.pct(r.varRate)},
          {k: 'direct', t: '直接归集', cls: 'num', fmt: r => App.money(r.direct)}
        ], d.list)}</div></div>`;
    }
    view.innerHTML = head + html;
    view.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { st.repTab = b.dataset.tab; App.route(); });
  }
});

// ---------------------------------------------------------------- 期间结账
App.page({
  id: 'period', t: '期间结账',
  render: async (view, st) => {
    const d = await App.GET('/api/periods');
    const canClose = st.user.perms.includes('period.close');
    const isAdmin = st.user.role === 'admin';
    view.innerHTML = `
      <div class="notice">结账闸口（三项全通过才允许结账）：① 无待审批费用单 ② 无未完工工单 ③ 本期已执行分摊。
        结账后该期间所有费用单、工单、分摊、预算写入一律拒绝；反结账仅管理员可操作并记入审计日志。</div>
      <div class="card">
        <div class="hd"><h3>会计期间（${d.list.length}）</h3>
          ${canClose ? '<button class="btn pri" id="add">+ 新建期间</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'period', t: '期间'},
          {k: 'status', t: '状态', cls: 'ctr', fmt: r => App.tag(r.status, App.ST)},
          {k: 'expenseCount', t: '费用单', cls: 'ctr'},
          {k: 'pendingExpenses', t: '待审批', cls: 'ctr', fmt: r => r.pendingExpenses ?
            `<span class="pos">${r.pendingExpenses}</span>` : '0'},
          {k: 'orderCount', t: '工单', cls: 'ctr'},
          {k: 'openOrders', t: '未完工', cls: 'ctr', fmt: r => r.openOrders ?
            `<span class="pos">${r.openOrders}</span>` : '0'},
          {k: 'allocDone', t: '分摊', cls: 'ctr', fmt: r => r.allocDone ? App.tag('已执行', App.ST) : '<span class="dim">未执行</span>'},
          {k: 'expenseTotal', t: '归集额', cls: 'num', fmt: r => App.money(r.expenseTotal)},
          {k: 'closedBy', t: '结账人', cls: 'ctr'},
          {k: 'closedAt', t: '结账时间'},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r => {
            if (r.status === '打开' && canClose) return `<button class="btn gho sm" data-close="${r.period}">结账</button>`;
            if (r.status === '已结账' && isAdmin) return `<button class="btn gho sm" data-reopen="${r.period}">反结账</button>`;
            return '<span class="dim">—</span>';
          }}
        ], d.list)}</div>
      </div>`;
    view.querySelectorAll('[data-close]').forEach(b => b.onclick = () =>
      App.confirmBox('期间结账', `确认对 ${b.dataset.close} 执行结账？结账后该期间数据将锁定，需反结账才能修改。`, async () => {
        try { await App.POST(`/api/periods/${b.dataset.close}/close`, {}); App.ok('已结账'); App.route(); }
        catch (e) { App.err(e.message); }
      }, '结账'));
    view.querySelectorAll('[data-reopen]').forEach(b => b.onclick = () =>
      App.confirmBox('反结账', `确认将 ${b.dataset.reopen} 反结账？操作会记入审计日志。`, async () => {
        try {
          await App.POST(`/api/periods/${b.dataset.reopen}/reopen`, {reason: '管理员手工反结账'});
          App.ok('已反结账'); App.route();
        } catch (e) { App.err(e.message); }
      }, '反结账'));
    if (canClose) view.querySelector('#add').onclick = () => App.modal('新建会计期间', `
      <div class="form"><div class="f"><label>期间（YYYY-MM）</label><input id="p" placeholder="2026-11"></div></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">创建</button>`, {after: (m) => {
        m.querySelector('#sv').onclick = async () => {
          try { await App.POST('/api/periods', {period: m.querySelector('#p').value.trim()});
            App.ok('已创建'); App.closeModal(); App.route(); } catch (e) { App.err(e.message); }
        };
      }});
  }
});
