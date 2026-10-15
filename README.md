# XRD Origin + Jade Skill

这是一个可放入 Codex `skills` 目录的 XRD 物相鉴定与配图 skill。它把 Jade 6.5 的 GUI 检索流程、PDF 标准卡片导出，以及 Origin / matplotlib 的 XRD 堆叠图生成流程封装成可复用的脚本和操作说明。

仓库地址：
<https://github.com/lxhb2/xrd-origin-Jades-kill>

## 功能

- 用 `scripts/jade_phaseid.py` 驱动 Jade 6.5：寻峰、元素/化学式筛选、Search/Match、候选结果导出和 PDF 卡片导出。
- 用 `scripts/xrd_stack.py` 解析样品谱与 Jade 卡片：生成 XRD 堆叠图、下方分层 PDF 棒状图、Origin 可导入数据表。
- 单谱支持 `markers` 符号标峰和 `hkl` 晶面指数标峰；启用标峰时不再绘制 PDF 卡片棒状图。
- 用 `scripts/origin_stack.py` 调用本机 Origin，生成可继续编辑的 `OPJU + PNG + PDF`。
- `references/` 和 `assets/` 提供 Jade 操作、Origin 画法、科学判据、质检清单和示例图。

## 环境要求

- Windows 10/11
- Python 3.10+
- Jade 6.5，且已安装并授权可用的 ICDD PDF 数据库
- Origin 2025b 或兼容版本，仅在使用自动生成 OPJU 时需要
- 使用真实 PDF 卡片时必须遵守 ICDD 数据库许可，不要把数据库文件或整段卡片数据公开分发

## 安装为 Codex Skill

将仓库克隆到 Codex 的 skills 目录，并保留目录名 `xrd-origin-jade`：

```powershell
git clone https://github.com/lxhb2/xrd-origin-Jades-kill.git "$env:USERPROFILE\.codex\skills\xrd-origin-jade"
```

如果目标目录已经存在，先把原目录移到备份位置，再执行克隆或在原目录中 `git pull`。

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

使用 Origin 自动出图的 Python 环境还需安装：

```powershell
python -m pip install -r requirements-origin.txt
```

`originpro` 必须与本机已安装的 Origin 版本匹配。

## 快速开始

先运行自检，不依赖真实数据和 Origin：

```powershell
python scripts/xrd_stack.py --demo --out .\demo
```

生成单谱符号标峰图：

```powershell
python scripts/xrd_stack.py `
  --sample "样品=raw\sample.txt" `
  --card "Si=jade\Si_75-0589.txt" `
  --card "FeS2=jade\FeS2_71-1680.txt" `
  --out .\figs\single `
  --peak-marking markers `
  --marker-min-intensity 5
```

生成多样品堆叠图：

```powershell
python scripts/xrd_stack.py `
  --sample "样品1=raw\s1.txt" `
  --sample "样品2=raw\s2.txt" `
  --card "Si=jade\Si_75-0589.txt" `
  --card "FeS2=jade\FeS2_71-1680.txt" `
  --out .\figs\stack
```

Jade 检索前必须先取得目标元素和化学式。示例：

```powershell
python scripts/jade_phaseid.py search `
  --pattern "raw\sample.raw" `
  --out .\jade_out `
  --elements "Si,Fe,Cu,S" `
  --formula "Si + FeS2 + CuFeS2" `
  --filter-mode possible `
  --export-card 75-0589 `
  --export-card 71-1680 `
  --export-card 75-0253
```

用 Origin 生成可编辑工程：

```powershell
python scripts/origin_stack.py `
  --origin-dir .\figs\stack\origin `
  --out .\figs\stack_origin `
  --x-range 10 80
```

运行 Origin 自动脚本前先保存并关闭已有 Origin 工程；只有确认可以复用现有进程时才加 `--allow-existing`。

## 目录结构

```text
.
|-- SKILL.md
|-- README.md
|-- CHANGELOG.md
|-- VERSION
|-- agents/
|-- assets/
|-- references/
`-- scripts/
    |-- jade_phaseid.py
    |-- origin_stack.py
    `-- xrd_stack.py
```

## 版本管理

- `VERSION` 保存当前打包版本号。
- `CHANGELOG.md` 记录版本变化。
- Git 标签使用 `v主版本.次版本.修订号`，当前标签为 `v1.2.2`。
- 脚本内部版本：`jade_phaseid.py v2.2.0`、`xrd_stack.py v1.2.2`、`origin_stack.py v1.2.2`。

## 科学边界

脚本只做数据解析、峰位匹配和版式生成，不替使用者认定未知物相。PDF 卡片号、峰位和标准强度必须来自授权数据库或用户确认的文件；最终物相归属要结合三强峰、元素约束、样品信息和文献判断。

## 免责声明

本项目不是 ICDD、OriginLab 或 Jade/MDI 的官方项目，不包含 ICDD 数据库。Jade、Origin 和 ICDD PDF 数据库均需由使用者合法取得并遵守各自许可。
