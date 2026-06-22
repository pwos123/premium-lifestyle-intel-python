#!/usr/bin/env python3
"""
回归测试 — 跑固定用例,验证 prompt 改动后行为
用法: python tests/run_regression.py [--case wabi_sabi_hotel] [--dry-run]
"""

import sys, json, logging, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import LLMCaller, ModelConfig
from src.config import load_config, load_model_configs
from prompts.gate1_pass_fail import GATE1_SYSTEM_PROMPT
from prompts.veto_check import VETO_CHECK_PROMPT
from prompts.gate2_dj_tier import GATE2_SYSTEM_PROMPT, check_fit_forbidden
from tests.regression_fixtures import ALL_CASES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("regression")


def run_gate1_test(case, caller, provider):
    """Mock run gate1 against a test case"""
    prompt = f"""请检查以下文章:

article_id: {case['id']}
标题: {case['title']}
英文原题: {case['title']}
摘要: {case['summary']}
正文开头: {(case.get('content', '') or '')[:500]}
配图URL列表首图: https://example.com/img.jpg
信源: test
频道: 艺术与文化

请按照系统提示中的 JSON 格式输出检查结果。"""

    system_prompt = GATE1_SYSTEM_PROMPT.format(current_date="2026-06-20")
    result = caller.call_model(provider, system_prompt, prompt,
                               temperature=0.2, max_tokens=800, timeout=30)
    return result


def run_veto_test(case, caller, provider):
    """Mock run veto check against a test case"""
    prompt = f"""请判断以下内容是否命中禁区:

article_id: {case['id']}
标题: {case['title']}
摘要: {case['summary']}
正文: {(case.get('content', '') or '')[:2000]}
频道: 艺术与文化
信源: test

请按照系统提示中的 JSON 格式输出判断结果。"""

    result = caller.call_model(provider, VETO_CHECK_PROMPT, prompt,
                               temperature=0.1, max_tokens=400, timeout=30)
    return result


def run_gate2_test(case, caller, provider):
    """Mock run gate2 against a test case"""
    prompt = f"""请分析以下内容:

article_id: {case['id']}
标题: {case['title']}
摘要: {case['summary']}
正文: {(case.get('content', '') or '')[:1500]}
频道: 艺术与文化
信源: test

请按照系统提示中的 JSON 格式输出分析结果。"""

    result = caller.call_model(provider, GATE2_SYSTEM_PROMPT, prompt,
                               temperature=0.3, max_tokens=1200, timeout=60)
    return result


def check_fit_reasons(fit_reasons, category=""):
    """Check if fit_reasons contain forbidden keywords (with channel scope)"""
    if not fit_reasons:
        return []
    return check_fit_forbidden(fit_reasons, category)


