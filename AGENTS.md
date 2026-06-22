# 优质图文推荐日报 — AGENTS.md

## 项目概述

AI 驱动的 premium lifestyle 内容策展系统。从 49 个网站抓取 RSS/网页，经三关筛选 + AI 成卡撰写，生成 H5 杂志式周报，部署于 Fly.io (nrt)。

## 状态机（文章生命周期）

```
crawl → pending → gate1(pass/fail) → gate2(DJ分级A/B/C/D) → gate3(小组赛排位)
                                                                    ↓
                                                            gate3_selected=1
                                                                    ↓
                                                              card_writer(事实提取+成卡)
                                                                    ↓
                                                    ┌─ success ─→ in_issue(入选期刊)
                                                    ├─ pending_human=1(超长/泄漏/违禁/低置信)
                                                    └─ rejected(禁句命中/否决)
```

**关键状态字段:**
- `status`: pending | candidate | in_issue | rejected | sunk | published
- `gate2_tier`: A/B/C/D (A最优)
- `gate3_selected`: 0/1 (小组赛胜出)
- `pending_human`: 0/1 (需人工复核)
- `issue_id`: 所属期刊 ID

## Prompt 位置

所有 LLM prompt 在 `prompts/` 目录:

| 文件 | 用途 | 调用方 |
|------|------|--------|
| `gate1_pass_fail.py` | 硬性闸门(pass/fail) | `run_gate1.py` |
| `gate2_dj_tier.py` | DJ 适配分级(A/B/C/D) | `run_gate2.py` |
| `gate3_group_match.py` | 小组赛排位 | `run_gate3.py` |
| `card_writer_v3.py` | 成卡撰写(含事实提取+推荐卡) | `run_generate_cards.py` |
| `summary_generation.py` | 摘要生成 | `run_resummarize.py` |
| `veto_check.py` | 否决词检查 | `run_veto_check.py` |

**注意:** 压缩重试 prompt (`COMPRESS_RETRY_PROMPT`)、输入脱敏规则 (`_SANITIZE_REPLACEMENTS`)、人称泄漏检测 pattern (`PERSON_REF_PATTERN`)、违禁词清单均在 `run_generate_cards.py` 中，不在 prompts 目录。

## 配置

- `config/settings.yaml` — API keys、模型分配、阈值、调度时间
- `config/sites.yaml` — 49 个网站 (RSS/网页)，含分类映射
- `config/categories.yaml` — 频道分类
- `fly.toml` — Fly.io 部署配置 (Volume、环境变量)

## 模型分配

`config/settings.yaml` → `gate_models`:
- gate1: qwen-flash (最便宜)
- gate2: qwen-plus
- gate3: deepseek-chat (最强)
- card_writer: deepseek-chat
- fact_extractor: deepseek-chat
- editor_note: deepseek-chat

## 回归测试

```bash
cd tests && python3 run_regression.py
```

测试覆盖: 三关 pipeline、card_writer、数据库迁移、API 端点。
运行前需 `source venv/bin/activate`。

## 部署检查清单

每次部署前逐项确认:

- [ ] **push了吗** — `git push origin main` 已成功，GitHub Actions 已触发
- [ ] **迁移了吗** — 新增 DB 字段/表已在 `src/database.py` `_ensure_schema()` 中声明
- [ ] **secrets全吗** — `fly secrets list` 确认 `DEEPSEEK_API_KEY`, `QWEN_API_KEY`, `KIMI_API_KEY` 均已设置
- [ ] **卷挂了吗** — `fly.toml` 中 `[[mounts]]` 指向 `lifestyle_data:/data`
- [ ] **`.env` 不可进镜像** — `.dockerignore` 和 `.gitignore` 均含 `.env`
- [ ] **`.dockerignore`** — 确认包含 `.env`, `__pycache__`, `venv`, `data/`, `output/`, `static/images/`

## 远程长任务规则

