#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
from pathlib import Path
import sys
from datetime import datetime
import subprocess
import shlex
import os

# --- 颜色和格式支持 ---
# ANSI颜色代码
COLORS = {
    "GREEN": "\033[92m",  # 绿色 - 用于OK状态
    "RED": "\033[91m",    # 红色 - 用于错误/不匹配状态
    "YELLOW": "\033[93m", # 黄色 - 用于警告/缺失状态
    "BLUE": "\033[94m",   # 蓝色 - 用于标题和提示
    "CYAN": "\033[96m",   # 青色 - 用于分类标题
    "GRAY": "\033[90m",   # 灰色 - 用于次要信息
    "BOLD": "\033[1m",    # 粗体
    "UNDERLINE": "\033[4m", # 下划线
    "END": "\033[0m"      # 结束颜色编码
}

# 设置分类
SETTING_CATEGORIES = {
    "编译优化": ["GCC_OPTIMIZATION_LEVEL", "SWIFT_OPTIMIZATION_LEVEL", "SWIFT_COMPILATION_MODE"],
    "代码剥离": ["STRIP_STYLE", "STRIP_SWIFT_SYMBOLS", "COPY_PHASE_STRIP", "DEAD_CODE_STRIPPING"],
    "链接优化": ["ENABLE_LTO", "DEPLOYMENT_POSTPROCESSING"],
    "其他设置": ["ENABLE_BITCODE", "ASSETCATALOG_COMPILER_OPTIMIZATION"]
}

# 检测终端是否支持颜色输出
def supports_color():
    """检测当前终端是否支持颜色输出。"""
    # 如果环境变量明确禁用颜色
    if os.environ.get('NO_COLOR') or os.environ.get('CLICOLOR_FORCE') == '0':
        return False
    # 如果环境变量明确启用颜色
    if os.environ.get('CLICOLOR_FORCE') == '1':
        return True
    # 如果stdout不是tty，通常不支持颜色
    if not sys.stdout.isatty():
        return False
    # 在类Unix系统上，检查TERM环境变量
    if os.environ.get('TERM') == 'dumb':
        return False
    # 大多数情况下支持颜色
    return True

# 颜色输出包装函数
def colored(text, color_code):
    """如果终端支持颜色，则返回带颜色的文本，否则返回原文本。"""
    if not supports_color():
        return text
    return f"{color_code}{text}{COLORS['END']}"

# --- 依赖检查与导入 ---
try:
    from pbxproj import XcodeProject
except ImportError:
    print("错误：缺少 pbxproj 库。请运行 'pip install pbxproj' 或 'pip3 install pbxproj' 进行安装。")
    sys.exit(1)

# --- 推荐的 Release 构建设置 ---
# 参考: README.md 和 Apple 官方文档
RECOMMENDED_RELEASE_SETTINGS = {
    # Code Generation
    "GCC_OPTIMIZATION_LEVEL": "s",  # Optimize for Size (-Os)
    "SWIFT_OPTIMIZATION_LEVEL": "-Osize", # Optimize for Size
    "SWIFT_COMPILATION_MODE": "wholemodule", # Whole Module Optimization

    # Linking
    "ENABLE_LTO": "YES", # Link-Time Optimization (Monolithic LTO)
    "DEAD_CODE_STRIPPING": "YES",

    # Deployment
    "DEPLOYMENT_POSTPROCESSING": "YES", # Enables Strip Linked Product, etc.

    # Symbols
    "STRIP_STYLE": "all", # All Symbols (ensure Debug Symbols are stripped too)
    "STRIP_SWIFT_SYMBOLS": "YES",
    "COPY_PHASE_STRIP": "YES", # Strips symbols from linked product (redundant if DEPLOYMENT_POSTPROCESSING=YES)

    # Bitcode (Optional but recommended for App Store)
    # Note: Bitcode is deprecated from Xcode 14. Check your Xcode version.
    # "ENABLE_BITCODE": "YES",

    # Asset Compilation
    "ASSETCATALOG_COMPILER_OPTIMIZATION": "space", # Optimize for space
}

# 设置名称和值的等效映射
# 用于处理Xcode UI显示和实际存储值之间的差异
SETTING_EQUIVALENTS = {
    # 名称等效 (Xcode可能使用的其他键名)
    'names': {
        # 大小写和格式变体
        'strip_style': 'STRIP_STYLE',           # 小写版本
        'stripStyle': 'STRIP_STYLE',            # 驼峰命名
        'StripStyle': 'STRIP_STYLE',            # 帕斯卡命名
        'Strip Style': 'STRIP_STYLE',           # UI显示名称
        'strip-style': 'STRIP_STYLE',           # 连字符分隔
        
        # Xcode特定别名
        'STRIP_INSTALLED_PRODUCT': 'STRIP_STYLE',  # Xcode可能使用的别名
        'LD_STRIP_INSTALLED_PRODUCT': 'STRIP_STYLE', # 另一个可能的别名
        'STRIPFLAGS': 'STRIP_STYLE',              # strip命令的标志
        
        # 其他设置的映射
        'optimization_level': 'GCC_OPTIMIZATION_LEVEL',
        'OptimizationLevel': 'GCC_OPTIMIZATION_LEVEL',
        'swift_opt_level': 'SWIFT_OPTIMIZATION_LEVEL',
        'link_time_optimization': 'ENABLE_LTO',
        'lto': 'ENABLE_LTO',
    },
    # 值等效 (Xcode可能使用的其他值)
    'values': {
        'STRIP_STYLE': {
            'all symbols': 'all',           # UI 显示值 vs 实际存储值
            'ALL': 'all',                   # 大写版本
            'All Symbols': 'all',           # UI可能显示的另一种形式
            'all-symbols': 'all',           # 连字符分隔
            'AllSymbols': 'all',            # 驼峰命名
            'debugging': 'debugging',       # 其他有效值，保持一致
            'non-global': 'non-global',     # 其他有效值，保持一致
        },
        'GCC_OPTIMIZATION_LEVEL': {
            '-Os': 's',                     # 命令行形式 vs Xcode内部存储
            'O1': '1',                      # 不同格式
            'O2': '2',                      # 不同格式
            'O3': '3',                      # 不同格式
            'O0': '0',                      # 不同格式
        },
        'SWIFT_OPTIMIZATION_LEVEL': {
            'Osize': '-Osize',              # 无连字符
            '-0size': '-Osize',             # 使用数字0而非字母O
            '0size': '-Osize',              # 无连字符且使用数字0
            '-O size': '-Osize',            # 包含空格
            'O size': '-Osize',             # 无连字符且包含空格
            '-OSIZE': '-Osize',             # 大写版本
            'OSIZE': '-Osize',              # 无连字符且大写
            '-osize': '-Osize',             # 小写版本
            'osize': '-Osize',              # 无连字符且小写
        }
    }
}

