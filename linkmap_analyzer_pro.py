# 分析linkmap中的 # Sections: 段 和 # Symbols: 段，给出分析报告

import sys
import argparse
import re
import os
import json
import csv
from collections import defaultdict
from datetime import datetime
import subprocess  # 用于调用外部命令
import shutil      # 用于查找命令路径

def find_executable(name):
    """查找可执行文件的路径"""
    return shutil.which(name)

SWIFT_DEMANGLE_PATH = find_executable('swift-demangle')
CPP_FILT_PATH = find_executable('c++filt')

print(f"Swift demangler path: {SWIFT_DEMANGLE_PATH}")
print(f"C++filt path: {CPP_FILT_PATH}")

def demangle_swift(mangled_name):
    """使用 swift-demangle 对 Swift 符号进行去混淆"""
    global SWIFT_DEMANGLE_PATH
    if not SWIFT_DEMANGLE_PATH or not mangled_name or not mangled_name.startswith(('_$s', '_$S', '$s', '$S')): # Swift 符号常见前缀
        return mangled_name
    try:
        # 使用 subprocess 调用 swift-demangle
        process = subprocess.run(
            [SWIFT_DEMANGLE_PATH],
            input=mangled_name,
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
        # swift-demangle 输出通常包含 "symbol -> demangled_symbol"，我们需要提取后者
        output = process.stdout.strip()
        if ' -> ' in output:
             # 提取 ' -> ' 之后的部分
             demangled = output.split(' -> ')[-1].strip()
             # 进一步清理可能的额外信息
             if demangled.startswith("merged ") or demangled.startswith("outlined variable"):
                 demangled = demangled.split(" of ", 1)[-1] # 取 of 之后的部分
             return demangled if demangled else mangled_name
        elif output and not output.startswith('error:'): # 有时直接输出结果
             return output
        else:
             return mangled_name # 如果去混淆失败或没有变化，返回原名
    except subprocess.CalledProcessError as e:
        # print(f"调用 swift-demangle 失败 (代码 {e.returncode}): {e.stderr}")
        return mangled_name # 失败时返回原名
    except FileNotFoundError:
        print("警告: 未找到 swift-demangle 工具。Swift 符号将不会被去混淆。请确保已安装 Xcode Command Line Tools。")
        SWIFT_DEMANGLE_PATH = None
        return mangled_name
    except Exception as e:
        # print(f"去混淆 Swift 符号时发生意外错误: {e}")
        return mangled_name # 发生其他错误也返回原名

def demangle_cpp(mangled_name):
    """使用 c++filt 对 C++ 符号进行去混淆"""
    global CPP_FILT_PATH
    # C++ 符号通常以 _Z 或 __Z 开头
    if not CPP_FILT_PATH or not mangled_name or not mangled_name.startswith(('_Z', '__Z')):
        return mangled_name
    try:
        process = subprocess.run(
            [CPP_FILT_PATH, mangled_name],
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
        demangled = process.stdout.strip()
        return demangled if demangled and demangled != mangled_name else mangled_name
    except subprocess.CalledProcessError as e:
        # print(f"调用 c++filt 失败 (代码 {e.returncode}): {e.stderr}")
        return mangled_name
    except FileNotFoundError:
        print("警告: 未找到 c++filt 工具。C++ 符号将不会被去混淆。请确保已安装 Xcode Command Line Tools 或相应构建工具。")
        CPP_FILT_PATH = None
        return mangled_name
    except Exception as e:
        # print(f"去混淆 C++ 符号时发生意外错误: {e}")
        return mangled_name

def demangle_symbol(name):
    """尝试对符号进行去混淆（先 Swift 后 C++）"""
    if not isinstance(name, str):
        return name
    # 尝试 Swift
    demangled = demangle_swift(name)
    # 如果 Swift 没变化，尝试 C++
    if demangled == name:
        demangled = demangle_cpp(name)
    return demangled

def parse_linkmap(filepath):
    """解析 Link Map 文件，提取 Sections 和 Symbols 信息。"""
    print(f"正在解析文件: {filepath}")
    sections = {}
    symbols = []
    object_files = {}  # 存储对象文件信息
    
    # 直接读取整个文件进行处理
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"错误: Link Map 文件未找到: {filepath}")
        return None, None, None
    except Exception as e:
        print(f"读取 Link Map 文件时出错: {e}")
        return None, None, None
    
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
                except Exception as e:
                    # print(f"解析 Object file 行失败: {line}, 错误: {e}")
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(object_files)} 个 Object files")
    else:
         print("警告: 未找到 '# Object files:' 段落。")
    
    # 解析 Sections 段落
    if sections_start != -1:
        i = sections_start + 1  # 跳过标题行
        # 跳过表头行
        while i < len(lines) and lines[i].startswith('# Address'): # 跳过表头
            i += 1
            
        # 开始解析数据行
        while i < len(lines) and not lines[i].startswith('#'): # 直到下一个 # 开头的段落
            line = lines[i].strip()
            if line:
                try:
                    parts = line.split('\t') # LinkMap 文件通常使用 Tab 分隔
                    if len(parts) >= 4 and parts[0].startswith('0x'):
                        addr = parts[0]
                        size_str = parts[1]
                        size = int(size_str, 16) # size 是十六进制
                        segment = parts[2]
                        section = parts[3]
                        sections[addr] = {
                            'size': size,
                            'segment': segment,
                            'section': section
                        }
                    else: # 尝试用空格分割
                        parts = line.split()
                    if len(parts) >= 4 and parts[0].startswith('0x'):
                        addr = parts[0]
                        size_str = parts[1]
                        size = int(size_str, 16)
                        segment = parts[2]
                        section = parts[3]
                        sections[addr] = {
                            'size': size, 
                            'segment': segment, 
                            'section': section
                        }

                except Exception as e:
                    # print(f"解析 Section 行失败: {line}, 错误: {e}")
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(sections)} 个 Sections")
    else:
        print("警告: 未找到 '# Sections:' 段落。")
    
    # 解析 Symbols 段落
    if symbols_start != -1:
        i = symbols_start + 1  # 跳过标题行
        # 跳过表头行
        while i < len(lines) and lines[i].startswith('# Address'): # 跳过表头
            i += 1
            
        # 开始解析数据行
        while i < len(lines) and not lines[i].startswith('#'): # 直到文件末尾或下一个 # 段落
            line = lines[i].strip()
            # 确保行以 0x 开头，且包含 `[` 和 `]` 包裹的文件索引
            if line.startswith('0x') and '[' in line and ']' in line:
                try:
                    # 0xAddress	0xSize	[ FileIndex] Name
                    parts = line.split('\t', 2) # 最多分割两次
                    if len(parts) == 3:
                        addr = parts[0]
                        size_str = parts[1]
                        # 从第三部分提取 FileIndex 和 Name
                        index_name_part = parts[2]
                        match = re.match(r'\[\s*(\d+)\s*\]\s*(.*)', index_name_part)
                    if match:
                            file_index = int(match.group(1))
                            name = match.group(2).strip()
                            size = int(size_str, 16)
                            symbols.append({
                            'address': addr,
                            'size': size,
                            'file_index': file_index,
                                'name': name,
                                'demangled_name': demangle_symbol(name) # 添加去混淆后的名字
                            })
                    else:
                         # 尝试用空格分割作为备用方案
                         match_space = re.match(r'(0x[0-9A-Fa-f]+)\s+(0x[0-9A-Fa-f]+)\s+\[\s*(\d+)\s*\]\s*(.*)', line)
                         if match_space:
                            addr = match_space.group(1)
                            size_str = match_space.group(2)
                            file_index = int(match_space.group(3))
                            name = match_space.group(4).strip()
                            size = int(size_str, 16)
                            symbols.append({
                                'address': addr,
                                'size': size,
                                'file_index': file_index,
                                'name': name,
                                'demangled_name': demangle_symbol(name)
                            })

                except Exception as e:
                    # print(f"解析 Symbol 行失败: {line}, 错误: {e}")
                    pass  # 忽略解析错误
            i += 1
        print(f"解析到 {len(symbols)} 个 Symbols")
    else:
        print("警告: 未找到 '# Symbols:' 段落。")

    if not sections and not symbols:
        print("错误：未能从文件中解析出任何 Sections 或 Symbols 信息。请检查文件格式是否正确。")
        return None, None, None
    
    return sections, symbols, object_files

