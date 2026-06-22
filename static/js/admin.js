let allArticles = [];
let currentFilter = 'featured';
let editingIssueId = null;
let editingArticleId = null;
let editingImages = [];
let issueReplaceState = {
  issueId: null,
  oldArticleId: null,
  oldTitle: '',
  position: null,
  tab: 'candidate',
  query: '',
  candidate: [],
  evergreen: [],
  issueArticleIds: new Set()
};
let evergreenModalPool = [];
let issueLocks = {};
let detailImageCache = [];
let articleBatchMode = false;
let articleBatchSelectedIds = new Set();
let currentRenderedArticleIds = [];
let maintenancePayloads = {};
let maintenanceArticleOptions = [];
let maintenanceArticleSelections = {
  resummarize: [],
  reeval: [],
  reveto: [],
  'clear-feedback': []
};

function isEvergreenArticle(a) {
  return a.evergreen === 1 || a.evergreen === '1' || a.evergreen === true;
}

function getArticleFilterTab(filter) {
  return Array.from(document.querySelectorAll('#filterTabs .filter-tab')).find(tab => {
    const onclick = tab.getAttribute('onclick') || '';
    const match = onclick.match(/filterArticles\('([^']+)'/);
    return match && match[1] === filter;
  }) || null;
}

function setActiveArticleFilterTab(filter, el) {
  document.querySelectorAll('#filterTabs .filter-tab').forEach(t => t.classList.remove('active'));
  const activeTab = el || getArticleFilterTab(filter);
  if (activeTab) activeTab.classList.add('active');
}

const CAT_EMOJI = {
  '精品酒店与度假':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="8" width="18" height="13" rx="1"/><path d="M3 12h18"/><path d="M9 8V5a2 2 0 012-2h2a2 2 0 012 2v3"/></svg>','旅行与探索':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z"/></svg>','美食与美酒':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 2v4M16 2v4"/><path d="M3 10h18v2a8 8 0 01-16 0v-2z"/><path d="M12 14v8"/></svg>','艺术与文化':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 15l5-5 4 4 4-6 5 5"/></svg>',
  '产品与设计':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18"/><path d="M9 3v18"/></svg>','建筑与空间':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/></svg>','时尚与风格':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.38 3.46L16 2 12 5.5 8 2l-4.38 1.46a1 1 0 00-.62.94v14a1 1 0 001 1h16a1 1 0 001-1v-14a1 1 0 00-.62-.94z"/><path d="M12 2v14"/></svg>','珠宝与腕表':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>','汽车与出行':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 17h14"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M5 17a2 2 0 01-2-2V9a2 2 0 012-2h1l2-3h8l2 3h1a2 2 0 012 2v6a2 2 0 01-2 2"/></svg>',
  '科技与生活':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>','健康与养生':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 000-7.78z"/></svg>',
  '音乐与演出':'<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'
};

const CHANNELS = ['精品酒店与度假','旅行与探索','美食与美酒','艺术与文化','建筑与空间','产品与设计','时尚与风格','珠宝与腕表','汽车与出行','科技与生活','健康与养生','音乐与演出'];

async function api(url, opts) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } catch(e) { console.error('API error:', url, e); return null; }
}

// ===== 页面切换 =====
function showPage(name, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.getElementById('page-' + name).classList.add('active');
  document.querySelectorAll('.nav-link').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  document.getElementById('sidebar').classList.remove('open');

  const titles = {
    dashboard: ['数据仪表盘','系统概览与数据统计'],
    articles: ['文章管理','审核、筛选与文章分析'],
    report: ['组刊工作台','从候选池中挑选文章组成新一期日报'],
    issues: ['往期日报','查看已生成日报并回填勾选结果'],
    maintenance: ['数据维护','执行存量数据操作']
  };
  document.getElementById('pageTitle').textContent = titles[name][0];
  document.getElementById('pageSub').textContent = titles[name][1];

  if (name === 'dashboard') loadDashboard();
  if (name === 'articles') {
    currentFilter = 'featured';
    pendingCategory = null;
    activeCatFilter = null;
    loadArticles();
  }
  if (name === 'report') { loadWorkbench(); currentFilter = 'candidate'; }
  if (name === 'issues') loadIssuesList();
  if (name === 'maintenance') {
    setupMaintenanceInputs();
    loadMaintenanceOptions();
  }
}

// ===== 仪表盘 =====
async function loadDashboard() {
  let stats;
  try { stats = await api('/api/stats'); } catch(e) { console.error('loadDashboard stats:', e); return; }
  if (!stats || typeof stats !== 'object') return;
  if (!stats.total && stats.total !== 0) return;

  try { document.getElementById('pendingCount').textContent = stats.pending || 0; } catch(e) { console.error('pendingCount:', e); }

  try {
  document.getElementById('statsGrid').innerHTML = `
    <div class="stat-card">
      <div class="stat-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg></div>
      <div class="stat-num">${stats.total || 0}</div>
      <div class="stat-label">总文章数</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></div>
      <div class="stat-num">${stats.selectable || 0}</div>
      <div class="stat-label">可筛选(A/B/C)</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><path d="M22 4L12 14.01l-3-3"/></svg></div>
      <div class="stat-num">${stats.candidate || 0}</div>
      <div class="stat-label">日报候选</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 4h16v16H4z"/><path d="M4 9h16M9 4v16"/></svg></div>
      <div class="stat-num">${stats.issues || 0}</div>
      <div class="stat-label">已生成日报(期)</div>
    </div>
    <div class="stat-card">
      <div class="stat-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 12l2 2 4-4"/><path d="M21 12c0 4.97-4.03 9-9 9s-9-4.03-9-9 4.03-9 9-9 9 4.03 9 9z"/></svg></div>
      <div class="stat-num">${stats.in_issue || 0}</div>
      <div class="stat-label">已入报文章</div>
    </div>
  `;
  } catch(e) { console.error('statsGrid:', e); document.getElementById('statsGrid').innerHTML = '<div style="color:var(--red);padding:20px">仪表盘加载失败，请刷新重试</div>'; }

  // Load category distribution, aligned with currently selectable A/B/C articles.
  try {
  const catCount = (stats && stats.category_counts) ? stats.category_counts : {};
  const ALL_CATEGORIES = ['精品酒店与度假','旅行与探索','美食与美酒','艺术与文化','建筑与空间','产品与设计','时尚与风格','珠宝与腕表','汽车与出行','科技与生活','健康与养生','音乐与演出'];
  let catHtml = '';
  ALL_CATEGORIES.forEach(cat => {
    const count = catCount[cat] || 0;
    catHtml += `
      <div class="cat-chip" onclick="showPage('articles', document.querySelector('[data-page=articles]')); filterByCategory('${cat}')">
        <span class="emoji">${CAT_EMOJI[cat] || ''}</span>
        <div class="count">${count}</div>
        <div class="name">${cat}</div>
      </div>`;
  });
  document.getElementById('catGrid').innerHTML = catHtml;
  } catch(e) { console.error('catGrid:', e); document.getElementById('catGrid').innerHTML = ''; }

  // Load archive reason stats
  try {
    const astats = await api('/api/archive-stats');
    let archiveHtml = '';
    if (astats && astats.reason_distribution && Object.keys(astats.reason_distribution).length > 0) {
      archiveHtml += '<div class="stat-section"><h4 style="font-size:13px;color:var(--text2);margin-bottom:8px">近30天归档理由分布</h4><div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">';
      Object.entries(astats.reason_distribution).forEach(([reason, count]) => {
        archiveHtml += '<div style="background:var(--card2);padding:6px 12px;border-radius:8px;font-size:12px"><span style="font-weight:600;color:var(--text)">' + reason + '</span> <span style="color:var(--accent)">×' + count + '</span></div>';
      });
      archiveHtml += '</div></div>';
    }
    if (astats && astats.ai_misclassify_count > 0) {
      archiveHtml += '<div class="stat-card" style="background:#fef0f0;border:1px solid #ecc">'
        + '<div class="stat-num" style="color:#c44">' + (astats.ai_misclassify_count || 0) + '</div>'
        + '<div class="stat-label">AI 评 A/B 档被人工归档 (误判参考)</div>'
        + '<div style="font-size:10px;color:var(--text3);margin-top:4px">近30天总归档 ' + (astats.total_archived_30d || 0) + ' 篇</div>'
        + '</div>';
    }
    document.getElementById('statsGrid').insertAdjacentHTML('beforeend', archiveHtml);
  } catch(e) { console.error(e); }

  // Expiry check stats
  try {
    const expStats = await api('/api/expiry-stats');
    if (expStats && expStats.stats) {
      const s = expStats.stats;
      let expHtml = '<div class="stat-section"><h4 style="font-size:13px;color:var(--text2);margin-bottom:8px">时效出清（最近一次）</h4>';
      expHtml += '<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">';
      expHtml += '<div style="background:var(--card2);padding:6px 12px;border-radius:8px;font-size:12px"><span style="color:var(--text)">扫描</span> <span style="color:var(--accent);font-weight:600">' + (s.checked || 0) + '</span> 篇</div>';
      expHtml += '<div style="background:var(--card2);padding:6px 12px;border-radius:8px;font-size:12px"><span style="color:var(--text)">归档过期</span> <span style="color:var(--red);font-weight:600">' + (s.archived || 0) + '</span> 篇</div>';
      expHtml += '<div style="background:var(--card2);padding:6px 12px;border-radius:8px;font-size:12px"><span style="color:var(--text)">即将过期</span> <span style="color:#b8860b;font-weight:600">' + (s.nearing || 0) + '</span> 篇</div>';
      expHtml += '</div>';
      if (expStats.summary) expHtml += '<div style="font-size:10px;color:var(--text3)">' + expStats.summary + '</div>';
      expHtml += '</div>';
      document.getElementById('statsGrid').insertAdjacentHTML('beforeend', expHtml);
    }
  } catch(e) { console.error(e); }

  // 沉库规模指标
  try {
    const sunkStats = await api('/api/sunk-stats');
    if (sunkStats && sunkStats.sunk_total !== undefined) {
      let sunkHtml = '<div class="stat-section dash-sunk-stat"><h4 style="font-size:13px;color:var(--text2);margin-bottom:8px">沉库规模</h4>';
      sunkHtml += '<div style="display:flex;gap:16px;margin-bottom:16px">';
      sunkHtml += '<div class="stat-card" style="border-left:3px solid #b8860b"><div class="stat-num" style="color:#b8860b">' + (sunkStats.sunk_total || 0) + '</div><div class="stat-label">沉库总数</div></div>';
      sunkHtml += '<div class="stat-card" style="border-left:3px solid #b8860b"><div class="stat-num" style="color:#b8860b">' + (sunkStats.sunk_7d || 0) + '</div><div class="stat-label">近7天净增</div></div>';
      sunkHtml += '</div></div>';
      document.getElementById('statsGrid').insertAdjacentHTML('beforeend', sunkHtml);
    }
  } catch(e) { console.error(e); }
}

// ===== 文章管理 =====
async function loadAllArticles() {
  // 全量加载(含 rejected/sunk), 用于全部入库视图
  const articles = await api('/api/articles?status=all&limit=1000');
  if (articles && articles.length > 0) {
    allArticles = articles;
    filterArticles();
  }
}

