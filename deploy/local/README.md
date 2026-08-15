# Local Deployment

当前只启动本地 PostgreSQL。教材源文件必须放在仓库忽略的 `data/sources` 或通过 `ATHENA_SOURCE_DIR` 指向的受控目录中。

```text
docker compose -f deploy/local/compose.yaml up -d
```

此配置仅用于开发，不是学校试点或生产部署方案。
