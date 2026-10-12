---
name: zzm-applogo
description: 从苹果 App Store 和 macosicons.com 查找、下载应用图标，统一为 1024×1024 的透明圆角阴影 PNG，保存到用户工作区或指定目录。用于“帮我下载 app logo”、按应用名称找图标、批量下载和候选预览；不设计新 Logo，也不修改系统应用图标。
license: MIT
---

# zzm-applogo

使用 [scripts/downlogo.py](scripts/downlogo.py) 完成检索、下载、渲染与校验。
脚本路径必须以当前 Skill 目录为基准解析。
相对输出路径以用户工作区为基准解析，不以 Skill 目录为基准。

## 执行

使用 Python 3.10+，依赖 [requirements.txt](requirements.txt) 中的 Pillow 与 NumPy。
先检查运行环境。缺依赖时使用独立虚拟环境安装，不改系统 Python。

```bash
python -m venv .venv
# macOS / Linux
.venv/bin/python -m pip install -r <Skill目录>/requirements.txt
# Windows
.venv\Scripts\python.exe -m pip install -r <Skill目录>\requirements.txt
```

用已具备依赖的解释器运行下列命令。
包含空格的应用名作为一个参数传入。

```bash
python <Skill目录>/scripts/downlogo.py download ChatGPT
python <Skill目录>/scripts/downlogo.py download Obsidian 飞书 剪映 --numbered --preview -o <用户指定目录>
python <Skill目录>/scripts/downlogo.py search Notion
```

默认输出为 `<用户工作区>/app-logos/`。
若用户已给出目录，直接通过 `-o` 使用该目录。
下载报告含每个文件的来源、匹配身份、原图分辨率与规格结果。
同名文件自动递增后缀，不覆盖已有文件。

## 来源与身份

- 默认 `--source auto`：优先 App Store 的常规图源，再用 macosicons 兜底。
- `--source appstore` 或 `--source macosicons`：只使用指定来源。
- App Store 默认按 `cn,us` 查找，先 iOS，再 macOS。用 `--country`、`--platform` 调整。
- `--seller` 筛选 App Store 开发者；同名或弱匹配返回 `needs_selection`。
- 出现歧义时展示应用名称、开发者、平台和 ID。请用户选择后重试，不把相似名称当作目标应用。
- App Store 的“上架应用图源”不等于对品牌身份的独立认证。保留开发者、bundle ID 与商店链接供核对。
- macosicons 是社区图源。`communityOfficialFlag` 是网站标记，不是 Apple 认证。
- 飞书与 Lark、剪映与 CapCut、印象笔记与 Evernote 分开检索。
- 不使用本机已安装应用或第三方官网作隐式第三来源。

```bash
python <Skill目录>/scripts/downlogo.py download ChatGPT --app-id 6448311069
python <Skill目录>/scripts/downlogo.py download Notion --source macosicons --id <候选ID>
python <Skill目录>/scripts/downlogo.py download Notion --source macosicons --style dark --candidates 3 --preview
```

默认选择常规款式。用户明确要求时使用 `dark`、`light` 或 `liquid-glass` 社区款式。
`--candidates N` 表示下载候选供比较，不代表这些候选均已确认身份。
显式 ID 代表用户选定记录，可绕过名称匹配；仍须校验图片规格。

## 图像与交付

所有主图标都重新生成同一套圆角、阴影与外边距。
固定规格见 [references/icon-spec.md](references/icon-spec.md)。
这是统一排版样式，不是对某一版本手机系统渲染的逐像素复刻。

```bash
python <Skill目录>/scripts/downlogo.py normalize -i <本地图片> -o <成品.png>
python <Skill目录>/scripts/downlogo.py verify <成品.png>
```

不要把放大图称为原生高清图。`upscaled: true` 时说明原图分辨率不足。
不要把预览拼图当作满足主图标规格的单个文件。
批量下载允许部分成功；逐项说明失败或待选择状态，不报告全部成功。
退出码非零时读取 JSON 原因，不盲目重复下载。

向用户交付可点击的主图标路径；批量任务同时交付预览与下载报告。
以 `status: ok` 且 `spec.compliant: true` 为单个图标的完成条件。
源站失败时说明原因，不生成替代品牌图案。
