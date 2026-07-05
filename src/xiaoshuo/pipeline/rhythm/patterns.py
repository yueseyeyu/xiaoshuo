# -*- coding: utf-8 -*-
"""
patterns.py — 节奏分析正则模式 SSOT (Single Source of Truth)
=============================================================
所有爽点/冲突/钩子/情绪正则模式的唯一来源。
rhythm.rule_analyzer 和 comparison_engine._rich_scan 均从此导入。

用法:
  from xiaoshuo.pipeline.rhythm.patterns import (
      PLEASURE_FACE_SLAP, CONFLICT_KW_ALL, CLIFFHANGER, ...
  )
"""
from __future__ import annotations

import re

# ============================================================
# 显式爽点 (传统打脸升级流)
# ============================================================
PLEASURE_FACE_SLAP = re.compile(r"打脸|嘲讽|看不起|小瞧|轻视|不屑|冷笑|嗤笑|凭什么|你也配|就这|惊呆|震惊|瞪大|倒吸|不可思议|怎么可能|不可能！|傻眼|目瞪口呆|鸦雀无声")
PLEASURE_LEVEL_UP = re.compile(r"突破|晋级|进阶|升级|渡劫|突破瓶颈|实力暴涨|修为大增|顿悟|觉醒|解锁|开启|新生|蜕变|脱胎换骨")
PLEASURE_CRUSH = re.compile(r"碾压|秒杀|横扫|秒败|一击|一招|摧枯拉朽|不堪一击|螳臂当车|随手|轻易|不费吹灰|挥手之间")
PLEASURE_COMEBACK = re.compile(r"绝地|绝境|反杀|逆转|翻盘|反败为胜|逆转乾坤|置之死地|破而后立|柳暗花明|峰回路转|起死回生|绝处逢生")
PLEASURE_HIDDEN = re.compile(r"扮猪|藏拙|隐藏实力|低调|显露|暴露|亮出|底牌|真正实力|终于出手|不再隐藏")
PLEASURE_GENERAL = re.compile(r"哈哈|爽|痛快|舒服|牛逼|厉害|强[^调化学]|很强|极强|无敌|逆天|恐怖如斯|骇然|惊呼|赞叹|佩服|崇拜|仰望|敬畏")

# ============================================================
# 隐式爽点 (智斗流/羁绊流专属)
# ============================================================
PLEASURE_BOND = re.compile(
    r"羁绊|守护|为你|替我|并肩|一起|等我|别走|回来|留下|陪你|跟你|"
    r"我会保护|我答应|不放手|伸出手|碰了碰|贴着|靠着|"
    r"第一[个次位]|唯一|只有你|只要你|除了你|不会让|不许|不行|不准"
)
PLEASURE_COGNITIVE = re.compile(
    r"原来如此|明白了|懂了|终于知道|恍然大悟|识破|看穿|洞察|"
    r"算到|预判|提前|早[就已]|那一瞬|猛然意识|忽然想到|突然想起|"
    r"面板弹出|推演显示|模拟得出|演算|第一条规则|从未见过"
)
PLEASURE_SACRIFICE = re.compile(
    r"燃[烧尽]|耗尽|透支|本源|代价|交换|换[取来]|付出|承受|扛住|撑住|"
    r"拼了|不管[了不]|豁出去|不计代价|不重要|没关系|值得|心甘情愿"
)
PHYSIO_REACTION = re.compile(
    r"瞳孔[骤微]?缩|呼吸[一戛]?滞|心头[一]?[震颤]|脊背发?凉|头皮发麻|"
    r"血液[仿凝]|浑身[一震]|心头[一]紧|掌心[出渗]|指尖[微发]颤|"
    r"眼眶[一微]?红|鼻子[一]?酸|喉[咙头][一发]?紧|说不出话|愣[在住]了|"
    r"沉默[了很]?久|久久[没未不]|一言不发|一动不动|半晌"
)

# ── 隐式爽点 — 策略/资源/人际关系 ──
PLEASURE_STRATEGY = re.compile(
    r"计策|谋划|布局|算计|预判|先[一]步|棋[高一]?着|将[了]?一军|"
    r"反[将计]?|设局|做局|套路|坑[了他]|算[计准]?|"
    r"计划[得通]|顺利|完美|不[出动]所料|果然|果[真不其]然"
)
PLEASURE_RESOURCE = re.compile(
    r"收获|获得|得到|入手|到[手账]|收集|囤积|储备|库存|"
    r"物资|粮食|水源|药[品剂]|武器|装备|弹药|"
    r"发现了|找到了|挖[到出]|捡[到回]|开[出启]了"
)
PLEASURE_SOCIAL = re.compile(
    r"信[任赖]|托付|交[给托]|认可|承认|接纳|加入|"
    r"成为[一了]|列入|纳入|吸收|收[编留]|"
    r"追随|跟随|效忠|臣服|折服|震慑|威[慑压]"
)