def run_local_helper_tests():
    results = {"pass": 0, "fail": 0}
    logger.info("\n--- 本地辅助函数测试 ---")
    try:
        from run_generate_cards import _clamp_text_at_boundary
        from run_gate1 import build_gate1_system_prompt

        long_text = (
            "第一句交代项目的核心做法。"
            "第二句补充材料和空间关系。"
            "第三句说明为什么值得展开阅读。"
            "第四句本来会超过限制但不应该被截成半句话。"
        )
        clamped = _clamp_text_at_boundary(long_text, 48, min_len=10)
        assert len(clamped) <= 48, f"clamped text too long: {len(clamped)}"
        assert clamped.endswith("。"), f"clamped text should end at sentence boundary: {clamped}"
        no_boundary = "这是一个没有明显停顿的超长字段" * 20
        fallback = _clamp_text_at_boundary(no_boundary, 50, min_len=10)
        assert len(fallback) <= 50, f"fallback too long: {len(fallback)}"
        assert fallback.endswith("…"), "fallback should mark ellipsis when no boundary exists"
        gate1_prompt = build_gate1_system_prompt()
        assert "{current_date}" not in gate1_prompt, "Gate1 current_date placeholder was not formatted"
        logger.info("  ✅ 文案收口不会硬切半句话")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 本地辅助函数测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1
    try:
        broken_title_json = """{
"article_id":"2643",
"title":""This is the best thing H&dM has done" says commenter",
"verdict":"pass",
"failed_checks":[],
"needs_human":false
}"""
        parsed = LLMCaller._parse_json_response(broken_title_json)
        assert parsed["article_id"] == "2643", parsed
        assert parsed["verdict"] == "pass", parsed
        assert "title" not in parsed, parsed
        logger.info("  ✅ Gate JSON 标题坏引号可剥离解析")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ Gate JSON 解析兜底测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1
    try:
        import tempfile
        from src.crawler import Crawler

        crawler = Crawler(site_timeout=180, image_cache_dir=tempfile.mkdtemp())
        assert crawler._site_outer_timeout({}) == 225.0
        assert crawler._site_outer_timeout({"site_timeout": 240}) == 300.0
        assert crawler._site_outer_timeout({"site_timeout": 40}) == 85.0
        logger.info("  ✅ 爬虫外层超时为部分结果留出回传余量")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 爬虫超时兜底测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1
    try:
        from src.parser import ContentParser

        parser = ContentParser()
        html = """
        <html><body>
          <img src="https://images.fie.futurecdn.net/lz2xjwnphyxhiqek-17745299135936-250-80.jpg.webp">
          <img src="https://cdn.mos.cms.futurecdn.net/Gksv8HM2gLnpcijk3i63RT-900-80.jpg">
          <article>
            <p>第一段正文，说明这个空间项目的背景。</p>
            <p>第二段正文，提供足够段落让正文容器被识别。</p>
            <img src="https://cdn.mos.cms.futurecdn.net/realArticleOne-1920-80.jpg">
            <img src="https://cdn.mos.cms.futurecdn.net/realArticleTwo-1600-80.jpg">
          </article>
        </body></html>
        """
        images = parser.parse_article(html, "https://www.wallpaper.com/test", {"image": "img"})["images"]
        assert images[0].endswith("realArticleOne-1920-80.jpg"), images
        assert "lz2xjwnphyxhiqek" not in images[0], images
        logger.info("  ✅ Wallpaper 通用资源不会挤占正文图首位")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 图片排序测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1
    try:
        from services.image_merge import merge_article_images

        merged = merge_article_images(
            ["/data/images/original.jpg", "/data/images/manual_42_a.webp"],
            ["/data/images/original.jpg", "/data/images/new_gallery.jpg"],
            max_images=5,
        )
        assert merged == [
            "/data/images/original.jpg",
            "/data/images/manual_42_a.webp",
            "/data/images/new_gallery.jpg",
        ], merged
        logger.info("  ✅ 图片合并保留人工图并追加新抓图")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 图片合并测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1
    return results