# Xcode默认设置值
# 当设置未在项目文件中明确指定时，Xcode会使用这些默认值
XCODE_DEFAULT_SETTINGS = {
    # Symbols
    "STRIP_STYLE": "all",              # 默认剥离所有符号
    "STRIP_SWIFT_SYMBOLS": "YES",       # 默认剥离Swift符号
    "DEAD_CODE_STRIPPING": "YES",       # 默认启用无效代码剥离
    
    # Optimization (部分平台/版本可能有不同默认值)
    "SWIFT_COMPILATION_MODE": "wholemodule",  # Release默认为整体模块优化
    "SWIFT_OPTIMIZATION_LEVEL": "-O",   # Release默认为标准优化级别
    
    # 其他常见默认值
    "ENABLE_BITCODE": "NO",            # 新版Xcode默认禁用Bitcode
    "ENABLE_TESTABILITY": "NO",        # Release默认禁用可测试性
    "VALIDATE_PRODUCT": "YES",         # Release默认验证产品
}

# 设置名称的友好描述
SETTING_DESCRIPTIONS = {
    "GCC_OPTIMIZATION_LEVEL": "Clang Optimization Level (代码生成优化级别)",
    "SWIFT_OPTIMIZATION_LEVEL": "Swift Optimization Level (Swift代码优化级别)",
    "SWIFT_COMPILATION_MODE": "Swift Compilation Mode (Swift编译模式)",
    "ENABLE_LTO": "Link-Time Optimization (链接时优化)",
    "DEAD_CODE_STRIPPING": "Dead Code Stripping (无效代码剥离)",
    "DEPLOYMENT_POSTPROCESSING": "Deployment Postprocessing (部署后处理)",
    "STRIP_STYLE": "Strip Style (符号剥离方式)",
    "STRIP_SWIFT_SYMBOLS": "Strip Swift Symbols (剥离Swift符号)",
    "COPY_PHASE_STRIP": "Strip Linked Product (剥离链接产品符号)",
    "ENABLE_BITCODE": "Enable Bitcode (启用 Bitcode)",
    "ASSETCATALOG_COMPILER_OPTIMIZATION": "Asset Catalog Compiler Optimization (资源目录编译器优化)",
}

# --- 核心功能 ---

def get_available_targets(project: XcodeProject) -> list:
    """获取项目中所有可用的Target名称列表。"""
    targets = []
    # 获取所有PBXNativeTarget类型的对象
    for section in project.objects.get_sections():
        if section == 'PBXNativeTarget':
            for obj in project.objects.get_objects_in_section(section):
                if hasattr(obj, 'name'):
                    targets.append(obj.name)
    return targets

def load_project(project_path_str: str) -> XcodeProject | None:
    """加载 Xcode 项目文件。"""
    project_path = Path(project_path_str)
    if not project_path.exists() or not project_path.is_dir() or not project_path.name.endswith(".xcodeproj"):
        print(f"错误：指定的路径不是有效的 .xcodeproj 目录: {project_path_str}")
        return None
    pbxproj_path = project_path / "project.pbxproj"
    if not pbxproj_path.exists():
        print(f"错误：在 {project_path} 中未找到 project.pbxproj 文件。")
        return None

    try:
        project = XcodeProject.load(str(pbxproj_path))
        print(f"成功加载项目: {project_path.name}")
        return project
    except Exception as e:
        print(f"加载项目时出错: {e}")
        return None

