# scripts/
> L2 | 父级: ../CLAUDE.md

成员清单
downlogo.py: CLI 协调器。选择候选并输出下载报告。
sources.py: 双来源适配器。保留应用身份与来源元数据。
network.py: HTTPS 客户端。复用缓存、限速与有限重试。
imaging.py: 图标渲染器。统一几何、色彩与透明阴影。
storage.py: 文件输出边界。独占命名并原子写入文件。

sources 依赖 network。入口依赖 sources 与 imaging。
storage 不访问网络。imaging 不选择应用。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
