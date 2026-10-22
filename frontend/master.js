/* 主数据：成本中心 / 成本科目 / 产品与 BOM */

// ---------------------------------------------------------------- 成本中心
App.page({
  id: 'center', t: '成本中心',
  render: async (view, st) => {
    const d = await App.GET('/api/cost-centers?period=' + st.period);
    const canWrite = st.user.perms.includes('center.write');
    view.innerHTML = `
      <div class="notice">阶梯分摊按「分摊顺序」升序执行：辅助中心（顺序 1-3）先摊给生产中心（顺序 5），
        管理/销售/研发中心不参与产品成本分摊。直接归集 = 本期已批准费用单金额。</div>
      <div class="card">
        <div class="hd"><h3>成本中心（${d.list.length}）</h3>
          <span class="hint">期间 ${d.period}</span>
          ${canWrite ? '<button class="btn pri" id="add">+ 新建成本中心</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'code', t: '编码'},
          {k: 'name', t: '名称'},
          {k: 'ctype', t: '类型', cls: 'ctr', fmt: r => App.tag(r.ctype, {'生产': 'blue', '辅助': 'orange', '管理': 'gray', '销售': 'gray', '研发': 'gray'})},
          {k: 'leader', t: '负责人', cls: 'ctr'},
          {k: 'laborRate', t: '人工费率', cls: 'num', fmt: r => App.num(r.laborRate)},
          {k: 'ohRate', t: '制费率', cls: 'num', fmt: r => App.num(r.ohRate)},
          {k: 'allocOrder', t: '分摊顺序', cls: 'ctr'},
          {k: 'driver', t: '动因', cls: 'ctr'},
          {k: 'directCost', t: '直接归集', cls: 'num', fmt: r => App.money(r.directCost)},
          {k: 'allocIn', t: '分入', cls: 'num', fmt: r => App.money(r.allocIn)},
          {k: 'allocOut', t: '分出', cls: 'num', fmt: r => App.money(r.allocOut)},
          {k: 'netCost', t: '净成本', cls: 'num', fmt: r => `<b>${App.money(r.netCost)}</b>`},
          {k: 'orderCount', t: '工单', cls: 'ctr'},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r => canWrite ?
            `<button class="btn gho sm" data-edit="${r.code}">编辑</button>` : ''}
        ], d.list)}</div>
      </div>`;

    const form = (x) => `
      <div class="form">
        <div class="f"><label>编码</label><input id="code" value="${App.esc(x.code || '')}" ${x.code ? 'readonly' : ''} placeholder="CC101"></div>
        <div class="f"><label>名称</label><input id="name" value="${App.esc(x.name || '')}" placeholder="注塑车间"></div>
        <div class="f"><label>类型</label><select id="ctype">${['生产', '辅助', '管理', '销售', '研发'].map(t => `<option ${x.ctype === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="f"><label>负责人</label><input id="leader" value="${App.esc(x.leader || '')}"></div>
        <div class="f"><label>人工费率（元/工时）</label><input id="laborRate" type="number" step="0.01" value="${x.laborRate || 0}"></div>
        <div class="f"><label>制造费率（元/工时）</label><input id="ohRate" type="number" step="0.01" value="${x.ohRate || 0}"></div>
        <div class="f"><label>分摊顺序</label><input id="allocOrder" type="number" value="${x.allocOrder === undefined ? 9 : x.allocOrder}">
          <div class="tip">数字越小越先分摊；只能分给数字更大的中心</div></div>
        <div class="f"><label>分摊动因</label><select id="driver">${['人工工时', '机器工时', '面积', '人数', '直接成本', '用量'].map(t => `<option ${x.driver === t ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
        <div class="f"><label>动因量</label><input id="driverQty" type="number" step="0.01" value="${x.driverQty || 0}"></div>
        <div class="f"><label>状态</label><select id="status"><option ${x.status !== '停用' ? 'selected' : ''}>启用</option><option ${x.status === '停用' ? 'selected' : ''}>停用</option></select></div>
        <div class="f full"><label>备注</label><textarea id="remark">${App.esc(x.remark || '')}</textarea></div>
      </div>`;

    const open = (x) => {
      App.modal((x.code ? '编辑成本中心 · ' : '新建成本中心'), form(x),
        `<button class="btn" data-x>取消</button><button class="btn pri" id="save">保存</button>`,
        {after: (m) => {
          m.querySelector('#save').onclick = async () => {
            const body = {
              code: m.querySelector('#code').value.trim().toUpperCase(),
              name: m.querySelector('#name').value.trim(),
              ctype: m.querySelector('#ctype').value, leader: m.querySelector('#leader').value,
              laborRate: Number(m.querySelector('#laborRate').value),
              ohRate: Number(m.querySelector('#ohRate').value),
              allocOrder: Number(m.querySelector('#allocOrder').value),
              driver: m.querySelector('#driver').value,
              driverQty: Number(m.querySelector('#driverQty').value),
              status: m.querySelector('#status').value, remark: m.querySelector('#remark').value
            };
            try {
              if (x.code) await App.PUT('/api/cost-centers/' + x.code, body);
              else await App.POST('/api/cost-centers', body);
              App.ok('已保存'); App.closeModal(); App.route();
            } catch (e) { App.err(e.message); }
          };
        }});
    };
    if (canWrite) {
      view.querySelector('#add').onclick = () => open({});
      view.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
        open(d.list.find(x => x.code === b.dataset.edit)));
    }
  }
});

// ---------------------------------------------------------------- 成本科目
App.page({
  id: 'subject', t: '成本科目',
  render: async (view, st) => {
    const d = await App.GET('/api/subjects');
    const canWrite = st.user.perms.includes('subject.write');
    view.innerHTML = `
      <div class="card">
        <div class="hd"><h3>成本科目（${d.list.length}）</h3>
          <span class="hint">直接计入产品成本 or 先归集再分摊</span>
          ${canWrite ? '<button class="btn pri" id="add">+ 新建科目</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'code', t: '科目编码'},
          {k: 'name', t: '科目名称'},
          {k: 'category', t: '类别', cls: 'ctr', fmt: r => App.tag(r.category, {'材料': 'blue', '人工': 'green', '制造费用': 'orange', '期间费用': 'gray'})},
          {k: 'gather', t: '归集方式', cls: 'ctr'},
          {k: 'enabled', t: '状态', cls: 'ctr', fmt: r => r.enabled ? App.tag('启用', App.ST) : App.tag('停用', App.ST)},
          {k: 'remark', t: '备注'},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r => canWrite ?
            `<button class="btn gho sm" data-edit="${r.code}">编辑</button>` : ''}
        ], d.list)}</div>
      </div>`;
    const open = (x) => {
      App.modal(x.code ? '编辑科目 · ' + x.code : '新建科目', `
        <div class="form">
          <div class="f"><label>科目编码</label><input id="code" value="${App.esc(x.code || '')}" ${x.code ? 'readonly' : ''} placeholder="S3001"></div>
          <div class="f"><label>科目名称</label><input id="name" value="${App.esc(x.name || '')}"></div>
          <div class="f"><label>类别</label><select id="category">${['材料', '人工', '制造费用', '期间费用'].map(c => `<option ${x.category === c ? 'selected' : ''}>${c}</option>`).join('')}</select></div>
          <div class="f"><label>归集方式</label><select id="gather"><option ${x.gather !== '间接' ? 'selected' : ''}>直接</option><option ${x.gather === '间接' ? 'selected' : ''}>间接</option></select></div>
          <div class="f full"><label>备注</label><input id="remark" value="${App.esc(x.remark || '')}"></div>
        </div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" id="save">保存</button>`,
        {after: (m) => {
          m.querySelector('#save').onclick = async () => {
            const body = {code: m.querySelector('#code').value.trim().toUpperCase(),
              name: m.querySelector('#name').value.trim(), category: m.querySelector('#category').value,
              gather: m.querySelector('#gather').value, remark: m.querySelector('#remark').value};
            try {
              if (x.code) await App.PUT('/api/subjects/' + x.code, body);
              else await App.POST('/api/subjects', body);
              App.ok('已保存'); App.closeModal(); App.route();
            } catch (e) { App.err(e.message); }
          };
        }});
    };
    if (canWrite) {
      view.querySelector('#add').onclick = () => open({});
      view.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
        open(d.list.find(x => x.code === b.dataset.edit)));
    }
  }
});

// ---------------------------------------------------------------- 产品与 BOM
App.page({
  id: 'product', t: '产品与 BOM',
  render: async (view, st) => {
    const [d, cd] = await Promise.all([
      App.GET('/api/products?period=' + st.period), App.GET('/api/cost-centers?period=' + st.period)]);
    const canWrite = st.user.perms.includes('product.write');
    view.innerHTML = `
      <div class="card">
        <div class="hd"><h3>产品清单（${d.list.length}）</h3>
          <span class="hint">标准单位成本 = 材料（BOM 含损耗）+ 人工 + 制造费用</span>
          ${canWrite ? '<button class="btn pri" id="add">+ 新建产品</button>' : ''}</div>
        <div class="bd nopad scroll">${App.table([
          {k: 'code', t: '产品编码'},
          {k: 'name', t: '名称'},
          {k: 'spec', t: '规格'},
          {k: 'unit', t: '单位', cls: 'ctr'},
          {k: 'stdHours', t: '标准工时', cls: 'num'},
          {k: 'centerName', t: '核算中心'},
          {k: 'bomCount', t: 'BOM', cls: 'ctr'},
          {k: 'stdMat', t: '材料', cls: 'num', fmt: r => App.money(r.stdMat)},
          {k: 'stdLabor', t: '人工', cls: 'num', fmt: r => App.money(r.stdLabor)},
          {k: 'stdOh', t: '制费', cls: 'num', fmt: r => App.money(r.stdOh)},
          {k: 'stdUnitCost', t: '单位标准成本', cls: 'num', fmt: r => `<b>${App.money(r.stdUnitCost)}</b>`},
          {k: 'listPrice', t: '售价', cls: 'num', fmt: r => App.money(r.listPrice)},
          {k: '_op', t: '操作', cls: 'ctr', fmt: r =>
            `<button class="btn gho sm" data-detail="${r.code}">BOM / 成本卡</button>` +
            (canWrite ? `<button class="btn gho sm" data-edit="${r.code}">编辑</button>` : '')}
        ], d.list)}</div>
      </div>`;

    const openEdit = (x) => {
      App.modal(x.code ? '编辑产品 · ' + x.code : '新建产品', `
        <div class="form">
          <div class="f"><label>产品编码</label><input id="code" value="${App.esc(x.code || '')}" ${x.code ? 'readonly' : ''}></div>
          <div class="f"><label>产品名称</label><input id="name" value="${App.esc(x.name || '')}"></div>
          <div class="f"><label>规格</label><input id="spec" value="${App.esc(x.spec || '')}"></div>
          <div class="f"><label>单位</label><input id="unit" value="${App.esc(x.unit || '件')}"></div>
          <div class="f"><label>标准工时（小时/件）</label><input id="stdHours" type="number" step="0.01" value="${x.stdHours || 0}"></div>
          <div class="f"><label>核算成本中心</label><select id="center">${cd.list.map(c => `<option value="${c.code}" ${x.center === c.code ? 'selected' : ''}>${c.code} ${c.name}</option>`).join('')}</select></div>
          <div class="f"><label>售价（元）</label><input id="listPrice" type="number" step="0.01" value="${x.listPrice || 0}"></div>
          <div class="f"><label>状态</label><select id="status"><option ${x.status !== '停产' ? 'selected' : ''}>在产</option><option ${x.status === '停产' ? 'selected' : ''}>停产</option></select></div>
        </div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" id="save">保存</button>`,
        {after: (m) => {
          m.querySelector('#save').onclick = async () => {
            const body = {code: m.querySelector('#code').value.trim().toUpperCase(),
              name: m.querySelector('#name').value.trim(), spec: m.querySelector('#spec').value,
              unit: m.querySelector('#unit').value, stdHours: Number(m.querySelector('#stdHours').value),
              center: m.querySelector('#center').value, listPrice: Number(m.querySelector('#listPrice').value),
              status: m.querySelector('#status').value};
            try {
              if (x.code) await App.PUT('/api/products/' + x.code, body);
              else await App.POST('/api/products', body);
              App.ok('已保存'); App.closeModal(); App.route();
            } catch (e) { App.err(e.message); }
          };
        }});
    };

    const openDetail = async (code) => {
      const det = await App.GET('/api/products/' + code + '?period=' + st.period);
      const p = det.product;
      const bomHtml = App.table([
        {k: 'materialCode', t: '物料编码'},
        {k: 'materialName', t: '物料名称'},
        {k: 'qtyPer', t: '单位用量', cls: 'num', fmt: r => App.num(r.qtyPer, 4)},
        {k: 'lossRate', t: '损耗率', cls: 'num', fmt: r => App.pct(r.lossRate)},
        {k: 'stdPrice', t: '标准单价', cls: 'num', fmt: r => App.num(r.stdPrice, 4)},
        {k: 'amount', t: '金额', cls: 'num', fmt: r => App.money(r.amount)},
        {k: '_op', t: '', cls: 'ctr', fmt: r => canWrite ?
          `<button class="btn gho sm" data-del="${r.id}">删除</button>` : ''}
      ], det.bom, {empty: '尚未维护 BOM'});
      const hist = App.table([
        {k: 'period', t: '期间'}, {k: 'version', t: '版本', cls: 'ctr'},
        {k: 'matCost', t: '材料', cls: 'num', fmt: r => App.money(r.matCost)},
        {k: 'laborCost', t: '人工', cls: 'num', fmt: r => App.money(r.laborCost)},
        {k: 'ohCost', t: '制费', cls: 'num', fmt: r => App.money(r.ohCost)},
        {k: 'unitCost', t: '单位成本', cls: 'num', fmt: r => `<b>${App.money(r.unitCost)}</b>`},
        {k: 'status', t: '状态', cls: 'ctr', fmt: r => App.tag(r.status, App.ST)}
      ], det.stdHistory, {empty: '该期间尚未计算标准成本'});
      App.modal(`${p.code} ${p.name} · BOM 与标准成本卡`, `
        <div class="grid g4" style="margin-bottom:14px">
          <div class="kpi"><div class="lb">材料</div><div class="vl" style="font-size:17px">${App.money(p.stdMat)}</div></div>
          <div class="kpi"><div class="lb">人工</div><div class="vl" style="font-size:17px">${App.money(p.stdLabor)}</div></div>
          <div class="kpi"><div class="lb">制造费用</div><div class="vl" style="font-size:17px">${App.money(p.stdOh)}</div></div>
          <div class="kpi ok"><div class="lb">单位标准成本</div><div class="vl" style="font-size:17px">${App.money(p.stdUnitCost)}</div></div>
        </div>
        <div class="card" style="margin-bottom:14px"><div class="hd"><h3>BOM 明细</h3>
          ${canWrite ? '<button class="btn sm" id="addbom">+ 加物料</button>' : ''}</div>
          <div class="bd nopad">${bomHtml}</div></div>
        <div class="card"><div class="hd"><h3>标准成本版本历史</h3></div>
          <div class="bd nopad">${hist}</div></div>`,
        `<button class="btn pri" data-x>关闭</button>`, {wide: true, after: (m) => {
          m.querySelectorAll('[data-del]').forEach(b => b.onclick = () =>
            App.confirmBox('删除 BOM 行', '删除后需重新计算标准成本才生效，确认删除？', async () => {
              try { await App.DEL(`/api/products/${code}/bom/${b.dataset.del}`);
                App.ok('已删除'); App.closeModal(); openDetail(code); } catch (e) { App.err(e.message); }
            }, '删除'));
          const ab = m.querySelector('#addbom');
          if (ab) ab.onclick = () => {
            App.modal('新增 BOM 物料', `<div class="form">
              <div class="f"><label>物料编码</label><input id="mc" placeholder="M1001"></div>
              <div class="f"><label>物料名称</label><input id="mn"></div>
              <div class="f"><label>单位用量</label><input id="qp" type="number" step="0.0001" value="1"></div>
              <div class="f"><label>损耗率</label><input id="lr" type="number" step="0.001" value="0.02">
                <div class="tip">0.02 = 2%，上限 20%</div></div>
              <div class="f"><label>标准单价</label><input id="sp" type="number" step="0.0001" value="0"></div>
              <div class="f"><label>单位</label><input id="ut" value="kg"></div></div>`,
              `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`,
              {after: (mm) => {
                mm.querySelector('#sv').onclick = async () => {
                  try {
                    await App.POST(`/api/products/${code}/bom`, {
                      materialCode: mm.querySelector('#mc').value.trim().toUpperCase(),
                      materialName: mm.querySelector('#mn').value,
                      qtyPer: Number(mm.querySelector('#qp').value),
                      lossRate: Number(mm.querySelector('#lr').value),
                      stdPrice: Number(mm.querySelector('#sp').value),
                      unit: mm.querySelector('#ut').value});
                    App.ok('已添加（记得重算标准成本）'); App.closeModal(); openDetail(code);
                  } catch (e) { App.err(e.message); }
                };
              }});
          };
        }});
    };

    if (canWrite) view.querySelector('#add').onclick = () => openEdit({});
    view.querySelectorAll('[data-detail]').forEach(b => b.onclick = () => openDetail(b.dataset.detail));
    view.querySelectorAll('[data-edit]').forEach(b => b.onclick = () =>
      openEdit(d.list.find(x => x.code === b.dataset.edit)));
  }
});