def analyze_symbols(symbols, object_files=None):
    """分析 Symbols，按文件聚合大小，包含去混淆名。"""
    size_by_file = defaultdict(lambda: {'size': 0, 'symbols': []})
    
    for symbol in symbols:
        file_index = symbol['file_index']
        file_id = object_files.get(file_index, f"未知文件[{file_index}]") if object_files else f"未知文件[{file_index}]"
        size_by_file[file_id]['size'] += symbol['size']
        size_by_file[file_id]['symbols'].append(symbol) # 保存原始符号信息

    # 按大小排序
    sorted_size_by_file = sorted(
        [(file_id, data['size'], data['symbols']) for file_id, data in size_by_file.items()],
        key=lambda item: item[1],
        reverse=True
    )
    return sorted_size_by_file

def analyze_symbols_by_library(symbols, object_files=None):
    """分析 Symbols，按库/模块聚合大小，包含去混淆名。"""
    size_by_library = defaultdict(lambda: {'size': 0, 'files': set(), 'symbols': []})
    
    for symbol in symbols:
        file_index = symbol['file_index']
        file_path = object_files.get(file_index, f"未知文件[{file_index}]") if object_files else f"未知文件[{file_index}]"
        
        # 提取库名
        library_name = extract_library_name(file_path)
        size_by_library[library_name]['size'] += symbol['size']
        size_by_library[library_name]['files'].add(file_path)
        size_by_library[library_name]['symbols'].append(symbol)

    # 按大小排序
    sorted_size_by_library = sorted(
        [(lib, data['size'], sorted(list(data['files'])), data['symbols']) for lib, data in size_by_library.items()],
        key=lambda item: item[1],
        reverse=True
    )
    return sorted_size_by_library

def extract_library_name(file_path):
    """从文件路径中提取库/模块名称。"""
    if not isinstance(file_path, str) or not file_path:
        return "未知"
        
    # 处理常见的库格式
    # 静态库成员: /path/to/libWhatever.a(object_file.o)
    static_lib_member_match = re.search(r'/([^/]+?\.a)\(', file_path)
    if static_lib_member_match:
        return static_lib_member_match.group(1)

    # 静态库本身: /path/to/libWhatever.a
    static_lib_match = re.search(r'/([^/]+\.a)$', file_path)
    if static_lib_match:
        return static_lib_match.group(1)
            
    # 框架: /path/to/MyFramework.framework/MyFramework
    framework_match = re.search(r'/([^/]+\.framework)/', file_path)
    if framework_match:
        return framework_match.group(1) + ".framework"

    # Pods 库: Pods/LibraryName/File.o
    pods_match = re.search(r'Pods/([^/]+)/', file_path)
    if pods_match:
        return f"Pods: {pods_match.group(1)}"

    # Carthage 库: Carthage/Build/iOS/LibraryName.framework/
    carthage_match = re.search(r'Carthage/Build/[^/]+/([^/]+\.framework)/', file_path)
    if carthage_match:
        return f"Carthage: {carthage_match.group(1)}"

    # SPM 库: SourcePackages/checkouts/library-name/
    # SPM 编译产物路径可能更复杂，取决于构建系统，但可以尝试匹配
    spm_match = re.search(r'SourcePackages/(?:checkouts|artifacts)/([^/]+)/', file_path)
    if spm_match:
         # 尝试从 .build 目录结构推断
         build_match = re.search(r'\.build/(?:[^/]+)/([^/]+)\.build/', file_path)
         if build_match:
              return f"SPM: {build_match.group(1)}"
         else:
              return f"SPM: {spm_match.group(1)}" # 简化回退


    # 系统库或 dylib: /usr/lib/libSystem.dylib, /System/Library/...
    if file_path.startswith('/usr/lib/') or file_path.startswith('/System/Library/'):
        return os.path.basename(file_path)

    # 如果是项目内部文件，尝试取文件名 (去掉 .o)
    if file_path.endswith(".o"):
        filename = os.path.basename(file_path)
         # 检查是否来自 main executable (通常没有库标识)
         # 这里可以添加逻辑，比如如果 object_files 字典中该索引对应的文件路径不包含特定库标识，则归类为主项目
         # 这需要 parse_linkmap 提供更完整的 object_files 路径信息
         # 暂时简化处理
        return "主项目或其他" # 无法明确归类时

    # 处理老格式 [ N] /path/to/file
    if re.match(r'\[\s*\d+\s*\]', file_path):
         actual_path = re.sub(r'\[\s*\d+\s*\]\s*', '', file_path)
         return extract_library_name(actual_path) # 递归调用处理真实路径


    # 无法识别，返回原始路径或"未知"
    return os.path.basename(file_path) if '/' in file_path else file_path

