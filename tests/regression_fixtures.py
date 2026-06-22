"""
回归测试用例集 — 固定用例,每次改 prompt 后必跑
"""
import json

# 用例1: 侘寂酒店篇 — 期望被否决拦截
CASE_WABI_SABI_HOTEL = {
    "id": "test_wabi_001",
    "title": "MIRA Earth Studios: A Boutique Hotel Embracing Wabi-Sabi Aesthetics in Tulum",
    "summary": "MIRA Earth Studios 是墨西哥图卢姆一家全新精品酒店,由夯土墙与绿色屋顶构成,温暖极简的侘寂风格内饰贯穿全部12间客房,每间配有私人泳池与户外淋浴。",
    "content": "MIRA Earth Studios, the latest addition to Tulum boutique hotel scene, is a masterclass in wabi-sabi design. The 12-room property features rammed earth walls and green roofs blending with jungle surroundings. Interiors are warm minimalism with hand-troweled plaster walls in earthy tones, custom oak furniture, and linen textiles. Each suite has a private plunge pool and outdoor rain shower. The philosophy celebrates imperfection in every crack and knot.",
    "expected": {
        "veto_hit": True,
        "veto_rule_contains": "1",
        "gate2_tier": "D",
    }
}

# 用例2: 图文错位篇 — Keith Haring 标题 + 压缩袜正文
CASE_KEITH_HARING_MISMATCH = {
    "id": "test_mismatch_001",
    "title": "Keith Haring Lost Murals Rediscovered in Brooklyn Basement",
    "summary": "A basement renovation in Brooklyn uncovered what experts believe are previously unknown Keith Haring murals dating to 1982.",
    "content": "Compression socks have become increasingly popular among long-haul travelers. Medical studies show they reduce the risk of deep vein thrombosis by up to 60 percent. Brands like Comrad and Sockwell offer graduated compression with moisture-wicking fabrics. When choosing compression socks, look for 15-20 mmHg for travel. Merino wool blends offer natural temperature regulation. Most pairs cost 25 to 45 dollars and last 6-12 months with proper care. Travel nurses and pilots swear by them for long flights.",
    "expected": {
        "gate1_verdict": "fail",
        "gate1_failed_contains": "图文题一致",
    }
}

# 用例2b: 图文错位篇 — 巧克力标题 + Haring 正文
CASE_CHOCOLATE_BAR_MISMATCH = {
    "id": "test_mismatch_002",
    "title": "The World Most Expensive Chocolate Bar: Toak 450 Dollar Aged Cacao",
    "summary": "Toak Chocolate has released a limited edition bar made from 10-year-aged Ecuadorian Nacional cacao, priced at 450 dollars for 50 grams.",
    "content": "Keith Haring iconic radiant baby and barking dog motifs continue to appear in unexpected places. A new exhibition at the Museum of Modern Art explores how his subway drawings evolved from illegal interventions into recognized symbols of 20th-century art. The show brings together 120 works spanning Haring brief but explosive career from 1978 to 1990. Highlights include never-before-seen sketchbooks, collaborations with Andy Warhol and Jean-Michel Basquiat, and the complete set of Pop Shop merchandise.",
    "expected": {
        "gate1_verdict": "fail",
        "gate1_failed_contains": "图文题一致",
    }
}

# 用例3: 正常优质篇 — 盖里回顾展,期望通过 veto, gate2 A 档
CASE_GEHRY_RETROSPECTIVE = {
    "id": "test_quality_001",
    "title": "Frank Gehry Retrospective Opens at LACMA With Never-Seen Models and Sketches",
    "summary": "洛杉矶 LACMA 举办弗兰克盖里大型回顾展,展出60件建筑模型、200幅原始草图及从未公开的设计过程文档,覆盖从早期住宅到毕尔巴鄂古根海姆的全历程。",
    "content": "The Los Angeles County Museum of Art has opened the most comprehensive Frank Gehry retrospective ever mounted, featuring over 60 architectural models, 200 original sketches, and extensive design process documentation spanning six decades. The exhibition, running through March 2027, is organized by design methodology. Visitors can trace Gehry evolution from early plywood furniture experiments to the titanium curves of Bilbao. A dedicated workshop space allows visitors to handle Gehry actual sketch models. The show includes Gehry personal collection of artists who influenced him: Robert Rauschenberg, Claes Oldenburg, and Richard Serra. Tickets 25 dollars with private curator-led tours available.",
    "expected": {
        "veto_hit": False,
        "gate2_tier": "A",
        "fit_reasons_clean": True,
    }
}

# 用例4: fit_reasons 幻觉测试 — 含侘寂关键词的推荐理由
CASE_FIT_REASON_HALLUCINATION = {
    "id": "test_fit_001",
    "title": "京都安缦推出侘寂茶道体验课程",
    "summary": "京都安缦酒店推出为期三天的茶道深度体验,包含里千家茶道大师指导、古窑参观和自制茶碗工坊。",
    "content": "Aman Kyoto launches an immersive tea ceremony program led by Urasenke grand master Tanaka Sosho. The three-day experience includes private tea ceremony sessions, visits to historic kilns, and a hands-on chawan making workshop with local potters.",
    "mock_fit_reasons": [
        "侘寂风格与服务对象艺术坐标高度契合",
        "茶道文化深度体验"
    ],
    "expected": {
        "fit_reasons_contains_forbidden": True,
        "action": "pending_human",
    }
}