def compare_settings(current_settings: dict, recommended_settings: dict, debug_mode: bool = False, verbose_values: bool = False) -> list:
    """将当前设置与推荐设置进行比较。"""
    issues = []
    checked_keys = set()

    if debug_mode:
        print("\n调试：比较设置...")

    for key, recommended_value in recommended_settings.items():
        current_value = current_settings.get(key)
        checked_keys.add(key)
        description = SETTING_DESCRIPTIONS.get(key, key)
        
        if debug_mode or verbose_values:
            print(f"检查 {key}: 当前值={current_value}, 推荐值={recommended_value}")

        if current_value is None or current_value == "": # 假设 xcodebuild 对未设置返回空
            issues.append({
                "key": key,
                "description": description,
                "status": "missing", # 或者 "mismatch" 如果认为空值不等于推荐值
                "current": "未设置或为空",
                "recommended": recommended_value,
                "suggestion": f"建议设置 '{key}' 为 '{recommended_value}' 以优化包体积。"
            })
            continue
        
        # 值的标准化处理
        str_current = str(current_value).strip()
        str_recommended = str(recommended_value).strip()
        
        # 检查值的等效性
        if key in SETTING_EQUIVALENTS.get('values', {}):
            for alt_value, canonical_value in SETTING_EQUIVALENTS['values'][key].items():
                if str_current == alt_value:
                    if debug_mode or verbose_values:
                        print(f"'{key}' 的值 '{str_current}' 等效于 '{canonical_value}'")
                    str_current = canonical_value
                    break
        
        if str_current != str_recommended:
            # 特殊情况处理
            is_equivalent_opt = False
            if key == "GCC_OPTIMIZATION_LEVEL" and {str_current, str_recommended} == {"s", "-Os"}:
                is_equivalent_opt = True
                if verbose_values:
                    print(f"特殊处理: GCC_OPTIMIZATION_LEVEL的值 '{str_current}' 和 '{str_recommended}' 被视为等效")
            elif key == "SWIFT_OPTIMIZATION_LEVEL":
                normalized_current = str_current.lower().replace(" ", "").replace("0", "o")
                normalized_recommend = str_recommended.lower().replace(" ", "").replace("0", "o") 
                
                if verbose_values:
                    print(f"SWIFT_OPTIMIZATION_LEVEL值规范化:")
                    print(f"  当前值 '{str_current}' → 规范化为 '{normalized_current}'")
                    print(f"  推荐值 '{str_recommended}' → 规范化为 '{normalized_recommend}'")
                
                if normalized_current == "-osize" and normalized_recommend == "-osize":
                    if debug_mode or verbose_values:
                        print(f"SWIFT_OPTIMIZATION_LEVEL值比较成功: 当前值和推荐值规范化后均为'-osize'，视为等效")
                    is_equivalent_opt = True
            elif str_current.lower() == str_recommended.lower():
                is_equivalent_opt = True
                if debug_mode or verbose_values:
                    print(f"'{key}' 的值不区分大小写相等: '{str_current}' ≈ '{str_recommended}'")

            if not is_equivalent_opt:
                if verbose_values and key == "SWIFT_OPTIMIZATION_LEVEL":
                    print(f"警告: SWIFT_OPTIMIZATION_LEVEL值不匹配!")
                    print(f"  请检查实际值 '{str_current}' 与推荐值 '{str_recommended}' 的差异")
                    print(f"  如果确认应该匹配，可能需要更新脚本的值等效映射")
                    
                issues.append({
                    "key": key,
                    "description": description,
                    "status": "mismatch",
                    "current": str_current, # xcodebuild 返回的实际值
                    "recommended": recommended_value,
                    "suggestion": f"建议将 '{key}' 从 '{current_value}' 修改为 '{recommended_value}' 以优化包体积。"
                })
            else:
                issues.append({
                    "key": key,
                    "description": description,
                    "status": "ok",
                    "current": str_current,
                    "recommended": recommended_value,
                    "note": "值被视为等效"
                })
        else:
            issues.append({
                "key": key,
                "description": description,
                "status": "ok",
                "current": str_current,
                "recommended": recommended_value
            })

    return issues

# --- 报告生成 ---