# ── 反转爽点 (6类) ──
PLEASURE_BACKFIRE = re.compile(
    r"弄巧成拙|自食恶果|反噬|搬起石头|自作自受|害人终害己|"
    r"反而帮了|反倒成就|因缺少|偷走.*失败|反而.*突破|"
    r"反被|反遭|毒计.*反成|阴谋.*反而"
)
PLEASURE_TRAP_MASTER = re.compile(
    r"请君入瓮|精准排雷|引蛇出洞|将计就计|故意中计|假装中计|"
    r"早已看穿|早就知道|故意.*引诱|故意.*踩入|明知.*陷阱|"
    r"假装重伤.*引诱|设[下个].*套|等着.*跳"
)
PLEASURE_KNOWLEDGE_GAP = re.compile(
    r"降维打击|跨频|现代知识|高维常识|异世界.*常识|"
    r"这个世界的规则|用.*知识.*解决|脑补|过度解读|"
    r"高深莫测|暗自心惊|心生敬畏|暗自揣测|"
    r"随口.*一句|小动作.*被|高人.*解读"
)
PLEASURE_HIDDEN_VALUE = re.compile(
    r"变废为宝|废品.*极品|垃圾.*宝物|残次品.*触发|"
    r"没人要|看不上|不起眼.*隐藏|隐藏.*机制|"
    r"精准扶贫|绝地.*修炼|恰好.*需要|因祸得福|"
    r"折磨.*恰好|最[适合]怕.*反而|绝境.*恰好"
)
PLEASURE_IDENTITY_REVEAL = re.compile(
    r"微服私访|大水冲龙王庙|靠山.*是|"
    r"随手帮助|普通老头|顶级掌权|最高特权|"
    r"没想到.*竟是|原来.*是|竟[然是].*认识|"
    r"真是.*有眼不识|不知.*身份|认出.*身份"
)
PLEASURE_FORESHADOW_PAYOFF = re.compile(
    r"拼图归位|最后.*碎片|关键.*碎片|多年.*得到|"
    r"当年.*无意|终于.*用上|终极.*钥匙|打开.*神门|"
    r"破石头.*关键|碎片.*完整|伏笔.*回收|埋.*线.*终于"
)

# ============================================================
# 爽点时序标签 (即时爽 vs 延迟爽)
# ============================================================
PLEASURE_TIMING = {
    "打脸": "instant",
    "突破": "instant",
    "碾压": "instant",
    "绝地反击": "instant",
    "扮猪吃虎": "delayed",
    "羁绊": "delayed",
    "认知突破": "instant",
    "牺牲": "delayed",
    "策略": "delayed",
    "资源": "instant",
    "社交": "delayed",
    "反派反噬": "instant",
    "反陷阱": "instant",
    "认知碾压": "instant",
    "隐藏价值": "instant",
    "身份反转": "delayed",
    "伏笔回收": "delayed",
}

# ============================================================
# 爽点权重表 (r值: 从 calibrate_v2 标定, 新增项用估算值)
# ============================================================
PLEASURE_WEIGHTS = {
    "slap": 0.096,
    "level": 0.086,
    "crush": 0.300,
    "comeback": 0.178,
    "hidden": 0.108,
    "general": 0.108,
    "bond": 0.155,
    "cognitive": 0.017,
    "sacrifice": 0.0,
    "physio": 0.179,
    "strategy": 0.108,
    "resource": 0.108,
    "social": 0.108,
    # v12 反转爽点 (估算, 待 calibrate_v2 标定)
    "backfire": 0.108,
    "trap_master": 0.108,
    "knowledge_gap": 0.108,
    "hidden_value": 0.108,
    "identity_reveal": 0.108,
    "foreshadow_payoff": 0.108,
}

# ============================================================
# 爽点子类型名称映射 (用于 dominant_sub 计算)
# ============================================================
PLEASURE_SUBTYPE_NAMES = [
    ("打脸", "slap"),
    ("突破", "level"),
    ("碾压", "crush"),
    ("绝地反击", "comeback"),
    ("扮猪吃虎", "hidden"),
    ("羁绊", "bond"),
    ("认知突破", "cognitive"),
    ("牺牲", "sacrifice"),
    ("策略", "strategy"),
    ("资源", "resource"),
    ("社交", "social"),
    ("反派反噬", "backfire"),
    ("反陷阱", "trap_master"),
    ("认知碾压", "knowledge_gap"),
    ("隐藏价值", "hidden_value"),
    ("身份反转", "identity_reveal"),
    ("伏笔回收", "foreshadow_payoff"),
]