ALL_CASES = {
    "wabi_sabi_hotel": CASE_WABI_SABI_HOTEL,
    "keith_haring_mismatch": CASE_KEITH_HARING_MISMATCH,
    "chocolate_bar_mismatch": CASE_CHOCOLATE_BAR_MISMATCH,
    "gehry_retrospective": CASE_GEHRY_RETROSPECTIVE,
    "fit_reason_hallucination": CASE_FIT_REASON_HALLUCINATION,
}

# ===== 新增回归测试用例 =====

# 用例5: 松本十帖篇 — 日式老旅馆但侘寂/原木非主要卖点，期望通过否决
CASE_MATSUMOTO_ROOMS = {
    "id": "test_quality_002",
    "title": "Matsumoto Jujo: A Historic Ryokan Transforms Century-Old Bathhouse Into a Library",
    "summary": "松本十帖将一座百年公共浴场改造为图书馆兼休息室，保留原有木梁结构与瓷砖壁画，12间客房分布在三栋翻新建筑中，提供当地清酒品鉴与手漉和纸工坊。",
    "content": "Matsumoto Jujo, a 120-year-old ryokan in Nagano Prefecture, has unveiled its most ambitious renovation yet: transforming the property's original public bathhouse into a two-story library and lounge. The project preserved the massive hinoki beams and hand-painted ceramic tiles dating to 1903. Twelve guest rooms are spread across three buildings, each with distinct architectural character—a former kura warehouse, a taisho-era residence, and a modern annex by Kengo Kuma's office. The ryokan offers sake tastings with local brewers and handmade washi paper workshops. Room rates start at ¥85,000 per night including kaiseki dinner.",
    "expected": {
        "veto_hit": False,
        "gate2_tier_not": "D",
    }
}

# 用例6: 顺延流转 — 构造一篇候选文章，连续两期不入选
CASE_CARRYOVER_FLOW = {
    "id": "test_carryover_001",
    "title": "Test Carryover: A Design Exhibition That Keeps Getting Passed Over",
    "summary": "A design exhibition at MoMA showcasing mid-century Italian furniture gets passed over for two consecutive issues.",
    "content": "The Museum of Modern Art presents 'Italian Modern: 1945-1975', a comprehensive survey of post-war Italian design featuring over 200 objects including furniture by Gio Ponti, Achille Castiglioni, and Joe Colombo. The exhibition traces the evolution of Italian design from reconstruction through the economic boom, highlighting innovations in materials like molded plywood and injection-molded plastics. Key pieces include Ponti's Superleggera chair, Castiglioni's Arco lamp, and Colombo's Tube Chair. The show runs through September 2027 with special programming including curator-led tours every Friday afternoon.",
    "expected": {
        "veto_hit": False,
        "gate2_tier": "A",
        "carryover_after_1": 1,
        "archived_after_2": True,
    }
}

# 用例7: 时效出清 — 展期昨日截止的候选文章
CASE_EXPIRED_EXHIBITION = {
    "id": "test_expiry_001",
    "title": "Yayoi Kusama Infinity Rooms Extended Through Yesterday",
    "summary": "草间弥生无限镜屋展昨日结束，应在时效出清任务中被归档。",
    "content": "Yayoi Kusama's Infinity Mirror Rooms exhibition at the Hirshhorn Museum has concluded its extended run. The blockbuster show attracted over 800,000 visitors during its eighteen-month stay in Washington DC, making it the most visited contemporary art exhibition in the museum's history. The six immersive installations, including the newly restored 'Phalli's Field' from 1965, drew average wait times of three hours on weekends. A touring version will open at Tate Modern in London next spring, but the DC installation has been fully deinstalled.",
    "expected": {
        "veto_hit": False,
        "expired_archived": True,
        "archive_reason": "时效已过",
    }
}

# 用例8: 期刊闭环 — 选3篇生成一期，验证全流程
CASE_ISSUE_CLOSURE = {
    "id": "test_issue_001",
    "title": "Test Issue Closure: Three Articles For A Complete Issue Lifecycle",
    "summary": "验证期刊创建、文章状态变更、往期周报可见、落选顺延的完整闭环。",
    "articles": [
        {
            "title": "Article A: New Boutique Hotel Opens in Kyoto",
            "category": "精品酒店与度假",
            "content": "A new boutique hotel has opened in Kyoto's Higashiyama district, featuring 18 rooms designed by Tadao Ando. The property incorporates a 200-year-old tea house and offers views of Yasaka Pagoda.",
        },
        {
            "title": "Article B: Copenhagen Restaurant Noma Announces Reopening",
            "category": "美食与美酒",
            "content": "Noma will reopen in September after a six-month renovation that adds a fermentation lab and expands the dining room to 50 seats. Chef Redzepi promises an entirely new menu concept.",
        },
        {
            "title": "Article C: David Hockney Exhibition Draws Record Crowds in Tokyo",
            "category": "艺术与文化",
            "content": "David Hockney's largest ever exhibition in Asia has drawn over 200,000 visitors in its first month at the Mori Art Museum, featuring 120 works spanning six decades.",
        },
    ],
    "expected": {
        "issue_created": True,
        "all_in_issue": True,
        "carryover_incremented": True,
    }
}

ALL_CASES.update({
    "matsumoto_rooms": CASE_MATSUMOTO_ROOMS,
    "carryover_flow": CASE_CARRYOVER_FLOW,
    "expired_exhibition": CASE_EXPIRED_EXHIBITION,
    "issue_closure": CASE_ISSUE_CLOSURE,
})