def format_size(size_bytes):
    """格式化文件大小显示，自动选择合适的单位。"""
    if not isinstance(size_bytes, (int, float)) or size_bytes < 0:
        return "N/A"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024*1024:
        return f"{size_bytes/1024:.2f} KB"
    elif size_bytes < 1024*1024*1024:
        return f"{size_bytes/(1024*1024):.2f} MB"
    else:
        return f"{size_bytes/(1024*1024*1024):.2f} GB"

def detect_potential_issues(symbols_analysis, library_analysis, top_n=10, size_threshold_kb=50):
    """检测潜在的未使用代码和重复代码（启发式）。"""
    warnings = []
    size_threshold_bytes = size_threshold_kb * 1024

    # 1. 潜在的未使用静态库符号 (如果一个 .a 文件只有一个或很少几个符号被链接，可能提示检查)
    #    这比较复杂，需要更精确的引用关系，LinkMap 不直接提供。暂时跳过。

    # 2. 潜在的重复代码 (基于去混淆后的名称和大小)
    symbols_by_demangled_name = defaultdict(list)
    all_symbols = []
    for _, _, _, symbols in library_analysis:
        all_symbols.extend(symbols)
    for _, _, symbols in symbols_analysis: # 也分析按文件聚合的
        all_symbols.extend(symbols)

    unique_symbols = { (s['address'], s['name']): s for s in all_symbols } # 去重

    for symbol in unique_symbols.values():
        # 忽略非常小的符号和非代码符号（如数据）
        if symbol['size'] > 100 and symbol['demangled_name'] and not symbol['demangled_name'].startswith(('OBJC_CLASS_$_', 'OBJC_METACLASS_$_')):
             # 简化名称，去除参数列表和模板参数，保留核心函数/方法名
             core_name_match = re.match(r'^(.*?)(?:<.*>)?\(.*\)', symbol['demangled_name'])
             core_name = core_name_match.group(1) if core_name_match else symbol['demangled_name']
             symbols_by_demangled_name[core_name].append(symbol)

    duplicate_candidates = []
    for core_name, symbols_list in symbols_by_demangled_name.items():
        if len(symbols_list) > 1:
            # 检查大小是否接近 (例如，差异在 20% 以内)
            base_symbol = symbols_list[0]
            for other_symbol in symbols_list[1:]:
                 size_diff = abs(base_symbol['size'] - other_symbol['size'])
                 if base_symbol['size'] > 0 and size_diff / base_symbol['size'] < 0.2: # 差异小于 20%
                    duplicate_candidates.append({
                         'name': core_name,
                         'symbols': [
                             {'address': s['address'], 'size': s['size'], 'original_name': s['name'], 'demangled_name': s['demangled_name']}
                             for s in symbols_list
                         ],
                         'total_size': sum(s['size'] for s in symbols_list)
                    })
                    break # 找到一组相似的就添加到候选中

    if duplicate_candidates:
        duplicate_candidates.sort(key=lambda x: x['total_size'], reverse=True)
        warnings.append("\n## ⚠️ 潜在重复代码警告 (基于名称和大小相似性，请仔细核查):\n")
        for i, dup in enumerate(duplicate_candidates[:top_n]):
             warnings.append(f"  {i+1}. 核心名称: {dup['name']} (共发现 {len(dup['symbols'])} 个相似符号, 总大小: {format_size(dup['total_size'])})")
             for s in dup['symbols'][:3]: # 最多显示3个例子
                 warnings.append(f"     - 地址: {s['address']}, 大小: {format_size(s['size'])}, 名称: {s['demangled_name']}")
             if len(dup['symbols']) > 3:
                 warnings.append(f"       ... (还有 {len(dup['symbols'])-3} 个)")


    # 3. 识别体积异常大的符号
    large_symbols = []
    for symbol in unique_symbols.values():
        if symbol['size'] > size_threshold_bytes:
            large_symbols.append(symbol)

    if large_symbols:
        large_symbols.sort(key=lambda x: x['size'], reverse=True)
        warnings.append(f"\n## ⚠️ 体积超大符号警告 (>{size_threshold_kb} KB，请检查是否可优化):\n")
        for i, symbol in enumerate(large_symbols[:top_n]):
            file_path = object_files.get(symbol['file_index'], f"未知文件[{symbol['file_index']}]")
            library_name = extract_library_name(file_path)
            warnings.append(f"  {i+1}. 大小: {format_size(symbol['size'])}")
            warnings.append(f"     名称: {symbol['demangled_name']}")
            warnings.append(f"     库/文件: {library_name}")
            warnings.append(f"     原始名称: {symbol['name']}")


    return warnings

