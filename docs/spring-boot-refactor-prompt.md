# Premium Lifestyle Intel Python → YuDao Spring Boot 重构提示词

> 使用方式：将本文整体复制给编码 Agent / IDE AI。目标是在已有 YuDao Spring Boot 脚手架基础上，重构当前 Python 版“优质图文推荐日报”系统。脚手架本地目录：`D:\workspace\seribest\code repository\premium-lifestyle-intel-server`。

## 一、角色与目标

你是一名资深 Java / Spring Boot 架构师，熟悉：

- YuDao / ruoyi-vue-pro Spring Boot 脚手架开发规范；
- Spring AI 大模型调用；
- MySQL 表结构设计与 MyBatis Plus；
- MinIO / 文件服务集成；
- RSS / 网页爬虫、正文抽取、内容审核、日报生成；
- 阿里巴巴 Java 开发规范。

请基于当前 Python 项目能力，在 YuDao 脚手架中重构出一个可维护、分层清晰、可扩展的 Java 版本。Python 项目只作为业务参考，不要求逐行翻译，要求按 Spring Boot + YuDao 的工程方式重新设计。

## 二、现有 Python 项目业务概述

当前系统是 AI 驱动的 premium lifestyle 内容策展系统：

1. 从多个 RSS / 网页来源抓取文章；
2. 保存原始网页、清洗后的结构化正文、图片；
3. 对文章进行三关筛选：
   - Gate1：硬性闸门 pass / fail；
   - Gate2：DJ 适配分级 A / B / C / D；
   - Gate3：小组赛排位，选出候选文章；
4. 对入选文章调用 AI 生成推荐卡片；
5. 每日生成一期包含约 25 篇文章的日报；
6. 后台可审核、替换、重跑、查看 AI prompt / response、查看文章详情。

### 2.1 文章生命周期状态机