def run_all_tests(dry_run=False):
    config = load_config()
    model_configs = load_model_configs(config)

    if not model_configs:
        logger.error("未配置任何模型")
        return

    # Setup callers
    qwen_cfg = model_configs.get("qwen")
    if not qwen_cfg:
        logger.error("qwen 未配置")
        return

    gate1_mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url,
                           model="qwen-flash", weight=1.0)
    gate1_caller = LLMCaller({"qwen": gate1_mc})

    gate2_mc = ModelConfig(name="qwen", api_key=qwen_cfg.api_key, base_url=qwen_cfg.base_url,
                           model="qwen-plus", weight=1.0)
    gate2_caller = LLMCaller({"qwen": gate2_mc})

    results = {"pass": 0, "fail": 0, "error": 0}
    details = {}
    helper_results = run_local_helper_tests()
    results["pass"] += helper_results["pass"]
    results["fail"] += helper_results["fail"]

    for name, case in ALL_CASES.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"测试用例: {name}")
        logger.info(f"标题: {case['title'][:80]}")

        expected = case["expected"]
        test_passed = True
        case_detail = {}

        try:
            if "gate1_verdict" in expected:
                # Gate1 test
                r = run_gate1_test(case, gate1_caller, "qwen")
                if r.success and r.data:
                    verdict = r.data.get("verdict", "?")
                    failed = r.data.get("failed_checks", [])
                    case_detail["gate1_verdict"] = verdict
                    case_detail["gate1_failed"] = failed

                    exp_fail_keyword = expected.get("gate1_failed_contains", "")
                    if verdict == "fail" and exp_fail_keyword and any(exp_fail_keyword in str(f) for f in failed):
                        logger.info(f"  ✅ Gate1 FAIL (expected), 命中: {failed}")
                    elif verdict == expected.get("gate1_verdict"):
                        logger.info(f"  ✅ Gate1 {verdict} (expected)")
                    else:
                        logger.warning(f"  ❌ Gate1 {verdict} (expected {expected['gate1_verdict']}), failed_checks={failed}")
                        test_passed = False
                else:
                    logger.error(f"  Gate1 调用失败: {r.error}")
                    test_passed = False
                    case_detail["error"] = r.error

            elif "veto_hit" in expected:
                # Veto test
                r = run_veto_test(case, gate1_caller, "qwen")
                if r.success and r.data:
                    veto_hit = r.data.get("veto_hit", False)
                    veto_rule = r.data.get("veto_rule", "")
                    case_detail["veto_hit"] = veto_hit
                    case_detail["veto_rule"] = veto_rule

                    if veto_hit == expected["veto_hit"]:
                        rule_ok = True
                        if expected.get("veto_rule_contains"):
                            rule_ok = expected["veto_rule_contains"] in str(veto_rule).lower()
                        if rule_ok:
                            logger.info(f"  ✅ Veto hit={veto_hit} rule={veto_rule}")
                        else:
                            logger.warning(f"  ❌ veto_rule 不包含 '{expected['veto_rule_contains']}': {veto_rule}")
                            test_passed = False
                    else:
                        logger.warning(f"  ❌ Veto hit={veto_hit} (expected {expected['veto_hit']})")
                        test_passed = False

                    # Also verify gate2 would be D if veto hit
                    if veto_hit and "gate2_tier" in expected:
                        logger.info(f"  ℹ️  否决命中 → 应跳过 Gate2,标记 D 档")
                else:
                    logger.error(f"  Veto 调用失败: {r.error}")
                    test_passed = False
                    case_detail["error"] = r.error

            if ("gate2_tier" in expected or "gate2_tier_not" in expected) and not case_detail.get("veto_hit"):
                # Gate2 test (only if not vetoed)
                r = run_gate2_test(case, gate2_caller, "qwen")
                if r.success and r.data:
                    tier = r.data.get("tier", "?")
                    fit_reasons = r.data.get("fit_reasons", [])
                    case_detail["gate2_tier"] = tier
                    case_detail["fit_reasons"] = fit_reasons

                    if "gate2_tier_not" in expected:
                        not_tier = expected["gate2_tier_not"]
                        if tier != not_tier:
                            logger.info(f"  ✅ Gate2 tier={tier} (非{not_tier}, 正常流转)")
                        else:
                            logger.warning(f"  ❌ Gate2 tier={tier} (应为非{not_tier}档)")
                            test_passed = False
                    elif tier == expected.get("gate2_tier"):
                        logger.info(f"  ✅ Gate2 tier={tier} (expected)")
                    else:
                        logger.warning(f"  ❌ Gate2 tier={tier} (expected {expected['gate2_tier']})")
                        test_passed = False

                    # Check fit_reasons cleanliness
                    if expected.get("fit_reasons_clean"):
                        hits = check_fit_reasons(fit_reasons, "艺术与文化")
                        if hits:
                            logger.warning(f"  ❌ fit_reasons 含禁区词: {hits}")
                            test_passed = False
                        else:
                            logger.info(f"  ✅ fit_reasons 不含禁区词")
                else:
                    logger.error(f"  Gate2 调用失败: {r.error}")
                    test_passed = False
                    case_detail["error"] = r.error

            if "fit_reasons_contains_forbidden" in expected:
                # Test fit_reasons keyword detection (offline, no API needed)
                fit_reasons = case.get("mock_fit_reasons",
                    ["侘寂风格与服务对象艺术坐标高度契合", "茶道文化深度体验"])
                hits = check_fit_reasons(fit_reasons, "艺术与文化")
                case_detail["fit_reasons"] = fit_reasons
                case_detail["forbidden_hits"] = hits

                if hits and expected["fit_reasons_contains_forbidden"]:
                    logger.info(f"  ✅ 禁区词检测命中: {hits}")
                    logger.info(f"  ℹ️  应被拦入待人工队列 (action={expected.get('action', '?')})")
                elif not hits and not expected["fit_reasons_contains_forbidden"]:
                    logger.info(f"  ✅ 无禁区词命中")
                else:
                    logger.warning(f"  ❌ 禁区词检测预期不符: hits={hits}")
                    test_passed = False

        except Exception as e:
            logger.error(f"  异常: {e}")
            test_passed = False
            case_detail["error"] = str(e)

        details[name] = {"passed": test_passed, "detail": case_detail}
        if test_passed:
            results["pass"] += 1
        else:
            results["fail"] += 1

    logger.info(f"\n{'='*60}")
    logger.info(f"回归测试完成: pass={results['pass']} fail={results['fail']} error={results['error']}")
    for name, d in details.items():
        status = "✅" if d["passed"] else "❌"
        logger.info(f"  {status} {name}")

    return results, details




