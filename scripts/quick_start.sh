#!/bin/bash
# CS 饰品数据采集系统 - 快速开始脚本
# 阶段0: 环境准备与验证

echo "========================================="
echo "  CS 饰品数据采集系统 - 阶段0验证"
echo "========================================="
echo ""

# 检查虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 未找到虚拟环境，请先运行: python3 -m venv venv"
    exit 1
fi

# 激活虚拟环境
echo "🔄 激活虚拟环境..."
source venv/bin/activate

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env 文件"
    echo "📝 从 .env.example 创建 .env 文件..."
    cp .env.example .env
    echo ""
    echo "✅ .env 文件已创建"
    echo "📝 请编辑 .env 文件，配置以下内容："
    echo "   - PRICEMPIRE_API_KEY (必需，用于历史数据)"
    echo "   - STEAMDT_API_KEY (可选，用于Buff数据)"
    echo ""
    echo "配置完成后，请重新运行此脚本。"
    exit 0
fi

# 检查必需的API Key
echo "🔍 检查环境配置..."
source .env

if [ -z "$PRICEMPIRE_API_KEY" ] || [ "$PRICEMPIRE_API_KEY" = "your_pricempire_api_key_here" ]; then
    echo "❌ 未配置 PRICEMPIRE_API_KEY"
    echo "📝 请在 .env 文件中配置 PRICEMPIRE_API_KEY"
    echo "   获取地址: https://pricempire.com/api"
    exit 1
fi

echo "✅ 环境配置检查通过"
echo ""

# 运行验证脚本
echo "========================================="
echo "  开始验证数据源"
echo "========================================="
echo ""

echo "📥 测试1: 历史数据API（Pricempire）"
echo "-------------------------------------"
python scripts/validation/01_test_historical_api.py
TEST1_RESULT=$?
echo ""

echo "🔄 测试2: 实时数据采集（Steam + Buff）"
echo "-------------------------------------"
python scripts/validation/02_test_realtime_scraper.py
TEST2_RESULT=$?
echo ""

# 总结
echo "========================================="
echo "  验证结果总结"
echo "========================================="
echo ""

if [ $TEST1_RESULT -eq 0 ]; then
    echo "✅ 历史数据API测试通过"
else
    echo "❌ 历史数据API测试失败"
fi

if [ $TEST2_RESULT -eq 0 ]; then
    echo "✅ 实时数据采集测试通过"
else
    echo "❌ 实时数据采集测试失败"
fi

echo ""

if [ $TEST1_RESULT -eq 0 ] && [ $TEST2_RESULT -eq 0 ]; then
    echo "🎉 所有验证通过！可以开始开发了！"
    echo ""
    echo "📋 下一步："
    echo "   1. 查看开发路线图: cat ROADMAP.md"
    echo "   2. 开始阶段1开发: 数据获取层"
    echo "   3. 查看验证结果: ls -lh data/validation/"
    exit 0
else
    echo "⚠️  部分验证失败，请检查配置和网络连接"
    echo ""
    echo "💡 常见问题："
    echo "   - 确认API Key配置正确"
    echo "   - 确认网络连接正常"
    echo "   - 查看日志了解详细错误"
    exit 1
fi
