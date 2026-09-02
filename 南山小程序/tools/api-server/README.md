# 本地 API（供小程序读取 MySQL）

微信小程序无法直连 MySQL，需先启动本服务。

## 启动

```bash
cd tools/api-server
pip install -r requirements.txt
python app.py
```

默认地址：`http://127.0.0.1:8787`

## 接口

- `GET /api/health` 健康检查
- `GET /api/platform-base?type=poc|pilot|all&keyword=&page=&pageSize=` 概念验证/中小试
- `GET /api/service-orgs?keyword=&page=&pageSize=` 银行融资（专业服务机构）
- `GET /api/invest-orgs?keyword=&page=&pageSize=` 投资机构（特色投资机构）
- `GET /api/file/<fileId>` 机构 Logo 代理（带本地缓存）

## 小程序联调

1. 保持 MySQL（3307）与本 API 运行
2. 微信开发者工具：详情 → 本地设置 →勾选「不校验合法域名…」
3. 模拟器可用 `127.0.0.1`；真机请把 `南山/common/config.js` 的 `API_BASE` 改成电脑局域网 IP
4. 若 HBuilderX 未刷新 `.vue`，需同步 `unpackage/dist/dev/mp-weixin/` 中对应文件
