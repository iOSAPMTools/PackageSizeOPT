#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import zipfile
import os
import shutil
import argparse
import pathlib
import tempfile
import json
import datetime
from collections import defaultdict
import re
import html

# --- Constants ---
HISTORY_FILE = "ipa_analysis_history.json"
CHART_JS_CDN = "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js" # Specify a version

# --- Utility Functions ---

def get_size(path):
    """递归计算文件或目录的大小 (bytes)"""
    total_size = 0
    path = pathlib.Path(path) # Ensure it's a Path object
    if not path.exists():
        print(f"警告：路径不存在，无法计算大小: {path}")
        return 0
    if path.is_file():
        total_size = path.stat().st_size
    elif path.is_dir():
        for item in path.rglob('*'):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except FileNotFoundError:
                    print(f"警告：计算大小时文件已消失: {item}")
                    pass # Ignore if file disappears during iteration
    return total_size

def pretty_size(size_bytes):
    """将字节大小转换为易读格式 (KB, MB)"""
    if size_bytes is None: return "N/A"
    if not isinstance(size_bytes, (int, float)) or size_bytes < 0: return "Invalid"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024**2:
        return f"{size_bytes / 1024:.2f} KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes / (1024**2):.2f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"

def infer_version_from_filename(ipa_path):
    """尝试从 IPA 文件名推断版本号 (例如 AppName-1.2.3-b456.ipa)"""
    filename = pathlib.Path(ipa_path).name
    # 尝试匹配 x.y.z 或 x.y 格式，可能带有构建号
    match = re.search(r'(\d+\.\d+(\.\d+)?)(?:[-_b]([a-zA-Z0-9]+))?', filename)
    if match:
        return match.group(0) # 返回匹配到的完整版本字符串
    # 回退：如果找不到特定模式，返回文件名本身（不含扩展名）作为标识
    return filename.rsplit('.', 1)[0]

# --- History Management ---

def load_history():
    """加载历史分析数据"""
    history_path = pathlib.Path(HISTORY_FILE)
    if history_path.exists():
        try:
            with open(history_path, 'r', encoding='utf-8') as f:
                # Load and sort by timestamp descending (most recent first)
                data = json.load(f)
                if isinstance(data, list): # Assuming history is a list of analyses
                    # Sort by timestamp, converting string back to datetime for comparison
                    data.sort(key=lambda x: datetime.datetime.fromisoformat(x.get('analysis_timestamp', '1970-01-01T00:00:00')), reverse=True)
                    return data
                else: # Handle old format or unexpected data
                    print(f"警告: {HISTORY_FILE} 格式不符合预期 (应为列表)，将创建新的历史记录。")
                    return []
        except json.JSONDecodeError:
            print(f"错误：无法解析历史文件 {HISTORY_FILE}。文件可能已损坏。")
            return []
        except Exception as e:
            print(f"加载历史文件时出错: {e}")
            return []
    return []

def save_history(new_analysis_entry):
    """将新的分析条目添加到历史记录并保存"""
    history = load_history()

    # Check if an entry with the same version already exists
    version_exists = False
    for i, entry in enumerate(history):
        if entry.get('version') == new_analysis_entry.get('version'):
            print(f"警告: 版本 '{new_analysis_entry.get('version')}' 的记录已存在，将覆盖旧记录。")
            history[i] = new_analysis_entry
            version_exists = True
            break

    if not version_exists:
        history.append(new_analysis_entry)

    # Sort again before saving
    history.sort(key=lambda x: datetime.datetime.fromisoformat(x.get('analysis_timestamp', '1970-01-01T00:00:00')), reverse=True)

    try:
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        print(f"分析结果已保存到: {HISTORY_FILE}")
    except IOError as e:
        print(f"错误：无法写入历史文件 {HISTORY_FILE}: {e}")
    except Exception as e:
        print(f"保存历史文件时出错: {e}")


# --- IPA Analysis ---

