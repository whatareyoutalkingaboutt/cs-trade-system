# Buff 全量抓取记录

**日期**：2026-02-05  
**更新日期**：2026-02-06  
**目标**：从第 1 页开始全量抓取 Buff goods_id


### 方案 A：暂停 + 降速 + 退避重试

1) 暂停 10–30 分钟  
2) 从 `last_page + 1` 继续，降低速率并启用退避重试

示例

```bash
  python3 /Users/gaolaozhuanghouxianzi/sourcescrapper/scripts/buff_collect_goods_ids.py \
    --mode api \
    --start-page 1 \
    --max-pages 30 \
    --delay 2.5 \
    --max-retries 8 \
    --backoff 10 \
    --cookies-file /Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/buff/buff_cookies.json \
    --save-every 5 \
    --progress-file /Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/buff/buff_progress.json \
    --out-json /Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/buff/buff_goods_ids.json \
    --out-txt /Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/buff/goods_ids.txt
```

### 方案 B：实时监控进度

```bash
while true; do date; cat "/Users/gaolaozhuanghouxianzi/cs-item-scraper/docs/buff/buff_progress.json"; echo; sleep 2; done
```

## 备注

- 如果再次出现 `Action Forbidden`，优先暂停、降低速率再继续。  
- 确认只运行 **一个** 抓取进程，避免并发触发风控。  
