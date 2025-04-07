#!/bin/bash

# CI/CD 包体积分析示例脚本
# 请根据您的项目和 CI 环境进行修改

set -e # 如果任何命令失败，则退出脚本

# --- 配置变量 (请修改为您的实际值) ---
PROJECT_NAME="YourProject"
SCHEME_NAME="YourAppScheme" # 主要 App Target 的 Scheme
CONFIGURATION="Release" # 通常分析 Release 版本
WORKSPACE_PATH="$PROJECT_NAME.xcworkspace" # 或者 .xcodeproj 路径
IPA_OUTPUT_DIR="./build/ipa" # IPA 文件输出目录
LINKMAP_OUTPUT_DIR="./build/linkmap" # Link Map 文件输出目录 (需要配置 Xcode Build Settings)

# --- 体积阈值 (示例，单位：字节) ---
IPA_SIZE_THRESHOLD=104857600 # 100 MB
LINKMAP_MAIN_EXECUTABLE_THRESHOLD=52428800 # 50 MB (LinkMap 中主执行文件的符号大小)
# 可以添加更多阈值，例如针对特定库或资源

# --- 辅助函数 ---
get_latest_ipa() {
    # 查找最新的 IPA 文件 (基于修改时间)
    find "$IPA_OUTPUT_DIR" -maxdepth 1 -name "*.ipa" -print0 | xargs -0 ls -t | head -n 1
}

get_latest_linkmap() {
    # 查找最新的 LinkMap 文件 (通常包含 Target 名称和架构)
    # 注意：您的 LinkMap 文件名格式可能不同
    find "$LINKMAP_OUTPUT_DIR" -maxdepth 1 -name "*$SCHEME_NAME*-LinkMap-*.txt" -print0 | xargs -0 ls -t | head -n 1
}

# --- 主要步骤 ---

echo "==== 1. 清理旧构建产物 ===="
rm -rf ./build # 清理之前的构建目录

echo "==== 2. 构建和归档 (示例) ===="
# !! 这是示例命令，请替换为您项目的实际构建和归档命令 !!
# 您可能需要使用 xcodebuild archive 或 fastlane 等工具
xcodebuild archive \
    -workspace "$WORKSPACE_PATH" \
    -scheme "$SCHEME_NAME" \
    -configuration "$CONFIGURATION" \
    -archivePath "./build/$PROJECT_NAME.xcarchive" \
    SKIP_INSTALL=NO \
    BUILD_LIBRARY_FOR_DISTRIBUTION=YES # 根据需要设置
# 确保您的 Xcode Build Settings 已配置生成 Link Map 文件 (Write Link Map File = Yes)
# 通常 Link Map 文件会输出到类似 DerivedData 的地方，您可能需要拷贝出来

echo "==== 3. 导出 IPA (示例) ===="
# !! 这是示例命令，请替换为您项目的实际导出命令 !!
# 您需要一个 ExportOptions.plist 文件
xcodebuild -exportArchive \
    -archivePath "./build/$PROJECT_NAME.xcarchive" \
    -exportPath "$IPA_OUTPUT_DIR" \
    -exportOptionsPlist "./ExportOptions.plist"

mkdir -p "$LINKMAP_OUTPUT_DIR"
# !! 示例：从 Xcode 的归档产物中查找并拷贝 Link Map 文件 !!
# Link Map 的确切路径取决于您的 Xcode 配置和版本
ARCHIVE_PRODUCTS_PATH="./build/$PROJECT_NAME.xcarchive/Products/Applications/$PROJECT_NAME.app"
LINKMAP_FILE_PATTERN="${SCHEME_NAME}-LinkMap-${CONFIGURATION}-*.txt" # 根据实际情况调整
# 查找 Link Map 文件 (这部分可能需要根据实际构建日志或产物结构调整)
echo "正在查找 Link Map 文件... (此步骤可能需要根据您的构建配置调整)"
# 尝试在标准位置查找，如果找不到，您需要手动指定或改进查找逻辑
DERIVED_DATA_PATH=$(xcodebuild -showBuildSettings -workspace "$WORKSPACE_PATH" -scheme "$SCHEME_NAME" -configuration "$CONFIGURATION" | grep "BUILD_DIR" | awk '{print $3}' | sed 's/\"//g')/../Intermediates.noindex
LINKMAP_SEARCH_PATH="$DERIVED_DATA_PATH/ArchiveIntermediates/$SCHEME_NAME/BuildProductsPath/$CONFIGURATION-iphoneos/"
echo "尝试在 $LINKMAP_SEARCH_PATH 查找 $LINKMAP_FILE_PATTERN"
FOUND_LINKMAP=$(find "$LINKMAP_SEARCH_PATH" -name "$LINKMAP_FILE_PATTERN" | head -n 1)

