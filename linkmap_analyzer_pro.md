# Link Map 分析工具

这是一个用于分析 iOS 应用 Link Map 文件的工具，可以帮助您了解应用的二进制大小构成，并提供优化建议。

## 功能特点

### 1. 基础分析功能
- 解析 Link Map 文件中的 Sections 和 Symbols 信息
- 按库/模块聚合大小分析
- 按文件大小分析
- 详细的优化建议

### 2. 高级分析功能
- Sections 分析（更详细的段分析）
- 多种输出格式支持（文本、CSV、JSON、HTML）
- 可视化图表（使用 Chart.js）
- 版本比较功能

### 3. 优化建议
- 未使用代码和重复代码检查建议
- 静态库链接优化建议
- 动态库使用建议
- 依赖管理建议

## 使用方法

### 1. 基本分析
```bash
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt
```

### 2. 生成多种格式报告
```bash
# 生成文本报告
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt -o report.txt

# 生成 CSV 报告
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt --csv=report.csv

# 生成 JSON 报告
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt --json=report.json

# 生成 HTML 报告（包含可视化图表）
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt --html=report.html
```

### 3. 版本比较
```bash
# 生成文本比较报告
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt --compare=linkmap-old.txt --compare-output=comparison.txt

# 生成 HTML 比较报告
python linkmap_analyzer_pro.py xxx-LinkMap-normal-arm64.txt --compare=linkmap-old.txt --compare-html=comparison.html
```

## 命令行参数说明

- `linkmap_file`: Link Map 文件路径（必需）
- `-o, --output`: 输出文本报告的文件路径
- `--csv`: 输出 CSV 格式报告的路径
- `--json`: 输出 JSON 格式报告的路径
- `--html`: 输出 HTML 格式报告的路径
- `--top`: 显示前 N 个最大的文件，默认为 20
- `--compare`: 要比较的旧版本 Link Map 文件路径
- `--compare-output`: 比较报告的输出路径
- `--compare-html`: 比较报告的 HTML 输出路径

## 报告内容说明

### 1. 基础报告
- 摘要信息（总大小、符号总大小、符号数量）
- Sections 分析（各段大小及占比）
- 库/模块分析（Top 15）
- 文件大小分析（Top 20）
- 优化建议

### 2. HTML 报告
- 可视化图表展示
- 交互式数据表格
- 响应式设计

### 3. 版本比较报告
- 总体变化分析
- 库/模块变化（Top 20）
- 文件变化（Top 20）
- 可视化对比图表