def analyze_app_bundle(app_path):
    """分析 .app 包内容, 返回各部分大小的字典 (与之前类似，但确保路径是字符串)"""
    analysis = {
        "executable": {"size": 0, "path": ""},
        "frameworks": defaultdict(lambda: {"size": 0, "path": ""}),
        "resources_by_ext": defaultdict(lambda: {"size": 0, "count": 0}),
        "resources_lproj": defaultdict(lambda: {"size": 0, "count": 0}),
        "plugins": defaultdict(lambda: {"size": 0, "path": ""}),
        "other": {"size": 0, "count": 0},
        "total_app_size": 0
    }
    app_path = pathlib.Path(app_path)
    if not app_path.exists() or not app_path.is_dir():
         print(f"错误：无效的 .app 路径: {app_path}")
         return analysis # Return empty analysis

    executable_name = app_path.stem

    analysis["total_app_size"] = get_size(app_path)

    for item in app_path.rglob('*'):
        if not item.exists(): continue

        try:
             relative_path = item.relative_to(app_path)
             parts = relative_path.parts
             item_size = get_size(item) if item.is_dir() else item.stat().st_size
        except FileNotFoundError:
             print(f"警告：分析时找不到文件 {item}")
             continue
        except ValueError: # Handles cases where item is not relative (e.g. symlink issues)
             print(f"警告：无法获取相对路径 {item}")
             continue
        except Exception as e:
            print(f"分析文件 {item} 时出错: {e}")
            continue

        is_categorized = False

        # 1. Executable
        if len(parts) == 1 and parts[0] == executable_name and item.is_file():
            analysis["executable"]["size"] = item_size
            analysis["executable"]["path"] = str(relative_path)
            is_categorized = True
            continue

        # 2. Frameworks
        if len(parts) > 1 and parts[0] == "Frameworks" and parts[-1].endswith(".framework"):
            framework_name = parts[-1]
            if framework_name not in analysis["frameworks"]:
                fw_path = app_path / parts[0] / framework_name
                # Ensure we calculate size of the *directory* framework
                analysis["frameworks"][framework_name]["size"] = get_size(fw_path)
                analysis["frameworks"][framework_name]["path"] = str(pathlib.Path(parts[0]) / framework_name)
            # Mark all files/subdirs *within* this framework dir as categorized too
            is_categorized = True

        # 3. Plugins
        if len(parts) > 1 and parts[0] == "PlugIns" and parts[-1].endswith(".appex"):
            plugin_name = parts[-1]
            if plugin_name not in analysis["plugins"]:
                plugin_path = app_path / parts[0] / plugin_name
                analysis["plugins"][plugin_name]["size"] = get_size(plugin_path)
                analysis["plugins"][plugin_name]["path"] = str(pathlib.Path(parts[0]) / plugin_name)
            is_categorized = True


        # 5. Resources by Extension (Files only, not already categorized)
        if item.is_file() and not is_categorized:
            # More comprehensive list? Maybe configurable later.
            res_exts = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.pdf',
                        '.wav', '.mp3', '.aac', '.m4a', '.mp4', '.mov',
                        '.ttf', '.otf', '.plist', '.json', '.xml', '.js', '.css', '.html',
                        '.car', '.nib', '.storyboardc', '.strings', '.stringsdict'}
            ext = item.suffix.lower()
            if ext in res_exts:
                 analysis["resources_by_ext"][ext]["size"] += item_size
                 analysis["resources_by_ext"][ext]["count"] += 1
                 is_categorized = True

        # 6. Resources by Lproj (Check if within *.lproj dir, not categorized)
        lproj_part_index = -1
        for i, part in enumerate(parts):
            if part.endswith(".lproj"):
                lproj_part_index = i
                break
        if lproj_part_index != -1 and not is_categorized:
             lproj_name = parts[lproj_part_index]
             # We want to sum files *inside* lproj dirs, not the dir itself initially
             if item.is_file(): # Only sum file sizes within .lproj
                 analysis["resources_lproj"][lproj_name]["size"] += item_size
                 analysis["resources_lproj"][lproj_name]["count"] += 1
             is_categorized = True # Mark anything inside .lproj as categorized


        # 7. Other (Files not categorized)
        if item.is_file() and not is_categorized:
            analysis["other"]["size"] += item_size
            analysis["other"]["count"] += 1

    # Convert defaultdicts
    analysis["frameworks"] = dict(analysis["frameworks"])
    analysis["resources_by_ext"] = dict(analysis["resources_by_ext"])
    analysis["resources_lproj"] = dict(analysis["resources_lproj"])
    analysis["plugins"] = dict(analysis["plugins"])

    return analysis