async function loadArticles() {
  const [articles, stats] = await Promise.all([
    api('/api/articles?limit=500'),
    api('/api/stats')
  ]);
  allArticles = articles;
  // Update tab count badges from server stats
  if (stats) {
    const tabCounts = {
      'featured': stats.featured || 0,
      'pending': stats.pending || 0,
      'pending_human': stats.pending_human || 0,
      'candidate': stats.candidate || 0,
      'evergreen': stats.evergreen || 0,
      'in_issue': stats.in_issue || 0,
      'checked': stats.dj_checked || 0,
      'rejected': stats.rejected || 0,
      'all': stats.total || 0
    };
    document.querySelectorAll('#filterTabs .filter-tab').forEach(tab => {
      const onclick = tab.getAttribute('onclick') || '';
      const match = onclick.match(/filterArticles\('(\w+)'/);
      if (match && tabCounts[match[1]] !== undefined) {
        const existing = tab.querySelector('.tab-count');
        if (existing) existing.remove();
        const count = tabCounts[match[1]];
        if (count > 0 || match[1] === 'evergreen') {
          const badge = document.createElement('span');
          badge.className = 'tab-count';
          badge.textContent = count;
          badge.style.cssText = 'margin-left:4px;font-size:10px;color:var(--text3);background:var(--card3);padding:1px 6px;border-radius:8px;font-family:-apple-system,sans-serif';
          tab.appendChild(badge);
        }
      }
    });
  }
  filterArticles();
}

let pendingCategory = null;
let filterDate = '';
let allSubFilter = 'in_flow';
let checkedSubFilter = 'all';
let inIssueSubFilter = 'all';
let activeCatFilter = null;
function filterByCategory(cat) {
  pendingCategory = cat;
  currentFilter = 'selectable';
  loadArticles();
}
function filterByCatTab(cat, el) {
  activeCatFilter = cat;
  pendingCategory = null;
  document.querySelectorAll('#catFilterRow .filter-tab').forEach(t => t.classList.remove('active'));
  if (el) el.classList.add('active');
  filterArticles();
}
function filterAllSub(sub, el) {
  allSubFilter = sub;
  document.querySelectorAll('#allArchiveChips .archive-chip').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  filterArticles();
}

function filterCheckedSub(sub, el) {
  checkedSubFilter = sub;
  document.querySelectorAll('#checkedChips .fb-chip').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  filterArticles();
}

function filterInIssueSub(sub, el) {
  inIssueSubFilter = sub;
  document.querySelectorAll('#inIssueChips .fb-chip').forEach(c => c.classList.remove('active'));
  if (el) el.classList.add('active');
  filterArticles();
}


function onDateChange(val) {
  filterDate = val;
  document.getElementById('filterDateInput').value = val;
  if (currentFilter) filterArticles(currentFilter);
}

function filterArticles(filter, el) {
  if (filter && typeof filter === 'string') {
    currentFilter = filter;
    pendingCategory = null;
    // 全部入库需要全量数据(含 rejected/sunk), 触发服务端重载
    if (currentFilter === 'all') {
      loadAllArticles();
      return;
    }
  }
  // 切换子筛选芯片行: 全部入库/已勾选/已入报
  document.getElementById('allArchiveChips').style.display = (currentFilter === 'all') ? 'flex' : 'none';
  document.getElementById('checkedChips').style.display = (currentFilter === 'checked') ? 'flex' : 'none';
  document.getElementById('inIssueChips').style.display = (currentFilter === 'in_issue') ? 'flex' : 'none';
  setActiveArticleFilterTab(currentFilter, el);
  let filtered = allArticles;
  if (currentFilter === 'selectable') {
    filtered = filtered.filter(a =>
      (a.gate2_tier === 'A' || a.gate2_tier === 'B' || a.gate2_tier === 'C') &&
      a.status === 'pending' &&
      !isEvergreenArticle(a) &&
      !(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) &&
      !(a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true)
    );
  } else if (currentFilter === 'featured') {
    filtered = filtered.filter(a =>
      (a.gate2_tier === 'A' || a.gate2_tier === 'B') &&
      a.status === 'pending' &&
      !isEvergreenArticle(a) &&
      !(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) &&
      !(a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true)
    );
  } else if (currentFilter === 'pending_human') {
    filtered = filtered.filter(a => {
    if (a.status === 'rejected' || a.status === 'sunk' || a.status === 'in_issue' || a.status === 'published') return false;
    return (a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true || a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true);
  });
  } else if (currentFilter === 'checked') {
    filtered = filtered.filter(a => a.dj_feedback === 'checked');
    if (checkedSubFilter === 'asap') {
      filtered = filtered.filter(a => a.feedback_detail === 'asap');
    } else if (checkedSubFilter === 'next_trip') {
      filtered = filtered.filter(a => a.feedback_detail === 'next_trip');
    }
  } else if (currentFilter === 'all') {
    if (allSubFilter === 'in_flow') {
      filtered = filtered.filter(a => a.status === 'pending' || a.status === 'candidate' || a.status === 'approved');
    } else if (allSubFilter === 'sunk') {
      filtered = filtered.filter(a => a.status === 'sunk');
    } else if (allSubFilter === 'archived') {
      filtered = filtered.filter(a => a.status === 'rejected');
    }
  } else if (currentFilter === 'evergreen') {
    filtered = filtered.filter(a => {
      const blocked = a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true || a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true;
      return isEvergreenArticle(a) && !a.issue_id && !blocked && (a.status === 'pending' || a.status === 'candidate' || a.status === 'approved');
    });
  } else {
    filtered = filtered.filter(a => {
      if (currentFilter === 'pending') {
        return a.gate2_tier === 'C' &&
          a.status === 'pending' &&
          !isEvergreenArticle(a) &&
          !(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) &&
          !(a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true);
      }
      if (currentFilter === 'candidate') return (a.status === 'candidate' || a.status === 'approved') && !isEvergreenArticle(a);
      if (currentFilter === 'in_issue') return a.status === 'in_issue' || a.status === 'published';
      return a.status === currentFilter;
    });
  }

  // 已入报子筛选: 按回填状态过滤
  if (currentFilter === 'in_issue') {
    if (inIssueSubFilter === 'checked') {
      filtered = filtered.filter(a => a.dj_feedback === 'checked');
    } else if (inIssueSubFilter === 'skipped') {
      filtered = filtered.filter(a => a.dj_feedback === 'skipped');
    } else if (inIssueSubFilter === 'none') {
      filtered = filtered.filter(a => !a.dj_feedback || a.dj_feedback === '');
    }
  }

  const q = (document.getElementById('searchInput')?.value || '').toLowerCase();
  if (q) filtered = filtered.filter(a =>
    (a.title||'').toLowerCase().includes(q) ||
    (a.translated_title||'').toLowerCase().includes(q) ||
    (a.source||'').toLowerCase().includes(q) );
  if (pendingCategory) {
    filtered = filtered.filter(a => a.category === pendingCategory);
  }
  if (filterDate) {
    filtered = filtered.filter(a => {
      const d = (a.crawled_at || '').slice(0, 10);
      return d === filterDate;
    });
  }
  if (activeCatFilter) {
    filtered = filtered.filter(a => a.category === activeCatFilter);
  }
  // Show category label if filtered from dashboard
  const catLabel = document.getElementById('catFilterLabel');
  if (catLabel) {
    if (pendingCategory) {
      catLabel.innerHTML = `<span style="display:inline-flex;align-items:center;gap:8px;background:var(--accent);color:#fff;padding:6px 16px;border-radius:20px;font-size:12px;font-family:-apple-system,sans-serif">${CAT_EMOJI[pendingCategory]||''} ${pendingCategory} <span style="cursor:pointer;opacity:.8" onclick="pendingCategory=null;filterArticles()">×</span></span>`;
    } else {
      catLabel.innerHTML = '';
    }
  }
  renderArticles(filtered);
}

function renderArticleBatchBar(articles) {
  const bar = document.getElementById('articleBatchBar');
  if (!bar) return;
  const visibleIds = new Set((articles || []).map(a => Number(a.id)));
  articleBatchSelectedIds.forEach(id => {
    if (!allArticles.find(a => Number(a.id) === Number(id))) articleBatchSelectedIds.delete(id);
  });
  const selectedVisible = [...articleBatchSelectedIds].filter(id => visibleIds.has(Number(id))).length;
  const selectedTotal = articleBatchSelectedIds.size;
  bar.classList.toggle('is-active', articleBatchMode);
  if (!articleBatchMode) {
    bar.innerHTML = `
      <div class="article-batch-left">
        <button class="btn btn-outline btn-sm" onclick="toggleArticleBatchMode(true)">批量选择</button>
        <span class="article-batch-count">需要连续处理多篇时开启</span>
      </div>
    `;
    return;
  }
  bar.innerHTML = `
    <div class="article-batch-left">
      <button class="btn btn-outline btn-sm" onclick="toggleArticleBatchMode(false)">退出批量</button>
      <button class="btn btn-outline btn-sm" onclick="selectVisibleArticles()">全选当前</button>
      <button class="btn btn-outline btn-sm" onclick="clearArticleBatchSelection()">清空</button>
      <span class="article-batch-count">已选 ${selectedTotal} 篇${selectedVisible !== selectedTotal ? '，当前筛选内 ' + selectedVisible + ' 篇' : ''}</span>
    </div>
    <div class="article-batch-actions">
      <button class="btn btn-green btn-sm" onclick="runArticleBatchAction('candidate')" ${selectedTotal ? '' : 'disabled'}>加入候选</button>
      <button class="btn btn-outline btn-sm" onclick="runArticleBatchAction('pending')" ${selectedTotal ? '' : 'disabled'}>移出候选</button>
      <button class="btn btn-outline btn-sm" onclick="runArticleBatchAction('clear_pending')" ${selectedTotal ? '' : 'disabled'}>放行待人工</button>
      <button class="btn btn-red btn-sm" onclick="runArticleBatchAction('rejected')" ${selectedTotal ? '' : 'disabled'}>归档</button>
    </div>
  `;
}

function toggleArticleBatchMode(force) {
  articleBatchMode = typeof force === 'boolean' ? force : !articleBatchMode;
  if (!articleBatchMode) articleBatchSelectedIds.clear();
  filterArticles();
}

function toggleArticleBatchSelection(id) {
  id = Number(id);
  if (articleBatchSelectedIds.has(id)) articleBatchSelectedIds.delete(id);
  else articleBatchSelectedIds.add(id);
  filterArticles();
}

function selectVisibleArticles() {
  currentRenderedArticleIds.forEach(id => articleBatchSelectedIds.add(Number(id)));
  filterArticles();
}

function clearArticleBatchSelection() {
  articleBatchSelectedIds.clear();
  filterArticles();
}

function selectedArticleBatchIds() {
  return [...articleBatchSelectedIds].map(Number).filter(Boolean);
}

async function runArticleBatchAction(action) {
  const ids = selectedArticleBatchIds();
  if (!ids.length) return alert('请先选择文章');
  if (action === 'rejected') {
    showBatchArchiveReason(ids);
    return;
  }
  const labels = {
    candidate: '加入候选',
    pending: '移出候选并回到待筛选',
    clear_pending: '放行待人工'
  };
  if (!confirm('确认对 ' + ids.length + ' 篇文章执行“' + (labels[action] || action) + '”？')) return;
  let res = null;
  if (action === 'candidate') {
    res = await api('/api/batch-review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids, status:'candidate'})});
  } else if (action === 'pending') {
    res = await api('/api/batch-move-pending', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids})});
  } else if (action === 'clear_pending') {
    res = await api('/api/clear-pending', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids})});
  }
  if (!res || res.ok === false) return alert((res && res.error) || '批量操作失败');
  articleBatchSelectedIds.clear();
  articleBatchMode = false;
  await refreshData();
}

