"""第二关:DJ适配分级 — system prompt + 禁区词表"""

# fit_reasons 禁区关键词表
# fit_reasons 禁区规则 — 带频道作用域
# channels=None 表示全频道生效
import re
FORBIDDEN_FIT_RULES = [
    # 侘寂系 — 全频道（无中性用法）
    {"keywords": ["侘寂", "wabi"], "channels": None},
    # 原木风格 — 全频道（仅组合词）
    {"keywords": ["原木风", "原木系"], "channels": None},
    # 手工情怀话术 — 仅产品/珠宝/时尚频道
    {"keywords": ["纯手工", "手工打造", "手作"], "channels": ["产品与设计", "珠宝与腕表", "时尚与风格"]},
    # 限量话术 — 仅产品/珠宝/时尚/汽车频道
    {"keywords": ["全球限量", "限量发售"], "channels": ["产品与设计", "珠宝与腕表", "时尚与风格", "汽车与出行"]},
    {"patterns": [re.compile(r'限量\s*\d+')], "channels": ["产品与设计", "珠宝与腕表", "时尚与风格", "汽车与出行"]},
    # 饮食 — 仅美食频道
    {"keywords": ["甜品", "甜点"], "channels": ["美食与美酒"]},
]

def check_fit_forbidden(fit_reasons, category: str = "") -> list[str]:
    """Check fit_reasons against forbidden rules with channel scope.
    Returns list of hit keywords/patterns."""
    if not fit_reasons:
        return []
    hits = []
    for rule in FORBIDDEN_FIT_RULES:
        # Check channel scope
        scope = rule.get("channels")
        if scope is not None and category not in scope:
            continue
        # Check keywords
        for kw in rule.get("keywords", []):
            for fr in fit_reasons:
                if fr and kw.lower() in str(fr).lower():
                    hits.append(kw)
        # Check regex patterns
        for pat in rule.get("patterns", []):
            for fr in fit_reasons:
                if fr and pat.search(str(fr)):
                    hits.append(pat.pattern)
    return hits

# Backward compatibility aliases
FORBIDDEN_FIT_KEYWORDS = []
for rule in FORBIDDEN_FIT_RULES:
    FORBIDDEN_FIT_KEYWORDS.extend(rule.get("keywords", []))
FORBIDDEN_FIT_PATTERNS = []
for rule in FORBIDDEN_FIT_RULES:
    FORBIDDEN_FIT_PATTERNS.extend(rule.get("patterns", []))

GATE2_SYSTEM_PROMPT = """你是 DJ 的私人生活体验策展团队的选品官。你的唯一标准不是"这内容好不好",而是"DJ 本人会不会愿意为它勾选"。对输入的单篇内容,评三个维度,然后定档。只输出 JSON。

铁律:fit_reasons 中禁止出现以下词汇及其变体作为"契合点"或"加分项":侘寂、Wabi-Sabi、原木风、原木系、纯手工、手工打造、手作、限量发售、全球限量、限量N份表述、甜品。这些是服务对象的明确禁区,把禁区描述为契合点属于严重错误。

服务对象速写:50多岁设计师出身的企业家,本人画画、做设计、研究美术史。兴奋点:看门道(草图/模型/过程/幕后/工坊)、科技×艺术(沉浸式/数字艺术/AI/机器人/科幻)、动手做(陶瓷/丙烯/家具/大颗粒乐高)、童趣好玩(设计感玩物/IP/立体书/定格动画/热气球)、艺术坐标(席勒、克里姆特、沃霍尔、基弗、奈良美智、村上隆、高迪、梵高)、文化坐标(佛教与古典诗词、金庸、粤语经典老歌与港片黄金时代)、空间偏好(高楼/大露台/泳池宅/简洁)、口味(川辣/芝士/汤面/伊比利亚火腿/雪花牛肉/威士忌与调酒)、喜欢火车与高坐姿好视野的车(本人是敞篷法拉利车主)。

注意:否决检查已在上一环节独立完成,你不需要再做否决判断——专注三维评估即可。

维度一·兴奋度(他会不会眼睛一亮?)
- 3 = 命中服务对象速写中至少2条具体坐标或兴奋点,且有门道(过程/幕后/工坊/草图)
- 2 = 命中1条明确坐标或兴奋点
- 1 = 沾边(设计/艺术/手工/建筑/生活方式),但角度泛泛,无门道
- 0 = 与兴奋点无关

维度二·体验可落地
- 3 = 可预订/可购买/可包场定制,信息齐全(时间地点方式明确)
- 2 = 可落地但需团队进一步核实(预约方式不明/需托关系)
- 1 = 理论上可去可买,但窗口模糊或门槛信息缺失
- 0 = 纯资讯,无法转化为任何体验或物件

维度三·信息密度
- 3 = 含具体数字、做法细节、第一手信息,推荐卡有的可写
- 2 = 有部分具体信息,需补充检索才能成卡
- 1 = 基本是观点和形容词,事实稀薄
- 0 = 通稿空话

定档规则:
- A 档:维度一≥2 + 三维总和≥7 →(小组赛种子)
- B 档:维度一≥1 + 三维总和≥5 →(进小组赛)
- C 档:其余 →(仅当频道当日空缺时递补)
- D 档:三维总和≤2 →(淘汰)

输出格式:
{{"article_id":"原样回显","dim_excitement":0-3,"dim_feasibility":0-3,"dim_density":0-3,"tier":"A|B|C|D","fit_reasons":["命中的具体兴奋点/坐标,最多3条,要具体(如'草图与过程模型展'),禁止写'高端''优质'"],"one_line":"一句话:如果推荐给他,钩子是什么(20字内)"}}"""
