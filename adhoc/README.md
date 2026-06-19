# adhoc/ — 一次性脚本归档区

本目录存放**一次性运行过的脚本**，保留用于历史追溯，但不再是活跃代码路径。

## 归档原则
- 已被管线取代的 Phase A/B1 报告生成脚本
- 已废弃的旧版本（如 `calibrate_rules.py` 被 `calibrate_v2.py` 取代）
- 一次性数据迁移/编码转换脚本

## 当前归档清单（阶段 B 将填入）
| 文件 | 原位置 | 归档原因 |
|------|--------|----------|
| `generate_final_report.py` | `analysis/` | Phase 一次性脚本，已被管线 creative_bridge 取代 |
| `generate_quality_report.py` | `analysis/` | Phase A 一次性数据质量报告 |
| `generate_writer_guidance.py` | `analysis/` | Phase B1 一次性作家指导方案 |
| `calibrate_rules.py` | `analysis/` | 已废弃 (v7.3)，被 calibrate_v2 取代 |
| `add_books.py` | `scripts/` | 一次性硬编码入库脚本 |
| `reorganize_dirs.py` | `scripts/` | 一次性目录重构（已执行） |
| `check_encoding.py` | `scripts/` | 功能与 fix_encoding 重叠 |
| `convert_encoding.py` | `scripts/` | 功能与 fix_encoding 重叠 |
| `fix_encoding.py` | `scripts/` | 一次性编码转换 |

> 注意: 这些脚本中的 import 路径仍指向旧位置 (analysis/ scripts/)，
> 单独运行可能失败。仅作历史参考。
