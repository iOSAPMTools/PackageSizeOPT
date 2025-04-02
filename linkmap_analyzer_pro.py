# 分析linkmap中的 # Sections: 段 和 # Symbols: 段，给出分析报告

import sys
import argparse
import re
import os
import json
import csv
from collections import defaultdict
from datetime import datetime

def parse_linkmap(filepath):
    """解析 Link Map 文件，提取 Sections 和 Symbols 信息。"""
    print(f"正在解析文件: {filepath}")
    sections = {}
    symbols = []
    object_files = {}  # 存储对象文件信息
    
    # 直接读取整个文件进行处理
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    # 处理换行符统一，然后分割为行
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    lines = content.split('\n')
    print(f"文件读取成功，共 {len(lines)} 行")

    # 查找各个段落的起始位置
    object_files_start = -1
    sections_start = -1
    symbols_start = -1
    
    for i, line in enumerate(lines):
        if line.strip() == '# Object files:':
            object_files_start = i
        elif line.strip() == '# Sections:':
            sections_start = i
        elif line.strip() == '# Symbols:':
            symbols_start = i
            
    # 解析 Object files 段落
    if object_files_start != -1:
        i = object_files_start + 1  # 跳过标题行
        while i < len(lines) and not lines[i].startswith('# '):
            line = lines[i].strip()
            if line and '[' in line and ']' in line:
                try:
                    # 格式: [  5] 文件路径
                    match = re.match(r'\[\s*(\d+)\]\s+(.*)', line)
                    if match:
                        file_index = int(match.group(1))
                        file_path = match.group(2).strip()
                        object_files[file_index] = file_path
                except Exception:
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(object_files)} 个 Object files")
    
    # 解析 Sections 段落
    if sections_start != -1:
        i = sections_start + 1  # 跳过标题行
        # 跳过表头行
        while i < len(lines) and lines[i].startswith('#'):
            i += 1
            
        # 开始解析数据行
        while i < len(lines) and not lines[i].startswith('# '):
            line = lines[i].strip()
            if line:
                try:
                    parts = line.split()
                    if len(parts) >= 4 and parts[0].startswith('0x'):
                        addr = parts[0]
                        size_str = parts[1]
                        size = int(size_str.replace('0x', ''), 16)
                        segment = parts[2]
                        section = parts[3]
                        sections[addr] = {
                            'size': size, 
                            'segment': segment, 
                            'section': section
                        }
                except Exception:
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(sections)} 个 Sections")
    
    # 解析 Symbols 段落
    if symbols_start != -1:
        i = symbols_start + 1  # 跳过标题行
        # 跳过表头行
        while i < len(lines) and lines[i].startswith('#'):
            i += 1
            
        # 开始解析数据行
        while i < len(lines) and not lines[i].startswith('# '):
            line = lines[i].strip()
            if line and line.startswith('0x'):
                try:
                    # 尝试解析行: 0x100004000 0x00000084 [  5] _$s8WoodyIOS...
                    match = re.match(r'(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+\[\s*(\d+)\](.*)', line)
                    if match:
                        addr = match.group(1)
                        size_str = match.group(2)
                        file_index = int(match.group(3))
                        name = match.group(4).strip() if len(match.groups()) > 3 else ""
                        
                        size = int(size_str.replace('0x', ''), 16)
                        symbols.append({
                            'address': addr,
                            'size': size,
                            'file_index': file_index,
                            'name': name
                        })
                except Exception:
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(symbols)} 个 Symbols")
    
    return sections, symbols, object_files

def analyze_symbols(symbols, object_files=None):
    """分析 Symbols，按文件聚合大小。"""
    size_by_file = defaultdict(int)
    
    for symbol in symbols:
        file_index = symbol['file_index']
        file_id = object_files.get(file_index, f"文件索引 {file_index}") if object_files else f"文件索引 {file_index}"
        size_by_file[file_id] += symbol['size']

    # 按大小排序
    sorted_size_by_file = sorted(size_by_file.items(), key=lambda item: item[1], reverse=True)
    return sorted_size_by_file