def analyze_ipa(ipa_path):
    """解压并分析 IPA，返回包含元数据和分析结果的字典"""
    ipa_path_obj = pathlib.Path(ipa_path)
    if not ipa_path_obj.is_file():
        raise FileNotFoundError(f"IPA 文件未找到: {ipa_path}")

    analysis_result = {
        "ipa_path": str(ipa_path),
        "ipa_size": ipa_path_obj.stat().st_size,
        "app_bundle_analysis": {},
        "swift_support": {"size": 0},
        "symbols": {"size": 0}
    }

    with tempfile.TemporaryDirectory(prefix="ipa_analyzer_") as temp_dir:
        temp_dir_path = pathlib.Path(temp_dir)
        print(f"正在解压 IPA: {ipa_path} 到 {temp_dir_path}")
        try:
            with zipfile.ZipFile(ipa_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir_path)
        except zipfile.BadZipFile:
            raise ValueError(f"无法解压文件，可能不是有效的 IPA/ZIP: {ipa_path}")
        except Exception as e:
            raise RuntimeError(f"解压 IPA 时出错: {e}")

        # Find .app bundle
        payload_dir = temp_dir_path / "Payload"
        app_bundle_list = list(payload_dir.glob("*.app"))
        if not app_bundle_list:
            raise FileNotFoundError(f"在 {payload_dir} 中找不到 .app 包")
        app_path = app_bundle_list[0]

        print(f"正在分析 App Bundle: {app_path.name}")
        analysis_result["app_bundle_analysis"] = analyze_app_bundle(app_path)

        # Analyze SwiftSupport (Improved Path)
        swift_support_path = temp_dir_path / "SwiftSupport"
        if swift_support_path.exists() and swift_support_path.is_dir():
            analysis_result["swift_support"]["size"] = get_size(swift_support_path)
            print(f"已分析 SwiftSupport 目录大小: {pretty_size(analysis_result['swift_support']['size'])}")

        # Analyze Symbols directory
        symbols_path = temp_dir_path / "Symbols"
        if symbols_path.exists() and symbols_path.is_dir():
            analysis_result["symbols"]["size"] = get_size(symbols_path)
            print(f"已分析 Symbols 目录大小: {pretty_size(analysis_result['symbols']['size'])}")

    return analysis_result


# --- HTML Report Generation ---

def _html_css():
    # Basic styling for the report
    return """
<style>
    body { font-family: sans-serif; margin: 20px; background-color: #f4f4f4; }
    h1, h2, h3 { color: #333; border-bottom: 1px solid #ccc; padding-bottom: 5px; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 20px; background-color: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
    th { background-color: #e9e9e9; font-weight: bold; }
    tr:nth-child(even) { background-color: #f9f9f9; }
    .diff-positive { color: #c00; font-weight: bold; } /* Red for increase */
    .diff-negative { color: #080; font-weight: bold; } /* Green for decrease */
    .percent-increase { color: #c00; font-weight: bold; }
    .percent-decrease { color: #080; font-weight: bold; }
    .chart-container { width: 90%; max-width: 800px; margin: 20px auto; background-color: #fff; padding: 15px; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .summary { background-color: #fff; padding: 15px; margin-bottom: 20px; border-radius: 5px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .summary p { margin: 5px 0; }
    code { background-color: #eee; padding: 2px 4px; border-radius: 3px; }
    .subtle { color: #777; font-size: 0.9em; }
</style>
"""

def _html_table_row(label, value_curr, value_prev, count_curr=None, count_prev=None, is_size=True):
    """Generates an HTML table row for comparison, handling None values."""
    val_c_str = pretty_size(value_curr) if is_size else (f"{value_curr:,}" if value_curr is not None else "N/A")
    val_p_str = pretty_size(value_prev) if is_size else (f"{value_prev:,}" if value_prev is not None else "N/A")

    diff_str = "N/A"
    diff_class = ""
    percent_str = "-"
    percent_class = ""

    # Ensure values are numeric for calculation, treat None as 0 for diff if the other exists
    calc_curr = value_curr if value_curr is not None else 0
    calc_prev = value_prev if value_prev is not None else 0

    if value_curr is not None and value_prev is not None:
        diff = calc_curr - calc_prev
        diff_str = pretty_size(diff) if is_size else f"{diff:+,}"
        if diff > 0: diff_class = "diff-positive"
        elif diff < 0: diff_class = "diff-negative"

        if calc_prev > 0:
            percent_diff = (diff / calc_prev) * 100
            percent_str = f"{percent_diff:+.2f}%"
            if percent_diff > 1: percent_class = "percent-increase" # Highlight > 1% change
            elif percent_diff < -1: percent_class = "percent-decrease"
    elif value_curr is not None: # Only current exists (new item)
        diff_str = val_c_str
        diff_class = "diff-positive"
        percent_str = "New"
        percent_class = "percent-increase"
    elif value_prev is not None: # Only previous exists (removed item)
        diff_str = f"-{val_p_str}"
        diff_class = "diff-negative"
        percent_str = "Removed"
        percent_class = "percent-decrease"

    count_c_str = f"{count_curr:,}" if count_curr is not None else "-"
    count_p_str = f"{count_prev:,}" if count_prev is not None else "-"
    count_diff_str = ""
    if count_curr is not None and count_prev is not None:
         count_diff = count_curr - count_prev
         count_diff_str = f" ({count_diff:+,})"

    label_display = html.escape(label)
    if not is_size: # Add file count info if counts are provided and it's not a size row
        if count_curr is not None or count_prev is not None:
             label_display += f" <span class='subtle'>({count_c_str} / {count_p_str} files{count_diff_str})</span>"

    return f"""
    <tr>
        <td>{label_display}</td>
        <td>{val_c_str}</td>
        <td>{val_p_str}</td>
        <td class='{diff_class}'>{diff_str}</td>
        <td class='{percent_class}'>{percent_str}</td>
    </tr>"""