# ============================================================
# 冲突正则 (战斗 + 心理 + 道德 + 环境 + 社会 + 悬疑)
# ============================================================
CONFLICT_PSYCHOLOGICAL = re.compile(
    r"试探|算计|博弈|陷阱|圈套|局[中里]|将计就计|反将|识破|"
    r"怀疑|猜忌|戒备|提防|警觉|怀疑|不信任|动摇|犹豫|迟疑|"
    r"他知[道晓]|她知[道晓]|没[说有]穿|假装|装作|掩饰|隐藏"
)
CONFLICT_MORAL = re.compile(
    r"抉择|选择|两条路|牺牲谁|换谁|保谁|救[谁不]|放弃|舍弃|"
    r"背叛|出卖|欺骗|隐瞒|瞒着|对不起|亏欠|负罪|愧疚|忏悔|"
    r"底线|原则|不能|不该|不可以|越界|突破底线|做不到"
)
CONFLICT_ENVIRONMENT = re.compile(
    r"饥饿|饥渴|干渴|脱水|辐射|污染|毒气|窒息|缺氧|"
    r"崩塌|坍塌|陷落|废墟|残骸|瓦砾|断壁|"
    r"极寒|酷暑|严寒|灼热|暴晒|酸雨|变异|异化|侵蚀|吞噬"
)
CONFLICT_SOCIAL = re.compile(
    r"规则|秩序|权力|夺权|争权|上位|夺位|取而代之|"
    r"质疑|反对|排斥|驱逐|孤立|排挤|针对|"
    r"凭什么你|谁同意的|谁允许|规矩|规定|制度|"
    r"领头|首领|领袖|话语权|说了算|一票否决"
)
CONFLICT_SUSPENSE = re.compile(
    r"诡异|恐怖|异常|不详|扭曲|怪异|反常|离奇|奇怪|毛骨悚然|"
    r"秘密|真相|隐瞒|谎言|背后|暗中|偷偷|悄悄|窥视|监视|"
    r"阴森|黑暗[中的]|深[处渊底]|未知|不可名状|不可描述|"
    r"消失|失踪|死去|复活|变异|扭曲|融化|腐[烂杇]|"
    r"不对劲|有[问]题|有问题|哪里不对|感觉不对|直觉|"
    r"危[险机]|威胁|逼近|降临|笼罩|弥漫|渗透|蔓延"
)

# 合并冲突正则列表 (v5: 战斗 + 心理 + 道德 + 环境 + 社会 + 悬疑)
CONFLICT_KW_ALL = [
    re.compile(
        r"你敢|休想|去死|找死|不可能！|我不信|凭什么|"
        r"战斗|厮杀|搏杀|血战|激战|苦战|酣战|大战|对决|决斗|"
        r"杀意|杀气|怒吼|暴怒|杀机|出手|进攻|攻击|反击|反攻|"
        r"偷袭|暗算|围杀|刺杀|击杀|斩杀|"
        r"一刀|一剑|一拳|一掌|一枪|武器|兵器|法宝|神通|禁术|秘术|底牌|"
        r"拼命|拼死|搏命|殊死|生死|致命|致命一击|决一死战|不死不休"
    ),
    CONFLICT_PSYCHOLOGICAL,
    CONFLICT_MORAL,
    CONFLICT_ENVIRONMENT,
    CONFLICT_SOCIAL,
    CONFLICT_SUSPENSE,
]

# ============================================================
# 对话/感叹/负面情绪/钩子
# ============================================================
DIALOGUE_PAT = re.compile(
    r'[「『"\u201c\u300c\u300e](.+?)[」』"\u201d\u300d\u300f]|'
    r'[^\n]*[:：]["\u201c].+["\u201d]'
)
EXCLAM_PAT = re.compile(r'！|!|\?|？')

NEGATIVE = re.compile(
    r"哭|泪|死|痛|绝望|恐惧|害怕|逃|躲|惨|败|输|危险|致命|"
    r"无奈|苦涩|悲哀|悲凉|凄凉|孤寂|苍凉|毁灭|湮灭|陨落|逝去|"
    r"悲伤|悲痛|心碎|心寒|心凉|心如死灰|万念俱灰"
)