function renderArticles(articles) {
  const grid = document.getElementById('articleGrid');
  const countEl = document.getElementById('filterCount');
  currentRenderedArticleIds = articles.map(a => Number(a.id));
  renderArticleBatchBar(articles);
  // 显示筛选计数
  var labelParts = [];
  if (currentFilter === 'selectable') labelParts.push('可筛选 A/B/C');
  else if (currentFilter === 'featured') labelParts.push('精选待筛选');
  else if (currentFilter === 'pending') labelParts.push('C档待筛选');
  else if (currentFilter === 'pending_human') labelParts.push('待人工');
  else if (currentFilter === 'candidate') labelParts.push('候选');
  else if (currentFilter === 'in_issue') {
    labelParts.push('已入报');
    if (inIssueSubFilter === 'checked') labelParts.push('已勾选');
    else if (inIssueSubFilter === 'skipped') labelParts.push('已跳过');
    else if (inIssueSubFilter === 'none') labelParts.push('未操作');
  }
  else if (currentFilter === 'checked') {
    labelParts.push('已勾选');
    if (checkedSubFilter === 'asap') labelParts.push('尽快安排');
    else if (checkedSubFilter === 'next_trip') labelParts.push('下次顺路');
  }
  else if (currentFilter === 'approved') labelParts.push('已通过');
  else if (currentFilter === 'evergreen') labelParts.push('常青库');
  else if (currentFilter === 'all') {
    const subLabels = {'in_flow': '流转中', 'sunk': '沉库', 'archived': '已归档'};
    labelParts.push('全部入库 · ' + (subLabels[allSubFilter] || allSubFilter));
  } else labelParts.push(currentFilter);
  if (activeCatFilter) labelParts.push(activeCatFilter);
  if (filterDate) labelParts.push(filterDate);
  if (pendingCategory) labelParts.push(pendingCategory);
  if (labelParts.length > 0) {
    countEl.style.display = 'block';
    countEl.textContent = labelParts.join(' + ') + ' — 共 ' + articles.length + ' 篇';
  } else {
    countEl.style.display = 'none';
  }
  grid.classList.add('feed-list');
  if (!articles.length) {
    grid.innerHTML = '<div style="text-align:center;padding:60px;color:var(--text3);font-size:14px">暂无文章</div>';
    return;
  }

  const groups = {};
  articles.forEach(a => {
    const d = (a.crawled_at || '').slice(0, 10) || '未知日期';
    if (!groups[d]) groups[d] = [];
    groups[d].push(a);
  });

  let html = '';
  Object.entries(groups).sort((a,b) => b[0].localeCompare(a[0])).forEach(([date, items]) => {
    html += `<div class="feed-date">${escapeHtml(formatFeedDate(date))}</div>`;
    items.forEach(a => {
      const imgs = asArray(a.images);
      const tags = asArray(a.tags);
      const thumb = imgs.length ? imageSrc(imgs[0]) : '';
      const title = a.translated_title || a.title || '';
      const summary = a.summary || a.recommend_reason || '';
      const selected = articleBatchSelectedIds.has(Number(a.id));
      html += `
        <div class="feed-item${articleBatchMode ? ' batch-mode' : ''}${selected ? ' batch-selected' : ''}" onclick="${articleBatchMode ? 'toggleArticleBatchSelection(' + a.id + ')' : 'openDetail(' + a.id + ')'}">
          ${articleBatchMode ? `<div class="feed-select"><input type="checkbox" ${selected ? 'checked' : ''} onclick="event.stopPropagation();toggleArticleBatchSelection(${a.id})"></div>` : ''}
          ${thumb ? `<img class="feed-thumb" src="${escapeHtml(thumb)}" loading="lazy" onerror="this.outerHTML='<div class=feed-thumb-empty></div>'">` : `<div class="feed-thumb-empty"></div>`}
          <div class="feed-main">
            <div class="feed-meta">
              <span class="cat-tag">${CAT_EMOJI[a.category] || ''} ${escapeHtml(a.category || '')}</span>
              <span>${escapeHtml((a.crawled_at || '').slice(11,16))}</span>
              <span>${escapeHtml(a.source || '')}</span>
            </div>
            <div class="feed-tier-row">
              ${(a.veto_hit === 1 || a.veto_hit === '1' || a.veto_hit === true) ? '<span class="veto-badge">否决' + (a.veto_rule ? ':' + a.veto_rule.slice(0,20) : '') + '</span>' : ''}
              ${(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) ? '<span class="pending-human-badge">待人工</span>' : ''}${(a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true) ? '<span class="summary-flagged-badge">摘要待审</span>' : ''}
              ${(a.gate2_tier) ? '<span class="tier-badge tier-' + a.gate2_tier + '">' + a.gate2_tier + '档</span>' : ''}
              ${a.gate2_dim_excitement != null ? `<span class="dims-tag">兴奋${a.gate2_dim_excitement}　落地${a.gate2_dim_feasibility}　密度${a.gate2_dim_density}</span>` : ''}
            </div>
            <div class="feed-title">${escapeHtml(title)}</div>
            ${a.translated_title ? `<div class="feed-original">${escapeHtml(a.title || '')}</div>` : ''}
            ${a.gate2_one_line ? `<div class="one-line-hook">${escapeHtml(a.gate2_one_line)}</div>` : ''}
            ${a.gate3_rationale ? `<div class="rationale-line"><span class="section-label">推荐理由</span>${escapeHtml(a.gate3_rationale)}</div>` : ''}
            ${summary ? `<div class="feed-summary"><span class="section-label">中文摘要</span>${escapeHtml(summary)}</div>` : ''}
            ${(asArray(a.gate2_fit_reasons)||[]).length ? (a.veto_hit === 1 || a.veto_hit === '1' || a.veto_hit === true ? `<details class="fit-tags-collapsed" style="margin-top:4px"><summary style="font-size:10px;color:var(--text3);cursor:pointer;opacity:.5">历史契合标签 (${asArray(a.gate2_fit_reasons).length}条)</summary><div class="fit-tags" style="margin-top:4px">${asArray(a.gate2_fit_reasons).slice(0,5).map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div></details>` : `<div class="fit-tags">${asArray(a.gate2_fit_reasons).slice(0,5).map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>`) : ''}
            ${tags.length ? `<div class="feed-tags">${tags.slice(0,6).map(t => `<span>${escapeHtml(t)}</span>`).join('')}</div>` : ''}
            <div class="feed-actions">
              <span style="font-size:12px;color:var(--text3)">${escapeHtml(date)}</span>
              <div class="feed-buttons">
                ${(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) ? `
                  <span style="color:#b8860b;font-size:11px;padding:3px 8px;background:#fff8e1;border-radius:4px">⏳ 待人工</span>
                  <button class="btn btn-green btn-sm" onclick="event.stopPropagation();releasePending(${a.id})">放行</button>
                  <button class="btn btn-red btn-sm" onclick="event.stopPropagation();violatePending(${a.id})">确认违规</button>
                ` : (a.dj_feedback === 'checked') ? `
                  <span style="color:var(--green);font-size:11px;padding:3px 8px;background:#e8f5e9;border-radius:4px">✓ 已勾选</span>
                  ${(a.feedback_detail === 'asap') ? ' <span class="fb-badge asap">尽快安排</span>' : ''}
                  ${(a.feedback_detail === 'next_trip') ? ' <span class="fb-badge next_trip">下次顺路</span>' : ''}
                ` : (a.dj_feedback === 'skipped') ? `
                  <span style="color:#c62828;font-size:11px;padding:3px 8px;background:#fce4ec;border-radius:4px">✗ 已跳过</span>
                ` : a.status === 'rejected' ? `
                  <span style="color:var(--text3);font-size:11px;padding:3px 8px;background:#f0ece4;border-radius:4px">已归档</span>
                ` : (a.status === 'in_issue' || a.status === 'published') ? `
                  <span style="color:var(--accent);font-size:11px;padding:3px 8px;background:#f5f0e8;border-radius:4px">已入报</span>
                  ${(a.dj_feedback === 'checked' && a.feedback_detail === 'asap') ? ' <span class="fb-badge asap">尽快安排</span>' : ''}
                  ${(a.dj_feedback === 'checked' && a.feedback_detail === 'next_trip') ? ' <span class="fb-badge next_trip">下次顺路</span>' : ''}
                  ${(a.dj_feedback === 'skipped') ? ' <span class="fb-badge skipped">已跳过</span>' : ''}
                  ${(!a.dj_feedback || a.dj_feedback === '') ? ' <span class="fb-badge none">未操作</span>' : ''}
                ` : (a.status === 'candidate' || a.status === 'approved') ? `
                  <span style="color:var(--accent);font-size:11px;padding:3px 8px;background:#f5f0e8;border-radius:4px">候选池</span>
                  <button class="btn btn-red btn-sm" onclick="event.stopPropagation();showArchiveReason(${a.id})">归档</button>
                  <button class="btn btn-outline btn-sm" onclick="event.stopPropagation();toggleEvergreen(${a.id})" style="font-size:10px">${a.evergreen ? '★ 已常青' : '☆ 常青'}</button>
                ` : a.status === 'pending' ? `
                  ${(a.veto_hit === 1 || a.veto_hit === '1' || a.veto_hit === true) ? '' : `<button class="btn btn-green btn-sm" onclick="event.stopPropagation();doAction(${a.id},'candidate')">加入候选</button>`}
                  <button class="btn btn-red btn-sm" onclick="event.stopPropagation();showArchiveReason(${a.id})">归档</button>
                  <button class="btn btn-outline btn-sm" onclick="event.stopPropagation();toggleEvergreen(${a.id})" style="font-size:10px">${a.evergreen ? '★ 已常青' : '☆ 常青'}</button>
                ` : ''}
                <button class="btn btn-outline btn-sm" onclick="event.stopPropagation();openDetail(${a.id})">详情</button>
              </div>
            </div>
          </div>
        </div>`;
    });
  });
  grid.innerHTML = html;
}

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try { return JSON.parse(value); } catch(e) { return []; }
}

function escapeHtml(value) {
  return String(value || '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}

function imageSrc(path) {
  if (!path) return '';
  if (/^https?:\/\//.test(path)) return path;
  const clean = String(path).split('/').pop().split('?')[0].split('#')[0];
  return `/images/${clean}`;
}

function formatFeedDate(date) {
  if (date === '未知日期') return date;
  const d = new Date(date + 'T00:00:00');
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.floor((today - d) / 86400000);
  if (diff === 0) return '今天';
  if (diff === 1) return '昨天';
  return `${d.getMonth()+1}月${d.getDate()}日`;
}

// ===== 文章详情弹窗 =====
async function openDetail(id, context) {
  context = context || '';
  const a = await api('/api/articles/' + id);
  if (!a || a.error) return;

  const imgs = asArray(a.images);
  detailImageCache = imgs;

  // Hero
  const heroEl = document.getElementById('modalHero');
  if (imgs.length > 0) {
    heroEl.innerHTML = `<img class="modal-hero" src="${escapeHtml(imageSrc(imgs[0]))}" onerror="this.style.display='none'">`;
  } else {
    heroEl.innerHTML = '';
  }

  // Body
  let body = '';
  const tierBadge = a.gate2_tier ? `<span class="tier-badge tier-${a.gate2_tier}" style="font-size:11px;padding:4px 12px">${a.gate2_tier}档</span>` : '';
  const dimsInfo = a.gate2_dim_excitement != null ? `<span class="dims-tag">兴奋${a.gate2_dim_excitement} · 落地${a.gate2_dim_feasibility} · 密度${a.gate2_dim_density}</span>` : '';
  const rankBadge = a.gate3_rank ? `<span style="font-size:12px;color:var(--accent);font-weight:700">#${a.gate3_rank}</span>` : '';
  body += `<div class="modal-meta">
    ${tierBadge}
    ${rankBadge}
    <span class="cat-tag" id="articleCategoryPill">${CAT_EMOJI[a.category]||''} ${a.category||''}</span>
    <span class="src-tag">${a.source||''}</span>
    <span style="font-size:12px;color:var(--text3);margin-left:auto">${dimsInfo}</span>
  </div>`;
  body += renderCategoryEditor(a.id, a.category || '', context);
  body += `<h2 class="modal-title">${escapeHtml(a.translated_title || a.title || '')}</h2>`;
  if (a.translated_title && a.title) body += `<div style="font-size:13px;color:var(--text3);line-height:1.7;margin-top:-4px;margin-bottom:18px">${escapeHtml(a.title)}</div>`;

  if (a.gate2_one_line) body += `<div class="modal-section"><div class="modal-section-title">一句话钩子</div><div class="one-line-hook" style="margin:0">${escapeHtml(a.gate2_one_line)}</div></div>`;
  if (a.gate3_rationale) body += `<div class="modal-section"><div class="modal-section-title">小组赛胜出理由</div><div class="rationale-line" style="margin:0;padding:6px 10px;background:#5a7a9a0a;border-left:2px solid #5a7a9a44;border-radius:0 4px 4px 0">${escapeHtml(a.gate3_rationale)}</div></div>`;
  if (a.summary) body += `<div class="modal-section"><div class="modal-section-title">中文整理 / 翻译摘要</div><div class="modal-section-body">${escapeHtml(a.summary).replace(/\n/g,'<br>')}</div></div>`;
  if (a.translated_content) body += `<div class="modal-section"><div class="modal-section-title">正文中文详译</div><div class="modal-fulltext">${escapeHtml(a.translated_content).replace(/\n/g,'<br>')}</div></div>`;

  const tags = asArray(a.tags);
  if (tags.length) {
    body += `<div class="modal-section"><div class="modal-section-title">标签</div><div class="modal-tags">`;
    tags.forEach(t => body += `<span>#${escapeHtml(t)}</span>`);
    body += `</div></div>`;
  }

  if (imgs.length) {
    body += `<div class="modal-section"><div class="modal-section-title">H5 可见图片</div><div class="modal-image-grid">`;
    imgs.slice(0, 5).forEach((img, idx) => {
      const label = idx === 0 ? '封面' : `画廊 ${idx}`;
      body += `<div class="modal-image-cell"><span>${label}</span><img src="${escapeHtml(imageSrc(img))}" onerror="this.style.display='none'"></div>`;
    });
    body += `</div>`;
    body += `<button class="modal-more-images-btn" onclick="renderAllDetailImages(this)">查看全部抓取图（${imgs.length} 张）</button><div class="modal-all-images" id="modalAllImages"></div>`;
    body += `</div>`;
  }

  if (a.content) {
    body += `<div class="modal-section"><div class="modal-section-title">原文正文</div><div class="modal-fulltext">${escapeHtml(a.content).replace(/\n/g,'<br>')}</div></div>`;
  }

  body += `<a class="modal-link" href="${a.url}" target="_blank">${a.url}</a>`;
  document.getElementById('modalBody').innerHTML = body;
  const isInIssue = a.status === 'in_issue' || a.status === 'published';
  const isCandidate = a.status === 'candidate';
  const canCandidate = a.status === 'pending' && !isInIssue && !isCandidate;
  const lightAnalysisButtons = renderLightArticleActionButtons(a.id, context);
  let footerHtml = '';
  if (context === 'workbench') {
    const inSelection = !!selectedArticleById(a.id);
    footerHtml = `
      <button class="btn btn-outline" onclick="toggleEvergreenFromModal(${a.id})" id="evergreenBtn">${a.evergreen ? '★ 取消常青' : '☆ 标记常青'}</button>
      ${lightAnalysisButtons}
      <button class="btn ${inSelection ? 'btn-outline' : 'btn-gold'}" id="workbenchSelectBtn" onclick="toggleWorkbenchSelectionFromModal(${a.id})">${inSelection ? '移出本期' : '选入本期'}</button>
    `;
  } else if (isInIssue) {
    footerHtml = `
      <span style="color:var(--green);font-size:13px;display:flex;align-items:center;gap:4px">✓ 已入报</span>
      <button class="btn btn-outline" onclick="toggleEvergreenFromModal(${a.id})" id="evergreenBtn">${a.evergreen ? '★ 取消常青' : '☆ 标记常青'}</button>
      ${lightAnalysisButtons}
    `;
  } else if (isCandidate) {
    footerHtml = `
      <span style="color:var(--accent);font-size:13px;display:flex;align-items:center;gap:4px">已入选候选池</span>
      <button class="btn btn-red" onclick="showArchiveReason(${a.id})">× 归档</button>
      <button class="btn btn-outline" onclick="toggleEvergreenFromModal(${a.id})" id="evergreenBtn">${a.evergreen ? '★ 取消常青' : '☆ 标记常青'}</button>
      ${lightAnalysisButtons}
    `;
  } else {
    footerHtml = `
      <button class="btn btn-red" onclick="showArchiveReason(${a.id})">× 归档</button>
      ${canCandidate ? `<button class="btn btn-green" onclick="doAction(${a.id},'candidate');closeModal()">√ 加入日报候选</button>` : ''}
      <button class="btn btn-outline" onclick="toggleEvergreenFromModal(${a.id})" id="evergreenBtn">${a.evergreen ? '★ 取消常青' : '☆ 标记常青'}</button>
      ${lightAnalysisButtons}
    `;
  }
  document.getElementById('modalFooter').innerHTML = footerHtml;
  document.getElementById('modalBg').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function renderCategoryEditor(id, category, context) {
  const ctxArg = context ? ",'" + context + "'" : "";
  const options = CHANNELS.map(cat => '<option value="' + escapeHtml(cat) + '"' + (cat === category ? ' selected' : '') + '>' + escapeHtml(cat) + '</option>').join('');
  return `
    <div class="modal-category-editor">
      <span>频道</span>
      <select id="articleCategorySelect">${options}</select>
      <button class="btn btn-outline btn-sm" id="articleCategorySaveBtn" onclick="saveArticleCategory(${id}${ctxArg})">保存</button>
      <span class="modal-category-status" id="articleCategoryStatus"></span>
    </div>
  `;
}

function renderLightArticleActionButtons(id, context) {
  const ctxArg = context ? ",'" + context + "'" : "";
  return `
    <button class="btn btn-outline" onclick="rerunArticleSummary(${id}${ctxArg})">重跑摘要</button>
    <button class="btn btn-outline" onclick="translateArticleContent(${id}${ctxArg})">补全文翻译</button>
  `;
}

async function saveArticleCategory(id, context) {
  const select = document.getElementById('articleCategorySelect');
  const btn = document.getElementById('articleCategorySaveBtn');
  const status = document.getElementById('articleCategoryStatus');
  const category = select ? select.value : '';
  if (!category) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '保存中...';
  }
  if (status) {
    status.textContent = '';
    status.className = 'modal-category-status';
  }
  try {
    const res = await fetch('/api/articles/' + id + '/category', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({category})
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || '保存频道失败');
    updateLocalArticleCategory(id, data.category);
    const pill = document.getElementById('articleCategoryPill');
    if (pill) pill.innerHTML = (CAT_EMOJI[data.category] || '') + ' ' + escapeHtml(data.category);
    if (context === 'workbench') {
      renderCandidatePool();
      renderIssuePanel();
    } else {
      filterArticles();
    }
    if (status) {
      status.textContent = '已保存';
      status.className = 'modal-category-status ok';
    }
    if (btn) btn.textContent = '已保存';
    setTimeout(() => {
      const currentBtn = document.getElementById('articleCategorySaveBtn');
      const currentStatus = document.getElementById('articleCategoryStatus');
      if (currentBtn) {
        currentBtn.disabled = false;
        currentBtn.textContent = '保存';
      }
      if (currentStatus) currentStatus.textContent = '';
    }, 1400);
  } catch(e) {
    if (status) {
      status.textContent = e.message || '保存失败';
      status.className = 'modal-category-status error';
    } else {
      alert(e.message || '保存频道失败');
    }
    if (btn) {
      btn.disabled = false;
      btn.textContent = '保存';
    }
  }
}

function updateLocalArticleCategory(id, category) {
  [allArticles, candidateArticles, selectedArticles, evergreenModalPool].forEach(list => {
    if (!Array.isArray(list)) return;
    list.forEach(a => {
      if (Number(a.id) === Number(id)) a.category = category;
    });
  });
}

function renderAllDetailImages(btn) {
  const target = document.getElementById('modalAllImages');
  if (!target) return;
  if (target.innerHTML) {
    target.innerHTML = '';
    if (btn) btn.textContent = '查看全部抓取图（' + detailImageCache.length + ' 张）';
    return;
  }
  let html = '<div class="modal-image-grid modal-image-grid-all">';
  detailImageCache.forEach((img, idx) => {
    const h5Label = idx === 0 ? '封面' : (idx < 5 ? `H5 画廊 ${idx}` : '未展示');
    html += `<div class="modal-image-cell"><span>#${idx + 1} · ${h5Label}</span><img src="${escapeHtml(imageSrc(img))}" loading="lazy" onerror="this.style.display='none'"></div>`;
  });
  html += '</div>';
  target.innerHTML = html;
  if (btn) btn.textContent = '收起全部抓取图';
}

function toggleWorkbenchSelectionFromModal(id) {
  toggleArticle(id);
  const btn = document.getElementById('workbenchSelectBtn');
  if (!btn) return;
  const inSelection = !!selectedArticleById(id);
  btn.textContent = inSelection ? '移出本期' : '选入本期';
  btn.classList.toggle('btn-gold', !inSelection);
  btn.classList.toggle('btn-outline', inSelection);
}

function openWorkbenchArticleDetail(id) {
  openDetail(id, 'workbench');
}

function showArchiveReason(id) {
  var reasons = ['不对味','图不行','软广/营销味重','时效已过','内容重复','其他'];
  var shortcuts = [1,2,3,null,null,null]; // only first 3 have shortcuts
  var html = '<div class="archive-overlay" id="archiveOv" onclick="if(event.target===this)closeArchiveOverlay()"><div class="archive-chips"><h3>归档理由 <span style="font-size:11px;color:var(--text3);font-weight:400">快捷键 1-3</span></h3><div class="chip-grid">';
  reasons.forEach(function(r, i) {
    var keyHint = shortcuts[i] ? ' <span style="font-size:9px;color:var(--text3)">' + shortcuts[i] + '</span>' : '';
    html += '<div class="chip" onclick="doArchive(' + id + ',\'' + r + '\');closeArchiveOverlay()" data-key="' + (i+1) + '">' + r + keyHint + '</div>';
  });
  html += `</div><div class="archive-custom"><label>手动输入理由</label><div class="archive-custom-row"><input id="archiveCustomReason" type="text" placeholder="例如：标题党、图片错配、信息太水..." onkeydown="if(event.key==='Enter')submitCustomArchiveReason(${id})"><button class="btn btn-red btn-sm" onclick="submitCustomArchiveReason(${id})">确认归档</button></div></div></div></div>`;
  document.body.insertAdjacentHTML('beforeend', html);
  window._archiveTargetId = id;
}

function submitCustomArchiveReason(id) {
  const input = document.getElementById('archiveCustomReason');
  const reason = (input && input.value ? input.value.trim() : '');
  if (!reason) return alert('请先输入归档理由');
  doArchive(id, reason);
  closeArchiveOverlay();
}

function closeArchiveOverlay() {
  var ov = document.getElementById('archiveOv');
  if (ov) ov.remove();
  window._archiveTargetId = null;
}

// Keyboard shortcut handler (1-3 for archive reasons)
document.addEventListener('keydown', function(e) {
  if (!window._archiveTargetId) return;
  // Only if not typing in an input
  var tag = document.activeElement && document.activeElement.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  var reasons = ['不对味','图不行','软广/营销味重'];
  var idx = parseInt(e.key);
  if (idx >= 1 && idx <= reasons.length) {
    e.preventDefault();
    doArchive(window._archiveTargetId, reasons[idx-1]);
    closeArchiveOverlay();
  }
  if (e.key === 'Escape') {
    closeArchiveOverlay();
  }
});

async function doArchive(id, reason) {
  reason = (reason || '').trim();
  if (!reason) return alert('请选择或输入归档理由');
  await api('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({id,status:'rejected',archive_reason:reason})});
  closeModal();
  await refreshData();
}

async function toggleEvergreenFromModal(id) {
  const a = await api('/api/articles/' + id);
  const newVal = !a.evergreen;
  const res = await fetch('/api/mark-evergreen', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: id, evergreen: newVal})
  });
  const data = await res.json();
  if (!data.ok) {
    alert(data.error || '标记常青失败');
    return;
  }
  const btn = document.getElementById('evergreenBtn');
  if (btn) btn.textContent = data.evergreen ? '★ 已常青' : '☆ 标记常青';
  const local = allArticles.find(x => x.id === id);
  if (local) local.evergreen = data.evergreen;
  await refreshData();
}

function closeModal() {
  document.getElementById('modalBg').classList.remove('open');
  document.getElementById('modal').classList.remove('card-edit-modal-shell');
  document.getElementById('modal').classList.remove('workbench-card-preview-shell');
  document.body.style.overflow = '';
}

// ===== 操作 =====
async function doAction(id, status, archiveReason) {
  const body = {id, status};
  if (archiveReason) body.archive_reason = archiveReason;
  await api('/api/review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
  await refreshData();
}

async function batchAction(status) {
  const ids = allArticles.filter(a => currentFilter==='featured'
    ? ((a.gate2_tier === 'A' || a.gate2_tier === 'B') &&
       a.status === 'pending' &&
       !isEvergreenArticle(a) &&
       !(a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true) &&
       !(a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true))
    : a.status==='pending' && !isEvergreenArticle(a)).map(a => a.id);
  if (!ids.length) return alert('没有待审核文章');

  if (status === 'rejected') {
    // 归档需要选择原因
    showBatchArchiveReason(ids);
    return;
  }

  if (!confirm('确认加入候选 ' + ids.length + ' 篇待筛选文章？')) return;
  await api('/api/batch-review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids,status})});
  await refreshData();
}

function showBatchArchiveReason(ids) {
  var chips = [
    {label:'时效已过', value:'时效已过', key:'1'},
    {label:'内容重复', value:'内容重复', key:'2'},
    {label:'质量不足', value:'质量不足', key:'3'},
    {label:'不符合调性', value:'不符合调性', key:'4'},
    {label:'来源不权威', value:'来源不权威', key:'5'},
    {label:'图片质量差', value:'图片质量差', key:'6'},
    {label:'其他原因', value:'其他原因', key:'7'},
  ];
  var html = '<div class="archive-overlay" id="batchArchiveOv" onclick="if(event.target===this)closeBatchArchive()"><div class="archive-chips"><h3>批量归档 ' + ids.length + ' 篇 — 选择原因 <span style="font-size:11px;color:var(--text3);font-weight:400">快捷键 1-7</span></h3><div class="chip-grid">';
  chips.forEach(function(c) {
        html += '<div class="chip" data-reason="' + c.value + '" onclick="selectBatchReason(this,\x27' + c.value + '\x27,' + ids.length + ')">' + c.label + '</div>';
  });
  html += `</div><div class="archive-custom"><label>手动输入理由</label><div class="archive-custom-row"><input id="batchArchiveCustomReason" type="text" placeholder="例如：同源重复、卡片价值不足、图片错配..." oninput="toggleBatchArchiveReady()" onkeydown="if(event.key==='Enter')confirmBatchArchive(${JSON.stringify(ids)})"></div></div><div style="margin-top:16px;text-align:right"><button class="btn btn-red" id="btnConfirmBatchArchive" disabled onclick="confirmBatchArchive(${JSON.stringify(ids)})">确认归档</button></div></div></div>`;
  var div = document.createElement('div');
  div.innerHTML = html;
  document.body.appendChild(div.firstElementChild);

  // Keyboard shortcuts
  var onKey = function(e) {
    var idx = parseInt(e.key) - 1;
    if (idx >= 0 && idx < chips.length) {
      var el = document.querySelector('#batchArchiveOv .chip[data-reason="' + chips[idx].value + '"]');
      if (el) selectBatchReason(el, chips[idx].value, ids.length);
    }
  };
  document.addEventListener('keydown', onKey, {once: true});
  document.getElementById('batchArchiveOv')._onKey = onKey;
}

var _batchReason = '';
function selectBatchReason(el, reason, count) {
  document.querySelectorAll('#batchArchiveOv .chip').forEach(function(c) { c.classList.remove('selected'); });
  el.classList.add('selected');
  _batchReason = reason;
  const input = document.getElementById('batchArchiveCustomReason');
  if (input) input.value = '';
  toggleBatchArchiveReady();
}

function toggleBatchArchiveReady() {
  const btn = document.getElementById('btnConfirmBatchArchive');
  const input = document.getElementById('batchArchiveCustomReason');
  const customReason = input && input.value ? input.value.trim() : '';
  if (btn) btn.disabled = !(_batchReason || customReason);
}

function closeBatchArchive() {
  var ov = document.getElementById('batchArchiveOv');
  if (ov && ov._onKey) document.removeEventListener('keydown', ov._onKey);
  if (ov) ov.remove();
  _batchReason = '';
}

async function confirmBatchArchive(ids) {
  const input = document.getElementById('batchArchiveCustomReason');
  const reason = input && input.value && input.value.trim() ? input.value.trim() : _batchReason;
  if (!reason) return alert('请选择或输入归档理由');
  closeBatchArchive();
  await api('/api/batch-review', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ids, status:'rejected', archive_reason:reason})});
  articleBatchSelectedIds.clear();
  articleBatchMode = false;
  await refreshData();
}

async function runArticleDetailAction(id, context, opts) {
  if (opts.confirmText && !confirm(opts.confirmText)) return;
  const body = document.getElementById('modalBody');
  body.innerHTML += '<div class="analyzing"><div class="dot"></div><div class="dot"></div><div class="dot"></div><span style="color:var(--gold);font-size:13px">' + escapeHtml(opts.loadingText) + '</span></div>';
  const r = await api(opts.url, {method:'POST'});
  if (r.ok) { openDetail(id, context); }
  else { body.innerHTML += `<div style="color:var(--red);margin-top:8px;font-size:12px">${escapeHtml(opts.errorLabel)}: ${escapeHtml(r.error||'未知错误')}</div>`; }
}

async function rerunArticleSummary(id, context) {
  await runArticleDetailAction(id, context, {
    url: '/api/articles/' + id + '/rerun-summary',
    loadingText: '正在重跑摘要，请稍候...',
    errorLabel: '摘要重跑失败',
    confirmText: '重跑摘要只会覆盖这篇文章的中文摘要，不会改分类、评分、档位或卡片。确认继续？'
  });
}

async function translateArticleContent(id, context) {
  await runArticleDetailAction(id, context, {
    url: '/api/articles/' + id + '/translate-content',
    loadingText: '正在补全文翻译，请稍候...',
    errorLabel: '补全文翻译失败',
    confirmText: '补全文翻译只会覆盖这篇文章的正文中文详译，不会改摘要、分类、评分、档位或卡片。确认继续？'
  });
}

// ===== 周报 =====
async function loadReportStatus() {
  const stats = await api('/api/stats');
  document.getElementById('reportStatus').innerHTML = `日报候选 <b style="color:var(--gold)">${stats.candidate || 0}</b> 篇文章可供生成 H5 日报`;
  // 更新分类标签数量
  if (stats.category_counts) {
    document.querySelectorAll('.filter-tab[data-cat]').forEach(function(tab) {
      var cat = tab.dataset.cat;
      var count = stats.category_counts[cat] || 0;
      if (count > 0 && tab.textContent.indexOf(' (') === -1) {
        tab.textContent += ' (' + count + ')';
      }
    });
  }
}

// ===== 组刊工作台 =====
let candidateArticles = [];
let selectedArticles = [];
let draggedIdx = -1;

function parseMaybeJson(value, fallback) {
  if (fallback === undefined) fallback = {};
  if (!value) return fallback;
  if (typeof value === 'object') return value;
  try { return JSON.parse(value); } catch(e) { return fallback; }
}

function cardReasonLabel(reason) {
  const labels = {
    missing_card: '缺完整card_json',
    incomplete_card: '缺完整card_json',
    editor_confidence_low: '低置信',
    example_similarity: '疑似套用示例',
    person_ref_leak: '人称泄漏',
    forbidden_hit: '违禁词命中',
    internal_marker: '含内部编号',
    date_year_mismatch: '年份疑似写错',
    card_api_failed: '成卡失败',
    card_exception: '成卡异常',
    manual_approved: '人工通过'
  };
  if (reason && reason.indexOf('date_year_mismatch') === 0) return '年份疑似写错';
  return labels[reason] || reason || '';
}

function cardReadiness(a) {
  const pending = a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true;
  const flagged = a.summary_flagged === 1 || a.summary_flagged === '1' || a.summary_flagged === true;
  if (pending) return {ready:false,status:'article_blocked',label:'文章待人工',reason:'待人工'};
  if (flagged) return {ready:false,status:'article_blocked',label:'文章待人工',reason:'摘要待审'};
  const card = parseMaybeJson(a.card_json, {});
  const complete = !!(card && card.body && card.deep_dive);
  const st = String(a.card_status || '').trim();
  const reason = String(a.card_review_reason || '').trim();
  if (!complete) {
    if (st === 'failed') return {ready:false,status:'failed',label:'成卡失败',reason:cardReasonLabel(reason) || '成卡失败'};
    return {ready:false,status:'none',label:'待成卡',reason:'缺完整card_json'};
  }
  if (st === 'approved') return {ready:true,status:'approved',label:'人工通过',reason:cardReasonLabel(reason)};
  if (st === 'needs_rewrite') return {ready:false,status:'needs_rewrite',label:'卡待重写',reason:cardReasonLabel(reason) || '低置信'};
  if (st === 'date_risk') return {ready:false,status:'date_risk',label:'日期风险',reason:cardReasonLabel(reason) || '年份疑似写错'};
  if (st === 'failed') return {ready:false,status:'failed',label:'成卡失败',reason:cardReasonLabel(reason) || '成卡失败'};
  if (card.editor_confidence === 'low') return {ready:false,status:'needs_rewrite',label:'卡待重写',reason:'低置信'};
  return {ready:true,status:'ready',label:st === 'ready' ? '可入刊' : '旧卡可复用',reason:cardReasonLabel(reason)};
}

function cardReadinessSummary(articles) {
  const counts = {ready:0, approved:0, none:0, needs_rewrite:0, date_risk:0, failed:0, article_blocked:0, not_ready:0, total:articles.length};
  articles.forEach(a => {
    const r = cardReadiness(a);
    if (r.ready) {
      counts.ready++;
      if (r.status === 'approved') counts.approved++;
    } else {
      counts.not_ready++;
      counts[r.status] = (counts[r.status] || 0) + 1;
    }
  });
  return counts;
}

function selectedArticleById(id) {
  return selectedArticles.find(a => Number(a.id) === Number(id)) || null;
}

function updateSelectedArticle(article) {
  if (!article || !article.id) return;
  const idx = selectedArticles.findIndex(a => Number(a.id) === Number(article.id));
  if (idx >= 0) selectedArticles[idx] = article;
}

function cardListText(value) {
  if (Array.isArray(value)) return value.filter(Boolean).join('\n');
  if (typeof value === 'string') return value;
  return '';
}

function renderCardPreviewSection(title, value, cls) {
  const text = cardListText(value);
  if (!text) return '';
  return '<div class="wb-card-preview-section">' +
    '<div class="modal-section-title">' + escapeHtml(title) + '</div>' +
    '<div class="' + (cls || 'modal-section-body') + '">' + escapeHtml(text).replace(/\n/g,'<br>') + '</div>' +
  '</div>';
}

function fallbackVisibleImages(imgs) {
  const mapped = asArray(imgs).map(imageSrc).filter(Boolean);
  return {
    cover: mapped[0] || '',
    gallery: mapped.slice(1, 5),
    visible: mapped.slice(0, 5),
    raw_count: mapped.length,
    existing_count: mapped.length,
    filtered_count: 0
  };
}

function renderWorkbenchVisibleImages(visibleImages) {
  const cover = visibleImages && visibleImages.cover ? visibleImages.cover : '';
  const gallery = asArray(visibleImages && visibleImages.gallery);
  if (!cover && !gallery.length) {
    return '<div class="wb-card-preview-section"><div class="modal-section-title">H5 可见图片</div><div class="wb-card-preview-empty">没有可预览图片。最终日报会使用频道占位样式。</div></div>';
  }
  let html = '<div class="wb-card-preview-section">';
  html += '<div class="modal-section-title">H5 可见图片</div>';
  html += '<div class="wb-visible-image-note">按最终日报口径筛选：封面 + 最多 4 张展开图。';
  if (visibleImages && visibleImages.raw_count != null) {
    html += ' 原始抓取 ' + Number(visibleImages.raw_count || 0) + ' 张';
    if (visibleImages.filtered_count) html += '，已过滤 ' + Number(visibleImages.filtered_count || 0) + ' 张';
  }
  html += '</div>';
  html += '<div class="wb-visible-images">';
  if (cover) {
    html += `<figure class="wb-visible-image is-cover"><img src="${escapeHtml(cover)}" loading="lazy" onerror="this.style.display='none'"><figcaption>封面</figcaption></figure>`;
  }
  gallery.forEach((img, idx) => {
    html += `<figure class="wb-visible-image"><img src="${escapeHtml(img)}" loading="lazy" onerror="this.style.display='none'"><figcaption>展开图 ${idx + 1}</figcaption></figure>`;
  });
  html += '</div></div>';
  return html;
}

async function openWorkbenchCard(id) {
  let article = selectedArticleById(id);
  let visibleImages = null;
  try {
    const [fresh, visible] = await Promise.all([
      api('/api/articles/' + id),
      api('/api/articles/' + id + '/visible-images')
    ]);
    if (fresh && !fresh.error) {
      article = fresh;
      updateSelectedArticle(fresh);
    }
    if (visible && !visible.error) visibleImages = visible;
  } catch(e) {
    console.warn(e);
  }
  if (!article) {
    alert('文章不在本期列表中');
    return;
  }

  const card = parseMaybeJson(article.card_json, {});
  const readiness = cardReadiness(article);
  const imgs = asArray(article.images);
  if (!visibleImages) visibleImages = fallbackVisibleImages(imgs);
  const complete = !!(card && card.body && card.deep_dive);
  const statusHtml = '<span class="wb-card-status ' + readiness.status + '">' +
    escapeHtml(readiness.label) + (readiness.reason ? ' · ' + escapeHtml(readiness.reason) : '') + '</span>';
  document.getElementById('modal').classList.add('workbench-card-preview-shell');
  document.getElementById('modal').classList.remove('card-edit-modal-shell');
  document.getElementById('modalHero').innerHTML = visibleImages.cover
    ? "<img class=\"modal-hero wb-card-preview-hero\" src=\"" + escapeHtml(visibleImages.cover) + "\" onerror=\"this.style.display='none'\">"
    : '';

  let body = '<div class="wb-card-preview">';
  body += '<div class="modal-meta"><span class="tier-badge tier-' + escapeHtml(article.gate2_tier || 'C') + '">' + escapeHtml(article.gate2_tier || 'C') + '档</span>' + statusHtml + '</div>';
  body += '<h2 class="modal-title">' + escapeHtml(card.headline || article.translated_title || article.title || '') + '</h2>';
  body += '<div class="wb-card-preview-sub">' + escapeHtml(article.category || '') + (article.source ? ' · ' + escapeHtml(article.source) : '') + '</div>';
  body += renderWorkbenchVisibleImages(visibleImages);
  if (!complete) {
    body += '<div class="wb-card-preview-empty">这篇还没有完整卡片。可以先点“重成此卡”，只重跑这一篇。</div>';
  } else {
    if (card.one_line) body += '<div class="one-line-hook">' + escapeHtml(card.one_line) + '</div>';
    body += renderCardPreviewSection('推荐文案', card.body, 'modal-section-body');
    body += renderCardPreviewSection('深挖信息', card.deep_dive, 'modal-fulltext');
    body += renderCardPreviewSection('安排建议', card.arrangement, 'scenario-box');
    body += renderCardPreviewSection('适合理由', card.fit_reasons, 'modal-section-body');
    body += renderCardPreviewSection('注意事项', card.cautions, 'modal-section-body');
    if (card.editor_confidence) {
      body += '<div class="wb-card-preview-section"><div class="modal-section-title">AI 自评</div><div class="modal-section-body">' + escapeHtml(card.editor_confidence) + '</div></div>';
    }
  }
  body += '<a class="modal-link" href="' + escapeHtml(article.url || '') + '" target="_blank">' + escapeHtml(article.url || '') + '</a>';
  body += '</div>';
  document.getElementById('modalBody').innerHTML = body;

  let footer = '<button class="btn btn-outline" onclick="closeModal()">关闭</button>';
  footer += '<button class="btn btn-outline" id="btnSingleCardRegen" onclick="rerunSingleCard(' + Number(id) + ',this)">重成此卡</button>';
  if (!readiness.ready && complete && !article.pending_human && !article.summary_flagged) {
    footer += '<button class="btn btn-gold" onclick="approveCard(' + Number(id) + ')">人工通过</button>';
  }
  document.getElementById('modalFooter').innerHTML = footer;
  document.getElementById('modalBg').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function syncSelectedArticlesFromPool() {
  if (!selectedArticles.length || !candidateArticles.length) return;
  const byId = new Map(candidateArticles.map(a => [a.id, a]));
  selectedArticles = selectedArticles.map(a => byId.get(a.id) || a);
}

async function refreshSelectedArticles() {
  if (!selectedArticles.length) return;
  const refreshed = await Promise.all(selectedArticles.map(a => api('/api/articles/' + a.id)));
  selectedArticles = selectedArticles.map((a, idx) => refreshed[idx] || a);
}

async function loadWorkbench() {
  const container = document.getElementById('candidatePool');
  container.innerHTML = '<div class="wb-loading">加载中...</div>';
  try {
    const pool = await api('/api/candidate-pool');
    if (pool === null) {
      container.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败，请刷新重试</div>';
      return;
    }
    if (!Array.isArray(pool)) throw new Error('Invalid response');
    candidateArticles = pool;
    syncSelectedArticlesFromPool();
    renderCandidatePool();
    renderIssuePanel();
  } catch(e) { console.error(e);
    container.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败: ' + e.message + '<br><button class="btn btn-outline btn-sm" style="margin-top:12px" onclick="loadWorkbench()">重试</button></div>';
  }
}

function renderCandidatePool() {
  const container = document.getElementById('candidatePool');
  const selectedIds = new Set(selectedArticles.map(a => a.id));

  const groups = {};
  candidateArticles.forEach(a => {
    const cat = a.category || '未分类';
    if (!groups[cat]) groups[cat] = [];
    groups[cat].push(a);
  });

  for (const cat of Object.keys(groups)) {
    groups[cat].sort((a, b) => {
      const aCarry = (a.carryover_count || 0) > 0 ? 0 : 1;
      const bCarry = (b.carryover_count || 0) > 0 ? 0 : 1;
      if (aCarry !== bCarry) return aCarry - bCarry;
      const tierOrder = {'A':0,'B':1,'C':2,'D':3};
      const aTier = tierOrder[a.gate2_tier] || 2;
      const bTier = tierOrder[b.gate2_tier] || 2;
      if (aTier !== bTier) return aTier - bTier;
      return (b.reviewed_at || '').localeCompare(a.reviewed_at || '');
    });
  }

  let html = '<div class="wb-candidate-list">';
  const sortedCats = Object.keys(groups).sort();
  for (const cat of sortedCats) {
    const articles = groups[cat];
    html += '<div class="wb-channel-header">' + escapeHtml(cat) + ' · ' + articles.length + ' 篇</div>';
    articles.forEach(a => {
      const isSel = selectedIds.has(a.id);
      const imgs = asArray(a.images);
      const thumb = imgs.length ? imageSrc(imgs[0]) : '';
      const carryover = (a.carryover_count || 0) > 0 ? '<span class="carryover-badge">顺延×' + a.carryover_count + '</span>' : '';
      const evergreen = a.evergreen ? '<span class="evergreen-tag">常青</span>' : '';
      html += '<div class="feed-item' + (isSel ? ' selected' : '') + '" id="cand-' + a.id + '" onclick="openWorkbenchArticleDetail(' + a.id + ')">' +
        (thumb ? '<img class="feed-thumb" src="' + escapeHtml(thumb) + '" loading="lazy" onerror="this.outerHTML=\'<div class=feed-thumb-empty></div>\'">' : '<div class="feed-thumb-empty"></div>') +
        '<div class="feed-main">' +
          '<div class="feed-meta">' +
            '<span class="cat-tag">' + (CAT_EMOJI[a.category]||'') + ' ' + escapeHtml(a.category||'') + '</span>' +
            (a.gate2_tier ? '<span class="tier-badge tier-' + a.gate2_tier + '" style="font-size:9px;padding:1px 5px">' + a.gate2_tier + '档</span>' : '') +
            carryover + evergreen +
          '</div>' +
          '<div class="feed-title">' + escapeHtml(a.translated_title || a.title || '') + '</div>' +
          (a.gate2_one_line ? '<div style="font-size:11px;color:var(--text2);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' + escapeHtml(a.gate2_one_line) + '</div>' : '') +
          '<div class="feed-meta" style="margin-top:4px">' + escapeHtml(a.source||'') + ' · ' + escapeHtml((a.crawled_at||'').slice(0,10)) + '</div>' +
        '</div>' +
        '<button class="wb-select-btn' + (isSel?' selected':'') + '" onclick="event.stopPropagation();toggleArticle(' + a.id + ')">' + (isSel?'已选 ✓':'选入 →') + '</button>' +
      '</div>';
    });
  }
  html += '</div>';
  container.innerHTML = html || '<div class="wb-empty" style="padding:40px;text-align:center;color:var(--text3)">暂无候选文章</div>';
  document.getElementById('candidateCount').textContent = candidateArticles.length + ' 篇';
}

function toggleArticle(id) {
  const idx = selectedArticles.findIndex(a => a.id === id);
  if (idx >= 0) {
    selectedArticles.splice(idx, 1);
  } else {
    const article = candidateArticles.find(a => a.id === id);
    if (article) {
      selectedArticles.push(article);
    }
  }
  renderCandidatePool();
  renderIssuePanel();
}

function removeFromIssue(id) {
  selectedArticles = selectedArticles.filter(a => a.id !== id);
  renderCandidatePool();
  renderIssuePanel();
}

function renderIssuePanel() {
  const container = document.getElementById('issueArticles');
  const count = selectedArticles.length;
  document.getElementById('issueCount').textContent = count + ' 篇';
  const cardCounts = cardReadinessSummary(selectedArticles);

  // Channel distribution
  const catCount = {};
  selectedArticles.forEach(a => {
    const cat = a.category || '未分类';
    catCount[cat] = (catCount[cat] || 0) + 1;
  });

  const allCats = ['精品酒店与度假','旅行与探索','美食与美酒','艺术与文化','建筑与空间','产品与设计','时尚与风格','珠宝与腕表','汽车与出行','科技与生活','健康与养生','音乐与演出'];
  let channelHtml = '';
  allCats.forEach(cat => {
    const cnt = catCount[cat] || 0;
    const cls = cnt === 0 ? 'channel-mini channel-zero' : 'channel-mini';
    channelHtml += '<span class="' + cls + '">' + cat + ' ' + cnt + '</span>';
  });
  document.getElementById('issueChannelStats').innerHTML = channelHtml;
  let cardStatsHtml = '';
  if (count > 0) {
    cardStatsHtml += '<span class="card-mini ready">可入刊 ' + cardCounts.ready + '</span>';
    if (cardCounts.none) cardStatsHtml += '<span class="card-mini warn">待成卡 ' + cardCounts.none + '</span>';
    if (cardCounts.needs_rewrite) cardStatsHtml += '<span class="card-mini warn">待重写 ' + cardCounts.needs_rewrite + '</span>';
    if (cardCounts.date_risk) cardStatsHtml += '<span class="card-mini warn">日期风险 ' + cardCounts.date_risk + '</span>';
    if (cardCounts.failed) cardStatsHtml += '<span class="card-mini fail">失败 ' + cardCounts.failed + '</span>';
    if (cardCounts.article_blocked) cardStatsHtml += '<span class="card-mini fail">文章待审 ' + cardCounts.article_blocked + '</span>';
  }
  document.getElementById('issueCardStats').innerHTML = cardStatsHtml;

  // Count warning
  const warnEl = document.getElementById('issueCountWarning');
  if (count === 0) {
    warnEl.innerHTML = '<span style="color:var(--text3)">请从左侧选择文章</span>';
  } else if (count < 15) {
    warnEl.innerHTML = '<span class="warn-low">已选 ' + count + ' 篇（目标 15–25）</span>';
  } else if (count > 25) {
    warnEl.innerHTML = '<span class="warn-high">已选 ' + count + ' 篇（超过建议上限）</span>';
  } else {
    warnEl.innerHTML = '<span style="color:#4a7c59">已选 ' + count + ' 篇 ✓</span>';
  }

  // Enable/disable action buttons
  const btnPrepare = document.getElementById('btnPrepareCards');
  const btnRetry = document.getElementById('btnRetryCards');
  const btn = document.getElementById('btnGenerateIssue');
  btnPrepare.disabled = count === 0;
  btnRetry.disabled = count === 0 || cardCounts.not_ready === 0;
  if (count === 0) {
    btn.disabled = true;
  } else if (cardCounts.not_ready > 0) {
    btn.disabled = true;
    btn.title = '请先成卡/重成卡/人工通过未就绪卡片';
  } else {
    btn.disabled = false;
    btn.title = '';
  }

  if (!count) {
    container.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text3);font-size:13px">从左侧候选池选择文章加入本期</div>';
  } else {
    let html = '<div class="wb-selected-list">';
    selectedArticles.forEach((a, i) => {
      const imgs = asArray(a.images);
      const thumb = imgs.length ? imageSrc(imgs[0]) : '';
      const r = cardReadiness(a);
      const statusClass = r.status.replace(/_/g, '_');
      const approveBtn = (!r.ready && (r.status === 'needs_rewrite' || r.status === 'date_risk' || r.status === 'failed') && parseMaybeJson(a.card_json, {}).body && parseMaybeJson(a.card_json, {}).deep_dive)
        ? '<button class="wb-card-action" onclick="event.stopPropagation();approveCard(' + a.id + ')">人工通过</button>'
        : '';
      const actionBtns = '<div class="wb-card-actions">' +
        '<button class="wb-card-action" onclick="event.stopPropagation();openWorkbenchCard(' + a.id + ')">预览</button>' +
        '<button class="wb-card-action" onclick="event.stopPropagation();rerunSingleCard(' + a.id + ',this)">重成</button>' +
        approveBtn +
        '</div>';
      html += '<div class="wb-selected-item" draggable="true" data-idx="' + i + '" ' +
        'onclick="openWorkbenchCard(' + a.id + ')" ' +
        'ondragstart="handleDragStart(event,' + i + ')" ' +
        'ondragover="handleDragOver(event)" ' +
        'ondrop="handleDrop(event,' + i + ')" ' +
        'ondragend="handleDragEnd()">' +
        '<span style="color:var(--text3);font-size:9px;min-width:14px;text-align:center">' + (i+1) + '</span>' +
        (thumb ? '<img class="wb-sel-thumb" src="' + escapeHtml(thumb) + '" loading="lazy" onerror="this.style.display=\'none\'">' : '<div class="wb-sel-thumb"></div>') +
        '<div class="wb-sel-info">' +
          '<div class="wb-sel-title">' + escapeHtml(a.translated_title || a.title || '') + '</div>' +
          '<div class="wb-sel-meta">' + (a.gate2_tier||'') + '档 · ' + escapeHtml(a.category||'') +
            '<span class="wb-card-status ' + statusClass + '">' + escapeHtml(r.label) + (r.reason ? ' · ' + escapeHtml(r.reason) : '') + '</span></div>' +
        '</div>' +
        actionBtns +
        '<button class="remove-btn" onclick="event.stopPropagation();removeFromIssue(' + a.id + ')">×</button>' +
      '</div>';
    });
    html += '</div>';
    container.innerHTML = html;
  }
}

function handleDragStart(e, idx) {
  draggedIdx = idx;
  e.target.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', idx);
}
function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
}
function handleDrop(e, targetIdx) {
  e.preventDefault();
  if (draggedIdx >= 0 && draggedIdx !== targetIdx) {
    const [item] = selectedArticles.splice(draggedIdx, 1);
    selectedArticles.splice(targetIdx, 0, item);
    renderIssuePanel();
  }
  draggedIdx = -1;
}
function handleDragEnd() {
  draggedIdx = -1;
  document.querySelectorAll('.wb-selected-item.dragging').forEach(el => el.classList.remove('dragging'));
}

