# 资料出处

本 skill 的流程来自本机既有的操作笔记，并经过交叉核对与实操验证。写具体步骤时以用户的软件版本为准，不要把这里的版本用词当普适真理。

## 主来源（用户提供）

- 本地笔记《Jade6.5 + Origin 绘制 XRD-PDF 堆叠图的使用》，含 16 张操作截图。原始笔记未随本仓库发布，使用时应放在用户自己的资料目录中。
- 该笔记自称整理自抖音视频《Origin 绘制标准的 XRD-PDF 堆叠图》（视频 ID 7467817878885076259）与今日头条同作者图文版，并补充了 Jade 6.5 导出卡片流程。
- 笔记里提到的华算科技《XRD 数据处理-Jade 分析、Origin 堆积图、PDF 卡片导出与插入》、科学指南针《XRD 数据分析——如何使用 Origin 作图》未直接核到原文。

## 交叉核对过的资料

- 科学指南针（shiyanjia.com）《采用 Jade 软件进行 XRD 数据处理、检索分析及 Origin 作图详细步骤》：核对到无条件检索、
  Search/Match Display、FOM 排序、Chemistry filter 限定元素、单峰检索（Painted Peaks）、Kα2 剥离与扣背景、Scherrer 估算晶粒尺寸等描述，与本 skill 的 Jade 步骤一致。
- ICDD 北京代表处（icddchina.com）JADE 页面：确认 JADE 由 Materials Data (MDI) 开发，自动拟背景、寻峰、鉴定物相并标定品质因数 FOM。
- Materials Data（materialsdata.com）JADE 产品页：确认全谱拟合/Rietveld、模拟与可视化等功能；注：JADE 9+ 是重写版，与经典 Jade 6.5 菜单不同。
- 知乎《小心错误引用 PDF 卡片被拒稿》：支撑“卡片号规范为 ICDD No. XX-XXX-XXXX（三组）”与旧两组号已变更的说法。

## 本机验证

- Origin 2025b 已安装，COM 类 `Origin.Application` 已注册。
- `scripts/jade_phaseid.py` v2.2.0 已在本机 Jade 6.5 上实测：元素 `Si,Fe,Cu,S`、目标 `Si + FeS2 + CuFeS2`、`possible` 模式完成 Find Peaks、化学筛选、Search/Match，并导出候选表；候选包含 `Si 75-0589`、`FeS2 71-1680`、`CuFeS2 75-0253`，未出现未选元素 Cr。
- 自动化卡片导出实测完成：`75-0589`、`71-1680`、`75-0253` 均成功保存为 d-I 峰表。期间修复了 Jade 结果列表“显示矩形与点击坐标相差一行”导致的错开上一张卡片问题。
- `scripts/xrd_stack.py` v1.2.2 用真实 Jade 卡片做过回归：`d(A)` 表头即使 hkl 被拆成三列，也能正确识别为 d 值而不是把强度列当 2θ；`d→2θ` 换算正常。默认版式已验证为“上方 XRD、下方卡片分层”，卡片标签读取 `# formula:` 放在图框外；单谱 `markers` 符号标峰和 `hkl` 晶面指数标峰均已实际出图验证，启用标峰时下方卡片棒状图会隐藏。
- `scripts/origin_stack.py` v1.2.2 已在本机生成可编辑 `OPJU + PNG + PDF`。卡片峰用折线“分段连接”画成独立竖线，并在下方按卡片逐层绘制水平基线；本轮化学式标签与标峰版式已通过语法与数据表回归，实际 Origin 重新导出前需先关闭已有工程或使用新的 Origin 实例。
- 本机 Origin 当前输出带重复 `demo` 水印，说明运行环境处于未激活/演示状态；该水印不是 skill 或脚本生成的数据标签。正式使用前需在 Origin 中完成本机许可激活。
- 中文菜单用词直接取自安装目录的语言资源，未凭印象编写：
  - `Localization\C\MainMenuText.txt`：绘图类型列表中的「Y 偏移堆积线图」；图菜单中的「图层中组数据偏移模式」；
  - `Localization\C\SearchPDD.json`：绘图细节的「堆叠 / 偏移」选项集「无、累积、常量、自动、单独、增量」与「间距(%)」，以及「垂直线 / 平行于 Y 轴」等控件路径；
  - 模板文件 `OffsetStackY.otpu`（Y 偏移堆积线）。
- `scripts/xrd_stack.py` 也已用合成数据跑通完整流程（出图 + 卡片解析 + Origin 数据表），示例图见 `assets/xrd-stack-example.png` 与 `assets/xrd-single-example.png`。

## 未验证/慎用

- 抖音视频原文与今日头条图文未在本次编写中直接打开，引用时以本地笔记为准。
- 各 X 射线波长是通用参考值，写论文时必须用测试报告上的值。
- Jade 各版本（6.5 / 9.x）界面差异较大；只有版本相关的菜单名在未知版本上不要硬套，直接请用户确认界面。