def analyze_symbols_by_library(symbols, object_files=None):
    """分析 Symbols，按库/模块聚合大小。"""
    size_by_library = defaultdict(int)
    library_files = defaultdict(list)
    
    for symbol in symbols:
        file_index = symbol['file_index']
        file_path = object_files.get(file_index, f"文件索引 {file_index}") if object_files else f"文件索引 {file_index}"
        
        # 提取库名
        library_name = extract_library_name(file_path)
        size_by_library[library_name] += symbol['size']
        
        # 记录该库包含的文件
        if file_path not in library_files[library_name]:
            library_files[library_name].append(file_path)

    # 按大小排序
    sorted_size_by_library = sorted(
        [(lib, size, library_files[lib]) for lib, size in size_by_library.items()],
        key=lambda item: item[1],
        reverse=True
    )
    return sorted_size_by_library

def extract_library_name(file_path):
    """从文件路径中提取库/模块名称。"""
    if not file_path:
        return "未知"
        
    # 处理常见的库格式
    if ".a[" in file_path:  # 静态库格式: libXXX.a[...]
        lib_match = re.search(r'lib([^/.]+)\.a', file_path)
        if lib_match:
            return lib_match.group(1)
            
    elif ".framework/" in file_path:  # 框架格式
        framework_match = re.search(r'([^/]+)\.framework', file_path)
        if framework_match:
            return framework_match.group(1)
            
    elif "[arm64][" in file_path:  # 特殊格式SDK
        sdk_match = re.search(r'([^\[/]+)\[arm64\]', file_path)
        if sdk_match:
            return sdk_match.group(1)
            
    # 处理一般对象文件
    filename = os.path.basename(file_path)
    # 如果是某些特殊文件，直接返回
    if filename.startswith("objc-") or filename == "crt1.o":
        return filename
        
    # 取前缀作为模块名
    parts = filename.split('_')
    prefix = parts[0]
    if prefix.startswith("WD") and len(prefix) > 2:  # 项目自己的模块
        return prefix
        
    # 如果无法识别特定格式，从路径第一级目录推断
    path_parts = file_path.split('/')
    if len(path_parts) > 1 and path_parts[0]:
        return path_parts[0]
        
    return "其它"