**所有远程执行的长任务必须 `nohup` 后台化 + 输出到日志文件，禁止 SSH 直连执行。**

```bash
# ✅ 正确
flyctl machine exec <mid> -a premium-lifestyle-intel \
  'sh -c "cd /app && nohup python3 run_report.py --force-cards --workers 3 > /data/output/run_v93.log 2>&1 &"'

# ❌ 错误 (连接断开任务即死)
fly ssh console -C "python3 /app/run_report.py --force-cards"
```

事后用以下命令查进度:
```bash
flyctl machine exec <mid> -a premium-lifestyle-intel 'sh -c "tail -50 /data/output/run_v93.log"'
```

## 常用运维命令

```bash
# 查看统计
curl https://premium-lifestyle-intel.fly.dev/api/stats

# 放行 pending_human 文章
curl -X POST https://premium-lifestyle-intel.fly.dev/api/clear-pending \
  -H "Content-Type: application/json" -d '{"ids":[316,357]}'

# 远程执行 (machine-id 用 flyctl machine list 获取)
flyctl machine exec <mid> -a premium-lifestyle-intel 'sh -c "..."'

# 查看部署状态
fly status -a premium-lifestyle-intel
```

## 文件结构

```
run_crawl.py          # 第0步: 抓取
run_gate1.py          # 第1关: 硬性闸门
run_gate2.py          # 第2关: DJ 分级
run_gate3.py          # 第3关: 小组赛排位
run_generate_cards.py # 第4步: 成卡撰写
run_report.py         # 第5步: H5 周报渲染
run_review.py         # 审核界面
run_refetch.py        # 文章回抓
run_expiry_check.py   # 过期检查
run_reset_pending.py  # 复位误杀的 pending_human
run_veto_check.py     # 否决词扫描
run_deep_analysis.py  # 深度分析
run_resummarize.py    # 摘要重写
src/database.py       # SQLite 数据库层
src/report_generator.py # H5 模板与渲染
src/crawler.py        # RSS + 网页抓取
src/models.py         # LLM 调用封装
src/config.py         # 配置加载
app.py                # Flask Web 后端
```

## 本地开发

```bash
source venv/bin/activate
python3 app.py           # 启动 Flask (端口 8080)
python3 run_report.py    # 生成周报 (使用本地 data/content.db)
```

注意: 沙箱内 `npm run build` 可验证但无法绑定端口 (listen EPERM)。

## 完成定义 (Definition of Done)

**报告的完成标记规则:**

| 标记 | 含义 |
|------|------|
| `✅` | 已部署到 Fly.io 且已生效且有证据（截图/curl/日志） |
| `⏳已写码待部署` | 代码已写完但未 push/部署 |
| `❌` | 已尝试但失败，附原因 |

- **完成的定义 = 远程生效，不是本地写完。**
- 未经 `git push` + Actions 绿 + `fly status` healthy 的改动不得标 `✅`。
- 夜班报告、周报等所有汇总文档均须遵守此规则。

## 部署冻结规则 (Deploy Freeze)

**长任务运行期间严禁部署。部署 = 重启机器 = 杀死所有运行中进程。**

- 抓取 (`run_crawl.py`)、批量成卡 (`run_generate_cards.py`)、三关 pipeline、图片压缩等耗时超过 2 分钟的任务均为"长任务"。
- **任何 `git push` 或 `fly deploy` 前，必须先确认远程无运行中任务：**
  ```bash
  # 查日志最后修改时间（2 分钟内有写入 = 有任务在跑）
  flyctl machine exec <mid> -a premium-lifestyle-intel \
    'sh -c "ls -la /data/output/crawl_*.log /data/output/img_*.log 2>/dev/null"'
  ```
- 若任务正在运行，等它自然结束或确认已死，再部署。
- 今早误杀案：调度器修复部署 (v124→v125) 在抓取 + 压缩运行期间触发，两进程被杀，44 条入库白费、压缩 500/7310 中断。以此为戒。
