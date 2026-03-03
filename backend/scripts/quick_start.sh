#!/bin/bash
# CS 饰品数据采集系统 - 快速开始脚本
# 阶段0: 环境准备与验证

echo "========================================="
echo "  CS 饰品数据采集系统 - 阶段0验证"
echo "========================================="
echo ""

# 进入项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

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
    echo "   - STEAMDT_API_KEY (必填，用于 Youpin 价格)"
    echo "   - YOUPIN_HEADERS_FILE / YOUPIN_TEMPLATE_MAP_FILE (可选，用于直连悠悠有品)"
    echo "   - BUFF_GOODS_ID_MAP_FILE 或 BUFF_SEARCH_ENABLED+BUFF_COOKIES_FILE (用于直连Buff)"
    echo "   - STEAMDT_API_KEY (可选，仅用于基础库/磨损查询)"
    echo ""
    echo "配置完成后，请重新运行此脚本。"
    exit 0
fi

echo "🔍 检查环境配置..."
source .env
echo "✅ 环境配置检查通过"
echo ""

# 运行验证脚本
echo "========================================="
echo "  开始验证数据源"
echo "========================================="
echo ""

echo "📥 测试: 实时数据采集（Steam + Buff）"
echo "-------------------------------------"
VALIDATION_SCRIPT="backend/scripts/validation/02_test_realtime_scraper.py"
if [ -f "$VALIDATION_SCRIPT" ]; then
    python "$VALIDATION_SCRIPT"
    TEST_RESULT=$?
else
    echo "⚠️  未找到 $VALIDATION_SCRIPT，执行内置连通性检查..."
    python - <<'PY'
from backend.scrapers.buff_scraper import BuffScraper
from backend.scrapers.steam_scraper import SteamMarketScraper

ok = True

print("[CHECK] Buff 连接测试")
try:
    with BuffScraper() as buff:
        if not buff.test_connection():
            print("[FAIL] Buff 连接测试失败")
            ok = False
        else:
            print("[PASS] Buff 连接测试通过")
except Exception as exc:
    print(f"[FAIL] Buff 测试异常: {exc}")
    ok = False

print("[CHECK] Steam 价格抓取（可选，依赖代理）")
try:
    with SteamMarketScraper(use_proxy=True) as steam:
        data = steam.get_price("AK-47 | Redline (Field-Tested)")
        if data:
            print("[PASS] Steam 返回价格数据")
        else:
            print("[WARN] Steam 未返回价格数据（通常为代理/网络原因）")
except Exception as exc:
    print(f"[WARN] Steam 测试异常（不作为硬失败）: {exc}")

raise SystemExit(0 if ok else 1)
PY
    TEST_RESULT=$?
fi
echo ""

# 总结
echo "========================================="
echo "  验证结果总结"
echo "========================================="
echo ""

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ 实时数据采集测试通过"
else
    echo "❌ 实时数据采集测试失败"
fi

echo ""

if [ $TEST_RESULT -eq 0 ]; then
    echo "🎉 所有验证通过！可以开始开发了！"
    echo ""
    echo "📋 下一步："
    echo "   1. 查看开发路线图: cat roadmappro.md"
    echo "   2. 开始阶段1开发: 数据获取层"
    echo "   3. 查看历史质量报告: ls -lh data/quality_reports/"
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
