// Postman Pre-request Script: 自动带Token
// 放到所有需要认证的请求的 Pre-request Script 标签中

// 自动添加认证头
const token = pm.environment.get("access_token");
if (token) {
    pm.request.headers.add({
        key: "Authorization",
        value: "Bearer " + token
    });
}

// 自动添加请求ID
pm.request.headers.add({
    key: "X-Request-Id",
    value: "postman_" + Date.now()
});
