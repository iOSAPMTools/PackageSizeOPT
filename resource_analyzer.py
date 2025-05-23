#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 分析iOS项目中资源文件大小，按照文件大小进行排序；找出工程中没有引用到的资源文件；检测相似图片

import os
import argparse
import re
import plistlib
import json
from datetime import datetime
from pathlib import Path
import sys
import hashlib
import pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm  # 添加进度条库
import math # 用于计算图片像素

# --- Dependencies Check ---
try:
    from PIL import Image
except ImportError:
    print("错误：缺少 Pillow 库。请运行 'pip install Pillow' 或 'pip3 install Pillow' 进行安装。")
    sys.exit(1)

try:
    import imagehash
except ImportError:
    print("错误：缺少 ImageHash 库。请运行 'pip install ImageHash' 或 'pip3 install ImageHash' 进行安装。")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    print("错误：缺少 tqdm 库。请运行 'pip install tqdm' 或 'pip3 install tqdm' 进行安装。")
    sys.exit(1)

# --- Output Format Configuration ---
class OutputFormat:
    TEXT = 'text'
    JSON = 'json'
    HTML = 'html'
    CSV = 'csv'

# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>iOS 资源分析报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #f5f5f5; }}
        .large-resource {{ color: #ff3b30; }}
        .section {{ margin: 30px 0; }}
        .section-title {{ font-size: 1.5em; color: #007AFF; margin-bottom: 10px; }}
        .warning {{ color: #ff9500; }}
        .error {{ color: #ff3b30; }}
        .success {{ color: #34c759; }}
        .note {{ color: #8e8e93; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>iOS 资源分析报告</h1>
        <p>生成时间: {timestamp}</p>
        <p>项目路径: {project_dir}</p>
        
        <div class="section">
            <h2 class="section-title">资源大小统计</h2>
            <table>
                <tr>
                    <th>大小 (KB)</th>
                    <th>类型</th>
                    <th>标识符</th>
                    <th>路径</th>
                </tr>
                {resource_table}
            </table>
            <p>总资源大小: {total_size_mb:.2f} MB</p>
            <p>总图片资源大小: {total_image_size_mb:.2f} MB</p>
        </div>

        <div class="section">
            <h2 class="section-title">可能未使用的资源</h2>
            {unused_resources}
        </div>

        <div class="section">
            <h2 class="section-title">Asset Catalog 分析</h2>
            {asset_catalog_analysis}
        </div>

        <div class="section">
            <h2 class="section-title">相似图片组</h2>
            {similar_images}
        </div>

        <div class="section">
            <h2 class="section-title">资源优化建议</h2>
            {optimization_suggestions}
            <h3>WebP 转换建议</h3>
            {webp_suggestions}
        </div>
    </div>
</body>
</html>
"""

# --- Configuration ---

# Common resource file extensions (add more as needed)
RESOURCE_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', # Images
    '.pdf',                                          # Documents
    '.strings',                                      # Localization
    '.plist',                                        # Property Lists (can contain references)
    '.json',                                         # Data
    '.mp3', '.wav', '.aac', '.m4a',                  # Audio
    '.mp4', '.mov',                                  # Video
    '.ttf', '.otf',                                  # Fonts
    '.storyboard', '.xib',                           # Interface Builder
    # Note: .xcassets are handled separately
    '.dataset',                                      # ML Models Data
    '.mlmodel',                                      # ML Models
    '.scn',                                          # SceneKit Scenes
    '.usdz', '.reality',                             # AR/RealityKit
    '.rcproject',                                    # Reality Composer
    '.realityproj',                                  # Reality Composer Pro
    '.usda', '.usdc', '.usdz',                      # USD 3D Assets
    '.arobject', '.arreferenceobject',              # AR Resources
    '.arresourcegroup',                             # AR Resource Groups
    '.arworldmap',                                  # AR World Maps
    '.arcoachingoverlay',                           # AR Coaching Overlays
    '.arcoachingdata',                              # AR Coaching Data
    '.car'                                          # 已编译的资源文件
}

# 超大图片尺寸阈值（像素）
LARGE_IMAGE_WIDTH_THRESHOLD = 2000
LARGE_IMAGE_HEIGHT_THRESHOLD = 2000
# 超大图片尺寸与权重比阈值（KB/千像素）- 用于检测过度大小的图片
LARGE_IMAGE_SIZE_RATIO_THRESHOLD = 10.0  # KB/千像素

# Asset Catalog Types (extended)
ASSET_TYPES = (
    '.imageset', '.colorset', '.symbolset', '.appiconset', '.launchimage',
    '.dataset', '.spriteatlas', '.complicationset', '.brandassets', '.imagestack',
    '.cubetextureset', '.mipmapset', '.textureset', '.stickerpack',
    '.arresourcegroup', '.arobject', '.arreferenceobject', '.arworldmap',
    '.arcoachingoverlay', '.arcoachingdata', '.3dcontent', '.rcproject',
    '.realityproj', '.usda', '.usdc', '.usdz'
)

# Specific image extensions for hashing
IMAGE_EXTENSIONS = { '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff' }

# Files to search for references within
CODE_FILE_EXTENSIONS = {'.swift', '.m', '.h'}
INTERFACE_FILE_EXTENSIONS = {'.storyboard', '.xib'}
PLIST_FILE_EXTENSIONS = {'.plist'}
OTHER_SEARCH_EXTENSIONS = {'.json', '.strings'} # Files that might contain string names

# Directories to exclude from search
EXCLUDED_DIRS = {'Pods', 'build', '.git', '.svn', 'Carthage', 'DerivedData'}
EXCLUDED_DIR_PATTERNS = {'.framework', '.bundle', '.app', '.xcworkspace', '.xcodeproj'} # Also exclude bundle-like dirs by pattern

# Regex to find potential resource references in code (simple examples)
# Looks for "ResourceName" or 'ResourceName'
# Looks for UIImage(named: "ResourceName"), NSImage(named: "ResourceName")
# Looks for [UIImage imageNamed:@"ResourceName"], [NSImage imageNamed:@"ResourceName"]
# Looks for R.image.resourceName, R.string.resourceName etc. (R.swift) - adjust 'R' if needed
# Looks for SwiftUI Image("ResourceName")
# Now also looks for SwiftUI Image(systemName: "ResourceName")
CODE_REFERENCE_REGEX = re.compile(
    # UIKit/AppKit
    r'UIImage\(named:\s*["\']([\w\-\.]+)["\']\)|'          # Swift UIImage
    r'NSImage\(named:\s*["\']([\w\-\.]+)["\']\)|'          # Swift NSImage
    r'\[UIImage\s+imageNamed:\s*@?"([\w\-\.]+)"\]|'       # Obj-C UIImage
    r'\[NSImage\s+imageNamed:\s*@?"([\w\-\.]+)"\]|'       # Obj-C NSImage
    r'UIImage\(contentsOfFile:\s*["\']([\w\-\.]+)["\']\)|'  # UIImage(contentsOfFile:)
    r'NSImage\(contentsOfFile:\s*["\']([\w\-\.]+)["\']\)|'  # NSImage(contentsOfFile:)
    
    # SwiftUI
    r'Image\(\s*["\']([\w\-\.]+)["\']\)|'                   # SwiftUI Image("...")
    r'Image\(\s*systemName:\s*["\']([\w\-\.]+)["\']\)|'     # SwiftUI Image(systemName: "...")
    r'Image\(\s*decorative:\s*["\']([\w\-\.]+)["\']\)|'      # SwiftUI Image(decorative: "...")
    r'Label\([^,]+,\s*systemImage:\s*["\']([\w\-\.]+)["\']\)|'  # SwiftUI Label(_, systemImage: "...")
    r'Bundle\.main\.url\(forResource:\s*["\']([\w\-\.]+)["\']\)|'  # Bundle.main.url(forResource:)
    
    # 资源管理库
    r'\b[Rr]\.(image|color|file|font|string|asset)\.([\w\-\.]+)|'  # R.swift/SwiftGen
    r'Asset\.([\w\-\.]+)\.image|'                           # SwiftGen Assets
    r'L10n\.([\w\-\.]+)|'                                   # SwiftGen Localization
    r'ColorName\.([\w\-\.]+)|'                              # SwiftGen Colors
    r'FontFamily\.([\w\-\.]+)|'                             # SwiftGen Fonts
    
    # SF Symbols
    r'UIImage\(systemName:\s*["\']([\w\-\.]+)["\']\)|'      # UIImage(systemName:)
    r'NSImage\(symbolName:\s*["\']([\w\-\.]+)["\']\)|'       # NSImage(symbolName:)
    r'Symbol\(["\']([\w\-\.]+)["\']\)|'                      # Symbol("...")
    
    # 其他常见模式
    r'named:\s*["\']([\w\-\.]+)["\']\)|'                     # 通用named参数
    r'forResource:\s*["\']([\w\-\.]+)["\']\)|'               # 通用forResource参数
    r'NSLocalizedString\(["\']([\w\-\.]+)["\']'              # 本地化字符串
)

# 增加对常见动态字符串拼接模式的检测
DYNAMIC_PATTERN_REGEX = re.compile(
    r'(UIImage|NSImage)\(named:\s*\w+\s*\+\s*["\']([\w\-]+)["\']|'  # 变量 + "后缀" (Swift)
    r'(UIImage|NSImage)\(named:\s*["\']([\w\-]+)["\']\s*\+\s*\w+|'  # "前缀" + 变量 (Swift)
    r'imageNamed:\s*\[(\w+)\s+stringByAppendingString:\s*@"([\w\-]+)"\]|'  # [var stringByAppendingString:@"后缀"] (Obj-C)
    r'imageNamed:\s*\[@"([\w\-]+)"\s+stringByAppendingString:\s*\w+\]|'    # [@"前缀" stringByAppendingString:var] (Obj-C)
    r'NSString\s*\*\s*\w+\s*=\s*\[NSString\s+stringWithFormat:\s*@["\'][\w\-%@]+["\']\s*,\s*(\w+)\]|'  # 字符串格式化 (Obj-C)
    r'let\s+\w+\s*=\s*["\'][\w\-]+["\']\s*\+\s*\w+\s*\+\s*["\']([\w\-]+)["\']|'  # 多段拼接 (Swift)
    r'String\(format:\s*["\']([\w\-%s]+)["\']\s*,\s*\w+\)'  # 字符串格式化 (Swift)
)

# Regex to find potential resource references in XML-based files (Storyboards, XIBs)
# Looks for image="ResourceName", key="ResourceName" (often in user defined attributes), etc.
XML_REFERENCE_REGEX = re.compile(
    r'(?:image|name|key|resourceName)\s*=\s*["\']([\w\-]+)["\']|'         # 常规属性
    r'<imageView.*?image\s*=\s*["\']([\w\-]+)["\']|'                     # 图片视图
    r'customClass\s*=\s*["\']([\w\-]+)["\']|'                            # 自定义类名
    r'storyboardIdentifier\s*=\s*["\']([\w\-]+)["\']|'                   # 故事板标识符
    r'<resources>.*?<\s*image\s+name\s*=\s*["\']([\w\-]+)["\'].*?</resources>|'  # 资源部分
    r'value\s*=\s*["\']([\w\-]+\.png)["\']|'                             # 直接包含扩展名的资源
    r'filename\s*=\s*["\']([\w\-]+)["\']'                                # 文件名属性
)

# --- Image Similarity Configuration ---
HASH_ALGORITHM = imagehash.phash  # Algorithm to use (phash is good, dhash, ahash also available)
HASH_SIZE = 8                   # Hash size (higher means more precision but slower)
# SIMILARITY_THRESHOLD = 5        # Default Max Hamming distance, now configurable via CLI

# --- ANSI Color Codes for Highlighting ---
COLOR_RED = '\033[91m'
COLOR_RESET = '\033[0m'

# --- Helper Functions ---

def get_file_size(path):
    """Gets the size of a file."""
    try:
        return os.path.getsize(path)
    except OSError:
        return 0

def is_lproj_directory(path):
    """检查是否为本地化资源目录(.lproj)"""
    return os.path.isdir(path) and path.endswith('.lproj')

def analyze_lproj_directory(lproj_path, project_root):
    """分析本地化资源目录(.lproj)的内容"""
    locale = os.path.basename(lproj_path).split('.')[0]
    resources = {}
    total_size = 0
    
    try:
        for item in os.listdir(lproj_path):
            item_path = os.path.join(lproj_path, item)
            if os.path.isfile(item_path):
                rel_path = os.path.relpath(item_path, project_root)
                file_size = get_file_size(item_path)
                total_size += file_size
                
                # 创建本地化资源标识符
                base_name = os.path.splitext(item)[0]
                identifier = f"{base_name}_{locale}"  # 例如：Localizable_en
                
                # 处理 .strings 文件内部的字符串引用
                if item.endswith('.strings'):
                    strings_refs = extract_strings_file_references(item_path)
                    if strings_refs:
                        resources[identifier] = {
                            'path': rel_path,
                            'size': file_size,
                            'type': 'localization',
                            'locale': locale,
                            'string_keys': strings_refs
                        }
                    else:
                        resources[identifier] = {
                            'path': rel_path,
                            'size': file_size,
                            'type': 'localization',
                            'locale': locale
                        }
                else:
                    resources[identifier] = {
                        'path': rel_path,
                        'size': file_size,
                        'type': 'localization',
                        'locale': locale
                    }
    except OSError as e:
        print(f"警告：无法访问本地化目录 '{lproj_path}'：{e}")
    
    return resources, total_size

def extract_strings_file_references(strings_file_path):
    """从 .strings 文件中提取键和值"""
    references = set()
    try:
        with open(strings_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
        # 匹配 "Key" = "Value"; 格式的字符串
        matches = re.finditer(r'"([^"]+)"\s*=\s*"([^"]+)"\s*;', content)
        for match in matches:
            key = match.group(1)
            # value = match.group(2)  # 如果需要可以存储值
            references.add(key)
            
    except Exception as e:
        print(f"警告：无法解析 .strings 文件 '{strings_file_path}'：{e}")
    
    return references

def analyze_car_file(car_path):
    """分析已编译的资源文件(.car)，提取基本信息。
    
    注意：完整解析 CAR 文件需要特殊工具，此函数仅提供基本信息。
    """
    result = {
        'size': get_file_size(car_path),
        'type': 'compiled_asset',
        'identifier': os.path.basename(car_path),
    }
    
    # 尝试使用 assetutil 工具获取更多信息（仅在 macOS 上可用）
    try:
        import subprocess
        output = subprocess.check_output(['assetutil', car_path], stderr=subprocess.STDOUT, universal_newlines=True)
        # 简单解析输出
        if output:
            result['has_asset_info'] = True
            # 尝试提取资源名称
            name_match = re.search(r'Name:\s+([^\n]+)', output)
            if name_match:
                result['asset_name'] = name_match.group(1).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        # assetutil 不可用或执行失败
        result['has_asset_info'] = False
    
    return result

def get_dir_size(path):
    """Gets the total size of all files within a directory (recursively)."""
    total_size = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                # skip if it is symbolic link
                if not os.path.islink(fp):
                    total_size += get_file_size(fp)
    except OSError:
        pass # Ignore errors like permission denied
    return total_size

def should_exclude(path_str, project_root):
    """Checks if a path should be excluded."""
    relative_path = os.path.relpath(path_str, project_root)
    parts = Path(relative_path).parts
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    if any(part.endswith(tuple(EXCLUDED_DIR_PATTERNS)) for part in parts):
         return True
    # Check direct subdirectories of root against EXCLUDED_DIRS
    if len(parts) > 0 and parts[0] in EXCLUDED_DIRS:
        return True
    # Check for patterns anywhere in the path segments
    if any(p.endswith(tuple(EXCLUDED_DIR_PATTERNS)) for p in parts):
        return True
    return False


# 常见配置键，可能指向资源文件
CONFIG_RESOURCE_KEYS = {
    'CFBundleIconFile', 'CFBundleIconFiles', 'UILaunchImageFile', 
    'UIPrerenderedIcon', 'UIApplicationShortcutItemIconFile',
    'NSPhotoLibraryUsageDescription', 'NSCameraUsageDescription',
    'UIBackgroundModes', 'UIRequiredDeviceCapabilities',
    'UISupportedInterfaceOrientations', 'icon', 'artwork', 'background',
    'logo', 'bundle', 'resource', 'image', 'sound', 'media'
}

def extract_plist_strings(filepath):
    """Extracts all string values from a plist file."""
    strings = set()
    try:
        with open(filepath, 'rb') as fp:
            plist_data = plistlib.load(fp)

        def find_strings(data, parent_key=None):
            if isinstance(data, str):
                # Basic check to avoid adding overly long strings or potential paths
                if 1 < len(data) < 100 and not ('/' in data or '\\' in data):
                     # Extract potential resource name (part before '.' if exists)
                     base_name = data.split('.')[0]
                     if base_name:
                         strings.add(base_name)
                         if parent_key in CONFIG_RESOURCE_KEYS:
                             # 如果父键是已知的资源配置键，也添加完整值
                             strings.add(data)
            elif isinstance(data, dict):
                for key, value in data.items():
                    if isinstance(key, str) and 1 < len(key) < 100: # Add keys too, they might be resource names
                         base_key = key.split('.')[0]
                         if base_key:
                            strings.add(base_key)
                    find_strings(value, key)
            elif isinstance(data, list):
                for item in data:
                    find_strings(item)

        find_strings(plist_data)
    except Exception as e:
        # Ignore plist parsing errors (binary, corrupted, etc.)
        # print(f"Warning: Could not parse plist {filepath}: {e}")
        pass
    return strings

def scan_other_references(filepath, root_dir):
    """扫描其他类型文件中的资源引用，如 JSON 配置文件"""
    references = set()
    try:
        _, ext = os.path.splitext(filepath)
        ext_lower = ext.lower()
        
        # 处理 JSON 文件
        if ext_lower == '.json':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                try:
                    json_data = json.load(f)
                    
                    def extract_json_refs(data, parent_key=None):
                        if isinstance(data, str):
                            # 处理字符串值
                            if 1 < len(data) < 100 and not ('/' in data or '\\' in data):
                                if not data.startswith(('http', 'www')):
                                    base_name = data.split('.')[0]
                                    if base_name:
                                        references.add(base_name)
                                        if parent_key in CONFIG_RESOURCE_KEYS:
                                            references.add(data)
                        elif isinstance(data, dict):
                            # 处理字典
                            for key, value in data.items():
                                if isinstance(key, str) and key.lower() in {'image', 'icon', 'resource', 'file'}:
                                    # 特殊处理可能是资源引用的键
                                    if isinstance(value, str) and 1 < len(value) < 100:
                                        references.add(value)
                                        base_name = value.split('.')[0]
                                        if base_name != value:
                                            references.add(base_name)
                                extract_json_refs(value, key)
                        elif isinstance(data, list):
                            # 处理列表
                            for item in data:
                                extract_json_refs(item)
                    
                    extract_json_refs(json_data)
                except json.JSONDecodeError:
                    # 解析失败，尝试简单文本模式
                    f.seek(0)
                    content = f.read()
                    for line in content.splitlines():
                        if '"' in line or "'" in line:
                            # 简单提取引号内的内容
                            matches = re.findall(r'["\']([\w\-\.]+)["\']', line)
                            for match in matches:
                                if 1 < len(match) < 100 and not ('/' in match or '\\' in match):
                                    references.add(match)
                                    if '.' in match:
                                        references.add(match.split('.')[0])
        
        # 处理其他文本文件
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
                # 查找可能的图片/资源名称模式
                patterns = [
                    r'["\']([\w\-]+\.(png|jpg|jpeg|gif))["\']',  # 带扩展名的完整文件名
                    r'["\']([\w\-]+)["\']'  # 通用字符串，可能是资源名
                ]
                
                for pattern in patterns:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        value = match.group(1)
                        if 1 < len(value) < 100 and not ('/' in value or '\\' in value):
                            references.add(value)
                            if '.' in value:
                                base_name = value.split('.')[0]
                                if base_name:
                                    references.add(base_name)
    
    except Exception as e:
        print(f"警告：分析文件 {filepath} 时出错：{e}")
    
    return references

def find_xcodeproj_path(start_dir):
    """Finds the .xcodeproj directory near the start_dir."""
    # Check inside start_dir first
    for item in os.listdir(start_dir):
        if item.endswith('.xcodeproj') and os.path.isdir(os.path.join(start_dir, item)):
            return os.path.join(start_dir, item)

    # If not found, check the parent directory
    parent_dir = os.path.dirname(start_dir)
    # Avoid going too high up (e.g., root directory)
    if parent_dir != start_dir and os.path.isdir(parent_dir):
        for item in os.listdir(parent_dir):
            if item.endswith('.xcodeproj') and os.path.isdir(os.path.join(parent_dir, item)):
                return os.path.join(parent_dir, item)

    return None # Not found

def extract_xcodeproj_references(xcodeproj_path):
    """Extracts potential resource references from project.pbxproj using regex."""
    pbxproj_path = os.path.join(xcodeproj_path, 'project.pbxproj')
    references = set()
    if not os.path.exists(pbxproj_path):
        print(f"警告：在 {xcodeproj_path} 中未找到 project.pbxproj 文件。")
        return references

    print(f"正在从 {os.path.basename(xcodeproj_path)} 中提取项目设置引用...")
    try:
        with open(pbxproj_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Regex for common build settings referencing resources
        # Note: These are simplified and might miss edge cases or custom configurations.
        patterns = {
            # App Icon Name (ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;)
            r'ASSETCATALOG_COMPILER_APPICON_NAME\s*=\s*([^;\s]+);?': 'asset_name',
            # Info.plist File Path (INFOPLIST_FILE = AppName/Info.plist;)
            r'INFOPLIST_FILE\s*=\s*"?([^;"\s]+)"?;?': 'plist_path',
            # Launch Screen Storyboard Name (UILaunchStoryboardName = LaunchScreen;)
            r'UILaunchStoryboardName\s*=\s*([^;\s]+);?': 'storyboard_name',
            # Old Launch Image Name (ASSETCATALOG_COMPILER_LAUNCHIMAGE_NAME = LaunchImage;)
            r'ASSETCATALOG_COMPILER_LAUNCHIMAGE_NAME\s*=\s*([^;\s]+);?': 'asset_name'
        }

        for pattern, ref_type in patterns.items():
            matches = re.finditer(pattern, content)
            for match in matches:
                value = match.group(1).strip()
                if value:
                    if ref_type == 'plist_path':
                        # Add the filename stem (e.g., "Info")
                        plist_stem = Path(value).stem
                        if plist_stem:
                            references.add(plist_stem)
                            # print(f"  Found Plist Ref: {plist_stem} (from {value})")
                    elif ref_type == 'asset_name' or ref_type == 'storyboard_name':
                        # Add the name directly (e.g., "AppIcon", "LaunchScreen")
                        references.add(value)
                        # print(f"  Found Project Ref: {value}")

    except Exception as e:
        print(f"警告：读取或处理 project.pbxproj 文件时出错：{e}")

    print(f"从项目设置中提取了 {len(references)} 个引用标识符。")
    return references

def calculate_image_hash(filepath):
    """Calculates the perceptual hash for an image file."""
    try:
        img = Image.open(filepath)
        # Convert to L (grayscale) or RGB if needed, phash often works well with grayscale
        # img = img.convert('L')
        file_size = get_file_size(filepath)
        
        # 获取图片尺寸信息
        width, height = img.size
        dimensions = {'width': width, 'height': height}
        
        img_hash = HASH_ALGORITHM(img, hash_size=HASH_SIZE)
        return img_hash, file_size, dimensions
    except FileNotFoundError:
        # print(f"警告：计算哈希时文件未找到：{filepath}")
        return None, 0, None
    except Exception as e:
        # print(f"警告：无法计算图片 '{os.path.basename(filepath)}' 的哈希值：{e}")
        return None, 0, None  # Return 0 size as well if hash fails

def extract_asset_catalog_references(asset_path):
    """从 .xcassets 的 Contents.json 中提取资源引用"""
    references = set()
    try:
        contents_path = os.path.join(asset_path, 'Contents.json')
        if not os.path.exists(contents_path):
            return references

        with open(contents_path, 'r', encoding='utf-8') as f:
            contents = json.load(f)

        def extract_from_properties(properties):
            if not properties:
                return
            # 检查 properties 中的 name 字段
            if 'name' in properties:
                references.add(properties['name'])
            # 检查 properties 中的 filename 字段
            if 'filename' in properties:
                base_name = os.path.splitext(properties['filename'])[0]
                references.add(base_name)

        def process_asset(asset):
            if not asset:
                return
            # 处理 properties
            if 'properties' in asset:
                extract_from_properties(asset['properties'])
            # 处理 children
            if 'children' in asset:
                for child in asset['children']:
                    process_asset(child)

        # 处理根级别的 properties
        if 'properties' in contents:
            extract_from_properties(contents['properties'])
        # 处理 assets
        if 'assets' in contents:
            for asset in contents['assets']:
                process_asset(asset)

    except Exception as e:
        print(f"警告：处理资源目录 {asset_path} 的 Contents.json 时出错：{e}")

    return references

# --- Main Logic ---

class ResourceCache:
    def __init__(self, cache_dir='.resource_cache'):
        self.cache_dir = cache_dir
        self.cache_file = os.path.join(cache_dir, 'resource_cache.pkl')
        self.cache = self._load_cache()

    def _load_cache(self):
        """加载缓存"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                print(f"警告：加载缓存失败：{e}")
        return {}

    def _save_cache(self):
        """保存缓存"""
        try:
            with open(self.cache_file, 'wb') as f:
                pickle.dump(self.cache, f)
        except Exception as e:
            print(f"警告：保存缓存失败：{e}")

    def _get_file_hash(self, filepath):
        """计算文件的 MD5 哈希值"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            return None

    def get_image_hash(self, filepath):
        """获取图片的哈希值（从缓存或重新计算）"""
        file_hash = self._get_file_hash(filepath)
        if not file_hash:
            return None, 0, None

        cache_key = f"image_hash_{file_hash}"
        if cache_key in self.cache:
            # 确保缓存中的数据也是三元组格式 (hash, size, dimensions)
            cached_data = self.cache[cache_key]
            if len(cached_data) == 2:  # 兼容旧缓存格式
                img_hash, file_size = cached_data
                dimensions = None
                # 更新缓存到新格式
                self.cache[cache_key] = (img_hash, file_size, dimensions)
                return img_hash, file_size, dimensions
            return cached_data  # 返回三元组

        img_hash, file_size, dimensions = calculate_image_hash(filepath)
        if img_hash is not None:
            self.cache[cache_key] = (img_hash, file_size, dimensions)
            self._save_cache()
        return img_hash, file_size, dimensions

    def get_file_references(self, filepath):
        """获取文件的资源引用（从缓存或重新扫描）"""
        file_hash = self._get_file_hash(filepath)
        if not file_hash:
            return set()

        cache_key = f"refs_{file_hash}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        _, ext = os.path.splitext(filepath)
        ext_lower = ext.lower()
        
        if ext_lower in CODE_FILE_EXTENSIONS or ext_lower in INTERFACE_FILE_EXTENSIONS:
            refs = scan_code_references(filepath)
        elif ext_lower in PLIST_FILE_EXTENSIONS:
            refs = extract_plist_strings(filepath)
        elif ext_lower in OTHER_SEARCH_EXTENSIONS:
            refs = scan_other_references(filepath, os.path.dirname(filepath))
        else:
            refs = set()

        self.cache[cache_key] = refs
        self._save_cache()
        return refs

def analyze_resources(project_dir, large_threshold_kb=100, similarity_threshold=5, output_format=OutputFormat.TEXT):
    """Analyzes resources in the given iOS project directory."""
    project_dir = os.path.abspath(project_dir)
    if not os.path.isdir(project_dir):
        print(f"错误：项目目录未找到：{project_dir}")
        return

    print(f"正在分析项目：{project_dir}")
    print("="*30)

    # 初始化缓存
    cache = ResourceCache()

    resources = {}  # {identifier: {'path': path, 'size': size, 'type': 'file'/'asset'}}
    referenced_identifiers = set()
    image_details = {} # {filepath: {'hash': hash_value, 'size': file_size}} - For similarity check
    
    # --- Pass 1: Find all resources, calculate sizes, AND calculate image hashes ---
    print("正在扫描资源文件并计算图片哈希...")
    asset_set_count = 0
    regular_file_count = 0
    hashed_image_count = 0
    lproj_count = 0  # 本地化目录计数

    for root, dirs, files in os.walk(project_dir, topdown=True):
        original_dirs = list(dirs)
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), project_dir)]

        # --- 处理本地化目录 (.lproj) ---
        lproj_dirs = [d for d in dirs if is_lproj_directory(os.path.join(root, d))]
        for lproj_dir in lproj_dirs:
            lproj_path = os.path.join(root, lproj_dir)
            lproj_resources, lproj_size = analyze_lproj_directory(lproj_path, project_dir)
            
            # 合并本地化资源到主资源列表
            if lproj_resources:
                resources.update(lproj_resources)
                lproj_count += 1
                
        # 从处理列表中排除已处理的本地化目录
        dirs[:] = [d for d in dirs if not is_lproj_directory(os.path.join(root, d))]

        # --- Asset Set Handling (includes hashing images inside) ---
        processed_asset_dirs = []
        for dir_name in original_dirs:
            if dir_name in dirs and dir_name.endswith(ASSET_TYPES):
                asset_path = os.path.join(root, dir_name)
                identifier = Path(dir_name).stem

                # Add asset set to main resources list
                if identifier not in resources and not identifier.startswith('.'):
                    asset_total_size = get_dir_size(asset_path) # Get total size for resource list
                    resources[identifier] = {
                        'path': os.path.relpath(asset_path, project_dir),
                        'size': asset_total_size,
                        'type': 'asset'
                    }
                    asset_set_count += 1

                # --- Hash individual images *inside* the asset set --- #
                try:
                    for item in os.listdir(asset_path):
                        item_path = os.path.join(asset_path, item)
                        if os.path.isfile(item_path):
                            _, item_ext = os.path.splitext(item)
                            if item_ext.lower() in IMAGE_EXTENSIONS:
                                if item_path not in image_details: # Avoid double hashing if already processed
                                    img_hash, file_size, dimensions = cache.get_image_hash(item_path)
                                    if img_hash is not None:
                                        rel_item_path = os.path.relpath(item_path, project_dir)
                                        image_details[rel_item_path] = {'hash': img_hash, 'size': file_size, 'dimensions': dimensions}
                                        hashed_image_count += 1
                except OSError as e:
                    print(f"警告：无法访问资源集合内部 '{dir_name}'：{e}")
                # --- End hashing inside asset set --- #

                processed_asset_dirs.append(dir_name)

        dirs[:] = [d for d in dirs if d not in processed_asset_dirs]

        # --- Handle Regular Files (includes hashing images) ---
        if Path(root).name.endswith(ASSET_TYPES):
             files[:] = []
             continue

        for filename in files:
            filepath = os.path.join(root, filename)
            rel_filepath = os.path.relpath(filepath, project_dir) # Use relative path consistently

            if filename == 'Contents.json':
                continue

            if should_exclude(filepath, project_dir):
                continue

            _, ext = os.path.splitext(filename)
            ext_lower = ext.lower()

            # --- Process Image Files (Hashing + Adding to resources) ---
            if ext_lower in IMAGE_EXTENSIONS:
                # Calculate hash first
                if rel_filepath not in image_details: # Avoid double hashing
                    img_hash, file_size, dimensions = cache.get_image_hash(filepath)
                    if img_hash is not None:
                        image_details[rel_filepath] = {'hash': img_hash, 'size': file_size, 'dimensions': dimensions}
                        hashed_image_count += 1
                    else:
                         file_size = get_file_size(filepath) # Still get size if hash failed
                else:
                    file_size = image_details[rel_filepath]['size'] # Get size from already hashed data

                # Add to main resources list using identifier logic
                identifier = filename
                base_name = Path(filename).stem
                chosen_id = identifier if ext_lower == '.strings' else base_name # Reuse logic for .strings specifically

                if chosen_id in resources and resources[chosen_id]['type'] == 'asset':
                    chosen_id = identifier

                if chosen_id not in resources:
                    resources[chosen_id] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                    
                    regular_file_count += 1
                elif chosen_id == base_name and resources[chosen_id]['type'] == 'file':
                    if file_size > resources[chosen_id]['size']:
                        resources[chosen_id]['path'] = rel_filepath
                        resources[chosen_id]['size'] = file_size
                    
                    if identifier != chosen_id and identifier not in resources:
                        resources[identifier] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                        
                        regular_file_count += 1
                elif chosen_id == identifier and identifier not in resources:
                    resources[identifier] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                    
                    regular_file_count += 1

            # --- Process Other Resource Files (No Hashing) ---
            elif ext_lower in RESOURCE_EXTENSIONS:
                 file_size = get_file_size(filepath)
                 identifier = filename
                 base_name = Path(filename).stem
                 chosen_id = identifier if ext_lower == '.strings' else base_name

                 # 特殊处理 .car 文件
                 if ext_lower == '.car':
                     car_info = analyze_car_file(filepath)
                     if car_info.get('asset_name'):
                         chosen_id = car_info['asset_name']
                     identifier = car_info['identifier']
                     file_size = car_info['size']

                 if chosen_id in resources and resources[chosen_id]['type'] == 'asset':
                     chosen_id = identifier

                 if chosen_id not in resources:
                     resources[chosen_id] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                     regular_file_count += 1
                 elif chosen_id == base_name and resources[chosen_id]['type'] == 'file':
                     if file_size > resources[chosen_id]['size']:
                          resources[chosen_id]['path'] = rel_filepath
                          resources[chosen_id]['size'] = file_size
                     if identifier != chosen_id and identifier not in resources:
                           resources[identifier] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                           regular_file_count += 1
                 elif chosen_id == identifier and identifier not in resources:
                     resources[identifier] = {'path': rel_filepath, 'size': file_size, 'type': 'file'}
                     regular_file_count += 1


    print(f"找到 {len(resources)} 个资源标识符 ({asset_set_count} 个资源集合已处理, {regular_file_count} 个独立资源文件已找到)。")
    print(f"已为 {hashed_image_count} 个图片文件计算哈希值。")
    print(f"处理了 {lproj_count} 个本地化资源目录(.lproj)。")

    # --- Pass 1.5: Find Similar Images ---
    print("\n正在比较图片相似度...")
    similar_image_groups = [] # List of sets, each set contains paths of similar images
    processed_for_similarity = set() # Keep track of images already grouped
    image_paths = list(image_details.keys())

    # Helper function to get the container (asset set or standalone file)
    def get_image_container(img_path, asset_types_tuple):
        parent = os.path.dirname(img_path)
        if parent and Path(parent).name.endswith(asset_types_tuple):
            return parent # Return the asset set directory path
        else:
            return img_path # Treat standalone images as their own container

    for i in range(len(image_paths)):
        path1 = image_paths[i]
        if path1 in processed_for_similarity or image_details[path1]['hash'] is None:
            continue

        current_group = {path1}
        hash1 = image_details[path1]['hash']

        for j in range(i + 1, len(image_paths)):
            path2 = image_paths[j]
            if path2 in processed_for_similarity or image_details[path2]['hash'] is None:
                continue

            hash2 = image_details[path2]['hash']
            distance = hash1 - hash2

            # Use the configurable similarity_threshold here
            if distance <= similarity_threshold:
                current_group.add(path2)
                # Don't add path2 to processed_for_similarity yet, it might match others

        # After checking path1 against all others, if it formed a group, process the group
        if len(current_group) > 1:
            # --- Filter check: Are all images in the group from the same container? ---
            container_paths = {get_image_container(p, ASSET_TYPES) for p in current_group}
            if len(container_paths) == 1:
                # All images are from the same asset set (e.g., @1x, @2x, @3x), ignore this group.
                # Mark them as processed to avoid redundant checks later.
                processed_for_similarity.update(current_group)
                continue # Skip to the next image (i)
            # --- End filter check ---

            # If the group contains images from different containers, it's a valid similar group.
            similar_image_groups.append(current_group)
            # Mark all images in this new valid group as processed
            processed_for_similarity.update(current_group)
        else:
             # Mark path1 as processed even if it wasn't similar to anything
             # This needs to be done here, AFTER the group check, because an image initially
             # not forming a cross-asset group might later be added to another valid group.
             if path1 not in processed_for_similarity: # Double check it wasn't processed in a valid group check
                  processed_for_similarity.add(path1)

    # Update the print message to reflect the used threshold
    print(f"找到 {len(similar_image_groups)} 组跨资源相似图片 (阈值 <= {similarity_threshold})。")

    # --- 检测超大尺寸图片 ---
    print("\n正在检测超大尺寸图片...")
    oversized_images = []
    
    for img_path, details in image_details.items():
        if 'dimensions' in details and details['dimensions']:
            width = details['dimensions']['width']
            height = details['dimensions']['height']
            img_size_kb = details['size'] / 1024.0
            
            # 计算每千像素的KB大小 (用于判断图片是否过于"沉重")
            pixels = (width * height) / 1000.0  # 千像素
            kb_per_kpixel = img_size_kb / pixels if pixels > 0 else 0
            
            is_oversized = False
            reason = []
            
            # 检查过大尺寸
            if width > LARGE_IMAGE_WIDTH_THRESHOLD or height > LARGE_IMAGE_HEIGHT_THRESHOLD:
                is_oversized = True
                reason.append(f"尺寸过大 ({width}x{height}px)")
            
            # 检查过高的大小/像素比
            if kb_per_kpixel > LARGE_IMAGE_SIZE_RATIO_THRESHOLD:
                is_oversized = True
                reason.append(f"压缩率低 ({kb_per_kpixel:.2f} KB/千像素)")
            
            if is_oversized:
                oversized_images.append({
                    'path': img_path,
                    'size_kb': img_size_kb,
                    'width': width,
                    'height': height,
                    'kb_per_kpixel': kb_per_kpixel,
                    'reason': reason
                })
    
    # 按大小排序结果
    oversized_images.sort(key=lambda x: x['size_kb'], reverse=True)
    
    # --- Resource Size Output ---
    print("\n--- 资源大小 (已排序) ---")
    sorted_resources = sorted(resources.items(), key=lambda item: item[1]['size'], reverse=True)
    if not sorted_resources:
        print("未找到资源文件。")
    else:
        print(f"{'大小 (KB)':>12} | {'类型':<6} | 标识符 (路径)")
        print("-" * 100)
        total_size_kb = 0
        for identifier, data in sorted_resources:
            size_kb = data['size'] / 1024.0
            total_size_kb += size_kb
            # --- Highlight large resources --- START
            line = f"{size_kb:12.2f} | {data['type']:<6} | {identifier} ({data['path']})"
            if size_kb >= large_threshold_kb:
                print(f"{COLOR_RED}{line}{COLOR_RESET}")
            else:
                print(line)
            # --- Highlight large resources --- END
        print("-" * 100)
        print(f"总资源大小：{total_size_kb / 1024.0:.2f} MB")
    
    # --- 超大尺寸图片输出 ---
    if oversized_images:
        print("\n--- 超大尺寸图片 ---")
        print(f"{'大小 (KB)':>12} | {'尺寸':>15} | {'KB/千像素':>12} | {'问题':^20} | 路径")
        print("-" * 120)
        
        for img in oversized_images:
            reason_str = ", ".join(img['reason'])
            print(f"{img['size_kb']:12.2f} | {img['width']:5}x{img['height']:<9} | {img['kb_per_kpixel']:12.2f} | {reason_str:<20} | {img['path']}")
        
        print("-" * 120)
        print(f"找到 {len(oversized_images)} 张尺寸异常的图片，建议优化。")
        print("• 尺寸过大的图片建议压缩或使用不同分辨率的变体")
        print("• 压缩率低的图片应使用更高效的压缩算法或更合适的格式（如 WebP）")
    else:
        print("\n未发现超大尺寸或压缩率低的图片。")

    # --- Pass 2: Find References ---
    print("\n正在扫描资源引用...")
    xcodeproj_path = find_xcodeproj_path(project_dir)
    if xcodeproj_path:
        xcodeproj_refs = extract_xcodeproj_references(xcodeproj_path)
        referenced_identifiers.update(xcodeproj_refs)
    else:
        print("警告：未能自动定位 .xcodeproj 文件。AppIcon, LaunchScreen, Info.plist 等项目级引用可能不会被计入。")

    # 添加对 .xcassets 的 Contents.json 解析
    print("正在扫描资源目录的 Contents.json...")
    for root, dirs, files in os.walk(project_dir, topdown=True):
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), project_dir)]
        
        for dir_name in dirs:
            if dir_name.endswith('.xcassets'):
                asset_path = os.path.join(root, dir_name)
                asset_refs = extract_asset_catalog_references(asset_path)
                referenced_identifiers.update(asset_refs)
                if asset_refs:
                    print(f"  从 {os.path.relpath(asset_path, project_dir)} 中提取了 {len(asset_refs)} 个引用")

    print("正在扫描代码、界面文件、Plist 及其他文件中的引用...")
    possible_reference_files_count = 0
    search_extensions = CODE_FILE_EXTENSIONS | INTERFACE_FILE_EXTENSIONS | PLIST_FILE_EXTENSIONS | OTHER_SEARCH_EXTENSIONS

    # 首先统计需要扫描的文件总数
    total_files = 0
    for root, dirs, files in os.walk(project_dir, topdown=True):
        dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), project_dir)]
        for filename in files:
            filepath = os.path.join(root, filename)
            if should_exclude(filepath, project_dir):
                continue
            _, ext = os.path.splitext(filename)
            if ext.lower() in search_extensions:
                total_files += 1

    # 使用进度条扫描文件
    with tqdm(total=total_files, desc="扫描文件", unit="文件") as pbar:
        for root, dirs, files in os.walk(project_dir, topdown=True):
            # Modify dirs in-place to skip excluded directories
            dirs[:] = [d for d in dirs if not should_exclude(os.path.join(root, d), project_dir)]

            for filename in files:
                filepath = os.path.join(root, filename)
                if should_exclude(filepath, project_dir):
                    continue

                _, ext = os.path.splitext(filename)
                ext_lower = ext.lower()

                content = ""
                try:
                    if ext_lower in CODE_FILE_EXTENSIONS or ext_lower in INTERFACE_FILE_EXTENSIONS or ext_lower in OTHER_SEARCH_EXTENSIONS:
                        possible_reference_files_count += 1
                        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()

                    # Search in Code files
                    if ext_lower in CODE_FILE_EXTENSIONS:
                        matches = CODE_REFERENCE_REGEX.finditer(content)
                        for match in matches:
                            # Extract the first non-None group
                            ref = next((g for g in match.groups() if g is not None), None)
                            if match.group(6) and match.group(7): # Handle R.swift style (Group 6=type, Group 7=name)
                                ref = match.group(7)
                            if ref:
                                # 增加更严格的过滤条件
                                if (1 < len(ref) < 100 and 
                                    not ('/' in ref or '\\' in ref) and
                                    not ref.startswith(('http', 'www')) and  # 排除 URL
                                    not ref.isdigit() and  # 排除纯数字
                                    not ref.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and  # 排除系统前缀
                                    not ref in {'hide', 'show', 'success', 'error', 'warning'}):  # 排除常见非资源词
                                    referenced_identifiers.add(ref.split('.')[0])
                        
                        # 检测动态拼接模式
                        dynamic_matches = DYNAMIC_PATTERN_REGEX.finditer(content)
                        for match in dynamic_matches:
                            # 提取所有潜在的静态部分
                            static_parts = [g for g in match.groups() if g is not None]
                            for part in static_parts:
                                if (1 < len(part) < 100 and 
                                    not ('/' in part or '\\' in part) and
                                    not part.startswith(('http', 'www')) and
                                    not part.isdigit() and
                                    not part.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and
                                    not part in {'hide', 'show', 'success', 'error', 'warning'}):
                                    referenced_identifiers.add(part.split('.')[0])
                                    
                                    # 由于这是动态拼接，增加额外处理
                                    # 如果静态部分是前缀或后缀，尝试查找可能的完整资源名
                                    for res_id in resources.keys():
                                        if res_id.startswith(part) or res_id.endswith(part):
                                            referenced_identifiers.add(res_id)

                    # Search in Storyboards/XIBs (XML)
                    elif ext_lower in INTERFACE_FILE_EXTENSIONS:
                        matches = XML_REFERENCE_REGEX.finditer(content)
                        for match in matches:
                            # 提取所有非空的组
                            potential_refs = [g for g in match.groups() if g is not None]
                            for ref in potential_refs:
                                if (1 < len(ref) < 100 and 
                                      not ('/' in ref or '\\' in ref) and
                                      not ref.startswith(('http', 'www')) and
                                      not ref.isdigit() and
                                      not ref.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and
                                      not ref in {'hide', 'show', 'success', 'error', 'warning'}):
                                    
                                    # 处理带扩展名的资源引用
                                    if '.' in ref:
                                        base_ref = ref.split('.')[0]
                                        referenced_identifiers.add(base_ref)
                                        referenced_identifiers.add(ref)  # 同时添加完整引用
                                    else:
                                        referenced_identifiers.add(ref)
                                        
                                        # 尝试查找可能匹配的资源
                                        for res_id in resources.keys():
                                            if res_id.startswith(ref + '.') or res_id == ref:
                                                referenced_identifiers.add(res_id)

                    # Search in Plist files
                    elif ext_lower in PLIST_FILE_EXTENSIONS:
                        plist_strings = extract_plist_strings(filepath)
                        # 过滤 plist 字符串
                        filtered_strings = {
                            s for s in plist_strings 
                            if (1 < len(s) < 100 and 
                                not ('/' in s or '\\' in s) and
                                not s.startswith(('http', 'www')) and
                                not s.isdigit() and
                                not s.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and
                                not s in {'hide', 'show', 'success', 'error', 'warning'})
                        }
                        referenced_identifiers.update(filtered_strings)

                    # Search in other text-based files (.strings, .json)
                    elif ext_lower in OTHER_SEARCH_EXTENSIONS:
                        # 使用专门的函数处理其他类型文件
                        other_refs = scan_other_references(filepath, project_dir)
                        if other_refs:
                            referenced_identifiers.update(other_refs)
                            
                        # 同时保留旧的代码，以防漏检
                        known_identifiers = set(resources.keys())
                        for identifier in known_identifiers:
                            try:
                                if re.search(r'\b' + re.escape(identifier) + r'\b', content) or \
                                   re.search(r'"' + re.escape(identifier) + r'"', content) or \
                                   re.search(r"'" + re.escape(identifier) + r"'", content):
                                    referenced_identifiers.add(identifier)
                                    base_identifier = Path(identifier).stem
                                    if base_identifier != identifier:
                                        referenced_identifiers.add(base_identifier)
                            except re.error:
                                if identifier in content:
                                    referenced_identifiers.add(identifier)
                                    base_identifier = Path(identifier).stem
                                    if base_identifier != identifier:
                                        referenced_identifiers.add(base_identifier)

                except Exception as e:
                    # print(f"Warning: Could not read or process {filepath}: {e}")
                    print(f"警告：无法读取或处理文件 {filepath}：{e}")
                
                # 更新进度条
                if ext_lower in search_extensions:
                    pbar.update(1)

    print(f"已扫描 {possible_reference_files_count} 个可能的代码/界面/配置/其他文件以查找引用。")
    print(f"总共找到 {len(referenced_identifiers)} 个唯一的潜在引用字符串 (包含项目设置)。")

    # --- Pass 3: Identify Unused Resources ---
    all_resource_identifiers = set(resources.keys())
    unused_identifiers = all_resource_identifiers - referenced_identifiers

    # Refinement: If 'icon.png' exists and 'icon' is referenced, consider 'icon.png' used.
    # Need to handle cases where references might omit extensions.
    truly_unused = set()
    for res_id in unused_identifiers:
        base_name = res_id.split('.')[0]
        if res_id not in referenced_identifiers and base_name not in referenced_identifiers:
             # Also check if the full name (e.g., "myImage.png") was referenced
             is_referenced = False
             for ref_id in referenced_identifiers:
                 # Check if the resource ID starts with a reference ID (e.g., res_id="icon.png", ref_id="icon")
                 # or if the reference ID starts with the resource ID (e.g. res_id="icon", ref_id="icon.png") - less common
                 if res_id.startswith(ref_id + '.') or ref_id.startswith(res_id + '.'):
                     is_referenced = True
                     break
                 # Check for storyboard/xib references that might include folder structure sometimes
                 # e.g., resource path = "Icons/my_icon.png", id = "my_icon", ref = "Icons/my_icon"
                 res_path_no_ext = os.path.splitext(resources[res_id]['path'])[0]
                 if ref_id == res_path_no_ext:
                     is_referenced = True
                     break

             if not is_referenced:
                 truly_unused.add(res_id)


    print("\n--- 可能未使用的资源 ---")
    if not truly_unused:
        print("未发现可能未使用的资源 (基于扫描结果)。")
    else:
        print("警告：此列表识别出的资源，其确切名称、基本名称或路径形式的引用")
        print("         未在扫描的文件中找到。请在删除前仔细检查，因为引用")
        print("         可能是动态构建的，或存在于未扫描的文件类型中（例如构建脚本）。")
        print(f"{'大小 (KB)':>12} | {'类型':<6} | 标识符 (路径)")
        print("-" * 100)
        # Sort unused by size as well
        unused_sorted = sorted(list(truly_unused), key=lambda id: resources[id]['size'], reverse=True)
        count_unused = 0
        total_unused_size_kb = 0
        for identifier in unused_sorted:
            data = resources[identifier]
            size_kb = data['size'] / 1024.0
            total_unused_size_kb += size_kb
            count_unused += 1
            print(f"{size_kb:12.2f} | {data['type']:<6} | {identifier} ({data['path']})")
        print("-" * 100)
        print(f"发现 {count_unused} 个可能未使用的资源。")
        print(f"预估总大小：{total_unused_size_kb / 1024.0:.2f} MB")

    # --- 添加资源优化建议 ---
    optimization_suggestions = [
        {
            'type': '图片优化',
            'suggestion': '1. 使用 ImageOptim 或 TinyPNG 压缩所有图片资源\n2. 考虑使用 WebP 格式替代 PNG/JPG\n3. 检查并移除重复的图片资源\n4. 使用适当的图片分辨率，避免过大尺寸'
        },
        {
            'type': '音频优化',
            'suggestion': '1. 使用 Audacity 或 XLD 压缩音频文件\n2. 考虑使用 AAC 格式替代 MP3\n3. 检查并移除未使用的音频资源\n4. 根据实际需求选择合适的音频质量'
        },
        {
            'type': '视频优化',
            'suggestion': '1. 使用 HandBrake 或 FFmpeg 压缩视频文件\n2. 考虑使用 H.264/H.265 编码\n3. 检查并移除未使用的视频资源\n4. 根据实际需求选择合适的视频质量'
        },
        {
            'type': '资源管理',
            'suggestion': '1. 定期清理未使用的资源文件\n2. 使用资源目录（.xcassets）管理图片资源\n3. 考虑使用资源压缩工具（如 Asset Catalog Compiler）\n4. 检查并移除重复的相似图片'
        }
    ]
    
    # 根据分析结果，添加具体的针对性建议
    specific_suggestions = []
    
    # 针对未使用资源的建议
    if len(truly_unused) > 0:
        unused_size_mb = sum(resources[id]['size'] for id in truly_unused) / (1024.0 * 1024.0)
        percentage = (unused_size_mb / (total_size_kb / 1024.0)) * 100 if total_size_kb > 0 else 0
        specific_suggestions.append({
            'type': '未使用资源清理',
            'suggestion': f'移除 {len(truly_unused)} 个未使用的资源文件可节省约 {unused_size_mb:.2f} MB ({percentage:.1f}% 的总资源大小)'
        })
    
    # 针对相似图片的建议
    if similar_image_groups:
        total_potential_savings = 0
        for group in similar_image_groups:
            group_files = []
            max_size = 0
            current_group_total_size = 0
            for img_path in group:
                if img_path in image_details:
                    group_files.append(image_details[img_path]['size'])
                    max_size = max(max_size, image_details[img_path]['size'])
                    current_group_total_size += image_details[img_path]['size']
            
            if len(group_files) > 1:
                potential_savings = current_group_total_size - max_size
                total_potential_savings += potential_savings
        
        similar_savings_mb = total_potential_savings / (1024.0 * 1024.0)
        percentage = (similar_savings_mb / (total_size_kb / 1024.0)) * 100 if total_size_kb > 0 else 0
        specific_suggestions.append({
            'type': '相似图片合并',
            'suggestion': f'合并 {len(similar_image_groups)} 组相似图片可节省约 {similar_savings_mb:.2f} MB ({percentage:.1f}% 的总资源大小)'
        })
    
    # 针对超大图片的建议
    if oversized_images:
        oversized_count = len(oversized_images)
        oversized_total_mb = sum(img['size_kb'] for img in oversized_images) / 1024.0
        potential_saving_mb = oversized_total_mb * 0.7  # 假设可以压缩至原大小的 30%
        specific_suggestions.append({
            'type': '超大图片压缩',
            'suggestion': f'压缩 {oversized_count} 张超大/低压缩图片可节省约 {potential_saving_mb:.2f} MB\n建议使用 WebP 格式并确保尺寸适合目标设备'
        })
    
    # 添加特定建议
    optimization_suggestions.extend(specific_suggestions)
    
    # --- Pass 4: Output Similar Images ---
    print("\n--- 相似图片组 (基于感知哈希) ---")
    if not similar_image_groups:
        print("未找到相似的图片组。")
    else:
        # Update the print message to reflect the used threshold
        print(f"找到 {len(similar_image_groups)} 组相似图片 (汉明距离 <= {similarity_threshold}):")
        total_potential_savings = 0
        group_index = 1
        for group in similar_image_groups:
            print(f"\n组 {group_index}:")
            group_files = []
            max_size = 0
            current_group_total_size = 0
            for img_path in sorted(list(group)):
                 if img_path in image_details:
                     details = image_details[img_path]
                     size_kb = details['size'] / 1024.0
                     print(f"  - {size_kb:8.2f} KB | {img_path} (Hash: {details['hash']})")
                     group_files.append(details['size'])
                     max_size = max(max_size, details['size'])
                     current_group_total_size += details['size']
                 else:
                      print(f"  - ??? KB | {img_path} (大小信息缺失)") # Should not happen ideally

            if len(group_files) > 1:
                potential_savings = current_group_total_size - max_size
                total_potential_savings += potential_savings
                print(f"  潜在可节省空间: {potential_savings / 1024.0:.2f} KB (保留最大文件，移除其他 {len(group_files) - 1} 个文件)")
            group_index += 1

        print("-"*100)
        print(f"所有相似组总计潜在可节省空间: {total_potential_savings / (1024.0*1024.0):.2f} MB")
        print("注意：此相似性检测已过滤掉同一资源集内部的图片（如 @2x/@3x 变体）。") # Added note
        print("注意：请务必手动确认这些图片是否真的可以合并或移除。")

    # --- Prepare Output Data ---
    output_data = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'project_dir': project_dir,
        'resources': [],
        'unused_resources': [],
        'similar_image_groups': [],
        'total_size_mb': total_size_kb / 1024.0,
        'large_threshold_kb': large_threshold_kb,
        'similarity_threshold': similarity_threshold,
        'optimization_suggestions': optimization_suggestions
    }

    # --- Format Resource Data ---
    for identifier, data in sorted_resources:
        size_kb = data['size'] / 1024.0
        resource_data = {
            'size_kb': size_kb,
            'type': data['type'],
            'identifier': identifier,
            'path': data['path'],
            'is_large': size_kb >= large_threshold_kb
        }
        output_data['resources'].append(resource_data)

    # --- Format Unused Resources Data ---
    for identifier in unused_sorted:
        data = resources[identifier]
        size_kb = data['size'] / 1024.0
        unused_data = {
            'size_kb': size_kb,
            'type': data['type'],
            'identifier': identifier,
            'path': data['path']
        }
        output_data['unused_resources'].append(unused_data)

    # --- Format Similar Images Data ---
    for group in similar_image_groups:
        group_data = []
        for img_path in sorted(list(group)):
            if img_path in image_details:
                details = image_details[img_path]
                size_kb = details['size'] / 1024.0
                group_data.append({
                    'path': img_path,
                    'size_kb': size_kb,
                    'hash': str(details['hash'])
                })
        output_data['similar_image_groups'].append(group_data)

    # --- Output Based on Format ---
    if output_format == OutputFormat.JSON:
        print(json.dumps(output_data, indent=2, ensure_ascii=False))
    elif output_format == OutputFormat.CSV:
        # 生成 CSV 内容
        import csv
        
        # 资源大小统计 CSV
        with open('resource_size_report.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['大小 (KB)', '类型', '标识符', '路径', '是否大文件'])
            for resource in output_data['resources']:
                writer.writerow([
                    f"{resource['size_kb']:.2f}",
                    resource['type'],
                    resource['identifier'],
                    resource['path'],
                    '是' if resource['is_large'] else '否'
                ])
        
        # 未使用资源 CSV
        with open('unused_resources.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['大小 (KB)', '类型', '标识符', '路径'])
            for resource in output_data['unused_resources']:
                writer.writerow([
                    f"{resource['size_kb']:.2f}",
                    resource['type'],
                    resource['identifier'],
                    resource['path']
                ])
        
        # 相似图片组 CSV
        with open('similar_images.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['组号', '大小 (KB)', '路径', '哈希值'])
            for i, group in enumerate(output_data['similar_image_groups'], 1):
                for img in group:
                    writer.writerow([
                        f"组 {i}",
                        f"{img['size_kb']:.2f}",
                        img['path'],
                        img['hash']
                    ])
        
        # 优化建议 CSV
        with open('optimization_suggestions.csv', 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['类型', '建议'])
            for suggestion in output_data['optimization_suggestions']:
                writer.writerow([
                    suggestion['type'],
                    suggestion['suggestion']
                ])
        
        print(f"\nCSV 报告已生成：")
        print(f"- 资源大小统计：{os.path.abspath('resource_size_report.csv')}")
        print(f"- 未使用资源：{os.path.abspath('unused_resources.csv')}")
        print(f"- 相似图片组：{os.path.abspath('similar_images.csv')}")
        print(f"- 优化建议：{os.path.abspath('optimization_suggestions.csv')}")
    elif output_format == OutputFormat.HTML:
        # Generate HTML content
        resource_table = ""
        for resource in output_data['resources']:
            size_class = ' class="large-resource"' if resource['is_large'] else ''
            resource_table += f"""
                <tr{size_class}>
                    <td>{resource['size_kb']:.2f}</td>
                    <td>{resource['type']}</td>
                    <td>{resource['identifier']}</td>
                    <td>{resource['path']}</td>
                </tr>
            """

        unused_resources_html = ""
        if output_data['unused_resources']:
            unused_resources_html = """
                <table>
                    <tr>
                        <th>大小 (KB)</th>
                        <th>类型</th>
                        <th>标识符</th>
                        <th>路径</th>
                    </tr>
            """
            for resource in output_data['unused_resources']:
                unused_resources_html += f"""
                    <tr>
                        <td>{resource['size_kb']:.2f}</td>
                        <td>{resource['type']}</td>
                        <td>{resource['identifier']}</td>
                        <td>{resource['path']}</td>
                    </tr>
                """
            unused_resources_html += "</table>"
        else:
            unused_resources_html = "<p class='success'>未发现可能未使用的资源。</p>"

        similar_images_html = ""
        if output_data['similar_image_groups']:
            for i, group in enumerate(output_data['similar_image_groups'], 1):
                similar_images_html += f"""
                    <h3>组 {i}:</h3>
                    <table>
                        <tr>
                            <th>大小 (KB)</th>
                            <th>路径</th>
                            <th>哈希值</th>
                        </tr>
                """
                for img in group:
                    similar_images_html += f"""
                        <tr>
                            <td>{img['size_kb']:.2f}</td>
                            <td>{img['path']}</td>
                            <td>{img['hash']}</td>
                        </tr>
                    """
                similar_images_html += "</table>"
        else:
            similar_images_html = "<p class='success'>未找到相似的图片组。</p>"

        optimization_suggestions_html = """
            <table>
                <tr>
                    <th>类型</th>
                    <th>建议</th>
                </tr>
        """
        for suggestion in output_data['optimization_suggestions']:
            optimization_suggestions_html += f"""
                <tr>
                    <td>{suggestion['type']}</td>
                    <td>{suggestion['suggestion'].replace('\n', '<br>')}</td>
                </tr>
            """
        optimization_suggestions_html += "</table>"

        html_content = HTML_TEMPLATE.format(
            timestamp=output_data['timestamp'],
            project_dir=output_data['project_dir'],
            resource_table=resource_table,
            unused_resources=unused_resources_html,
            similar_images=similar_images_html,
            optimization_suggestions=optimization_suggestions_html,
            total_size_mb=output_data['total_size_mb'],
            total_image_size_mb=sum(img['size'] for img in output_data['resources']) / (1024.0 * 1024.0)
        )

        # Write HTML file
        output_file = 'resource_analysis_report.html'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"\nHTML 报告已生成：{os.path.abspath(output_file)}")

    # --- 输出资源优化建议 ---
    print("\n--- 资源优化建议 ---")
    for suggestion in optimization_suggestions:
        print(f"\n{suggestion['type']}:")
        print(suggestion['suggestion'])

    print("\n分析完成。")

    return output_data


# --- Entry Point ---

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="分析iOS项目资源：按大小列出，查找未使用，并检测相似图片。",
        epilog="示例：python resource_analyzer.py /path/to/YourXcodeProject --large-threshold 200 --similarity-threshold 3 --output json",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "project_dir",
        metavar="PROJECT_DIRECTORY",
        help="iOS项目根目录的路径 (包含 .xcodeproj 或 .xcworkspace 文件)。"
    )
    parser.add_argument(
        "--large-threshold",
        type=int,
        default=100,
        help="定义大资源文件的大小阈值 (KB)，超过此阈值将在列表中标红。"
    )
    parser.add_argument(
        "--similarity-threshold",
        type=int,
        default=5,
        help="定义图片相似度比较的汉明距离阈值，越小表示越相似。"
    )
    parser.add_argument(
        "--output",
        choices=[OutputFormat.TEXT, OutputFormat.JSON, OutputFormat.HTML, OutputFormat.CSV],
        default=OutputFormat.TEXT,
        help="指定输出格式：text（默认）、json 或 html。"
    )

    args = parser.parse_args()

    analyze_resources(args.project_dir,
                     large_threshold_kb=args.large_threshold,
                     similarity_threshold=args.similarity_threshold,
                     output_format=args.output)

def scan_code_references(filepath):
    """扫描代码文件中的资源引用"""
    references = set()
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 使用通用引用模式
        matches = CODE_REFERENCE_REGEX.finditer(content)
        for match in matches:
            # 提取第一个非空的组
            ref = next((g for g in match.groups() if g is not None), None)
            # 处理 R.swift 风格 (组 6=类型, 组 7=名称)
            if match.lastindex >= 7 and match.group(6) and match.group(7): 
                ref = match.group(7)
            
            if ref and (1 < len(ref) < 100 and 
                       not ('/' in ref or '\\' in ref) and
                       not ref.startswith(('http', 'www')) and
                       not ref.isdigit() and
                       not ref.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and
                       not ref in {'hide', 'show', 'success', 'error', 'warning'}):
                references.add(ref.split('.')[0])
        
        # 使用动态拼接检测模式
        dynamic_matches = DYNAMIC_PATTERN_REGEX.finditer(content)
        for match in dynamic_matches:
            static_parts = [g for g in match.groups() if g is not None]
            for part in static_parts:
                if (1 < len(part) < 100 and 
                    not ('/' in part or '\\' in part) and
                    not part.startswith(('http', 'www')) and
                    not part.isdigit() and
                    not part.startswith(('CF', 'NS', 'UI', 'LAUNCH')) and
                    not part in {'hide', 'show', 'success', 'error', 'warning'}):
                    references.add(part.split('.')[0])
                    
    except Exception as e:
        print(f"警告：无法扫描代码文件 {filepath}：{e}")
    
    return references

# --- Asset Catalog Analysis ---

def analyze_asset_catalog(asset_path: Path, all_resources: dict):
    """分析单个 Asset Catalog (.xcassets) 目录。"""
    results = {
        "sets_analyzed": 0,
        "imagesets": [],
        "issues": [] # 存储发现的问题
    }
    
    # Asset Catalog 本身不需要添加到 all_resources，我们关心它内部的 imageset 等

    for item_path in asset_path.rglob('*'):
        if item_path.is_dir() and item_path.suffix in ASSET_TYPES:
            if item_path.suffix == '.imageset':
                analysis = analyze_imageset(item_path, all_resources)
                if analysis:
                     results["sets_analyzed"] += 1
                     results["imagesets"].append(analysis)
                     results["issues"].extend(analysis["issues"])
            # TODO: 可以添加对其他类型 (.colorset, .symbolset 等) 的分析

    return results

def analyze_imageset(imageset_path: Path, all_resources: dict):
    """分析单个 .imageset 目录。"""
    contents_path = imageset_path / "Contents.json"
    analysis = {
        "name": imageset_path.stem,
        "path": str(imageset_path.relative_to(project_root)), # Use global project_root
        "images": [],
        "issues": [],
        "total_size": 0,
        "referenced_in": [] # Add this field
    }

    if not contents_path.exists():
        analysis["issues"].append({"type": "error", "message": "未找到 Contents.json"})
        return analysis

    try:
        with open(contents_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        analysis["issues"].append({"type": "error", "message": "Contents.json 解析失败"})
        return analysis
    except Exception as e:
        analysis["issues"].append({"type": "error", "message": f"读取 Contents.json 时出错: {e}"})
        return analysis

    has_1x = False
    has_2x = False
    has_3x = False
    idioms = set()
    gamuts = set()
    appearances = set()
    defined_files = set()

    if "images" in data:
        for img_info in data["images"]:
            filename = img_info.get("filename")
            if filename:
                defined_files.add(filename)
                img_path = imageset_path / filename
                if img_path.exists():
                    size = get_file_size(str(img_path))
                    analysis["images"].append({"filename": filename, "size": size})
                    analysis["total_size"] += size
                    # 将 imageset 内部的图片文件也记录到 all_resources 中，方便统一处理大小和引用
                    file_key = str(img_path.relative_to(project_root))
                    all_resources[file_key] = {
                        'size': size,
                        'type': 'Image',
                        'asset_catalog_set': analysis["name"],
                        'referenced_in': set() # 初始化引用集合
                    }
                else:
                    analysis["issues"].append({"type": "warning", "message": f"Contents.json 中引用的文件 '{filename}' 不存在"})

            scale = img_info.get("scale")
            if scale == "1x": has_1x = True
            if scale == "2x": has_2x = True
            if scale == "3x": has_3x = True

            idiom = img_info.get("idiom")
            if idiom: idioms.add(idiom)

            gamut = img_info.get("display-gamut")
            if gamut: gamuts.add(gamut)

            appearance = img_info.get("appearances")
            if appearance:
                 for app_dict in appearance:
                     if app_dict.get("appearance") == "luminosity":
                         appearances.add(app_dict.get("value")) # e.g., "light", "dark"

        # 检查变体完整性
        if not has_3x and 'iphone' in idioms:
            analysis["issues"].append({"type": "warning", "message": "缺少 @3x 变体，可能在高分辨率 iPhone 上模糊或拉伸。"})
        if not has_2x and ('iphone' in idioms or 'ipad' in idioms or 'mac' in idioms):
            # 2x is usually necessary unless it's vector or single scale
            is_vector = any(img.get("properties", {}).get("template-rendering-intent") == "vector" for img in data.get("images",[]))
            preserves_vector = data.get("properties",{}).get("preserves-vector-representation")
            if not is_vector and not preserves_vector:
                analysis["issues"].append({"type": "info", "message": "缺少 @2x 停用，如果不是矢量图，可能在非 Retina 设备上需要。"}) # Lower severity

        # 检查冗余文件
        actual_files = {f.name for f in imageset_path.glob('*') if f.is_file() and f.name != 'Contents.json'}
        undefined_files = actual_files - defined_files
        if undefined_files:
            for fname in undefined_files:
                 analysis["issues"].append({"type": "warning", "message": f"文件 '{fname}' 存在于目录中，但在 Contents.json 未定义。"})
                 # 将未定义的文件也加入 all_resources，以便检测是否被其他地方引用
                 undefined_path = imageset_path / fname
                 file_key_undef = str(undefined_path.relative_to(project_root))
                 size_undef = get_file_size(str(undefined_path))
                 all_resources[file_key_undef] = {
                    'size': size_undef,
                    'type': 'Image',
                    'asset_catalog_set': analysis["name"] + " (未定义)",
                    'referenced_in': set()
                }


    # Check for single scale vector images
    # if len(analysis["images"]) == 1 and has_1x and not has_2x and not has_3x:
    #     img_info = data.get("images", [])[0]
    #     props = data.get("properties", {})
    #     filename = img_info.get("filename")
    #     if filename and (filename.endswith(".pdf") or filename.endswith(".svg")):
    #         if props.get("preserves-vector-representation"):
    #              analysis["issues"].append({"type": "info", "message": "检测到单比例矢量图像。"})
    #         else:
    #              analysis["issues"].append({"type": "warning", "message": f"矢量文件 '{filename}' 未设置 'Preserve Vector Representation'。"})

    # 检查是否存在暗黑模式但只有一个资源的情况
    if "dark" in appearances and len(analysis["images"]) == len([a for a in appearances if a]): # Check if only one appearance value used across images
          pass # Might need more logic if images can have *different* appearances

    return analysis


# --- WebP Suggestion --- WEB_P_GAIN_ESTIMATE = 0.7 # 假设 WebP 平均节省 30% 体积 WEBP_SUGGESTION_THRESHOLD_KB = 50 # 只对大于 50KB 的图片提出建议 def generate_webp_suggestions(resources_data: list, top_n=10):
    """生成 WebP 转换建议。"""
    suggestions = []
    webp_present = any(res['identifier'].lower().endswith('.webp') for res in resources_data)
    
    if webp_present:
        # print("检测到项目中已使用 WebP 格式，不生成转换建议。")
        return ["<li>检测到项目中已使用 WebP 格式，不重复生成转换建议。</li>"]

    potential_candidates = []
    for resource in resources_data:
        ext = Path(resource['identifier']).suffix.lower()
        if ext in {'.png', '.jpg', '.jpeg'}:
            size_kb = resource['size'] / 1024.0
            if size_kb > WEBP_SUGGESTION_THRESHOLD_KB:
                 potential_candidates.append(resource)

    if not potential_candidates:
        return ["<li>未发现适合转换为 WebP 的大型 PNG/JPG 图片。</li>"]

    # 按大小排序
    potential_candidates.sort(key=lambda x: x['size'], reverse=True)

    suggestions.append(f"<li>考虑将以下大型 PNG/JPG 图片转换为 WebP 格式以减小体积 (预估可节省约 {int((1-WEB_P_GAIN_ESTIMATE)*100)}%):</li>")
    suggestions.append("<ul>")
    total_estimated_saving_bytes = 0
    count = 0
    for candidate in potential_candidates[:top_n]:
        estimated_saving = candidate['size'] * (1 - WEB_P_GAIN_ESTIMATE)
        total_estimated_saving_bytes += estimated_saving
        count += 1
        suggestions.append(f"  <li>{candidate['identifier']} ({format_size(candidate['size'])}) - 预估节省: {format_size(estimated_saving)}</li>")

    suggestions.append("</ul>")
    suggestions.append(f"<li>转换 Top {count} 张图片预估总共可节省: <strong>{format_size(total_estimated_saving_bytes)}</strong></li>")
    suggestions.append("<li>注意：WebP 转换可能需要调整部署目标或添加依赖库 (如 libwebp)。请在转换前进行充分测试。</li>")

    return suggestions

# --- Resource Processing Enhancement ---

def scan_resources(project_dir: Path, excluded_dirs: set, excluded_patterns: set):
    """扫描项目目录，查找所有资源文件和 Asset Catalog。"""
    all_files = {}
    asset_catalogs_analysis = []
    total_files_scanned = 0
    print("开始扫描资源文件...")
    
    # 使用 Path.rglob 进行递归扫描
    for file_path in tqdm(project_dir.rglob('*'), desc="扫描文件", unit=" 文件"):
        total_files_scanned += 1
        relative_path_str = str(file_path.relative_to(project_dir))
        parts = file_path.parts
        
        # 检查是否应排除
        if any(part in excluded_dirs for part in parts) or \
           any(pattern in relative_path_str for pattern in excluded_patterns):
            continue
            
        if file_path.is_file():
            ext = file_path.suffix.lower()
            # 常规资源文件（非 Asset Catalog 内部文件，将在下面处理）
            if ext in RESOURCE_EXTENSIONS and not any(part.endswith('.xcassets') for part in parts):
                size = get_file_size(str(file_path))
                # 使用相对路径作为 key
                all_files[relative_path_str] = {
                    'size': size,
                    'type': ext,
                    'referenced_in': set()
                }
        elif file_path.is_dir() and file_path.name.endswith('.xcassets'):
            print(f"\n发现 Asset Catalog: {relative_path_str}")
            # 分析 Asset Catalog，并将内部文件添加到 all_files
            catalog_analysis = analyze_asset_catalog(file_path, all_files)
            asset_catalogs_analysis.append(catalog_analysis)
            print(f"完成分析 Asset Catalog: {relative_path_str}, 问题数: {len(catalog_analysis.get('issues',[]))}")

    print(f"\n完成扫描，共扫描 {total_files_scanned} 个条目，找到 {len(all_files)} 个资源文件。")
    return all_files, asset_catalogs_analysis

# ... (find_references, analyze_project 等函数需要适配新的 all_files 结构)

def find_references(project_dir: Path, resources: dict, excluded_dirs: set, excluded_patterns: set):
    """在代码和配置文件中查找对资源的引用。"""
    print("开始查找资源引用...")
    potential_references = set()
    dynamic_references = set() # 用于存储动态引用模式的根名称

    files_to_scan = []
    for file_path in project_dir.rglob('*'):
        relative_path_str = str(file_path.relative_to(project_dir))
        parts = file_path.parts
        # 排除目录检查
        if any(part in excluded_dirs for part in parts) or \
           any(pattern in relative_path_str for pattern in excluded_patterns):
            continue
            
        if file_path.is_file():
            ext = file_path.suffix.lower()
            if ext in CODE_FILE_EXTENSIONS or ext in INTERFACE_FILE_EXTENSIONS or \
               ext in PLIST_FILE_EXTENSIONS or ext in OTHER_SEARCH_EXTENSIONS:
                 files_to_scan.append(file_path)

    # 使用多线程加速文件读取和正则匹配
    with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
         future_to_path = {executor.submit(scan_file_for_references, path): path for path in files_to_scan}
         for future in tqdm(as_completed(future_to_path), total=len(files_to_scan), desc="分析引用", unit=" 文件"):
             path = future_to_path[future]
             try:
                 file_refs, dynamic_refs = future.result()
                 potential_references.update(file_refs)
                 dynamic_references.update(dynamic_refs)
             except Exception as exc:
                 print(f'\n文件 {path} 生成引用时出错: {exc}')

    print(f"\n完成引用查找，找到 {len(potential_references)} 个潜在静态引用和 {len(dynamic_references)} 个动态引用模式。")

    # 更新 resources 字典中的引用信息
    referenced_keys = set()
    resource_identifiers = {Path(key).stem: key for key in resources.keys()} # Map stem to full key
    resource_full_paths = set(resources.keys())

    for ref in potential_references:
        # 1. 完全匹配 (e.g., "image.png")
        if ref in resource_full_paths:
            resources[ref]['referenced_in'].add("静态直接引用")
            referenced_keys.add(ref)
            continue
        
        # 2. 匹配文件名 (去除扩展名, e.g., "image") - 主要用于 Asset Catalog
        ref_stem = Path(ref).stem
        if ref_stem in resource_identifiers:
             res_key = resource_identifiers[ref_stem]
             resources[res_key]['referenced_in'].add("静态名称引用")
             referenced_keys.add(res_key)
             # 如果是 Asset Catalog 引用，标记其内的所有文件也被引用
             if resources[res_key].get('asset_catalog_set'):
                 set_name = resources[res_key]['asset_catalog_set']
                 for rk, r_info in resources.items():
                     if r_info.get('asset_catalog_set') == set_name:
                         r_info['referenced_in'].add("静态名称引用 (来自 Set)")
                         referenced_keys.add(rk)
             continue

        # 3. 可能的本地化字符串引用（检查 .lproj 目录）
        # This requires a more complex check involving .strings files, handle later

    # 4. 处理动态引用 (标记包含动态模式前缀/后缀的资源为可能被引用)
    for dyn_ref in dynamic_references:
         matched_dynamic = False
         for res_key in resource_full_paths:
             res_name = Path(res_key).name # Get filename.ext
             if dyn_ref in res_name: # Simple substring check
                 resources[res_key]['referenced_in'].add("动态模式引用 (可能)")
                 referenced_keys.add(res_key)
                 matched_dynamic = True
         # if matched_dynamic:
         #      print(f"动态模式 '{dyn_ref}' 匹配到资源")


    # 计算未使用资源
    unused_resources = []
    for key, data in resources.items():
        # If a resource has no references after checks
        if not data['referenced_in']:
             # Don't immediately flag files inside asset catalogs if the SET itself is referenced
             is_in_referenced_set = False
             if data.get('asset_catalog_set') and not data['asset_catalog_set'].endswith("(未定义)"):
                 set_name = data['asset_catalog_set']
                 # Find the primary key for this set (might be complex if no single file represents it)
                 # Simplified: Check if ANY file from this set was referenced by name
                 for rk_other, r_info_other in resources.items():
                     if r_info_other.get('asset_catalog_set') == set_name and \
                        any("静态名称引用" in s for s in r_info_other.get('referenced_in', set())):
                         is_in_referenced_set = True
                         break

             if not is_in_referenced_set:
                 unused_resources.append({
                     'identifier': key,
                     'size': data['size'],
                     'type': data['type']
                 })

    print(f"分析完成，发现 {len(unused_resources)} 个可能未使用的资源。")
    return unused_resources

# --- Main Analysis Function --- def analyze_project(project_dir_str: str, large_threshold_kb: int, similarity_threshold: int, output_format: str):
    """主分析函数。"""
    start_time = datetime.now()
    global project_root # Make project_root global for helper functions
    project_root = Path(project_dir_str).resolve()
    
    if not project_root.is_dir():
        print(f"错误：项目路径 '{project_dir_str}' 无效或不是一个目录。")
        sys.exit(1)

    # --- 1. 扫描资源文件和 Asset Catalogs ---
    all_resources, asset_catalogs_analysis = scan_resources(project_root, EXCLUDED_DIRS, EXCLUDED_DIR_PATTERNS)

    # --- 2. 查找资源引用 ---
    unused_resources_list = find_references(project_root, all_resources, EXCLUDED_DIRS, EXCLUDED_DIR_PATTERNS)

    # --- 3. 相似图片检测 (基于 all_resources 中识别的图片) ---
    image_files_to_hash = {
         key: data for key, data in all_resources.items()
         if Path(key).suffix.lower() in IMAGE_EXTENSIONS
    }
    similar_images_groups = find_similar_images(image_files_to_hash, similarity_threshold, project_root)

    # --- 4. 格式化资源数据以便报告 ---
    resources_data_list = []
    for key, data in all_resources.items():
        # 使用标识符（相对路径）
        resources_data_list.append({
            'identifier': key,
            'size': data['size'],
            'type': data.get('type', Path(key).suffix),
            'path': str(project_root / key), # Add absolute path for context
            'referenced': bool(data.get('referenced_in'))
        })
    # 按大小排序
    resources_data_list.sort(key=lambda x: x['size'], reverse=True)

    # --- 5. 生成优化建议 (包括超大图片等) ---
    optimization_suggestions_list = generate_optimization_suggestions(
        resources_data_list,
        large_threshold_kb,
        unused_resources_list,
        similar_images_groups
    )
    # --- 6. 生成 WebP 建议 ---
    webp_suggestions_list = generate_webp_suggestions(resources_data_list)

    # --- 7. 准备输出数据 ---
    total_size_bytes = sum(r['size'] for r in resources_data_list)
    output_data = {
        'project_dir': str(project_root),
        'timestamp': start_time.isoformat(),
        'total_size_bytes': total_size_bytes,
        'total_size_mb': total_size_bytes / (1024.0 * 1024.0),
        'resource_count': len(resources_data_list),
        'resources': resources_data_list,
        'unused_resources': sorted(unused_resources_list, key=lambda x: x['size'], reverse=True),
        'asset_catalog_analysis': asset_catalogs_analysis,
        'similar_images': similar_images_groups,
        'optimization_suggestions': optimization_suggestions_list,
        'webp_suggestions': webp_suggestions_list
    }

    # --- 8. 生成报告 ---
    generate_report(output_data, output_format, large_threshold_kb)

    end_time = datetime.now()
    print(f"\n分析总耗时: {end_time - start_time}")

# ... (generate_report 和 main 函数需要更新以包含新数据)
def generate_report(output_data: dict, output_format: str, large_threshold_kb: int):
    """根据指定的格式生成最终报告。"""
    timestamp = datetime.fromisoformat(output_data['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
    project_dir = output_data['project_dir']

    # --- 通用数据准备 ---
    resource_table_rows = ""
    large_threshold_bytes = large_threshold_kb * 1024
    for res in output_data['resources'][:100]: # Limit table size for readability
         size_kb = res['size'] / 1024.0
         is_large = res['size'] > large_threshold_bytes
         row_class = ' class="large-resource"' if is_large else ''
         # 显示相对路径作为标识符
         identifier = res['identifier']
         resource_table_rows += f'<tr{row_class}><td>{size_kb:.2f}</td><td>{res["type"]}</td><td>{identifier}</td><td>{res["path"]}</td></tr>\n'
    if len(output_data['resources']) > 100:
        resource_table_rows += "<tr><td colspan='4'>... (只显示最大的100个资源) ...</td></tr>"

    unused_resources_html = "<p>未发现可能未使用的资源。</p>" # Default message
    if output_data['unused_resources']:
        unused_resources_html = "<table><tr><th>大小 (KB)</th><th>类型</th><th>标识符 (相对路径)</th></tr>"
        for res in output_data['unused_resources']:
            size_kb = res['size'] / 1024.0
            unused_resources_html += f'<tr><td>{size_kb:.2f}</td><td>{res["type"]}</td><td>{res["identifier"]}</td></tr>\n'
        unused_resources_html += "</table><p class='note'>注意：未使用检测基于静态分析，可能存在误报（特别是动态引用或间接引用），请在删除前仔细确认。</p>"

    similar_images_html = "<p>未发现相似图片组。</p>"
    if output_data['similar_images']:
        similar_images_html = ""
        group_count = 0
        for i, group in enumerate(output_data['similar_images']):
            group_count += 1
            total_group_size = sum(img_data['size'] for img_data in group['files'])
            similar_images_html += f"<h4>相似组 {group_count} (总大小: {format_size(total_group_size)}, 哈希距离: {group['max_distance']})</h4><ul>"
            for img_data in group['files']:
                similar_images_html += f"<li>{img_data['path']} ({format_size(img_data['size'])})</li>"
            similar_images_html += "</ul>"

    optimization_suggestions_html = "<ul>" + "\n".join(output_data['optimization_suggestions']) + "</ul>"
    webp_suggestions_html = "<ul>" + "\n".join(output_data['webp_suggestions']) + "</ul>"

    asset_catalog_analysis_html = "<p>未找到或未分析 Asset Catalog。</p>"
    if output_data['asset_catalog_analysis']:
        asset_catalog_analysis_html = ""
        for catalog in output_data['asset_catalog_analysis']:
             # Assuming asset_path is now relative within catalog analysis data
             # catalog_rel_path = catalog.get('path', '未知路径')
             catalog_name = Path(catalog.get('path', '未知AssetCatalog')).name
             asset_catalog_analysis_html += f"<h3>{catalog_name} ({catalog.get('sets_analyzed', 0)} 个 Set)</h3>"
             if catalog.get("issues"):
                 asset_catalog_analysis_html += "<ul><strong>发现问题:</strong>"
                 for issue in catalog["issues"]:
                     level_class = "error" if issue["type"] == "error" else ("warning" if issue["type"] == "warning" else "info")
                     asset_catalog_analysis_html += f"<li class='{level_class}'>[{issue['type'].upper()}] {issue['message']}</li>"
                 asset_catalog_analysis_html += "</ul>"
             else:
                 asset_catalog_analysis_html += "<p>未发现明显问题。</p>"
             # Optionally add details about imagesets within the catalog
             # if catalog.get('imagesets'):
             #     asset_catalog_analysis_html += "<h4>Image Sets:</h4><ul>"
             #     for imgset in catalog['imagesets']:
             #         asset_catalog_analysis_html += f"<li>{imgset['name']} ({len(imgset['images'])} images, {format_size(imgset['total_size'])})</li>"
             #     asset_catalog_analysis_html += "</ul>"


    # --- 根据格式输出 ---
    if output_format == OutputFormat.HTML:
         # 使用增强的 HTML 模板
         total_image_size = sum(res['size'] for res in output_data['resources'] if Path(res['identifier']).suffix.lower() in IMAGE_EXTENSIONS)
         html_content = HTML_TEMPLATE.format(
             timestamp=timestamp,
             project_dir=project_dir,
             resource_table=resource_table_rows,
             unused_resources=unused_resources_html,
             asset_catalog_analysis=asset_catalog_analysis_html,
             similar_images=similar_images_html,
             optimization_suggestions=optimization_suggestions_html,
             webp_suggestions=webp_suggestions_html,
             total_size_mb=output_data['total_size_mb'],
             total_image_size_mb=total_image_size / (1024.0 * 1024.0)
         )
         output_filename = "resource_analysis_report.html"
         try:
             with open(output_filename, 'w', encoding='utf-8') as f:
                 f.write(html_content)
             print(f"HTML 报告已生成: {output_filename}")
         except IOError as e:
             print(f"错误：无法写入 HTML 文件 {output_filename}: {e}")

    elif output_format == OutputFormat.JSON:
         output_filename = "resource_analysis_report.json"
         # Exclude full path from JSON for cleaner output
         clean_resources = [
             {k: v for k, v in res.items() if k != 'path'} for res in output_data['resources']
         ]
         output_data['resources'] = clean_resources # Overwrite with cleaned data
         # Clean similar images paths too
         for group in output_data.get('similar_images', []):
              for file_data in group.get('files', []):
                   if 'full_path' in file_data: del file_data['full_path']

         try:
             with open(output_filename, 'w', encoding='utf-8') as f:
                 json.dump(output_data, f, indent=2, ensure_ascii=False)
             print(f"JSON 报告已生成: {output_filename}")
         except (IOError, TypeError) as e:
             print(f"错误：无法写入 JSON 文件 {output_filename}: {e}")

    elif output_format == OutputFormat.CSV:
        generate_csv_report(output_data)

    else: # Default to TEXT
         print("--- iOS 资源分析报告 ---")
         print(f"项目路径: {project_dir}")
         print(f"生成时间: {timestamp}")
         print(f"总资源大小: {output_data['total_size_mb']:.2f} MB")
         print(f"资源数量: {output_data['resource_count']}")
         print("\n--- 资源大小统计 (Top 50) ---")
         print("{:<10} {:<8} {:<60} {:<60}".format("大小(KB)", "类型", "标识符", "路径"))
         print("-" * 140)
         for res in output_data['resources'][:50]:
             size_kb = res['size'] / 1024.0
             is_large = res['size'] > large_threshold_bytes
             large_marker = "*" if is_large else " "
             print(f"{size_kb:<9.2f}{large_marker} {res['type']:<8} {res['identifier']:<60} {res['path']:<60}")
         if len(output_data['resources']) > 50: print("... (只显示最大的50个资源) ...")
         if any(res['size'] > large_threshold_bytes for res in output_data['resources']): print(f"(* 表示大于 {large_threshold_kb} KB)")

         print("\n--- Asset Catalog 分析 ---")
         if output_data['asset_catalog_analysis']:
             for catalog in output_data['asset_catalog_analysis']:
                 catalog_name = Path(catalog.get('path', '未知AssetCatalog')).name
                 print(f"  Catalog: {catalog_name} ({catalog.get('sets_analyzed', 0)} 个 Set)")
                 if catalog.get("issues"):
                     print("    发现问题:")
                     for issue in catalog["issues"]:
                         print(f"      - [{issue['type'].upper()}] {issue['message']}")
                 else:
                     print("    未发现明显问题。")
         else:
             print("  未找到或未分析 Asset Catalog。")


         print("\n--- 可能未使用的资源 ---")
         if output_data['unused_resources']:
             print("{:<10} {:<8} {:<60}".format("大小(KB)", "类型", "标识符 (相对路径)"))
             print("-" * 80)
             for res in output_data['unused_resources']:
                 size_kb = res['size'] / 1024.0
                 print(f"{size_kb:<9.2f} {res['type']:<8} {res['identifier']:<60}")
             print("\n注意：未使用检测基于静态分析，可能存在误报。")
         else:
             print("未发现可能未使用的资源。")

         print("\n--- 相似图片组 ---")
         if output_data['similar_images']:
             group_count = 0
             for i, group in enumerate(output_data['similar_images']):
                 group_count += 1
                 total_group_size = sum(img_data['size'] for img_data in group['files'])
                 print(f"  相似组 {group_count} (总大小: {format_size(total_group_size)}, 最大哈希距离: {group['max_distance']}):")
                 for img_data in group['files']:
                      # Use relative path from group data
                      rel_path = img_data.get('path', '未知路径')
                      print(f"    - {rel_path} ({format_size(img_data['size'])})")
         else:
             print("未发现相似图片组。")

         print("\n--- 资源优化建议 ---")
         if output_data['optimization_suggestions']:
             for suggestion in output_data['optimization_suggestions']:
                 # Simple text conversion from HTML list items
                 clean_suggestion = suggestion.replace("<li>", "- ").replace("</li>", "").replace("<strong>", "").replace("</strong>", "")
                 print(clean_suggestion)
         else:
             print("无特定优化建议。")

         print("\n--- WebP 转换建议 ---")
         if output_data['webp_suggestions']:
              for suggestion in output_data['webp_suggestions']:
                  clean_suggestion = suggestion.replace("<li>", "- ").replace("</li>", "").replace("<strong>", "").replace("</strong>", "").replace("<ul>","").replace("</ul>","").strip()
                  if clean_suggestion: # Avoid printing empty lines from ul tags
                       print(clean_suggestion)
         else:
              print("无 WebP 转换建议。")

def generate_csv_report(output_data: dict):
    """生成 CSV 格式的报告文件。"""
    files_created = []

    # 1. Resource Size Report
    res_size_file = "resource_size_report.csv"
    try:
        with open(res_size_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Identifier (Relative Path)', 'Size (Bytes)', 'Type', 'Is Referenced'])
            for res in output_data['resources']:
                writer.writerow([res['identifier'], res['size'], res['type'], res['referenced']])
        files_created.append(res_size_file)
    except IOError as e:
        print(f"错误: 无法写入 CSV 文件 {res_size_file}: {e}")

    # 2. Unused Resources Report
    unused_file = "unused_resources.csv"
    if output_data['unused_resources']:
        try:
            with open(unused_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Identifier (Relative Path)', 'Size (Bytes)', 'Type'])
                for res in output_data['unused_resources']:
                    writer.writerow([res['identifier'], res['size'], res['type']])
            files_created.append(unused_file)
        except IOError as e:
            print(f"错误: 无法写入 CSV 文件 {unused_file}: {e}")

    # 3. Similar Images Report
    similar_file = "similar_images.csv"
    if output_data['similar_images']:
        try:
            with open(similar_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Group ID', 'Max Hash Distance', 'File Path (Relative)', 'Size (Bytes)'])
                for i, group in enumerate(output_data['similar_images']):
                    group_id = i + 1
                    for img_data in group['files']:
                        writer.writerow([group_id, group['max_distance'], img_data['path'], img_data['size']])
            files_created.append(similar_file)
        except IOError as e:
            print(f"错误: 无法写入 CSV 文件 {similar_file}: {e}")

    # 4. Optimization Suggestions (including WebP)
    opt_file = "optimization_suggestions.csv"
    all_suggestions = output_data['optimization_suggestions'] + ["--- WebP Suggestions ---"] + output_data['webp_suggestions']
    if all_suggestions:
        try:
            with open(opt_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Suggestion'])
                for suggestion in all_suggestions:
                     # Clean HTML tags for CSV
                     clean_suggestion = suggestion.replace("<li>", "").replace("</li>", "").replace("<strong>", "").replace("</strong>", "").replace("<ul>","").replace("</ul>","").strip()
                     if clean_suggestion and clean_suggestion != "--- WebP Suggestions ---":
                         writer.writerow([clean_suggestion])
            files_created.append(opt_file)
        except IOError as e:
            print(f"错误: 无法写入 CSV 文件 {opt_file}: {e}")

    if files_created:
        print(f"CSV 报告文件已生成: {', '.join(files_created)}")
    else:
        print("未能生成任何 CSV 文件。")

# --- Main Execution --- if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='分析iOS项目资源文件，查找未使用资源和相似图片。')
    parser.add_argument('project_dir', help='iOS项目根目录的路径')
    parser.add_argument('--large-threshold', type=int, default=100,
                        help='大文件阈值（KB），超过此值的资源将被标记')
    parser.add_argument('--similarity-threshold', type=int, default=5,
                        help='图片相似度阈值（汉明距离），值越小表示要求越相似')
    parser.add_argument('--output', choices=[OutputFormat.TEXT, OutputFormat.JSON, OutputFormat.HTML, OutputFormat.CSV],
                        default=OutputFormat.TEXT, help='输出格式')

    args = parser.parse_args()

    analyze_project(args.project_dir, args.large_threshold, args.similarity_threshold, args.output)
