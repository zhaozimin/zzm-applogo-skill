# zzm-applogo - 独立应用图标下载 Skill

Python 3.10+ + Pillow + NumPy

本文件是独立安装单元的 L1 地图。
本单元不依赖仓库根目录的测试与说明。

成员清单
SKILL.md: Agent 入口。定义触发条件、来源选择与交付边界。
requirements.txt: Python 运行依赖。供虚拟环境安装。
LICENSE.txt: 独立分发时保留的 MIT 许可声明。
scripts/: 执行链路。拆分网络、图源、渲染与命令入口。
references/: 固定图标规格与来源边界。
agents/: Skill 的界面元数据。

本目录独立于仓库测试工具。复制后即可运行。
输出目录以调用者工作区为基准。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
