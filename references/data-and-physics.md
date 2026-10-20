# 数据、物理与脚本参数

## 一、Bragg 换算

Bragg 定律 `nλ = 2d sinθ`，XRD 常规取一级衍射 n=1：

```
 d = λ / (2 sinθ)           # Å
 2θ = 2 · arcsin(λ / (2d))  # 度
```

- λ 用 **Å**，d 也用 **Å**，角度与弧度不要混。
- 例（Cu Kα1，λ = 1.54056 Å）：d = 3.1401 Å → 2θ = 28.400°；d = 3.1200 Å → 2θ = 28.586°。
- 卡片如果只给 d 值，换算时用错 λ 会让整排竖线错峰；脚本会把 λ 写进 `manifest.json`。

## 二、常用波长

| 预设 | λ (Å) | 说明 |
| --- | --- | --- |
| `CuKa1` | 1.54056 | 铜靶 Kα1，最常用（默认） |
| `CuKa` | 1.5418 | 铜靶 Kα1+Kα2 加权平均，未做 Kα2 剥离时更接近实际 |
| `CoKa1` | 1.78897 | 钴靶 |
| `MoKa1` | 0.70930 | 钼靶 |
| `CrKa1` | 2.28970 | 铬靶 |
| `FeKa1` | 1.93604 | 铁靶 |

以上是通用参考值，**以测试报告/仪器设置为准**。铜靶报告上常见 1.5406、1.54056、1.5418 三种写法，差别来自是否剥离 Kα2，不确定时问用户。

## 三、归一化与偏移

- **归一化**：每条曲线除以自身最强峰。`max1`（默认）把最高点缩放到 1，便于统一定间距；`max100` 缩放到 100，常见于卡片相对强度；`none` 保留原始计数。
- 归一化只改变视觉效果，不改变峰位与相对强度关系，但图注应注明“归一化”或纵轴标 `Intensity (a.u.)`。
- **显示平滑**：默认 `savgol`，11 点、3 阶 Savitzky–Golay，用于压掉过小的噪声起伏；可用 `--smooth none` 关闭。平滑先于归一化执行，只影响成图，不修改 `origin/` 中的强度表。不要把平滑后的弱峰当成新增或确认物相。
- **偏移**：脚本按等间距把曲线依次抬高，间距 `gap` 是相对谱线高度（归一化后 1）的倍数。
- **卡片排版**：默认 `--card-position bottom`，所有 PDF 卡片统一排在下方，每张卡片占一行，带独立水平基线和颜色。默认层距 `0.40`，总棒高为层高的 `0.58`，只绘制相对强度不低于 `5%` 的峰；原始卡片峰表不删数据。卡片数可以与样品数不同，不需要强行配对。单谱使用 `--peak-marking markers` 或 `--peak-marking hkl` 时，下方卡片棒状图和卡片标签自动隐藏；多样品堆叠图仍保留卡片层。
- **卡片标签**：优先取 Jade 卡片文件头部的 `# formula:`，例如 `Si`、`FeS2`、`CuFeS2`。所有标签、棒状图和基线必须留在同一坐标框内；标签放在棒线上方但不要贴近层顶，靠右对齐，并用紧凑层距避免标签越框或压峰。缺少该字段时才回退到 `--card "名称=路径"` 里的名称。
- **字体与边框**：英文使用 Times New Roman，公式使用 STIX 数学字体风格；找不到时再回退。上、下、左、右保留完整图框，但顶部边框不显示刻度线，底部 X 轴刻度朝内。
- 旧的 `--card-position per-sample` 仅用于必须把某张卡片贴在对应样品下方的特殊场景；普通投稿图优先使用默认分层排版。

## 四、脚本不做什么

`xrd_stack.py` 只做「读取 → 可选显示平滑 → 归一化 → 排版」。它**不做**：

- 扣背景和 Kα2 剥离（这些请在 Jade/仪器软件里做完再导出，并在文中说明）；
- 寻峰、拟合、晶粒尺寸/微应变计算；
- 物相检索或峰归属；
- 生成 PDF 卡片号（卡片号只能来自检索结果或用户提供的文件）。

## 五、命令行参数

```
python scripts/xrd_stack.py [--sample "名称=路径"]... [--card "名称=路径"]... --out 输出目录
```

