#!/usr/bin/env python3
"""
审核页面入口 — 三关打分体系工作台
用法: python run_review.py
"""

import json
import logging
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from src.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REVIEW_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>文章审核 — 三关工作台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"PingFang SC",sans-serif;background:#0a0a0f;color:#e0e0e0;min-height:100vh}
.hdr{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:20px 24px;border-bottom:1px solid #c9a96e22;position:sticky;top:0;z-index:100}
.hdr h1{font-size:18px;color:#c9a96e;font-weight:600}
.hdr .stats{font-size:12px;color:#888;margin-top:4px}
.toolbar{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;align-items:center}
.toolbar button{padding:5px 14px;border:1px solid #c9a96e44;background:transparent;color:#c9a96e;border-radius:4px;cursor:pointer;font-size:12px;transition:all .2s}
.toolbar button:hover{background:#c9a96e22}
.toolbar button.on{background:#c9a96e;color:#0a0a0f}
.toolbar .batch{background:#2d7a3a;border-color:#2d7a3a;color:#fff;margin-left:auto}
.tier-badge{padding:2px 10px;border-radius:4px;font-size:11px;font-weight:800;letter-spacing:.5px}
.tier-A{background:#c9a96e;color:#0a0a0f}
.tier-B{background:#4a90d9;color:#fff}
.tier-C{background:#555;color:#ccc}
.tier-D{background:#3a1a1a;color:#c44}
.funnel{font-size:11px;color:#666;margin-left:12px}
.funnel span{color:#c9a96e;font-weight:600}
.container{max-width:880px;margin:0 auto;padding:16px}
.card{background:#1a1a2e;border:1px solid #fff1;border-radius:12px;margin-bottom:14px;overflow:hidden;transition:border-color .2s}
.card:hover{border-color:#c9a96e44}
.card.done{opacity:.35;pointer-events:none}
.card-img{width:100%;height:200px;object-fit:cover;display:block}
.card-body{padding:14px 18px}
.meta{display:flex;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap}
.badge-cat{padding:2px 8px;background:#fff1;border-radius:3px;font-size:10px;color:#aaa}
.dims{font-size:11px;color:#888;margin-left:4px}
.src{font-size:11px;color:#555}
.title{font-size:16px;font-weight:600;color:#fff;margin-bottom:6px;line-height:1.4}
.one-line{font-size:13px;color:#c9a96e;margin-bottom:8px;padding:4px 10px;background:#c9a96e0a;border-radius:4px;border-left:2px solid #c9a96e44}
.rationale{font-size:12px;color:#a0c4ff;padding:6px 10px;background:#a0c4ff0a;border-left:2px solid #a0c4ff44;border-radius:0 4px 4px 0;margin-bottom:8px}
.summary{font-size:13px;color:#aaa;line-height:1.7;margin-bottom:8px}
.fit-tags{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px}
.fit-tags span{padding:2px 8px;background:#c9a96e18;border:1px solid #c9a96e22;border-radius:3px;font-size:10px;color:#c9a96e}
.score{font-size:13px;font-weight:600;color:#999}
.failed{font-size:11px;color:#c44;padding:4px 8px;background:#c4418;border-radius:3px;margin-bottom:6px}
.actions{display:flex;gap:8px;padding-top:10px;border-top:1px solid #fff1}
.actions button{flex:1;padding:8px;border:none;border-radius:6px;font-size:13px;cursor:pointer;font-weight:600;transition:all .2s}
.btn-ok{background:#2d7a3a;color:#fff}
.btn-ok:hover{background:#388e3c}
.btn-no{background:#c62828;color:#fff}
.btn-no:hover{background:#e53935}
.btn-maybe{background:#c9a96e;color:#0a0a0f}
.btn-maybe:hover{background:#d4b87a}
.url{font-size:11px;color:#444;margin-top:6px;word-break:break-all}
.url a{color:#6a9fd8;text-decoration:none}
.empty{text-align:center;color:#555;padding:60px 20px;font-size:15px}
.section-label{font-size:10px;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px}
</style>
</head>
<body>
<div class="hdr">
  <h1>📋 文章审核 — 三关工作台</h1>
  <div class="stats">
    漏斗: <span class="funnel"><span>{{ g1_total }}</span>→G1</span>
    <span class="funnel"><span>{{ g1_pass }}</span>→G2</span>
    <span class="funnel"><span>{{ g2_ab }}</span>→G3</span>
    <span class="funnel"><span>{{ g3_sel }}</span>入选</span>
    &nbsp;|&nbsp; 待审核: {{ pending }} | 已通过: {{ approved }} | 已拒绝: {{ rejected }}
  </div>
  <div class="toolbar">
    <button class="on" onclick="filterAll(this)">全部</button>
    <button onclick="filterTier('A',this)">A档</button>
    <button onclick="filterTier('B',this)">B档</button>
    <button onclick="filterTier('C',this)">C档</button>
    <button onclick="filterTier('D',this)">D档</button>
    {% for cat in categories %}
    <button onclick="filterCat('{{ cat }}',this)">{{ cat }}</button>
    {% endfor %}
    <button class="batch" onclick="approveAll()">✅ 全部通过</button>
  </div>
</div>
<div class="container">
{% for a in articles %}
<div class="card" id="c{{ a.id }}" data-tier="{{ a.tier }}" data-cat="{{ a.category }}" data-status="pending">
  {% if a.images %}
  <img class="card-img" src="{{ a.images[0] }}" loading="lazy" onerror="this.style.display='none'">
  {% endif %}
  <div class="card-body">
    <div class="meta">
      <span class="tier-badge tier-{{ a.tier }}">{{ a.tier }}档</span>
      {% if a.gate3_rank %}<span style="font-size:11px;color:#c9a96e">⭐#{{ a.gate3_rank }}</span>{% endif %}
      <span class="dims">兴奋{{ a.dim_excitement }} 落地{{ a.dim_feasibility }} 密度{{ a.dim_density }}</span>
      <span class="badge-cat">{{ a.category }}</span>
      <span class="src">{{ a.source }}</span>
      {% if a.score %}<span class="score">{{ a.score }}分</span>{% endif %}
    </div>
    <div class="title">{{ a.title }}</div>
    {% if a.one_line %}<div class="one-line">🎯 {{ a.one_line }}</div>{% endif %}
    {% if a.rationale %}<div class="rationale">🏆 {{ a.rationale }}</div>{% endif %}
    <div class="summary">{{ a.summary }}</div>
    {% if a.fit_reasons %}
    <div class="fit-tags">
      {% for t in a.fit_reasons %}<span>{{ t }}</span>{% endfor %}
    </div>
    {% endif %}
    {% if a.failed_checks %}
    <div class="failed">⚠️ 未通过: {{ a.failed_checks }}</div>
    {% endif %}
    {% if a.needs_human %}
    <div style="font-size:11px;color:#ffb74d;margin-bottom:6px">🔍 需人工复核</div>
    {% endif %}
    <div class="actions">
      <button class="btn-ok" onclick="doReview({{ a.id }},'candidate',this)">✅ 入选</button>
      <button class="btn-maybe" onclick="doReview({{ a.id }},'maybe',this)">🤔 候补</button>
      <button class="btn-no" onclick="doReview({{ a.id }},'rejected',this)">❌ 淘汰</button>
    </div>
    <div class="url"><a href="{{ a.url }}" target="_blank">{{ a.url[:80] }}</a></div>
  </div>
</div>
{% endfor %}
{% if not articles %}<div class="empty">暂无待审核文章,请先运行 python run_crawl.py</div>{% endif %}
</div>

<script>
const STORAGE_KEY = 'review_decisions_v2';
function getDecisions(){try{return JSON.parse(localStorage.getItem(STORAGE_KEY)||'{}')}catch(e){return{}}}
function saveDecisions(d){localStorage.setItem(STORAGE_KEY,JSON.stringify(d))}

function doReview(id, status, btn) {
  const card = document.getElementById('c'+id);
  card.classList.add('done');
  card.dataset.status = status;
  const decisions = getDecisions();
  decisions[id] = status;
  saveDecisions(decisions);
}

function approveAll() {
  if(!confirm('确认通过所有待审核文章？')) return;
  document.querySelectorAll('.card[data-status="pending"]').forEach(card => {
    const id = card.id.replace('c','');
    doReview(parseInt(id), 'candidate', null);
  });
}

function filterAll(btn) {
  document.querySelectorAll('.toolbar button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.card').forEach(c=>c.style.display='');
}

function filterTier(tier, btn) {
  document.querySelectorAll('.toolbar button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = c.dataset.tier === tier ? '' : 'none';
  });
}

function filterCat(cat, btn) {
  document.querySelectorAll('.toolbar button').forEach(b=>b.classList.remove('on'));
  btn.classList.add('on');
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = c.dataset.cat === cat ? '' : 'none';
  });
}

(function(){
  const d = getDecisions();
  for(const[id, status] of Object.entries(d)) {
    const card = document.getElementById('c'+id);
    if(card) { card.classList.add('done'); card.dataset.status = status; }
  }
})();
</script>
</body>
</html>"""


def generate_review_page(db_path: str = "data/content.db", output: str = "output/review.html"):
    """生成三关审核页面"""
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    db = Database(db_path)

    # 获取待审核文章(三关已跑,按tier+gate3_rank排序)
    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM articles
               WHERE status='pending' AND gate2_tier IS NOT NULL
               ORDER BY
                 CASE gate2_tier WHEN 'A' THEN 1 WHEN 'B' THEN 2 WHEN 'C' THEN 3 ELSE 4 END,
                 COALESCE(gate3_rank, 999),
                 score DESC
               LIMIT 50"""
        ).fetchall()
        articles = [db._row_to_dict(r) for r in rows]

    stats = db.get_stats()
    gate_stats = db.get_gate_stats()

    # 序列化 JSON 字段
    for a in articles:
        for field in ("images", "tags", "pros", "cons", "fit_reasons"):
            key = field if field != "fit_reasons" else "gate2_fit_reasons"
            val = a.get(key)
            if isinstance(val, str):
                try:
                    a[key] = json.loads(val)
                except:
                    a[key] = []
        for field in ("gate1_failed_checks",):
            val = a.get(field)
            if isinstance(val, str):
                try:
                    a[field] = json.loads(val)
                except:
                    a[field] = []

        # 映射新字段到模板变量
        a["tier"] = a.get("gate2_tier") or "?"
        a["dim_excitement"] = a.get("gate2_dim_excitement") or 0
        a["dim_feasibility"] = a.get("gate2_dim_feasibility") or 0
        a["dim_density"] = a.get("gate2_dim_density") or 0
        a["one_line"] = a.get("gate2_one_line") or ""
        a["fit_reasons"] = a.get("gate2_fit_reasons") or []
        a["rationale"] = a.get("gate3_rationale") or ""
        a["gate3_rank"] = a.get("gate3_rank") or 0
        a["failed_checks"] = ", ".join(a.get("gate1_failed_checks") or []) if a.get("gate1_failed_checks") else ""
        a["needs_human"] = a.get("gate1_needs_human")

        if not isinstance(a.get("images"), list):
            a["images"] = []
        if not isinstance(a.get("tags"), list):
            a["tags"] = []

        # 图片转绝对路径
        abs_images = []
        for img in a["images"]:
            abs_path = Path(img).resolve()
            if abs_path.exists():
                abs_images.append(str(abs_path))
            else:
                abs_images.append(img)
        a["images"] = abs_images

    categories = list(set(a.get("category", "") for a in articles if a.get("category")))

    from jinja2 import Template
    template = Template(REVIEW_HTML)
    html = template.render(
        articles=articles,
        pending=stats["pending"],
        approved=stats["candidate"],
        rejected=stats["rejected"],
        categories=categories,
        g1_total=gate_stats["total_pending"],
        g1_pass=gate_stats["gate1_pass"],
        g2_ab=gate_stats["gate2_A"] + gate_stats["gate2_B"],
        g3_sel=gate_stats["gate3_selected"],
    )

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logger.info(f"✅ 审核页面已生成: {output_path} ({len(html)//1024}KB)")
    return str(output_path)


if __name__ == "__main__":
    output = generate_review_page()
    webbrowser.open(f"file://{Path(output).absolute()}")
