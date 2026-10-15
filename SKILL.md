---
name: xrd-origin-jade
description: 处理粉末 XRD 的物相鉴定与配图：用 Jade 6.5 检索并导出 PDF 标准卡片、判断物相归属是否站得住，再在 Origin 里画 Y 偏移堆积图并叠加卡片峰位竖线，或用随附脚本一键生成堆叠图与 Origin 可导入数据表。适用于 XRD 堆叠图/堆积图、PDF 卡片（JCPDS/ICDD）比对、标准卡片竖线、物相鉴定、图谱归一化与投稿配图等请求。不用于单晶结构解析、Rietveld 精修本身、未经检索就替用户认定物相，或非衍射类表征图。
metadata:
  short-description: XRD 物相鉴定与 Origin 堆叠图
---

# XRD 堆叠图 + Jade PDF 卡片

处理"多条 XRD 曲线沿 Y 偏移堆叠、下面配标准卡片竖线"这一类科研出图与物相鉴定任务。

## 先判断用户要哪件事

一次请求里可能同时包含多件，按顺序处理：

1. **要图**：已有谱图数据（和/或卡片数据）→ 走「出图」路线。
2. **要物相鉴定**：还没确定是什么相 → 先走「检索」路线，再出图。
3. **要在 Origin 里自己画一遍**：用户是来学操作的 → 给操作步骤卡，不要只丢脚本。

### 出图路线

优先用脚本出图并同时导出 Origin 数据表，再用文字告诉用户 Origin 里怎么改：

```text
python scripts/xrd_stack.py --sample "未处理=raw/s1.txt" --sample "5% MnO=raw/s2.txt" --card "beta-PbO2=jade/pbo2.txt" --out ./figs/xrd --radiation CuKa1 --dpi 600
```

- 先跑 `--demo` 自检环境是否可用；`--cards-only` 只解析卡片、不出图（不需要 matplotlib）。
- 脚本只做「读取 → 归一化 → 排版」，不扣背景、不平滑、不检索物相，并把 λ、归一化方式、每条曲线的偏移量、卡片三强峰写进 `manifest.json`。
- 缺 matplotlib 时脚本会给出安装命令并仍然导出数据表，不要因此宣称图形已完成。
- 默认排版：XRD 谱线放在上方；PDF 卡片统一放在最下方，每张卡片占一行、带独立基线和颜色。卡片标签优先读取 Jade 文件里的 `# formula:`，显示化学式（如 `FeS2`、`CuFeS2`），并放在图框外侧的独立标签区，不压棒状图。单条谱自动收紧线宽并在右上放卡片图例；多条谱在右侧标样品名。单谱启用任何标峰模式后，不再绘制下方 PDF 卡片棒状图，避免同一物相在一张图里重复表达。
- 出图后必须做视觉检查：卡片竖线是否与样品谱共用同一 2θ 标尺、卡片行有没有互相遮挡、中文字体是否正常。排版参照见 `assets/xrd-stack-example.png` 与 `assets/xrd-single-example.png`（合成数据，不是真实样品）。
- 命令里的 `scripts/xrd_stack.py` 指本 skill 目录下的路径，执行时用绝对路径（Windows 上注意中文路径要加引号）。
- 详细参数、Origin 列结构、排版规则见 [references/data-and-physics.md](references/data-and-physics.md) 与 [references/origin-stacking.md](references/origin-stacking.md)。

### 单谱标峰（两种）

两种模式只对**单条 XRD 谱**启用；多样品堆叠图会自动忽略并给出 warning。

```text
# 1. 图形符号：圆、三角、方块等分别对应不同 PDF 卡片
python scripts/xrd_stack.py --sample "样品=raw/s1.txt" ^
  --card "Si=jade/Si.txt" --card "FeS2=jade/FeS2.txt" ^
  --out ./figs/single --peak-marking markers --marker-min-intensity 5

# 2. 晶面指数：在匹配到的实测峰上标 (111)、(200)、(220) 等
python scripts/xrd_stack.py --sample "样品=raw/s1.txt" ^
  --card "FeS2=jade/FeS2.txt" ^
  --out ./figs/single_hkl --peak-marking hkl --hkl-card 1 --hkl-min-intensity 15
```

- `markers`：不同卡片使用不同符号和颜色，并在图例中显示 `化学式 + PDF#号`。
- `hkl`：`--hkl-card 1` 表示使用第 1 张 `--card` 的 hkl；只给单个主物相使用，避免多个物相的晶面指数混在一起。
- 任一标峰模式启用时，下方 PDF 卡片棒状图和卡片右侧标签都会隐藏，只保留实测谱与标峰；卡片数据仍会写入 `origin/` 目录，便于后续需要时恢复。多样品堆叠图不使用单谱标峰，因此仍保留底部卡片棒状图。
- `--peak-tolerance` 控制卡片峰与实测局部峰的匹配容差；默认 `0.35°`。脚本只做位置匹配和排版，不替用户判断物相。
- 标峰记录写入 `peak_annotations.csv`，便于回到原始峰位复核。示例见 `assets/xrd-peak-markers-example.png` 与 `assets/xrd-hkl-labels-example.png`。

### 检索路线（Jade）

