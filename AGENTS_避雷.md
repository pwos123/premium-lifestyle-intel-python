# AGENTS 避雷手册

> 记录本项目中反复踩过的坑。每次操作前读一遍。

## 1. 远程渲染：输出目录陷阱

**雷：** `flyctl machine exec` 的 cwd 是 `/data`，`generate_report` 相对路径 `output` 解析为 `/data/output/`。但 Flask serve 的是 `/app/output/`。

**避雷：** 远程渲染必须两部到位：
```bash
# ❌ 错误
python3 -c "... generate_report(articles, config, ...)"  # 只写到 /data/output/

# ✅ 正确
cd /app && python3 -c "
c['report']['output_dir'] = '/app/output'
output = generate_report(...)
shutil.copy2(output, '/data/output/' + Path(output).name)
"
```

## 2. 图片修改：H5 只展示前 5 张

**雷：** H5 卡片详情 = `thumb(images[0])` + `gallery(images[1:5] 最多 4 张)`。修改 DB 列表末尾（`images[-1]`、`images[-3:]`）不影响展示。

**避雷：**
| 目的 | 正确操作 |
|------|---------|
| 删画廊最后一张 | `del imgs[4]`（然后保留 `imgs[:4]` 让 gallery=3） |
| 改画廊后三张 | `imgs[2]=新图; imgs[3]=新图; imgs[4]=新图` |
| 只要封面 | `imgs = [imgs[0]]` |
| 删画廊第一张 | `del imgs[1]`（thumb 前移，gallery 自动前进） |

## 3. Shell 转义：flyctl + base64 + python3 三层地狱

**雷：** `flyctl machine exec 'sh -c "... python3 -c \"...\""'` 嵌套引号极容易断裂。

**避雷：**
```bash
# ✅ 稳定模式：本地生成 base64，远程 decode 执行
python3 -c "
import base64
script = '''...Python代码（避免内嵌单引号）...'''
print(base64.b64encode(script.encode()).decode())
" | pbcopy  # 复制

flyctl machine exec <mid> -a <app> 'sh -c "echo PASTE_BASE64 | base64 -d | python3"'

# ✅ 禁止：&& 串联多个 base64 命令（zsh 解析出错）
# ✅ 禁止：Python 代码内嵌 `\"` 或 `\\\"`（三重转义自残）
```

**本地生成 base64 的黄金模板：**
```python
python3 -c "
import base64
s = '''import sqlite3, json
db = sqlite3.connect(\"/data/content/content.db\")
cur = db.cursor()
# ... 你的代码，用 f-string 避免内嵌引号 ...
'''
print(base64.b64encode(s.encode()).decode())
"
```

## 4. DB 修改：先验证再渲染

**雷：** 改了 DB 就以为生效了，没验证 H5 实际内容。

**避雷：** 每次 DB 修改后立即验证：
```bash
# 1. 验 DB
flyctl machine exec ... 'python3 -c "..."'  # 查 articles.images 数量

# 2. 验 H5
curl -s https://xxx.fly.dev/output/file.html | python3 -c "
import re; html=...; print(len(re.findall(r'gallery-img', html)))
"