def _generate_comparison_html(analysis_curr, analysis_prev, output_path):
    """Generates comparison HTML report for two analyses"""
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>IPA 大小对比报告</title>
    <script src="{CHART_JS_CDN}"></script>
    {_html_css()}
</head>
<body>
    <h1>IPA 大小对比报告</h1>

    <div class="summary">
        <p><strong>当前 IPA:</strong> <code>{html.escape(analysis_curr.get('ipa_path', 'N/A'))}</code></p>
        <p><strong>先前 IPA:</strong> <code>{html.escape(analysis_prev.get('ipa_path', 'N/A'))}</code></p>
        <p><strong>当前版本:</strong> {html.escape(analysis_curr.get('version', 'N/A'))}</p>
        <p><strong>先前版本:</strong> {html.escape(analysis_prev.get('version', 'N/A'))}</p>
        <p><strong>报告生成时间:</strong> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>

    <h2>总体大小对比</h2>
    <table>
        <thead>
            <tr><th>组件</th><th>当前大小</th><th>先前大小</th><th>差异</th><th>变化 (%)</th></tr>
        </thead>
        <tbody>
            {_html_table_row("Total IPA", analysis_curr.get('ipa_size'), analysis_prev.get('ipa_size'))}
            {_html_table_row("Payload/.app Bundle", analysis_curr.get('app_bundle_analysis', {}).get('total_app_size'), analysis_prev.get('app_bundle_analysis', {}).get('total_app_size'))}
            {_html_table_row("SwiftSupport", analysis_curr.get('swift_support', {}).get('size'), analysis_prev.get('swift_support', {}).get('size'))}
            {_html_table_row("Symbols", analysis_curr.get('symbols', {}).get('size'), analysis_prev.get('symbols', {}).get('size'))}
        </tbody>
    </table>

    <h2>App Bundle 分解对比 (.app)</h2>
    <div class="chart-container">
        <canvas id="appBundleChart"></canvas>
    </div>
    <table>
        <thead>
            <tr><th>组件 / 分类</th><th>当前大小</th><th>先前大小</th><th>差异</th><th>变化 (%)</th></tr>
        </thead>
        <tbody>