CLIFFHANGER = re.compile(
    r"就在这时|突然[一之]|忽然|骤然|猛然|只见[那这]|赫然|不料|"
    r"竟然|居然|竟[然敢会]|"
    r"下一刻|下一秒|紧接着|与此同时|眼下|眼下这一幕|"
    r"未完待续|欲知后事|预知后事|"
    r"危机降临|危险[正即]|不妙|不好[了啦]|糟糕|"
    r"\?[ \n]*$|难道|莫非|怎么[会可]|为[什]?么|"
    r"一定会|必定|必将|来日|改日|下次|等着|走着瞧",
)

# ============================================================
# v9.0: 信息炸弹4类子分类 (来源: "4个追读技巧" — 章节开头信息炸弹)
# 用于检测每章开头50字内的"注意力抓取"机制类型
# ============================================================
INFO_BOMB_CRISIS = re.compile(
    r"再不.{0,6}就|来不及|只剩|最后.{0,4}(?:机会|时间|期限)|"
    r"命悬一线|危在旦夕|生死存亡|倒计时|"
    r"中毒|剧毒|毒性|发作|解药|"
    r"即将.*(?:死亡|毁灭|崩溃|爆炸)"
)
INFO_BOMB_JOY = re.compile(
    r"中了|获得.*(?:大奖|宝物|传承|秘籍)|意外之喜|天降|"
    r"一夜暴富|突然.*发财|捡到|"
    r"突破|晋级|升阶|觉醒.*血脉"
)
INFO_BOMB_TEMPTATION = re.compile(
    r"只要.{0,10}就能|巨大的(?:利益|好处|收获|宝藏)|"
    r"无法拒绝|难以拒绝|诱人|"
    r"若是.*能得到|一旦.*(?:成功|获得|掌握)|"
    r"前途无量|钱途无量|一本万利"
)
INFO_BOMB_GOSSIP = re.compile(
    r"你听说了吗|据说|听说|传言|"
    r"秘密|隐秘|不可告人|"
    r"你知道吗|告诉你一个|想不到|"
    r"背后.*(?:势力|靠山|真相)|水很深"
)

# 信息炸弹类型索引 (供 rhythm_analyzer / comparison_engine 使用)
INFO_BOMB_PATTERNS = {
    "crisis": INFO_BOMB_CRISIS,
    "joy": INFO_BOMB_JOY,
    "temptation": INFO_BOMB_TEMPTATION,
    "gossip": INFO_BOMB_GOSSIP,
}

INFO_BOMB_TYPE_NAMES = [
    ("危机信息", "crisis"),
    ("大喜信息", "joy"),
    ("诱惑信息", "temptation"),
    ("八卦信息", "gossip"),
]

# ============================================================
# 反套路信号 + 情绪价值检测
# ============================================================
ANTI_TROPE = re.compile(
    r"不[想愿打算要]?变强|不[想愿打算要]?升级|不[想愿打算要]?战斗|"
    r"拒绝[系统金手指]|不要[系统任务]|不想[穿越重生]|"
    r"[只想只要]?[退休归隐躺平平淡安逸苟着]|"
    r"[明明已经].*?[却还要].*?[被迫无奈]|"
    r"系统[呢在哪]|为什么[是我选]|这[不没]科学|太离谱|太荒唐"
)

EMOTION_HIGH = re.compile(
    r"绝望|崩溃|疯狂|怒吼|咆哮|撕心裂肺|痛不欲生|生不如死|"
    r"狂喜|癫狂|痴狂|失控|失态|歇斯底里|情绪崩溃|精神[崩垮]"
)
EMOTION_LOW = re.compile(
    r"平静|淡然|释然|坦然|从容|平和|从容|波澜不惊|心如止水|"
    r"麻木|冷漠|漠然|空洞|放空|放[弃手]|认命|听天由命"
)
EMOTION_BURNOUT = re.compile(
    r"累[了极垮]|疲惫|筋疲力尽|精疲力竭|心力交瘁|身心俱疲|"
    r"乏力|无[能力]为力|撑不住|扛不住|受不了|熬不住"
)

# ============================================================
# comparison_engine 用的简化模式 (供 _rich_scan 使用)
# ============================================================
# 钩子模式 (4类)
RICH_HOOK_PATTERNS = {
    "cliffhanger": re.compile(r'悬念|究竟|到底|未完|待续|下回|欲知'),
    "reversal": re.compile(r'反转|逆袭|翻盘|竟然|原来|真相|秘密'),
    "emotion_bomb": re.compile(r'牺牲|守护|最[后终]|绝不|为了|只为'),
    "info_drop": re.compile(r'透露|揭示|浮现|终于|知道'),
}

