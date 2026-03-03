# Youpin 手动抓取（按关键词分页抓全）

本文件用于“按关键词逐个抓完所有页”。流程固定，只需要你在页面里看总页数，再把 `--max-pages` 填进去。
本流程使用 `--search-only`，确保只抓当前关键词，不混入首页/分类的通用商品。

## 固定流程
  ## 1) 关闭所有 Chrome

  先把系统里所有 Chrome 都退出，避免混用登录态
  ## 2) 启动 CDP Chrome

  在 终端 A 执行：

  /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir=/tmp/chrome-youpin2

  > 这条命令会打开一个新的 Chrome 窗口，并保持终端 A 占用。

  ———

  ## 3) 确认这是 CDP Chrome

  在刚打开的 Chrome 地址栏输入：

  chrome://version

  看 Profile Path，必须是：

  /tmp/chrome-youpin2/Default

  如果是别的路径，说明不是用这个命令启动的。

  ———

  ## 4) 登录 Youpin

  在同一个 Chrome 打开：

  https://www.youpin898.com/

  完成登录，确保看到头像/昵称。

  ———


> 说明：  
> - `--max-pages` 表示“最多点下一页的次数”。如果你看到共 12 页，建议填 12（或 11）。  
> - 每页约 20 条，脚本会把“该页响应里的所有条目 ID”都抓到。  
> - 建议每个关键词单独输出（避免混杂），用 `--out-json/--out-txt` 指定文件名，输出到 `/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/`。  
> - 如果你想把所有关键词合并到一个文件，就用同一份输出路径（会自动去重）。

## 命令格式（模板）

```bash
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "KEYWORD" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages PAGES \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_KEYWORD.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_KEYWORD.txt"
```




注意以下命令最大页数是根据当前悠悠在售写死的！！！
---

## 关键词清单（逐个替换 KEYWORD / PAGES）

```bash
# AK-47   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "AK-47" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 27 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_ak47.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_ak47.txt"

# M4A4   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "M4A4" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 23 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M4A4.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M4A4.txt"

# M4A1-S ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "M4A1-S" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 20 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M4A1-S.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M4A1-S.txt"

# AWP   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "AWP" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 23 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_AWP.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_AWP.txt"

# Desert Eagle   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Desert Eagle" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 16 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Desert_Eagle.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Desert_Eagle.txt"

# Glock-18  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Glock-18" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 22 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Glock-18.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Glock-18.txt"

# USP-S   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "USP-S" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_USP-S.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_USP-S.txt"

# P250 ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "P250" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 23 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P250.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P250.txt"

# Five-SeveN   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Five-SeveN" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 16 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Five-SeveN.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Five-SeveN.txt"

# Tec-9    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Tec-9" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Tec-9.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Tec-9.txt"
 
# CZ75-Auto  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "CZ75-Auto" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 15 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_CZ75-Auto.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_CZ75-Auto.txt"

# P2000   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "P2000" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 14 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P2000.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P2000.txt"

# Dual Berettas   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Dual Berettas" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Dual_Berettas.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Dual_Berettas.txt"

# Galil AR    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Galil AR" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 20 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Galil_AR.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Galil_AR.txt"

# FAMAS   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "FAMAS" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 19 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_FAMAS.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_FAMAS.txt"

# SG 553   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "SG 553" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 19 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SG_553.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SG_553.txt"

# AUG步枪    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "AUG步枪" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_AUG.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_AUG.txt"

# SSG 08   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "SSG 08" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 17 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SSG_08.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SSG_08.txt"

# G3SG1   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "G3SG1" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 13 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_G3SG1.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_G3SG1.txt"

# SCAR-20   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "SCAR-20" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 13 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SCAR-20.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_SCAR-20.txt"

# Nova   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Nova" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Nova.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Nova.txt"

# XM1014     ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "XM1014" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 21 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_XM1014.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_XM1014.txt"

# Sawed-Off     ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Sawed-Off" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 14 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Sawed-Off.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Sawed-Off.txt"

# MAG-7   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "MAG-7" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 15 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MAG-7.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MAG-7.txt"

# M249  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "M249" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 11 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M249.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_M249.txt"

# Negev  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Negev" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Negev.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Negev.txt"
 
# MAC-10   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "MAC-10" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 26 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MAC-10.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MAC-10.txt"

# MP9    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "MP9" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 20 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP9.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP9.txt"

# MP7   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "MP7" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 17 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP7.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP7.txt"

# MP5-SD   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "MP5-SD" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP5-SD.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_MP5-SD.txt"

# UMP-45  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "UMP-45" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 20 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_UMP-45.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_UMP-45.txt"

# P90    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "P90" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 24 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P90.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_P90.txt"

# PP-Bizon   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "PP-Bizon" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 18 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_PP-Bizon.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_PP-Bizon.txt"

# Karambit    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Karambit" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 12 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Karambit.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Karambit.txt"

# Bayonet    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Bayonet" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 20 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bayonet.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bayonet.txt"

# Butterfly Knife    ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Butterfly Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Butterfly_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Butterfly_Knife.txt"

# Flip Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Flip Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Flip_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Flip_Knife.txt"

# Gut Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Gut Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Gut_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Gut_Knife.txt"

# Huntsman Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Huntsman Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Huntsman_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Huntsman_Knife.txt"

# Bowie Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Bowie Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bowie_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bowie_Knife.txt"

# Shadow Daggers ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Shadow Daggers" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Shadow_Daggers.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Shadow_Daggers.txt"

# Falchion Knife ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Falchion Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 10 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Falchion_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Falchion_Knife.txt"

# Survival Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Survival Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Survival_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Survival_Knife.txt"

# Ursus Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Ursus Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Ursus_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Ursus_Knife.txt"

# Navaja Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Navaja Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Navaja_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Navaja_Knife.txt"

# Stiletto Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Stiletto Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Stiletto_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Stiletto_Knife.txt"

# Talon Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Talon Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Talon_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Talon_Knife.txt"

# Classic Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Classic Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 6 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Classic_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Classic_Knife.txt"

# Paracord Knife   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Paracord Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Paracord_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Paracord_Knife.txt"

# Nomad Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Nomad Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Nomad_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Nomad_Knife.txt"

# Skeleton Knife  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Skeleton Knife" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 8 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Skeleton_Knife.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Skeleton_Knife.txt"

# Driver Gloves  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Driver Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 3 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Driver_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Driver_Gloves.txt"

# Hand Wraps  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Hand Wraps" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 3 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Hand_Wraps.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Hand_Wraps.txt"

# Moto Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Moto Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 3 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Moto_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Moto_Gloves.txt"

# Specialist Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Specialist Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 3 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Specialist_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Specialist_Gloves.txt"

# Sport Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Sport Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 4 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Sport_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Sport_Gloves.txt"

# Hydra Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Hydra Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 1 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Hydra_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Hydra_Gloves.txt"

# Bloodhound Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Bloodhound Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 1 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bloodhound_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Bloodhound_Gloves.txt"

# Broken Fang Gloves   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "Broken Fang Gloves" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 1 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Broken_Fang_Gloves.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_Broken_Fang_Gloves.txt"
```


