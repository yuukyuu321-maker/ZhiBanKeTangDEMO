# Textbook Knowledge Web

React／TypeScript 教师 PPT 备课入口。教师端只保留“对话 + 当前 PPT 文件 + 附件”：教师说出生成或修改要求，未来直接获得标准 PPTX，并继续在 PowerPoint／WPS 中调整。当前页面是诚实的转向状态，OfficeCLI 等 PPTX 文档引擎尚未接入，因此不会误报已经生成文件。

2026-08-15 教师复核确认“和 AI 一起做 PPT”符合零学习成本目标，同时明确不会使用“教材与教案（高级）”页面，因此该教师入口和页面挂载已删除。原教案、逐页故事板、教材检索、证据编号和 JSON 能力继续作为后台生成、校验、追溯和开发排错基础，不构成教师可见产品页面。

## 本地运行

依赖安装后：

```text
pnpm install
pnpm --dir apps/textbook-knowledge-web dev
```

类型检查和生产构建：

```text
pnpm --dir apps/textbook-knowledge-web typecheck
pnpm --dir apps/textbook-knowledge-web build
```

## 开发配置

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| `VITE_ATHENA_API_BASE` | `http://127.0.0.1:8000` | 教材知识 API 地址 |
| `VITE_ATHENA_WORKSPACE_ID` | `workspace-demo-science-grade8` | 不可变工作区标识 |
| `VITE_ATHENA_PRINCIPAL_ID` | `teacher-demo` | 本地开发主体 |
| `VITE_ATHENA_SCHOOL_ID` | `school-demo` | 学校范围 |
| `VITE_ATHENA_ACADEMIC_YEAR` | `2026-2027` | 学年 |
| `VITE_ATHENA_GRADE` | `八年级` | 年级 |
| `VITE_ATHENA_SUBJECT` | `科学` | 学科 |
| `VITE_ATHENA_CLASS_ID` | `class-2` | 可选班级范围 |
| `VITE_ATHENA_ON_DATE` | `2026-10-01` | 首次固定时解析分配的日期 |

真实本地试点应通过未提交仓库的本地环境配置替换默认值。教材检索和证据页读取由后台服务使用固定教材工作区完成，不要求教师切换到独立页面。

内部教案自动保存使用约 800 毫秒静默期，并携带基础修订号；服务端检测到陈旧版本时明确提示冲突，不会静默覆盖。锁定实验、课时预算、教材证据和故事板继续作为正式 PPTX 文件生成的内部输入。教师只通过 PPT 对话入口表达修改，不直接操作这些结构。

真实任务样例使用批准教材包的证据编号。高锰酸钾法、向上排空气法和错误装置图可以由教师上传并标为 `teacher_supplied` 后进入 PPT 草稿，不再因教材未覆盖而被静默删除；图片不提交仓库，也不会被伪装为教材证据。

当前 `X-Athena-Principal-Id` 只是开发身份映射，不是生产认证。进入真实学校试点前必须接入学校身份系统或单点登录（SSO），并由后端会话或短期受控链接处理页图授权。