| 参数 | 作用 |
| --- | --- |
| `--sample 名称=路径` | 样品谱图文件，可重复；两列数值（2θ、强度） |
| `--card 名称=路径` | Jade 导出的卡片 TXT，可重复；d–I 或 2θ–I 都能识别 |
| `--out 目录` | 输出目录（默认 `./xrd_out`） |
| `--demo` | 用合成数据跑一遍自检，不需要输入文件 |
| `--cards-only` | 只解析卡片导出 CSV，不画图（不需要 matplotlib） |
| `--radiation` / `--wavelength` | 波长预设或直接指定 λ（Å） |
| `--norm max1\|max100\|none` | 归一化方式（默认 max1） |
| `--smooth none\|savgol` | 成图平滑方式（默认 `savgol`，原始强度表不改） |
| `--smooth-window` / `--smooth-polyorder` | Savitzky–Golay 窗口与阶数（默认 11 和 3） |
| `--sample-cols i,j` / `--card-cols i,j` | 文件里峰位与强度所在的列号（1 基），列多时必用 |
| `--card-kind auto\|two_theta\|d` | 强制指定卡片第一列含义 |
| `--gap` / `--stick-height` / `--stick-width` | 曲线间距、卡片竖线占行高比例、竖线线宽 |
| `--card-row-height` | 下方卡片的分层行高（默认 0.40） |
| `--card-min-intensity` | 卡片棒线显示阈值，默认 5%；只过滤图形，不删除原始卡片表 |
| `--card-position per-sample\|bottom` | 卡片贴在各自曲线下方，或统一放在底部（默认底部） |
| `--card-labels` / `--no-card-labels` | 是否在坐标框内右上部显示卡片化学式（默认显示） |
| `--sample-labels` / `--no-sample-labels` | 多条谱时是否在右侧显示样品名（默认显示；单条谱不重复显示） |
| `--line-width` / `--colors` / `--card-colors` | 曲线线宽、样品颜色和卡片颜色（HEX 列表） |
| `--legend auto\|above\|inside\|none` | 图例位置；默认 `auto` 在分层卡片图中不重复绘制卡片图例，因为每行已有框内标签 |
| `--peak-marking none\|markers\|hkl` | 单谱标峰：符号对应卡片，或标晶面指数（默认不标） |
| `--hkl-card 1` / `--hkl-min-intensity` | hkl 模式选第几张卡片，以及只标到哪个卡片强度阈值 |
| `--marker-min-intensity` | markers 模式只标到哪个卡片强度阈值 |
| `--peak-tolerance` | 卡片峰与实测峰匹配容差（°） |
| `--observed-min-fraction` | 实测局部峰最低相对强度比例 |
| `--x-range MIN MAX` / `--x-tick` | X 轴范围与主刻度间隔 |
| `--xlabel` / `--ylabel` / `--title` | 轴标题与图标题 |
| `--font` | 首选英文字体；默认 Times New Roman，中文自动回退 Microsoft YaHei |
| `--width` / `--height` / `--dpi` | 画布尺寸（英寸）与位图分辨率 |
| `--formats png,pdf,svg` | 导出格式 |

## 六、输出文件

| 路径 | 内容 |
| --- | --- |
| `xrd_stack.png/.pdf/.svg` | 成图（矢量图便于投稿排版） |
| `manifest.json` | 输入路径、λ、归一化方式、偏移量、每张卡片的三强峰、警告列表 |
| `cards_clean/<卡片名>.csv` | 清理后的卡片表：`2theta_deg, d_A, I_rel_100, I_raw, hkl` |
| `origin/Sheet1_samples.csv` | 样品数据，按 Origin 列习惯成对排列 |
| `origin/Sheet2_cards.csv` | 卡片数据，每张卡片两列 |
| `origin/Sheet3_peak_annotations.csv` | 单谱符号标峰或 hkl 标峰的匹配结果 |
| `origin/sample*.csv` / `origin/card*.csv` | 单个样品/卡片的独立表，含 `I_raw/I_norm/y_offset` |
| `origin/导入Origin说明.txt` | 导入与绘图的简短步骤 |
| `peak_annotations.csv` | 卡片峰、实测峰、匹配位置、化学式和 hkl 的可追溯记录 |

## 七、杂项

- 中文系统下仪器导出的 TXT 常见 GBK/GB18030 编码，脚本会依次尝试 UTF-8、GBK、Big5；读不出来时用记事本另存为 UTF-8 再试。
- 导出的 CSV 表头是 ASCII，保存为 UTF-8（带 BOM），Excel/Origin 都能直接打开。
- 脚本控制台输出跟随系统编码（中文 Windows 为 GBK）；若在重定向到文件时出现乱码，用 GBK 解码查看。
