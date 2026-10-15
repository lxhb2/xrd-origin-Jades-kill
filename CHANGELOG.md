# Changelog

本项目采用语义化版本号，Git 标签格式为 `v主版本.次版本.修订号`。

## [1.2.2] - 2026-10-15

首个公开打包版本。

### 包含

- `jade_phaseid.py v2.2.0`：驱动 Jade 6.5 完成寻峰、元素/化学式筛选、Search/Match、候选结果和 PDF 卡片导出。
- `xrd_stack.py v1.2.2`：解析样品谱和 Jade 卡片，默认生成上方 XRD、下方分层 PDF 卡片棒状图，并导出 Origin 数据表。
- 单谱 `markers` 符号标峰和 `hkl` 晶面指数标峰。
- 启用单谱标峰时自动隐藏 PDF 卡片棒状图和卡片标签；多样品堆叠图仍保留底部卡片层。
- 卡片标签优先读取 Jade 文件的 `# formula:`，显示化学式并放在图框外。
- `origin_stack.py v1.2.2`：生成可编辑 Origin `OPJU`、PNG 和 PDF。
- Jade、Origin、数据物理、质检和来源参考文档，以及合成数据示例图。