# 冲突模式 (5类, 简化版供 _rich_scan 使用)
RICH_CONFLICT_PATTERNS = {
    "combat": re.compile(r'战斗|杀|轰|斩|刺|劈|拳|剑|枪|刀'),
    "psychological": re.compile(r'恐惧|愤怒|绝望|挣扎|崩溃|怀疑|内疚'),
    "moral": re.compile(r'选择|天平|代价|牺牲|背叛'),
    "environmental": re.compile(r'崩塌|毁灭|洪水|地震|毒气|辐射'),
    "social": re.compile(r'排挤|误会|陷害|诬蔑|舆论'),
}

# 爽点模式 (8类, 简化版供 _rich_scan 使用)
RICH_PLEASURE_PATTERNS = {
    "face_slap": re.compile(r'打脸|反杀|碾压|打翻|吊打|秒杀'),
    "breakthrough": re.compile(r'突破|升级|进阶|觉醒|领悟|融会'),
    "overwhelm": re.compile(r'镇压|横扫|碾压|碾压一切|无敌'),
    "comeback": re.compile(r'绝地|翻盘|逆袭|反败|逆转'),
    "hidden_master": re.compile(r'隐藏|低调|收敛|扮猪|显露|真正实力'),
    "bond": re.compile(r'守护|并肩|托付|生死|交心|羁绊'),
    "cognition": re.compile(r'原来如此|终于明白|恍然大悟|我懂了|悟了'),
    "sacrifice": re.compile(r'牺牲自己|舍身|赴死|以命|拼尽|最后一'),
}

# 正面/负面关键词 (简化版供 _rich_scan 使用)
RICH_POS_KW = re.compile(r'好|强|厉害|痛快|爽|舒服|赞|惊|震|叹|佩|牛|棒|绝|妙|胜')
RICH_NEG_KW = re.compile(r'恐惧|愤怒|绝望|挣扎|崩溃|怀疑|内疚|悲|痛|苦|恨|忧|愁|惨|伤|死|亡|危|难')
RICH_PHYSIO_KW = re.compile(r'心跳|呼吸|血[液压]|肌肉|骨骼|瞳孔|冷汗|颤抖|颤栗|寒毛|鸡皮|毛孔')

# ============================================================
# v2: 6类阻碍检测 — 与18爽点形成对偶结构
# 爽点是"突破阻碍后的奖励"，阻碍是"爽点的前置张力"
# ============================================================

OBSTACLE_ENEMY = re.compile(
    r"被\w*追杀|遭到\w*伏击|\w*挡在前面|拦住|阻拦|截住|包围|封锁|"
    r"强敌|劲敌|大敌|宿敌|追兵|敌人|敌军|敌对|敌视"
)
OBSTACLE_RULE = re.compile(
    r"规定|禁止|律法|宗门规矩|不能违反|条令|法则|铁律|禁令|"
    r"门槛|准入|资格|条件|限制|约束|不得|严禁|不准"
)
OBSTACLE_RESOURCE = re.compile(
    r"缺少|不足|耗尽|匮乏|短缺|没有.*灵石|没有.*丹药|没有.*钱|"
    r"买不起|付不起|供不起|消耗.*殆尽|入不敷出|囊中羞涩"
)
OBSTACLE_IDENTITY = re.compile(
    r"身份暴露|伪装被识破|不能暴露|隐瞒不住|被发现|被认出|"
    r"庶出|私生|低等|下等|卑贱|不配|没资格|身份.*限制"
)
OBSTACLE_TIME = re.compile(
    r"只剩|来不及|最后一刻|倒计时|即将|马上|很快|"
    r"时间不多了|迫在眉睫|争分夺秒|刻不容缓|紧要关头"
)
OBSTACLE_INNER = re.compile(
    r"犹豫|恐惧|心魔|动摇|无法下定决心|徘徊|挣扎|"
    r"不敢|害怕|畏惧|退缩|踌躇|彷徨|内心.*矛盾|天人交战"
)

OBSTACLE_KW_ALL = [
    OBSTACLE_ENEMY,
    OBSTACLE_RULE,
    OBSTACLE_RESOURCE,
    OBSTACLE_IDENTITY,
    OBSTACLE_TIME,
    OBSTACLE_INNER,
]

OBSTACLE_TYPE_NAMES = [
    ("敌人阻碍", "enemy"),
    ("规则阻碍", "rule"),
    ("资源阻碍", "resource"),
    ("身份阻碍", "identity"),
    ("时间阻碍", "time"),
    ("内心阻碍", "inner"),
]