```text
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

### 2.2 关键状态字段

- `status`：`pending`、`candidate`、`in_issue`、`rejected`、`sunk`、`published`；
- `gate2_tier`：`A`、`B`、`C`、`D`；
- `gate3_selected`：是否小组赛胜出；
- `pending_human`：是否需要人工复核；
- `issue_id`：所属日报 ID。

## 三、重构硬性约束

1. 使用 YuDao Spring Boot 脚手架现有模块、代码生成、权限、菜单、字典、文件、定时任务等基础能力。
2. 业务数据使用 MySQL 保存。
3. 文件存储使用 MinIO，不要自己直接操作 MinIO SDK，统一调用脚手架已有 `FileApi.createFile` 接口保存并获取文件路径 / object key。
4. AI 框架使用 Spring AI。
5. 编码严格遵守：
   - 阿里巴巴 Java 开发规范；
   - YuDao 脚手架分层规范；
   - Controller / Service / Mapper / DO / DTO / VO / Convert 清晰分层；
   - 不在 Controller 写业务逻辑；
   - 不在数据库中保存大段正文、prompt、response 原文。
6. MySQL 只保存文章标题、摘要、分类、标签、评分、状态、日报 ID，以及 MinIO 文件 object key / URL。
7. 具体大文件内容保存到 MinIO。

## 四、MinIO 文件存储设计

### 4.1 文章文件

每篇文章在 MinIO 中保存以下文件：

| 文件 | 说明 | 用途 |
|---|---|---|
| `raw.html` | 爬虫抓取到的原始网页 HTML | 后续重新解析、排查正文提取问题、核对原始来源 |
| `content.json` | 清洗后的结构化正文 | 前端文章详情页真正使用的展示文件 |
| `cover.webp` / `cover.png` | 文章封面图 | 列表页、日报卡片、推荐流展示 |
| `img_001.png`、`img_002.png` | 正文图片 | 前端渲染 `content.json` 时按图片路径展示 |

`content.json` 建议结构：

```json
{
  "title": "文章标题",
  "source": "来源网站",
  "url": "原文 URL",
  "language": "en",
  "author": "作者",
  "publishedAt": "2026-06-22T10:00:00Z",
  "blocks": [
    { "type": "heading", "level": 2, "text": "小标题" },
    { "type": "paragraph", "text": "正文段落" },
    { "type": "image", "src": "articles/2026/06/22/123/img_001.png", "alt": "图片说明" },
    { "type": "quote", "text": "引用内容", "source": "引用来源" }
  ]
}
```

### 4.2 日报文件

每天生成一期日报，保存：

| 文件 | 说明 | 用途 |
|---|---|---|
| `issue.json` | 日报结构化数据 | 前端日报展示 |
| `issue.md` | 日报 Markdown 版本 | 后台预览、人工编辑、导出或发布到其他平台 |

`issue.json` 建议结构：

```json
{
  "issueNo": "2026-06-22",
  "reportDate": "2026-06-22",
  "editorNote": "今日编辑导语",
  "articles": [
    {
      "articleId": 1001,
      "sortOrder": 1,
      "title": "标题",
      "summary": "摘要",
      "categoryCode": "travel",
      "score": 92,
      "gate2Tier": "A",
      "recommendReason": "推荐理由",
      "coverPath": "articles/2026/06/22/1001/cover.webp"
    }
  ]
}
```

### 4.3 AI 调用审计文件

AI 的 prompt 和 response 不存 MySQL，直接保存到 MinIO，例如：

- `quality_prompt.txt`
- `quality_response.json`
- `persona_prompt.txt`
- `persona_response.json`
- `classifier_prompt.txt`
- `classifier_response.json`
- `gate1_prompt.txt`
- `gate1_response.json`
- `gate2_prompt.txt`
- `gate2_response.json`
- `gate3_prompt.txt`
- `gate3_response.json`
- `card_writer_prompt.txt`
- `card_writer_response.json`

建议 object key 规范：

```text
articles/{yyyy}/{MM}/{dd}/{articleId}/raw.html
articles/{yyyy}/{MM}/{dd}/{articleId}/content.json
articles/{yyyy}/{MM}/{dd}/{articleId}/cover.webp
articles/{yyyy}/{MM}/{dd}/{articleId}/images/img_001.png
articles/{yyyy}/{MM}/{dd}/{articleId}/ai/gate1_prompt.txt
articles/{yyyy}/{MM}/{dd}/{articleId}/ai/gate1_response.json
issues/{yyyy}/{MM}/{dd}/{issueId}/issue.json
issues/{yyyy}/{MM}/{dd}/{issueId}/issue.md
```

## 五、建议 MySQL 表结构

请先在 YuDao 项目中创建业务模块 SQL。表名前缀建议使用 `pli_`（premium lifestyle intel）。如项目已有命名前缀规范，请按脚手架规范调整。

### 5.1 文章主表：`pli_article`

```sql
CREATE TABLE `pli_article` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '文章ID',
  `url` VARCHAR(1024) NOT NULL COMMENT '原文URL',
  `url_hash` CHAR(64) NOT NULL COMMENT 'URL SHA-256，用于去重',
  `source_code` VARCHAR(64) NOT NULL COMMENT '来源站点编码',
  `source_name` VARCHAR(128) DEFAULT NULL COMMENT '来源站点名称',
  `title` VARCHAR(512) DEFAULT NULL COMMENT '原始标题',
  `translated_title` VARCHAR(512) DEFAULT NULL COMMENT '中文标题',
  `summary` VARCHAR(2000) DEFAULT NULL COMMENT '摘要',
  `category_code` VARCHAR(64) DEFAULT NULL COMMENT '分类编码',
  `category_name` VARCHAR(128) DEFAULT NULL COMMENT '分类名称',
  `tags` JSON DEFAULT NULL COMMENT '标签数组',
  `score` INT NOT NULL DEFAULT 0 COMMENT '综合评分',
  `recommend_reason` VARCHAR(2000) DEFAULT NULL COMMENT '推荐理由',
  `scenario` VARCHAR(512) DEFAULT NULL COMMENT '适用场景',
  `pros` JSON DEFAULT NULL COMMENT '优点数组',
  `cons` JSON DEFAULT NULL COMMENT '缺点数组',
  `recommend_level` VARCHAR(32) NOT NULL DEFAULT '了解' COMMENT '推荐等级',
  `language` VARCHAR(16) DEFAULT NULL COMMENT '文章语言',
  `author` VARCHAR(128) DEFAULT NULL COMMENT '作者',
  `published_at` DATETIME DEFAULT NULL COMMENT '原文发布时间',
  `crawled_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
  `reviewed_at` DATETIME DEFAULT NULL COMMENT '审核时间',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/candidate/in_issue/rejected/sunk/published',
  `is_relevant` BIT(1) NOT NULL DEFAULT b'1' COMMENT '是否相关',
  `pending_human` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否需要人工复核',
  `veto_hit` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否命中否决规则',
  `veto_rule` VARCHAR(512) DEFAULT NULL COMMENT '命中的否决规则',
  `archive_reason` VARCHAR(512) DEFAULT NULL COMMENT '归档原因',
  `archive_reason_at` DATETIME DEFAULT NULL COMMENT '归档时间',
  `carryover_count` INT NOT NULL DEFAULT 0 COMMENT '顺延次数',
  `evergreen` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否常青内容',
  `expiry_date` DATE DEFAULT NULL COMMENT '过期日期',
  `issue_id` BIGINT DEFAULT NULL COMMENT '所属日报ID',
  `issue_sort_order` INT DEFAULT NULL COMMENT '日报内排序',
  `raw_html_path` VARCHAR(512) DEFAULT NULL COMMENT 'MinIO raw.html 路径',
  `content_json_path` VARCHAR(512) DEFAULT NULL COMMENT 'MinIO content.json 路径',
  `cover_path` VARCHAR(512) DEFAULT NULL COMMENT 'MinIO 封面图路径',
  `image_paths` JSON DEFAULT NULL COMMENT 'MinIO 正文图片路径数组',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pli_article_url_hash` (`url_hash`),
  KEY `idx_pli_article_status` (`status`),
  KEY `idx_pli_article_category` (`category_code`),
  KEY `idx_pli_article_score` (`score`),
  KEY `idx_pli_article_crawled_at` (`crawled_at`),
  KEY `idx_pli_article_issue_id` (`issue_id`),
  KEY `idx_pli_article_source` (`source_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI文章表';
```

### 5.2 文章闸门结果表：`pli_article_gate`

```sql
CREATE TABLE `pli_article_gate` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `article_id` BIGINT NOT NULL COMMENT '文章ID',
  `gate1_verdict` VARCHAR(16) DEFAULT NULL COMMENT 'Gate1结果：pass/fail',
  `gate1_failed_checks` JSON DEFAULT NULL COMMENT 'Gate1失败检查项',
  `gate1_needs_human` BIT(1) NOT NULL DEFAULT b'0' COMMENT 'Gate1是否需人工',
  `gate1_checked_at` DATETIME DEFAULT NULL COMMENT 'Gate1检查时间',
  `gate2_tier` VARCHAR(8) DEFAULT NULL COMMENT 'Gate2分级：A/B/C/D',
  `gate2_veto` VARCHAR(512) DEFAULT NULL COMMENT 'Gate2否决原因',
  `gate2_dim_excitement` INT DEFAULT NULL COMMENT '兴奋度评分',
  `gate2_dim_feasibility` INT DEFAULT NULL COMMENT '可行性评分',
  `gate2_dim_density` INT DEFAULT NULL COMMENT '信息密度评分',
  `gate2_fit_reasons` JSON DEFAULT NULL COMMENT '适配理由数组',
  `gate2_one_line` VARCHAR(512) DEFAULT NULL COMMENT '一句话评价',
  `gate2_status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'Gate2状态',
  `gate2_error` VARCHAR(2000) DEFAULT NULL COMMENT 'Gate2错误信息',
  `gate2_attempt_count` INT NOT NULL DEFAULT 0 COMMENT 'Gate2尝试次数',
  `gate2_checked_at` DATETIME DEFAULT NULL COMMENT 'Gate2检查时间',
  `gate3_rank` INT DEFAULT NULL COMMENT 'Gate3排名',
  `gate3_rationale` VARCHAR(2000) DEFAULT NULL COMMENT 'Gate3理由',
  `gate3_group_code` VARCHAR(64) DEFAULT NULL COMMENT 'Gate3分组',
  `gate3_selected` BIT(1) NOT NULL DEFAULT b'0' COMMENT 'Gate3是否胜出',
  `gate3_status` VARCHAR(32) DEFAULT NULL COMMENT 'Gate3状态',
  `gate3_checked_at` DATETIME DEFAULT NULL COMMENT 'Gate3检查时间',
  `fit_keywords_hit` JSON DEFAULT NULL COMMENT '命中关键词',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pli_article_gate_article` (`article_id`),
  KEY `idx_pli_article_gate_tier` (`gate2_tier`),
  KEY `idx_pli_article_gate_selected` (`gate3_selected`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI文章闸门结果表';
```

### 5.3 AI 审计文件表：`pli_ai_audit_file`

```sql
CREATE TABLE `pli_ai_audit_file` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `biz_type` VARCHAR(64) NOT NULL COMMENT '业务类型：article/issue',
  `biz_id` BIGINT NOT NULL COMMENT '业务ID',
  `stage` VARCHAR(64) NOT NULL COMMENT 'AI阶段：gate1/gate2/gate3/card_writer/summary/classifier等',
  `prompt_path` VARCHAR(512) DEFAULT NULL COMMENT 'prompt文件路径',
  `response_path` VARCHAR(512) DEFAULT NULL COMMENT 'response文件路径',
  `model_name` VARCHAR(128) DEFAULT NULL COMMENT '模型名称',
  `request_id` VARCHAR(128) DEFAULT NULL COMMENT '请求ID',
  `success` BIT(1) NOT NULL DEFAULT b'1' COMMENT '是否成功',
  `error_message` VARCHAR(2000) DEFAULT NULL COMMENT '错误信息',
  `started_at` DATETIME DEFAULT NULL COMMENT '开始时间',
  `finished_at` DATETIME DEFAULT NULL COMMENT '结束时间',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  KEY `idx_pli_ai_audit_biz` (`biz_type`, `biz_id`),
  KEY `idx_pli_ai_audit_stage` (`stage`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLIAI审计文件表';
```

### 5.4 日报表：`pli_issue`

```sql
CREATE TABLE `pli_issue` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT '日报ID',
  `issue_no` VARCHAR(64) NOT NULL COMMENT '期号，例如2026-06-22',
  `report_type` VARCHAR(32) NOT NULL DEFAULT 'daily' COMMENT '报告类型：daily/weekly',
  `report_date` DATE NOT NULL COMMENT '报告日期',
  `status` VARCHAR(32) NOT NULL DEFAULT 'draft' COMMENT '状态：draft/published/voided',
  `article_count` INT NOT NULL DEFAULT 0 COMMENT '文章数量',
  `editor_note` VARCHAR(2000) DEFAULT NULL COMMENT '编辑导语',
  `issue_json_path` VARCHAR(512) DEFAULT NULL COMMENT 'MinIO issue.json路径',
  `issue_md_path` VARCHAR(512) DEFAULT NULL COMMENT 'MinIO issue.md路径',
  `html_path` VARCHAR(512) DEFAULT NULL COMMENT '兼容旧版HTML路径',
  `locked_at` DATETIME DEFAULT NULL COMMENT '锁定时间',
  `published_at` DATETIME DEFAULT NULL COMMENT '发布时间',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pli_issue_no` (`issue_no`),
  KEY `idx_pli_issue_report_date` (`report_date`),
  KEY `idx_pli_issue_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI日报表';
```

### 5.5 日报文章关联表：`pli_issue_article`

```sql
CREATE TABLE `pli_issue_article` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `issue_id` BIGINT NOT NULL COMMENT '日报ID',
  `article_id` BIGINT NOT NULL COMMENT '文章ID',
  `sort_order` INT NOT NULL COMMENT '排序',
  `category_code` VARCHAR(64) DEFAULT NULL COMMENT '快照分类编码',
  `title_snapshot` VARCHAR(512) DEFAULT NULL COMMENT '标题快照',
  `summary_snapshot` VARCHAR(2000) DEFAULT NULL COMMENT '摘要快照',
  `score_snapshot` INT DEFAULT NULL COMMENT '评分快照',
  `recommend_reason_snapshot` VARCHAR(2000) DEFAULT NULL COMMENT '推荐理由快照',
  `cover_path_snapshot` VARCHAR(512) DEFAULT NULL COMMENT '封面路径快照',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pli_issue_article` (`issue_id`, `article_id`),
  KEY `idx_pli_issue_article_issue_order` (`issue_id`, `sort_order`),
  KEY `idx_pli_issue_article_article` (`article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI日报文章关联表';
```

### 5.6 日报文章替换记录表：`pli_issue_article_replacement`

```sql
CREATE TABLE `pli_issue_article_replacement` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `issue_id` BIGINT NOT NULL COMMENT '日报ID',
  `old_article_id` BIGINT NOT NULL COMMENT '旧文章ID',
  `new_article_id` BIGINT NOT NULL COMMENT '新文章ID',
  `position` INT NOT NULL COMMENT '替换位置',
  `reason` VARCHAR(1000) DEFAULT NULL COMMENT '替换原因',
  `replaced_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '替换时间',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  KEY `idx_pli_replacement_issue` (`issue_id`),
  KEY `idx_pli_replacement_old` (`old_article_id`),
  KEY `idx_pli_replacement_new` (`new_article_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI日报文章替换记录表';
```

### 5.7 来源站点表：`pli_source_site`

```sql
CREATE TABLE `pli_source_site` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `site_code` VARCHAR(64) NOT NULL COMMENT '站点编码',
  `site_name` VARCHAR(128) NOT NULL COMMENT '站点名称',
  `site_url` VARCHAR(512) DEFAULT NULL COMMENT '站点URL',
  `rss_url` VARCHAR(1024) DEFAULT NULL COMMENT 'RSS URL',
  `crawl_type` VARCHAR(32) NOT NULL DEFAULT 'rss' COMMENT '抓取类型：rss/html',
  `category_code` VARCHAR(64) DEFAULT NULL COMMENT '默认分类',
  `enabled` BIT(1) NOT NULL DEFAULT b'1' COMMENT '是否启用',
  `crawl_interval_minutes` INT NOT NULL DEFAULT 1440 COMMENT '抓取间隔分钟',
  `last_crawled_at` DATETIME DEFAULT NULL COMMENT '上次抓取时间',
  `remark` VARCHAR(512) DEFAULT NULL COMMENT '备注',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_pli_source_site_code` (`site_code`),
  KEY `idx_pli_source_site_enabled` (`enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI来源站点表';
```

### 5.8 任务日志表：`pli_task_log`

```sql
CREATE TABLE `pli_task_log` (
  `id` BIGINT NOT NULL AUTO_INCREMENT COMMENT 'ID',
  `task_name` VARCHAR(128) NOT NULL COMMENT '任务名称',
  `run_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '运行时间',
  `status` VARCHAR(32) NOT NULL DEFAULT 'success' COMMENT '状态：success/fail/running',
  `stats` JSON DEFAULT NULL COMMENT '统计信息',
  `summary` VARCHAR(2000) DEFAULT NULL COMMENT '摘要',
  `error_message` VARCHAR(2000) DEFAULT NULL COMMENT '错误信息',
  `creator` VARCHAR(64) DEFAULT '' COMMENT '创建者',
  `create_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updater` VARCHAR(64) DEFAULT '' COMMENT '更新者',
  `update_time` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted` BIT(1) NOT NULL DEFAULT b'0' COMMENT '是否删除',
  `tenant_id` BIGINT NOT NULL DEFAULT 0 COMMENT '租户编号',
  PRIMARY KEY (`id`),
  KEY `idx_pli_task_log_name_run_at` (`task_name`, `run_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PLI任务日志表';
```

## 六、建议 Java 模块与分层

请在 YuDao 项目中新增或复用一个业务模块，例如：

```text
yudao-module-pli/
  yudao-module-pli-api/
  yudao-module-pli-biz/
```

建议包结构：

```text
cn.iocoder.yudao.module.pli
├── controller
│   └── admin
│       ├── article
│       ├── issue
│       └── source
├── dal
│   ├── dataobject
│   │   ├── article
│   │   ├── issue
│   │   └── source
│   └── mysql
├── service
│   ├── article
│   ├── crawl
│   ├── gate
│   ├── issue
│   ├── storage
│   └── ai
├── convert
├── enums
├── job
└── framework
```

### 6.1 核心 Service 拆分

- `ArticleService`：文章 CRUD、状态流转、审核；
- `ArticleContentService`：正文清洗、`content.json` 生成、图片路径组装；
- `CrawlService`：RSS / 网页抓取、去重、保存 `raw.html`；
- `GateService`：Gate1 / Gate2 / Gate3 编排；
- `CardWriterService`：AI 成卡、事实提取、推荐理由生成；
- `IssueService`：日报创建、选文、排序、发布、替换；
- `PliFileService`：统一封装 `FileApi.createFile`，生成 object key 并保存文件；
- `AiAuditService`：保存 prompt / response 到 MinIO，并写入 `pli_ai_audit_file` 记录；
- `SourceSiteService`：来源站点配置管理；
- `TaskLogService`：任务运行日志。

### 6.2 枚举建议

```java
ArticleStatusEnum: PENDING, CANDIDATE, IN_ISSUE, REJECTED, SUNK, PUBLISHED
Gate1VerdictEnum: PASS, FAIL
Gate2TierEnum: A, B, C, D
GateStatusEnum: PENDING, RUNNING, SUCCESS, FAIL
IssueStatusEnum: DRAFT, PUBLISHED, VOIDED
AiStageEnum: GATE1, GATE2, GATE3, CARD_WRITER, SUMMARY, CLASSIFIER
CrawlTypeEnum: RSS, HTML
```

## 七、业务流程实现要求

### 7.1 抓取流程

1. 从 `pli_source_site` 读取启用站点；
2. RSS 站点解析 feed，HTML 站点按扩展策略抓取；
3. 对 URL 规范化后计算 `url_hash`；
4. 若不存在则插入 `pli_article`；
5. 抓取原始网页 HTML；
6. 调用 `PliFileService` 保存 `raw.html`；
7. 提取正文和图片，保存正文图片；
8. 生成并保存 `content.json`；
9. 更新文章的 `raw_html_path`、`content_json_path`、`cover_path`、`image_paths`。

### 7.2 Gate1 / Gate2 / Gate3

- 每个 Gate 调用 Spring AI；
- prompt 构建和 response 解析要独立封装；
- prompt / response 原文必须保存到 MinIO；
- MySQL 只保存结构化结果和审计文件路径；
- Gate2 分级规则需要可单元测试；
- Gate3 按分类或分组进行小组赛排位，最终设置 `gate3_selected`。

### 7.3 成卡流程

1. 查询 `gate3_selected = true` 且未入日报的文章；
2. 加载 `content.json`；
3. 调用 Spring AI 做事实提取与推荐卡生成；
4. 保存 prompt / response 到 MinIO；
5. 将摘要、标签、评分、推荐理由、优缺点、推荐等级等写回 `pli_article`；
6. 如果命中禁句、低置信、内容过长或人称泄漏，则设置 `pending_human = true` 或 `status = rejected`。

### 7.4 日报生成流程

1. 选取 `gate3_selected = true`、`status = candidate` 或符合条件的文章；
2. 按 Gate2 tier、score、分类均衡、时效性进行排序；
3. 默认生成 25 篇文章；
4. 写入 `pli_issue` 和 `pli_issue_article`；
5. 生成 `issue.json` 和 `issue.md`；
6. 调用 `FileApi.createFile` 保存文件；
7. 更新 `issue_json_path`、`issue_md_path`；
8. 将入选文章更新为 `in_issue` 并写入 `issue_id`、`issue_sort_order`。

## 八、后台接口建议

请按 YuDao `admin-api` 风格实现接口，返回统一 `CommonResult`，分页使用脚手架分页对象。

### 8.1 文章接口

- `GET /pli/article/page`：文章分页；
- `GET /pli/article/get?id=`：文章详情；
- `GET /pli/article/content?id=`：读取 MinIO `content.json` 并返回；
- `POST /pli/article/create`：手工创建文章；
- `PUT /pli/article/update`：更新文章元数据；
- `PUT /pli/article/review`：审核 / 放行 / 拒绝；
- `POST /pli/article/refetch`：重新抓取；
- `POST /pli/article/run-gates`：对指定文章重跑 Gate；
- `POST /pli/article/generate-card`：对指定文章重新成卡。

### 8.2 日报接口

- `GET /pli/issue/page`：日报分页；
- `GET /pli/issue/get?id=`：日报详情；
- `GET /pli/issue/content?id=`：读取 `issue.json`；
- `POST /pli/issue/generate`：生成日报；
- `POST /pli/issue/publish`：发布日报；
- `POST /pli/issue/replace-article`：替换日报文章；
- `GET /pli/issue/markdown?id=`：读取 `issue.md`。

### 8.3 来源站点接口

- `GET /pli/source-site/page`；
- `POST /pli/source-site/create`；
- `PUT /pli/source-site/update`；
- `DELETE /pli/source-site/delete`；
- `POST /pli/source-site/test-crawl`。

## 九、定时任务建议

使用 YuDao / XXL-Job / Spring Scheduler 中脚手架已有的任务能力：

- `PliCrawlJob`：每日 / 每小时抓取；
- `PliGatePipelineJob`：执行 Gate1 → Gate2 → Gate3；
- `PliCardWriterJob`：对入选文章成卡；
- `PliIssueGenerateJob`：生成日报；
- `PliExpiryCheckJob`：过期检查；
- `PliImageCleanupJob`：无用图片清理。

每个 Job 必须写 `pli_task_log`，记录成功、失败、统计信息和异常摘要。

## 十、Spring AI 实现要求

1. 使用 Spring AI 的 `ChatClient` / `ChatModel`；
2. 不要在业务代码中硬编码 API Key；
3. 模型配置放入 `application.yaml` 或配置中心；
4. prompt 模板建议放在 `resources/prompts/pli/`；
5. response 优先要求模型返回 JSON；
6. 对 JSON 解析失败、模型超时、内容违规等情况进行可观测错误处理；
7. 每次调用都保存 prompt / response 文件到 MinIO；
8. 不要把完整 prompt / response 写入普通业务日志。

## 十一、从 Python 版本迁移时的参考映射

| Python 文件 | Java 重构目标 |
|---|---|
| `run_crawl.py`、`src/crawler.py`、`src/rss_parser.py` | `CrawlService`、`PliCrawlJob` |
| `run_gate1.py` | `Gate1Service` |
| `run_gate2.py` | `Gate2Service` |
| `run_gate3.py` | `Gate3Service` |
| `run_generate_cards.py` | `CardWriterService` |
| `run_report.py`、`services/issue_builder.py` | `IssueService`、`PliIssueGenerateJob` |
| `run_review.py`、`web/*.py`、`app.py` | YuDao Admin Controller + 前端页面 |
| `src/database.py` | MySQL 表结构 + Mapper + Service |
| `prompts/*.py` | `resources/prompts/pli/*.st` 或 `.txt` 模板 |

## 十二、实施步骤

请按以下顺序执行，不要一次性把所有业务写成巨型类：

1. 阅读 YuDao 脚手架现有模块结构，确认模块命名和包名；
2. 新增 PLI 业务模块或在合适模块中新增 PLI 包；
3. 先提交 SQL 表结构和字典枚举；
4. 生成 DO / Mapper / Service / Controller 基础 CRUD；
5. 实现 `PliFileService`，统一调用 `FileApi.createFile`；
6. 实现文章抓取入库和 `raw.html` / `content.json` 文件保存；
7. 实现 Gate1 / Gate2 / Gate3 的 Spring AI 调用和审计文件保存；
8. 实现成卡流程；
9. 实现日报生成和文件保存；
10. 实现后台接口和必要的权限菜单；
11. 补充单元测试 / 集成测试；
12. 最后再考虑 Python 历史数据迁移脚本。

## 十三、验收标准

完成后需要满足：

- MySQL 中能看到文章、Gate 结果、日报、来源站点、任务日志；
- MinIO 中能看到每篇文章的 `raw.html`、`content.json`、封面图、正文图片、AI prompt / response；
- MinIO 中能看到日报的 `issue.json` 和 `issue.md`；
- 后台能分页查询文章、查看文章详情、读取结构化正文；
- 后台能生成日报、查看日报详情、读取 Markdown；
- AI prompt / response 可追溯，但不污染 MySQL 大字段；
- Gate2 分级、日报选文、URL 去重有单元测试；
- 所有新增代码通过 Maven 测试和 Checkstyle / 阿里规约扫描；
- 代码符合 YuDao 的 Controller、Service、Mapper、DO、VO、Convert 分层习惯。

## 十四、编码注意事项

- 不要直接把 Python 代码机械翻译成 Java；
- 不要把完整 HTML、正文 JSON、AI prompt、AI response 存进 MySQL；
- 不要绕过 `FileApi.createFile` 直接调用 MinIO；
- 不要在 Controller 中写爬虫、AI、文件存储等业务逻辑；
- 不要在日志中输出完整 prompt / response 或大段正文；
- 不要忽略 URL 规范化和去重；
- 不要忽略 AI 失败重试、JSON 解析失败、内容违规和人工复核状态；
- Java 类名、方法名、字段名要语义清晰，避免缩写滥用；
- 所有数据库状态值都建议使用枚举，不要到处散落字符串常量。

## 十五、请你开始执行的第一批任务

请先完成以下内容：

1. 在 YuDao 项目中创建 PLI 业务模块 / 包结构；
2. 根据本文 SQL 生成初始化建表脚本；
3. 定义文章、Gate、日报、来源站点、AI 审计相关 DO / Mapper；
4. 定义枚举类和基础 CRUD；
5. 实现 `PliFileService` 对 `FileApi.createFile` 的封装；
6. 给出下一步实现抓取流程和 Spring AI Gate 流程的详细计划。
