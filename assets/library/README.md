# 题材库 (Genre Library)

## 结构

```
library/
├── index.json              # 总索引: genre → world → reference 三向映射
├── genres/                 # 题材组合文件
│   └── {题材名}.md         # 每个题材组合一个文件
├── references/             # 参考小说分析
│   └── {书名}.md           # 已分析小说的节奏数据和可借鉴要素
└── README.md
```

## 使用方式

1. **新增题材组合**: 在 `genres/` 创建 `{题材名}.md`, 填写融合方案
2. **链接世界观**: 编辑 `index.json`, 将该题材的 `world` 指向 `canon/` 目录下的设定文件
3. **关联参考小说**: 在 `index.json` 的 `references` 数组中添加已有分析的小说
4. **S0 构建**: `novel.py worldbuild` 会自动读取当前题材文件并注入 System Prompt

## 当前状态

| 题材 | 状态 | 世界观 |
|------|:---:|------|
| 灵气复苏×洪荒 | 构思中 | — |