# ============================================================
# v2: 命运变化检测 — 量化"每章是否推动主角命运轨迹"
# 避免堆砌无关日常 → "水文"核心指标
# 注意: "成功/完成/达成" 单独使用太常见，需要上下文限定
# ============================================================

FATE_PROGRESS = re.compile(
    r"离\w*更近一步|终于\w*|终于能|迈出.*一步|迈进|跨入|"
    r"取得.*进展|达成.*目标|完成.*任务|成功.*突破|实现.*愿望|破局|打开.*局面"
)
FATE_SETBACK = re.compile(
    r"失去|被夺|失败|重伤|死亡|陨落|跌落|坠落|"
    r"惨败|溃败|一败涂地|全军覆没|功亏一篑|前功尽弃"
)
FATE_REVELATION = re.compile(
    r"原来是|真相.*大白|没想到.*竟然|竟然是|实则|揭开.*真相|揭晓|"
    r"浮出水面|水落石出|豁然开朗"
)
FATE_RELATIONSHIP = re.compile(
    r"背叛|结盟|决裂|和解|反目|倒戈|投靠|归顺|"
    r"分道扬镳|冰释前嫌|化敌为友"
)

FATE_SIGNALS = [
    ("goal_progress", FATE_PROGRESS),
    ("setback", FATE_SETBACK),
    ("revelation", FATE_REVELATION),
    ("relationship_shift", FATE_RELATIONSHIP),
]


# ============================================================
# 7种叙事元模式 (Plot DNA Meta-Patterns)
# 来源: 建议文件 "180种高能情节 → 7种叙事元模式"
# 价值: 题材specific情节库, 与通用爽点/反转正则互补
# 用法: from xiaoshuo.pipeline.rhythm.patterns import META_PATTERNS, PLOT_DNA_PATTERNS
# ============================================================

# ── 元模式正则检测器 ──
# 每种元模式对应一组正则, 用于在章节文本中检测该模式是否出现

# 模式1: 阈值突破 (Threshold Break)
THRESHOLD_BREAK = re.compile(
    r'理智值.*(?:崩溃|临界|瓶颈|极限)|SAN值.*(?:跌|降|临界)|'
    r'生态适应.*(?:极限|濒临)|精神力.*(?:瓶颈|极限|超限)|'
    r'修为.*(?:瓶颈|极限|壁障)|境界.*(?:瓶颈|无法突破)|'
    r'濒临.*(?:崩溃|极限|临界)|突破.*(?:瓶颈|极限|壁障)|'
    r'顿悟|觉醒.*(?:血脉|天赋|能力)|超限.*爆发|'
    r'看透.*(?:规则|本质)|抵御.*(?:心智|精神).*侵蚀'
)

# 模式2: 身份伪装 (Identity Masquerade)
IDENTITY_MASQUERADE = re.compile(
    r'伪装成.*(?:NPC|信徒|土著|海盗|护卫|侍从|下人)|'
    r'混进.*(?:诡异|邪教|敌方|敌营|部落)|'
    r'混入.*(?:阵营|据点|组织|内部)|'
    r'假扮.*(?:身份|角色|信徒|仆从)|'
    r'伪装身份|隐藏身份.*潜入|冒充.*(?:成员|信徒|手下)|'
    r'深入.*(?:敌营|虎穴|老巢|腹地)'
)

# 模式3: 遗物觉醒 (Artifact Awakening)
ARTIFACT_AWAKENING = re.compile(
    r'随身.*(?:物品|护符|玉佩|法器).*(?:觉醒|激活|异变)|'
    r'(?:遗物|圣物|古物).*(?:觉醒|激活|异变|共鸣)|'
    r'偶然.*(?:得到|捡到|获得).*(?:遗物|宝物|传承|秘宝)|'
    r'(?:护符|玉佩|项链|戒指|法器).*(?:发光|震动|发烫|共鸣)|'
    r'觉醒.*(?:特殊能力|隐藏能力|血脉之力)|'
    r'获得.*(?:传承|记忆|力量|能力)'
)

# 模式4: 信息差博弈 (Information Asymmetry)
INFORMATION_ASYMMETRY = re.compile(
    r'设局.*(?:反杀|反抢|清剿|端掉)|'
    r'(?:揪出|识破|揭露).*(?:内鬼|叛徒|卧底)|'
    r'用.*(?:低级|普通|简单).*(?:道具|武器).*(?:反杀|击败|击杀).*(?:高端|高阶|强大)|'
    r'信息差|信息优势|掌握.*情报|'
    r'早已.*(?:看穿|知道|算到|布局)|故意.*(?:引诱|暴露|示弱)|'
    r'(?:引蛇出洞|请君入瓮|将计就计|关门打狗)'
)

