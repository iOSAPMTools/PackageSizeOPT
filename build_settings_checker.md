# Xcode 构建设置检查器 (build_settings_checker.py)

## 简介

`build_settings_checker.py` 是一个 Python 脚本，用于检查指定 Xcode 项目的构建设置，并将其与一组推荐用于优化 App 包体积的设置进行比较。它可以帮助开发者快速识别可能影响最终 App 大小的配置项。

## 工作原理

脚本通过调用苹果官方的 Xcode 命令行工具 `xcodebuild -showBuildSettings` 来获取指定 Target 和 Configuration 下实际生效的构建设置。这种方法能够准确反映 Xcode 在构建过程中考虑了所有继承、覆盖关系以及 `.xcconfig` 文件后的最终设置值。

然后，脚本将获取到的设置与内部定义的一组推荐值进行比较，并生成报告指出差异。

## 依赖项

运行此脚本需要：

1.  **Python 3**: 脚本是用 Python 3 编写的。
2.  **Xcode 命令行工具**: 脚本依赖 `xcodebuild` 命令。请确保已安装 Xcode，并在 Xcode 的 Preferences -> Locations -> Command Line Tools 中选择了正确的 Xcode 版本。可以通过在终端运行 `xcodebuild -version` 来检查。

## 使用方法

```bash
python build_settings_checker.py <project_path> [options]
```

**必需参数:**

*   `project_path`: Xcode 项目文件（`.xcodeproj` 目录）的路径。

**可选参数:**

*   `-t TARGET`, `--target TARGET`
    *   要检查的目标 Target 名称。如果省略，脚本将检查项目级别的设置（这通常不是最终 App 构建所使用的设置，建议明确指定 App 的主 Target）。
*   `-c CONFIG`, `--config CONFIG`
    *   要检查的 Build Configuration 名称。默认为 `Release`。
*   `-o OUTPUT`, `--output OUTPUT`
    *   将报告输出到指定的文件路径。如果省略，报告将打印到标准输出（终端）。
*   `-f {text,json,html}`, `--format {text,json,html}`
    *   指定报告的输出格式。默认为 `text`。
*   `-d`, `--debug`
    *   启用调试模式。会输出更详细的信息，例如 `xcodebuild` 命令获取到的所有设置以及设置比较的中间步骤。
*   `--no-color`
    *   禁用终端输出中的颜色代码。
*   `--color`
    *   强制启用终端颜色输出，即使在不支持的环境中（例如重定向到文件时）。
*   `--group-by-category`
    *   （当前为默认行为）在文本和 HTML 报告中按设置的功能类别（如编译优化、代码剥离等）对结果进行分组。
*   `--verbose-values`
    *   在调试模式下，显示更详细的值比较和规范化过程信息，有助于诊断特定设置的比较逻辑。

## 输出格式

*   **text**: (默认) 在终端输出带有颜色高亮的文本报告，易于阅读。包含统计摘要和按类别或优先级列出的问题项。
*   **json**: 输出 JSON 格式的报告，方便机器解析或与其他工具集成。包含元数据、统计信息、按类别和优先级分组的问题列表。
*   **html**: 生成一个独立的 HTML 文件报告，包含交互式表格、状态高亮、过滤控件和优先级建议，适合在浏览器中查看和分享。

## 推荐设置来源

脚本中内置的推荐设置主要基于 Apple 官方文档关于减少 App 体积的建议以及社区公认的最佳实践。目标是平衡优化效果和构建稳定性。

## 示例

1.  **检查名为 \"MyApp\" Target 的 Release 配置，输出到终端：**
    ```bash
    python build_settings_checker.py /path/to/MyApp.xcodeproj -t MyApp
    ```

2.  **检查项目级别设置的 Debug 配置，输出 HTML 报告：**
    ```bash
    python build_settings_checker.py /path/to/MyApp.xcodeproj -c Debug -f html -o report.html
    ```

3.  **检查 \"MyApp\" Target 的 Release 配置，并启用调试模式：**
    ```bash
    python build_settings_checker.py /path/to/MyApp.xcodeproj -t MyApp -d
    ```

## 故障排除

*   **错误：无法通过 xcodebuild 获取构建设置...**:
    *   请确认 Xcode 命令行工具已正确安装并被脚本找到。
    *   尝试手动在终端运行 `xcodebuild -project /path/to/MyApp.xcodeproj -target MyApp -showBuildSettings` 看看是否能成功执行。
    *   检查项目路径和 Target 名称是否正确。
*   **报告中设置值与 Xcode 不符**:
    *   确保检查的 Target 和 Configuration 与你在 Xcode 中查看的一致。
    *   检查项目是否使用了 `.xcconfig` 文件，脚本通过 `xcodebuild` 获取的值会包含 `.xcconfig` 的影响。