async function pollWorkbenchTask(taskId, button, idleLabel, doneHandler) {
  const poll = setInterval(async () => {
    try {
      const r = await fetch('/api/task-status/' + taskId);
      const t = await r.json();
      if (!t.ok) return;
      button.textContent = (t.status_text || '处理中...') + ' (' + (t.progress || 0) + '%)';
      if (t.status === 'done') {
        clearInterval(poll);
        button.disabled = false;
        button.textContent = idleLabel;
        await doneHandler(t.result || {});
        renderIssuePanel();
      } else if (t.status === 'error') {
        clearInterval(poll);
        alert('任务失败: ' + (t.error || '未知错误'));
        button.disabled = false;
        button.textContent = idleLabel;
        renderIssuePanel();
      }
    } catch(e) {
      clearInterval(poll);
      alert('任务状态查询失败: ' + e.message);
      button.disabled = false;
      button.textContent = idleLabel;
      renderIssuePanel();
    }
  }, 2000);
}

async function prepareCards(mode) {
  if (!selectedArticles.length) {
    alert('请先从候选池选择文章');
    return;
  }
  const btn = document.getElementById(mode === 'not_ready' ? 'btnRetryCards' : 'btnPrepareCards');
  const idleLabel = mode === 'not_ready' ? '重成未就绪' : '成卡';
  btn.disabled = true;
  btn.textContent = '提交中...';
  try {
    const res = await fetch('/api/prepare-cards-async', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({article_ids: selectedArticles.map(a => a.id), mode})
    });
    const data = await res.json();
    if (!data.ok) {
      alert('成卡提交失败: ' + (data.error || '未知错误'));
      btn.disabled = false;
      btn.textContent = idleLabel;
      renderIssuePanel();
      return;
    }
    await pollWorkbenchTask(data.task_id, btn, idleLabel, async (result) => {
      await loadWorkbench();
      await refreshSelectedArticles();
      const counts = (result.readiness && result.readiness.counts) || {};
      alert('成卡完成\n可入刊: ' + (counts.ready || 0) + ' 篇\n未就绪: ' + (counts.not_ready || 0) + ' 篇');
    });
  } catch(e) {
    alert('成卡请求失败: ' + e.message);
    btn.disabled = false;
    btn.textContent = idleLabel;
    renderIssuePanel();
  }
}

