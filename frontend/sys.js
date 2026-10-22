/* 系统设置：用户 / 业务规则 / API Key / Webhook / 审计日志 / 修改密码 */
App.page({
  id: 'sys', t: '系统设置',
  render: async (view, st) => {
    const tab = st.sysTab || 'user';
    const isAdmin = st.user.role === 'admin';
    const tabs = [['user', '用户与角色'], ['rule', '业务规则'], ['key', 'API Key'],
                  ['hook', 'Webhook'], ['log', '审计日志'], ['pwd', '修改密码']]
      .filter(([k]) => isAdmin || ['pwd', 'rule'].includes(k));
    let html = '';
    if (tab === 'user') {
      const d = await App.GET('/api/users');
      html = `<div class="card"><div class="hd"><h3>用户（${d.list.length}）</h3>
        <button class="btn pri" id="add">+ 新建用户</button></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'username', t: '账号'}, {k: 'name', t: '姓名'},
          {k: 'roleName', t: '角色', cls: 'ctr', fmt: r => App.tag(r.roleName, {'系统管理员': 'red', '成本经理': 'blue', '成本会计': 'green', '成本中心负责人': 'orange', '生产统计': 'gray', '只读用户': 'gray', '审计': 'gray'})},
          {k: 'dept', t: '部门'}, {k: 'created', t: '创建时间'}
        ], d.list)}</div></div>`;
    } else if (tab === 'rule') {
      const d = await App.GET('/api/rules');
      html = `<div class="card"><div class="hd"><h3>业务规则（${d.list.length}）</h3>
        <span class="hint">口径参数，改动即时生效</span></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'code', t: '编码'}, {k: 'name', t: '名称'},
          {k: 'category', t: '分类', cls: 'ctr'},
          {k: 'value', t: '取值', cls: 'num', fmt: r => `<b>${App.esc(r.value)}</b>`},
          {k: 'unit', t: '单位', cls: 'ctr'},
          {k: 'remark', t: '说明'},
          {k: '_op', t: '', cls: 'ctr', fmt: r => isAdmin ?
            `<button class="btn gho sm" data-rule="${r.code}">改值</button>` : ''}
        ], d.list)}</div></div>`;
    } else if (tab === 'key') {
      const d = await App.GET('/api/keys');
      html = `<div class="notice">API Key 通过请求头 <code>X-Fb-Key</code> 使用，默认只读（scope=read）；
        新 Key 只在创建时明文显示一次，服务端只存 SHA-256。</div>
        <div class="card"><div class="hd"><h3>API Key（${d.list.length}）</h3>
          <button class="btn pri" id="add">+ 创建 Key</button></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'prefix', t: '前缀'}, {k: 'name', t: '名称'},
          {k: 'scope', t: '权限', cls: 'ctr'}, {k: 'created', t: '创建时间'},
          {k: 'lastUsed', t: '最近使用'},
          {k: 'revoked', t: '状态', cls: 'ctr', fmt: r => r.revoked ? App.tag('已吊销', {'已吊销': 'red'}) : App.tag('有效', App.ST)},
          {k: '_op', t: '', cls: 'ctr', fmt: r => r.revoked ? '' :
            `<button class="btn gho sm" data-rev="${r.id}">吊销</button>`}
        ], d.list)}</div></div>`;
    } else if (tab === 'hook') {
      const [d, dv] = await Promise.all([App.GET('/api/webhooks'), App.GET('/api/webhooks/deliveries')]);
      html = `<div class="notice">事件推送：HMAC-SHA256 签名（头 <code>X-Fb-Signature</code>，内容为
        <code>timestamp.payload</code>），失败按 30/60/120 秒退避重试 3 次。</div>
        <div class="card" style="margin-bottom:14px"><div class="hd"><h3>Webhook（${d.list.length}）</h3>
          <button class="btn" id="test">发送 test.ping</button>
          <button class="btn pri" id="add">+ 新增</button></div>
          <div class="bd nopad">${App.table([
            {k: 'name', t: '名称'}, {k: 'url', t: 'URL'},
            {k: 'events', t: '订阅事件'},
            {k: 'enabled', t: '状态', cls: 'ctr', fmt: r => r.enabled ? App.tag('启用', App.ST) : App.tag('停用', App.ST)}
          ], d.list, {empty: '尚未配置 Webhook'})}</div></div>
        <div class="card"><div class="hd"><h3>最近投递</h3></div>
          <div class="bd nopad scroll">${App.table([
            {k: 'id', t: '#'}, {k: 'event', t: '事件'}, {k: 'status', t: '状态', cls: 'ctr'},
            {k: 'attempts', t: '尝试', cls: 'ctr'}, {k: 'lastAt', t: '时间'}, {k: 'response', t: '响应'}
          ], dv.list, {empty: '暂无投递记录'})}</div></div>`;
    } else if (tab === 'log') {
      const d = await App.GET('/api/logs?limit=300');
      html = `<div class="card"><div class="hd"><h3>审计日志（最近 ${d.list.length} 条）</h3></div>
        <div class="bd nopad scroll">${App.table([
          {k: 'at', t: '时间'}, {k: 'user', t: '操作人'},
          {k: 'action', t: '动作', fmt: r => `<b>${App.esc(r.action)}</b>`},
          {k: 'detail', t: '明细'}
        ], d.list)}</div></div>`;
    } else {
      html = `<div class="card" style="max-width:520px"><div class="hd"><h3>修改密码</h3></div>
        <div class="bd"><div class="form">
          <div class="f full"><label>原密码</label><input id="o" type="password"></div>
          <div class="f full"><label>新密码（至少 8 位）</label><input id="n" type="password"></div>
          <div class="f full"><label>确认新密码</label><input id="n2" type="password"></div>
        </div>
        <div class="bar" style="margin-top:16px"><button class="btn pri" id="sv">保存</button></div></div></div>`;
    }
    view.innerHTML = `<div class="tabs">${tabs.map(([k, t]) =>
      `<button class="${tab === k ? 'on' : ''}" data-tab="${k}">${t}</button>`).join('')}</div>` + html;
    view.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { st.sysTab = b.dataset.tab; App.route(); });

    const add = view.querySelector('#add');
    if (tab === 'user' && add) add.onclick = async () => {
      const d = await App.GET('/api/users');
      App.modal('新建用户', `<div class="form">
        <div class="f"><label>账号</label><input id="u"></div>
        <div class="f"><label>姓名</label><input id="n"></div>
        <div class="f"><label>角色</label><select id="r">${d.roles.map(r => `<option value="${r.code}">${r.name}</option>`).join('')}</select></div>
        <div class="f"><label>部门</label><input id="d"></div>
        <div class="f full"><label>初始密码（≥8 位）</label><input id="p" type="password"></div></div>`,
        `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">创建</button>`, {after: (m) => {
          m.querySelector('#sv').onclick = async () => {
            try {
              await App.POST('/api/users', {username: m.querySelector('#u').value.trim(),
                name: m.querySelector('#n').value, role: m.querySelector('#r').value,
                dept: m.querySelector('#d').value, password: m.querySelector('#p').value});
              App.ok('已创建'); App.closeModal(); App.route();
            } catch (e) { App.err(e.message); }
          };
        }});
    };
    if (tab === 'key' && add) add.onclick = () => App.modal('创建 API Key', `<div class="form">
        <div class="f"><label>名称</label><input id="n" placeholder="ERP 对接"></div>
        <div class="f"><label>权限</label><select id="s"><option value="read">只读</option><option value="write">读写</option></select></div>
      </div>`, `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">生成</button>`, {after: (m) => {
        m.querySelector('#sv').onclick = async () => {
          try {
            const r = await App.POST('/api/keys', {name: m.querySelector('#n').value,
                                                   scope: m.querySelector('#s').value});
            App.modal('API Key（仅显示一次）', `<div class="notice">请立即复制保存：</div>
              <pre style="background:#f7f9fc;padding:12px;border-radius:8px;word-break:break-all">${App.esc(r.key)}</pre>`);
          } catch (e) { App.err(e.message); }
        };
      }});
    if (tab === 'hook' && add) add.onclick = () => App.modal('新增 Webhook', `<div class="form">
        <div class="f"><label>名称</label><input id="n"></div>
        <div class="f"><label>URL</label><input id="u" placeholder="https://example.com/hook"></div>
        <div class="f full"><label>订阅事件（逗号分隔）</label><input id="e" value="expense.approved,period.closed">
          <div class="tip">可选：center.created, product.created, std.calculated, wo.created, wo.completed,
            expense.created, expense.approved, expense.rejected, alloc.executed, budget.updated,
            period.closed, variance.calculated</div></div></div>`,
      `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`, {after: (m) => {
        m.querySelector('#sv').onclick = async () => {
          try {
            const r = await App.POST('/api/webhooks', {name: m.querySelector('#n').value,
              url: m.querySelector('#u').value, events: m.querySelector('#e').value});
            App.modal('Webhook 已创建', `<div class="notice">签名密钥（仅显示一次）：</div>
              <pre style="background:#f7f9fc;padding:12px;border-radius:8px">${App.esc(r.secret)}</pre>`);
            setTimeout(() => App.route(), 1200);
          } catch (e) { App.err(e.message); }
        };
      }});
    if (tab === 'hook') {
      const t = view.querySelector('#test');
      if (t) t.onclick = async () => {
        try { await App.POST('/api/webhooks/test', {}); App.ok('已投递 test.ping（失败会自动重试）'); }
        catch (e) { App.err(e.message); }
      };
    }
    view.querySelectorAll('[data-rule]').forEach(b => b.onclick = async () => {
      const d = await App.GET('/api/rules');
      const r = d.list.find(x => x.code === b.dataset.rule);
      App.modal('修改规则 · ' + r.name, `<div class="form">
          <div class="f full"><label>取值</label><input id="v" value="${App.esc(r.value)}"></div>
          <div class="f full"><div class="tip">${App.esc(r.remark || '')}　单位：${App.esc(r.unit || '无')}</div></div>
        </div>`, `<button class="btn" data-x>取消</button><button class="btn pri" id="sv">保存</button>`,
        {after: (m) => {
          m.querySelector('#sv').onclick = async () => {
            try { await App.PUT('/api/rules/' + r.code, {value: m.querySelector('#v').value});
              App.ok('已保存'); App.closeModal(); App.route(); } catch (e) { App.err(e.message); }
          };
        }});
    });
    view.querySelectorAll('[data-rev]').forEach(b => b.onclick = () =>
      App.confirmBox('吊销 Key', '吊销后使用该 Key 的调用将全部失败，确认？', async () => {
        try { await App.POST(`/api/keys/${b.dataset.rev}/revoke`, {}); App.ok('已吊销'); App.route(); }
        catch (e) { App.err(e.message); }
      }, '吊销'));
    const pv = view.querySelector('#sv');
    if (tab === 'pwd' && pv) pv.onclick = async () => {
      const o = view.querySelector('#o').value, n = view.querySelector('#n').value,
            n2 = view.querySelector('#n2').value;
      if (n !== n2) return App.err('两次输入的新密码不一致');
      try { await App.PUT('/api/auth/password', {old: o, new: n}); App.ok('密码已修改'); App.route(); }
      catch (e) { App.err(e.message); }
    };
  }
});