def format_size(size_bytes):
    """格式化文件大小显示，自动选择合适的单位。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024*1024:
        return f"{size_bytes/1024:.2f} KB"
    else:
        return f"{size_bytes/(1024*1024):.2f} MB"

def generate_report(sections, symbols_analysis, library_analysis):
    """生成分析报告。"""
    report = []
    report.append("--- Link Map 分析报告 ---")
    report.append("")

    # 计算总大小
    total_section_size = sum(s['size'] for s in sections.values())
    total_symbol_size = sum(size for _, size in symbols_analysis)
    
    # 摘要信息
    report.append("## 摘要:")
    report.append(f"总大小: {format_size(total_section_size)}")
    report.append(f"符号总大小: {format_size(total_symbol_size)}")
    report.append(f"符号数量: {len(symbols_analysis)} 个文件")
    report.append("")

    # Sections Summary
    report.append("## Sections 分析:")
    
    # 按 Segment/Section 聚合大小
    size_by_segment = defaultdict(int)
    section_details = defaultdict(list)
    
    for addr, section in sections.items():
        segment = section['segment']
        size_by_segment[segment] += section['size']
        section_details[segment].append((section['section'], section['size']))
    
    for segment, size in sorted(size_by_segment.items(), key=lambda x: x[1], reverse=True):
        percentage = size / total_section_size * 100 if total_section_size > 0 else 0
        report.append(f"  {segment}: {format_size(size)} ({percentage:.1f}%)")
        
        # 添加该段内各节的详细信息
        section_info = section_details[segment]
        section_info.sort(key=lambda x: x[1], reverse=True)
        # 只显示最大的3个节
        for section_name, section_size in section_info[:3]:
            section_percentage = section_size / size * 100
            report.append(f"    - {section_name}: {format_size(section_size)} ({section_percentage:.1f}%)")

    report.append("")
    
    # 按库聚合分析
    report.append("## 按库/模块聚合分析 (Top 15):")
    report.append("-" * 80)
    report.append(f"{'库名':<20} {'大小':<10} {'占比':<8} {'文件数':<8}")
    report.append("-" * 80)
    
    for i, (lib_name, size, files) in enumerate(library_analysis):
        if i >= 15:  # 只显示前15个
            break
            
        percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
        report.append(f"{lib_name:<20} {format_size(size):<10} {percentage:.1f}% {len(files):<6}")
    
    report.append("")

    # Symbols Summary by File
    report.append("## 文件大小分析 (Top 20):")
    report.append("-" * 80)
    
    # 计算文件名最大长度以对齐
    max_name_length = min(60, max([len(file_id.split('/')[-1]) for file_id, _ in symbols_analysis[:20]] + [20]))
    
    # 表头
    report.append(f"{'文件名':<{max_name_length}} {'大小':<10} {'占比':<10}")
    report.append("-" * 80)
    
    for i, (file_id, size) in enumerate(symbols_analysis):
        if i >= 20:  # 只显示前20个
            break
        
        # 获取简化文件名（去除路径）
        simple_name = file_id.split('/')[-1]
        if len(simple_name) > max_name_length:
            simple_name = simple_name[:max_name_length-3] + "..."
            
        percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
        report.append(f"{simple_name:<{max_name_length}} {format_size(size):<10} {percentage:.1f}%")

    report.append("")
    
    # 添加优化建议
    report.append("## 优化建议")
    report.append("")
    
    # 1. 检查未使用代码和重复代码
    report.append("### 1. 未使用代码和重复代码检查")
    report.append("- 原因：未使用代码增加包体积、编译时间和维护成本；重复代码导致维护困难、易出错")
    report.append("- 检测工具：")
    report.append("  - Periphery (Swift推荐)：`brew install peripheryapp/periphery/periphery`")
    report.append("  - Xcode代码覆盖率：运行测试并开启覆盖率，检查0%覆盖的代码区域")
    report.append("  - 静态分析器：SwiftLint/OCLint 配置相关规则")
    report.append("- 处理建议：")
    report.append("  - 确认无用后，安全移除未使用代码")
    report.append("  - 提取重复代码为公共函数/类")
    report.append("")
    
    # 2. 静态库链接优化
    report.append("### 2. 静态库链接优化")
    report.append("- 原因：静态库会将所有目标文件(.o)链接进主二进制，即使只用到部分功能")
    report.append("- 检查方法：")
    report.append("  - 分析本报告：查看体积大的库及其关联的`.o`文件，判断功能是否必需")
    report.append("  - 查阅库文档：看是否有裁剪功能的配置选项")
    report.append("  - 命令行检查：`ar -t <lib.a>` 列出.o文件，`nm -m <lib.a> | c++filt` 列出符号")
    report.append("- 处理建议：")
    report.append("  - 配置库仅引入所需模块")
    report.append("  - 联系提供方获取精简版本")
    report.append("  - 考虑拆分自有库")
    report.append("  - 寻找替代库")
    report.append("")
    
    # 3. 动态库使用建议
    report.append("### 3. 动态库使用建议")
    report.append("- 原理：代码移出主二进制，运行时加载")
    report.append("- 优点：")
    report.append("  - 减小主二进制体积")
    report.append("  - 可能实现App与Extension代码共享")
    report.append("- 缺点：")
    report.append("  - 增加App冷启动时间")
    report.append("  - 需要权衡体积与启动时间")
    report.append("- 适用场景：")
    report.append("  - 模块体积巨大")
    report.append("  - 需要在多Target间共享大量代码")
    report.append("")
    
    # 4. 依赖管理建议
    report.append("### 4. 依赖管理建议")
    report.append("- 定期检查和清理不再使用的第三方库或代码")
    report.append("- 检查方法：")
    report.append("  - 审查依赖文件：`Podfile`、`Package.swift`、`Cartfile`")
    report.append("  - 利用未使用代码工具：Periphery可能标记出未使用的库接口")
    report.append("  - 全局代码搜索：搜索库的`import`或关键类名")
    report.append("- 建议：")
    report.append("  - 建立定期审查流程")
    report.append("  - 注释掉依赖并编译验证")
    report.append("  - 确认无用后移除")

    report.append("")
    report.append("--- 报告结束 ---")

    return "\n".join(report)

def export_to_csv(output_file, symbols_analysis, library_analysis, sections):
    """将分析结果导出为CSV文件。"""
    total_section_size = sum(s['size'] for s in sections.values()) if sections else 0
    total_symbol_size = sum(size for _, size in symbols_analysis) if symbols_analysis else 0
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # 写入头部信息
        writer.writerow(['Link Map 分析报告'])
        writer.writerow(['生成时间', '总大小', '符号总大小'])
        writer.writerow(['', format_size(total_section_size), format_size(total_symbol_size)])
        writer.writerow([])
        
        # 写入库分析
        writer.writerow(['库/模块分析'])
        writer.writerow(['库名', '大小', '占比', '文件数'])
        
        for lib_name, size, files in library_analysis:
            percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
            writer.writerow([lib_name, format_size(size), f"{percentage:.1f}%", len(files)])
        
        writer.writerow([])
        
        # 写入文件分析
        writer.writerow(['文件分析'])
        writer.writerow(['文件名', '大小', '占比'])
        
        for file_id, size in symbols_analysis:
            simple_name = file_id.split('/')[-1]
            percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
            writer.writerow([simple_name, format_size(size), f"{percentage:.1f}%"])
    
    print(f"CSV报告已导出至: {output_file}")

def export_to_json(output_file, symbols_analysis, library_analysis, sections):
    """将分析结果导出为JSON文件。"""
    total_section_size = sum(s['size'] for s in sections.values())
    
    # 格式化各部分数据
    sections_data = []
    for addr, section in sections.items():
        sections_data.append({
            'address': addr,
            'size': section['size'],
            'size_formatted': format_size(section['size']),
            'segment': section['segment'],
            'section': section['section']
        })
    
    files_data = []
    for file_id, size in symbols_analysis:
        simple_name = file_id.split('/')[-1]
        percentage = (size / total_section_size * 100) if total_section_size > 0 else 0
        files_data.append({
            'file_path': file_id,
            'file_name': simple_name,
            'size': size,
            'size_formatted': format_size(size),
            'percentage': percentage
        })
    
    libraries_data = []
    for lib_name, size, files in library_analysis:
        percentage = (size / total_section_size * 100) if total_section_size > 0 else 0
        libraries_data.append({
            'name': lib_name,
            'size': size,
            'size_formatted': format_size(size),
            'percentage': percentage,
            'file_count': len(files),
            'files': files
        })
    
    # 创建完整数据结构
    data = {
        'summary': {
            'total_size': total_section_size,
            'total_size_formatted': format_size(total_section_size),
            'symbol_count': len(symbols_analysis),
            'library_count': len(library_analysis)
        },
        'sections': sections_data,
        'libraries': libraries_data,
        'files': files_data
    }
    
    # 写入JSON文件
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"JSON报告已导出至: {output_file}")

def generate_html_report(output_file, symbols_analysis, library_analysis, sections):
    """生成HTML格式的分析报告。"""
    total_section_size = sum(s['size'] for s in sections.values())
    total_symbol_size = sum(size for _, size in symbols_analysis)
    
    # 按段落聚合大小
    size_by_segment = defaultdict(int)
    for section in sections.values():
        size_by_segment[section['segment']] += section['size']
    
    # 生成HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Link Map 分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .summary {{ background-color: #e9f7ef; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .chart-container {{ height: 300px; margin-bottom: 30px; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h1>Link Map 分析报告</h1>
    
    <div class="summary">
        <h2>摘要</h2>
        <p>总大小: {format_size(total_section_size)}</p>
        <p>符号总大小: {format_size(total_symbol_size)}</p>
        <p>符号数量: {len(symbols_analysis)} 个文件</p>
    </div>
    
    <h2>Sections 分析</h2>
    <div class="chart-container">
        <canvas id="segmentsChart"></canvas>
    </div>
    <table>
        <tr>
            <th>Segment</th>
            <th>大小</th>
            <th>占比</th>
        </tr>
    """
    
    # 段内容
    segment_names = []
    segment_sizes = []
    segment_colors = []
    colors = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796']
    
    for i, (segment, size) in enumerate(sorted(size_by_segment.items(), key=lambda x: x[1], reverse=True)):
        percentage = size / total_section_size * 100 if total_section_size > 0 else 0
        html += f"""
        <tr>
            <td>{segment}</td>
            <td>{format_size(size)}</td>
            <td>{percentage:.1f}%</td>
        </tr>"""
        segment_names.append(segment)
        segment_sizes.append(size)
        segment_colors.append(colors[i % len(colors)])
    
    html += """
    </table>
    
    <h2>库/模块分析 (Top 15)</h2>
    <div class="chart-container">
        <canvas id="librariesChart"></canvas>
    </div>
    <table>
        <tr>
            <th>库名</th>
            <th>大小</th>
            <th>占比</th>
            <th>文件数</th>
        </tr>
    """
    
    # 库分析内容
    lib_names = []
    lib_sizes = []
    lib_colors = []
    
    for i, (lib_name, size, files) in enumerate(library_analysis[:15]):
        percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
        html += f"""
        <tr>
            <td>{lib_name}</td>
            <td>{format_size(size)}</td>
            <td>{percentage:.1f}%</td>
            <td>{len(files)}</td>
        </tr>"""
        lib_names.append(lib_name)
        lib_sizes.append(size)
        lib_colors.append(colors[i % len(colors)])
    
    html += """
    </table>
    
    <h2>文件大小分析 (Top 20)</h2>
    <table>
        <tr>
            <th>文件名</th>
            <th>大小</th>
            <th>占比</th>
        </tr>
    """
    
    # 文件分析内容
    for i, (file_id, size) in enumerate(symbols_analysis[:20]):
        simple_name = file_id.split('/')[-1]
        percentage = (size / total_symbol_size * 100) if total_symbol_size > 0 else 0
        html += f"""
        <tr>
            <td>{simple_name}</td>
            <td>{format_size(size)}</td>
            <td>{percentage:.1f}%</td>
        </tr>"""
    
    # 添加图表JS代码
    html += f"""
    </table>
    
    <script>
        // 段大小图表
        var segCtx = document.getElementById('segmentsChart').getContext('2d');
        var segChart = new Chart(segCtx, {{
            type: 'pie',
            data: {{
                labels: {json.dumps(segment_names)},
                datasets: [{{
                    data: {json.dumps(segment_sizes)},
                    backgroundColor: {json.dumps(segment_colors)},
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                title: {{ display: true, text: 'Segments大小分布' }}
            }}
        }});
        
        // 库大小图表
        var libCtx = document.getElementById('librariesChart').getContext('2d');
        var libChart = new Chart(libCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(lib_names)},
                datasets: [{{
                    label: '库大小(bytes)',
                    data: {json.dumps(lib_sizes)},
                    backgroundColor: {json.dumps(lib_colors)},
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    yAxes: [{{ ticks: {{ beginAtZero: true }} }}]
                }}
            }}
        }});
    </script>
</body>
</html>
    """
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"HTML报告已导出至: {output_file}")