# ===== 新增: 生命周期离线测试 =====

def run_lifecycle_tests():
    """Run offline lifecycle tests (carryover, expiry, issue closure)"""
    from src.database import Database
    import tempfile, os

    db_path = os.path.join(tempfile.gettempdir(), "test_lifecycle.db")
    try:
        os.remove(db_path)
    except:
        pass

    db = Database(db_path)

    results = {"pass": 0, "fail": 0}

    # --- Test 1: Carryover flow ---
    logger.info("\n--- 顺延流转测试 ---")
    try:
        # Insert a candidate article
        aid = db.insert_article({
            "url": "https://test.example.com/carryover",
            "title": "Test Carryover Article",
            "category": "艺术与文化",
            "score": 85,
            "status": "candidate",
            "gate2_tier": "A",
        })
        assert aid, "Failed to insert article"

        # First carryover (not selected)
        db.carryover_candidates([999])  # article not in excluded list
        a = db.get_article(aid)
        assert a["carryover_count"] == 1, f"Expected carryover_count=1, got {a['carryover_count']}"
        assert a["status"] == "candidate", f"Expected status=candidate, got {a['status']}"
        logger.info("  ✅ 第一次顺延: carryover_count=1, 仍为候选")

        # Second carryover (still not selected)
        db.carryover_candidates([999])
        a = db.get_article(aid)
        sink_enabled = load_config().get("throttle", {}).get("carryover_sink_enabled", True)
        if sink_enabled:
            assert a["status"] == "sunk", f"Expected status=sunk, got {a['status']}"
            assert a["archive_reason"] == "顺延超限", f"Expected 顺延超限, got {a['archive_reason']}"
            logger.info("  ✅ 第二次顺延: 转入沉库, 原因=顺延超限")
        else:
            assert a["status"] == "candidate", f"Expected status=candidate, got {a['status']}"
            assert a["carryover_count"] == 2, f"Expected carryover_count=2, got {a['carryover_count']}"
            logger.info("  ✅ 第二次顺延: 配置关闭沉库, carryover_count=2")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 顺延测试失败: {e}")
        results["fail"] += 1

    # --- Test 2: Expiry check ---
    logger.info("\n--- 时效出清测试 ---")
    try:
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        aid = db.insert_article({
            "url": "https://test.example.com/expired",
            "title": "Expired Exhibition",
            "category": "艺术与文化",
            "score": 80,
            "status": "candidate",
            "gate2_tier": "B",
            "expiry_date": yesterday,
        })
        assert aid, "Failed to insert article"

        stats = db.run_expiry_check()
        assert stats["archived"] >= 1, f"Expected >=1 archived, got {stats}"
        a = db.get_article(aid)
        assert a["status"] == "rejected", f"Expected rejected, got {a['status']}"
        assert a["archive_reason"] == "时效已过", f"Expected 时效已过, got {a['archive_reason']}"
        logger.info("  ✅ 过期文章自动归档: 原因=时效已过")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 时效测试失败: {e}")
        results["fail"] += 1

    # --- Test 3: Issue closure ---
    logger.info("\n--- 期刊闭环测试 ---")
    try:
        # Insert 5 candidate articles
        ids = []
        for i in range(5):
            aid = db.insert_article({
                "url": f"https://test.example.com/issue_{i}",
                "title": f"Issue Test Article {i}",
                "category": ["精品酒店与度假", "美食与美酒", "艺术与文化", "建筑与空间", "旅行与探索"][i],
                "score": 85 + i,
                "status": "candidate",
                "gate2_tier": "A" if i < 3 else "B",
            })
            assert aid, f"Failed to insert article {i}"
            ids.append(aid)

        # Create an issue with 3 articles
        selected = ids[:3]
        unselected = ids[3:]
        issue_id = db.create_issue("2026-W99", "2026-06-10", selected)
        assert issue_id, "Failed to create issue"
        logger.info(f"  ✅ 期刊创建: id={issue_id}")

        # Assign articles
        db.assign_to_issue(selected, issue_id)

        # Verify selected articles are in_issue
        for aid in selected:
            a = db.get_article(aid)
            assert a["status"] == "in_issue", f"Article {aid} not in_issue: {a['status']}"
            assert a["issue_id"] == issue_id, f"Article {aid} issue_id mismatch"
        logger.info("  ✅ 3篇文章状态已变为 in_issue, 已写入 issue_id")

        # Carryover unselected
        db.carryover_candidates(selected)

        # Verify unselected articles got carryover
        for aid in unselected:
            a = db.get_article(aid)
            assert a["carryover_count"] >= 1, f"Article {aid} carryover not incremented"
        logger.info("  ✅ 落选2篇 carryover_count+1")

        # Publish issue
        db.publish_issue(issue_id, "/output/test_report.html")
        for aid in selected:
            a = db.get_article(aid)
            assert a["status"] == "in_issue", f"Article {aid} not in_issue: {a['status']}"
        logger.info("  ✅ 发布后文章状态变为 in_issue")

        # Verify issue list
        all_issues = db.get_all_issues()
        assert len(all_issues) >= 1, "Issue list empty"
        logger.info("  ✅ 往期周报页可见")

        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 期刊闭环测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1

    # --- Test 4: pending_human isolation ---
    logger.info("\n--- 待人工隔离测试 ---")
    try:
        aid_pending_selected = db.insert_article({
            "url": "https://test.example.com/pending_selected",
            "title": "Pending Human Selected",
            "category": "艺术与文化",
            "score": 95,
            "status": "pending",
            "gate2_tier": "A",
            "gate3_selected": 1,
            "pending_human": 1,
        })
        aid_pending_candidate = db.insert_article({
            "url": "https://test.example.com/pending_candidate",
            "title": "Pending Human Candidate",
            "category": "艺术与文化",
            "score": 90,
            "status": "candidate",
            "gate2_tier": "A",
            "pending_human": 1,
        })
        assert aid_pending_selected and aid_pending_candidate, "Failed to insert pending_human fixtures"

        selected_ids = {a["id"] for a in db.get_gate3_selected(limit=100)}
        gate3_candidate_ids = {a["id"] for a in db.get_gate3_candidates(limit=100)}
        pool_ids = {a["id"] for a in db.get_candidate_pool()}

        assert aid_pending_selected not in selected_ids, "pending_human leaked into gate3_selected"
        assert aid_pending_selected not in gate3_candidate_ids, "pending_human leaked into gate3 candidates"
        assert aid_pending_candidate not in pool_ids, "pending_human leaked into candidate pool"
        logger.info("  ✅ pending_human 未进入 Gate3 入选/候选池")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 待人工隔离测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1

    # --- Test 5: Evergreen pool exclusivity ---
    logger.info("\n--- 常青库互斥归属测试 ---")
    try:
        evergreen_ab_id = db.insert_article({
            "url": "https://test.example.com/evergreen_ab",
            "title": "Evergreen AB",
            "category": "艺术与文化",
            "score": 93,
            "status": "pending",
            "gate2_tier": "A",
            "evergreen": 1,
        })
        evergreen_c_id = db.insert_article({
            "url": "https://test.example.com/evergreen_c",
            "title": "Evergreen C",
            "category": "艺术与文化",
            "score": 80,
            "status": "pending",
            "gate2_tier": "C",
            "evergreen": 1,
        })
        evergreen_candidate_id = db.insert_article({
            "url": "https://test.example.com/evergreen_candidate",
            "title": "Evergreen Candidate",
            "category": "艺术与文化",
            "score": 88,
            "status": "candidate",
            "gate2_tier": "B",
        })
        db.mark_evergreen(evergreen_candidate_id, True)
        evergreen_candidate = db.get_article(evergreen_candidate_id)
        assert evergreen_candidate["evergreen"], "mark_evergreen did not set evergreen flag"
        assert evergreen_candidate["status"] == "pending", "mark_evergreen should remove candidate status"
        db.review_article(evergreen_candidate_id, "candidate")
        moved_candidate = db.get_article(evergreen_candidate_id)
        assert moved_candidate["status"] == "candidate", "review_article should move evergreen article to candidate"
        assert not moved_candidate["evergreen"], "review_article(candidate) should remove evergreen flag"
        db.mark_evergreen(evergreen_candidate_id, True)
        featured_ids = {a["id"] for a in db.get_gate3_selected(limit=100)}
        gate3_candidate_ids = {a["id"] for a in db.get_gate3_candidates(limit=100)}
        candidate_ids = {a["id"] for a in db.get_candidate_pool()}
        evergreen_ids = {a["id"] for a in db.get_evergreen_pool()}
        assert evergreen_ab_id not in featured_ids, "evergreen A/B leaked into featured pool"
        assert evergreen_ab_id not in gate3_candidate_ids, "evergreen A/B leaked into Gate3 candidates"
        assert evergreen_candidate_id not in candidate_ids, "evergreen candidate leaked into normal candidate pool"
        assert {evergreen_ab_id, evergreen_c_id, evergreen_candidate_id}.issubset(evergreen_ids), "evergreen articles missing from evergreen pool"
        stats = db.get_stats()
        assert stats["featured"] == len(featured_ids), "Featured stats should exclude evergreen A/B"
        logger.info("  ✅ 常青文章只进常青库，不出现在精选/C档/日报候选")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 常青库互斥归属测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1

    # --- Test 6: Issue H5 readiness guard ---
    logger.info("\n--- H5 重生护栏测试 ---")
    try:
        from services.issue_builder import get_card_readiness, summarize_card_readiness, validate_issue_ready_for_h5
        from run_generate_cards import _store_card

        complete_card = json.dumps({
            "headline": "完整卡片",
            "body": "可渲染正文",
            "deep_dive": "可渲染展开详情",
        }, ensure_ascii=False)
        low_card = json.dumps({
            "headline": "低置信卡片",
            "body": "可渲染正文",
            "deep_dive": "可渲染展开详情",
            "editor_confidence": "low",
        }, ensure_ascii=False)
        body_only_card = json.dumps({
            "headline": "半张卡片",
            "body": "只有正文，没有展开详情",
        }, ensure_ascii=False)
        ready_id = db.insert_article({
            "url": "https://test.example.com/ready_card",
            "title": "Ready Card",
            "category": "艺术与文化",
            "score": 90,
            "status": "candidate",
            "gate2_tier": "A",
            "card_json": complete_card,
        })
        body_only_id = db.insert_article({
            "url": "https://test.example.com/body_only_card",
            "title": "Body Only Card",
            "category": "艺术与文化",
            "score": 89,
            "status": "candidate",
            "gate2_tier": "A",
            "card_json": body_only_card,
        })
        low_card_id = db.insert_article({
            "url": "https://test.example.com/low_card",
            "title": "Low Confidence Card",
            "category": "艺术与文化",
            "score": 87,
            "status": "candidate",
            "gate2_tier": "A",
            "card_json": low_card,
        })
        missing_id = db.insert_article({
            "url": "https://test.example.com/missing_card",
            "title": "Missing Card",
            "category": "艺术与文化",
            "score": 88,
            "status": "candidate",
            "gate2_tier": "A",
        })
        pending_id = db.insert_article({
            "url": "https://test.example.com/pending_card",
            "title": "Pending Card",
            "category": "艺术与文化",
            "score": 86,
            "status": "candidate",
            "gate2_tier": "A",
            "card_json": complete_card,
            "pending_human": 1,
        })
        pre_create_errors = validate_issue_ready_for_h5(
            {"article_ids": [ready_id, body_only_id, low_card_id]},
            db.get_articles_by_ids([ready_id, body_only_id, low_card_id]),
        )
        assert pre_create_errors, "Expected pre-create guard to block body-only and low-confidence cards"
        assert db.get_article(body_only_id)["issue_id"] is None, "Pre-create guard should not assign issue_id"
        low_readiness = get_card_readiness(db.get_article(low_card_id))
        assert low_readiness["status"] == "needs_rewrite", f"Low confidence should be card-level needs_rewrite: {low_readiness}"
        assert db.get_article(low_card_id)["pending_human"] in (0, None), "Low confidence card must not become pending_human"
        db.update_article(low_card_id, {"card_status": "approved", "card_review_reason": "manual_approved"})
        assert get_card_readiness(db.get_article(low_card_id))["ready"], "Manual approval should allow a complete low card"
        assert not validate_issue_ready_for_h5({"article_ids": [low_card_id]}, db.get_articles_by_ids([low_card_id])), "Approved low card should pass H5 guard"

        stored_low_id = db.insert_article({
            "url": "https://test.example.com/stored_low_card",
            "title": "Stored Low Card",
            "category": "艺术与文化",
            "score": 84,
            "status": "candidate",
            "gate2_tier": "A",
        })
        _store_card(
            db,
            stored_low_id,
            json.loads(low_card),
            card_status="needs_rewrite",
            reason="editor_confidence_low",
        )
        stored_low = db.get_article(stored_low_id)
        assert stored_low["pending_human"] in (0, None), "_store_card must not write pending_human for card-level issues"
        assert stored_low["card_status"] == "needs_rewrite", "Card-level low confidence should be stored in card_status"
        stored_summary = summarize_card_readiness(db.get_articles_by_ids([stored_low_id]))
        assert stored_summary["counts"]["needs_rewrite"] == 1, "Readiness summary should count low card as needs_rewrite"

        issue_id = db.create_issue("2026-T01", "2026-06-19", [ready_id, missing_id, pending_id])
        db.assign_to_issue([ready_id, missing_id, pending_id], issue_id)
        db.update_article(pending_id, {"pending_human": 1})

        issue = db.get_issue(issue_id)
        articles = db.get_issue_articles(issue_id)
        errors = validate_issue_ready_for_h5(issue, articles)
        assert errors, "Expected H5 readiness guard to block incomplete issue"
        string_issue_errors = validate_issue_ready_for_h5({"article_ids": json.dumps(issue["article_ids"])}, articles)
        assert string_issue_errors, "Expected readiness guard to accept JSON-string article_ids"
        joined = " ".join(errors)
        assert str(missing_id) in joined, f"Missing card article not reported: {errors}"
        assert str(pending_id) in joined, f"pending_human article not reported: {errors}"
        assert isinstance(issue["article_ids"], list), "get_issue should return article_ids as list"

        released = db.fail_issue_release_articles(issue_id)
        assert released == 3, f"Expected 3 released articles, got {released}"
        failed_issue = db.get_issue(issue_id)
        assert failed_issue["status"] == "failed", "Failed issue should be marked failed"
        released_missing = db.get_article(missing_id)
        released_pending = db.get_article(pending_id)
        assert released_missing["issue_id"] is None, "Released article should clear issue_id"
        assert released_missing["status"] == "pending", "Released article should return to pending"
        assert released_pending["issue_id"] is None, "Pending-human article should clear issue_id"
        assert released_pending["pending_human"] == 1, "Release must preserve pending_human flag"

        keep_ready_id = db.insert_article({
            "url": "https://test.example.com/keep_ready_card",
            "title": "Keep Ready Card",
            "category": "艺术与文化",
            "score": 91,
            "status": "candidate",
            "gate2_tier": "A",
            "card_json": complete_card,
        })
        keep_missing_id = db.insert_article({
            "url": "https://test.example.com/keep_missing_card",
            "title": "Keep Missing Card",
            "category": "艺术与文化",
            "score": 87,
            "status": "candidate",
            "gate2_tier": "B",
        })
        keep_pending_id = db.insert_article({
            "url": "https://test.example.com/keep_pending_card",
            "title": "Keep Pending Card",
            "category": "艺术与文化",
            "score": 86,
            "status": "candidate",
            "gate2_tier": "B",
            "card_json": complete_card,
            "pending_human": 1,
        })
        salvage_issue_id = db.create_issue(
            "2026-T02",
            "2026-06-19",
            [keep_ready_id, keep_missing_id, keep_pending_id],
        )
        db.assign_to_issue([keep_ready_id, keep_missing_id, keep_pending_id], salvage_issue_id)
        db.update_article(keep_pending_id, {"pending_human": 1, "gate3_status": "pending_human"})
        released_bad = db.keep_issue_articles_release_rest(salvage_issue_id, [keep_ready_id])
        assert released_bad == 2, f"Expected 2 bad articles released, got {released_bad}"
        salvage_issue = db.get_issue(salvage_issue_id)
        assert salvage_issue["article_ids"] == [keep_ready_id], f"Unexpected kept ids: {salvage_issue['article_ids']}"
        assert db.get_article(keep_ready_id)["issue_id"] == salvage_issue_id, "Ready article should stay in issue"
        assert db.get_article(keep_missing_id)["issue_id"] is None, "Missing card should be released"
        assert db.get_article(keep_pending_id)["pending_human"] == 1, "Salvage release must preserve pending_human"

        void_gate3_id = db.insert_article({
            "url": "https://test.example.com/void_gate3_pending",
            "title": "Void Gate3 Pending",
            "category": "艺术与文化",
            "score": 85,
            "status": "candidate",
            "gate2_tier": "B",
            "card_json": complete_card,
        })
        void_issue_id = db.create_issue("2026-T03", "2026-06-19", [void_gate3_id])
        db.assign_to_issue([void_gate3_id], void_issue_id)
        db.update_article(void_gate3_id, {"gate3_status": "pending_human"})
        db.void_issue(void_issue_id)
        voided_article = db.get_article(void_gate3_id)
        assert voided_article["issue_id"] is None, "Voided article should clear issue_id"
        assert voided_article["gate3_status"] is None, "Void must clear stale gate3 pending_human"
        replace_old_id = db.insert_article({
            "url": "https://test.example.com/replace_old_card",
            "title": "Replace Old Card",
            "category": "艺术与文化",
            "score": 83,
            "status": "candidate",
            "gate2_tier": "B",
            "card_json": complete_card,
        })
        replace_keep_id = db.insert_article({
            "url": "https://test.example.com/replace_keep_card",
            "title": "Replace Keep Card",
            "category": "艺术与文化",
            "score": 82,
            "status": "candidate",
            "gate2_tier": "B",
            "card_json": complete_card,
        })
        replace_new_id = db.insert_article({
            "url": "https://test.example.com/replace_new_card",
            "title": "Replace New Card",
            "category": "艺术与文化",
            "score": 92,
            "status": "pending",
            "gate2_tier": "A",
            "evergreen": 1,
            "card_json": complete_card,
        })
        replace_issue_id = db.create_issue("2026-T04", "2026-06-19", [replace_old_id, replace_keep_id])
        db.assign_to_issue([replace_old_id, replace_keep_id], replace_issue_id)
        replacement = db.replace_issue_article(
            replace_issue_id,
            replace_old_id,
            replace_new_id,
            reason="test_replace",
        )
        assert replacement["position"] == 0, f"Replacement should preserve zero-based position: {replacement}"
        replaced_issue = db.get_issue(replace_issue_id)
        assert replaced_issue["article_ids"] == [replace_new_id, replace_keep_id], f"Unexpected replacement ids: {replaced_issue['article_ids']}"
        replaced_old = db.get_article(replace_old_id)
        replaced_new = db.get_article(replace_new_id)
        assert replaced_old["issue_id"] is None and replaced_old["status"] == "candidate", "Old issue article should return to candidate only"
        assert replaced_new["issue_id"] == replace_issue_id and replaced_new["status"] == "in_issue", "New article should become the issue article"
        assert replaced_new["issue_sort_order"] == 0, "New article should keep the old position"
        assert not replaced_new["evergreen"], "Replacement should remove new article from evergreen pool"
        with db._get_conn() as conn:
            logged = conn.execute(
                "SELECT COUNT(*) FROM issue_article_replacements WHERE issue_id=? AND old_article_id=? AND new_article_id=?",
                (replace_issue_id, replace_old_id, replace_new_id),
            ).fetchone()[0]
        assert logged == 1, "Replacement audit log should record the swap"
        logger.info("  ✅ 缺卡/待人工会阻止 H5 重生；异步救援会保留好卡并释放坏卡")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ H5 重生护栏测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1

    # --- Test 7: Gate backlog counters ---
    logger.info("\n--- 前两关 backlog 计数测试 ---")
    try:
        gate1_id = db.insert_article({
            "url": "https://test.example.com/gate1_waiting",
            "title": "Gate1 Waiting",
            "category": "艺术与文化",
            "status": "pending",
        })
        gate2_id = db.insert_article({
            "url": "https://test.example.com/gate2_waiting",
            "title": "Gate2 Waiting",
            "category": "艺术与文化",
            "status": "pending",
            "gate1_verdict": "pass",
        })
        assert gate1_id and gate2_id, "Failed to insert gate backlog fixtures"
        assert db.count_gate1_candidates() >= 1, "Expected Gate1 backlog"
        assert db.count_gate2_candidates() >= 1, "Expected Gate2 backlog"
        logger.info("  ✅ Gate1/Gate2 backlog 计数可用")
        results["pass"] += 1
    except Exception as e:
        logger.error(f"  ❌ 前两关 backlog 计数测试失败: {e}")
        import traceback; traceback.print_exc()
        results["fail"] += 1

    # Cleanup
    try:
        os.remove(db_path)
    except:
        pass

    logger.info(f"\n生命周期离线测试: pass={results['pass']} fail={results['fail']}")
    return results



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="回归测试")
    parser.add_argument("--case", type=str, help="只跑指定用例")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lifecycle", action="store_true", help="运行生命周期离线测试")
    args = parser.parse_args()

    if args.lifecycle:
        run_lifecycle_tests()
        sys.exit(0)

    if args.case:
        case = ALL_CASES.get(args.case)
        if not case:
            logger.error(f"未知用例: {args.case}")
            sys.exit(1)
        ALL_CASES.clear()
        ALL_CASES[args.case] = case

    run_all_tests()