# 模式5: 阵营重构 (Faction Restructuring)
FACTION_RESTRUCTURING = re.compile(
    r'(?:新人|调查员|土著|玩家|成员).*(?:建立|树立).*(?:威信|威望|声望)|'
    r'立威|收编.*(?:小队|成员|势力|部下)|'
    r'(?:成为|被推举为|被认可为).*(?:领袖|首领|队长|核心)|'
    r'(?:追随|效忠|臣服|归顺)|'
    r'(?:分配|瓜分|掌控).*(?:资源|领地|利益)|'
    r'整合.*(?:势力|资源|人手)|重组.*(?:团队|势力|阵营)'
)

# 模式6: 真相揭露 (Truth Revelation)
TRUTH_REVELATION = re.compile(
    r'(?:破解|破译|解读).*(?:规则|密码|符文|石板|典籍|古籍)|'
    r'揭开.*(?:真相|秘密|身世|血脉|诅咒|阴谋)|'
    r'发现.*(?:表世界|里世界|隐藏|未知|真相)|'
    r'(?:家族|身世|血脉).*(?:诅咒|秘密|真相|封印)|'
    r'(?:认知|世界观).*(?:颠覆|崩塌|重构)|'
    r'原来.*(?:一直|竟然|其实)|真相.*(?:大白|浮出水面|揭晓)'
)

# 模式7: 外部危机 (External Crisis)
EXTERNAL_CRISIS = re.compile(
    r'全服.*(?:灭团|危机|灾难)|全球.*(?:危机|苏醒|爆发)|'
    r'多.*(?:地区|星球|区域).*(?:异象|冲突|爆发)|'
    r'诡异.*(?:入侵|攻击|席卷)|安全区.*(?:沦陷|入侵|告急)|'
    r'古神.*(?:苏醒|降临|复苏)|末日.*(?:降临|逼近|爆发)|'
    r'(?:大规模|全面|全服).*(?:战争|入侵|灾难|危机)|'
    r'所有人.*(?:面临|陷入|卷入).*(?:危机|危险|灾难)'
)

# ── 元模式索引 ──
META_PATTERNS = {
    "threshold_break": {
        "name": "阈值突破",
        "description": "主角某数值濒临极限, 突破后获得成长",
        "pattern": THRESHOLD_BREAK,
        "tension_curve": "上升→平台→断崖→跃升",
        "applicable_genres": ["规则怪谈", "克苏鲁", "星际拓荒", "修仙", "玄幻"],
    },
    "identity_masquerade": {
        "name": "身份伪装",
        "description": "主角伪装成敌方/内部人员获取情报",
        "pattern": IDENTITY_MASQUERADE,
        "tension_curve": "潜入→试探→危机→暴露/成功",
        "applicable_genres": ["规则怪谈", "克苏鲁", "星际拓荒", "古代悬疑", "都市"],
    },
    "artifact_awakening": {
        "name": "遗物觉醒",
        "description": "随身物品/遗物觉醒特殊能力",
        "pattern": ARTIFACT_AWAKENING,
        "tension_curve": "获得→试探→依赖→反噬/掌控",
        "applicable_genres": ["全部"],
    },
    "information_asymmetry": {
        "name": "信息差博弈",
        "description": "主角掌握他人不知道的信息, 设局反杀",
        "pattern": INFORMATION_ASYMMETRY,
        "tension_curve": "隐忍→布局→引爆→清算",
        "applicable_genres": ["全部"],
    },
    "faction_restructuring": {
        "name": "阵营重构",
        "description": "主角在群体中建立威信/收编/重组势力",
        "pattern": FACTION_RESTRUCTURING,
        "tension_curve": "局外人→被接纳→核心→领袖",
        "applicable_genres": ["规则怪谈", "克苏鲁", "星际拓荒", "古代悬疑", "玄幻"],
    },
    "truth_revelation": {
        "name": "真相揭露",
        "description": "逐步揭开隐藏真相, 颠覆认知",
        "pattern": TRUTH_REVELATION,
        "tension_curve": "疑点→探索→碎片→拼图→颠覆",
        "applicable_genres": ["克苏鲁", "规则怪谈", "星际拓荒", "古代悬疑", "悬疑"],
    },
    "external_crisis": {
        "name": "外部危机",
        "description": "大规模外部威胁降临, 考验主角",
        "pattern": EXTERNAL_CRISIS,
        "tension_curve": "平静→预兆→爆发→混乱→新秩序",
        "applicable_genres": ["全部"],
    },
}