async function rerunSingleCard(id, btn) {
  const article = selectedArticleById(id);
  const title = article ? (article.translated_title || article.title || '') : ('#' + id);
  if (!confirm('只重成这一张卡？\n\n' + title)) return;
  const button = btn || document.getElementById('btnSingleCardRegen');
  const idleLabel = button ? button.textContent : '重成';
  if (button) {
    button.disabled = true;
    button.textContent = '提交中...';
  }
  try {
    const res = await fetch('/api/prepare-card-async/' + id, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (!data.ok) {
      alert('单卡重成提交失败: ' + (data.error || '未知错误'));
      if (button) {
        button.disabled = false;
        button.textContent = idleLabel;
      }
      return;
    }
    const taskId = data.task_id;
    const poll = setInterval(async () => {
      try {
        const r = await fetch('/api/task-status/' + taskId);
        const t = await r.json();
        if (!t.ok) return;
        if (button) button.textContent = (t.status_text || '处理中...') + ' (' + (t.progress || 0) + '%)';
        if (t.status === 'done') {
          clearInterval(poll);
          await refreshSelectedArticles();
          renderIssuePanel();
          if (button) {
            button.disabled = false;
            button.textContent = idleLabel;
          }
          if (document.getElementById('modalBg').classList.contains('open')) {
            await openWorkbenchCard(id);
          } else {
            alert('单卡重成完成');
          }
        } else if (t.status === 'error') {
          clearInterval(poll);
          alert('单卡重成失败: ' + (t.error || '未知错误'));
          if (button) {
            button.disabled = false;
            button.textContent = idleLabel;
          }
        }
      } catch(e) {
        clearInterval(poll);
        alert('任务状态查询失败: ' + e.message);
        if (button) {
          button.disabled = false;
          button.textContent = idleLabel;
        }
      }
    }, 2000);
  } catch(e) {
    alert('单卡重成请求失败: ' + e.message);
    if (button) {
      button.disabled = false;
      button.textContent = idleLabel;
    }
  }
}

async function approveCard(id) {
  if (!confirm('确认这张卡人工通过并允许入刊？')) return;
  const res = await fetch('/api/article-card-status/' + id, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({status: 'approved'})
  });
  const data = await res.json();
  if (!data.ok) {
    alert('人工通过失败: ' + (data.error || '未知错误'));
    return;
  }
  await loadWorkbench();
  await refreshSelectedArticles();
  renderIssuePanel();
  if (document.getElementById('modalBg').classList.contains('open')) {
    await openWorkbenchCard(id);
  }
}

