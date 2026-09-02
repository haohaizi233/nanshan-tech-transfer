# 科交中心资本对接数据爬虫

## 数据来源
- 专业服务机构（银行融资）：[知识产权质押融资信息服务](https://www.szte.com/capital/financeService/pledge/index.html)
- 特色投资机构（投资机构）：[特色投资机构一览](https://www.szte.com/visual/customize/detail?id=81)

## 表结构（库 `nanshan_capital`）
| 表名 | 用途 |
|------|------|
| `ip_service_org` | 专业服务机构：名称 + 简介（`intro`） |
| `featured_invest_org` | 特色投资机构：名称 + 列表/悬停简介（`intro`）+ 点击详情（`detail_info`） |

说明：
- `intro`：一览页卡片短文（悬停信息）
- `detail_info`：点击公司进入详情页后的机构介绍正文（源站仅部分机构有独立详情页）

## 用法

```bash
cd tools/szte-crawler
pip install pymysql
python crawl_szte_orgs.py
```

连接参数默认读取同目录 `db_config.json`（当前本机为 `127.0.0.1:3307`）。
