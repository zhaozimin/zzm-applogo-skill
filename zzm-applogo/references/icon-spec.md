# 图标规格与图源边界
> L2 参考 | 父级: ../CLAUDE.md

## 固定外观

| 项目 | 数值 |
|---|---|
| 文件 | PNG，8-bit RGBA |
| 画布 | 1024×1024 像素 |
| 色彩 | 嵌入 sRGB ICC 配置 |
| 主体 | 824×824 居中区域 |
| 外边距 | 100 像素 |
| 圆角 | 超椭圆，指数 4.3，双倍采样抗锯齿 |
| 阴影 | 黑色，峰值透明度参数 72/255 |
| 阴影偏移 | 向下 10 像素 |
| 阴影模糊 | 高斯半径 14 像素 |
| 分辨率元数据 | 144 DPI；显示大小由像素决定 |

参数由 `scripts/imaging.py` 定义。
这些参数定义本工具的统一样式。
参数不代表 Apple 当前系统的精确模板。

## 原图进入渲染器

不透明方形图直接缩放进入卡片。
带透明边距的卡片先裁去旧阴影。
透明标志放在白色卡片中央，最长边为 560 像素。
非正方形内容保持比例，不拉伸。
渲染器统一生成外轮廓与阴影。
图案内部已经烘焙的光影保留。
不同来源的内部画风不由几何归一化改变。

Pillow 解码 PNG、JPEG、WebP 与 ICNS。
ICNS 使用最大可解码图层。
本工具不调用系统图标转换程序。
来源图小于目标内容区时，报告 `upscaled: true`。

## 校验

`verify` 检查尺寸、格式、RGBA 与 sRGB。
透明度必须与完整圆角和阴影模板一致。
透明度每像素误差上限为 2/255。
直角图、缺阴影图与错误边距均不合格。
完全透明图与不可解码图返回失败结果。

## 来源

App Store 使用 Apple 搜索和 ID 查询接口。
默认常规图源优先 iOS，再查 macOS。
自动匹配要求完整名称或标题主名称一致。
常见易混淆品牌另核对开发者关键词。
其他应用保留开发者与 bundle ID 供用户判断。
同名的不同 bundle ID 要求选择。
CDN 的 1024 地址须实际下载并解码。
高分辨率地址失败后，尝试接口原地址。

macosicons 使用网站搜索接口。
默认排除概念改色、旧版、暗黑与玻璃款式。
名称匹配优先于社区标记和下载量。
PNG 原图与 ICNS 原包均可作为输入。
低清预览字段不作为最终图源。
网站接口不是本工具控制的稳定 API。
接口失败必须出现在下载报告中。

App Store 搜索按约 20 次/分钟限速。
同一进程缓存重复请求。
网络请求最多尝试两次。
Apple 主机请求失败后停止别名扩搜。

## 权利与资料

MIT 许可仅覆盖本仓库代码与说明。
图标权利由品牌方或图标作者保留。
保留来源页面，使用时遵守来源条件。

- [Apple Search API 与素材使用条件](https://performance-partners.apple.com/search-api)
- [Apple 图标遮罩与系统渲染](https://developer.apple.com/documentation/xcode/creating-your-app-icon-using-icon-composer)
- [macosicons](https://macosicons.com/)
- [Pillow ICNS 支持](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#icns)

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