async function generateIssue() {
  if (!selectedArticles.length) {
    alert('请先从候选池选择文章');
    return;
  }
  const cardCounts = cardReadinessSummary(selectedArticles);
  if (cardCounts.not_ready > 0) {
    alert('还有 ' + cardCounts.not_ready + ' 篇卡片未就绪，请先成卡/重成卡/人工通过。');
    return;
  }

  const catCount = {};
  selectedArticles.forEach(a => {
    const cat = a.category || '未分类';
    catCount[cat] = (catCount[cat] || 0) + 1;
  });
  let confirmMsg = '确认组刊生成日报？\n\n共 ' + selectedArticles.length + ' 篇\n';
  Object.entries(catCount).sort((a,b)=>b[1]-a[1]).forEach(([cat, cnt]) => {
    confirmMsg += '  ' + cat + ': ' + cnt + '\n';
  });
  if (!confirm(confirmMsg)) return;

  const btn = document.getElementById('btnGenerateIssue');
  btn.disabled = true;
  btn.textContent = '提交中...';

  try {
    const res = await fetch('/api/generate-issue-async', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({article_ids: selectedArticles.map(a => a.id)})
    });
    const data = await res.json();
    if (!data.ok) {
      alert('提交失败: ' + (data.error || '未知错误'));
      btn.disabled = false;
      btn.textContent = '组刊生成日报';
      renderIssuePanel();
      return;
    }

    await pollWorkbenchTask(data.task_id, btn, '组刊生成日报', async (result) => {
      let msg = formatIssueLabel(result.issue_number) + ' 已生成！';
      if (result.article_count) msg += '\n入刊文章: ' + result.article_count + ' 篇';
      alert(msg);
      selectedArticles = [];
      await loadWorkbench();
      loadDashboard();
    });
  } catch(e) {
    alert('请求失败: ' + e.message);
    btn.disabled = false;
    btn.textContent = '组刊生成日报';
    renderIssuePanel();
  }
}

async function openEvergreenModal() {
  const container = document.getElementById('modalBody');
  document.getElementById('modal').classList.remove('card-edit-modal-shell');
  container.innerHTML = '<div class="wb-loading">加载中...</div>';
  document.getElementById('modalHero').innerHTML = '';
  document.getElementById('modalFooter').innerHTML = '<button class="btn btn-outline" onclick="closeModal()">关闭</button>';
  document.getElementById('modalBg').classList.add('open');
  document.body.style.overflow = 'hidden';

  try {
    const pool = await api('/api/evergreen-pool');
    evergreenModalPool = Array.isArray(pool) ? pool : [];
    let listHtml = '';
    evergreenModalPool.forEach(a => {
      const imgs = asArray(a.images);
      const thumb = imgs.length ? imageSrc(imgs[0]) : '';
      const selected = !!selectedArticles.find(x => x.id === a.id);
      listHtml += '<div class="feed-item" id="evergreen-item-' + a.id + '" onclick="addFromEvergreen(' + a.id + ')">' +
        (thumb ? '<img class="feed-thumb" src="' + escapeHtml(thumb) + '" loading="lazy" onerror="this.outerHTML=\'<div class=feed-thumb-empty></div>\'">' : '<div class="feed-thumb-empty"></div>') +
        '<div class="feed-main">' +
          '<div class="feed-meta">' +
            '<span class="cat-tag">' + (CAT_EMOJI[a.category]||'') + ' ' + escapeHtml(a.category || '') + '</span>' +
            (a.gate2_tier ? '<span class="tier-badge tier-' + a.gate2_tier + '" style="font-size:9px;padding:1px 5px">' + a.gate2_tier + '档</span>' : '') +
            (a.carryover_count ? '<span class="carryover-badge">顺延×' + a.carryover_count + '</span>' : '') +
          '</div>' +
          '<div class="feed-title">' + escapeHtml(a.translated_title || a.title || '') + '</div>' +
          (a.gate2_one_line || a.summary ? '<div style="font-size:11px;color:var(--text2);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' + escapeHtml(a.gate2_one_line || a.summary || '') + '</div>' : '') +
          '<div class="feed-meta" style="margin-top:4px">' + escapeHtml(a.source || '') + ' · ' + escapeHtml((a.crawled_at || '').slice(0,10)) + '</div>' +
        '</div>' +
        '<button class="wb-select-btn" id="evergreen-btn-' + a.id + '" onclick="event.stopPropagation();addFromEvergreen(' + a.id + ')">' + (selected ? '已选 ✓' : '选入 →') + '</button>' +
      '</div>';
    });
    container.innerHTML = '<h3 style="font-size:16px;margin-bottom:12px">常青库</h3><div class="evergreen-modal-list">' + (listHtml || '<div class="wb-empty">暂无常青文章</div>') + '</div>';
  } catch(e) { console.error(e);
    container.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败</div>';
  }
}

async function addFromEvergreen(id) {
  if (selectedArticles.find(a => a.id === id)) {
    markEvergreenSelected(id);
    return;
  }
  const article = evergreenModalPool.find(a => a.id === id);
  if (article) {
    const res = await api('/api/review', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({id, status:'candidate'})
    });
    if (!res || res.ok === false) {
      alert((res && res.error) || '加入候选失败');
      return;
    }
    article.status = 'candidate';
    article.evergreen = false;
    selectedArticles.push(article);
    if (!candidateArticles.find(a => a.id === id)) candidateArticles.push(article);
    evergreenModalPool = evergreenModalPool.filter(a => a.id !== id);
    const local = allArticles.find(a => a.id === id);
    if (local) {
      local.status = 'candidate';
      local.evergreen = false;
    }
    renderIssuePanel();
    renderCandidatePool();
    markEvergreenSelected(id);
  }
}

function markEvergreenSelected(id) {
  const btn = document.getElementById('evergreen-btn-' + id);
  if (btn) btn.textContent = '已选 ✓';
  const item = document.getElementById('evergreen-item-' + id);
  if (item) item.remove();
}

async function toggleEvergreenFromModal(id) {
  const a = await api('/api/articles/' + id);
  const newVal = !a.evergreen;
  const res = await fetch('/api/mark-evergreen', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: id, evergreen: newVal})
  });
  const data = await res.json();
  if (!data.ok) {
    alert(data.error || '标记常青失败');
    return;
  }
  const btn = document.getElementById('evergreenBtn');
  if (btn) btn.textContent = data.evergreen ? '★ 已常青' : '☆ 标记常青';
  const local = allArticles.find(x => x.id === id);
  if (local) local.evergreen = data.evergreen;
  await refreshData();
  if (typeof loadWorkbench === 'function') loadWorkbench();
}

async function toggleEvergreen(id) {
  const a = await api('/api/articles/' + id);
  const newVal = !a.evergreen;
  const res = await fetch('/api/mark-evergreen', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: id, evergreen: newVal})
  });
  const data = await res.json();
  if (!data.ok) {
    alert(data.error || '标记常青失败');
    return;
  }
  const local = allArticles.find(x => x.id === id);
  if (local) local.evergreen = data.evergreen;
  await refreshData();
}

// ===== 往期日报 =====
async function regenerateH5(issueId, btn) {
  btn.textContent = '生成中...';
  btn.disabled = true;
  try {
	    const r = await api('/api/regenerate-h5/' + issueId, {method:'POST'});
	    if (r.ok) {
	      btn.textContent = '已更新';
	      btn.disabled = false;
	      loadIssuesList();
	    } else {
      btn.textContent = '失败';
      btn.disabled = false;
      alert('生成失败: ' + (r.error || '未知错误'));
    }
  } catch(e) {
    btn.textContent = '重试';
    btn.disabled = false;
  }
}

async function loadIssuesList() {
  const container = document.getElementById('issuesList');
  container.innerHTML = '<div class="wb-loading">加载中...</div>';
  try {
    const issues = await api('/api/issues');
    if (issues === null) {
      container.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败，请刷新重试</div>';
      return;
    }
    if (!issues || !issues.length) {
      container.innerHTML = '<div class="wb-empty">暂无已生成日报</div>';
      return;
    }
	    let html = '';
	    issueLocks = {};
	    issues.forEach(issue => {
	      const locked = !!issue.locked_at;
	      issueLocks[issue.id] = locked;
	      let issueActions = '';
	      if (issue.html_path) {
	        issueActions += `<a href="/output/${escapeHtml(issue.html_path.split('/').pop())}" target="_blank" class="btn btn-outline btn-sm" onclick="event.stopPropagation()">查看 H5</a>`;
	        issueActions += locked
	          ? `<span class="btn btn-outline btn-sm" style="margin-left:6px;cursor:default;color:var(--green);border-color:var(--green)">已锁定</span>`
	          : `<button class="btn btn-outline btn-sm" style="margin-left:6px" onclick="event.stopPropagation();regenerateH5(${issue.id},this)">重生成 H5</button><button class="btn btn-outline btn-sm" style="margin-left:6px;color:var(--green);border-color:var(--green)" onclick="event.stopPropagation();lockIssue(${issue.id},this)">锁定/已发送</button>`;
	      } else {
	        issueActions += `<button class="btn btn-outline btn-sm" onclick="event.stopPropagation();regenerateH5(${issue.id},this)">生成 H5</button>`;
	      }
	      if (!locked) {
	        issueActions += `<button class="btn btn-outline btn-sm" style="color:var(--red);border-color:var(--red);margin-left:6px" onclick="event.stopPropagation();voidIssue(${issue.id},this)">作废</button>`;
	      }
	      html += '<div class="issue-card" id="issue-' + issue.id + '">' +
	        '<div class="issue-card-header" onclick="toggleIssueDetail(' + issue.id + ')" style="cursor:pointer">' +
	          '<div>' +
	            '<div class="issue-card-title">' + escapeHtml(formatIssueLabel(issue.issue_number)) + '</div>' +
	            '<div class="issue-card-meta">' +
	              '<span>' + escapeHtml(issue.created_date || '') + '</span>' +
	              '<span>' + (issue.article_count || 0) + ' 篇</span>' +
	              '<span>' + (locked ? '已发送锁定' : (issue.status === 'published' ? '已生成' : issue.status === 'voided' ? '已作废' : '草稿')) + '</span>' +
	            '</div>' +
	          '</div>' +
	          '<div>' +
	            issueActions +
	          '</div>' +
        '</div>' +
        '<div class="issue-card-body" id="issue-body-' + issue.id + '"></div>' +
      '</div>';
    });
    container.innerHTML = html;
  } catch(e) { console.error(e);
    container.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败</div>';
  }
}

function formatIssueLabel(issueNumber) {
  const raw = String(issueNumber || '').trim();
  return /^\d+$/.test(raw) ? ('第' + raw + '期') : raw;
}

async function voidIssue(issueId, btn) {
  if (!confirm('确定作废此期刊？文章将退回候选池，卡片缓存保留。')) return;
  btn.disabled = true;
  btn.textContent = '作废中...';
  try {
    const res = await api('/api/void-issue/' + issueId, {method:'POST'});
    if (res.ok) {
      alert('已作废，' + res.count + ' 篇文章退回候选');
      loadIssuesList();
    } else {
      alert('作废失败: ' + (res.error || '未知错误'));
      btn.disabled = false;
      btn.textContent = '作废';
    }
  } catch(e) {
    alert('作废失败: ' + e.message);
    btn.disabled = false;
    btn.textContent = '作废';
  }
}

async function lockIssue(issueId, btn) {
  if (!confirm('确认这期已经发出并锁定？锁定后不能编辑卡片、换图、重生成 H5 或作废。')) return;
  btn.disabled = true;
  btn.textContent = '锁定中...';
  const res = await api('/api/lock-issue/' + issueId, {method:'POST'});
  if (res && res.ok) {
    loadIssuesList();
  } else {
    alert('锁定失败: ' + ((res && res.error) || '未知错误'));
    btn.disabled = false;
    btn.textContent = '锁定/已发送';
  }
}

async function toggleIssueDetail(issueId) {
  const card = document.getElementById('issue-' + issueId);
  const body = document.getElementById('issue-body-' + issueId);
  if (card.classList.contains('open')) {
    collapseIssueDetail(issueId);
    return;
  }
  card.classList.add('open');
  if (body) body.style.display = 'block';
  if (body.innerHTML) return;

  body.innerHTML = '<div class="wb-loading">加载中...</div>';
  try {
    const articles = await api('/api/issue-articles/' + issueId);
    if (!articles || !articles.length) {
      body.innerHTML = '<div class="wb-empty">无文章</div>';
      return;
	    }
	    let html = '<div class="issue-detail-toolbar"><button class="issue-collapse-btn" onclick="event.stopPropagation();collapseIssueDetail(' + issueId + ')">收起列表</button></div>';
	    const locked = !!issueLocks[issueId];
	    articles.forEach((a, i) => {
      var fbLabels = {'checked_asap':'尽快安排','checked_next_trip':'下次顺路','checked':'已勾选','skipped':'已跳过'};
      var fbDetail = a.feedback_detail || '';
      var fbKey = a.dj_feedback + (fbDetail ? '_' + fbDetail : '');
      var fbText = a.dj_feedback ? (fbLabels[fbKey] || fbLabels[a.dj_feedback] || '') : '未操作';
      var fbColor = 'var(--text3)';
      if (a.dj_feedback === 'checked') fbColor = fbDetail === 'next_trip' ? '#1565c0' : '#2e7d32';
      else if (a.dj_feedback === 'skipped') fbColor = '#c62828';
	      var fbHtml = a.dj_feedback ? '<span class="issue-row-feedback" style="color:' + fbColor + '">' + fbText + '</span>' : '';
	      html += '<div class="issue-article-row">' +
	        '<span class="issue-row-index">' + (i+1) + '.</span>' +
          '<div class="issue-row-main">' +
            '<div class="issue-row-title">' + escapeHtml(a.translated_title || a.title || '') + fbHtml + '</div>' +
          '</div>' +
          '<div class="issue-row-actions">' +
            (locked ? '' : '<button class="issue-edit-btn" onclick="openCardEditor(' + issueId + ',' + a.id + ')" title="编辑本期卡片">编辑卡片</button>' +
              '<button class="issue-replace-btn" onclick="openIssueReplaceModal(' + issueId + ',' + a.id + ')" title="从日报候选或常青库替换这一篇">替换本篇</button>') +
            '<div class="issue-feedback-group">' +
              '<button class="dj-fb-btn ' + (a.dj_feedback === 'checked' && fbDetail === 'asap' ? 'active-asap' : '') + '" onclick="setDjFeedback(' + a.id + ',\'checked\',' + issueId + ',\'asap\')" title="DJ尽快安排">尽快</button>' +
              '<button class="dj-fb-btn ' + (a.dj_feedback === 'checked' && fbDetail === 'next_trip' ? 'active-next' : '') + '" onclick="setDjFeedback(' + a.id + ',\'checked\',' + issueId + ',\'next_trip\')" title="DJ下次顺路时安排">顺路</button>' +
              '<button class="dj-fb-btn ' + (a.dj_feedback === 'skipped' ? 'active-skipped' : '') + '" onclick="setDjFeedback(' + a.id + ',\'skipped\',' + issueId + ')" title="DJ跳过此条">跳过</button>' +
            '</div>' +
          '</div>' +
	      '</div>';
	    });
    body.innerHTML = html;
	  } catch(e) { console.error(e);
	    body.innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败</div>';
	  }
		}

function collapseIssueDetail(issueId) {
  const card = document.getElementById('issue-' + issueId);
  if (card) card.classList.remove('open');
  const body = document.getElementById('issue-body-' + issueId);
  if (body) {
    body.innerHTML = '';
    body.style.display = 'none';
  }
}

function refreshIssueDetail(issueId) {
  const issueBody = document.getElementById('issue-body-' + issueId);
  const card = document.getElementById('issue-' + issueId);
  if (issueBody) issueBody.innerHTML = '';
  if (card) card.classList.remove('open');
  if (issueBody) issueBody.style.display = 'none';
  toggleIssueDetail(issueId);
}