def generate_text_report(issues: list, project_name: str, target_name: str | None, config_name: str) -> str:
    """生成文本格式的报告。"""
    report_lines = [
        colored(f"=== 构建设置检查报告 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===", COLORS["BOLD"] + COLORS["BLUE"]),
        colored(f"项目: {project_name}", COLORS["BOLD"]),
        colored(f"Target: {target_name if target_name else '项目级别'}", COLORS["BOLD"]),
        colored(f"Configuration: {config_name}", COLORS["BOLD"]),
        "",
        colored("检查结果:", COLORS["BOLD"] + COLORS["UNDERLINE"]),
        ""
    ]

    # 按状态和类别统计
    stats = {
        "ok": 0,
        "mismatch": 0,
        "missing": 0,
        "missing_with_default": 0
    }
    
    # 创建优先级问题列表
    high_priority = []
    medium_priority = []
    low_priority = []
    
    # 按类别分组问题
    categorized_issues = {}
    uncategorized = []
    
    for issue in issues:
        # 更新统计
        stats[issue["status"]] += 1
        if issue["status"] == "missing" and issue.get("xcode_default"):
            stats["missing_with_default"] += 1
        
        # 优先级分类
        if issue["status"] == "mismatch":
            high_priority.append(issue)
        elif issue["status"] == "missing" and (not issue.get("xcode_default") or issue.get("xcode_default") != issue["recommended"]):
            medium_priority.append(issue)
        elif issue["status"] == "missing":
            low_priority.append(issue)
        
        # 类别分组
        key = issue["key"]
        category = None
        for cat_name, keys in SETTING_CATEGORIES.items():
            if key in keys:
                category = cat_name
                break
        
        if category:
            if category not in categorized_issues:
                categorized_issues[category] = []
            categorized_issues[category].append(issue)
        else:
            uncategorized.append(issue)
    
    # 按类别展示问题
    for category, cat_issues in categorized_issues.items():
        report_lines.append(colored(f"【{category}】", COLORS["CYAN"] + COLORS["BOLD"]))
        report_lines.append("-" * 50)
        
        for issue in cat_issues:
            # 确定状态显示
            if issue["status"] == "ok":
                status_text = colored("[✓ 正常]", COLORS["GREEN"])
            elif issue["status"] == "mismatch":
                status_text = colored("[✗ 不匹配]", COLORS["RED"])
            else:  # missing
                status_text = colored("[? 未设置]", COLORS["YELLOW"])
            
            report_lines.append(f"{status_text} {issue['description']} ({issue['key']})")
            
            # 显示当前值
            current_value_text = issue['current']
            if issue["status"] == "ok":
                current_value_text = colored(current_value_text, COLORS["GREEN"])
            elif issue["status"] == "mismatch":
                current_value_text = colored(current_value_text, COLORS["RED"])
            
            report_lines.append(f"    当前值: {current_value_text}")
            
            if issue["status"] != "ok":
                # 显示推荐值
                report_lines.append(f"    推荐值: {colored(issue['recommended'], COLORS['BLUE'])}")
                
                # 显示建议
                suggestion_text = issue.get('suggestion', '')
                report_lines.append(f"    建议: {suggestion_text}")
            
            report_lines.append("") # 添加空行分隔
        
        report_lines.append("") # 类别之间添加空行
    
    # 处理未分类的问题
    if uncategorized:
        report_lines.append(colored("【其他未分类设置】", COLORS["CYAN"] + COLORS["BOLD"]))
        report_lines.append("-" * 50)
        # 重复上面的逻辑，处理未分类问题...
        for issue in uncategorized:
            # 与上面相同的显示逻辑...
            if issue["status"] == "ok":
                status_text = colored("[✓ 正常]", COLORS["GREEN"])
            elif issue["status"] == "mismatch":
                status_text = colored("[✗ 不匹配]", COLORS["RED"])
            else:  # missing
                status_text = colored("[? 未设置]", COLORS["YELLOW"])
            
            report_lines.append(f"{status_text} {issue['description']} ({issue['key']})")
            report_lines.append(f"    当前值: {issue['current']}")
            
            if issue["status"] != "ok":
                report_lines.append(f"    推荐值: {colored(issue['recommended'], COLORS['BLUE'])}")
                report_lines.append(f"    建议: {issue.get('suggestion', '')}")
            
            report_lines.append("")
    
    # 添加分隔线
    report_lines.append(colored("=" * 60, COLORS["GRAY"]))
    
    # 添加Xcode默认值说明
    if stats["missing_with_default"] > 0:
        report_lines.append(colored("【关于Xcode默认值的说明】", COLORS["BLUE"]))
        report_lines.append("部分标记为'未设置'的选项在Xcode中可能有默认值。")
        report_lines.append("如果项目依赖于Xcode的默认值，且默认值与推荐值不同，建议显式设置为推荐值以确保最佳优化。")
        report_lines.append("")
    
    # 添加统计摘要
    report_lines.append(colored("【统计摘要】", COLORS["BOLD"] + COLORS["BLUE"]))
    report_lines.append(f"总检查项: {len(issues)}")
    report_lines.append(f"正常项: {colored(str(stats['ok']), COLORS['GREEN'])}")
    report_lines.append(f"不匹配项: {colored(str(stats['mismatch']), COLORS['RED']) if stats['mismatch'] > 0 else stats['mismatch']}")
    report_lines.append(f"未设置项: {colored(str(stats['missing']), COLORS['YELLOW']) if stats['missing'] > 0 else stats['missing']} (其中 {stats['missing_with_default']} 项有Xcode默认值)")
    
    # 添加优先级建议
    if high_priority or medium_priority:
        report_lines.append("")
        report_lines.append(colored("【优先修改建议】", COLORS["BOLD"] + COLORS["BLUE"]))
        
        if high_priority:
            report_lines.append(colored("高优先级 (当前值与推荐值不匹配):", COLORS["RED"]))
            for issue in high_priority:
                report_lines.append(f"  • {issue['key']}: 当前 '{issue['current']}' → 推荐 '{issue['recommended']}'")
        
        if medium_priority:
            report_lines.append(colored("中优先级 (未设置且没有等效的默认值):", COLORS["YELLOW"]))
            for issue in medium_priority:
                report_lines.append(f"  • {issue['key']}: 推荐设置为 '{issue['recommended']}'")
    
    # 添加结论
    num_issues = stats["mismatch"] + stats["missing"]
    if num_issues == 0:
        report_lines.append("")
        report_lines.append(colored("结论：所有检查的设置均符合推荐值。✨", COLORS["GREEN"] + COLORS["BOLD"]))
    else:
        report_lines.append("")
        report_lines.append(colored(f"结论：发现 {num_issues} 个设置项与推荐值不符或缺失。建议按照优先级进行修改。", COLORS["YELLOW"] + COLORS["BOLD"]))

    return "\n".join(report_lines)

def generate_json_report(issues: list, project_name: str, target_name: str | None, config_name: str) -> str:
    """生成 JSON 格式的报告。"""
    # 统计和分类处理
    stats = {
        "ok": sum(1 for i in issues if i["status"] == "ok"),
        "mismatch": sum(1 for i in issues if i["status"] == "mismatch"),
        "missing": sum(1 for i in issues if i["status"] == "missing"),
        "missing_with_default": sum(1 for i in issues if i["status"] == "missing" and i.get("xcode_default"))
    }
    
    # 分类处理
    categorized_issues = {}
    for issue in issues:
        # 补充默认值与推荐值的比较结果
        if issue["status"] == "missing" and issue.get("xcode_default"):
            issue["default_matches_recommended"] = (issue["xcode_default"] == issue["recommended"])
        
        # 按类别分组
        key = issue["key"]
        category = None
        for cat_name, keys in SETTING_CATEGORIES.items():
            if key in keys:
                category = cat_name
                break
        
        if category:
            if category not in categorized_issues:
                categorized_issues[category] = []
            categorized_issues[category].append(issue)
    
    # 按优先级分组
    priority_issues = {
        "high": [i for i in issues if i["status"] == "mismatch"],
        "medium": [i for i in issues if i["status"] == "missing" and (not i.get("xcode_default") or i.get("xcode_default") != i["recommended"])],
        "low": [i for i in issues if i["status"] == "missing" and i.get("xcode_default") == i["recommended"]]
    }
    
    # 构建报告数据
    report_data = {
        "metadata": {
            "project": project_name,
            "target": target_name if target_name else "项目级别",
            "configuration": config_name,
            "timestamp": datetime.now().isoformat()
        },
        "statistics": stats,
        "issues_by_category": categorized_issues,
        "issues_by_priority": priority_issues,
        "issues": issues,
        "summary": {
            "total_issues": stats["mismatch"] + stats["missing"],
            "has_missing_with_defaults": stats["missing_with_default"] > 0
        }
    }
    
    # 添加Xcode默认值说明
    if stats["missing_with_default"] > 0:
        report_data["xcode_defaults_note"] = "部分标记为'未设置'的选项在Xcode中可能有默认值。如果项目依赖于Xcode的默认值，且默认值与推荐值不同，建议显式设置为推荐值以确保最佳优化。"
    
    return json.dumps(report_data, indent=2, ensure_ascii=False)

