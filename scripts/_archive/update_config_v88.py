"""v8.8: 更新config.yaml质量分级 + known_quality_list + known_genre_map"""
import re

config_path = "config.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    content = f.read()

# === 1. 替换 quality_tiers 整块 ===
old_tiers = """    # v8.7修订依据: DeepSeek(8.5/10) + Kimi(8.0/10) + Doubao(7.5/10) 三方共识
    #   - 末世魔神游戏 S→A: hook3=1.10 S级最低, zero_hook_10=2 (三方全票)
    #   - 黑暗血时代 B→A: 商业72=A, hook3=2.46第4 (DeepSeek+Kimi)
    #   - 全球进化 A→B+: hook3=0.99, zero_hook_10=2, 商业60 (三方全票)
    #   - 蹉跎 B→C: 商业评分46=D级 (三方全票)
    #   - 黑暗末日 B→C: 商业评分43=D级 (三方全票)
    #   - B级细分B+/B/B-: 16本跨度太大 (三方全票)
    quality_tiers:
      S:                         # 绝世神作, 白金代表 — 权重1.0, 正例核心
        weight: 1.0
        description: "多维度顶尖, AI学习的核心标杆"
        books:
          - "地球游戏场"              # borda#1, signing#1, diversity#3, 独立排名#2
          - "末世之深渊召唤师"        # borda#2, retention#2, conflict3=1.04(最高)
          - "末世大回炉"              # borda#3, pleasure_all=5.53(最高), 独立排名#1
          - "异兽迷城"                # borda#4, bt#6, 各维度均衡, 无明显短板
          - "神秘尽头"                # borda#6, hook3=4.12(远超第二), retention#1
          # 注: 神秘尽头仅292章, hook3可能因短篇效应高估, 待数据积累后复评
      A:                         # 质量上乘佳作 — 权重0.7, 正例补充
        weight: 0.7
        description: "优秀作品, 补充学习多样性"
        books:
          - "我的末世领地"            # borda#7, pleasure3=5.40(最高!)
          - "从红月开始"              # borda#8, bt#2, webnovel8#2, hook3=2.88
          - "世界末日从考试不及格开始"  # borda#9, bt#1, webnovel8#1, 外部#1
          - "末世魔神游戏"            # v8.7: S→A降级, hook3=1.10偏低, zero_hook_10=2
          - "末世召唤狂潮"            # borda#11, conflict3=0.88
          - "末日拼图游戏"            # borda#12, hook3=2.21, conflict3=0.94
          - "废土崛起"                # borda#13, bt#5, pleasure3=2.87
          - "全球变异"                # borda#14, hook3=2.49(第3)
          - "黑暗血时代"              # v8.7: B→A升级, 商业72=A, hook3=2.46(第4)
      B_plus:                    # B+ 良好偏上 — 权重0.4
        weight: 0.4
        description: "中上质量, 有亮点但存在短板"
        books:
          - "狩魔手记"                # borda#15, 文学性强, 商业67, bt#27偏低
          - "全球进化"                # v8.7: A→B+降级, hook3=0.99, zero_hook_10=2
          - "我在末世有套房"          # borda#17
          - "黑暗文明"                # borda#18, diversity#1
          - "恐慌沸腾"                # borda#19, bt#7
      B:                          # B 良好, 书荒仙草 — 权重0.3
        weight: 0.3
        description: "中等质量, 提供题材多样性覆盖"
        books:
          - "我的女友是丧尸"          # borda#20
          - "灾厄纪元"                # borda#21
          - "黑暗王者"                # borda#22
          - "重卡战车在末世"          # borda#23
          - "末日蟑螂"                # borda#24, 经典但节奏偏弱(hook3=0.31)
      B_minus:                    # B- 中等偏下 — 权重0.2
        weight: 0.2
        description: "中下质量, 节奏/商业有明显弱项"
        books:
          - "第九特区"                # borda#25
          - "末世超级商人"            # borda#26, 各项指标偏低
          - "我在末世种个田"          # borda#28
          - "限制级末日症候"          # borda#29
      C:                         # 反例/反面教材 — 权重0.0, 不进入正样本池
        weight: 0.0
        description: "反面教材, 用于反模式提取(contrastive rejected)"
        books:
          - "末世之三宫六院"          # 用户确认垃圾书 (无节奏数据)
          - "末世精灵皇"              # 用户确认垃圾书 (无节奏数据)
          - "蹉跎"                    # v8.7: B→C降级, 商业评分46=D, 有节奏数据
          - "黑暗末日"                # v8.7: B→C降级, 商业评分43=D, borda#30, 有节奏数据"""