async function openIssueReplaceModal(issueId, oldArticleId) {
  issueReplaceState = {
    issueId: Number(issueId),
    oldArticleId: Number(oldArticleId),
    oldTitle: '',
    position: null,
    tab: 'candidate',
    query: '',
    candidate: [],
    evergreen: [],
    issueArticleIds: new Set()
  };
  document.getElementById('modal').classList.remove('card-edit-modal-shell');
  document.getElementById('modal').classList.remove('workbench-card-preview-shell');
  document.getElementById('modalHero').innerHTML = '';
  document.getElementById('modalBody').innerHTML = '<div class="wb-loading">加载中...</div>';
  document.getElementById('modalFooter').innerHTML = '<button class="btn btn-outline" onclick="closeModal()">取消</button>';
  document.getElementById('modalBg').classList.add('open');
  document.body.style.overflow = 'hidden';
  try {
    const [issueArticles, candidatePool, evergreenPool] = await Promise.all([
      api('/api/issue-articles/' + issueId),
      api('/api/candidate-pool'),
      api('/api/evergreen-pool')
    ]);
    const currentIssueArticles = Array.isArray(issueArticles) ? issueArticles : [];
    issueReplaceState.issueArticleIds = new Set(currentIssueArticles.map(a => Number(a.id)));
    const oldIndex = currentIssueArticles.findIndex(a => Number(a.id) === Number(oldArticleId));
    const oldArticle = oldIndex >= 0 ? currentIssueArticles[oldIndex] : null;
    issueReplaceState.position = oldIndex >= 0 ? oldIndex + 1 : null;
    issueReplaceState.oldTitle = oldArticle ? (oldArticle.translated_title || oldArticle.title || '') : '';
    issueReplaceState.candidate = Array.isArray(candidatePool) ? candidatePool : [];
    issueReplaceState.evergreen = Array.isArray(evergreenPool) ? evergreenPool : [];
    renderIssueReplaceModal();
  } catch(e) {
    console.error(e);
    document.getElementById('modalBody').innerHTML = '<div class="wb-empty" style="color:var(--red)">加载失败，请刷新后再试</div>';
  }
}

function setIssueReplaceTab(tab) {
  issueReplaceState.tab = tab === 'evergreen' ? 'evergreen' : 'candidate';
  renderIssueReplaceModal();
}

function updateIssueReplaceSearch(value) {
  issueReplaceState.query = value || '';
  renderIssueReplaceModal();
}

function replacementPoolForTab(tab) {
  const source = tab === 'evergreen' ? issueReplaceState.evergreen : issueReplaceState.candidate;
  const q = (issueReplaceState.query || '').trim().toLowerCase();
  return source.filter(a => {
    const id = Number(a.id);
    if (id === Number(issueReplaceState.oldArticleId)) return false;
    if (issueReplaceState.issueArticleIds.has(id)) return false;
    if (!q) return true;
    const haystack = [
      a.translated_title || '',
      a.title || '',
      a.source || '',
      a.category || '',
      a.gate2_one_line || '',
      a.summary || ''
    ].join(' ').toLowerCase();
    return haystack.indexOf(q) >= 0;
  });
}

function renderIssueReplaceModal() {
  const candidateCount = replacementPoolForTab('candidate').length;
  const evergreenCount = replacementPoolForTab('evergreen').length;
  const pool = replacementPoolForTab(issueReplaceState.tab);
  let html = '<div class="issue-replace-modal">';
  html += '<div class="modal-section-title">替换第 ' + (issueReplaceState.position || '-') + ' 条</div>';
  html += '<div class="modal-section-body" style="margin-bottom:14px;color:var(--text2)">' + escapeHtml(issueReplaceState.oldTitle || '当前文章') + '</div>';
  html += '<div class="filter-tabs" style="margin-bottom:12px">' +
    '<button class="filter-tab ' + (issueReplaceState.tab === 'candidate' ? 'active' : '') + '" onclick="setIssueReplaceTab(\'candidate\')">日报候选 ' + candidateCount + '</button>' +
    '<button class="filter-tab ' + (issueReplaceState.tab === 'evergreen' ? 'active' : '') + '" onclick="setIssueReplaceTab(\'evergreen\')">常青库 ' + evergreenCount + '</button>' +
    '</div>';
  html += '<input class="card-edit-input" id="issueReplaceSearch" value="' + escapeHtml(issueReplaceState.query) + '" oninput="updateIssueReplaceSearch(this.value)" placeholder="搜索标题、来源、频道" style="display:block;width:100%;margin-bottom:12px">';
  if (!pool.length) {
    html += '<div class="wb-empty" style="padding:26px;text-align:center;color:var(--text3)">这个来源里暂无可替换文章</div>';
  } else {
    html += '<div class="issue-replace-list">';
    pool.slice(0, 120).forEach(a => {
      const imgs = asArray(a.images);
      const thumb = imgs.length ? imageSrc(imgs[0]) : '';
      const readiness = cardReadiness(a);
      const reason = readiness.reason ? ' · ' + readiness.reason : '';
      const oneLine = a.gate2_one_line || a.summary || '';
      const actionButton = readiness.ready
        ? '<button class="wb-select-btn" onclick="confirmIssueReplacement(' + Number(a.id) + ',this)">选为替换</button>'
        : '<button class="wb-select-btn" onclick="prepareIssueReplacementCard(' + Number(a.id) + ',this)">先成卡</button>';
      html += '<div class="feed-item issue-replace-item">' +
        (thumb ? '<img class="feed-thumb" src="' + escapeHtml(thumb) + '" loading="lazy" onerror="this.outerHTML=\'<div class=feed-thumb-empty></div>\'">' : '<div class="feed-thumb-empty"></div>') +
        '<div class="feed-main">' +
          '<div class="feed-meta">' +
            '<span class="cat-tag">' + (CAT_EMOJI[a.category] || '') + ' ' + escapeHtml(a.category || '') + '</span>' +
            (a.gate2_tier ? '<span class="tier-badge tier-' + escapeHtml(a.gate2_tier) + '" style="font-size:9px;padding:1px 5px">' + escapeHtml(a.gate2_tier) + '档</span>' : '') +
            '<span class="wb-card-status ' + escapeHtml(readiness.status || '') + '">' + escapeHtml(readiness.label || '') + escapeHtml(reason) + '</span>' +
          '</div>' +
          '<div class="feed-title">' + escapeHtml(a.translated_title || a.title || '') + '</div>' +
          (oneLine ? '<div style="font-size:11px;color:var(--text2);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">' + escapeHtml(oneLine) + '</div>' : '') +
          '<div class="feed-meta" style="margin-top:4px">' + escapeHtml(a.source || '') + ' · ' + escapeHtml((a.crawled_at || '').slice(0,10)) + '</div>' +
        '</div>' +
        actionButton +
      '</div>';
    });
    if (pool.length > 120) {
      html += '<div class="wb-empty" style="padding:12px;text-align:center;color:var(--text3)">已显示前 120 篇，可搜索缩小范围</div>';
    }
    html += '</div>';
  }
  html += '</div>';
  document.getElementById('modalBody').innerHTML = html;
  document.getElementById('modalFooter').innerHTML = '<button class="btn btn-outline" onclick="closeModal()">取消</button>';
}

async function refreshIssueReplacePools() {
  const [issueArticles, candidatePool, evergreenPool] = await Promise.all([
    api('/api/issue-articles/' + issueReplaceState.issueId),
    api('/api/candidate-pool'),
    api('/api/evergreen-pool')
  ]);
  const currentIssueArticles = Array.isArray(issueArticles) ? issueArticles : [];
  issueReplaceState.issueArticleIds = new Set(currentIssueArticles.map(a => Number(a.id)));
  issueReplaceState.candidate = Array.isArray(candidatePool) ? candidatePool : [];
  issueReplaceState.evergreen = Array.isArray(evergreenPool) ? evergreenPool : [];
  renderIssueReplaceModal();
}

async function prepareIssueReplacementCard(articleId, btn) {
  const pool = issueReplaceState.candidate.concat(issueReplaceState.evergreen);
  const article = pool.find(a => Number(a.id) === Number(articleId));
  const title = article ? (article.translated_title || article.title || '') : ('#' + articleId);
  if (!confirm('先为这篇文章成卡？\n\n' + title)) return;
  const idleLabel = btn ? btn.textContent : '先成卡';
  if (btn) {
    btn.disabled = true;
    btn.textContent = '提交中...';
  }
  try {
    const res = await fetch('/api/prepare-card-async/' + articleId, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (!data.ok) {
      alert('成卡提交失败: ' + (data.error || '未知错误'));
      if (btn) {
        btn.disabled = false;
        btn.textContent = idleLabel;
      }
      return;
    }
    const taskId = data.task_id;
    const poll = setInterval(async () => {
      try {
        const r = await fetch('/api/task-status/' + taskId);
        const t = await r.json();
        if (!t.ok) return;
        if (btn) btn.textContent = (t.status_text || '处理中...') + ' (' + (t.progress || 0) + '%)';
        if (t.status === 'done') {
          clearInterval(poll);
          await refreshIssueReplacePools();
        } else if (t.status === 'error') {
          clearInterval(poll);
          alert('成卡失败: ' + (t.error || '未知错误'));
          if (btn) {
            btn.disabled = false;
            btn.textContent = idleLabel;
          }
        }
      } catch(e) {
        clearInterval(poll);
        alert('任务状态查询失败: ' + e.message);
        if (btn) {
          btn.disabled = false;
          btn.textContent = idleLabel;
        }
      }
    }, 2000);
  } catch(e) {
    alert('成卡请求失败: ' + e.message);
    if (btn) {
      btn.disabled = false;
      btn.textContent = idleLabel;
    }
  }
}

async function confirmIssueReplacement(newArticleId, btn) {
  const pool = issueReplaceState.candidate.concat(issueReplaceState.evergreen);
  const newArticle = pool.find(a => Number(a.id) === Number(newArticleId));
  const title = newArticle ? (newArticle.translated_title || newArticle.title || '') : '所选文章';
  if (!confirm('确认用“' + title + '”替换当前这篇？系统会同步重生成本期 H5。')) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '替换中...';
  }
  try {
    const res = await fetch('/api/issues/' + issueReplaceState.issueId + '/replace-article', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        old_article_id: issueReplaceState.oldArticleId,
        new_article_id: Number(newArticleId),
        old_status: 'candidate',
        reason: 'manual_issue_replace'
      })
    });
    const data = await res.json();
    if (!res.ok || !data.ok) {
      alert('替换失败: ' + (data.error || '未知错误'));
      if (btn) {
        btn.disabled = false;
        btn.textContent = '选为替换';
      }
      return;
    }
    closeModal();
    await loadIssuesList();
    alert('已替换，并已重生成本期 H5。');
  } catch(e) {
    console.error(e);
    alert('替换失败: ' + (e.message || e));
    if (btn) {
      btn.disabled = false;
      btn.textContent = '选为替换';
    }
  }
}

async function openCardEditor(issueId, articleId) {
  editingIssueId = issueId;
  editingArticleId = articleId;
  const data = await api('/api/issue-card/' + issueId + '/' + articleId);
  if (!data || !data.ok) {
    alert('加载卡片失败: ' + ((data && data.error) || '未知错误'));
    return;
  }
  const card = data.card || {};
  editingImages = Array.isArray(data.images) ? data.images.slice() : [];
  document.getElementById('modal').classList.add('card-edit-modal-shell');
  document.getElementById('modalHero').innerHTML = '';
  document.getElementById('modalBody').innerHTML = `
    <div class="card-edit-form">
      <div style="font-size:12px;color:var(--text3)">#${articleId} · ${escapeHtml(data.article_title || '')}</div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">标题</label>
        <input class="card-edit-input" id="editHeadline" value="${escapeHtml(card.headline || '')}" style="display:block;width:100%">
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">频道</label>
        <input class="card-edit-input" id="editChannel" value="${escapeHtml(card.channel || data.category || '')}" style="display:block;width:100%">
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">一句话钩子</label>
        <input class="card-edit-input" id="editOneLine" value="${escapeHtml(card.one_line || '')}" style="display:block;width:100%">
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">推荐文案</label>
        <textarea class="card-edit-textarea card-edit-long" id="editBody" style="display:block;width:100%;min-height:190px">${escapeHtml(card.body || '')}</textarea>
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">深挖信息</label>
        <textarea class="card-edit-textarea card-edit-long" id="editDeepDive" style="display:block;width:100%;min-height:190px">${escapeHtml(card.deep_dive || '')}</textarea>
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">安排建议</label>
        <textarea class="card-edit-textarea card-edit-short" id="editArrangement" style="display:block;width:100%;min-height:118px">${escapeHtml(card.arrangement || '')}</textarea>
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">注意事项 每行一条</label>
        <textarea class="card-edit-textarea card-edit-short" id="editCautions" style="display:block;width:100%;min-height:118px">${escapeHtml((Array.isArray(card.cautions) ? card.cautions : []).join('\\n'))}</textarea>
      </div>
      <div class="card-edit-field" style="display:block;margin-bottom:14px">
        <label style="display:block;margin-bottom:6px">图片 第一张为封面</label>
        <div class="card-edit-images" id="editImages" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px"></div>
      </div>
      <div class="card-edit-upload">
        <input type="file" id="editImageFile" accept="image/*">
        <button class="btn btn-outline btn-sm" type="button" onclick="uploadEditImage()">上传</button>
      </div>
    </div>`;
  document.getElementById('modalFooter').innerHTML = `
    <button class="btn btn-outline" onclick="closeModal()">取消</button>
    <button class="btn btn-gold" id="saveCardEditBtn" onclick="saveCardEditor()">保存卡片</button>`;
  renderEditImages();
  document.getElementById('modalBg').classList.add('open');
  document.body.style.overflow = 'hidden';
}

function renderEditImages() {
  const container = document.getElementById('editImages');
  if (!container) return;
  if (!editingImages.length) {
    container.innerHTML = '<div class="wb-empty" style="grid-column:1/-1;padding:18px">暂无图片</div>';
    return;
  }
  let html = '';
  editingImages.forEach((img, idx) => {
    html += `<div class="card-edit-img" style="border:1px solid var(--border);border-radius:8px;overflow:hidden;background:var(--card2)">
      <img src="${escapeHtml(imageSrc(img))}" style="width:100%;height:180px;object-fit:contain;display:block;background:#f7f4ee" onerror="this.style.display='none'">
      <div class="card-edit-img-actions">
        <button type="button" onclick="moveEditImage(${idx},-1)" ${idx===0?'disabled':''}>上</button>
        <button type="button" onclick="moveEditImage(${idx},1)" ${idx===editingImages.length-1?'disabled':''}>下</button>
        <button type="button" onclick="removeEditImage(${idx})">删</button>
      </div>
    </div>`;
  });
  container.innerHTML = html;
}

function moveEditImage(idx, delta) {
  const next = idx + delta;
  if (next < 0 || next >= editingImages.length) return;
  const item = editingImages[idx];
  editingImages.splice(idx, 1);
  editingImages.splice(next, 0, item);
  renderEditImages();
}

function removeEditImage(idx) {
  editingImages.splice(idx, 1);
  renderEditImages();
}

async function uploadEditImage() {
  const input = document.getElementById('editImageFile');
  if (!input || !input.files || !input.files.length) {
    alert('先选择一张图片');
    return;
  }
  const fd = new FormData();
  fd.append('image', input.files[0]);
  const res = await fetch('/api/issue-card/' + editingIssueId + '/' + editingArticleId + '/upload-image', {
    method: 'POST',
    body: fd
  });
  const data = await res.json();
  if (!data.ok) {
    alert('上传失败: ' + (data.error || '未知错误'));
    return;
  }
  editingImages = editingImages.concat([data.path]);
  input.value = '';
  renderEditImages();
}

async function saveCardEditor() {
  const btn = document.getElementById('saveCardEditBtn');
  if (btn) { btn.disabled = true; btn.textContent = '保存中...'; }
  const cautions = (document.getElementById('editCautions').value || '')
    .split('\\n').map(s => s.trim()).filter(Boolean);
  const payload = {
    card: {
      headline: document.getElementById('editHeadline').value || '',
      channel: document.getElementById('editChannel').value || '',
      one_line: document.getElementById('editOneLine').value || '',
      body: document.getElementById('editBody').value || '',
      deep_dive: document.getElementById('editDeepDive').value || '',
      arrangement: document.getElementById('editArrangement').value || '',
      cautions: cautions
    },
    images: editingImages
  };
  const res = await fetch('/api/issue-card/' + editingIssueId + '/' + editingArticleId, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!data.ok) {
    alert('保存失败: ' + (data.error || '未知错误'));
    if (btn) { btn.disabled = false; btn.textContent = '保存卡片'; }
    return;
  }
  closeModal();
  refreshIssueDetail(editingIssueId);
  alert('已保存。需要更新页面时，点击本期右侧的“重生成 H5”。');
}