def compare_versions(old_data, new_data):
    """比较两个版本的数据，生成差异报告。"""
    report = []
    report.append("--- Link Map 版本对比报告 ---")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    # 计算总体变化
    old_total = old_data['summary']['total_size']
    new_total = new_data['summary']['total_size']
    total_diff = new_total - old_total
    total_diff_percentage = (total_diff / old_total * 100) if old_total > 0 else 0
    
    report.append("## 总体变化")
    report.append(f"旧版本大小: {format_size(old_total)}")
    report.append(f"新版本大小: {format_size(new_total)}")
    report.append(f"变化: {format_size(total_diff)} ({total_diff_percentage:+.1f}%)")
    report.append("")

    # 比较库/模块变化
    report.append("## 库/模块变化 (Top 20)")
    report.append("-" * 100)
    report.append(f"{'库名':<20} {'旧大小':<10} {'新大小':<10} {'变化':<10} {'变化率':<8}")
    report.append("-" * 100)
    
    # 创建库名到大小的映射
    old_libs = {lib['name']: lib['size'] for lib in old_data['libraries']}
    new_libs = {lib['name']: lib['size'] for lib in new_data['libraries']}
    
    # 合并所有库名
    all_libs = set(old_libs.keys()) | set(new_libs.keys())
    
    # 计算每个库的变化
    lib_changes = []
    for lib_name in all_libs:
        old_size = old_libs.get(lib_name, 0)
        new_size = new_libs.get(lib_name, 0)
        diff = new_size - old_size
        diff_percentage = (diff / old_size * 100) if old_size > 0 else float('inf')
        lib_changes.append((lib_name, old_size, new_size, diff, diff_percentage))
    
    # 按变化大小排序
    lib_changes.sort(key=lambda x: abs(x[3]), reverse=True)
    
    # 显示前20个变化最大的库
    for lib_name, old_size, new_size, diff, diff_percentage in lib_changes[:20]:
        report.append(f"{lib_name:<20} {format_size(old_size):<10} {format_size(new_size):<10} "
                     f"{format_size(diff):<10} {diff_percentage:+.1f}%")
    
    report.append("")
    
    # 比较文件变化
    report.append("## 文件变化 (Top 20)")
    report.append("-" * 100)
    report.append(f"{'文件名':<40} {'旧大小':<10} {'新大小':<10} {'变化':<10} {'变化率':<8}")
    report.append("-" * 100)
    
    # 创建文件名到大小的映射
    old_files = {file['file_name']: file['size'] for file in old_data['files']}
    new_files = {file['file_name']: file['size'] for file in new_data['files']}
    
    # 合并所有文件名
    all_files = set(old_files.keys()) | set(new_files.keys())
    
    # 计算每个文件的变化
    file_changes = []
    for file_name in all_files:
        old_size = old_files.get(file_name, 0)
        new_size = new_files.get(file_name, 0)
        diff = new_size - old_size
        diff_percentage = (diff / old_size * 100) if old_size > 0 else float('inf')
        file_changes.append((file_name, old_size, new_size, diff, diff_percentage))
    
    # 按变化大小排序
    file_changes.sort(key=lambda x: abs(x[3]), reverse=True)
    
    # 显示前20个变化最大的文件
    for file_name, old_size, new_size, diff, diff_percentage in file_changes[:20]:
        report.append(f"{file_name:<40} {format_size(old_size):<10} {format_size(new_size):<10} "
                     f"{format_size(diff):<10} {diff_percentage:+.1f}%")
    
    report.append("")
    report.append("--- 报告结束 ---")
    
    return "\n".join(report)

