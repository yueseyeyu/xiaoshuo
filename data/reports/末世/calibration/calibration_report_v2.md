# 规则校准报告 v2 (100章全特征)
> 样本: 100 chapters | r(rule vs LLM) = 0.123
> 校准公式: LLM = 0.106 × Rule + 2.8

## 特征重要性 (Pearson r vs LLM 爽点强度)
| 特征 | r_intensity | r_conflict | r_bond | 保留 |
|------|:---:|:---:|:---:|:---:|
| pos_density | 0.445 | 0.327 | 0.095 | ✅ |
| conflict_density | 0.406 | 0.348 | -0.1 | ✅ |
| crush_count | 0.3 | 0.338 | -0.068 | ✅ |
| neg_density | 0.241 | 0.443 | 0.13 | ✅ |
| physio_count | 0.179 | 0.221 | 0.285 | ✅ |
| comeback_count | 0.178 | 0.082 | -0.119 | ✅ |
| bond_count | 0.155 | 0.212 | 0.08 | ✅ |
| rule_intensity | 0.123 | 0.087 | 0.189 | ✅ |
| excl_density | 0.108 | 0.069 | 0.188 | ✅ |
| hook_density | 0.096 | 0.135 | -0.015 | ✅ |
| slap_count | 0.096 | 0.109 | 0.048 | ✅ |
| dialogue_ratio | -0.091 | -0.105 | 0.177 | ✅ |
| level_count | 0.086 | 0.053 | -0.081 | ❌ 剔除 |
| sacrifice_count | 0.053 | 0.024 | -0.13 | ❌ 剔除 |
| cognitive_count | 0.017 | 0.072 | 0.037 | ❌ 剔除 |

## 子类型偏置
| 子类型 | 偏置 | 样本数 |
|------|:---:|:---:|
| bond | -0.29 | 48 |
| general | -1.31 | 38 |
| slap | -3.54 | 5 |
| smart | -0.69 | 9 |

---
*calibrate_v2.py · Platt Scaling + per-feature r*