def generate_report(linkmap_file, sections, symbols_analysis, library_analysis, top_n=20, potential_warnings=None):
    """生成增强的分析报告，包含去混淆名和潜在问题。"""
    report = []
    linkmap_name = os.path.basename(linkmap_file)
    report.append(f"--- Link Map 分析报告 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")
    report.append(f"文件: {linkmap_name}")
    report.append("")

    # 计算总大小
    total_section_size = sum(s['size'] for s in sections.values()) if sections else 0
    total_symbol_size_from_files = sum(size for _, size, _ in symbols_analysis)
    total_symbol_size_from_libs = sum(size for _, size, _, _ in library_analysis)
    # Use the one from library analysis as it should be more accurate if parsing worked well
    total_symbol_size = total_symbol_size_from_libs
    
    # 摘要信息
    report.append("## 摘要:")
    report.append(f"总段大小 (估算): {format_size(total_section_size)}")
    report.append(f"总符号大小: {format_size(total_symbol_size)}")
    report.append(f"库/模块数量: {len(library_analysis)}")
    report.append(f"文件数量 (含符号): {len(symbols_analysis)}")
    total_symbols_count = sum(len(s_list) for _, _, _, s_list in library_analysis)
    report.append(f"符号总数: {total_symbols_count}")
    report.append("")

    # Sections Summary
    if sections:
        report.append("## Sections 分析 (按 Segment):")
        size_by_segment = defaultdict(int)
        section_details = defaultdict(lambda: defaultdict(int))
    
    for addr, section in sections.items():
        segment = section['segment']
        sec_name = section['section']
        size_by_segment[segment] += section['size']
        section_details[segment][sec_name] += section['size']
    
        sorted_segments = sorted(size_by_segment.items(), key=lambda x: x[1], reverse=True)

        for segment, size in sorted_segments:
            percentage = size / total_section_size * 100 if total_section_size > 0 else 0
            report.append(f"  {segment}: {format_size(size)} ({percentage:.1f}%)")
        
        # 添加该段内各节的详细信息
            sorted_sections = sorted(section_details[segment].items(), key=lambda x: x[1], reverse=True)
            for sec_name, sec_size in sorted_sections[:5]: # 最多显示 5 个节
                sec_percentage_of_segment = sec_size / size * 100 if size > 0 else 0
                report.append(f"    - {sec_name}: {format_size(sec_size)} ({sec_percentage_of_segment:.1f}%)")
            if len(sorted_sections) > 5:
                 report.append(f"      ... (还有 {len(sorted_sections)-5} 个节)")
        report.append("")
    else:
        report.append("## Sections 分析:")
        report.append("  未能解析 Sections 数据。")
    report.append("")
    

    # Library Analysis
    report.append(f"## 库/模块大小分析 (Top {top_n}):")
    report.append("|排名|库/模块        | 大小     | 文件数 | 符号数 | 主要文件 (示例) |")
    report.append("|---|---------------|----------|--------|--------|-----------------|")
    for i, (library, size, files, symbols_list) in enumerate(library_analysis[:top_n]):
        percentage = size / total_symbol_size * 100 if total_symbol_size > 0 else 0
        # 主要文件示例：显示最多2个，取 basename
        example_files = ", ".join([os.path.basename(f) for f in files[:2]])
        if len(files) > 2:
            example_files += ", ..."
        report.append(f"|{i+1:<3}|{library:<15}|{format_size(size):<10}|{len(files):<8}|{len(symbols_list):<8}|{example_files:<17}|")
    if len(library_analysis) > top_n:
        report.append(f"|...| (还有 {len(library_analysis)-top_n} 个库/模块) | ... | ... | ... | ... |")
    report.append("")


    # File Analysis
    report.append(f"## 文件大小分析 (Top {top_n}):")
    report.append("|排名|文件路径             | 大小     | 符号数 | 最大符号 (示例) |")
    report.append("|---|----------------------|----------|--------|-------------------|")
    for i, (filepath, size, symbols_list) in enumerate(symbols_analysis[:top_n]):
        percentage = size / total_symbol_size * 100 if total_symbol_size > 0 else 0
        # 最大符号示例
        largest_symbol_name = "-"
        if symbols_list:
            largest_symbol = max(symbols_list, key=lambda s: s['size'])
            largest_symbol_name = largest_symbol['demangled_name'] if largest_symbol['demangled_name'] else largest_symbol['name']
            # 截断过长的名字
            if len(largest_symbol_name) > 50:
                 largest_symbol_name = largest_symbol_name[:47] + "..."

        # 截断过长的文件路径
        display_filepath = filepath
        if len(display_filepath) > 60:
            display_filepath = "..." + display_filepath[-57:]

        report.append(f"|{i+1:<3}|{display_filepath:<22}|{format_size(size):<10}|{len(symbols_list):<8}|{largest_symbol_name:<19}|")
    if len(symbols_analysis) > top_n:
        report.append(f"|...| (还有 {len(symbols_analysis)-top_n} 个文件) | ... | ... | ... |")
    report.append("")
    
    # 添加潜在问题警告
    if potential_warnings:
        report.extend(potential_warnings)
    report.append("")
    
    # Optimization Suggestions (can be enhanced)
    report.append("## 优化建议:")
    report.append("- 重点关注体积较大的库/模块和文件，评估是否可以移除、替换或进行代码优化。")
    report.append("- 检查体积超大的符号，分析其实现，看是否有优化空间（如算法改进、代码拆分）。")
    report.append("- 对于潜在的重复代码警告，请仔细比对涉及的符号，确认是否可以合并或重构。")
    report.append("- 确保 Release 构建启用了 LTO（链接时优化）和 Dead Code Stripping（无效代码剥离）。")
    report.append("- 定期使用此工具进行版本对比，监控体积变化趋势。")
    report.append("") # End of report marker

    return "\n".join(report)

def generate_csv_report(filepath, library_analysis, symbols_analysis):
    """生成 CSV 格式报告。"""
    try:
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)

            # 写入库/模块分析
            writer.writerow(['Type', 'Name', 'Size (Bytes)', 'File Count', 'Symbol Count'])
            for library, size, files, symbols_list in library_analysis:
                writer.writerow(['Library/Module', library, size, len(files), len(symbols_list)])

            writer.writerow([]) # 空行分隔

            # 写入文件分析
            writer.writerow(['Type', 'File Path', 'Size (Bytes)', 'Symbol Count'])
            for file_path, size, symbols_list in symbols_analysis:
                 writer.writerow(['File', file_path, size, len(symbols_list)])

        print(f"CSV 报告已保存到: {filepath}")
    except IOError as e:
        print(f"错误: 无法写入 CSV 文件 {filepath}: {e}")

