# zzm-applogo-skill - 双来源应用图标下载 Skill

Python 3.10+ + Pillow + NumPy + unittest

<directory>
zzm-applogo/ - 可独立安装的 Skill。包含入口、图源与渲染器。
tests/ - 离线行为回归。验证识别、渲染和落盘边界。
.github/ - 持续集成。验证三个系统的 Python 执行链路。
assets/ - README 展示素材。包含应用图标效果截图。
</directory>

<config>
README.md - 面向使用者的安装与使用说明。
LICENSE - MIT 代码许可。图标权利不在许可范围内。
.gitignore - 排除下载物、缓存与本机环境。
</config>

图源模块只返回候选。入口决定是否下载。
渲染器只依赖本地图像与固定外观参数。
网络失败必须与无匹配结果区分。
代码与目录地图在同一次变更中更新。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
