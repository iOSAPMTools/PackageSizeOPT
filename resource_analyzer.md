# iOS资源分析工具 (Resource Analyzer)

## 简介

Resource Analyzer是一个强大的Python脚本，专为iOS开发者设计，用于分析和优化项目中的资源文件。该工具可以帮助您：

- 按大小排序所有资源文件，快速定位大文件
- 检测项目中可能未使用的资源文件
- 识别视觉上相似的图片资源，减少冗余
- 检测超大尺寸或低压缩率的图片
- 分析本地化资源文件及其引用
- 生成详细的资源分析报告

通过使用此工具，您可以显著减少应用程序的体积，提高下载速度和用户体验。

## 功能特点

- **资源大小统计**：扫描所有资源文件并按大小排序
- **未使用资源检测**：识别代码中未引用的资源文件
- **相似图片检测**：使用感知哈希算法找出相似图片
- **超大图片检测**：识别尺寸过大或压缩率低的图片
- **本地化资源分析**：解析.lproj目录中的本地化资源
- **已编译资源分析**：分析.car等已编译资源文件
- **动态引用检测**：识别代码中动态拼接的资源引用模式
- **Asset Catalog分析**：解析.xcassets的Contents.json提取资源引用
- **增强的资源引用检测**：支持现代iOS/macOS开发中的多种资源引用模式
- **资源优化建议**：提供针对不同类型资源的优化方案
- **多种输出格式**：支持文本、JSON、HTML和CSV格式输出
- **智能缓存**：使用哈希缓存加速重复分析

## 安装依赖

在使用此工具前，您需要安装以下Python依赖库：

```bash
pip install Pillow ImageHash
```

## 基本用法

```bash
python resource_analyzer.py 项目路径 [选项]
```

### 示例

```bash
# 基本用法
python resource_analyzer.py /path/to/YourXcodeProject

# 自定义大文件阈值为200KB，相似度阈值为3，输出为HTML格式
python resource_analyzer.py /path/to/YourXcodeProject --large-threshold 200 --similarity-threshold 3 --output html

# 生成JSON格式报告
python resource_analyzer.py /path/to/YourXcodeProject --output json
```

## 参数说明

| 参数 | 描述 | 默认值 |
|------|------|--------|
| `project_dir` | iOS项目根目录的路径 (必需参数) | - |
| `--large-threshold` | 大文件阈值（KB），超过此值的资源将被标记 | 100 |
| `--similarity-threshold` | 图片相似度阈值（汉明距离），值越小表示要求越相似 | 5 |
| `--output` | 输出格式，可选值：text、json、html、csv | text |

## 输出格式

### 文本输出 (text)

直接在命令行中显示分析结果，包括资源大小列表、未使用资源、相似图片组、超大图片和优化建议。

### HTML输出 (html)

生成一个美观的HTML报告文件`resource_analysis_report.html`，包含完整的分析结果，方便分享和查看。

### CSV输出 (csv)

生成四个CSV文件，便于进一步数据分析：
- `resource_size_report.csv`：资源大小统计
- `unused_resources.csv`：未使用资源列表
- `similar_images.csv`：相似图片组信息
- `optimization_suggestions.csv`：优化建议

### JSON输出 (json)

生成机器可读的JSON格式数据，便于与其他工具集成。

## 工作原理

1. **资源扫描**：递归扫描项目目录，识别所有资源文件（图片、音频、视频等）
2. **引用检测**：分析代码文件、界面文件和配置文件，查找对资源的引用
   - 扫描Swift、Objective-C代码中的静态和动态资源引用
   - 解析Storyboard、XIB文件中的资源引用
   - 分析Plist、JSON等配置文件中的资源键值
   - 提取.xcassets中的Contents.json资源引用
   - 分析项目配置文件中的资源设置
3. **相似图片检测**：对所有图片资源计算感知哈希值，比较哈希之间的汉明距离来确定相似性
4. **超大图片检测**：分析图片尺寸和文件大小比例，检测异常图片
5. **资源分析**：汇总分析结果，生成报告

## 支持的资源引用模式

工具可以识别多种iOS/macOS开发中的资源引用模式，包括：

### UIKit/AppKit 引用
- UIImage(named:)，NSImage(named:)
- [UIImage imageNamed:]，[NSImage imageNamed:]
- UIImage(contentsOfFile:)，NSImage(contentsOfFile:)

### SwiftUI 引用
- Image("resourceName")
- Image(systemName: "symbol.name")
- Image(decorative: "resourceName")
- Label(_, systemImage: "symbol.name")

### 资源管理库
- R.swift：R.image.name，R.string.key等
- SwiftGen：Asset.name.image，L10n.key，ColorName.name，FontFamily.name

### SF Symbols
- UIImage(systemName:)，NSImage(symbolName:)
- Symbol("symbol.name")

### 其他常见模式
- 通用 named: 参数
- Bundle.main.url(forResource:) 
- NSLocalizedString() 本地化字符串引用

### 动态引用检测
- 变量 + 字符串后缀
- 字符串前缀 + 变量
- 字符串格式化
- 多段字符串拼接

## 内置阈值与配置

工具内置了一些默认阈值，用于识别问题资源：

- **超大图片阈值**：宽度>2000像素或高度>2000像素的图片将被标记
- **图片压缩率阈值**：当图片大小与像素比例超过10KB/千像素时将被标记为压缩率低
- **相似图片阈值**：默认汉明距离为5，可通过参数调整
- **大文件阈值**：默认100KB，可通过参数调整

## 缓存机制

- 缓存存储位置：工具会在当前目录下创建`.resource_cache`文件夹
- 缓存内容：图片哈希值、文件引用分析结果等
- 缓存识别：基于文件MD5哈希，只有文件内容变化才会重新计算
- 缓存管理：自动创建和更新，无需手动干预

## 注意事项

- 未使用资源检测基于静态分析，可能存在误报，请在删除前手动确认
- 相似图片检测已排除同一资源集内的变体（如@2x/@3x）
- 默认排除Pods、Carthage等第三方目录
- 首次运行可能较慢，但会建立缓存加速后续分析
- 动态资源引用检测可能不完整，尤其是复杂的字符串拼接和变量组合

## 优化建议

工具提供的优化建议包括：

- **图片优化**：使用ImageOptim或TinyPNG压缩，考虑WebP格式
- **超大图片处理**：压缩过大图片或使用不同分辨率变体
- **低压缩率图片**：使用更高效的压缩算法或更合适的格式（如WebP）
- **相似图片合并**：合并视觉上相似的图片资源，减少冗余
- **音频优化**：使用Audacity或XLD压缩，选择合适的音频质量
- **视频优化**：使用HandBrake或FFmpeg压缩，考虑H.264/H.265编码
- **资源管理**：定期清理未使用资源，使用资源目录（.xcassets）管理图片

## 支持的资源类型

工具支持分析多种iOS资源类型，包括：

- **图片**：png、jpg、jpeg、gif、webp、svg等
- **音频**：mp3、wav、aac、m4a等
- **视频**：mp4、mov等
- **字体**：ttf、otf等
- **界面文件**：storyboard、xib等
- **资源目录**：xcassets及其内部的各类资源集
- **本地化资源**：lproj目录及其中的strings文件
- **已编译资源**：car文件
- **其他**：plist、json、strings等配置文件

## 许可

本工具开源免费使用。

## 贡献与反馈

欢迎提交问题报告和功能建议，共同改进此工具。
