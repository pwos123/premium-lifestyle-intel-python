#!/usr/bin/env python3
"""
同步审核结果 — 从浏览器 localStorage 导出的 decisions 更新数据库
支持: candidate(入选) / maybe(候补) / rejected(淘汰)

用法: 
  1. 在审核页面完成筛选
  2. 在浏览器控制台(F12)运行:
     copy(JSON.stringify(localStorage.getItem('review_decisions_v2')))
  3. 将结果粘贴到 review_decisions.json
  4. 运行: python sync_reviews.py
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from src.database import Database

db = Database("data/content.db")

dec_file = Path("review_decisions.json")
if not dec_file.exists():
    print("❌ 未找到 review_decisions.json")
    print("请在审核页面按 F12，控制台输入：")
    print('  copy(localStorage.getItem("review_decisions_v2"))')
    print("然后粘贴到 review_decisions.json 文件中")
    sys.exit(1)

decisions_raw = json.loads(dec_file.read_text())
# decisions_raw 是字符串 "{\"id\":\"status\",...}"
if isinstance(decisions_raw, str):
    decisions = json.loads(decisions_raw)
else:
    decisions = decisions_raw

ok = 0
for article_id_str, status in decisions.items():
    try:
        db.review_article(int(article_id_str), status)
        ok += 1
    except Exception as e:
        print(f"  ⚠️  article {article_id_str}: {e}")

stats = db.get_stats()
print(f"✅ 同步完成: {ok} 条审核结果")
print(f"   待审核: {stats['pending']} | 已入选: {stats['candidate']} | 已拒绝: {stats['rejected']}")
