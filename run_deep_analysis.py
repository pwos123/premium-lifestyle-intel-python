#!/usr/bin/env python3
"""批量深度分析已采纳文章（三模型交叉验证）"""

import sys, json, logging, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.ai_analyzer import AIAnalyzer
from src.database import Database
from src.config import load_config, load_model_configs

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def main():
    CONFIG = load_config()

    db = Database(CONFIG["database"]["path"])
    
    analyzer = AIAnalyzer(load_model_configs(CONFIG))
    if not analyzer.llm.available_models:
        logger.error("未配置模型 API Key，请先设置环境变量")
        return
    
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, content, source, category FROM articles WHERE status='approved' AND (pros = '[]' OR pros IS NULL OR pros = '') ORDER BY score DESC"
        ).fetchall()
    
    logger.info(f"需要深度分析: {len(rows)} 篇文章")
    
    success = 0
    fail = 0
    
    for i, row in enumerate(rows):
        aid = row[0]
        title = row[1]
        content = row[2] or ""
        source = row[3] or ""
        category = row[4] or ""
        
        logger.info(f"[{i+1}/{len(rows)}] 深度分析: {title[:50]}...")
        
        try:
            result = analyzer.analyze_article(
                title=title, content=content, source=source, category_hint=category,
            )
            db.update_article(aid, {
                "summary": result.get("summary", ""),
                "translated_title": result.get("translated_title", ""),
                "translated_content": result.get("translated_content", ""),
                "category": result.get("category", category),
                "score": result.get("score", 0),
                "tags": result.get("tags", []),
                "recommend_reason": result.get("recommend_reason", ""),
                "scenario": result.get("scenario", ""),
                "pros": result.get("pros", []),
                "cons": result.get("cons", []),
                "recommend_level": result.get("recommend_level", "了解"),
                "is_relevant": 1 if result.get("is_relevant", True) else 0,
                "model_votes": result.get("model_votes", {}),
            })
            success += 1
            logger.info(f"  OK 分类={result.get('category','')} 评分={result.get('score',0)}")
        except Exception as e:
            fail += 1
            logger.error(f"  FAIL: {e}")
        
        time.sleep(1)
    
    logger.info(f"深度分析完成: 成功 {success} | 失败 {fail}")

if __name__ == "__main__":
    main()