def generate_json_report(filepath, sections, library_analysis, symbols_analysis):
    """生成 JSON 格式报告。"""
    report_data = {
        "metadata": {
            "report_time": datetime.now().isoformat(),
            "linkmap_file": filepath,
        },
        "sections_summary": {seg: {'size': size} for seg, size in defaultdict(int).items()}, # Simplified section summary
        "libraries": [
            {"name": lib, "size": size, "file_count": len(files), "symbol_count": len(s_list)}
            for lib, size, files, s_list in library_analysis
        ],
        "files": [
             {"path": fpath, "size": size, "symbol_count": len(s_list)}
             for fpath, size, s_list in symbols_analysis
        ]
        # Maybe add detailed symbols later if needed, could be large
    }

    # Populate sections summary more accurately
    if sections:
         size_by_segment = defaultdict(int)
         for addr, section in sections.items():
             size_by_segment[section['segment']] += section['size']
         report_data['sections_summary'] = {seg: {'size': size} for seg, size in size_by_segment.items()}


    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report_data, f, indent=2, ensure_ascii=False)
        print(f"JSON 报告已保存到: {filepath}")
    except IOError as e:
        print(f"错误: 无法写入 JSON 文件 {filepath}: {e}")


def generate_html_report(filepath, linkmap_file, sections, library_analysis, symbols_analysis, top_n=20, potential_warnings=None):
    """生成 HTML 格式报告（包含 Chart.js 可视化）。"""

    linkmap_name = os.path.basename(linkmap_file)
    report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
    # --- Chart Data Preparation ---
    # Library Size Chart (Top N Pie Chart)
    library_labels = [lib for lib, _, _, _ in library_analysis[:top_n]]
    library_sizes = [size for _, size, _, _ in library_analysis[:top_n]]
    other_library_size = sum(size for _, size, _, _ in library_analysis[top_n:])
    if other_library_size > 0:
        library_labels.append("其他库/模块")
        library_sizes.append(other_library_size)

    library_chart_data = {
        "labels": library_labels,
        "datasets": [{
            "label": '库/模块大小',
            "data": library_sizes,
            "backgroundColor": [ # Generate some colors (can be improved)
                f'hsl({(i * 360 / (top_n + 1)) % 360}, 70%, 60%)' for i in range(len(library_labels))
            ],
            "hoverOffset": 4
        }]
    }

    # Section Size Chart (Pie Chart)
    section_chart_labels = []
    section_chart_sizes = []
    if sections:
         size_by_segment = defaultdict(int)
    for addr, section in sections.items():
        size_by_segment[section['segment']] += section['size']
        sorted_segments = sorted(size_by_segment.items(), key=lambda x: x[1], reverse=True)
        section_chart_labels = [seg for seg, _ in sorted_segments]
        section_chart_sizes = [size for _, size in sorted_segments]

    section_chart_data = {
        "labels": section_chart_labels,
         "datasets": [{
             "label": '段大小',
             "data": section_chart_sizes,
             "backgroundColor": [
                 f'hsl({(i * 60 + 180) % 360}, 65%, 55%)' for i in range(len(section_chart_labels)) # Different color scheme
             ],
             "hoverOffset": 4
         }]
    }


    # --- Table Generation ---
    library_table_rows = ""
    total_symbol_size = sum(s for _, s, _, _ in library_analysis)
    for i, (library, size, files, symbols_list) in enumerate(library_analysis[:top_n]):
        percentage = size / total_symbol_size * 100 if total_symbol_size > 0 else 0
        example_files = ", ".join([os.path.basename(f) for f in files[:2]])
        if len(files) > 2: example_files += ", ..."
        library_table_rows += f"""
        <tr>
            <td>{i+1}</td>
            <td>{library}</td>
            <td>{format_size(size)} ({percentage:.1f}%)</td>
            <td>{len(files)}</td>
            <td>{len(symbols_list)}</td>
            <td>{example_files}</td>
        </tr>"""
    if len(library_analysis) > top_n: library_table_rows += f"<tr><td colspan='6'>... (还有 {len(library_analysis)-top_n} 个库/模块) ...</td></tr>"

    file_table_rows = ""
    for i, (filepath, size, symbols_list) in enumerate(symbols_analysis[:top_n]):
         percentage = size / total_symbol_size * 100 if total_symbol_size > 0 else 0
         largest_symbol_name = "-"
         largest_symbol_size = 0
         if symbols_list:
             largest_symbol = max(symbols_list, key=lambda s: s['size'])
             largest_symbol_name = largest_symbol['demangled_name'] if largest_symbol['demangled_name'] else largest_symbol['name']
             largest_symbol_size = largest_symbol['size']
             if len(largest_symbol_name) > 40: largest_symbol_name = largest_symbol_name[:37] + "..."
         display_filepath = filepath
         if len(display_filepath) > 50: display_filepath = "..." + display_filepath[-47:]

         file_table_rows += f"""
         <tr>
             <td>{i+1}</td>
             <td>{display_filepath}</td>
             <td>{format_size(size)} ({percentage:.1f}%)</td>
             <td>{len(symbols_list)}</td>
             <td>{largest_symbol_name} ({format_size(largest_symbol_size)})</td>
         </tr>"""
    if len(symbols_analysis) > top_n: file_table_rows += f"<tr><td colspan='5'>... (还有 {len(symbols_analysis)-top_n} 个文件) ...</td></tr>"

    # Warnings
    warnings_html = ""
    if potential_warnings:
        warnings_html = "<div class='section warnings'><h2>潜在问题与警告</h2><ul>"
        # Simple formatting, replace newlines with list items
        warning_text = "\n".join(potential_warnings).strip()
        # Split by ## for major sections, then by \n for lines
        sections_warn = warning_text.split('\n## ')
        for section_w in sections_warn:
            if not section_w.strip(): continue
            lines_w = section_w.strip().split('\n')
            title_w = f"<h3>{lines_w[0]}</h3>" if lines_w else ""
            items_w = "".join([f"<li>{line.strip()}</li>" for line in lines_w[1:] if line.strip()])
            warnings_html += f"{title_w}<ul>{items_w}</ul>"

        warnings_html += "</ul></div>"


    # --- HTML Structure ---
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Link Map 分析报告 - {linkmap_name}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background-color: #f8f9fa; color: #212529; }}
        .container {{ max-width: 1200px; margin: auto; background-color: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #007bff; border-bottom: 2px solid #dee2e6; padding-bottom: 10px; margin-top: 30px; }}
        h1 {{ text-align: center; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 25px 0; box-shadow: 0 2px 3px rgba(0,0,0,0.05); }}
        th, td {{ padding: 12px 15px; text-align: left; border: 1px solid #dee2e6; }}
        th {{ background-color: #e9ecef; font-weight: 600; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
        .increase {{ color: #dc3545; font-weight: bold; }} /* Red for increase */
        .decrease {{ color: #28a745; font-weight: bold; }} /* Green for decrease */
        .nochange {{ color: #6c757d; }}
        .chart-container {{ display: flex; justify-content: space-around; flex-wrap: wrap; margin: 30px 0; }}
        .chart-box {{ width: 45%; min-width: 300px; margin-bottom: 20px; padding: 15px; background: #fff; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
        canvas {{ max-width: 100%; height: auto; }}
        .section {{ margin-bottom: 30px; }}
        .summary p {{ font-size: 1.1em; margin: 8px 0; }}
        .summary strong {{ font-weight: 600; }}
        .metadata p {{ margin: 5px 0; color: #6c757d; }}
    </style>
</head>
<body>
    <div class="container">
    <h1>Link Map 分析报告</h1>
         <div class="metadata section">
             <p><strong>文件:</strong> {linkmap_name}</p>
             <p><strong>报告时间:</strong> {report_time}</p>
             <p><strong>总符号大小:</strong> {format_size(total_symbol_size)}</p>
    </div>
    
    <div class="chart-container">
             <div class="chart-box">
                 <h2>库/模块大小分布 (Top {top_n})</h2>
                 <canvas id="libraryChart"></canvas>
    </div>
             <div class="chart-box">
                 <h2>段 (Segment) 大小分布</h2>
                 <canvas id="sectionChart"></canvas>
             </div>
         </div>

        {warnings_html}

        <div class="section">
            <h2>库/模块大小分析 (Top {top_n})</h2>
            <table>
                <thead><tr><th>排名</th><th>库/模块</th><th>大小</th><th>文件数</th><th>符号数</th><th>主要文件 (示例)</th></tr></thead>
                <tbody>{library_table_rows}</tbody>
    </table>
    </div>

        <div class="section">
            <h2>文件大小分析 (Top {top_n})</h2>
    <table>
                <thead><tr><th>排名</th><th>文件路径</th><th>大小</th><th>符号数</th><th>最大符号 (示例)</th></tr></thead>
                <tbody>{file_table_rows}</tbody>
    </table>
        </div>
    </div>
    
    <script>
        const libraryCtx = document.getElementById('libraryChart');
        new Chart(libraryCtx, {{
            type: 'pie',
            data: {json.dumps(library_chart_data)},
            options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'top' }} }} }}
        }});
        
        const sectionCtx = document.getElementById('sectionChart');
        new Chart(sectionCtx, {{
            type: 'pie',
            data: {json.dumps(section_chart_data)},
            options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ position: 'top' }} }} }}
        }});
    </script>
</body>
</html>
    """
    
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML 报告已保存到: {filepath}")
    except IOError as e:
        print(f"错误: 无法写入 HTML 报告 {filepath}: {e}")

def compare_linkmaps(file1, file2, output_file=None, html_output_file=None, top_n=20):
    """比较两个 Link Map 文件。"""
    print(f"开始比较 Link Map 文件: {os.path.basename(file1)} vs {os.path.basename(file2)}")

    sections1, symbols1, obj_files1 = parse_linkmap(file1)
    sections2, symbols2, obj_files2 = parse_linkmap(file2)

    if sections1 is None or symbols1 is None or sections2 is None or symbols2 is None:
         print("错误：无法完成比较，因为一个或两个文件解析失败。")
         return

    lib_analysis1 = analyze_symbols_by_library(symbols1, obj_files1)
    lib_analysis2 = analyze_symbols_by_library(symbols2, obj_files2)

    file_analysis1 = analyze_symbols(symbols1, obj_files1)
    file_analysis2 = analyze_symbols(symbols2, obj_files2)

    # --- 数据处理与比较 ---
    lib_data1 = {lib: {'size': size, 'files': files, 'symbols': s_list} for lib, size, files, s_list in lib_analysis1}
    lib_data2 = {lib: {'size': size, 'files': files, 'symbols': s_list} for lib, size, files, s_list in lib_analysis2}

    file_data1 = {fpath: {'size': size, 'symbols': s_list} for fpath, size, s_list in file_analysis1}
    file_data2 = {fpath: {'size': size, 'symbols': s_list} for fpath, size, s_list in file_analysis2}

    all_libs = set(lib_data1.keys()) | set(lib_data2.keys())
    all_files = set(file_data1.keys()) | set(file_data2.keys())

    lib_comparison = []
    for lib in all_libs:
        size1 = lib_data1.get(lib, {}).get('size', 0)
        size2 = lib_data2.get(lib, {}).get('size', 0)
        diff = size2 - size1
        if diff != 0: # Only show changes
             lib_comparison.append({'name': lib, 'size1': size1, 'size2': size2, 'diff': diff})

    file_comparison = []
    for fpath in all_files:
        size1 = file_data1.get(fpath, {}).get('size', 0)
        size2 = file_data2.get(fpath, {}).get('size', 0)
        diff = size2 - size1
        if diff != 0: # Only show changes
            file_comparison.append({'name': fpath, 'size1': size1, 'size2': size2, 'diff': diff})
    
    # 按差异大小排序
    lib_comparison.sort(key=lambda x: abs(x['diff']), reverse=True)
    file_comparison.sort(key=lambda x: abs(x['diff']), reverse=True)

    total_size1 = sum(item['size1'] for item in lib_comparison) + sum(s['size'] for l,s in lib_data1.items() if l not in {c['name'] for c in lib_comparison})
    total_size2 = sum(item['size2'] for item in lib_comparison) + sum(s['size'] for l,s in lib_data2.items() if l not in {c['name'] for c in lib_comparison})
    total_diff = total_size2 - total_size1


    # --- 生成比较报告 (文本) ---
    report = []
    report.append(f"--- Link Map 比较报告 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")
    report.append(f"文件 1 (旧): {os.path.basename(file1)}")
    report.append(f"文件 2 (新): {os.path.basename(file2)}")
    report.append("")
    report.append("## 总体变化:")
    report.append(f"旧版本总符号大小: {format_size(total_size1)}")
    report.append(f"新版本总符号大小: {format_size(total_size2)}")
    report.append(f"变化量: {format_size(total_diff)} ({'+' if total_diff >= 0 else ''}{(total_diff / total_size1 * 100) if total_size1 else 0:.1f}%)")
    report.append("")
    
    report.append(f"## 库/模块变化 (Top {top_n} 绝对值变化):")
    report.append("|排名|库/模块        | 旧大小   | 新大小   | 变化量   |")
    report.append("|---|---------------|----------|----------|----------|")
    for i, item in enumerate(lib_comparison[:top_n]):
         report.append(f"|{i+1:<3}|{item['name']:<15}|{format_size(item['size1']):<10}|{format_size(item['size2']):<10}|{format_size(item['diff']):<10} ({'+' if item['diff'] >= 0 else ''}{(item['diff'] / item['size1'] * 100) if item['size1'] else 0:.1f}%)|")
    if len(lib_comparison) > top_n: report.append("|...| ... | ... | ... | ... |")
    report.append("")

    report.append(f"## 文件变化 (Top {top_n} 绝对值变化):")
    report.append("|排名|文件路径             | 旧大小   | 新大小   | 变化量   |")
    report.append("|---|----------------------|----------|----------|----------|")
    for i, item in enumerate(file_comparison[:top_n]):
         display_name = item['name']
         if len(display_name) > 50: display_name = "..." + display_name[-47:]
         report.append(f"|{i+1:<3}|{display_name:<22}|{format_size(item['size1']):<10}|{format_size(item['size2']):<10}|{format_size(item['diff']):<10} ({'+' if item['diff'] >= 0 else ''}{(item['diff'] / item['size1'] * 100) if item['size1'] else 0:.1f}%)|")
    if len(file_comparison) > top_n: report.append("|...| ... | ... | ... | ... |")
    report.append("")


    report_text = "\n".join(report)
    if output_file:
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_text)
            print(f"比较报告已保存到: {output_file}")
        except IOError as e:
            print(f"错误: 无法写入比较报告 {output_file}: {e}")
            print("\n" + report_text) # Fallback to console
    else:
        print("\n" + report_text)


    # --- 生成比较报告 (HTML) ---
    if html_output_file:
         generate_comparison_html_report(html_output_file, file1, file2, total_size1, total_size2, lib_comparison, file_comparison, top_n)

def generate_comparison_html_report(filepath, file1, file2, total_size1, total_size2, lib_comparison, file_comparison, top_n):
    """生成 HTML 格式的比较报告。"""
    file1_name = os.path.basename(file1)
    file2_name = os.path.basename(file2)
    report_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_diff = total_size2 - total_size1
    total_percentage = (total_diff / total_size1 * 100) if total_size1 else 0

    # --- Chart Data ---
    # Top Library Increases
    lib_increases = sorted([item for item in lib_comparison if item['diff'] > 0], key=lambda x: x['diff'], reverse=True)[:top_n]
    lib_increase_labels = [item['name'] for item in lib_increases]
    lib_increase_data = [item['diff'] for item in lib_increases]

    # Top Library Decreases
    lib_decreases = sorted([item for item in lib_comparison if item['diff'] < 0], key=lambda x: x['diff'])[:top_n]
    lib_decrease_labels = [item['name'] for item in lib_decreases]
    lib_decrease_data = [abs(item['diff']) for item in lib_decreases] # Use absolute value for chart

    lib_increase_chart = {
         "labels": lib_increase_labels,
         "datasets": [{"label": '体积增加量 (Bytes)', "data": lib_increase_data, "backgroundColor": 'rgba(255, 99, 132, 0.6)'}]
    }
    lib_decrease_chart = {
         "labels": lib_decrease_labels,
         "datasets": [{"label": '体积减少量 (Bytes)', "data": lib_decrease_data, "backgroundColor": 'rgba(75, 192, 192, 0.6)'}]
    }

    # --- Table Rows ---
    def format_diff(diff, old_size):
        sign = '+' if diff >= 0 else ''
        percentage = f"({sign}{(diff / old_size * 100) if old_size else 0:.1f}%)" if old_size is not None else ""
        color_class = "increase" if diff > 0 else ("decrease" if diff < 0 else "nochange")
        return f"<span class='{color_class}'>{format_size(diff)} {percentage}</span>"

    lib_rows = ""
    for i, item in enumerate(lib_comparison[:top_n]):
         lib_rows += f"""
         <tr>
             <td>{i+1}</td>
             <td>{item['name']}</td>
             <td>{format_size(item['size1'])}</td>
             <td>{format_size(item['size2'])}</td>
             <td>{format_diff(item['diff'], item['size1'])}</td>
         </tr>"""
    if len(lib_comparison) > top_n: lib_rows += f"<tr><td colspan='5'>... (还有 {len(lib_comparison)-top_n} 个变化的库) ...</td></tr>"

    file_rows = ""
    for i, item in enumerate(file_comparison[:top_n]):
         display_name = item['name']
         if len(display_name) > 45: display_name = "..." + display_name[-42:]
         file_rows += f"""
         <tr>
             <td>{i+1}</td>
             <td>{display_name}</td>
             <td>{format_size(item['size1'])}</td>
             <td>{format_size(item['size2'])}</td>
             <td>{format_diff(item['diff'], item['size1'])}</td>
         </tr>"""
    if len(file_comparison) > top_n: file_rows += f"<tr><td colspan='5'>... (还有 {len(file_comparison)-top_n} 个变化的文件) ...</td></tr>"

    # --- HTML Structure ---
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>Link Map 比较报告</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; background-color: #f8f9fa; color: #212529; }}
        .container {{ max-width: 1200px; margin: auto; background-color: #fff; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
        h1, h2 {{ color: #007bff; border-bottom: 2px solid #dee2e6; padding-bottom: 10px; margin-top: 30px; }}
        h1 {{ text-align: center; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 25px 0; box-shadow: 0 2px 3px rgba(0,0,0,0.05); }}
        th, td {{ padding: 12px 15px; text-align: left; border: 1px solid #dee2e6; }}
        th {{ background-color: #e9ecef; font-weight: 600; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
        .increase {{ color: #dc3545; font-weight: bold; }} /* Red for increase */
        .decrease {{ color: #28a745; font-weight: bold; }} /* Green for decrease */
        .nochange {{ color: #6c757d; }}
        .chart-container {{ display: flex; justify-content: space-around; flex-wrap: wrap; margin: 30px 0; }}
        .chart-box {{ width: 45%; min-width: 300px; margin-bottom: 20px; padding: 15px; background: #fff; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.08); }}
        canvas {{ max-width: 100%; height: auto; }}
        .section {{ margin-bottom: 30px; }}
        .summary p {{ font-size: 1.1em; margin: 8px 0; }}
        .summary strong {{ font-weight: 600; }}
        .metadata p {{ margin: 5px 0; color: #6c757d; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Link Map 比较报告</h1>
         <div class="metadata section">
             <p><strong>文件 1 (旧):</strong> {file1_name}</p>
             <p><strong>文件 2 (新):</strong> {file2_name}</p>
             <p><strong>报告时间:</strong> {report_time}</p>
         </div>

        <div class="summary section">
        <h2>总体变化</h2>
            <p><strong>旧版本总符号大小:</strong> {format_size(total_size1)}</p>
            <p><strong>新版本总符号大小:</strong> {format_size(total_size2)}</p>
            <p><strong>变化量:</strong> {format_diff(total_diff, total_size1)}</p>
    </div>
    
    <div class="chart-container">
             <div class="chart-box">
                 <h2>库/模块体积增加 Top {top_n}</h2>
                 <canvas id="libIncreaseChart"></canvas>
    </div>
             <div class="chart-box">
                 <h2>库/模块体积减少 Top {top_n}</h2>
                 <canvas id="libDecreaseChart"></canvas>
             </div>
         </div>

        <div class="section">
            <h2>库/模块变化详情 (Top {top_n} 绝对值变化)</h2>
            <table>
                <thead><tr><th>排名</th><th>库/模块</th><th>旧大小</th><th>新大小</th><th>变化量</th></tr></thead>
                <tbody>{lib_rows}</tbody>
    </table>
        </div>
    
        <div class="section">
            <h2>文件变化详情 (Top {top_n} 绝对值变化)</h2>
    <table>
                <thead><tr><th>排名</th><th>文件路径</th><th>旧大小</th><th>新大小</th><th>变化量</th></tr></thead>
                <tbody>{file_rows}</tbody>
    </table>
        </div>
    </div>
    
    <script>
        const libIncreaseCtx = document.getElementById('libIncreaseChart');
        new Chart(libIncreaseCtx, {{
            type: 'bar',
            data: {json.dumps(lib_increase_chart)},
            options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
        }});

        const libDecreaseCtx = document.getElementById('libDecreaseChart');
        new Chart(libDecreaseCtx, {{
             type: 'bar',
             data: {json.dumps(lib_decrease_chart)},
             options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }} }}
        }});
    </script>
</body>
</html>
    """
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"HTML 比较报告已保存到: {filepath}")
    except IOError as e:
        print(f"错误: 无法写入 HTML 比较报告 {filepath}: {e}")


# --- 主程序 ---

def main():
    parser = argparse.ArgumentParser(description="分析 Link Map 文件，展示符号大小分布并提供优化建议。")
    parser.add_argument("linkmap_file", help="Link Map 文件路径")
    parser.add_argument("-o", "--output", help="输出文本报告的文件路径", default=None)
    parser.add_argument("--csv", help="输出 CSV 格式报告的路径", default=None)
    parser.add_argument("--json", help="输出 JSON 格式报告的路径", default=None)
    parser.add_argument("--html", help="输出 HTML 格式报告的路径（包含图表）", default=None)
    parser.add_argument("--top", type=int, default=20, help="在报告中显示 Top N 个条目，默认为 20")
    parser.add_argument("--compare", help="要比较的旧版本 Link Map 文件路径", default=None)
    parser.add_argument("--compare-output", help="文本比较报告的输出路径", default=None)
    parser.add_argument("--compare-html", help="HTML 比较报告的输出路径", default=None)
    parser.add_argument("--warn-size-kb", type=int, default=50, help="大符号警告阈值 (KB)，默认为 50 KB")


    args = parser.parse_args()

    if args.compare:
        compare_linkmaps(args.compare, args.linkmap_file, args.compare_output, args.compare_html, args.top)
    else:
        sections, symbols, object_files = parse_linkmap(args.linkmap_file)
        
        if sections is None and symbols is None:
            sys.exit(1) # 解析失败

        if not symbols:
            print("错误：未能解析出任何 Symbols 数据。无法生成分析报告。")
            sys.exit(1)
            
        # Perform analysis
        symbols_analysis = analyze_symbols(symbols, object_files)
        library_analysis = analyze_symbols_by_library(symbols, object_files)
        potential_warnings = detect_potential_issues(symbols_analysis, library_analysis, args.top, args.warn_size_kb)
        
        
        # Generate reports
        report_text = generate_report(args.linkmap_file, sections, symbols_analysis, library_analysis, args.top, potential_warnings)

        if args.output:
            try:
                with open(args.output, 'w', encoding='utf-8') as f:
                    f.write(report_text)
                print(f"文本报告已保存到: {args.output}")
            except IOError as e:
                print(f"错误: 无法写入文本报告 {args.output}: {e}")
                print("\n" + report_text) # Fallback to console
        else:
            print("\n" + report_text)

        if args.csv:
            generate_csv_report(args.csv, library_analysis, symbols_analysis)
        
        if args.json:
             generate_json_report(args.json, sections, library_analysis, symbols_analysis)
            
        if args.html:
             generate_html_report(args.html, args.linkmap_file, sections, library_analysis, symbols_analysis, args.top, potential_warnings)


if __name__ == "__main__":
    main()
