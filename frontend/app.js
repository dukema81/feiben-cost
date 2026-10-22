/* 飞奔成本管理系统 · 前端核心（路由 / 请求 / 渲染工具 / 图表） */
const App = (() => {
  const state = {user: null, period: '', periods: [], pstatus: ''};
  const PAGES = [];

  // ---------------------------------------------------------------- 请求
  async function API(method, path, body) {
    const t = localStorage.getItem('fb_token');
    const opt = {method, headers: {'Content-Type': 'application/json'}};
    if (t) opt.headers.Authorization = 'Bearer ' + t;
    if (body !== undefined && method !== 'GET') opt.body = JSON.stringify(body || {});
    const r = await fetch(path, opt);
    let d = null;
    try { d = await r.json(); } catch (e) { d = {}; }
    if (r.status === 401) { localStorage.removeItem('fb_token'); location.href = 'login.html'; throw new Error('登录已失效'); }
    if (!r.ok) throw new Error(d.message || ('请求失败 ' + r.status));
    return d;
  }
  const GET = (p, q) => API('GET', q ? p + (p.includes('?') ? '&' : '?') + q : p);
  const POST = (p, b) => API('POST', p, b);
  const PUT = (p, b) => API('PUT', p, b);
  const DEL = (p) => API('DELETE', p);

  // ---------------------------------------------------------------- 工具
  const $ = (s, r) => (r || document).querySelector(s);
  const esc = (s) => String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const money = (v, d) => {
    const n = Number(v || 0);
    return n.toLocaleString('zh-CN', {minimumFractionDigits: d === undefined ? 2 : d,
                                       maximumFractionDigits: d === undefined ? 2 : d});
  };
  const wan = (v) => {
    const n = Number(v || 0);
    return Math.abs(n) >= 10000 ? (n / 10000).toFixed(2) + ' 万' : money(n);
  };
  const num = (v, d) => Number(v || 0).toFixed(d === undefined ? 2 : d);
  const pct = (v, d) => (Number(v || 0) * 100).toFixed(d === undefined ? 1 : d) + '%';
  const sign = (v) => (Number(v) > 0 ? '+' : '');

  function toast(msg, kind) {
    const box = $('#toast');
    const d = document.createElement('div');
    d.className = kind || '';
    d.textContent = msg;
    box.appendChild(d);
    setTimeout(() => d.remove(), 2600);
  }
  const ok = (m) => toast(m, 'ok');
  const err = (m) => toast(m, 'err');

  function tag(v, map) {
    const cls = (map && map[v]) || 'gray';
    return `<span class="tag ${cls}">${esc(v)}</span>`;
  }
  const ST = {
    '已完工': 'green', '已关闭': 'gray', '在生产': 'blue', '草稿': 'gray',
    '已批准': 'green', '待审批': 'orange', '已驳回': 'red',
    '已结账': 'gray', '打开': 'green', '启用': 'green', '停用': 'gray',
    '正常': 'green', '预警': 'orange', '超支': 'red', '阻断区': 'red', '未设预算': 'gray',
    '重大不利': 'red', '不利': 'orange', '微小': 'gray', '有利': 'green', '重大有利': 'green',
    '已发布': 'green', '历史': 'gray', '在产': 'green'
  };

  // 表格：cols = [{k, t, w, cls, fmt}]
  function table(cols, rows, opts) {
    const o = opts || {};
    const th = cols.map(c => `<th class="${c.cls || ''}" ${c.w ? `style="width:${c.w}"` : ''}>${c.t}</th>`).join('');
    if (!rows || !rows.length) return `<table><thead><tr>${th}</tr></thead>
      <tbody><tr><td colspan="${cols.length}"><div class="empty">${o.empty || '暂无数据'}</div></td></tr></tbody></table>`;
    const tr = rows.map((r, i) => '<tr>' + cols.map(c => {
      let v = c.fmt ? c.fmt(r, i) : r[c.k];
      if (v === undefined || v === null || v === '') v = '<span class="dim">—</span>';
      return `<td class="${c.cls || ''}">${v}</td>`;
    }).join('') + '</tr>').join('');
    return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>`;
  }

  // ---------------------------------------------------------------- 弹层
  let maskEl, dlgEl;
  function modal(title, bodyHtml, footHtml, opts) {
    const o = opts || {};
    dlgEl.className = 'dlg' + (o.wide ? ' wide' : '');
    dlgEl.innerHTML = `<div class="dh"><h3>${esc(title)}</h3><button class="x" data-x>×</button></div>
      <div class="db">${bodyHtml}</div>
      <div class="df">${footHtml || '<button class="btn" data-x>关闭</button>'}</div>`;
    maskEl.classList.remove('hide');
    dlgEl.querySelectorAll('[data-x]').forEach(b => b.onclick = closeModal);
    if (o.after) o.after(dlgEl);
    return dlgEl;
  }
  function closeModal() { maskEl.classList.add('hide'); dlgEl.innerHTML = ''; }
  function confirmBox(title, text, onYes, yesText) {
    modal(title, `<div class="notice warn">${esc(text)}</div>`,
      `<button class="btn" data-x>取消</button>
       <button class="btn pri" id="yes">${esc(yesText || '确认执行')}</button>`,
      {after: (d) => { d.querySelector('#yes').onclick = async () => { closeModal(); await onYes(); }; }});
  }

  // ---------------------------------------------------------------- 图表
  function lineChart(series, labels, opts) {
    const o = Object.assign({h: 190, fmt: wan}, opts || {});
    const W = 720, H = o.h, pad = {l: 62, r: 12, t: 14, b: 24};
    const all = series.flatMap(s => s.data.map(Number));
    const max = Math.max(...all, 1), min = Math.min(...all, 0);
    const span = max - min || 1;
    const x = i => pad.l + (labels.length <= 1 ? 0 : i * (W - pad.l - pad.r) / (labels.length - 1));
    const y = v => pad.t + (1 - (v - min) / span) * (H - pad.t - pad.b);
    let g = '';
    for (let i = 0; i <= 3; i++) {
      const v = min + span * i / 3, yy = y(v);
      g += `<line x1="${pad.l}" y1="${yy}" x2="${W - pad.r}" y2="${yy}" stroke="#eef1f6"/>
            <text x="${pad.l - 8}" y="${yy + 4}" font-size="10.5" fill="#98a2b3" text-anchor="end">${o.fmt(v)}</text>`;
    }
    const COLORS = ['#1f6feb', '#0a8f4d', '#f2994a'];
    const paths = series.map((s, si) => {
      const c = s.color || COLORS[si % 3];
      const pts = s.data.map((v, i) => `${x(i)},${y(Number(v))}`).join(' ');
      const dots = s.data.map((v, i) => `<circle cx="${x(i)}" cy="${y(Number(v))}" r="3" fill="${c}"/>`).join('');
      return `<polyline points="${pts}" fill="none" stroke="${c}" stroke-width="2.2"/>${dots}`;
    }).join('');
    const xs = labels.map((l, i) => `<text x="${x(i)}" y="${H - 6}" font-size="10.5" fill="#98a2b3" text-anchor="middle">${esc(l)}</text>`).join('');
    return `<svg class="chart" viewBox="0 0 ${W} ${H}">${g}${paths}${xs}</svg>
      <div class="legend">${series.map((s, i) => `<span><i style="background:${s.color || COLORS[i % 3]}"></i>${esc(s.name)}</span>`).join('')}</div>`;
  }

  function bars(data, opts) {
    const o = Object.assign({key: 'name', val: 'amount', color: '#1f6feb', fmt: wan}, opts || {});
    const max = Math.max(...data.map(d => Math.abs(Number(d[o.val]))), 1);
    return data.map(d => {
      const v = Number(d[o.val]);
      const w = Math.max(2, Math.abs(v) / max * 100);
      const c = d.color || (v < 0 ? '#0a8f4d' : o.color);
      return `<div class="hbar"><span class="nm" title="${esc(d[o.key])}">${esc(d[o.key])}</span>
        <span class="tr"><i style="width:${w}%;background:${c}"></i></span>
        <span class="vl">${o.fmt(v)}</span></div>`;
    }).join('');
  }

  // ---------------------------------------------------------------- 页面注册
  function page(def) { PAGES.push(def); }

  const NAV = [
    {grp: '总览'},
    {id: 'dashboard', t: '成本驾驶舱', ic: '◈'},
    {grp: '主数据'},
    {id: 'center', t: '成本中心', ic: '◉'},
    {id: 'subject', t: '成本科目', ic: '▤'},
    {id: 'product', t: '产品与 BOM', ic: '▣'},
    {id: 'std', t: '标准成本', ic: '◐'},
    {grp: '成本核算'},
    {id: 'wo', t: '生产工单', ic: '⚙'},
    {id: 'exp', t: '费用归集', ic: '▦'},
    {id: 'alloc', t: '成本分摊', ic: '⇄'},
    {id: 'budget', t: '预算管控', ic: '◫'},
    {grp: '分析与关账'},
    {id: 'variance', t: '差异分析', ic: '◭'},
    {id: 'report', t: '报表中心', ic: '▥'},
    {id: 'period', t: '期间结账', ic: '⚑'},
    {grp: '系统'},
    {id: 'sys', t: '系统设置', ic: '☰'}
  ];

  function renderNav(cur) {
    $('#nav').innerHTML = NAV.map(n => n.grp ? `<div class="grp">${n.grp}</div>` :
      `<a href="#${n.id}" class="${n.id === cur ? 'on' : ''}"><span class="ic">${n.ic}</span>${n.t}</a>`).join('');
  }

  async function loadPeriods() {
    const d = await GET('/api/periods');
    state.periods = d.list;
    const cur = state.periods.find(p => p.status === '打开') || state.periods[0];
    if (!state.period) state.period = (cur && cur.period) || new Date().toISOString().slice(0, 7);
    const sel = $('#period');
    sel.innerHTML = state.periods.map(p =>
      `<option value="${p.period}" ${p.period === state.period ? 'selected' : ''}>${p.period}${p.status === '已结账' ? '（已结账）' : ''}</option>`).join('');
    if (!state.periods.length) sel.innerHTML = `<option>${state.period}</option>`;
    sel.onchange = () => { state.period = sel.value; route(); };
    const p = state.periods.find(x => x.period === state.period);
    const st = p ? p.status : '未建期';
    $('#pstate').textContent = st;
    $('#pstate').className = 'tag ' + (st === '打开' ? 'green' : st === '已结账' ? 'gray' : 'orange');
    return d;
  }

  async function route() {
    const id = (location.hash || '#dashboard').slice(1);
    const def = PAGES.find(p => p.id === id) || PAGES[0];
    renderNav(def.id);
    $('#ptitle').textContent = def.t;
    const view = $('#view');
    view.innerHTML = '<div class="empty">加载中…</div>';
    try {
      await loadPeriods();
      await def.render(view, state);
    } catch (e) {
      view.innerHTML = `<div class="notice bad">${esc(e.message)}</div>`;
    }
  }

  async function start() {
    if (!localStorage.getItem('fb_token')) { location.href = 'login.html'; return; }
    maskEl = $('#mask'); dlgEl = $('#dlg');
    maskEl.onclick = (e) => { if (e.target === maskEl) closeModal(); };
    try {
      state.user = await GET('/api/auth/me');
    } catch (e) { return; }
    $('#who').innerHTML = `<b>${esc(state.user.name)}</b>
      <span class="dim">${esc(state.user.roleName)}</span>`;
    $('#logout').onclick = async () => {
      try { await POST('/api/auth/logout', {}); } catch (e) {}
      localStorage.removeItem('fb_token'); location.href = 'login.html';
    };
    if (!location.hash) location.hash = '#dashboard';
    window.addEventListener('hashchange', route);
    await route();
  }

  return {API, GET, POST, PUT, DEL, $, esc, money, wan, num, pct, sign, toast, ok, err, tag, ST,
          table, modal, closeModal, confirmBox, lineChart, bars, page, start, state, route,
          renderNav, loadPeriods};
})();