async function setDjFeedback(articleId, feedback, issueId, detail) {
  var label = feedback === 'skipped' ? '跳过' : (detail === 'next_trip' ? '顺路' : '尽快');
  if (!confirm('确认把这篇标记为“' + label + '”？这会写入 DJ 反馈，但不会改动已生成的 H5 内容。')) return;
  var body = {id: articleId, feedback: feedback};
  if (detail) body.detail = detail;
  await fetch('/api/dj-feedback', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  refreshIssueDetail(issueId);
}

// ===== 通用工具 =====
async function releasePending(id) {
  if (!confirm('确认放行此文章？将恢复原档位并允许正常流转。')) return;
  await fetch('/api/release-pending', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: id})
  });
  loadArticles();
}

async function violatePending(id) {
  if (!confirm('确认此文章违规？将被归档（原因：画像冲突）。')) return;
  await fetch('/api/violate-pending', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: id})
  });
  loadArticles();
}

async function runMaintenance(op) {
  const statusEl = document.getElementById('status-' + op);
  const progressEl = document.getElementById('progress-' + op);
  const btn = document.getElementById('btnRun-' + op) || document.querySelector('#maint-' + op + ' button');
  const payload = maintenancePayloads[op] || getMaintenancePayload(op);

  if (['resummarize', 'reeval', 'reveto', 'clear-feedback'].includes(op) && (!maintenancePayloads[op] || maintenancePayloads[op]._previewCount == null)) {
    alert('请先预览影响范围，再执行。');
    return;
  }
  if (['resummarize', 'reeval', 'reveto', 'clear-feedback'].includes(op) && maintenancePayloads[op]._previewCount === 0) {
    alert('预览结果为空，无需执行。');
    return;
  }

  statusEl.textContent = '启动中...';
  statusEl.className = 'maint-status running';
  progressEl.style.display = 'block';
  progressEl.innerHTML = '<div class="line">提交任务...</div>';
  btn.disabled = true;

  try {
    const res = await fetch('/api/maint/' + op, {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload || {})
    });
    const data = await res.json();
    if (!data.ok) {
      statusEl.textContent = '失败';
      statusEl.className = 'maint-status error';
      progressEl.innerHTML = '<div class="line err">✗ 启动失败</div>';
      btn.disabled = false;
      return;
    }

    // Poll for status
    let pollCount = 0;
    const poll = setInterval(async () => {
      try {
        const r = await fetch('/api/maint/status/' + op);
        const s = await r.json();
        pollCount++;

        if (s.status === 'pending') {
          progressEl.innerHTML = '<div class="line">等待执行...</div>';
        } else if (s.status === 'running') {
          progressEl.innerHTML = '<div class="line">执行中... (' + (s.progress||'?') + ')</div>';
        } else if (s.status === 'done') {
          clearInterval(poll);
          statusEl.textContent = '完成';
          statusEl.className = 'maint-status done';
          let report = '<div class="line ok">✓ 完成</div>';
          if (s.result && s.result.stats) {
            for (const [k,v] of Object.entries(s.result.stats)) {
              report += '<div class="line">' + k + ': ' + JSON.stringify(v) + '</div>';
            }
          }
          if (s.result && s.result.summary) report += '<div class="line ok">' + s.result.summary + '</div>';
          if (s.result && s.result.failed_list) {
            report += '<div class="line warn">失败清单:</div>';
            s.result.failed_list.slice(0,10).forEach(f => report += '<div class="line err">  ' + f + '</div>');
          }
          progressEl.innerHTML = report;
          maintenancePayloads[op] = null;
          btn.disabled = false;
        } else if (s.status === 'error') {
          clearInterval(poll);
          statusEl.textContent = '失败';
          statusEl.className = 'maint-status error';
          progressEl.innerHTML = '<div class="line err">✗ ' + (s.error || '未知错误') + '</div>';
          btn.disabled = false;
        }

        if (pollCount > 300) { clearInterval(poll); btn.disabled = false; }
      } catch(e) { console.error(e);
        clearInterval(poll);
        statusEl.textContent = '错误';
        statusEl.className = 'maint-status error';
        progressEl.innerHTML = '<div class="line err">✗ 轮询失败</div>';
        btn.disabled = false;
      }
    }, 2000);
  } catch(e) { console.error(e);
    statusEl.textContent = '错误';
    statusEl.className = 'maint-status error';
    progressEl.innerHTML = '<div class="line err">✗ ' + e.message + '</div>';
    btn.disabled = false;
  }
}

function selectedMaintenanceIds(op) {
  return (maintenanceArticleSelections[op] || []).map(a => Number(a.id)).filter(Boolean);
}

function getMaintenancePayload(op) {
  if (op === 'resummarize') {
    const mode = document.getElementById('maintResumMode')?.value || 'ids';
    return {
      mode,
      ids: mode === 'ids' ? selectedMaintenanceIds('resummarize') : [],
      limit: parseInt(document.getElementById('maintResumLimit')?.value || '20', 10)
    };
  }
  if (op === 'reeval') {
    const mode = document.getElementById('maintReevalMode')?.value || 'queue';
    return {
      mode,
      ids: mode === 'ids' ? selectedMaintenanceIds('reeval') : [],
      limit: parseInt(document.getElementById('maintReevalLimit')?.value || '100', 10)
    };
  }
  if (op === 'reveto') {
    const mode = document.getElementById('maintRevetoMode')?.value || 'ids';
    return {
      mode,
      ids: mode === 'ids' ? selectedMaintenanceIds('reveto') : [],
      limit: parseInt(document.getElementById('maintRevetoLimit')?.value || '10', 10)
    };
  }
  if (op === 'clear-feedback') {
    return {
      issue_id: (document.getElementById('maintClearIssueId')?.value || '').trim(),
      ids: selectedMaintenanceIds('clear-feedback')
    };
  }
  return {};
}

function validateMaintenancePayload(op, payload) {
  if (op === 'resummarize' && payload.mode === 'ids' && !payload.ids.length) {
    return '请先加入至少一篇文章，或选择一个固定范围。';
  }
  if (op === 'reeval' && payload.mode === 'ids' && !payload.ids.length) {
    return '请先加入至少一篇待人工文章，或选择扫描待人工队列。';
  }
  if (op === 'reveto' && payload.mode === 'ids' && !payload.ids.length) {
    return '请先加入至少一篇文章，或选择一个固定范围。';
  }
  if (op === 'clear-feedback' && !payload.issue_id && !payload.ids.length) {
    return '请选择期刊，或加入至少一篇文章。';
  }
  return '';
}

async function loadMaintenanceOptions() {
  const issueSelect = document.getElementById('maintClearIssueId');
  await loadMaintenanceArticleOptions();
  if (!issueSelect || issueSelect.dataset.loaded === '1') return;
  issueSelect.innerHTML = '<option value="">加载期刊中...</option>';
  try {
    const issues = await api('/api/issues');
    const rows = Array.isArray(issues) ? issues.filter(i => (i.article_count || 0) > 0) : [];
    let html = '<option value="">选择期刊（可选）</option>';
    rows.slice(0, 80).forEach(issue => {
      const date = (issue.report_date || issue.created_date || issue.created_at || '').slice(0, 10);
      const label = formatIssueLabel(issue.issue_number) +
        (date ? ' · ' + date : '') +
        ' · ' + (issue.article_count || 0) + '篇' +
        (issue.status ? ' · ' + issue.status : '');
      html += '<option value="' + Number(issue.id) + '">' + escapeHtml(label) + '</option>';
    });
    issueSelect.innerHTML = html;
    issueSelect.dataset.loaded = '1';
  } catch(e) {
    issueSelect.innerHTML = '<option value="">期刊加载失败</option>';
  }
}

async function loadMaintenanceArticleOptions() {
  const selectors = [
    'maintArticleSelect-resummarize',
    'maintArticleSelect-reeval',
    'maintArticleSelect-reveto',
    'maintArticleSelect-clear-feedback'
  ].map(id => document.getElementById(id)).filter(Boolean);
  if (!selectors.length || maintenanceArticleOptions.length) {
    selectors.forEach(fillMaintenanceArticleSelect);
    return;
  }
  selectors.forEach(sel => sel.innerHTML = '<option value="">加载文章中...</option>');
  try {
    const articles = await api('/api/articles?status=all&limit=1000');
    maintenanceArticleOptions = Array.isArray(articles) ? articles.map(a => ({
      id: Number(a.id),
      title: a.translated_title || a.title || '',
      category: a.category || '',
      tier: a.gate2_tier || '',
      status: a.status || '',
      source: a.source || '',
      pending_human: a.pending_human === 1 || a.pending_human === '1' || a.pending_human === true
    })).filter(a => a.id) : [];
    selectors.forEach(fillMaintenanceArticleSelect);
  } catch(e) {
    selectors.forEach(sel => sel.innerHTML = '<option value="">文章加载失败</option>');
  }
}

function fillMaintenanceArticleSelect(selectEl) {
  if (!selectEl) return;
  const op = selectEl.id.replace('maintArticleSelect-', '');
  const selected = new Set(selectedMaintenanceIds(op));
  let rows = maintenanceArticleOptions;
  if (op === 'reeval') rows = rows.filter(a => a.pending_human);
  let html = '<option value="">选择文章加入...</option>';
  rows.slice(0, 1000).forEach(a => {
    const disabled = selected.has(a.id) ? ' disabled' : '';
    const label = '#' + a.id + ' · ' + (a.tier ? a.tier + '档 · ' : '') + (a.category || '未分类') + ' · ' + (a.title || '').slice(0, 54);
    html += '<option value="' + a.id + '"' + disabled + '>' + escapeHtml(label) + '</option>';
  });
  selectEl.innerHTML = html;
}

function addMaintenanceArticle(op) {
  const selectEl = document.getElementById('maintArticleSelect-' + op);
  const id = Number(selectEl?.value || 0);
  if (!id) return;
  const article = maintenanceArticleOptions.find(a => a.id === id);
  if (!article) return;
  if (!maintenanceArticleSelections[op].find(a => a.id === id)) {
    maintenanceArticleSelections[op].push(article);
  }
  if (op === 'resummarize') document.getElementById('maintResumMode').value = 'ids';
  if (op === 'reeval') document.getElementById('maintReevalMode').value = 'ids';
  if (op === 'reveto') document.getElementById('maintRevetoMode').value = 'ids';
  renderMaintenanceSelected(op);
  fillMaintenanceArticleSelect(selectEl);
  resetMaintenancePreview(op);
}

function removeMaintenanceArticle(op, id) {
  maintenanceArticleSelections[op] = (maintenanceArticleSelections[op] || []).filter(a => Number(a.id) !== Number(id));
  renderMaintenanceSelected(op);
  fillMaintenanceArticleSelect(document.getElementById('maintArticleSelect-' + op));
  resetMaintenancePreview(op);
}

function renderMaintenanceSelected(op) {
  const target = document.getElementById('maintSelected-' + op);
  if (!target) return;
  const selected = maintenanceArticleSelections[op] || [];
  if (!selected.length) {
    target.innerHTML = '<div class="maint-selected-empty">未选择文章</div>';
    return;
  }
  target.innerHTML = selected.map(a => {
    const label = '#' + a.id + ' · ' + (a.title || '').slice(0, 42);
    return '<div class="maint-selected-chip"><span>' + escapeHtml(label) + '</span><button onclick="removeMaintenanceArticle(\'' + op + '\',' + Number(a.id) + ')">×</button></div>';
  }).join('');
}

function resetMaintenancePreview(op) {
  maintenancePayloads[op] = null;
  const btn = document.getElementById('btnRun-' + op);
  if (btn) btn.disabled = true;
  const statusEl = document.getElementById('status-' + op);
  if (statusEl) {
    statusEl.textContent = '待执行';
    statusEl.className = 'maint-status';
  }
}

function setupMaintenanceInputs() {
  if (window._maintenanceInputsReady) return;
  window._maintenanceInputsReady = true;
  [
    ['maintResumMode', 'resummarize'],
    ['maintResumLimit', 'resummarize'],
    ['maintReevalMode', 'reeval'],
    ['maintReevalLimit', 'reeval'],
    ['maintRevetoMode', 'reveto'],
    ['maintRevetoLimit', 'reveto'],
    ['maintClearIssueId', 'clear-feedback'],
  ].forEach(([id, op]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', () => resetMaintenancePreview(op));
    el.addEventListener('change', () => resetMaintenancePreview(op));
  });
  Object.keys(maintenanceArticleSelections).forEach(renderMaintenanceSelected);
}

function renderMaintenancePreview(op, data) {
  const progressEl = document.getElementById('progress-' + op);
  const runBtn = document.getElementById('btnRun-' + op);
  progressEl.style.display = 'block';
  let html = '<div class="line ok">预览命中 ' + (data.count || 0) + ' 篇</div>';
  if (data.articles && data.articles.length) {
    html += '<div class="maint-preview-list">';
    data.articles.slice(0, 30).forEach(a => {
      const fb = a.dj_feedback ? ' · ' + a.dj_feedback + (a.feedback_detail ? '/' + a.feedback_detail : '') : '';
      const action = a.action ? ' · ' + (a.action === 'reset' ? '可复位' : '保留') : '';
      html += '<div class="line">#' + a.id + ' · ' + escapeHtml(a.tier || '') + '档 · ' + escapeHtml(a.category || '') + ' · ' + escapeHtml((a.title || '').slice(0, 48)) + escapeHtml(fb + action) + '</div>';
    });
    if (data.articles.length > 30) html += '<div class="line warn">仅显示前 30 篇</div>';
    html += '</div>';
  }
  progressEl.innerHTML = html;
  if (runBtn) runBtn.disabled = !(data.count > 0);
}

async function previewMaintenance(op) {
  const payload = getMaintenancePayload(op);
  const error = validateMaintenancePayload(op, payload);
  if (error) {
    alert(error);
    return;
  }
  const statusEl = document.getElementById('status-' + op);
  const progressEl = document.getElementById('progress-' + op);
  const runBtn = document.getElementById('btnRun-' + op);
  if (runBtn) runBtn.disabled = true;
  statusEl.textContent = '预览中...';
  statusEl.className = 'maint-status running';
  progressEl.style.display = 'block';
  progressEl.innerHTML = '<div class="line">扫描影响范围...</div>';
  try {
    const res = await fetch('/api/maint/' + op + '/preview', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    const data = await res.json();
    if (!data.ok) {
      statusEl.textContent = '预览失败';
      statusEl.className = 'maint-status error';
      progressEl.innerHTML = '<div class="line err">' + escapeHtml(data.error || '预览失败') + '</div>';
      return;
    }
    const frozenIds = (data.articles || []).map(a => Number(a.id)).filter(Boolean);
    if (frozenIds.length) {
      payload.ids = frozenIds;
      if (['resummarize', 'reeval', 'reveto'].includes(op)) payload.mode = 'ids';
      if (op === 'clear-feedback') payload.issue_id = '';
    }
    payload._previewCount = data.count || 0;
    maintenancePayloads[op] = payload;
    statusEl.textContent = '已预览';
    statusEl.className = 'maint-status done';
    renderMaintenancePreview(op, data);
  } catch(e) {
    statusEl.textContent = '预览失败';
    statusEl.className = 'maint-status error';
    progressEl.innerHTML = '<div class="line err">' + escapeHtml(e.message || e) + '</div>';
  }
}

async function refreshData() {
  const activePage = document.querySelector('.page.active');
  const pageId = activePage ? activePage.id : '';
  if (pageId === 'page-articles') {
    const scrollY = window.scrollY;
    if (currentFilter === 'all') await loadAllArticles();
    else await loadArticles();
    window.requestAnimationFrame(() => window.scrollTo(0, scrollY));
    return;
  }
  if (pageId === 'page-dashboard') return loadDashboard();
  if (pageId === 'page-report') return loadWorkbench();
  if (pageId === 'page-issues') return loadIssuesList();
  if (pageId === 'page-maintenance') {
    setupMaintenanceInputs();
    return loadMaintenanceOptions();
  }
}

// 启动
loadDashboard();
