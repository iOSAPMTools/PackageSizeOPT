 # IPA 分析器脚本 (ipa_analyzer.py)

## 概述

该脚本用于分析 iOS IPA 文件的体积构成。它会解压 IPA 文件，对其内容（可执行文件、框架、资源等）进行分类，计算各组件的大小，并将分析结果按历史记录存储。脚本还能生成交互式的 HTML 报告，用于对比两个 IPA 文件或可视化历史体积趋势。

## 功能特性

*   **详细的 `.app` 包分析**: 将 `.app` 包分解为以下组件：
    *   可执行文件
    *   框架 (`Frameworks/`)
    *   App 扩展 / 插件 (`PlugIns/`)
    *   按文件扩展名分类的资源 (例如 `.png`, `.jpg`, `.car`, `.nib`, `.strings`)
    *   按本地化分类的资源 (`*.lproj/`)
    *   其他未分类文件
*   **顶层目录分析**: 测量 IPA 根目录下存在的 `SwiftSupport` 和 `Symbols` 目录的大小。
*   **易读的体积格式**: 以字节 (B)、KB、MB 或 GB 显示文件大小。
*   **版本推断**: 自动尝试从 IPA 文件名中确定应用版本 (例如 `AppName-1.2.3.ipa`)。
*   **历史记录追踪**: 将分析结果持久化存储在 `ipa_analysis_history.json` 文件中，支持趋势分析。会覆盖相同版本号的旧记录。
*   **HTML 报告生成**: 使用 Chart.js 创建交互式 HTML 报告：
    *   **对比报告**: 并排展示两个 IPA 文件的体积构成，包含表格和条形图。
    *   **历史报告**: 通过折线图展示不同分析版本中各组件的历史体积趋势，并包含最新版本的分析表格。
*   **命令行接口**: 提供易于使用的命令来执行不同的分析模式。

## 环境要求

*   **Python 3**: 该脚本需要 Python 3 环境。
*   **标准库**: 仅使用 Python 标准库 (`zipfile`, `os`, `shutil`, `argparse`, `pathlib`, `tempfile`, `json`, `datetime`, `re`, `html`)。无需通过 pip 安装外部包。
*   **网络连接 (用于报告)**: 查看生成的 HTML 报告需要网络连接，以便从 CDN 加载 Chart.js 库。

## 使用方法

在终端中运行脚本，使用 `python ipa_analyzer.py` 命令，后跟所需的模式和选项。

```bash
python ipa_analyzer.py [模式] [选项]
```

### 模式

#### 1. 分析模式 (Analyze Mode)

分析单个 IPA 文件，推断其版本（除非手动指定），并将结果保存到历史文件 (`ipa_analysis_history.json`) 中。

**命令:**
```bash
python ipa_analyzer.py --analyze <IPA_路径> [--version <版本号>] [--output <输出HTML路径>]
```

*   `<IPA_路径>`: 需要分析的 IPA 文件路径。
*   `--version <版本号>` (可选): 手动指定版本字符串。如果省略，脚本会尝试从文件名推断。
*   `--output <输出HTML路径>` (可选): 虽然存在此选项，但在分析模式下不太常用，因为脚本默认流程中未激活单个文件报告的生成。主要输出是更新 `ipa_analysis_history.json` 文件。

**示例:**

```bash
# 分析 MyApp-1.0.ipa，指定版本为 1.0，并保存到历史记录
python ipa_analyzer.py --analyze MyApp-1.0.ipa --version 1.0

# 分析 MyApp-v1.1_build25.ipa，让脚本从文件名推断版本
python ipa_analyzer.py --analyze MyApp-v1.1_build25.ipa
```

#### 2. 对比模式 (Compare Mode)

对比两个指定的 IPA 文件的大小构成，并生成交互式 HTML 对比报告。

**命令:**
```bash
python ipa_analyzer.py --compare <当前IPA路径> <先前IPA路径> [--output <输出HTML路径>]
```

*   `<当前IPA路径>`: 较新或当前的 IPA 文件路径。
*   `<先前IPA路径>`: 用于对比的较旧或先前的 IPA 文件路径。
*   `--output <输出HTML路径>` (可选): 保存生成的 HTML 报告的文件路径。默认为 `ipa_report.html`。

**示例:**

```bash
# 对比 MyApp-1.1.ipa 和 MyApp-1.0.ipa，并将报告保存为 comparison_report.html
python ipa_analyzer.py --compare MyApp-1.1.ipa MyApp-1.0.ipa --output comparison_report.html
```

#### 3. 历史模式 (History Mode)

从 `ipa_analysis_history.json` 加载所有先前保存的分析数据，并生成显示历史体积趋势的交互式 HTML 报告。

**命令:**
```bash
python ipa_analyzer.py --history [--output <输出HTML路径>]
```

*   `--output <输出HTML路径>` (可选): 保存生成的 HTML 报告的文件路径。默认为 `ipa_report.html`。

**示例:**

```bash
# 生成历史报告并将其保存为 history_trend.html
python ipa_analyzer.py --history --output history_trend.html
```

## 输出

### `ipa_analysis_history.json`

*   **用途**: 存储由 `--analyze` 模式触发的每次分析运行的结果。
*   **格式**: 一个 JSON 文件，包含一个分析对象列表。每个对象代表一个已分析的 IPA 版本，并包含：
    *   `version`: 版本标识符（推断或提供）。
    *   `ipa_path`: 被分析 IPA 的原始路径。
    *   `ipa_size`: IPA 文件的总大小（字节）。
    *   `analysis_timestamp`: 执行分析时的 ISO 格式时间戳。
    *   `app_bundle_analysis`: `.app` 包大小的详细分解（可执行文件、框架、资源等）。
    *   `swift_support`: `SwiftSupport` 目录的大小信息。
    *   `symbols`: `Symbols` 目录的大小信息。
*   **排序**: 保存时，条目按 `analysis_timestamp` 排序（最新的在前）。

### HTML 报告 (`*.html`)

*   **用途**: 提供 IPA 体积数据的可视化摘要和比较。
*   **对比报告 (`--compare` 模式)**:
    *   并排显示 IPA 整体组件（总 IPA、Payload/.app、SwiftSupport、Symbols）的大小比较。
    *   展示详细表格，比较 `.app` 包组件（可执行文件、框架总计、插件总计、资源总计、其他）的大小。
    *   包含针对特定框架、插件、按扩展名分类的资源、按本地化分类的资源的详细表格。
    *   包含一个交互式条形图，比较两个版本之间主要 `.app` 包组件的大小。
    *   高亮显示体积差异和百分比变化。
*   **历史报告 (`--history` 模式)**:
    *   展示交互式折线图，显示以下组件随时间/版本的体积趋势：总 IPA 大小、.app 包大小、可执行文件大小、框架大小、SwiftSupport 大小和 Symbols 大小。
    *   包含一个表格，总结历史文件中找到的*最新*版本的详细分析。
*   **技术**: 使用从 CDN 加载的 Chart.js 来渲染交互式图表。