if [ -f "$FOUND_LINKMAP" ]; then
    cp "$FOUND_LINKMAP" "$LINKMAP_OUTPUT_DIR/"
    echo "Link Map 文件已拷贝到 $LINKMAP_OUTPUT_DIR"
elif [ -d "./build/$PROJECT_NAME.xcarchive" ]; then
    # 备用方案：尝试在 xcarchive 内查找（如果构建设置将其包含）
    echo "在 $LINKMAP_SEARCH_PATH 未找到，尝试在 .xcarchive 中查找..."
    find "./build/$PROJECT_NAME.xcarchive" -name "$LINKMAP_FILE_PATTERN" -exec cp {} "$LINKMAP_OUTPUT_DIR/" \;
else
    echo "警告：未能自动找到 Link Map 文件。请检查 Xcode 构建设置中的 Link Map 输出路径，并确保此脚本可以访问它。"
    # 您可以在这里添加从固定路径或环境变量获取 Link Map 的逻辑
fi


echo "==== 4. 执行包体积分析 ===="
LATEST_IPA=$(get_latest_ipa)
LATEST_LINKMAP=$(get_latest_linkmap)

ANALYSIS_SUCCESS=true

if [ -z "$LATEST_IPA" ]; then
    echo "错误：找不到 IPA 文件！" 
    ANALYSIS_SUCCESS=false
else
    echo "分析 IPA: $LATEST_IPA"
    # 运行 ipa_analyzer.py (分析并保存历史记录)
    python ipa_analyzer.py --analyze "$LATEST_IPA" || ANALYSIS_SUCCESS=false
    
    # 检查 IPA 大小
    IPA_SIZE=$(stat -f%z "$LATEST_IPA")
    echo "当前 IPA 大小: $IPA_SIZE 字节"
    if [ $IPA_SIZE -gt $IPA_SIZE_THRESHOLD ]; then
        echo "错误：IPA 大小 ($IPA_SIZE bytes) 超出阈值 ($IPA_SIZE_THRESHOLD bytes)！" >&2
        ANALYSIS_SUCCESS=false
    else
        echo "IPA 大小在阈值范围内。"
    fi
fi

if [ -z "$LATEST_LINKMAP" ]; then
    echo "警告：找不到 Link Map 文件，跳过 Link Map 分析。" 
    # 根据您的策略，找不到 LinkMap 可能也应该视为失败
    # ANALYSIS_SUCCESS=false 
else
    echo "分析 Link Map: $LATEST_LINKMAP"
    # 运行 linkmap_analyzer_pro.py (生成文本报告到控制台)
    python linkmap_analyzer_pro.py "$LATEST_LINKMAP" --html ./build/linkmap_report.html || ANALYSIS_SUCCESS=false
    
    # 示例：检查 Link Map 中主执行文件的符号大小 (需要 linkmap_analyzer_pro.py 支持 JSON 输出)
    # python linkmap_analyzer_pro.py "$LATEST_LINKMAP" --json ./build/linkmap_report.json
    # if [ -f ./build/linkmap_report.json ]; then
    #     # 使用 jq 解析 JSON (需要安装 jq: brew install jq)
    #     MAIN_EXEC_SIZE=$(jq -r --arg scheme "$SCHEME_NAME" '.libraries[] | select(.name==$scheme) | .size' ./build/linkmap_report.json || echo 0)
    #     echo "Link Map 中主程序 ($SCHEME_NAME) 符号大小: $MAIN_EXEC_SIZE 字节"
    #     if [ $MAIN_EXEC_SIZE -gt $LINKMAP_MAIN_EXECUTABLE_THRESHOLD ]; then
    #         echo "错误：Link Map 主程序符号大小 ($MAIN_EXEC_SIZE bytes) 超出阈值 ($LINKMAP_MAIN_EXECUTABLE_THRESHOLD bytes)！" >&2
    #         ANALYSIS_SUCCESS=false
    #     else
    #         echo "Link Map 主程序符号大小在阈值范围内。"
    #     fi
    # else
    #     echo "警告：无法读取 Link Map JSON 报告，跳过符号大小检查。"
    # fi
fi

# 可以在此添加 resource_analyzer.py 和 build_settings_checker.py 的调用
# echo "==== 运行 Resource Analyzer ===="
# python resource_analyzer.py . --output html --output-file ./build/resource_report.html || ANALYSIS_SUCCESS=false

# echo "==== 运行 Build Settings Checker ===="
# python build_settings_checker.py "$WORKSPACE_PATH" --target "$SCHEME_NAME" --config "$CONFIGURATION" --format html --output ./build/build_settings_report.html || ANALYSIS_SUCCESS=false


echo "==== 5. 分析完成 ===="

if $ANALYSIS_SUCCESS; then
    echo "包体积分析成功，所有检查项通过。"
    exit 0
else
    echo "错误：包体积分析失败或超出阈值！" >&2
    exit 1 # CI/CD 流程应根据此退出码判断失败
fi 