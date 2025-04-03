# iOS资源分析工具 (Resource Analyzer)

## 简介

Resource Analyzer是一个强大的Python脚本，专为iOS开发者设计，用于分析和优化项目中的资源文件。该工具可以帮助您：

- 按大小排序所有资源文件，快速定位大文件
- 检测项目中可能未使用的资源文件
- 识别视觉上相似的图片资源，减少冗余
- 生成详细的资源分析报告

通过使用此工具，您可以显著减少应用程序的体积，提高下载速度和用户体验。

## 功能特点

- **资源大小统计**：扫描所有资源文件并按大小排序
- **未使用资源检测**：识别代码中未引用的资源文件
- **相似图片检测**：使用感知哈希算法找出相似图片
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

直接在命令行中显示分析结果，包括资源大小列表、未使用资源、相似图片组和优化建议。

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
3. **相似图片检测**：对所有图片资源计算感知哈希值，比较哈希之间的汉明距离来确定相似性
4. **资源分析**：汇总分析结果，生成报告

## 注意事项

- 未使用资源检测基于静态分析，可能存在误报，请在删除前手动确认
- 相似图片检测已排除同一资源集内的变体（如@2x/@3x）
- 默认排除Pods、Carthage等第三方目录
- 首次运行可能较慢，但会建立缓存加速后续分析

## 优化建议

工具提供的优化建议包括：

- **图片优化**：使用ImageOptim或TinyPNG压缩，考虑WebP格式
- **音频优化**：使用Audacity或XLD压缩，选择合适的音频质量
- **视频优化**：使用HandBrake或FFmpeg压缩，考虑H.264/H.265编码
- **资源管理**：定期清理未使用资源，使用资源目录（.xcassets）管理图片

## 许可

本工具开源免费使用。

## 贡献与反馈

欢迎提交问题报告和功能建议，共同改进此工具。
