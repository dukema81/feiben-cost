/* 成本核算：标准成本 / 生产工单 / 费用归集 */

// ---------------------------------------------------------------- 标准成本
App.page({
  id: 'std', t: '标准成本',
  render: async (view, st) => {
    const d = await App.GET('/api/std-costs?period=' + st.period);
    const canWrite = st.user.perms.includes('std.write');
    view.innerHTML = `
      <div class="notice">标准成本按期计算并版本化：每次计算生成新版本，旧版本转「历史」。
        材料成本 = Σ 单位用量 ×(1+损耗率)× 标准单价；人工 / 制造费用 = 标准工时 × 中心费率。</div>
      <div class="card">
        <div class="hd"><h3>标准成本卡（${d.list.length}）</h3>
          <span class="hint">期间 ${d.period}</span>
          ${canWrite ? '<button class="btn pri" id="calc">按期重算标准成本</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'product', t: '产品编码'},
          {k: 'productName', t: '产品名称'},
          {k: 'unit', t: '单位', cls: 'ctr'},
          {k: 'version', t: '版本', cls: 'ctr', fmt: r => 'v' + r.version},
          {k: 'matCost', t: '材料', cls: 'num', fmt: r => App.money(r.matCost)},
          {k: 'laborCost', t: '人工', cls: 'num', fmt: r => App.money(r.laborCost)},
          {k: 'ohCost', t: '制造费用', cls: 'num', fmt: r => App.money(r.ohCost)},
          {k: 'unitCost', t: '单位标准成本', cls: 'num', fmt: r => `<b>${App.money(r.unitCost)}</b>`},
          {k: 'status', t: '状态', cls: 'ctr', fmt: r => App.tag(r.status, App.ST)},
          {k: 'calcAt', t: '计算时间'}
        ], d.list)}</div>
      </div>`;
    if (canWrite) view.querySelector('#calc').onclick = () =>
      App.confirmBox('重算标准成本', `将按当前 BOM 与中心费率重算 ${st.period} 的全部在产产品，生成新版本。确认执行？`,
        async () => {
          try {
            const r = await App.POST('/api/std-costs/calc', {period: st.period});
            App.ok(`已计算 ${r.count} 个产品` + (r.warnings.length ? `，${r.warnings.length} 条提示` : ''));
            if (r.warnings.length) App.modal('计算提示', r.warnings.map(w => `<div class="check">⚠ ${App.esc(w)}</div>`).join(''));
            App.route();
          } catch (e) { App.err(e.message); }
        });
  }
});