def generate_comparison_html(old_data, new_data, output_file):
    """生成HTML格式的版本对比报告。"""
    # 计算总体变化
    old_total = old_data['summary']['total_size']
    new_total = new_data['summary']['total_size']
    total_diff = new_total - old_total
    total_diff_percentage = (total_diff / old_total * 100) if old_total > 0 else 0
    
    # 生成HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Link Map 版本对比报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1, h2 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        .summary {{ background-color: #e9f7ef; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .chart-container {{ height: 300px; margin-bottom: 30px; }}
        .increase {{ color: #e74a3b; }}
        .decrease {{ color: #2ecc71; }}
    </style>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body>
    <h1>Link Map 版本对比报告</h1>
    <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    
    <div class="summary">
        <h2>总体变化</h2>
        <p>旧版本大小: {format_size(old_total)}</p>
        <p>新版本大小: {format_size(new_total)}</p>
        <p>变化: <span class="{'increase' if total_diff > 0 else 'decrease'}">
            {format_size(total_diff)} ({total_diff_percentage:+.1f}%)
        </span></p>
    </div>
    
    <h2>库/模块变化 (Top 20)</h2>
    <div class="chart-container">
        <canvas id="librariesChart"></canvas>
    </div>
    <table>
        <tr>
            <th>库名</th>
            <th>旧大小</th>
            <th>新大小</th>
            <th>变化</th>
            <th>变化率</th>
        </tr>
    """
    
    # 库变化数据
    old_libs = {lib['name']: lib['size'] for lib in old_data['libraries']}
    new_libs = {lib['name']: lib['size'] for lib in new_data['libraries']}
    all_libs = set(old_libs.keys()) | set(new_libs.keys())
    
    lib_changes = []
    for lib_name in all_libs:
        old_size = old_libs.get(lib_name, 0)
        new_size = new_libs.get(lib_name, 0)
        diff = new_size - old_size
        diff_percentage = (diff / old_size * 100) if old_size > 0 else float('inf')
        lib_changes.append((lib_name, old_size, new_size, diff, diff_percentage))
    
    lib_changes.sort(key=lambda x: abs(x[3]), reverse=True)
    
    # 图表数据
    lib_names = []
    lib_diffs = []
    lib_colors = []
    colors = ['#4e73df', '#1cc88a', '#36b9cc', '#f6c23e', '#e74a3b', '#858796']
    
    for i, (lib_name, old_size, new_size, diff, diff_percentage) in enumerate(lib_changes[:20]):
        color = '#e74a3b' if diff > 0 else '#2ecc71'
        html += f"""
        <tr>
            <td>{lib_name}</td>
            <td>{format_size(old_size)}</td>
            <td>{format_size(new_size)}</td>
            <td class="{'increase' if diff > 0 else 'decrease'}">{format_size(diff)}</td>
            <td class="{'increase' if diff > 0 else 'decrease'}">{diff_percentage:+.1f}%</td>
        </tr>"""
        lib_names.append(lib_name)
        lib_diffs.append(diff)
        lib_colors.append(color)
    
    html += """
    </table>
    
    <h2>文件变化 (Top 20)</h2>
    <table>
        <tr>
            <th>文件名</th>
            <th>旧大小</th>
            <th>新大小</th>
            <th>变化</th>
            <th>变化率</th>
        </tr>
    """
    
    # 文件变化数据
    old_files = {file['file_name']: file['size'] for file in old_data['files']}
    new_files = {file['file_name']: file['size'] for file in new_data['files']}
    all_files = set(old_files.keys()) | set(new_files.keys())
    
    file_changes = []
    for file_name in all_files:
        old_size = old_files.get(file_name, 0)
        new_size = new_files.get(file_name, 0)
        diff = new_size - old_size
        diff_percentage = (diff / old_size * 100) if old_size > 0 else float('inf')
        file_changes.append((file_name, old_size, new_size, diff, diff_percentage))
    
    file_changes.sort(key=lambda x: abs(x[3]), reverse=True)
    
    for file_name, old_size, new_size, diff, diff_percentage in file_changes[:20]:
        html += f"""
        <tr>
            <td>{file_name}</td>
            <td>{format_size(old_size)}</td>
            <td>{format_size(new_size)}</td>
            <td class="{'increase' if diff > 0 else 'decrease'}">{format_size(diff)}</td>
            <td class="{'increase' if diff > 0 else 'decrease'}">{diff_percentage:+.1f}%</td>
        </tr>"""
    
    # 添加图表JS代码
    html += f"""
    </table>
    
    <script>
        // 库变化图表
        var libCtx = document.getElementById('librariesChart').getContext('2d');
        var libChart = new Chart(libCtx, {{
            type: 'bar',
            data: {{
                labels: {json.dumps(lib_names)},
                datasets: [{{
                    label: '大小变化(bytes)',
                    data: {json.dumps(lib_diffs)},
                    backgroundColor: {json.dumps(lib_colors)},
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                scales: {{
                    yAxes: [{{
                        ticks: {{
                            beginAtZero: true,
                            callback: function(value) {{
                                return value.toLocaleString() + ' bytes';
                            }}
                        }}
                    }}]
                }}
            }}
        }});
    </script>
</body>
</html>
    """
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"HTML对比报告已导出至: {output_file}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='分析 Xcode Link Map 文件，给出大小分析报告。')
    parser.add_argument('linkmap_file', help='Link Map 文件路径')
    parser.add_argument('-o', '--output', help='输出报告的文件路径')
    parser.add_argument('--csv', help='输出CSV格式报告的路径')
    parser.add_argument('--json', help='输出JSON格式报告的路径')
    parser.add_argument('--html', help='输出HTML格式报告的路径')
    parser.add_argument('--top', type=int, default=20, help='显示前N个最大的文件，默认为20')
    parser.add_argument('--compare', help='要比较的旧版本Link Map文件路径')
    parser.add_argument('--compare-output', help='比较报告的输出路径')
    parser.add_argument('--compare-html', help='比较报告的HTML输出路径')
    args = parser.parse_args()

    try:
        # 解析文件
        sections, symbols, object_files = parse_linkmap(args.linkmap_file)
        
        if not sections and not symbols:
            print(f"错误: 无法从 {args.linkmap_file} 解析数据，请检查文件格式。")
            sys.exit(1)
            
        # 分析符号大小（按文件）
        symbols_analysis = analyze_symbols(symbols, object_files)
        
        # 分析符号大小（按库/模块）
        library_analysis = analyze_symbols_by_library(symbols, object_files)
        
        # 生成并显示文本报告
        report = generate_report(sections, symbols_analysis, library_analysis)
        print(report)
        
        # 如果指定了输出文件路径，保存文本报告
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"报告已保存至: {args.output}")
        
        # 导出CSV报告
        if args.csv:
            export_to_csv(args.csv, symbols_analysis, library_analysis, sections)
        
        # 导出JSON报告
        if args.json:
            export_to_json(args.json, symbols_analysis, library_analysis, sections)
            
        # 导出HTML报告
        if args.html:
            generate_html_report(args.html, symbols_analysis, library_analysis, sections)
            
        # 如果需要比较两个版本
        if args.compare:
            print(f"\n正在解析旧版本文件: {args.compare}")
            old_sections, old_symbols, old_object_files = parse_linkmap(args.compare)
            
            if not old_sections and not old_symbols:
                print(f"错误: 无法从 {args.compare} 解析数据，请检查文件格式。")
                sys.exit(1)
                
            # 分析旧版本数据
            old_symbols_analysis = analyze_symbols(old_symbols, old_object_files)
            old_library_analysis = analyze_symbols_by_library(old_symbols, old_object_files)
            
            # 导出旧版本JSON数据
            old_json_file = args.compare + '.json'
            export_to_json(old_json_file, old_symbols_analysis, old_library_analysis, old_sections)
            
            # 读取新旧版本的JSON数据
            with open(old_json_file, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
            
            # 如果没有指定新版本的JSON文件，创建一个临时文件
            if not args.json:
                new_json_file = args.linkmap_file + '.json'
                export_to_json(new_json_file, symbols_analysis, library_analysis, sections)
                with open(new_json_file, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
            else:
                with open(args.json, 'r', encoding='utf-8') as f:
                    new_data = json.load(f)
            
            # 生成比较报告
            comparison_report = compare_versions(old_data, new_data)
            
            # 保存比较报告
            if args.compare_output:
                with open(args.compare_output, 'w', encoding='utf-8') as f:
                    f.write(comparison_report)
                print(f"比较报告已保存至: {args.compare_output}")
            
            # 生成HTML比较报告
            if args.compare_html:
                generate_comparison_html(old_data, new_data, args.compare_html)
            
            # 清理临时文件
            os.remove(old_json_file)
            if not args.json:
                os.remove(new_json_file)

    except FileNotFoundError as e:
        print(f"错误: 文件未找到 - {e}")
        sys.exit(1)
    except Exception as e:
        print(f"发生错误: {e}")
        sys.exit(1)
