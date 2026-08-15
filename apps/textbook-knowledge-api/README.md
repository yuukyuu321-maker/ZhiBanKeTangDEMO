# Textbook Knowledge API

FastAPI 教材证据服务。当前提供：

- 健康检查；
- 导入清单与质量报告读取；
- 分页查看教材页面元数据；
- 受控页图读取；
- 只返回服务端证据锚点的本地关键词检索。
- 按主体和教学范围解析适用教材；
- PostgreSQL 只读仓储和 JSON 开发适配器；
- 学校范围行级安全配合显式授权查询；
- 将活动教材分配不可变固定到教师工作区；
- 按固定教材检索并通过受控工作区路径打开证据页；
- 基于所选教材证据生成结构化教案草稿；
- 表达非等长多课时、逐知识点证据覆盖、教师演示、连续学生实验和安全门禁；
- 追加保存、比较和恢复修订，并使用乐观并发避免静默覆盖；
- 教师确认当前未超预算修订后导出结构化 JSON；
- 从当前教师确认教案生成、追加保存、确认并导出证据约束的内部幻灯片故事板。

依赖安装后从仓库根目录运行：

```text
uvicorn app.main:app --app-dir apps/textbook-knowledge-api --reload
```

默认只允许读取 `approved` 或 `active` 导入包。人工抽查期间可显式设置 `ATHENA_LOCAL_REVIEW_MODE=true` 读取 `needs_review` 包；该设置不得用于共享或生产环境。

PDF 导入只通过本地命令行执行，API 不接受任意文件系统路径，也不会自动批准或启用教材。


## 教材适用关系后端

配置 `ATHENA_DATABASE_URL` 时，API 使用 PostgreSQL 仓储；否则回退到 `ATHENA_ASSIGNMENT_CATALOG` JSON 开发适配器。`GET /health` 通过 `assignment_catalog_backend` 返回 `postgresql`、`file` 或 `disabled`。

PostgreSQL 仓储在每个事务设置学校上下文，同时检查主体授权与教学范围。当前请求头仍是开发身份映射，不是生产认证。数据库只读运行角色和迁移命令见 `deploy/postgres/README.md`。

## 固定教材工作区

配置 `ATHENA_DATABASE_URL` 后，`POST /v1/workspaces` 在同一事务内解析活动教材分配并写入不可变固定记录。精确重放返回 `reused=true`；已经固定的工作区不得改绑主体、分配、教材版本或源摘要。

`GET /v1/workspaces/{workspace_id}/search` 只检索工作区固定教材，不因后来调整教材分配而漂移。工作区读取、检索和页面图接口每次都会重新检查固定主体的活动教学授权。详细运行和错误语义见 [`Increment_2_4_Workspace_Pinning_Runbook.md`](../../07_Technology/School_AI/MVP/Increment_2_4_Workspace_Pinning_Runbook.md)。

当前旧版无工作区读取接口仅用于本地导入调试和既有查看器兼容，不得作为生产教师入口直接发布。

## 教案工作区

配置 `ATHENA_DATABASE_URL` 后，API v0.6.0 提供以下路由：

- `POST /v1/workspaces/{workspace_id}/lesson-plan/generate`；
- `GET` 和 `PUT /v1/workspaces/{workspace_id}/lesson-plan`；
- `GET /v1/workspaces/{workspace_id}/lesson-plan/revisions`；
- `GET /v1/workspaces/{workspace_id}/lesson-plan/compare`；
- `POST /v1/workspaces/{workspace_id}/lesson-plan/revisions/{revision_number}/restore`；
- `POST /v1/workspaces/{workspace_id}/lesson-plan/confirm`；
- `GET /v1/workspaces/{workspace_id}/lesson-plan/export`。

生成器当前为离线、确定性的开发适配器。服务端会验证证据属于工作区固定教材，重算总预算、分课时预算、确认阻断项和内容指纹；修订只能追加，历史恢复会产生新修订。`athena.lesson-plan.v2` 增加 `sessions`、`topic_coverage`、`experiments`、`session_budgets` 与确认状态；服务端仍兼容读取 v1 内容。只有教师确认的当前修订可以导出结构化 JSON。单课时契约见 [`Increment_3_Lesson_Plan_Workspace_Runbook.md`](../../07_Technology/School_AI/MVP/Increment_3_Lesson_Plan_Workspace_Runbook.md)，多课时真实任务见 [`Increment_3_1_Multi_Session_Teacher_Task_Runbook.md`](../../07_Technology/School_AI/MVP/Increment_3_1_Multi_Session_Teacher_Task_Runbook.md)。

## 内部幻灯片故事板

`/v1/workspaces/{workspace_id}/slide-storyboard` 提供生成、读取、追加保存、教师确认和结构化 JSON 导出。生成只消费当前教师确认教案；页面不能伪造源教案外教材证据，源教案变化后既有故事板不能继续确认或导出。内容修订与固定模板版本分别记录。该接口现在定位为 PPTX 文档引擎的内部输入和技术审计接口，不再是默认教师工作面。教师明确登记的补充材料将在下一增量以 `teacher_supplied` 来源接入。详见 [`Increment_4_Slide_Storyboard_Runbook.md`](../../07_Technology/School_AI/MVP/Increment_4_Slide_Storyboard_Runbook.md) 和 [`ADR-0002`](../../ADR/ADR-0002-Conversational_PPTX_as_Teacher_Artifact.md)。

当前不提供生产身份、多教师协作、学校审批、产品内正式 PPTX 生成或隐藏思维链。正式 PPTX 将通过可替换的 `PresentationDocumentEngine` 生成；首个概念验证候选为 OfficeCLI。教师确认表示教师对当前草稿作出判断，不代表学校发布批准。
