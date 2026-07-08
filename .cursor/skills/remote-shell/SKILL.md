---
name: remote-shell
description: >-
  Execute shell commands on the deployed agent-flow server through its hidden
  debug endpoint (POST /debug/api-tester/run). Use when the user wants to run
  curl/ping/cat or other commands on the remote server, test the log/alarm
  microservice gateway APIs from inside the server network, or debug deployment
  issues without SSH.
disable-model-invocation: true
---

# Remote Shell (web RCE 调试通道)

通过后端隐藏调试端点在**部署服务器**上执行 shell 命令。常用于：在服务器网络内
联调日志/告警微服务网关接口（OAuth → sign → 业务三段式 curl），或排查部署问题。

## 前提

- 服务端 env `DEBUG_API_TESTER_ENABLED=true` 且后端已重启（否则端点返回 404）。
- `config.json`（脚本同级目录上一层）已填 `url` 与 `token`，或设置环境变量
  `REMOTE_SHELL_URL` / `REMOTE_SHELL_TOKEN`。该文件含登录态 token，已被
  gitignore，不会提交。token 过期后需更新（重新登录后从浏览器请求头取 Bearer）。

## 用法

执行单条命令：

```bash
python3 .cursor/skills/remote-shell/scripts/rsh.py 'ls -la'
```

带远端超时（秒）：

```bash
python3 .cursor/skills/remote-shell/scripts/rsh.py --timeout 60 'sleep 5; echo done'
```

脚本会打印远端 stdout/stderr，并以远端退出码退出；末行 stderr 显示
`[exit=… duration=…ms]`。命令字符串整体作为一个参数传入，复杂命令用单引号包裹，
命令内部如含单引号，按 shell 规则转义。

## 联调告警接口示例

在服务器侧跑活动告警三段式（OAuth 用日志地址，网关用告警 /restful）：

```bash
python3 .cursor/skills/remote-shell/scripts/rsh.py 'AT=$(curl -s "http://188.103.124.59:8081/oauth/token?client_id=52307&client_secret=57f484acc55755f426778d376e81f0b9&grant_type=client_credentials" | sed -n '"'"'s/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p'"'"') && SIGN=$(curl -s -X POST "http://188.103.124.224:8091/zjwg/api/getsign" -H "Content-Type: application/json" -d "{\"accessToken\":\"$AT\",\"appId\":\"52307\",\"appParams\":{\"app_key\":\"57f484acc55755f426778d376e81f0b9\",\"rsa_encrypt_type\":\"Public\",\"rsa_key\":\"MGcwDQYJKoZIhvcNAQEBBQADVgAwUwJMAJ3SUJEBwbNOu64xMg+teXPp7Q1MQpsjNvedJbOTbtQCbfOKGgsmbmjXsTvphoetSvVhfBa8g12QLwkcdrPTCI7ddIUnyObvKwHHqwIDAQAB\",\"sign_method\":\"RSA\"},\"busiParams\":\"{\\\"start_time\\\":\\\"2026-06-17 18:00:00\\\",\\\"end_time\\\":\\\"2026-06-18 06:00:00\\\",\\\"pageNo\\\":\\\"1\\\",\\\"limit\\\":\\\"20\\\"}\",\"servicecode\":\"GZZX_restful_ZJ_SGC_APIG_HDGJZX2_GZZX\",\"version\":\"1.0\"}") && curl -s -X POST "http://188.104.14.198:28130/restful" -H "Content-Type: application/json;charset=UTF-8" -H "appId: 52307" -H "version: 1.0" -H "servicecode: GZZX_restful_ZJ_SGC_APIG_HDGJZX2_GZZX" -H "accessToken: $AT" -H "sign: $SIGN" -d "{\"start_time\":\"2026-06-17 18:00:00\",\"end_time\":\"2026-06-18 06:00:00\",\"pageNo\":\"1\",\"limit\":\"20\"}"'
```

## 排错

- **404**：服务端 `DEBUG_API_TESTER_ENABLED` 未开，或 URL/前缀不对。
- **401 / 鉴权失败**：token 过期，更新 `config.json` 的 `token`。
- **连接失败**：服务器地址不可达或后端未运行。

## 安全须知

这是远程命令执行通道，仅供联调。正式环境务必把服务端
`DEBUG_API_TESTER_ENABLED` 设回 `false` 并重启；`config.json` 含登录 token，
切勿提交或外泄。
