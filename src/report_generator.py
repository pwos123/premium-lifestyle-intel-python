"""
H5 周报生成器 — v3 体验策展版
收起态: 4:3封面图 + 标题 + 钩子 (杂志封面式)
展开态: 原比例竖排图集 + 门道 + 落地方案 + 注意事项
"""

import html as _html
import json, logging, re as _re
from datetime import datetime, timedelta
from src.filters import HARD_BLOCK_WORDS, HARD_BLOCK_PATTERNS, SOFT_FLAG_WORDS, SOFT_FLAG_PATTERNS, INTERNAL_PATTERN, PERSON_REF_PATTERN, check_field
from services.issue_builder import get_card_readiness
from services.image_selection import image_to_static_url, is_junk_image, resolve_image_path, select_h5_visible_images
from pathlib import Path
from jinja2 import Template

logger = logging.getLogger(__name__)

CATEGORY_SVG = {
    "艺术与文化": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 15l5-5 4 4 4-6 5 5"/></svg>',
    "建筑与空间": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 21h18"/><path d="M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6"/></svg>',
    "科技与生活": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
    "产品与设计": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M3 9h18"/><path d="M9 3v18"/></svg>',
    "精品酒店与度假": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="8" width="18" height="13" rx="1"/><path d="M3 12h18"/><path d="M9 8V5a2 2 0 012-2h2a2 2 0 012 2v3"/></svg>',
    "旅行与探索": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10A15.3 15.3 0 0112 2z"/></svg>',
    "美食与美酒": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M8 2v4M16 2v4"/><path d="M3 10h18v2a8 8 0 01-16 0v-2z"/><path d="M12 14v8"/><path d="M8 22h8"/></svg>',
    "时尚与风格": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.38 3.46L16 2 12 5.5 8 2l-4.38 1.46a1 1 0 00-.62.94v14a1 1 0 001 1h16a1 1 0 001-1v-14a1 1 0 00-.62-.94z"/><path d="M12 2v14"/></svg>',
    "珠宝与腕表": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    "汽车与出行": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 17h14"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M5 17a2 2 0 01-2-2V9a2 2 0 012-2h1l2-3h8l2 3h1a2 2 0 012 2v6a2 2 0 01-2 2"/></svg>',
    "健康与养生": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78L12 21.23l8.84-8.84a5.5 5.5 0 000-7.78z"/></svg>',
    "音乐与演出": '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
}