def generate_html_report(issues: list, project_name: str, target_name: str | None, config_name: str) -> str:
    """生成 HTML 格式的报告。"""
    # 统计和分类处理
    stats = {
        "ok": 0,
        "mismatch": 0,
        "missing": 0,
        "missing_with_default": 0
    }
    
    # 按类别分组问题
    categorized_issues = {}
    uncategorized = []
    
    # 创建优先级问题列表
    high_priority = []
    medium_priority = []
    low_priority = []
    
    for issue in issues:
        # 更新统计
        stats[issue["status"]] += 1
        if issue["status"] == "missing" and issue.get("xcode_default"):
            stats["missing_with_default"] += 1
        
        # 优先级分类
        if issue["status"] == "mismatch":
            high_priority.append(issue)
        elif issue["status"] == "missing" and (not issue.get("xcode_default") or issue.get("xcode_default") != issue["recommended"]):
            medium_priority.append(issue)
        elif issue["status"] == "missing":
            low_priority.append(issue)
        
        # 类别分组
        key = issue["key"]
        category = None
        for cat_name, keys in SETTING_CATEGORIES.items():
            if key in keys:
                category = cat_name
                break
        
        if category:
            if category not in categorized_issues:
                categorized_issues[category] = []
            categorized_issues[category].append(issue)
        else:
            uncategorized.append(issue)
    
    # 生成表格行
    category_tables = ""
    
    # 处理分类问题
    for category, cat_issues in categorized_issues.items():
        category_tables += f"""
        <div class="category-section">
            <h3>{category}</h3>
            <table class="settings-table">
                <thead>
                    <tr>
                        <th>检查项</th>
                        <th>当前值</th>
                        <th>推荐值</th>
                        <th>建议</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for issue in cat_issues:
            status_class = "status-ok" if issue["status"] == "ok" else ("status-mismatch" if issue["status"] == "mismatch" else "status-missing")
            status_icon = "✅" if issue["status"] == "ok" else ("❌" if issue["status"] == "mismatch" else "❓")
            status_text = "正常" if issue["status"] == "ok" else ("不匹配" if issue["status"] == "mismatch" else "未设置")
            
            # 构建建议信息，包含默认值提示
            suggestion = ""
            if issue["status"] != "ok":
                suggestion = f"<p class='suggestion'><strong>建议:</strong> {issue.get('suggestion', '')}</p>"
                
                # 如果是缺失设置且有Xcode默认值，添加默认值信息
                if issue["status"] == "missing" and issue.get("xcode_default"):
                    xcode_default_value = issue["xcode_default"]
                    if xcode_default_value == issue["recommended"]:
                        default_class = "default-matches"
                        default_note = "(默认值与推荐值一致，但显式设置可提高明确性)"
                    else:
                        default_class = "default-differs"
                        default_note = "(默认值与推荐值不同，建议显式设置为推荐值)"
                    
                    suggestion += f"<p class='xcode-default {default_class}'><strong>Xcode默认值:</strong> {xcode_default_value} <span class='note'>{default_note}</span></p>"
            
            category_tables += f"""
            <tr class="{status_class}" data-status="{issue['status']}">
                <td>
                    <span class="status-badge {issue['status']}">{status_icon} {status_text}</span>
                    <div class="setting-name">{issue['description']}</div>
                    <small>({issue['key']})</small>
                </td>
                <td class="value current-value">{issue['current']}</td>
                <td class="value recommended-value">{issue['recommended'] if issue['status'] != 'ok' else '-'}</td>
                <td>{suggestion}</td>
            </tr>
            """
        
        category_tables += """
                </tbody>
            </table>
        </div>
        """
    
    # 处理未分类问题
    if uncategorized:
        category_tables += """
        <div class="category-section">
            <h3>其他未分类设置</h3>
            <table class="settings-table">
                <thead>
                    <tr>
                        <th>检查项</th>
                        <th>当前值</th>
                        <th>推荐值</th>
                        <th>建议</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for issue in uncategorized:
            status_class = "status-ok" if issue["status"] == "ok" else ("status-mismatch" if issue["status"] == "mismatch" else "status-missing")
            status_icon = "✅" if issue["status"] == "ok" else ("❌" if issue["status"] == "mismatch" else "❓")
            status_text = "正常" if issue["status"] == "ok" else ("不匹配" if issue["status"] == "mismatch" else "未设置")
            
            suggestion = ""
            if issue["status"] != "ok":
                suggestion = f"<p class='suggestion'><strong>建议:</strong> {issue.get('suggestion', '')}</p>"
                
                if issue["status"] == "missing" and issue.get("xcode_default"):
                    xcode_default_value = issue["xcode_default"]
                    if xcode_default_value == issue["recommended"]:
                        default_class = "default-matches"
                        default_note = "(默认值与推荐值一致，但显式设置可提高明确性)"
                    else:
                        default_class = "default-differs"
                        default_note = "(默认值与推荐值不同，建议显式设置为推荐值)"
                    
                    suggestion += f"<p class='xcode-default {default_class}'><strong>Xcode默认值:</strong> {xcode_default_value} <span class='note'>{default_note}</span></p>"
            
            category_tables += f"""
            <tr class="{status_class}" data-status="{issue['status']}">
                <td>
                    <span class="status-badge {issue['status']}">{status_icon} {status_text}</span>
                    <div class="setting-name">{issue['description']}</div>
                    <small>({issue['key']})</small>
                </td>
                <td class="value current-value">{issue['current']}</td>
                <td class="value recommended-value">{issue['recommended'] if issue['status'] != 'ok' else '-'}</td>
                <td>{suggestion}</td>
            </tr>
            """
        
        category_tables += """
                </tbody>
            </table>
        </div>
        """
    
    # 准备统计和优先级建议
    summary_html = f"""
    <div class="summary-container">
        <div class="summary-box">
            <h3>统计摘要</h3>
            <table class="summary-table">
                <tr>
                    <td>总检查项:</td>
                    <td>{len(issues)}</td>
                </tr>
                <tr class="summary-ok">
                    <td>正常项:</td>
                    <td>{stats['ok']}</td>
                </tr>
                <tr class="summary-mismatch">
                    <td>不匹配项:</td>
                    <td>{stats['mismatch']}</td>
                </tr>
                <tr class="summary-missing">
                    <td>未设置项:</td>
                    <td>{stats['missing']} (其中 {stats['missing_with_default']} 项有Xcode默认值)</td>
                </tr>
            </table>
        </div>
    """
    
    # 添加优先级建议
    if high_priority or medium_priority:
        summary_html += """
        <div class="priority-box">
            <h3>优先修改建议</h3>
        """
        
        if high_priority:
            summary_html += """
            <div class="priority high-priority">
                <h4>高优先级 (当前值与推荐值不匹配):</h4>
                <ul>
            """
            for issue in high_priority:
                summary_html += f"""
                <li>{issue['key']}: 当前 '{issue['current']}' → 推荐 '{issue['recommended']}'</li>
                """
            summary_html += """
                </ul>
            </div>
            """
        
        if medium_priority:
            summary_html += """
            <div class="priority medium-priority">
                <h4>中优先级 (未设置且没有等效的默认值):</h4>
                <ul>
            """
            for issue in medium_priority:
                summary_html += f"""
                <li>{issue['key']}: 推荐设置为 '{issue['recommended']}'</li>
                """
            summary_html += """
                </ul>
            </div>
            """
        
        summary_html += """
        </div>
        """
    
    summary_html += """
    </div>
    """
    
    # 准备结论
    num_issues = stats["mismatch"] + stats["missing"]
    conclusion = f"""
    <div class="conclusion conclusion-{'ok' if num_issues == 0 else 'issue'}">
        <p>结论：{'所有检查的设置均符合推荐值。✨' if num_issues == 0 else f'发现 {num_issues} 个设置项与推荐值不符或缺失。建议按照优先级进行修改。'}</p>
    </div>
    """
    
    # 准备Xcode默认值说明
    xcode_defaults_note = ""
    if stats["missing_with_default"] > 0:
        xcode_defaults_note = """
        <div class="note-box">
            <h3>关于Xcode默认值的说明</h3>
            <p>部分标记为'未设置'的选项在Xcode中可能有默认值。如果项目依赖于Xcode的默认值，且默认值与推荐值不同，建议显式设置为推荐值以确保最佳优化。</p>
        </div>
        """
    
    # 生成过滤器控制
    filter_controls = """
    <div class="filter-controls">
        <h3>筛选结果</h3>
        <div class="button-group">
            <button class="filter-btn active" data-filter="all">显示全部</button>
            <button class="filter-btn" data-filter="mismatch">仅显示不匹配</button>
            <button class="filter-btn" data-filter="missing">仅显示未设置</button>
            <button class="filter-btn" data-filter="ok">仅显示正常</button>
        </div>
    </div>
    """

    # 完整HTML内容
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>构建设置检查报告</title>
    <style>
        :root {{
            --color-ok: #28a745;
            --color-mismatch: #dc3545;
            --color-missing: #ff9800;
            --color-info: #0056b3;
            --color-text: #333;
            --color-bg: #f9f9f9;
            --color-border: #ddd;
            --color-heading: #333;
            --color-highlight: #f1f1f1;
        }}
        
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; 
            margin: 0; 
            line-height: 1.6; 
            color: var(--color-text);
            background-color: #f3f3f3;
        }}
        
        .container {{ 
            max-width: 1200px; 
            margin: auto; 
            background: white; 
            padding: 30px; 
            border-radius: 8px; 
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-top: 20px;
            margin-bottom: 20px;
        }}
        
        h1, h2, h3, h4 {{ 
            color: var(--color-heading); 
            border-bottom: 1px solid #eee; 
            padding-bottom: 10px;
            margin-top: 30px;
        }}
        
        h1 {{ font-size: 28px; color: #2c3e50; }}
        h2 {{ font-size: 22px; }}
        h3 {{ font-size: 18px; margin-top: 25px; }}
        
        /* 表格样式 */
        .settings-table {{ 
            width: 100%; 
            border-collapse: collapse; 
            margin-top: 15px;
            margin-bottom: 30px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .settings-table th, 
        .settings-table td {{ 
            padding: 12px 15px; 
            text-align: left; 
            border-bottom: 1px solid var(--color-border);
        }}
        
        .settings-table th {{ 
            background-color: #f0f0f0; 
            font-weight: bold;
            position: sticky;
            top: 0;
            box-shadow: 0 1px 0 rgba(0,0,0,0.1);
        }}
        
        .settings-table tr:hover {{ 
            background-color: var(--color-highlight); 
        }}
        
        /* 状态标记样式 */
        .status-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-weight: bold;
            margin-bottom: 6px;
        }}
        
        .status-badge.ok {{
            background-color: rgba(40, 167, 69, 0.15);
            color: var(--color-ok);
            border: 1px solid rgba(40, 167, 69, 0.3);
        }}
        
        .status-badge.mismatch {{
            background-color: rgba(220, 53, 69, 0.15);
            color: var(--color-mismatch);
            border: 1px solid rgba(220, 53, 69, 0.3);
        }}
        
        .status-badge.missing {{
            background-color: rgba(255, 152, 0, 0.15);
            color: var(--color-missing);
            border: 1px solid rgba(255, 152, 0, 0.3);
        }}
        
        /* 行状态样式 */
        .status-ok {{ }}  /* Normal styling */
        .status-mismatch {{
            background-color: rgba(220, 53, 69, 0.03);
        }}
        .status-missing {{ 
            background-color: rgba(255, 152, 0, 0.03);
        }}
        
        /* 设置名称样式 */
        .setting-name {{
            font-weight: bold;
            margin-bottom: 3px;
        }}
        
        small {{ 
            color: #666; 
            font-size: 0.85em; 
            display: block;
        }}
        
        /* 值显示样式 */
        .value {{
            font-family: SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            padding: 2px 4px;
            background-color: #f8f9fa;
            border-radius: 3px;
            border: 1px solid #eaecef;
            font-size: 0.9em;
        }}
        
        /* 建议与默认值样式 */
        .suggestion {{ 
            margin: 5px 0; 
            color: #555; 
        }}
        
        .xcode-default {{ 
            margin: 8px 0; 
            padding: 8px; 
            border-radius: 4px; 
            font-size: 0.9em;
        }}
        
        .default-matches {{
            background-color: rgba(40, 167, 69, 0.08);
            border-left: 3px solid var(--color-ok);
        }}
        
        .default-differs {{
            background-color: rgba(255, 152, 0, 0.08);
            border-left: 3px solid var(--color-missing);
        }}
        
        .note {{
            font-style: italic;
            display: block;
            margin-top: 5px;
            color: #666;
        }}
        
        /* 结论样式 */
        .conclusion {{ 
            margin-top: 30px; 
            padding: 15px 20px; 
            border-radius: 5px; 
            font-weight: bold; 
            font-size: 1.1em;
            text-align: center;
        }}
        
        .conclusion-ok {{ 
            background-color: #e8f5e9; 
            border: 1px solid #c8e6c9; 
            color: #2e7d32; 
        }}
        
        .conclusion-issue {{ 
            background-color: #ffebee; 
            border: 1px solid #ffcdd2; 
            color: #c62828; 
        }}
        
        /* 说明框样式 */
        .note-box {{ 
            margin: 25px 0; 
            padding: 15px 20px; 
            background-color: #fff3cd; 
            border: 1px solid #ffeeba; 
            border-radius: 5px; 
            color: #856404; 
        }}
        
        .note-box h3 {{
            border-bottom: 1px solid rgba(133, 100, 4, 0.2);
            color: #856404;
            padding-bottom: 8px;
            margin-top: 0;
        }}
        
        /* 摘要与优先级建议样式 */
        .summary-container {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin: 30px 0;
        }}
        
        .summary-box, .priority-box {{
            flex: 1;
            min-width: 300px;
            background-color: #f8f9fa;
            border-radius: 8px;
            padding: 15px 20px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .summary-table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        .summary-table td {{
            padding: 8px 5px;
            border-bottom: 1px solid #eaecef;
        }}
        
        .summary-ok td:first-child {{ color: var(--color-ok); }}
        .summary-mismatch td:first-child {{ color: var(--color-mismatch); }}
        .summary-missing td:first-child {{ color: var(--color-missing); }}
        
        .priority h4 {{
            border-bottom: none;
            margin-bottom: 10px;
            padding-bottom: 0;
        }}
        
        .high-priority h4 {{ color: var(--color-mismatch); }}
        .medium-priority h4 {{ color: var(--color-missing); }}
        
        /* 过滤控制样式 */
        .filter-controls {{
            margin: 20px 0;
            padding: 15px;
            background-color: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #eaecef;
        }}
        
        .filter-controls h3 {{
            margin-top: 0;
            border-bottom: none;
            padding-bottom: 5px;
        }}
        
        .button-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        
        .filter-btn {{
            padding: 8px 15px;
            background-color: #f1f1f1;
            border: 1px solid #ddd;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        
        .filter-btn:hover {{
            background-color: #e2e6ea;
        }}
        
        .filter-btn.active {{
            background-color: #007bff;
            color: white;
            border-color: #0069d9;
        }}
        
        /* 类别分组样式 */
        .category-section {{
            margin-bottom: 30px;
            border: 1px solid #eaecef;
            border-radius: 8px;
            overflow: hidden;
        }}
        
        .category-section h3 {{
            margin: 0;
            padding: 15px;
            background-color: #f8f9fa;
            border-bottom: 1px solid #eaecef;
        }}
        
        /* 响应式调整 */
        @media (max-width: 768px) {{
            .container {{ padding: 15px; }}
            .settings-table th, 
            .settings-table td {{ 
                padding: 8px 10px;
                font-size: 0.9em;
            }}
            .summary-container {{ flex-direction: column; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>构建设置检查报告</h1>
        <p><strong>生成时间:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <p><strong>项目:</strong> {project_name}</p>
        <p><strong>Target:</strong> {target_name if target_name else '项目级别'}</p>
        <p><strong>Configuration:</strong> {config_name}</p>

        {summary_html}
        
        {filter_controls}

        <h2>检查结果</h2>
        {category_tables}
        
        {conclusion}
        {xcode_defaults_note}
    </div>
    
    <script>
        // 过滤功能
        document.addEventListener('DOMContentLoaded', function() {{
            const filterButtons = document.querySelectorAll('.filter-btn');
            
            filterButtons.forEach(btn => {{
                btn.addEventListener('click', function() {{
                    // 更新按钮状态
                    filterButtons.forEach(b => b.classList.remove('active'));
                    this.classList.add('active');
                    
                    // 获取过滤条件
                    const filter = this.getAttribute('data-filter');
                    
                    // 应用过滤
                    const rows = document.querySelectorAll('.settings-table tr[data-status]');
                    rows.forEach(row => {{
                        if (filter === 'all' || row.getAttribute('data-status') === filter) {{
                            row.style.display = '';
                        }} else {{
                            row.style.display = 'none';
                        }}
                    }});
                }});
            }});
        }});
    </script>
</body>
</html>
    """
    return html_content

def get_xcode_settings(project_path: str, target_name: str | None, config_name: str, debug_mode: bool = False) -> dict:
    """使用xcodebuild命令获取Xcode项目的实际有效设置。"""
    settings = {}
    try:
        # 构建命令
        cmd = ["xcodebuild", "-project", project_path, "-showBuildSettings"]
        if target_name:
            cmd.extend(["-target", target_name])
        if config_name:
            cmd.extend(["-configuration", config_name])
        
        if debug_mode:
            print(f"调试：执行命令: {' '.join(cmd)}")
        
        # 执行命令
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"获取Xcode设置时出错: {result.stderr}")
            return settings
        
        # 解析结果
        current_target = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
                
            # 检测目标部分
            if line.startswith("Build settings for"):
                current_target = line
                if debug_mode:
                    print(f"调试：处理设置部分: {current_target}")
                continue
                
            # 解析设置行
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                settings[key] = value
        
        if debug_mode:
            print(f"调试：从xcodebuild获取到 {len(settings)} 个设置")
    except Exception as e:
        print(f"调用xcodebuild时出错: {e}")
    
    return settings

def show_script_mode(debug_mode: bool) -> None:
    """显示脚本的运行信息。"""
    print(colored("【运行信息】", COLORS["BOLD"]) + ": " + colored("脚本将使用 xcodebuild 获取实际构建设置", COLORS["BLUE"]))
    if debug_mode:
        print(colored("【调试模式】", COLORS["RED"] + COLORS["BOLD"]) + ": " + colored("开启", COLORS["RED"]))
    print("")

# --- 主程序 ---

def main():
    parser = argparse.ArgumentParser(description="检查 Xcode 项目的构建设置与推荐的包体积优化设置进行对比。")
    parser.add_argument("project_path", help="Xcode 项目 (.xcodeproj) 的路径")
    parser.add_argument("-t", "--target", help="要检查的目标 Target 名称 (可选，默认为项目级别设置)", default=None)
    parser.add_argument("-c", "--config", help="要检查的 Build Configuration 名称", default="Release")
    parser.add_argument("-o", "--output", help="将报告输出到指定文件 (可选)", default=None)
    parser.add_argument("-f", "--format", help="输出格式 (text, json, html)", choices=["text", "json", "html"], default="text")
    parser.add_argument("-d", "--debug", help="启用调试模式，显示详细的设置信息", action="store_true")
    parser.add_argument("--no-color", help="禁用颜色输出", action="store_true")
    parser.add_argument("--color", help="强制启用颜色输出，即使在非终端环境", action="store_true")
    parser.add_argument("--group-by-category", help="按设置类别分组显示结果", action="store_true", default=True)
    parser.add_argument("--verbose-values", help="显示详细的值比较和规范化信息", action="store_true")

    args = parser.parse_args()

    # 处理颜色设置
    if args.no_color:
        os.environ['NO_COLOR'] = '1'
    elif args.color:
        os.environ['CLICOLOR_FORCE'] = '1'

    # 显示当前运行模式
    show_script_mode(args.debug)

    # Extract project name from path
    project_name = Path(args.project_path).stem

    # 直接使用 xcodebuild 获取设置
    print("使用 xcodebuild 获取实际的构建设置...")
    xcode_settings = get_xcode_settings(args.project_path, args.target, args.config, args.debug)

    # 错误检查
    if not xcode_settings:
        print(colored("错误：无法通过 xcodebuild 获取构建设置。请确保 Xcode 命令行工具已安装并配置正确。", COLORS["RED"]))
        sys.exit(1)

    # 显式打印 xcodebuild 获取的 SWIFT_OPTIMIZATION_LEVEL 值进行验证 (仍然有用)
    swift_opt_level_from_xcodebuild = xcode_settings.get("SWIFT_OPTIMIZATION_LEVEL", "未找到")
    print(colored(f"🔍 [xcodebuild 值验证] SWIFT_OPTIMIZATION_LEVEL = {swift_opt_level_from_xcodebuild}", COLORS["CYAN"] + COLORS["BOLD"]))
        
    # 处理别名映射
    current_settings = {}
    for key, value in xcode_settings.items():
        canonical_key = key
        for alt_name, canon_name in SETTING_EQUIVALENTS['names'].items():
            if key.lower() == alt_name.lower():
                canonical_key = canon_name
                if args.debug:
                    print(f"调试：将键 '{key}' 映射到标准键 '{canon_name}'")
                break
        current_settings[canonical_key] = value
            
    if args.debug:
        print(f"已从xcodebuild加载 {len(current_settings)} 个设置")
        print("\n调试：最终使用的设置:")
        for key, value in sorted(current_settings.items()):
            print(f"    {key} = {value}")

    # 确定推荐设置
    recommended_settings = {}
    if args.config == "Release":
        recommended_settings = RECOMMENDED_RELEASE_SETTINGS
    else:
        print(f"警告：当前检查的是 '{args.config}' 配置，但推荐的优化设置主要适用于 'Release' 配置。结果可能不完全相关。")
        recommended_settings = RECOMMENDED_RELEASE_SETTINGS # 仍然对比 Release 设置

    # 执行比较
    issues = compare_settings(current_settings, recommended_settings, args.debug, args.verbose_values)

    # 生成报告
    report_content = ""
    if args.format == "text":
        report_content = generate_text_report(issues, project_name, args.target, args.config)
    elif args.format == "json":
        report_content = generate_json_report(issues, project_name, args.target, args.config)
    elif args.format == "html":
        report_content = generate_html_report(issues, project_name, args.target, args.config)

    # 输出报告
    if args.output:
        try:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_content)
            print(f"报告已保存到: {output_path}")
        except IOError as e:
            print(f"错误：无法写入报告文件 {args.output}: {e}")
            print("\n报告内容:\n" + report_content)
    else:
        print("\n" + report_content)


if __name__ == "__main__":
    main() 