// ---------------------------------------------------------------- 生产工单
App.page({
  id: 'wo', t: '生产工单',
  render: async (view, st) => {
    const qs = new URLSearchParams({period: st.period, ...(st.woFilter || {})});
    const [d, cd] = await Promise.all([App.GET('/api/work-orders?' + qs), App.GET('/api/cost-centers?period=' + st.period)]);
    const canWrite = st.user.perms.includes('wo.write');
    view.innerHTML = `
      <div class="card">
        <div class="hd"><h3>工单（${d.list.length}）</h3>
          <div class="bar">
            <select id="fs" style="height:30px;border:1px solid var(--line);border-radius:7px;padding:0 8px">
              <option value="">全部状态</option>${d.states.map(s => `<option ${(st.woFilter || {}).status === s ? 'selected' : ''}>${s}</option>`).join('')}
            </select>
            ${canWrite ? '<button class="btn pri" id="add">+ 新建工单</button>' : ''}
          </div></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'no', t: '工单号'},
          {k: 'product', t: '产品', fmt: r => `${r.product}<div class="dim" style="font-size:11.5px">${App.esc(r.productName)}</div>`},
          {k: 'centerName', t: '成本中心'},
          {k: 'qtyPlan', t: '计划', cls: 'num', fmt: r => App.num(r.qtyPlan, 0)},
          {k: 'qtyDone', t: '完工', cls: 'num', fmt: r => App.num(r.qtyDone, 0)},
          {k: 'wipQty', t: '在制', cls: 'num', fmt: r => App.num(r.wipQty, 0)},
          {k: 'mat', t: '材料', cls: 'num', fmt: r => App.money(r.mat)},
          {k: 'labor', t: '人工', cls: 'num', fmt: r => App.money(r.labor)},
          {k: 'oh', t: '制费', cls: 'num', fmt: r => App.money(r.oh)},
          {k: 'total', t: '实际合计', cls: 'num', fmt: r => `<b>${App.money(r.total)}</b>`},
          {k: 'unitCost', t: '单位成本', cls: 'num', fmt: r => App.num(r.unitCost, 4)},
          {k: 'status', t: '状态', cls: 'ctr', fmt: r => App.tag(r.status, App.ST)},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r => `<button class="btn gho sm" data-detail="${r.no}">明细</button>`}
        ], d.list)}</div>
      </div>`;

    view.querySelector('#fs').onchange = (e) => {
      st.woFilter = {status: e.target.value};
      App.route();
    };

    const openDetail = async (no) => {
      const det = await App.GET('/api/work-orders/' + no);
      const o = det.order;
      const editable = canWrite && !['已完工', '已关闭'].includes(o.status);
      const matHtml = App.table([
        {k: 'materialCode', t: '物料'},
        {k: 'materialName', t: '名称'},
        {k: 'qty', t: '数量', cls: 'num', fmt: r => App.num(r.qty, 3)},
        {k: 'price', t: '单价', cls: 'num', fmt: r => App.num(r.price, 4)},
        {k: 'amount', t: '金额', cls: 'num', fmt: r => App.money(r.amount)}
      ], det.materials, {empty: '暂无领料'});
      const labHtml = App.table([
        {k: 'workType', t: '工时类型'},
        {k: 'hours', t: '工时', cls: 'num', fmt: r => App.num(r.hours, 2)},
        {k: 'rate', t: '工资率', cls: 'num', fmt: r => App.num(r.rate, 2)},
        {k: 'amount', t: '金额', cls: 'num', fmt: r => App.money(r.amount)},
        {k: 'worker', t: '班组'}
      ], det.labors, {empty: '暂无报工'});
      App.modal(`工单 ${o.no} · ${o.product} ${o.productName}`, `
        <div class="grid g4" style="margin-bottom:14px">
          <div class="kpi"><div class="lb">计划 / 完工</div><div class="vl" style="font-size:17px">${App.num(o.qtyPlan, 0)} / ${App.num(o.qtyDone, 0)}</div>
            <div class="ft">状态 ${App.esc(o.status)}</div></div>
          <div class="kpi"><div class="lb">实际成本合计</div><div class="vl" style="font-size:17px">${App.money(o.total)}</div>
            <div class="ft">材料 ${App.money(o.mat)} · 人工 ${App.money(o.labor)} · 制费 ${App.money(o.oh)}</div></div>
          <div class="kpi"><div class="lb">约当产量</div><div class="vl" style="font-size:17px">${App.num(o.equivQty, 2)}</div>
            <div class="ft">在制 ${App.num(o.wipQty, 0)} × 进度 ${App.pct(o.wipRate)}</div></div>
          <div class="kpi ok"><div class="lb">单位成本 / 完工转出</div><div class="vl" style="font-size:17px">${App.num(o.unitCost, 2)}</div>
            <div class="ft">完工 ${App.money(o.finishedCost)} · 在制 ${App.money(o.wipCost)}</div></div>
        </div>
        <div class="notice">标准单位成本 ${App.money(det.stdUnitCost)}，
          本工单差异 ${App.sign(o.total - det.stdUnitCost * o.qtyDone)}${App.money(o.total - det.stdUnitCost * o.qtyDone)}
          （${App.pct(det.stdUnitCost * o.qtyDone ? (o.total - det.stdUnitCost * o.qtyDone) / (det.stdUnitCost * o.qtyDone) : 0)}）</div>
        <div class="card" style="margin-bottom:12px"><div class="hd"><h3>领料明细</h3>
          ${editable ? '<button class="btn sm" id="addmat">+ 领料</button>' : ''}</div>
          <div class="bd nopad">${matHtml}</div></div>
        <div class="card"><div class="hd"><h3>工时报工</h3>
          ${editable ? '<button class="btn sm" id="addlab">+ 报工</button>' : ''}</div>
          <div class="bd nopad">${labHtml}</div></div>`,
        `${editable ? '<button class="btn" id="calc">核算实际成本</button>' : ''}
         ${canWrite && o.status === '在生产' ? '<button class="btn pri" id="done">完工</button>' : ''}
         <button class="btn" data-x>关闭</button>`, {wide: true, after: (m) => {
          const reload = () => { App.closeModal(); App.route(); setTimeout(() => openDetail(no), 60); };
          const mc = m.querySelector('#calc');
          if (mc) mc.onclick = async () => {
            try {
              const r = await App.POST(`/api/work-orders/${no}/calc`, {});
              App.ok(`已核算：合计 ${App.money(r.actual.totalActual)}，单位 ${App.num(r.split.unitCost, 2)}`);
              reload();
            } catch (e) { App.err(e.message); }
          };
          const dn = m.querySelector('#done');
          if (dn) dn.onclick = async () => {
            try {
              await App.POST(`/api/work-orders/${no}/stage`, {target: '已完工'});
              App.ok('工单已完工'); reload();
            } catch (e) { App.err(e.message); }
          };
          const am = m.querySelector('#addmat');
          if (am) am.onclick = () => App.modal('工单领料', `<div class="form">
              <div class="f"><label>物料编码</label><input id="mc2"></div>
              <div class="f"><label>物料名称</label><input id="mn2"></div>
              <div class="f"><label>数量</label><input id="q2" type="number" step="0.001"></div>
              <div class="f"><label>单价</label><input id="p2" type="number" step="0.0001"></div></div>`,
            `<button class="btn" data-x>取消</button><button class="btn pri" id="s2">保存</button>`, {after: (mmm) => {
              mmm.querySelector('#s2').onclick = async () => {
                try {
                  await App.POST(`/api/work-orders/${no}/materials`, {
                    materialCode: mmm.querySelector('#mc2').value.trim().toUpperCase(),
                    materialName: mmm.querySelector('#mn2').value,
                    qty: Number(mmm.querySelector('#q2').value),
                    price: Number(mmm.querySelector('#p2').value)});
                  App.ok('已领料'); reload();
                } catch (e) { App.err(e.message); }
              };
            }});
          const al = m.querySelector('#addlab');
          if (al) al.onclick = () => App.modal('工时报工', `<div class="form">
              <div class="f"><label>工时类型</label><select id="wt"><option>直接工时</option><option>间接工时</option></select></div>
              <div class="f"><label>工时（小时）</label><input id="h2" type="number" step="0.01"></div>
              <div class="f"><label>工资率（留空用中心费率）</label><input id="r2" type="number" step="0.01"></div>
              <div class="f"><label>班组</label><input id="w2" value="班组A"></div></div>`,
            `<button class="btn" data-x>取消</button><button class="btn pri" id="s3">保存</button>`, {after: (mmm) => {
              mmm.querySelector('#s3').onclick = async () => {
                try {
                  await App.POST(`/api/work-orders/${no}/labor`, {
                    workType: mmm.querySelector('#wt').value,
                    hours: Number(mmm.querySelector('#h2').value),
                    rate: Number(mmm.querySelector('#r2').value) || 0,
                    worker: mmm.querySelector('#w2').value});
                  App.ok('已报工'); reload();
                } catch (e) { App.err(e.message); }
              };
            }});
        }});
    };
    view.querySelectorAll('[data-detail]').forEach(b => b.onclick = () => openDetail(b.dataset.detail));

    if (canWrite) view.querySelector('#add').onclick = () => {
      App.GET('/api/products?period=' + st.period).then(pd => {
        App.modal('新建生产工单', `<div class="form">
          <div class="f"><label>产品</label><select id="prod">${pd.list.map(p => `<option value="${p.code}">${p.code} ${p.name}</option>`).join('')}</select></div>
          <div class="f"><label>成本中心</label><select id="ctr">${cd.list.filter(c => c.ctype === '生产').map(c => `<option value="${c.code}">${c.code} ${c.name}</option>`).join('')}</select></div>
          <div class="f"><label>计划数量</label><input id="qp" type="number" step="1"></div>
          <div class="f"><label>完工数量</label><input id="qd" type="number" step="1" value="0"></div>
          <div class="f"><label>在制完工进度</label><input id="wr" type="number" step="0.05" value="1"></div>
          <div class="f"><label>开工日期</label><input id="sd" type="date"></div>
          <div class="f full"><label>备注</label><input id="rm"></div></div>`,
          `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">创建</button>`, {after: (m) => {
            m.querySelector('#sv').onclick = async () => {
              try {
                const r = await App.POST('/api/work-orders', {
                  product: m.querySelector('#prod').value, center: m.querySelector('#ctr').value,
                  qtyPlan: Number(m.querySelector('#qp').value), qtyDone: Number(m.querySelector('#qd').value),
                  wipRate: Number(m.querySelector('#wr').value),
                  startDate: m.querySelector('#sd').value, period: st.period,
                  remark: m.querySelector('#rm').value});
                App.ok('已创建 ' + r.no); App.closeModal(); App.route();
              } catch (e) { App.err(e.message); }
            };
          }});
      });
    };
  }
});

