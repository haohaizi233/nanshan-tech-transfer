# 概念验证中心 / 中小试基地 数据采集

## 数据来源

- 页面：[南方创投网 - 概念验证中心/中小试基地库](https://www.first-net.cn/page/portal/platformBase/platformBase.jsp)
- 接口：`POST /portal/platformBase_showPlatformBaseList`
- 分页：每页 20 条，全量约 5 页 / 100 条

## 字段对应

| 网站列名 | 源站字段 | 后台导入字段 | PG `institution` 列 |
| --- | --- | --- | --- |
| 序号 | storeId | serialNo / sourcePk | serial_no / source_pk |
| 平台名称 | platformName | name | name |
| 平台类型 | platformType | platformType / platformTypeKey | platform_type / platform_type_key |
| 依托单位 | supportUnit | unit | support_unit |
| 平台功能 | platformFun | functionText | functions |
| 联系人 | contactPerson | contact | contact_person |
| 联系方式 | contactMobile | phone | contact_mobile |

源站另有 `status`、`orderNum`，分别写入 `sourceStatus`、`orderNum`。

平台类型归一：含「概念验证」→ `poc`；含「中小试」或「中试」→ `pilot`。源站原文仍保留在 `platformType`。

## 输出文件

```bash
cd tools/platform-crawler
pip install -r requirements.txt
python crawl_platform_base.py
```

默认导出（不写 MySQL）：

- `concept_validation_centers.json` 概念验证中心
- `pilot_test_bases.json` 中小试基地（含源站「中试基地」）
- `platform_base_data.json` 全量 snake_case（兼容旧格式）

分类 JSON 的 `items` 可直接给后台 `POST /api/tech-transfer/v1/admin/institutions/import`。

如需写入 legacy MySQL `nanshan_capital.platform_base`：

```bash
python crawl_platform_base.py --mysql --host 127.0.0.1 --port 3307 --user root --password=
```

## 批量导入后台管理

后端需已启动（默认 `http://127.0.0.1:8787`）。按 `(kind, source_pk)` 幂等更新，可重复执行。

```bash
# 本地开发（mock 票据，dev-user-001 为 admin 种子）
python import_to_admin.py --base-url http://127.0.0.1:8787

# 账号密码
python import_to_admin.py --username admin --password Admin@2026

# 已有 JWT
python import_to_admin.py --token <jwt>
```

管理端「资本对接」页也支持 CSV 批量导入，模板列包含 `serialNo` / `unit` / `functionText` / `contact` / `phone`。