new_tiers = """    # v8.8修订依据: 三方AI(DeepSeek+Kimi+Doubao)审视 + 用户确认过滤"鼻祖效应"
    #   v8.7→v8.8变更:
    #   - 黑暗血时代 A→S: 三方全票, 文字质量够S (非靠鼻祖标签)
    #   - 末世之深渊召唤师 S→A: 三方全票, 外部零验证, 原S级靠signing循环论证
    #   - 神秘尽头 S→A: 三方全票, 仅292章短篇效应高估hook3
    #   - 狩魔手记 B+→A: 豆瓣8.1, 文学性强, 多平台一致
    #   - 第九特区 B-→B: 三方建议升级但仅升一级, 连升到A过于激进
    #   - 第一序列(新增S): 289万字完结, 十万均订, 中国图书馆典藏, 文字+商业双顶级
    #   - 长夜余火(新增S): 281万字完结, 白金大神乌贼, 文学深度+废土公路片
    #   - 末日蟑螂维持B: 过滤"鼻祖效应", hook3=0.31节奏极弱, 不因历史地位升级
    #   - 蹉跎维持C: 过滤"鼻祖效应", 商业46=D级, 2002年作品对AI无学习价值
    #   核心原则: 文字质量优先, "鼻祖"/"经典"标签不自动=高质量
    quality_tiers:
      S:                         # 绝世神作, 白金代表 — 权重1.0, 正例核心
        weight: 1.0
        description: "多维度顶尖, AI学习的核心标杆"
        books:
          - "地球游戏场"              # borda#1, signing#1, diversity#3, 独立排名#2
          - "末世大回炉"              # borda#3, pleasure_all=5.53(最高), 独立排名#1
          - "异兽迷城"                # borda#4, bt#6, 各维度均衡, 无明显短板
          - "黑暗血时代"              # v8.8: A→S升级, 三方全票, 商业72+A, hook3=2.46(第4)
          - "第一序列"                # v8.8新增, 289万字完结, 十万均订, 中国图书馆典藏
          - "长夜余火"                # v8.8新增, 281万字完结, 白金大神乌贼, 文学深度+废土
      A:                         # 质量上乘佳作 — 权重0.7, 正例补充
        weight: 0.7
        description: "优秀作品, 补充学习多样性"
        books:
          - "我的末世领地"            # borda#7, pleasure3=5.40(最高!)
          - "从红月开始"              # borda#8, bt#2, webnovel8#2, hook3=2.88
          - "世界末日从考试不及格开始"  # borda#9, bt#1, webnovel8#1, 外部#1
          - "末世魔神游戏"            # v8.7: S→A降级, hook3=1.10偏低, zero_hook_10=2
          - "末世召唤狂潮"            # borda#11, conflict3=0.88
          - "末日拼图游戏"            # borda#12, hook3=2.21, conflict3=0.94
          - "废土崛起"                # borda#13, bt#5, pleasure3=2.87
          - "全球变异"                # borda#14, hook3=2.49(第3)
          - "末世之深渊召唤师"        # v8.8: S→A降级, 外部零验证, signing循环论证
          - "神秘尽头"                # v8.8: S→A降级, 仅292章短篇效应高估hook3
          - "狩魔手记"                # v8.8: B+→A升级, 豆瓣8.1, 文学性强, 多平台一致
      B_plus:                    # B+ 良好偏上 — 权重0.4
        weight: 0.4
        description: "中上质量, 有亮点但存在短板"
        books:
          - "全球进化"                # v8.7: A→B+降级, hook3=0.99, zero_hook_10=2
          - "我在末世有套房"          # borda#17
          - "黑暗文明"                # borda#18, diversity#1
          - "恐慌沸腾"                # borda#19, bt#7
      B:                          # B 良好, 书荒仙草 — 权重0.3
        weight: 0.3
        description: "中等质量, 提供题材多样性覆盖"
        books:
          - "我的女友是丧尸"          # borda#20
          - "灾厄纪元"                # borda#21
          - "黑暗王者"                # borda#22
          - "重卡战车在末世"          # borda#23
          - "末日蟑螂"                # borda#24, 过滤鼻祖效应维持B, hook3=0.31极弱
          - "第九特区"                # v8.8: B-→B升级, 仅升一级不过激
      B_minus:                    # B- 中等偏下 — 权重0.2
        weight: 0.2
        description: "中下质量, 节奏/商业有明显弱项"
        books:
          - "末世超级商人"            # borda#26, 各项指标偏低
          - "我在末世种个田"          # borda#28
          - "限制级末日症候"          # borda#29
      C:                         # 反例/反面教材 — 权重0.0, 不进入正样本池
        weight: 0.0
        description: "反面教材, 用于反模式提取(contrastive rejected)"
        books:
          - "末世之三宫六院"          # 用户确认垃圾书 (无节奏数据)
          - "末世精灵皇"              # 用户确认垃圾书 (无节奏数据)
          - "蹉跎"                    # v8.7: B→C降级, 商业评分46=D, 过滤鼻祖效应维持C
          - "黑暗末日"                # v8.7: B→C降级, 商业评分43=D, borda#30, 有节奏数据"""

assert old_tiers in content, "old_tiers block not found!"
content = content.replace(old_tiers, new_tiers)

# === 2. 添加新书到 known_quality_list ===
old_known = '''      - "我的末世领地"
      - "蹉跎"'''
new_known = '''      - "我的末世领地"
      - "蹉跎"
      - "第一序列"
      - "长夜余火"'''
assert old_known in content, "known_quality_list block not found!"
content = content.replace(old_known, new_known, 1)

# === 3. 添加新书到 known_genre_map ===
old_genre = '''      "蹉跎": "末世"
      "黑暗末日": "末世"'''
new_genre = '''      "蹉跎": "末世"
      "黑暗末日": "末世"
      "第一序列": "末世"
      "长夜余火": "末世"'''
assert old_genre in content, "known_genre_map block not found!"
content = content.replace(old_genre, new_genre, 1)

with open(config_path, "w", encoding="utf-8") as f:
    f.write(content)

print("config.yaml updated to v8.8 successfully!")
print("  S级: 6本 (地球游戏场,末世大回炉,异兽迷城,黑暗血时代↑,第一序列+,长夜余火+)")
print("  A级: 11本 (+末世之深渊召唤师↓,+神秘尽头↓,+狩魔手记↑,-黑暗血时代↑)")
print("  B+级: 4本 (-狩魔手记↑)")
print("  B级: 6本 (+第九特区↑)")
print("  B-级: 3本 (-第九特区↑)")
print("  C级: 4本 (不变)")
