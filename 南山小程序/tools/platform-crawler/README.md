# 概念验证中心 / 中小试基地 数据采集

## 数据来源

- 页面：[南方创投网 - 概念验证中心/中小试基地库](https://www.first-net.cn/page/portal/platformBase/platformBase.jsp)
- 接口：`POST /portal/platformBase_showPlatformBaseList`
- 分页参数：`pagination.pageSize`、`pagination.pageIndex`

## 字段对应

| 网站列名 | 接口字段 | MySQL 列 |
| --- | --- | --- |
| 序号 | storeId | serial_no |
| 平台名称 | platformName | platform_name |
| 平台类型 | platformType | platform_type |
| 依托单位 | supportUnit | support_unit |
| 平台功能 | platformFun | platform_fun |
| 联系人 | contactPerson | contact_person |
| 联系方式 | contactMobile | contact_mobile |

## 数据库

- 库名：`nanshan_capital`
- 表名：`platform_base`
- 本机连接（当前环境）：见 `db_config.json`
  - host: `127.0.0.1`
  - port: **3307**（3306 已被其他 MySQL 占用）
  - user: `root`
  - password: 空（本地初始化，请尽快改密）

启动本机 8.4 实例（若未在跑）：

```powershell
& "C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqld.exe" --defaults-file="C:\ProgramData\MySQL\MySQL Server 8.4\my.ini"
```

## 使用

```bash
cd tools/platform-crawler
pip install -r requirements.txt

# 仅爬取导出 JSON（无需 MySQL）
python crawl_platform_base.py --skip-mysql

# 写入本地 MySQL（当前环境）
python crawl_platform_base.py --host 127.0.0.1 --port 3307 --user root --password=
```

重复执行会按 `serial_no` 做 upsert 更新。

当前已成功入库 **100** 条（概念验证中心 49 / 中小试基地 26 / 中试基地 25）。