# ── 题材specific情节模式 (供 PlotDNAMatcher 使用) ──
PLOT_DNA_PATTERNS = {
    "规则怪谈无限流": {
        "副本降临": re.compile(r'副本.*降临|强制.*(?:拉入|进入).*副本|突然.*传送'),
        "隐藏区域": re.compile(r'隐藏.*(?:区域|关卡|房间|通道)|误入.*(?:隐藏|禁区)'),
        "规则畸变": re.compile(r'规则.*(?:畸变|改变|变化|修改|崩坏)|异常.*规则'),
        "理智值": re.compile(r'理智值|SAN值|精神值|理智.*(?:下降|降低|消耗)'),
        "副本BOSS": re.compile(r'副本.*BOSS|BOSS.*(?:递出|提议|合作|招揽)'),
        "通关方案": re.compile(r'(?:推演|制定|完美).*通关|(?:通关|清关).*方案'),
    },
    "克苏鲁诡秘调查": {
        "诡异委托": re.compile(r'诡异.*委托|奇怪.*委托|神秘.*委托|雨夜.*委托'),
        "旧日遗物": re.compile(r'旧日.*遗物|远古.*(?:雕像|遗物|法器)|禁忌.*典籍'),
        "邪教": re.compile(r'邪教|邪教徒|召唤.*古神|阻止.*召唤'),
        "SAN值": re.compile(r'SAN值|san值|理智.*(?:下降|降低|检定)|精神.*污染'),
        "眷族": re.compile(r'眷族|眷属|外神|古神.*(?:降临|苏醒|意志)'),
        "调查员": re.compile(r'调查员|神秘学|占卜|炼金术|咒文'),
    },
    "星际拓荒种田流": {
        "星舰失事": re.compile(r'星舰.*(?:失事|坠落|迫降)|飞船.*(?:坠毁|故障|残骸)'),
        "异星土著": re.compile(r'异星.*土著|土著.*(?:部落|族人)|原住民'),
        "生态适应": re.compile(r'生态.*(?:适应|极限|濒临)|环境.*(?:适应|极限|恶化)'),
        "星际海盗": re.compile(r'星际.*海盗|海盗.*(?:袭击|劫掠|抢夺)'),
        "能源矿": re.compile(r'能源.*矿|稀有.*矿|能源.*(?:发现|开采|触发)'),
        "基地": re.compile(r'基地.*(?:护盾|建设|升级|扩建|防御)'),
    },
    "古代市井悬疑流": {
        "仵作": re.compile(r'仵作|验尸|勘验|尸检'),
        "镖局": re.compile(r'镖局|押镖|走镖|劫镖'),
        "漕帮": re.compile(r'漕帮|漕运|码头|帮派'),
        "市井": re.compile(r'市井|街市|茶馆|酒楼|勾栏|瓦肆'),
        "案件": re.compile(r'案件|命案|凶杀|悬案|疑案|冤案'),
        "推理": re.compile(r'推理|线索|证据|真相|破案|结案'),
    },
}


def detect_meta_patterns(text: str) -> list[dict]:
    """检测文本中出现的叙事元模式。

    Args:
        text: 章节文本

    Returns:
        [{"pattern": "threshold_break", "name": "阈值突破", "matches": [...], "count": 3}, ...]
    """
    results = []
    for key, meta in META_PATTERNS.items():
        matches = meta["pattern"].findall(text)
        if matches:
            results.append({
                "pattern": key,
                "name": meta["name"],
                "description": meta["description"],
                "count": len(matches),
                "examples": matches[:3],  # 前3个匹配示例
            })
    return results


def detect_genre_plots(text: str, genre: str = "") -> list[dict]:
    """检测文本中出现的题材specific情节模式。

    Args:
        text: 章节文本
        genre: 题材标签 (如 "规则怪谈无限流"), 空字符串则检测所有题材

    Returns:
        [{"genre": "克苏鲁诡秘调查", "plot": "邪教", "count": 2, "examples": [...]}, ...]
    """
    results = []
    genres_to_check = [genre] if genre else list(PLOT_DNA_PATTERNS.keys())
    for g in genres_to_check:
        plots = PLOT_DNA_PATTERNS.get(g, {})
        for plot_name, pattern in plots.items():
            matches = pattern.findall(text)
            if matches:
                results.append({
                    "genre": g,
                    "plot": plot_name,
                    "count": len(matches),
                    "examples": matches[:2],
                })
    return results
