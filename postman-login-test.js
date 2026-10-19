// Postman Pre-request Script: 自动获取Token
// 放到 Login 请求的 Tests 标签中

// 登录后自动保存Token
if (pm.response.code === 200) {
    const jsonData = pm.response.json();
    if (jsonData.code === 0 && jsonData.data) {
        pm.environment.set("access_token", jsonData.data.accessToken);
        pm.environment.set("refresh_token", jsonData.data.refreshToken);
        console.log("Token已保存到环境变量");
    }
}
