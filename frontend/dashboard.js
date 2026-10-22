/* 成本驾驶舱 */
App.page({
  id: 'dashboard', t: '成本驾驶舱',
  render: async (view, st) => {
    const d = await App.GET('/api/board?period=' + st.period);
    const k = d.kpi;
    const varCls = k.variance > 0 ? 'bad' : 'ok';
    const card = (cls, lb, vl, ft) => `<div class="kpi ${cls}"><div class="lb">${lb}</div>
      <div class="vl">${vl}</div><div class="ft">${ft}</div></div>`;

    view.innerHTML = `
      <div class="grid g4" style="margin-bottom:14px">
        ${card('', '本期直接归集成本', '¥' + App.wan(k.directCost),
               `已批准费用单 ${k.pendingExpenses ? '· ' + k.pendingExpenses + ' 张待审批' : '· 无待审批'}`)}
        ${card(k.allocCheck === 0 ? 'ok' : 'warn', '分摊执行', k.allocated > 0 ? '¥' + App.wan(k.allocated) : '未执行',
               k.allocated > 0 ? `守恒校核差 ${App.money(k.allocCheck)} 元` : '本期尚未运行阶梯分摊')}
        ${card(varCls, '标准 vs 实际', '¥' + App.wan(k.actTotal),
               `标准 ${App.wan(k.stdTotal)} · 差异 ${App.sign(k.variance)}${App.wan(k.variance)}`)}
        ${card(k.varianceRate > 0.05 ? 'warn' : 'ok', '成本差异率', App.pct(k.varianceRate),
               `差异额占标准成本比重（红线 10%）`)}
      </div>
      <div class="grid g4" style="margin-bottom:14px">
        ${card('', '成本中心 / 在产产品', `${k.centers} / ${k.products}`, '启用中心与在产产品数')}
        ${card('', '预算执行率', App.pct(k.budget.rate), `预算 ${App.wan(k.budget.amount)} · 已用 ${App.wan(k.budget.used)}`)}
        ${card(k.openOrders ? 'warn' : 'ok', '未完工工单', k.openOrders + ' 张', '草稿 + 在生产状态')}
        ${card(k.periodStatus === '打开' ? 'ok' : 'warn', '期间状态', k.periodStatus, `会计期间 ${k.period}`)}
      </div>

      <div class="grid g23" style="margin-bottom:14px">
        <div class="card">
          <div class="hd"><h3>近 6 期成本趋势</h3><span class="hint">标准成本 vs 实际成本 vs 直接归集</span></div>
          <div class="bd">${App.lineChart([
            {name: '标准成本', data: d.trend.map(x => x.standard), color: '#1f6feb'},
            {name: '实际成本', data: d.trend.map(x => x.actual), color: '#f2994a'},
            {name: '直接归集', data: d.trend.map(x => x.direct), color: '#0a8f4d'}
          ], d.trend.map(x => x.period.slice(5) + '月'))}</div>
        </div>
        <div class="card">
          <div class="hd"><h3>成本结构</h3><span class="hint">按科目类别</span></div>
          <div class="bd">${d.category.length ? App.bars(d.category, {key: 'name', val: 'amount'}) :
            '<div class="empty">本期无已批准费用</div>'}</div>
        </div>
      </div>

      <div class="grid g2">
        <div class="card">
          <div class="hd"><h3>成本中心归集 TOP8</h3></div>
          <div class="bd">${d.centerTop.length ? App.bars(d.centerTop, {key: 'name', val: 'amount'}) :
            '<div class="empty">暂无数据</div>'}</div>
        </div>
        <div class="card">
          <div class="hd"><h3>差异 TOP5</h3><button class="btn sm" onclick="location.hash='#variance'">差异分析 →</button></div>
          <div class="bd nopad">${App.table([
            {k: 'product', t: '产品'},
            {k: 'variance', t: '差异额', cls: 'num', fmt: r => `<span class="${r.variance > 0 ? 'pos' : 'neg'}">${App.sign(r.variance)}${App.money(r.variance)}</span>`},
            {k: 'actTotal', t: '实际成本', cls: 'num', fmt: r => App.money(r.actTotal)}
          ], d.topVariance, {empty: '本期尚未计算差异'})}</div>
        </div>
      </div>

      <div class="card" style="margin-top:14px">
        <div class="hd"><h3>关账前自检</h3><span class="hint">三项闸口全部通过才能结账</span></div>
        <div class="bd">
          <div class="check"><span class="dot">${k.pendingExpenses ? '⛔' : '✅'}</span>
            待审批费用单：<b>${k.pendingExpenses}</b> 张 ${k.pendingExpenses ? '（需全部批准或驳回）' : ''}</div>
          <div class="check"><span class="dot">${k.openOrders ? '⛔' : '✅'}</span>
            未完工工单：<b>${k.openOrders}</b> 张 ${k.openOrders ? '（需完工或关闭）' : ''}</div>
          <div class="check"><span class="dot">${k.allocated > 0 ? '✅' : '⛔'}</span>
            本期分摊：<b>${k.allocated > 0 ? '已执行' : '未执行'}</b></div>
        </div>
      </div>`;
  }
});