# ==== 两级过滤 ====
# 硬拦级: 命中即转人工, 绝不出报
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>{{ title }}</title>
<style>
:root{--accent:#b8860b;--bg:#fdfaf5;--card:#fff;--text:#1e1e1e;--dim:#8c8c8c;--border:#ece7dd;--hook:#8b6914;--morandi-border:#d0ccc4}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"PingFang SC","Hiragino Sans GB","Noto Serif SC",sans-serif;background:var(--bg);color:var(--text);line-height:1.75;-webkit-font-smoothing:antialiased;max-width:600px;margin:0 auto;padding:0 0 60px}

/* ===== Header ===== */
.header{padding:32px 16px 20px;text-align:center;border-bottom:1px solid var(--border)}
.header .issue{font-size:11px;letter-spacing:3px;color:var(--dim);font-weight:500;margin-bottom:4px}
.header .date{font-size:11px;color:var(--dim);margin-bottom:16px}
.header .note{font-size:14px;color:var(--text);line-height:1.8;max-width:460px;margin:0 auto;padding:12px 0}
.header .note-tag{display:inline-block;font-size:9px;letter-spacing:2px;color:var(--accent);border:1px solid var(--accent);border-radius:20px;padding:2px 10px;margin-bottom:8px}

/* ===== Filter bar ===== */
.filter-bar{display:flex;gap:6px;padding:10px 16px;overflow-x:auto;-webkit-overflow-scrolling:touch;border-bottom:1px solid var(--border)}
.filter-chip{flex-shrink:0;padding:5px 12px;border-radius:16px;font-size:11px;border:1px solid var(--border);background:var(--card);color:var(--dim);cursor:pointer;white-space:nowrap}
.filter-chip.active{border-color:var(--accent);color:var(--accent);background:#faf5e6}

/* ===== Section header ===== */
.section-hd{padding:28px 16px 6px;display:flex;align-items:center;gap:6px}
.section-hd .icon{color:var(--dim)}
.section-hd h2{font-size:15px;font-weight:600;color:var(--text)}
.section-hd .count{font-size:10px;color:var(--dim);margin-left:auto}

/* ===== Card ===== */
.card{margin:20px 12px;background:var(--card);border-radius:12px;border:1px solid var(--morandi-border)}

/* Cover image block: 21:9 ultrawide, padding-top technique for WeChat compat */
.card-cover{position:relative;width:100%;padding-top:42.9%;overflow:hidden;border-radius:12px 12px 0 0;cursor:pointer}
.card-cover img{position:absolute;top:0;left:0;width:100%;height:100%;object-fit:cover}
.card-cover.no-img{background:var(--morandi-border)}
.card-cover .card-tag{position:absolute;top:10px;left:10px;z-index:2;color:#fff;background:rgba(80,80,80,0.45)}
.card-tag{display:inline-flex;align-items:center;font-size:10px;color:var(--accent);background:#faf5e6;padding:2px 10px;border-radius:10px;letter-spacing:.5px;font-weight:500}
.card-seq{font-size:11px;color:var(--dim);font-weight:700;font-family:"DIN Alternate","Helvetica Neue",sans-serif;letter-spacing:-.02em}

/* Title row: headline left + seq right */
.card-title-row{display:flex;align-items:baseline;justify-content:space-between;padding:14px 16px 0;cursor:pointer}
.card-title-row .card-headline{font-size:16px;font-weight:600;line-height:1.4;color:var(--text);flex:1;min-width:0;padding-right:12px}
.card-title-row .card-seq{flex-shrink:0}
.card-info{padding:6px 16px 14px;cursor:pointer}
.card-headline{font-size:16px;font-weight:600;line-height:1.4;color:var(--text)}
.card-hook{font-size:14px;color:var(--hook);line-height:1.6;font-weight:500}
.card-warning{margin:0 16px 12px;padding:9px 11px;background:#fff3cd;border:1px solid #ffc107;border-radius:8px;color:#856404;font-size:12px;line-height:1.6}
.card-warning b{font-weight:700}

/* Expanded */
.card-body-exp{display:none;padding:0 16px 16px}
.card.open{overflow:visible}
.card.open .card-body-exp{display:block}

/* Gallery: stacked, original ratio */
.card-gallery{display:none}
.card.open .card-gallery{display:block}
.gallery-img{width:100%;display:block;margin-bottom:2px}
.gallery-img:last-child{margin-bottom:0}

/* Body text */
.card-body-exp .rec{font-size:14px;line-height:1.85;color:var(--text);margin-bottom:18px;padding-top:14px}
.card-body-exp .dd-section{margin:18px 0;padding:14px;background:#faf8f3;border-radius:8px}
.card-body-exp .dd-label{font-size:10px;letter-spacing:2px;color:var(--accent);margin-bottom:4px;text-transform:uppercase}
.card-body-exp .dd-text{font-size:13px;line-height:1.8;color:#444}
.card-body-exp .meta-row{margin-bottom:14px}
.card-body-exp .meta-label{font-size:10px;letter-spacing:1px;color:var(--accent);text-transform:uppercase;margin-bottom:2px}
.card-body-exp .meta-text{font-size:13px;color:#444;line-height:1.7}
.card-body-exp .caution{margin-top:4px;padding:8px 10px;background:#fef9f0;border-left:2px solid var(--accent);border-radius:0 6px 6px 0;font-size:12px;color:#6b5a3e;line-height:1.6}
.card-body-exp .src-link{margin-top:10px;font-size:11px}
.card-body-exp .src-link a{color:var(--dim);text-decoration:underline;text-underline-offset:2px}

/* Actions */
.card-actions{display:none;padding:0 16px 14px;gap:6px;flex-wrap:wrap}
.card.open .card-actions{display:flex}
.btn-act{flex:1;min-width:80px;padding:8px 0;border-radius:8px;font-size:12px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;text-align:center;transition:all .15s;font-family:inherit}
.btn-act.asap{border-color:var(--accent);color:var(--accent)}
.btn-act.asap:hover,.btn-act.asap.active{background:var(--accent);color:#fff}
.btn-act.next{border-color:#6b8f71;color:#6b8f71}
.btn-act.next:hover,.btn-act.next.active{background:#6b8f71;color:#fff}
.btn-act.skip{border-color:#ccc;color:var(--dim);max-width:56px;flex:0}
.btn-act.skip:hover,.btn-act.skip.active{background:#eee;color:#666}
.btn-collapse{display:none;width:100%;padding:6px 0;margin-top:4px;border:none;background:transparent;color:var(--dim);font-size:11px;cursor:pointer;text-align:center;font-family:inherit}
.card.open .btn-collapse{display:block}

/* Feedback states */
.card.fb-asap .btn-act.asap{background:var(--accent);color:#fff}
.card.fb-next .btn-act.next{background:#6b8f71;color:#fff}
.card.fb-skip .btn-act.skip{background:#eee;color:#666}

/* Explicit selected button states (survives card class changes) */
.btn-act.selected.asap{background:var(--accent);color:#fff;font-weight:600}
.btn-act.selected.next{background:#6b8f71;color:#fff;font-weight:600}
.btn-act.selected.skip{background:#666;color:#fff;font-weight:600}
.fb-done{display:none;font-size:10px;color:var(--dim);text-align:center;padding:0 16px 6px}
.card.open .fb-done{display:block}
</style>
</head>
<body data-issue="{{ issue_number }}">

<div class="header">
  <div class="issue">{{ issue_label }}</div>
  <div class="date">{{ date_range }}</div>
  {% if editor_note %}
  <div class="note">
    <div class="note-tag">本期看点</div>
    <p>{{ editor_note }}</p>
  </div>
  {% endif %}
  {% if warnings %}
  {{ warnings|safe }}
  {% endif %}
</div>

<div class="filter-bar">
  <div class="filter-chip active" onclick="filterAll(this)">全部</div>
  {% for ch in channels %}
  <div class="filter-chip" onclick="filterChannel('{{ ch }}',this)">{{ ch }}</div>
  {% endfor %}
</div>

<div id="cards-container">
{% for sec in sections %}
<div class="section-hd" data-channel="{{ sec.name }}">
  <span class="icon">{{ sec.icon|safe }}</span>
  <h2>{{ sec.name }}</h2>
  <span class="count">{{ sec.articles|length }}条</span>
</div>

{% for card in sec.articles %}
<div class="card" id="card-{{ card.id }}" data-channel="{{ card.channel or sec.name }}">
  <!-- Cover: 21:9 block with tag overlay top-left, no-image fallback with solid color -->
  <div class="card-cover{% if not card.thumb %} no-img{% endif %}" onclick="toggleCard({{ card.id }}, event)">
    {% if card.thumb %}<img src="{{ card.thumb }}" alt="" loading="lazy">{% endif %}
    <div class="card-tag">{% if card.channel %}{{ card.channel }}{% else %}{{ sec.name }}{% endif %}</div>
  </div>
  <!-- Title (left) + Seq (right) -->
  <div class="card-title-row" onclick="toggleCard({{ card.id }}, event)">
    <div class="card-headline">{{ card.headline }}</div>
    {% if card.seq_str %}<div class="card-seq">{{ card.seq_str }}</div>{% endif %}
  </div>
  <!-- One-line hook (reads card.one_line via card.hook mapping) -->
  <div class="card-info" onclick="toggleCard({{ card.id }}, event)">
    {% if card.hook %}
    <div class="card-hook">{{ card.hook }}</div>
    {% endif %}
  </div>
  {% if card.hard_warnings %}
  <div class="card-warning">⚠️ 禁词告警:
    {% for w in card.hard_warnings %}
      <b>{{ w }}</b>{% if not loop.last %}、{% endif %}
    {% endfor %}
  </div>
  {% endif %}
  <!-- Expanded body -->
  <div class="card-body-exp">
    <div class="rec">{{ card.body | safe }}</div>

  <!-- Gallery (after body, unique images only) -->
  {% if card.gallery_images %}
  <div class="card-gallery" style="margin:18px 0">
    {% for img in card.gallery_images %}
    <img class="gallery-img" src="{{ img }}" alt="" loading="lazy">
    {% endfor %}
  </div>
  {% endif %}

    {% if card.deep_dive %}
    <div class="dd-section">
      <div class="dd-label">门道</div>
      <div class="dd-text">{{ card.deep_dive | safe }}</div>
    </div>
    {% endif %}

    {% if card.arrangement %}
    <div class="meta-row">
      <div class="meta-label">落地方案</div>
      <div class="meta-text">{{ card.arrangement }}</div>
    </div>
    {% endif %}

    {% if card.cautions %}
    {% for c in card.cautions %}
    <div class="caution">⚠ {{ c }}</div>
    {% endfor %}
    {% endif %}

    {% if card.link %}
    <div class="src-link"><a href="{{ card.link }}" target="_blank">原文链接</a></div>
    {% endif %}
  </div>

  <!-- Actions -->
  <div class="card-actions">
    <button class="btn-act asap" onclick="event.stopPropagation();doFeedback({{ card.id }},'checked','asap')">尽快安排</button>
    <button class="btn-act next" onclick="event.stopPropagation();doFeedback({{ card.id }},'checked','next_trip')">下次顺路时</button>
    <button class="btn-act skip" onclick="event.stopPropagation();doFeedback({{ card.id }},'skipped','')">跳过</button>
  </div>
  <button class="btn-collapse" onclick="event.stopPropagation();collapseCard({{ card.id }})">收起 ▲</button>
  <div class="fb-done"><span id="fb-label-{{ card.id }}"></span></div>
</div>
{% endfor %}
{% endfor %}
</div>

<div id="empty-hint" style="display:none;text-align:center;padding:60px 20px;color:var(--dim);font-size:13px">该频道暂无内容</div>

<script>
var cardPositions = {};
var currentFilter = '';

function saveCardPos(id) {
  var el = document.getElementById('card-' + id);
  if (el) cardPositions[id] = el.getBoundingClientRect().top + window.scrollY;
}

function toggleCard(id, evt) {
  if (evt) evt.stopPropagation();
  var card = document.getElementById('card-' + id);
  if (!card) return;
  if (card.classList.contains('open')) {
    collapseCard(id);
  } else {
    saveCardPos(id);
    card.classList.add('open');
    lazyLoadGallery(id);
  }
}

function collapseCard(id) {
  var card = document.getElementById('card-' + id);
  if (!card) return;
  card.classList.remove('open');
  if (cardPositions[id]) {
    window.scrollTo({top: cardPositions[id] - 20, behavior: 'smooth'});
  }
}

function lazyLoadGallery(id) {
  var imgs = document.querySelectorAll('#card-' + id + ' .gallery-img');
  imgs.forEach(function(img) {
    if (img.dataset.src) { img.src = img.dataset.src; img.removeAttribute('data-src'); }
  });
}

// === Filter ===
function filterChannel(ch, el) {
  currentFilter = currentFilter === ch ? '' : ch;
  document.querySelectorAll('.filter-chip').forEach(function(c){c.classList.remove('active')});
  if (currentFilter) el.classList.add('active');
  else document.querySelector('.filter-chip').classList.add('active');
  applyFilter();
}
function filterAll(el) {
  currentFilter = '';
  document.querySelectorAll('.filter-chip').forEach(function(c){c.classList.remove('active')});
  el.classList.add('active');
  applyFilter();
}
function applyFilter() {
  var cards = document.querySelectorAll('.card');
  var sections = document.querySelectorAll('.section-hd');
  var anyVisible = false;
  cards.forEach(function(c){
    var ch = c.getAttribute('data-channel');
    var show = !currentFilter || ch === currentFilter;
    c.style.display = show ? '' : 'none';
    if (show) anyVisible = true;
  });
  sections.forEach(function(s){s.style.display = currentFilter ? 'none' : ''});
  document.getElementById('empty-hint').style.display = anyVisible ? 'none' : '';
}

// === Feedback ===
function doFeedback(id, feedback, detail) {
  var card = document.getElementById('card-' + id);
  card.classList.remove('fb-asap','fb-next','fb-skip');
  if (feedback === 'checked') {
    card.classList.add(detail === 'asap' ? 'fb-asap' : 'fb-next');
  } else { card.classList.add('fb-skip'); }
  var labels = {'checked_asap':'已选:尽快安排','checked_next_trip':'已选:下次顺路时','skipped':'已跳过'};
  var lbl = document.getElementById('fb-label-' + id);
  if (lbl) lbl.textContent = labels[feedback + '_' + detail] || labels[feedback] || '';
  var body = {id: id, feedback: feedback};
  if (detail) body.detail = detail;
  fetch('/api/dj-feedback', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  }).catch(function(e){console.error(e)});
}

document.addEventListener('DOMContentLoaded', function() {
  var labels = {'checked_asap':'已选:尽快安排','checked_next_trip':'已选:下次顺路时','skipped':'已跳过'};
  function applyFeedback(fb) {
    var card = document.getElementById('card-' + fb.id);
    if (!card) return;
    var f = fb.dj_feedback, d = fb.feedback_detail || '';
    // Reset all feedback classes
    card.classList.remove('fb-asap','fb-next','fb-skip');
    if (!f) {
      var lbl = document.getElementById('fb-label-' + fb.id);
      if (lbl) lbl.textContent = '';
      return;
    }
    if (f === 'checked') card.classList.add(d === 'asap' ? 'fb-asap' : 'fb-next');
    else if (f === 'skipped') card.classList.add('fb-skip');
    var lbl = document.getElementById('fb-label-' + fb.id);
    if (lbl) lbl.textContent = labels[f + '_' + d] || labels[f] || '';
  }
  // Step 1: apply embedded initial data (fast)
  var INITIAL_FEEDBACK = {{ initial_feedback_json | safe }};
  INITIAL_FEEDBACK.forEach(applyFeedback);
  // Step 2: fetch live feedback from API (overwrites stale data)
  var cardIds = [];
  document.querySelectorAll('.card').forEach(function(c){ cardIds.push(parseInt(c.id.replace('card-',''))); });
  if (cardIds.length) {
    fetch('/api/articles-feedback', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ids: cardIds})
    }).then(function(r){ return r.json(); })
    .then(function(fbRows){
      if (Array.isArray(fbRows)) fbRows.forEach(applyFeedback);
    }).catch(function(e){ console.error('Feedback fetch failed:', e); });
  }
});
</script>
</body>
</html>"""

class _CardObj:
    def __init__(self, d: dict):
        self.id = d.get("id", 0)
        self.headline = d.get("headline", "")
        self.body = d.get("body", "")
        self.deep_dive = d.get("deep_dive", "")
        self.arrangement = d.get("arrangement", "")
        self.cautions = d.get("cautions", [])
        self.channel = d.get("channel", "")
        self.hook = d.get("hook", "")
        self.thumb = d.get("thumb", "")
        self.gallery_images = d.get("gallery_images", [])
        self.link = d.get("link", "")
        self.seq_str = d.get("seq_str", "")
        self.hard_warnings = d.get("hard_warnings", [])

def generate_report(articles: list[dict], config: dict = None, editor_note: str = "", issue_number: str = "", report_type: str = "daily", report_date: str = "") -> str | None:
    if not articles:
        return None
    now = datetime.now()
    ws = now - timedelta(days=now.weekday())
    we = ws + timedelta(days=6)
    week_num = now.isocalendar()[1]
    daily_num = 0
    if report_type == "daily":
        # 按已发布刊计数: 在 published 刊中按日期排序, 本期排第几
        try:
            from src.database import Database as _DBCount
            _db_path_count = config.get("database", {}).get("path", "data/content.db") if config else "data/content.db"
            _dbc = _DBCount(_db_path_count)
            daily_num = _dbc.get_display_number(issue_number, report_date)
        except Exception:
            daily_num = 1  # 极端兜底
    cards, skipped_ids, fb_total = [], [], 0
    hard_hit_warnings = []  # 禁词命中但不丢卡的告警
    skip_reasons = {}  # aid -> reason

    for a in articles:
        aid = a["id"]
        readiness = get_card_readiness(a)
        if not readiness["ready"]:
            skipped_ids.append(aid)
            skip_reasons[aid] = readiness.get("reason") or readiness.get("label") or "卡片未就绪"
            logger.warning(f"  #{aid} {skip_reasons[aid]}, 跳过")
            continue
        cjs = a.get("card_json", "")
        card = {}
        if isinstance(cjs, str) and cjs:
            try: card = json.loads(cjs)
            except: pass
        if not card:
            skipped_ids.append(aid)
            skip_reasons[aid] = "缺card_json"
            logger.warning(f"  #{aid} 缺card_json, 跳过(请在组刊前先成卡)")
            continue
        if not card:
            skipped_ids.append(aid); continue

        all_text = " ".join([
            card.get("body","") or "", (card.get("arrangement","") or ""), card.get("headline","") or "",
            card.get("deep_dive","") or "", " ".join((card.get("cautions") or [])),
        ])
        hits = check_field(all_text)
        hard_warnings_for_card = []
        if hits["hard"]:
            for h in hits["hard"]:
                hard_hit_warnings.append({"id": aid, "word": h, "fields": "DJ可见字段(body/deep_dive/headline等)"})
                hard_warnings_for_card.append(h)
            logger.warning(f"Article {aid} HARD filter hit (保留卡片): {hits['hard']}")
        soft_flags = hits["soft"]
        visible_images = select_h5_visible_images(a.get("images", []), max_gallery=4)
        thumb = visible_images["cover"]
        gallery = visible_images["gallery"]

        cards.append({
            "id": aid, "headline": card.get("headline", a.get("title", "")),
            "article_title": a.get("translated_title") or a.get("title", ""),
            "body": card.get("body", ""), "deep_dive": card.get("deep_dive", ""),
            "arrangement": card.get("arrangement", ""),
            "cautions": card.get("cautions", []) if isinstance(card.get("cautions"), list) else [],
            "channel": card.get("channel", a.get("category", "")),
            "hook": card.get("one_line", ""),  # 写手产的读者钩子,不再引用 gate2_one_line
            "thumb": thumb, "gallery_images": gallery, "link": a.get("url", ""),
            "soft_flags": soft_flags,
            "hard_warnings": hard_warnings_for_card,
            "feedback": a.get("dj_feedback", ""),
            "feedback_detail": a.get("feedback_detail", ""),
            "gate3_rank": a.get("gate3_rank", 99),
            "gate2_tier": a.get("gate2_tier", ""),
        })

    # === 序号分配 ===
    global_card_idx = 0
    if report_type == "daily":
        for c in cards:
            global_card_idx += 1
            c["seq_str"] = f"{global_card_idx:02d}"
    else:
        for c in cards:
            c["seq_str"] = ""

    # === 跨卡片首图去重 (渲染层, 严格限定在当期周报范围内) ===
    # 若两张卡片的封面图内容相同, 第二张起不展示封面(用频道图标代替)
    import hashlib as _hl
    _seen_thumbs: dict[str, int] = {}  # hash -> first card id
    _dup_thumbs = set()
    for _c in cards:
        _tp = _c.get("thumb", "")
        if _tp and _tp.startswith("/images/"):
            try:
                _rp = _resolve_path(_tp)
                if _rp:
                    _h = _hl.md5(_rp.read_bytes()).hexdigest()
                    if _h in _seen_thumbs:
                        _dup_thumbs.add(_c["id"])
                    else:
                        _seen_thumbs[_h] = _c["id"]
            except: pass
    if _dup_thumbs:
        logger.info(f"首图去重: {len(_dup_thumbs)} 张重复封面, 卡片ID: {sorted(_dup_thumbs)}")
        for _c in cards:
            if _c["id"] in _dup_thumbs:
                # 优先用图集中下一张不重复的图当封面
                _gallery = _c.get("gallery_images", [])
                _new_cover = ""
                for _gi in _gallery:
                    _gp = _gi if isinstance(_gi, str) else _gi.get("src", "")
                    if _gp and _gp.startswith("/images/"):
                        try:
                            _rp = _resolve_path(_gp)
                            if _rp:
                                _gh = _hl.md5(_rp.read_bytes()).hexdigest()
                                if _gh not in _seen_thumbs:
                                    _new_cover = _gp
                                    _seen_thumbs[_gh] = _c["id"]
                                    break
                        except: pass
                if _new_cover:
                    _c["thumb"] = _new_cover
                    logger.info(f"  #{_c['id']} 封面降级: 使用图集第{_gallery.index(_new_cover) if _new_cover in _gallery else '?'}张")
                else:
                    _c["thumb"] = ""
                    logger.warning(f"  #{_c['id']} 封面降级: 无可用图集,使用频道图标")

    if not cards:
        logger.error("All articles filtered out"); return None

    if report_type == "daily":
        # 日报: 全列平铺, 序号连续
        sections = [{"name": "精选推荐", "icon": "", "articles": [_CardObj(c) for c in cards]}]
        CHANNEL_ORDER = ['艺术与文化', '建筑与空间', '科技与生活', '产品与设计', '旅行与探索', '精品酒店与度假', '音乐与演出', '健康与养生', '时尚与风格', '汽车与出行', '珠宝与腕表', '美食与美酒']
        channels = sorted(set(c["channel"] or "艺术与文化" for c in cards),
                         key=lambda n: CHANNEL_ORDER.index(n) if n in CHANNEL_ORDER else len(CHANNEL_ORDER))
    else:
        # 周报: 按频道分组
        cg: dict[str, list] = {}
        for c in cards:
            ch = c["channel"] or "艺术与文化"
            cg.setdefault(ch, []).append(c)
        CHANNEL_ORDER = ['艺术与文化', '建筑与空间', '科技与生活', '产品与设计', '旅行与探索', '精品酒店与度假', '音乐与演出', '健康与养生', '时尚与风格', '汽车与出行', '珠宝与腕表', '美食与美酒']
        def _ord(n): return CHANNEL_ORDER.index(n) if n in CHANNEL_ORDER else len(CHANNEL_ORDER)
        sections, channels = [], []
        for ch_name in sorted(cg.keys(), key=_ord):
            sections.append({"name": ch_name, "icon": CATEGORY_SVG.get(ch_name, ""), "articles": [_CardObj(c) for c in cg[ch_name]]})
            channels.append(ch_name)

    display_num = issue_number or str(week_num)
    if report_type == "daily":
        display_num = issue_number or str(daily_num)
    
    # Build initial feedback data for embedded JS (no fetch needed)
    import json as _json
    initial_feedback_json = "[]"
    try:
        from src.database import Database as _DB
        _db_path = config.get("database", {}).get("path", "data/content.db") if config else "data/content.db"
        _db = _DB(_db_path)
        _article_ids = [c["id"] for c in cards]
        _fb_rows = _db.get_articles_feedback(_article_ids)
        initial_feedback_json = _json.dumps(_fb_rows, ensure_ascii=False)
    except Exception as _e:
        logger.warning(f"无法加载反馈数据到 H5: {_e}")
    
    if report_type == "daily":
        title_str = f"高品质生活体验日报 第{display_num}期"
        issue_str = f"第 {display_num} 期"
        date_str = (datetime.strptime(report_date, "%Y-%m-%d") if report_date else now).strftime("%Y.%m.%d")
    else:
        title_str = f"高品质生活体验周报 第{display_num}期"
        issue_str = f"第 {display_num} 期"
        date_str = f"{ws.strftime('%Y.%m.%d')} — {we.strftime('%Y.%m.%d')}"

    warnings_html = ""
    if hard_hit_warnings:
        card_lookup = {c["id"]: c for c in cards}
        warnings_html = '<div style="margin:12px 16px;padding:12px 16px;background:#fff3cd;border:2px solid #ffc107;border-radius:8px;font-size:12px;line-height:1.8;color:#856404;">'
        warnings_html += '<div style="font-weight:700;font-size:13px;margin-bottom:6px;">⚠️ 禁词告警 — 以下卡片命中禁词但已保留，请人工复核：</div>'
        for w in hard_hit_warnings:
            card = card_lookup.get(w["id"], {})
            seq = card.get("seq_str") or "?"
            headline = _html.escape((card.get("article_title") or card.get("headline") or "未命名卡片")[:80])
            word = _html.escape(str(w["word"]))
            fields = _html.escape(str(w["fields"]))
            warnings_html += f'<div>· 第{seq}张《{headline}》 · ID#{w["id"]} — <b>{word}</b> — {fields}</div>'
        warnings_html += '</div>'

    html = Template(TEMPLATE).render(
        title=title_str,
        issue_label=issue_str,
        date_range=date_str,
        editor_note=editor_note, sections=sections, channels=channels,
        warnings=warnings_html,
        issue_number=display_num,
        initial_feedback_json=initial_feedback_json,
        report_type=report_type,
    )
    out_dir = Path(config.get("report",{}).get("output_dir","output") if config else "output")
    out_dir.mkdir(parents=True, exist_ok=True)
    if report_type == "daily":
        prefix = "daily_report"
        label = "日报"
        fname_num = display_num
    else:
        prefix = "weekly_report"
        label = "周报"
        fname_num = issue_number or display_num
    file_date = (datetime.strptime(report_date, "%Y-%m-%d") if report_date else now).strftime("%Y%m%d")
    fp = out_dir / f"{prefix}_{fname_num}_{file_date}.html"
    fp.write_text(html, encoding="utf-8")
    # === 完整性断言: 若出卡数 < 入选题数, 大声打日志 ===
    input_count = len(articles)
    output_count = len(cards)
    if output_count < input_count:
        gap = input_count - output_count
        logger.error(f"⚠️ 出卡不足: 选题{input_count}篇 → 出卡{output_count}篇, 丢了{gap}篇!")
        for aid in skipped_ids:
            reason = skip_reasons.get(aid, "未知原因")
            logger.error(f"  丢失ID={aid}: {reason}")
        article_id_set = {a["id"] for a in articles}
        unaccounted = article_id_set - set(c["id"] for c in cards) - set(skipped_ids)
        if unaccounted:
            logger.error(f"  ⚠️ 以下ID丢失但未记录跳过原因: {sorted(unaccounted)}")
    else:
        logger.info(f"✅ 出卡完整: 选题{input_count}篇 → 出卡{output_count}篇, 无丢失")
    logger.info(f"{label}: {fp} ({len(html)//1024}KB) cards={output_count} skipped={len(skipped_ids)} fb={fb_total}")
    return str(fp)

def _pj(val):
    if isinstance(val, list): return val
    if isinstance(val, str) and val:
        try: return json.loads(val)
        except: return []
    return []

def _is_junk_image(path: str) -> bool:
    return is_junk_image(path)

def _resolve_path(path: str) -> Path | None:
    return resolve_image_path(path)

def _to_data(path: str, url: str = "") -> str:
    return image_to_static_url(path)