# 3. 两个都对了才算完
```

## 5. 部署冻结

**雷：** 长任务（抓取/成卡/压缩）运行期间 `git push` 会杀进程。

**避雷：**
```bash
# 部署前必查
flyctl machine exec <mid> -a <app> 'ls -la /data/output/crawl_*.log /data/output/img_*.log 2>/dev/null'
# 2 分钟内有写入 = 有任务在跑 → 禁止部署
```

## 6. 数据库路径

- 生产 DB：`/data/content/content.db`（Volume 挂载）
- 旧/僵尸 DB：`/app/data/content.db`、根目录 `content.db`
- `config/settings.yaml` 里 `database.path: data/content.db` 是**相对路径**（cwd=/app → /app/data/content.db）
- **始终用绝对路径** `/data/content/content.db`

## 7. 快速诊断清单

日报失败时按顺序查：
1. `flyctl machine list` → 确认机器活着
2. `ls /data/output/verify_*.log` → 晨间简报
3. `ls /data/output/gate*_20260618.log` → 三关是否跑完
4. DB 查 `gate3_selected` 和 `card_json` 状态
5. DB 查 `issues` 表 status

## 8. 晨间链路：抓取成功不等于入池成功

**雷：** 看见 `articles` 新增，就以为候选池 / A/B 池也会同步增加。

**真实事故：** `2026-06-20` 生产抓取已经跑完，`crawl_20260620.log` 汇总是：
```text
处理 891 | 新增 349 | 精选 201 | 跳过 542 | 缺图 0
```
但旧版 scheduler 在写完 `开始自动前两关收敛...` 后静默退出，`Gate1/Gate2` 没接上，导致“入库增加但池子没涨”。

**避雷：** 晨报至少分开报 3 个数：
```text
新增抓取数
Gate1 通过数
A/B 入池数
```
只看新增抓取数没有意义，必须同时看：
```bash
cd /app && python3 -c "
from src.scheduler import _count_gate1_left, _count_gate2_left
print('gate1_left', _count_gate1_left())
print('gate2_left', _count_gate2_left())
"
```

## 9. 调度器：裸后台会静默消失

**雷：** `start.sh` 用 `python src/scheduler.py &` 裸后台启动。进程一旦异常退出，Web 还活着，但晨间链路已经死了。

**真实事故：** `2026-06-20` 的 `scheduler.log` 停在：
```text
✅ run_crawl.py 完成
🔄 开始自动前两关收敛...
```
之后没有 `▶ run_gate1.py`，也没有 `gates_20260620.log`。容器里只剩 `gunicorn`，`src/scheduler.py` 已消失。

**避雷：**
- scheduler 必须有独立 supervisor，退出后自动重启
- scheduler 异常必须 `logger.exception(...)` 落 traceback，禁止静默死
- 看晨间事故时，先确认容器里是否还有 `src/scheduler.py` 常驻，不要只看网页活不活

## 10. Gate2 残留：JSON 解析失败不会自己好

**雷：** Gate2 批跑结束后还剩 1~2 条 backlog，以为只是“慢一点”。

**真实事故：** `2026-06-20` 补跑后主批次完成，但残留 2 条：
- `2618` `schindler elevates the seconds of transit into a cohesive architectural journey`
- `2720` `Bring a Loupe: A Broken Mulco Chronograph, A Gold Rolex Paul Newman, And A Lot In-Between`

日志里对应的是：
```text
无法解析 JSON 响应
Gate2 调用失败: None
```

**避雷：**
- `gate2_left > 0` 时，先查是不是解析失败残留，而不是盲目等
- 必查：
```bash
grep -n "无法解析 JSON 响应\|Gate2 调用失败" /data/output/gates_*.log
```
- 这类条目要单独重跑，不要和正常 backlog 混看

## 11. 已发布日报修卡：先认准 issue_id，不要凭“第几期文件名”猜

**雷：** 用户说“第五期”，就去改 `issue_id=5` 或旧文件 `daily_report_5_20260619.html`。

**真实事故：** 实际线上“第 5 期”对应的是：
- `issue_id=57`
- `issue_number='5'`
- `html_path=/data/output/daily_report_5_20260620.html`

同一 public issue number 可能对应不同日期文件，必须先查 `issues` 表真身。

**避雷：**
```bash
python3 -c "
import sqlite3
db = sqlite3.connect('/data/content/content.db')
for row in db.execute(\"select id, issue_number, status, created_at, html_path from issues order by id desc limit 20\"):
    print(row)
"
```
先锁定真实 `issue_id`，再动单卡。

## 12. 东方快车这类“看似重复”的选题，日期和路线是主键

**雷：** 标题都写东方快车、五日、意大利，就当成重复。

**真实事故：**
- `2052`：`东方快车推出意大利豪华火车之旅，灵感源自大巡游`
- `2042`：`东方快车推出意大利至土耳其五日奢华列车之旅`

两篇不是同一条新闻。真正区分它们的是：
- 路线：`罗马→西西里往返` vs `罗马→伊斯坦布尔`
- 时间：旧文 vs 当期有效出发行程
- 叙事核心：Grand Tour / Italy circuit vs Eurasian Orient Express route

**避雷：**
- 重复判断不能只看主题词，必须一起看：
  - `路线起止`
  - `月份/年份`
  - `是否首发/新开`
- 只要旅游/酒店/列车类文章含具体日期，先核 `title / hook / meta` 三处是否一致

## 13. 年份幻觉：DeepSeek 会把 2026 写成 2025

**雷：** 模型把未来行程年份写错，人工下一眼就会把它误判为旧文 / 过期文。

**真实事故：** 有的文章原文是 `2026年10月` 行程，卡片却被写成 `2025`，造成“这是不是过期了”的二次误判。

**避雷：**
- 所有涉及 `2025/2026/首程/开售/10月` 的卡，必须回源核日期
- 旅游与活动类卡片，`年份` 不能只信 LLM 文案，必须信源文或结构化字段
- 若标题、hook、meta 三处日期不一致，优先判为“时间语义风险”，不要先判重复或过期

## 14. 已发布单卡替换：最小安全步骤

已发布日报要单卡替换时，按这个顺序：
1. 先备份生产 DB 到 `/data/output/content_before_*.db`
2. 查清 `issue_id`、原卡 `article_id`、新卡 `article_id`
3. 确认新卡 `card_json` 已存在
4. 只改：
   - `issues.article_ids`
   - 原卡 `issue_id / issue_sort_order / status`
   - 新卡 `issue_id / issue_sort_order / status`
5. 只重生该 `issue_id` 的 H5
6. 用线上页面 grep 新旧标题，确认替换已生效

## 15. 审核列表：处理 C 档后不要跳回精选

**雷：** 人工捞 C 档文章时，点进文章处理归档或加入候选后，列表又跳回“精选”视图，导致每处理一篇都要重新切回 C 档。

**真实事故：** `2026-06-20` 补跑 Gate1/Gate2 后，用户在 C 档里捞文章，处理完单篇后筛选态没有保持，反复回到精选池，操作成本很高。

**避雷：**
- 文章处理动作完成后，应保留当前列表筛选态，包括：
  - 当前 tab / tier（例如 C 档）
  - 搜索词
  - 排序
  - 页码或滚动位置
- 前端不要在处理成功后无条件调用“默认精选列表”
- 如果必须刷新列表，也要用当前 URL query 或本地状态恢复到处理前视图

## 16. 文章详情：需要查看全部图片入口

**雷：** 详情页只能看到部分图片或首图，无法快速展开查看文章抓到的全部图片，人工判断配图质量和可替换图时不够用。

**真实事故：** `2026-06-20` 审核和修卡过程中，多次需要判断“是否有可用图”“H5 展示的前 5 张是否正确”，但详情页缺少“查看全部图片”的明确按钮。

**避雷：**
- 文章详情页应提供“查看全部图片”入口
- 入口至少要能显示：
  - `images` 字段的完整图片列表
  - 当前 H5 会使用的前 5 张标记
  - 封面图 `images[0]`
  - 画廊图 `images[1:5]`
- 图片相关修复不要只看 DB 原始列表，必须同时看“实际 H5 可见图”