// ---------------------------------------------------------------- 费用归集
App.page({
  id: 'exp', t: '费用归集',
  render: async (view, st) => {
    const [d, cd, sd, sum] = await Promise.all([
      App.GET('/api/expenses?period=' + st.period + (st.expStatus ? '&status=' + encodeURIComponent(st.expStatus) : '')),
      App.GET('/api/cost-centers?period=' + st.period), App.GET('/api/subjects'),
      App.GET('/api/expenses/summary?period=' + st.period)]);
    const canWrite = st.user.perms.includes('exp.write');
    const canApprove = st.user.perms.includes('exp.approve');
    view.innerHTML = `
      <div class="grid g4" style="margin-bottom:14px">
        <div class="kpi"><div class="lb">已批准归集额</div><div class="vl">¥${App.wan(d.approvedTotal)}</div>
          <div class="ft">${d.list.filter(x => x.status === '已批准').length} 张单</div></div>
        ${sum.byCategory.map(c => `<div class="kpi"><div class="lb">${App.esc(c.name)}</div>
          <div class="vl" style="font-size:19px">¥${App.wan(c.amount)}</div>
          <div class="ft">占总额 ${App.pct(sum.total ? c.amount / sum.total : 0)}</div></div>`).join('')}
      </div>
      <div class="card">
        <div class="hd"><h3>费用归集单（${d.list.length}）</h3>
          <div class="bar">
            <select id="fs" style="height:30px;border:1px solid var(--line);border-radius:7px;padding:0 8px">
              <option value="">全部状态</option>${d.states.map(s => `<option ${st.expStatus === s ? 'selected' : ''}>${s}</option>`).join('')}
            </select>
            ${canWrite ? '<button class="btn pri" id="add">+ 新建费用单</button>' : ''}
          </div></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'no', t: '单号'},
          {k: 'centerName', t: '成本中心'},
          {k: 'subjectName', t: '科目'},
          {k: 'category', t: '类别', cls: 'ctr'},
          {k: 'amount', t: '金额', cls: 'num', fmt: r => App.money(r.amount)},
          {k: 'source', t: '来源', cls: 'ctr'},
          {k: 'summary', t: '摘要'},
          {k: 'status', t: '状态', cls: 'ctr', fmt: r => App.tag(r.status, App.ST)},
          {k: 'applicant', t: '申请人', cls: 'ctr'},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r => {
            const b = [];
            if (canWrite && ['草稿', '已驳回'].includes(r.status)) b.push(`<button class="btn gho sm" data-sub="${r.no}">提交</button>`);
            if (canApprove && r.status === '待审批') {
              b.push(`<button class="btn gho sm" data-ok="${r.no}">批准</button>`);
              b.push(`<button class="btn gho sm" data-no="${r.no}">驳回</button>`);
            }
            return b.join('') || '<span class="dim">—</span>';
          }}
        ], d.list)}</div>
      </div>`;

    view.querySelector('#fs').onchange = (e) => { st.expStatus = e.target.value; App.route(); };
    const stage = async (no, target) => {
      try { await App.POST(`/api/expenses/${no}/stage`, {target}); App.ok(target === '待审批' ? '已提交' : target); App.route(); }
      catch (e) { App.err(e.message); }
    };
    view.querySelectorAll('[data-sub]').forEach(b => b.onclick = () => stage(b.dataset.sub, '待审批'));
    view.querySelectorAll('[data-ok]').forEach(b => b.onclick = () => stage(b.dataset.ok, '已批准'));
    view.querySelectorAll('[data-no]').forEach(b => b.onclick = () => stage(b.dataset.no, '已驳回'));

    if (canWrite) view.querySelector('#add').onclick = () => {
      App.modal('新建费用归集单', `<div class="form">
        <div class="f"><label>成本中心</label><select id="ctr">${cd.list.map(c => `<option value="${c.code}">${c.code} ${c.name}</option>`).join('')}</select></div>
        <div class="f"><label>科目</label><select id="sub">${sd.list.map(s => `<option value="${s.code}">${s.code} ${s.name}（${s.category}）</option>`).join('')}</select></div>
        <div class="f"><label>金额（元）</label><input id="amt" type="number" step="0.01"></div>
        <div class="f"><label>来源</label><select id="src">${d.sources.map(s => `<option>${s}</option>`).join('')}</select></div>
        <div class="f full"><label>摘要</label><input id="sm" placeholder="如：注塑车间 10 月电费"></div>
        <div class="f"><label>提交状态</label><select id="sts"><option value="草稿">保存草稿</option><option value="待审批">直接提交审批</option></select>
          <div class="tip">提交时校验预算，超出预算 110% 会被阻断</div></div>
      </div>`, `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`,
      {after: (m) => {
        m.querySelector('#sv').onclick = async () => {
          try {
            const r = await App.POST('/api/expenses', {
              period: st.period, center: m.querySelector('#ctr').value,
              subject: m.querySelector('#sub').value, amount: Number(m.querySelector('#amt').value),
              source: m.querySelector('#src').value, summary: m.querySelector('#sm').value,
              status: m.querySelector('#sts').value});
            App.ok('已创建 ' + r.no); App.closeModal(); App.route();
          } catch (e) { App.err(e.message); }
        };
      }});
    };
  }
});
