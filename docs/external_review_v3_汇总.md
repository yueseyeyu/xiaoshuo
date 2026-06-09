# 外部AI审视汇总 v3 — 番茄小说 v7.3 全管线

> 来源: 两位独立评审 (DS + Kimi) · 日期: 2026-06-07
> 覆盖: 6模块 26个审视问题

---

## 双方完全一致的 P0（3项，立即修）

| # | 事项 | 评审A | 评审B |
|---|------|:---:|:---:|
| 1 | **LLM端点兼容性** — `/completion`→`/v1/chat/completions` OpenAI兼容 | P0 | P0 |
| 2 | **代理评分公式校准** — `avg_pleasure*10+avg_hook*20` 无理论依据 | P0 | P0 |
| 3 | **LLM校准结果消费** — llm_labeler的F1必须流入genre_synthesizer | P0 | P0 |

## 双方接近一致的 P1（8项，本轮修）

| # | 事项 |
|---|------|
| 4 | 引入 UNVERIFIED 状态 + book_id 统一体系 |
| 5 | Bootstrap百分位CI + 子类型权重收缩 |
| 6 | POOL排除QUARANTINE书 + 章节正则分层检测 |
| 7 | zero_hook_streak 按篇幅分桶 + QUARANTINE→30天 |
| 8 | %分桶改为功能分段/篇幅分桶 |
| 9 | LLM两阶段标注 + 章节文本复用rhythm分割 |
| 10 | 反馈回路5-8核心维追踪 |
| 11 | patterns.py 抽取 + 主入口pipeline脚本 + 增量分析 |

---

## 双方审结对系统的总体评价

> DS: "v3 已具备工业化雏形，P0 缺陷是上线前必须清除的障碍。尤其 book_id 统一化和代理评分的统计安全是数据诚信的基石。"

> Kimi: "v3 是从'可信'向'可用'演进。llm_labeler 校准结果必须立即消费到下游，这是 v3 最关键的待办项。工程基础设施（patterns.py + pipeline + 增量分析）是模块膨胀下的生存必需。"
