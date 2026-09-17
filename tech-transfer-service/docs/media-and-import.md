# 媒体与成果资料导入

## 运行配置

- `MEDIA_ROOT`：业务媒体的持久化目录。生产环境必须配置为代码目录外的挂载卷，例如 `/data/nanshan/media`。
- `MEDIA_BASE_URL`：文件读取接口前缀，默认 `/api/tech-transfer/v1/files`。
- `MAX_UPLOAD_BYTES`：单文件上限，默认 20MB。

文件正文只存于 `MEDIA_ROOT`，数据库 `file_object` 只保存元数据和 storage key。允许图片 `jpg/jpeg/png/webp/gif`，以及 `pdf/doc/docx/xls/xlsx/ppt/pptx`。图片上传同时校验后缀、真实 MIME 魔数和可解码的图片结构；读取时，上传者可读；被已发布成果或需求引用的文件可公开读取。

成果列表使用 `GET /api/tech-transfer/v1/files/{fileId}?variant=thumbnail`：服务端首次访问时在 `MEDIA_ROOT/.thumbnails/` 生成最长边 320px 的 JPEG 派生图，原图仍用于详情。缩略图不是数据库二进制字段，也不进入小程序包；删除未引用的原文件时会一并清理对应缩略图。

成果写接口的新版媒体字段是 `media`（含 `fileId`、角色与排序）。为兼容旧客户端，`mediaFileIds` 仍可提交：第一项会成为 `cover`，其余按顺序成为 `gallery`，并真实写入 `achievement_media`；不能与 `media` 同时传入。成果 `tags` 也会写入独立的 `achievement_tag` / `achievement_tag_relation`，不会再被静默丢弃。

## 小程序与域名

生产微信小程序需将 API 域名（以及 WebView 外链域名）加入微信后台业务域名白名单。动态成果图片和附件不能复制进小程序 `static` 或主包。

## PPT/PDF 暂存导入

```powershell
cd tech-transfer-service
..\.venv\Scripts\python.exe tools\import_achievement_documents.py <文件.pptx> --source-org <机构名> --created-by <用户ID>
```

工具只创建 `achievement_import_batch` 与 `achievement_import_item` 暂存记录，绝不自动创建或发布成果。每一页/幻灯片保留原始文本、规范化草稿、校验错误及来源页码，供后台确认后再写入正式成果。

先检查资料而不写数据库：

```powershell
..\.venv\Scripts\python.exe tools\import_achievement_documents.py <文件.pptx> --dry-run
```

输出会包含可暂存页数、校验失败页和候选图片数。

PPTX/PDF 内可识别的 PNG/JPEG/WebP/GIF 图片会在暂存时写入统一 `file_object` 媒体库；staging JSON 只保存文件 ID、名称和尺寸，不保存二进制。它们会以候选封面/成果图的形式随人工确认写入草稿。因为图片必须拥有可追溯的上传归属，**含图片的导入必须提供 `--created-by`**；请在确认前复核候选图，移除装饰背景、Logo 等非成果图片后再入库。

管理员可通过以下接口查看并逐条确认：

```text
GET  /api/tech-transfer/v1/admin/achievement-imports
GET  /api/tech-transfer/v1/admin/achievement-imports/{batchId}
POST /api/tech-transfer/v1/admin/achievement-imports/{batchId}/items/{itemId}/confirm
```

确认请求可携带经人工校正的成果字段（如 `title`、`techIntro`、`sections`、`patents`、`categoryId`）。接口只接受已通过暂存校验且仍为 `staged` 的记录；确认后创建一条 `draft` 成果，并更新批次成功数。**确认不等于发布**，成果仍必须走既有审核与发布状态机。