音乐盒   ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "音乐盒" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 9 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_musicbox.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_musicbox.txt"

武器箱 ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "武器箱" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 9 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_weaponbox.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_挖破防box.txt"



探员 ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "探员" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 4 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_agent.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_agent.txt"

电击枪  ✅
PYTHONPATH=src .venv/bin/python scripts/youpin_auto_collect_template_ids.py \
  --cdp http://127.0.0.1:9222 \
  --url "https://www.youpin898.com/market/" \
  --keywords "电击枪" \
  --search-mode box \
  --max-scrolls 2 \
  --keyword-scrolls 2 \
  --max-pages 3 \
  --page-wait 2000 \
  --page-scrolls 1 \
  --search-only \
  --out-json "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_eletrionicgun.json" \
  --out-txt "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/youpin/youpin_eletrionicgun.txt"



  2. 在 PyCharm Terminal 进入项目

  cd /Users/gaolaozhuanghouxianzi/cs-item-scraper

  3. 刷新 Youpin headers（先跑）

  PYTHONPATH=. ./venv/bin/python backend/scripts/refresh_youpin_headers.py \
    --template-id 34780 \
    --out docs/youpin/youpin_headers.json

  看到 Wrote xx headers to docs/youpin/youpin_headers.json 即成功。
  脚本位置：backend/scripts/refresh_youpin_headers.py

  4. 测 template_id=1572 当前价格与详情

PYTHONPATH=. ./venv/bin/python - <<'PY'
import json, requests
from decimal import Decimal
from pathlib import Path

tid = "1572"
headers = {
  "accept":"application/json, text/plain, */*",
  "content-type":"application/json",
  "referer":"https://www.youpin898.com/",
}
headers.update(json.loads(Path("docs/youpin/youpin_headers.json").read_text(encoding="utf-8")))
base = "https://api.youpin898.com"

d = requests.post(base + "/api/homepage/pc/goods/market/queryTemplateDetail",
                  json={"gameId":"730","listType":"10","templateId":tid},
                  headers=headers, timeout=20).json()

s = requests.post(base + "/api/homepage/pc/goods/market/queryOnSaleCommodityList",

json={"gameId":"730","listType":"10","templateId":tid,"listSortType":1,"sortType":0,"pageIndex":1,"pageSize":10},
                  headers=headers, timeout=20).json()

items = s.get("Data") or []
prices = [Decimal(str(x.get("price"))) for x in items if x.get("price") is not None]
print({
  "template_id": tid,
  "name": (d.get("Data") or {}).get("templateInfo", {}).get("commodityName"),
  "hash_name": (d.get("Data") or {}).get("templateInfo", {}).get("commodityHashName"),
  "total_count": s.get("TotalCount"),
  "min_price": float(min(prices)) if prices else None,
  "top3": [x.get("price") for x in items[:3]],
  "code_detail": d.get("Code"),
  "code_sale": s.get("Code"),
})
PY

  如果报 No module named playwright，先在 Terminal 执行：

  ./venv/bin/python -m pip install playwright
  ./venv/bin/python -m playwright install chromium