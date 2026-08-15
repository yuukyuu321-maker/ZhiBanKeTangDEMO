# PostgreSQL 数据契约

本目录定义学校 AI 基础设施中教材知识库 MVP 的 PostgreSQL 持久化边界、迁移账本、学校行级安全和本地运行角色。API 已具备教材只读仓储、工作区固定和教案修订写入能力，但不代表生产部署已经完成。

## 表与责任

| 表 | 责任 |
|---|---|
| `textbook_editions` | 学校拥有的教材版本元数据及活动状态 |
| `textbook_sources` | 内容哈希、导入状态、授权到期时间和复核责任 |
| `textbook_pages` | PDF 页索引、展示页码、尺寸和受控页图引用 |
| `textbook_evidence` | 原文、内容哈希和 PDF 顶部左侧坐标系区域 |
| `teaching_groups` | 学校、校区、学年、年级、班级和学科范围 |
| `principal_teaching_scopes` | 教师或管理者被授予的教学范围 |
| `textbook_assignments` | 教学范围在有效日期内适用的教材版本与源文件 |
| `workspace_textbook_pins` | 工作区创建时固定的分配、版本与源文件 |
| `lesson_plans` | 工作区教案、当前修订、草稿／教师确认状态和确认责任人 |
| `lesson_plan_revisions` | 不可覆盖的教案内容快照、指纹、生成来源和版本元数据 |
| `lesson_plan_revision_evidence` | 每个修订与固定教材证据之间的学校内关系 |
| `lesson_plan_events` | 生成、保存、恢复和确认等追加写审计事件 |

## 关键不变量

- 新工作区只能选择状态为 `active` 的教材；跨表状态检查由领域解析器和数据库适配器共同执行。
- 同一范围、同一优先级、同一日期出现多条有效分配时必须返回冲突，不按创建时间或“最新版本”静默选择。
- 班级分配优先于年级分配；班级未覆盖时才回退到年级范围。
- 工作区一经固定，不会因后续教材分配变化而漂移。
- 每条证据同时固定教材版本、源文件 SHA-256、PDF 页序号和区域坐标。
- `owner_school_id` 是学校数据所有权边界；十二张业务表已强制启用行级安全，仓储仍保留显式学校与主体授权条件。
- 导入状态为 `needs_review` 的真实教材不能因本地开发配置被写成 `approved` 或 `active`。
- 正式登记必须绑定批准包内容 SHA-256、导入管线版本、批准记录和首次登记操作方；登记不会自动激活或分配教材。
- `active` 教材版本和来源必须记录激活决定者、时间和理由；激活必须与一个明确、无同级日期冲突的适用关系在同一事务完成。
- 教材适用关系不自动授予人员权限；教师主体必须另行获得相同教学范围的活动授权。
- 教案修订、修订证据关系和事件只能追加，数据库触发器拒绝更新或删除历史记录；恢复会创建新修订。
- 教案证据必须同时属于同一学校、同一教案修订和工作区固定的教材版本／来源，不能跨校或跨教材拼接。
- 只有当前且未超预算的修订可以由教师确认；未确认教案不能通过正式导出端点导出。

## 应用迁移

在本地 PostgreSQL 容器健康后，由数据库所有者运行校验摘要的迁移器：

```powershell
$env:PYTHONPATH = "apps/textbook-knowledge-api;packages/domain/src"
.\.venv\Scripts\python -m app.migrations --database-url "postgresql://athena_owner:<secret>@127.0.0.1:5432/athena" --migration-dir deploy/postgres/migrations
```

迁移器建立 `athena_schema_migrations` 账本。完整的既有八表可引导登记 `0001`；部分既有结构、重复编号或摘要漂移会明确失败。

`0003_textbook_registration_provenance.sql` 为教材来源增加批准包指纹、管线版本、批准记录和登记操作方字段。旧记录可暂时为空，新的受控登记必须全部提供。

`0004_textbook_activation_audit.sql` 为教材版本和来源增加激活决定者、时间和理由，并用数据库约束阻止缺少审计信息的 `active` 状态。迁移不会自动激活任何教材。

`0005_lesson_plan_revisions.sql` 新增教案、修订、修订证据和审计事件表，并为工作区固定记录与教材证据补充复合唯一标识。四张新表强制学校行级安全，历史修订及其关系为追加写入。

`0006_lesson_plan_evidence_ownership.sql` 用包含 `owner_school_id` 的复合外键强化修订证据所有权，阻止跨学校证据关系。

## 批准教材登记

登记命令只接受位于 `data/imports/<edition-id>/<source-sha256>/` 且带有效 `promotion.json` 的正式教材包。学校 ID 必须由业务责任方明确提供：

```powershell
$env:PYTHONPATH = "packages/domain/src;packages/textbook-ingestion/src"
.\.venv\Scripts\python -m athena_ingestion register-postgres `
  --bundle "data/imports/<edition-id>/<source-sha256>" `
  --import-root "data/imports" `
  --database-url "postgresql://<registration-role>:<secret>@127.0.0.1:5432/athena" `
  --school-id "<stable-school-id>" `
  --registered-by "<responsible-operator-id>"
```

命令在学校行级上下文内原子登记版本、来源、页面和证据，状态固定为 `approved`。精确重跑幂等，数据漂移明确失败；命令不创建教学范围、教材分配或工作区固定记录。

## 受控激活、分配和主体授权

由课程或教材责任方确认学年、适用层级和日期后，使用 `activate-and-assign-postgres` 在单个事务中创建教学范围、教材分配并激活教材。活动范围建立后，再用 `grant-teaching-scope-postgres` 授权一个稳定主体标识。两个命令均显式要求 `school-id`，并在 SQL 与行级安全两层限制学校范围。

完整参数、冲突规则和验证步骤见 `07_Technology/School_AI/MVP/Increment_2_3_Activation_and_Scope_Runbook.md`。只读 `athena_app` 不能执行这两个管理动作；生产环境应建立独立、可审计的管理写入身份。

## 运行角色

`provision_runtime_role.psql` 创建固定的 `athena_app` 只读角色，并启用行级安全。该角色不能执行工作区或教案写入；本地开发闭环当前由数据库所有者运行。密码必须通过本地 psql 变量或密钥管理传入，不得写入仓库：

```powershell
$runtimePassword = Read-Host "athena_app password"
$script = Get-Content -Raw -Encoding utf8 deploy/postgres/provision_runtime_role.psql
$script | docker exec -i local-postgres-1 psql -U athena_owner -d athena -v "runtime_password=$runtimePassword"
```

生产环境仍需独立迁移身份、可信身份提供方、密钥托管、备份恢复和审计归档。教案工作区还需要一个受行级安全约束、权限小于数据库所有者且操作可审计的写入身份；当前仓库不虚构其凭据或部署配置。