"""
    # App Bundle Components
    app_curr = analysis_curr.get('app_bundle_analysis', {})
    app_prev = analysis_prev.get('app_bundle_analysis', {})
    exe_curr = app_curr.get('executable', {})
    exe_prev = app_prev.get('executable', {})
    other_curr = app_curr.get("other", {})
    other_prev = app_prev.get("other", {})

    html_content += _html_table_row(f"Executable (`{html.escape(exe_curr.get('path','N/A'))}`)", exe_curr.get('size'), exe_prev.get('size'))

    # Totals for categories
    fw_total_curr = sum(f.get('size', 0) for f in app_curr.get("frameworks", {}).values())
    fw_total_prev = sum(f.get('size', 0) for f in app_prev.get("frameworks", {}).values())
    html_content += _html_table_row("Frameworks (Total)", fw_total_curr, fw_total_prev)

    pl_total_curr = sum(p.get('size', 0) for p in app_curr.get("plugins", {}).values())
    pl_total_prev = sum(p.get('size', 0) for p in app_prev.get("plugins", {}).values())
    html_content += _html_table_row("PlugIns (Total)", pl_total_curr, pl_total_prev)

    res_ext_total_curr = sum(r.get('size', 0) for r in app_curr.get("resources_by_ext", {}).values())
    res_ext_total_prev = sum(r.get('size', 0) for r in app_prev.get("resources_by_ext", {}).values())
    res_ext_count_curr = sum(r.get('count', 0) for r in app_curr.get("resources_by_ext", {}).values())
    res_ext_count_prev = sum(r.get('count', 0) for r in app_prev.get("resources_by_ext", {}).values())
    html_content += _html_table_row("Resources by Ext (Total)", res_ext_total_curr, res_ext_total_prev, res_ext_count_curr, res_ext_count_prev, is_size=False) # Use label for count

    res_lproj_total_curr = sum(r.get('size', 0) for r in app_curr.get("resources_lproj", {}).values())
    res_lproj_total_prev = sum(r.get('size', 0) for r in app_prev.get("resources_lproj", {}).values())
    res_lproj_count_curr = sum(r.get('count', 0) for r in app_curr.get("resources_lproj", {}).values())
    res_lproj_count_prev = sum(r.get('count', 0) for r in app_prev.get("resources_lproj", {}).values())
    html_content += _html_table_row("Resources .lproj (Total)", res_lproj_total_curr, res_lproj_total_prev, res_lproj_count_curr, res_lproj_count_prev, is_size=False)

    html_content += _html_table_row("Other Files", other_curr.get('size', 0), other_prev.get('size', 0), other_curr.get('count', 0), other_prev.get('count', 0), is_size=False)

    html_content += "</tbody></table>"

    # --- Detailed Sections ---
    details_map = {
        "Frameworks": "frameworks",
        "PlugIns": "plugins",
        "Resources by Extension": "resources_by_ext",
        "Resources by Localization (.lproj)": "resources_lproj",
    }

    for title, key in details_map.items():
        all_detail_keys = set(app_curr.get(key, {}).keys()) | set(app_prev.get(key, {}).keys())
        if all_detail_keys:
            html_content += f"<h3>{title} Detail</h3><table><thead><tr><th>名称</th><th>当前大小</th><th>先前大小</th><th>差异</th><th>变化 (%)</th></tr></thead><tbody>"
            for item_key in sorted(list(all_detail_keys)):
                item_curr = app_curr.get(key, {}).get(item_key, {})
                item_prev = app_prev.get(key, {}).get(item_key, {})
                count_curr = item_curr.get('count') # Will be None for frameworks/plugins
                count_prev = item_prev.get('count')
                # For resources, label includes counts, for others it's just the key
                is_size_row = key in ["frameworks", "plugins"]
                html_content += _html_table_row(f"`{html.escape(item_key)}`", item_curr.get('size'), item_prev.get('size'), count_curr, count_prev, is_size=is_size_row)
            html_content += "</tbody></table>"


    # --- Chart.js Script ---
    chart_labels = ["Executable", "Frameworks", "PlugIns", "Resources (Ext)", "Resources (Lproj)", "Other"]
    chart_data_curr = [
        exe_curr.get('size', 0),
        fw_total_curr,
        pl_total_curr,
        res_ext_total_curr,
        res_lproj_total_curr,
        other_curr.get('size', 0)
    ]
    chart_data_prev = [
        exe_prev.get('size', 0),
        fw_total_prev,
        pl_total_prev,
        res_ext_total_prev,
        res_lproj_total_prev,
        other_prev.get('size', 0)
    ]

    html_content += f"""
    <script>
        const ctx = document.getElementById('appBundleChart').getContext('2d');
        new Chart(ctx, {{
            type: 'bar', // Use bar chart for comparison
            data: {{
                labels: {json.dumps(chart_labels)},
                datasets: [
                {{
                    label: '当前版本 ({html.escape(analysis_curr.get('version', 'Current'))})',
                    data: {json.dumps(chart_data_curr)},
                    backgroundColor: 'rgba(54, 162, 235, 0.6)', // Blue
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }},
                {{
                    label: '先前版本 ({html.escape(analysis_prev.get('version', 'Previous'))})',
                    data: {json.dumps(chart_data_prev)},
                    backgroundColor: 'rgba(255, 99, 132, 0.6)', // Red
                    borderColor: 'rgba(255, 99, 132, 1)',
                    borderWidth: 1
                }}
              ]
            }},
            options: {{
                indexAxis: 'y', // Horizontal bars might be better if many categories
                scales: {{
                    x: {{
                        beginAtZero: true,
                        title: {{ display: true, text: '大小 (Bytes)' }},
                        ticks: {{ // Optional: Format ticks to KB/MB if needed (more complex JS)
                             callback: function(value, index, values) {{
                                if (value < 1024) return value + ' B';
                                if (value < 1024**2) return (value / 1024).toFixed(1) + ' KB';
                                return (value / (1024**2)).toFixed(1) + ' MB';
                            }}
                        }}
                    }},
                    y: {{
                         title: {{ display: true, text: '组件分类' }}
                    }}
                }},
                plugins: {{
                    title: {{ display: true, text: '.app 包主要组件大小对比' }},
                    tooltip: {{ callbacks: {{ // Format tooltip values
                        label: function(context) {{
                            let label = context.dataset.label || '';
                            if (label) {{ label += ': '; }}
                            let value = context.raw;
                             if (value < 1024) label += value + ' B';
                             else if (value < 1024**2) label += (value / 1024).toFixed(2) + ' KB';
                             else label += (value / (1024**2)).toFixed(2) + ' MB';
                            return label;
                        }}
                    }} }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"对比报告已生成: {output_path}")
    except IOError as e:
        print(f"错误：无法写入报告文件 {output_path}: {e}")

def _generate_history_html(history_data, output_path):
    """Generates HTML report showing historical trends"""
    if not history_data:
        print("没有历史数据可生成报告。")
        # Create a minimal HTML file indicating no data
        html_content = f"""
<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>IPA 历史大小报告</title>{_html_css()}</head>
<body><h1>IPA 历史大小报告</h1><p>没有找到历史分析数据 ({HISTORY_FILE})。</p></body></html>"""
        try:
            with open(output_path, "w", encoding="utf-8") as f: f.write(html_content)
            print(f"空的报告已生成: {output_path}")
        except IOError as e: print(f"错误：无法写入空的报告文件 {output_path}: {e}")
        return

    # Prepare data for charts (reverse history for chronological order in charts)
    history_data.sort(key=lambda x: datetime.datetime.fromisoformat(x.get('analysis_timestamp', '1970-01-01T00:00:00'))) # Sort oldest first for charts

    versions = [entry.get('version', f"Unknown_{i}") for i, entry in enumerate(history_data)]
    ipa_sizes = [entry.get('ipa_size') for entry in history_data]
    app_sizes = [entry.get('app_bundle_analysis', {}).get('total_app_size') for entry in history_data]
    exec_sizes = [entry.get('app_bundle_analysis', {}).get('executable', {}).get('size') for entry in history_data]
    fw_sizes = [sum(f.get('size', 0) for f in entry.get('app_bundle_analysis', {}).get("frameworks", {}).values()) for entry in history_data]
    swift_sizes = [entry.get('swift_support', {}).get('size', 0) for entry in history_data] # SwiftSupport size
    symbols_sizes = [entry.get('symbols', {}).get('size', 0) for entry in history_data] # Checklist item 8: Prepare symbols_sizes list

    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>IPA 历史大小报告</title>
    <script src="{CHART_JS_CDN}"></script>
    {_html_css()}
</head>
<body>
    <h1>IPA 历史大小报告</h1>
    <p>数据来源: <code>{HISTORY_FILE}</code></p>
    <p>报告生成时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

    <h2>大小趋势</h2>
    <div class="chart-container">
        <canvas id="sizeTrendChart"></canvas>
    </div>

    <h2>最新版本分析 ({html.escape(versions[-1] if versions else 'N/A')})</h2>
"""
    # Display table for the latest version's analysis (similar to comparison but only one column)
    latest_analysis = history_data[-1] if history_data else {}
    latest_app = latest_analysis.get('app_bundle_analysis', {})

    html_content += "<table><thead><tr><th>组件 / 分类</th><th>大小</th><th>文件数 (如果适用)</th></tr></thead><tbody>"
    html_content += f"<tr><td>Total IPA</td><td>{pretty_size(latest_analysis.get('ipa_size'))}</td><td>-</td></tr>"
    html_content += f"<tr><td>Payload/.app Bundle</td><td>{pretty_size(latest_app.get('total_app_size'))}</td><td>-</td></tr>"
    html_content += f"<tr><td>SwiftSupport</td><td>{pretty_size(latest_analysis.get('swift_support',{}).get('size'))}</td><td>-</td></tr>"
    html_content += f"<tr><td>Symbols</td><td>{pretty_size(latest_analysis.get('symbols',{}).get('size'))}</td><td>-</td></tr>" # Checklist item 7: Add Symbols row to latest version table
    html_content += f"<tr><td>Executable (`{html.escape(latest_app.get('executable',{}).get('path','N/A'))}`)</td><td>{pretty_size(latest_app.get('executable',{}).get('size'))}</td><td>-</td></tr>"
    # Add rows for Frameworks (Total), Plugins (Total), Resources (Total), Other
    fw_total = sum(f.get('size', 0) for f in latest_app.get("frameworks", {}).values())
    html_content += f"<tr><td>Frameworks (Total)</td><td>{pretty_size(fw_total)}</td><td>{len(latest_app.get('frameworks', {}))}</td></tr>"
    pl_total = sum(p.get('size', 0) for p in latest_app.get("plugins", {}).values())
    html_content += f"<tr><td>PlugIns (Total)</td><td>{pretty_size(pl_total)}</td><td>{len(latest_app.get('plugins', {}))}</td></tr>"
    res_ext_total = sum(r.get('size', 0) for r in latest_app.get("resources_by_ext", {}).values())
    res_ext_count = sum(r.get('count', 0) for r in latest_app.get("resources_by_ext", {}).values())
    html_content += f"<tr><td>Resources by Ext (Total)</td><td>{pretty_size(res_ext_total)}</td><td>{res_ext_count:,}</td></tr>"
    res_lproj_total = sum(r.get('size', 0) for r in latest_app.get("resources_lproj", {}).values())
    res_lproj_count = sum(r.get('count', 0) for r in latest_app.get("resources_lproj", {}).values())
    html_content += f"<tr><td>Resources .lproj (Total)</td><td>{pretty_size(res_lproj_total)}</td><td>{res_lproj_count:,}</td></tr>"
    other = latest_app.get("other", {})
    html_content += f"<tr><td>Other Files</td><td>{pretty_size(other.get('size', 0))}</td><td>{other.get('count', 0):,}</td></tr>"
    html_content += "</tbody></table>"

    # Add detailed tables for latest version (optional, can reuse logic from comparison)

    # --- Chart.js Script for History ---
    html_content += f"""
    <script>
        const ctxTrend = document.getElementById('sizeTrendChart').getContext('2d');
        new Chart(ctxTrend, {{
            type: 'line',
            data: {{
                labels: {json.dumps(versions)},
                datasets: [
                {{
                    label: 'Total IPA Size',
                    data: {json.dumps(ipa_sizes)},
                    borderColor: 'rgb(75, 192, 192)', // Teal
                    tension: 0.1,
                    fill: false
                }},
                {{
                    label: '.app Bundle Size',
                    data: {json.dumps(app_sizes)},
                    borderColor: 'rgb(54, 162, 235)', // Blue
                    tension: 0.1,
                     fill: false
                }},
                 {{
                    label: 'Executable Size',
                    data: {json.dumps(exec_sizes)},
                    borderColor: 'rgb(255, 99, 132)', // Red
                    tension: 0.1,
                    fill: false
                }},
                 {{
                    label: 'Frameworks Size',
                    data: {json.dumps(fw_sizes)},
                    borderColor: 'rgb(255, 159, 64)', // Orange
                    tension: 0.1,
                    fill: false
                }},
                 {{
                    label: 'SwiftSupport Size',
                    data: {json.dumps(swift_sizes)},
                    borderColor: 'rgb(153, 102, 255)', // Purple
                    tension: 0.1,
                    fill: false,
                    hidden: true // Hide by default as it might be 0 often
                }},
                 {{
                    label: 'Symbols Size',
                    data: {json.dumps(symbols_sizes)},
                    borderColor: 'rgb(201, 203, 207)', // Grey
                    tension: 0.1,
                    fill: false,
                    hidden: true // Hide by default
                }}
              ]
            }},
            options: {{
                scales: {{
                    y: {{
                        beginAtZero: true,
                         title: {{ display: true, text: '大小 (Bytes)' }},
                         ticks: {{ callback: function(value) {{ // Format Y-axis ticks
                             if (value < 1024) return value + ' B';
                             if (value < 1024**2) return (value / 1024).toFixed(1) + ' KB';
                             return (value / (1024**2)).toFixed(1) + ' MB';
                         }} }}
                    }},
                     x: {{
                         title: {{ display: true, text: '版本 / 时间' }}
                     }}
                }},
                plugins: {{
                    title: {{ display: true, text: 'IPA 组件大小历史趋势' }},
                    tooltip: {{ callbacks: {{ label: function(context) {{ // Format tooltip
                        let label = context.dataset.label || '';
                        if (label) {{ label += ': '; }}
                        let value = context.raw;
                        if (value < 1024) label += value + ' B';
                        else if (value < 1024**2) label += (value / 1024).toFixed(2) + ' KB';
                        else label += (value / (1024**2)).toFixed(2) + ' MB';
                        return label;
                    }} }} }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    # Write to file
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"历史报告已生成: {output_path}")
    except IOError as e:
        print(f"错误：无法写入报告文件 {output_path}: {e}")

def generate_html_report(mode, output_path, **kwargs):
    """主函数，根据模式调用不同的 HTML 生成器"""
    if mode == 'compare':
        _generate_comparison_html(kwargs['analysis_curr'], kwargs['analysis_prev'], output_path)
    elif mode == 'history':
        _generate_history_html(kwargs['history_data'], output_path)
    # Add mode for single analysis report if needed
    # elif mode == 'single':
    #     _generate_single_analysis_html(kwargs['analysis_data'], output_path)
    else:
        print(f"错误：不支持的报告模式 '{mode}'")


# --- Main Execution ---

def main():
    # Format the epilog string first
    epilog_text = """
示例:
  分析并存储版本:
    %(prog)s --analyze MyApp-1.0.ipa --version 1.0 --output report_1.0.html

  对比两个特定 IPA:
    %(prog)s --compare MyApp-1.1.ipa MyApp-1.0.ipa --output comparison_1.1_vs_1.0.html

  生成历史趋势报告 (从 {history_file}):
    %(prog)s --history --output history_report.html
""".format(history_file=HISTORY_FILE) # Use .format() for clarity

    parser = argparse.ArgumentParser(
        description="分析 iOS IPA 文件大小构成，生成可视化 HTML 对比或历史报告。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog_text # Pass the pre-formatted string
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--analyze", metavar="IPA_PATH",
                       help="分析单个 IPA 文件并将其结果添加到历史记录 (%(history_file)s)。")
    group.add_argument("--compare", nargs=2, metavar=('CURRENT_IPA', 'PREVIOUS_IPA'),
                       help="对比指定的两个 IPA 文件。")
    group.add_argument("--history", action="store_true",
                       help=f"加载 '{HISTORY_FILE}' 中的所有历史数据并生成趋势报告。")

    parser.add_argument("--version",
                        help="为 --analyze 模式指定版本号 (如果省略，将尝试从文件名推断)。")
    parser.add_argument("--output", default="ipa_report.html",
                        help="输出 HTML 报告的文件路径 (默认: ipa_report.html)。")

    args = parser.parse_args()

    try:
        if args.analyze:
            ipa_path = args.analyze
            version = args.version if args.version else infer_version_from_filename(ipa_path)
            print(f"开始分析 IPA: {ipa_path} (版本: {version})")

            analysis_data = analyze_ipa(ipa_path)
            analysis_entry = {
                "version": version,
                "ipa_path": analysis_data["ipa_path"],
                "ipa_size": analysis_data["ipa_size"],
                "analysis_timestamp": datetime.datetime.now().isoformat(),
                "app_bundle_analysis": analysis_data["app_bundle_analysis"],
                "swift_support": analysis_data["swift_support"],
                "symbols": analysis_data["symbols"]
            }
            save_history(analysis_entry)
            # Optionally generate a simple report for this single analysis
            # generate_html_report('single', args.output, analysis_data=analysis_entry)
            print("分析完成并已记录。")

        elif args.compare:
            current_ipa_path, previous_ipa_path = args.compare
            print(f"开始对比 IPA: {current_ipa_path} vs {previous_ipa_path}")

            analysis_curr = analyze_ipa(current_ipa_path)
            analysis_prev = analyze_ipa(previous_ipa_path)

            # Add version info inferred from filename for the report title
            analysis_curr['version'] = infer_version_from_filename(current_ipa_path)
            analysis_prev['version'] = infer_version_from_filename(previous_ipa_path)


            generate_html_report('compare', args.output,
                                 analysis_curr=analysis_curr,
                                 analysis_prev=analysis_prev)

        elif args.history:
            print(f"加载历史数据从: {HISTORY_FILE}")
            history_data = load_history()
            if not history_data:
                 print(f"未找到历史数据或文件 '{HISTORY_FILE}' 为空/无效。")
                 # generate_html_report will handle empty data case
            generate_html_report('history', args.output, history_data=history_data)

    except FileNotFoundError as e:
        print(f"错误: {e}")
        exit(1)
    except ValueError as e: # Catch specific errors like bad zip
        print(f"错误: {e}")
        exit(1)
    except RuntimeError as e: # Catch other runtime issues from analysis
        print(f"运行时错误: {e}")
        exit(1)
    except Exception as e:
        print(f"发生未知错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()