**检索前必须先取得目标元素和化学式，不许先猜物相。** 用户没给时，先问样品信息或研究方向；仍没有时，再查论文和公开信息，归纳该方向的常规元素/化学式，得到用户确认后再检索。

本机 Jade 6.5 可通过 `scripts/jade_phaseid.py` 驱动图形界面完成寻峰、化学筛选、Search/Match 和 PDF 卡片导出：

```text
python scripts/jade_phaseid.py search --out ./jade_out --elements "Si,Fe,Cu,S" --formula "Si + FeS2 + CuFeS2" --filter-mode possible
```

- `--filter-mode possible`：混相默认。每个候选相只需含至少一个目标元素，适合 Si + FeS2 + CuFeS2 这类多个独立物相。
- `--filter-mode required`：候选相必须含全部目标元素，只适合单相或所有物相都共享同一元素集的情况。
- 脚本默认执行 Find Peaks；若用户已人工确认峰位并要复用，才加 `--reuse-peaks`。
- 找到目标卡片后，可重复使用 `--export-card 75-0589 --export-card 71-1680` 导出干净 d-I 峰表。
- 输出是候选表和峰表，不是自动认定的物相。必须用三强峰、弱峰、元素约束、合成条件和文献继续判断。

流程、判据与常见坑见 [references/jade-phase-id.md](references/jade-phase-id.md)。如果本机另存有原始操作笔记和截图，可结合用户自己的资料核对这些步骤，但不要假设其他使用者拥有相同路径。

### Origin 自动与手工路线

先运行 `scripts/xrd_stack.py` 生成成图和 Origin 数据表，再用 `scripts/origin_stack.py` 读取 `origin/Sheet1_samples.csv` 与 `origin/Sheet2_cards.csv`，输出可编辑 `OPJU + PNG + PDF`。Origin 脚本默认沿用 manifest 中的卡片行高，并把每张卡片做成下方分层棒状图：

```text
python scripts/origin_stack.py --origin-dir ./figs/xrd/origin --out ./figs/xrd_origin --x-range 10 80
```

Origin 自动脚本运行前先保存并关闭 Origin；若确定要复用现有进程，显式加 `--allow-existing`。菜单路径与故障排查见 [references/origin-stacking.md](references/origin-stacking.md)。
若 Origin 未激活，自动图可能出现重复 `demo` 水印；这是许可证状态，不是脚本生成的数据标签。

## 科学底线

- **不臆造卡片号、峰位和物相**。PDF 卡片号（如 `PDF#00-041-1442`）只能来自用户提供的检索结果或用户确认的文件；脚本不会生成卡片号，也不要在报告里补上你没见过的编号。
- **物相归属是用户的科学判断**。给出证据（三强峰吻合度、元素约束、文献旁证）和不确定性，不要用"确认是 β-PbO₂"这类措辞替用户下结论。
- **竖线不是定量证据**。卡片竖线只说明"标准峰位在哪里"；半定量需要 RIR 或全谱拟合，别把峰高比当成相含量。
- **凡改动数据都要说**。归一化、平滑、扣背景、Kα2 剥离都是数据处理，必须在图注或实验部分留痕；脚本默认只做逐条归一化。
- **λ 以仪器/测试报告为准**。d 值换算 2θ 时用错波长会整体错峰；所有换算都要把 λ 记进 manifest 并告诉用户。
- **尊重数据库版权**。ICDD PDF 卡片数据来自授权数据库，不要把整段卡片数据或数据库文件随图外发。

## 常见输入形态

| 输入 | 说明 |
| --- | --- |
| 仪器导出的谱图 | 两列数值（2θ、强度），TXT/CSV/ASC；中文系统导出常为 GBK，脚本会自动识别 |
| Origin 式多列数据 | 每个样品两列（A/B=样品 1，C/D=样品 2）；脚本用 `--sample-cols` 指定列号 |
| Jade 导出的卡片 TXT | 可能是 d–I 列表（3–4 列，含 hkl）或 2θ–I 列表；脚本自动判断，必要时用 `--card-cols`/`--card-kind` |
| 用户口述的峰位 | 先请用户给原始文件；只有峰位表时，可写成两列文本再用 `--card` 传入 |

卡片数与样品数不一致时脚本会把卡片统一排在底部，这是正常行为，不是错误。

## 汇报方式

出图后按这个顺序汇报，不要贴 JSON：

1. 认到的数据：几个样品、各多少点、2θ 范围；几张卡片、按 d 还是 2θ 解析、三强峰位置。
2. 图形与数据表路径（PNG/PDF/SVG、`origin/` 目录、`manifest.json`）。
3. 用到的 λ 和做过的处理（归一化方式等），以及任何 warning。
4. 还需要用户确认的一两件事（例如卡片是否来自授权数据库、样品名与卡片对应关系）。

## 按需读取

- [references/jade-phase-id.md](references/jade-phase-id.md)：Jade 6.5 检索、判据、导出卡片的完整操作与坑。
- [references/origin-stacking.md](references/origin-stacking.md)：Origin 三种画法、2025b 中文菜单路径、故障排查。
- [references/data-and-physics.md](references/data-and-physics.md)：Bragg 换算、波长、归一化、脚本全部参数。
- [references/qa-checklist.md](references/qa-checklist.md)：出图前与投稿前的检查清单。
- [references/sources.md](references/sources.md)：本 skill 的资料出处与可信度说明。
