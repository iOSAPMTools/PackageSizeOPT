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
        </div>

        <div class="section">
            <h2 class="section-title">可能未使用的资源</h2>
            {unused_resources}
        </div>

        <div class="section">
            <h2 class="section-title">相似图片组</h2>
            {similar_images}
        </div>

        <div class="section">
            <h2 class="section-title">资源优化建议</h2>
            {optimization_suggestions}
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
    r'UIImage\(named:\s*["\']([\w\-]+)["\']\)|'          # Swift UIImage
    r'NSImage\(named:\s*["\']([\w\-]+)["\']\)|'          # Swift NSImage
    r'\[UIImage\s+imageNamed:\s*@?"([\w\-]+)"\]|'       # Obj-C UIImage
    r'\[NSImage\s+imageNamed:\s*@?"([\w\-]+)"\]|'       # Obj-C NSImage
    r'\b[Rr]\.(image|color|file|font)\.([\w\-]+)|'        # R.swift (or similar) - captures type and name
    r'Image\(\s*["\']([\w\-]+)["\']\)|'                   # SwiftUI Image("...")
    r'Image\(\s*systemName:\s*["\']([\w\-\.]+)["\']\)'    # SwiftUI Image(systemName: "...")
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
    
    # 输出优化建议
    print("\n--- 资源优化建议 ---")
    for suggestion in optimization_suggestions:
        print(f"\n{suggestion['type']}:")
        print(suggestion['suggestion'])

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

    print("\n分析完成。")

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
            total_size_mb=output_data['total_size_mb']
        )

        # Write HTML file
        output_file = 'resource_analysis_report.html'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"\nHTML 报告已生成：{os.path.abspath(output_file)}")
    else:  # Default text output
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
                line = f"{size_kb:12.2f} | {data['type']:<6} | {identifier} ({data['path']})"
                if size_kb >= large_threshold_kb:
                    print(f"{COLOR_RED}{line}{COLOR_RESET}")
                else:
                    print(line)
            print("-" * 100)
            print(f"总资源大小：{total_size_kb / 1024.0:.2f} MB")

        print("\n--- 资源优化建议 ---")
        for suggestion in optimization_suggestions:
            print(f"\n{suggestion['type']}:")
            print(suggestion['suggestion'])

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
