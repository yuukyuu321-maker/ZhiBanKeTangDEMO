import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";

import {
  compareLessonPlanRevisions,
  confirmLessonPlan,
  exportLessonPlan,
  generateLessonPlan,
  getLessonPlan,
  listLessonPlanRevisions,
  loadEvidenceRender,
  restoreLessonPlanRevision,
  saveLessonPlan,
  searchWorkspaceTextbook,
  type EvidenceItem,
  type LessonPlan,
  type LessonPlanContent,
  type LessonPlanRevisionSummary,
  type SearchScope,
} from "./api";
import {
  REAL_TEACHER_TASK_CONFIG,
  REAL_TEACHER_TASK_EVIDENCE_IDS,
  REAL_TEACHER_TASK_TITLE,
} from "./realTeacherTask";

const SCOPE: SearchScope = {
  workspaceId:
    import.meta.env.VITE_ATHENA_WORKSPACE_ID ?? "workspace-demo-science-grade8",
  principalId: import.meta.env.VITE_ATHENA_PRINCIPAL_ID ?? "teacher-demo",
  schoolId: import.meta.env.VITE_ATHENA_SCHOOL_ID ?? "school-demo",
  academicYear: import.meta.env.VITE_ATHENA_ACADEMIC_YEAR ?? "2026-2027",
  grade: import.meta.env.VITE_ATHENA_GRADE ?? "八年级",
  subject: import.meta.env.VITE_ATHENA_SUBJECT ?? "科学",
  classId: import.meta.env.VITE_ATHENA_CLASS_ID ?? "class-2",
  onDate: import.meta.env.VITE_ATHENA_ON_DATE ?? "2026-10-01",
};

const SYNTHETIC_EVIDENCE: EvidenceItem = {
  id: "synthetic-evidence-001",
  title: "合成教材示例：空气的组成",
  location: "合成教材 · 第 1 章第 1 节 · 第 2 页",
  excerpt: "此段为合成内容，仅用于验证证据区域高亮。",
  editionId: "synthetic-science-grade8-volume2",
  sourceSha256: "a".repeat(64),
  pdfPageIndex: 2,
  pageLabel: "2",
  pageWidth: 680,
  pageHeight: 960,
  bbox: { x0: 60, y0: 248, x1: 620, y1: 366 },
  renderUrl: "/synthetic-page.svg",
};

function highlightStyle(item: EvidenceItem): CSSProperties {
  const left = Math.max(0, (item.bbox.x0 / item.pageWidth) * 100);
  const top = Math.max(0, (item.bbox.y0 / item.pageHeight) * 100);
  const right = Math.min(100, (item.bbox.x1 / item.pageWidth) * 100);
  const bottom = Math.min(100, (item.bbox.y1 / item.pageHeight) * 100);
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${Math.max(0, right - left)}%`,
    height: `${Math.max(0, bottom - top)}%`,
  };
}

function recalculateBudget(content: LessonPlanContent): void {
  const planned = content.lesson_segments.reduce(
    (total, segment) => total + segment.minutes,
    0,
  );
  const overBy = Math.max(0, planned - content.available_minutes);
  content.budget = {
    planned_minutes: planned,
    available_minutes: content.available_minutes,
    over_by_minutes: overBy,
    status: overBy > 0 ? "over_budget" : "within_budget",
  };
  content.session_budgets = content.sessions.map((session) => {
    const sessionPlanned = content.lesson_segments
      .filter((segment) => segment.session_id === session.session_id)
      .reduce((total, segment) => total + segment.minutes, 0);
    const sessionOverBy = Math.max(0, sessionPlanned - session.minutes);
    return {
      session_id: session.session_id,
      planned_minutes: sessionPlanned,
      available_minutes: session.minutes,
      over_by_minutes: sessionOverBy,
      status: sessionOverBy > 0 ? "over_budget" : "within_budget",
    };
  });

  const scheduledTopics = new Set(
    content.lesson_segments.flatMap((segment) => segment.topic_ids),
  );
  const experimentSessions = new Set(
    content.experiments.map((experiment) => experiment.session_id),
  );
  const blockers = [
    ...(overBy > 0 ? ["total_budget_overrun"] : []),
    ...content.session_budgets
      .filter((budget) => budget.over_by_minutes > 0)
      .map((budget) => `session_overrun:${budget.session_id}`),
    ...content.topic_coverage
      .filter((topic) => topic.status !== "covered")
      .map((topic) => `topic_evidence:${topic.topic_id}:${topic.status}`),
    ...content.topic_coverage
      .filter((topic) => !scheduledTopics.has(topic.topic_id))
      .map((topic) => `topic_unscheduled:${topic.topic_id}`),
    ...content.experiments
      .filter((experiment) => !experiment.teacher_safety_confirmed)
      .map((experiment) => `experiment_safety_review:${experiment.experiment_id}`),
    ...content.sessions
      .filter(
        (session) =>
          session.kind === "student_lab" &&
          !experimentSessions.has(session.session_id),
      )
      .map((session) => `student_lab_without_experiment:${session.session_id}`),
  ];
  content.confirmation_blockers = [...new Set(blockers)];
  content.confirmation_ready = content.confirmation_blockers.length === 0;
}

const SESSION_KIND_LABEL = {
  instruction: "讲授",
  demonstration: "演示实验",
  student_lab: "学生实验",
  mixed: "讲授与实验",
} as const;

const COVERAGE_STATUS_LABEL = {
  covered: "证据已覆盖",
  partial: "部分覆盖",
  missing: "缺少证据",
} as const;

const EXPERIMENT_MODE_LABEL = {
  demonstration: "教师演示",
  student_lab: "学生实验",
  demonstration_and_student: "演示并由学生实验",
} as const;

function confirmationBlockerLabel(
  blocker: string,
  content: LessonPlanContent,
): string {
  const [kind, identifier, status] = blocker.split(":");
  if (kind === "total_budget_overrun") return `总时间超过 ${content.available_minutes} 分钟预算`;
  if (kind === "session_overrun") return `课时 ${identifier} 超出时间预算`;
  if (kind === "topic_evidence") {
    const topic = content.topic_coverage.find((item) => item.topic_id === identifier);
    return `${topic?.title ?? identifier}：${status === "missing" ? "缺少证据" : "证据仅部分覆盖"}`;
  }
  if (kind === "topic_unscheduled") {
    const topic = content.topic_coverage.find((item) => item.topic_id === identifier);
    return `${topic?.title ?? identifier} 尚未排入任何教学环节`;
  }
  if (kind === "experiment_safety_review") {
    const experiment = content.experiments.find(
      (item) => item.experiment_id === identifier,
    );
    return `${experiment?.title ?? identifier} 尚未完成教师安全复核`;
  }
  if (kind === "student_lab_without_experiment") {
    return `学生实验课时 ${identifier} 尚未绑定实验`;
  }
  return blocker;
}

function EvidenceWorkspace() {
  const [query, setQuery] = useState("空气的组成");
  const [items, setItems] = useState<EvidenceItem[]>([SYNTHETIC_EVIDENCE]);
  const [selectedEvidenceIds, setSelectedEvidenceIds] = useState<string[]>([]);
  const [selected, setSelected] = useState<EvidenceItem | null>(null);
  const [sourceLabel, setSourceLabel] = useState("合成演示 · 固定版本");
  const [notice, setNotice] = useState(
    "当前显示合成证据，可连接本地 API 检索已分配教材。",
  );
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [revisions, setRevisions] = useState<LessonPlanRevisionSummary[]>([]);
  const [saveState, setSaveState] = useState("尚未生成教案");
  const [instruction, setInstruction] = useState("压缩导入，增加板书建议");
  const [comparison, setComparison] = useState<string | null>(null);
  const [pageImageUrl, setPageImageUrl] = useState<string | null>(null);
  const [pageImageStatus, setPageImageStatus] = useState<string | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  async function refreshRevisions(): Promise<void> {
    setRevisions(await listLessonPlanRevisions(SCOPE));
  }

  useEffect(() => {
    let disposed = false;
    getLessonPlan(SCOPE)
      .then(async (existing) => {
        if (disposed || existing === null) return;
        setPlan(existing);
        setSaveState(
          existing.status === "teacher_confirmed"
            ? `修订 ${existing.current_revision_number} · 教师已确认`
            : `修订 ${existing.current_revision_number} · 已保存 · 教师尚未确认`,
        );
        const history = await listLessonPlanRevisions(SCOPE);
        if (!disposed) setRevisions(history);
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setNotice(error instanceof Error ? error.message : "既有教案读取失败。");
        }
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (selected === null) return undefined;
    closeButton.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected]);

  useEffect(() => {
    setPageImageUrl(null);
    setPageImageStatus(null);
    if (selected === null || selected.renderUrl === null) return undefined;
    let disposed = false;
    let ownedUrl: string | null = null;
    setPageImageStatus("正在读取受控教材页图……");
    loadEvidenceRender(selected.renderUrl, SCOPE.principalId)
      .then((url) => {
        if (disposed) {
          if (url.startsWith("blob:")) URL.revokeObjectURL(url);
          return;
        }
        ownedUrl = url.startsWith("blob:") ? url : null;
        setPageImageUrl(url);
        setPageImageStatus(null);
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setPageImageStatus(
            error instanceof Error ? error.message : "无法读取教材页图。",
          );
        }
      });
    return () => {
      disposed = true;
      if (ownedUrl !== null) URL.revokeObjectURL(ownedUrl);
    };
  }, [selected]);

  useEffect(() => {
    if (plan === null || saveState !== "有未保存修改") return undefined;
    const snapshot = plan;
    const timer = window.setTimeout(() => {
      setSaveState("正在自动保存……");
      saveLessonPlan(
        SCOPE,
        snapshot.current_revision_number,
        snapshot.revision.content,
        "自动保存：教师调整结构化教案",
      )
        .then(async (saved) => {
          setPlan(saved);
          setSaveState(
            `修订 ${saved.current_revision_number} · 已自动保存 · 教师尚未确认`,
          );
          await refreshRevisions();
        })
        .catch((error: unknown) => {
          setSaveState(
            error instanceof Error ? `自动保存失败：${error.message}` : "自动保存失败。",
          );
        });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [plan, saveState]);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) {
      setNotice("请输入教材内知识点。");
      return;
    }
    setLoading(true);
    setNotice("正在固定教材工作区并执行教材内检索……");
    try {
      const result = await searchWorkspaceTextbook(trimmed, SCOPE);
      setItems(result.evidence);
      setSelectedEvidenceIds(result.evidence.slice(0, 5).map((item) => item.id));
      setSourceLabel(`${result.editionId} · ${result.assignmentId} · 固定版本`);
      setNotice(
        result.evidence.length > 0
          ? `找到 ${result.evidence.length} 条证据；已选择前 ${Math.min(5, result.evidence.length)} 条。`
          : "当前固定教材未覆盖该知识点，请调整关键词或人工确认。",
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "无法完成教材检索。");
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    if (selectedEvidenceIds.length === 0) {
      setNotice("请先检索并选择至少一条真实教材证据。");
      return;
    }
    setBusy("generate");
    try {
      const generated = await generateLessonPlan(
        SCOPE,
        query.trim() || "教材课题",
        selectedEvidenceIds,
      );
      setPlan(generated);
      setSaveState(`修订 ${generated.current_revision_number} · 已保存 · 教师尚未确认`);
      await refreshRevisions();
      setNotice("已生成 40 分钟结构化教案草稿；实验环节已锁定。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "教案生成失败。");
    } finally {
      setBusy(null);
    }
  }

  async function handleRealTaskGenerate() {
    setBusy("real-task");
    try {
      const generated = await generateLessonPlan(
        SCOPE,
        REAL_TEACHER_TASK_TITLE,
        REAL_TEACHER_TASK_EVIDENCE_IDS,
        REAL_TEACHER_TASK_CONFIG,
      );
      setPlan(generated);
      setQuery(REAL_TEACHER_TASK_TITLE);
      setSaveState(`修订 ${generated.current_revision_number} · 已保存 · 教师尚未确认`);
      await refreshRevisions();
      setNotice(
        "已载入约 140 分钟真实任务草稿；高锰酸钾法、向上排空气法和错误操作图仍需补充证据，实验安全仍需教师确认。",
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "真实任务草稿生成失败。");
    } finally {
      setBusy(null);
    }
  }

  function updateContent(change: (content: LessonPlanContent) => void) {
    setPlan((current) => {
      if (current === null) return current;
      const content = structuredClone(current.revision.content);
      change(content);
      recalculateBudget(content);
      return {
        ...current,
        status: "draft",
        confirmed_revision_number: null,
        export_ready: false,
        revision: { ...current.revision, content },
      };
    });
    setSaveState("有未保存修改");
    setComparison(null);
  }

  function applyInstruction() {
    const value = instruction.trim();
    const supported =
      (value.includes("压缩") && value.includes("导入")) ||
      value.includes("板书") ||
      value.includes("实验");
    if (plan === null || !value) {
      setNotice("请先生成教案并输入修改要求。");
      return;
    }
    if (!supported) {
      setNotice("本增量仅支持压缩导入、增加板书建议和锁定实验；其他要求未假装执行。");
      return;
    }
    updateContent((content) => {
      if (value.includes("压缩") && value.includes("导入")) {
        const opening = content.lesson_segments.find(
          (segment) =>
            segment.segment_id === "opening" ||
            segment.segment_id.endsWith("-opening"),
        );
        if (opening !== undefined) opening.minutes = Math.max(1, opening.minutes - 1);
      }
      if (value.includes("板书")) {
        const suggestion = "组成关系图：教材证据 → 关键观察 → 课堂结论";
        if (!content.board_plan.includes(suggestion)) content.board_plan.push(suggestion);
      }
      if (value.includes("实验")) {
        const experimentIds = new Set(
          content.experiments.map((experiment) => experiment.experiment_id),
        );
        for (const segment of content.lesson_segments) {
          if (segment.segment_id === "experiment" || experimentIds.has(segment.segment_id)) {
            segment.locked = true;
          }
        }
      }
    });
    setNotice("修改已落实到结构化教案，等待自动保存。");
  }

  async function handleCompare() {
    if (plan === null || plan.current_revision_number < 2) {
      setComparison("当前没有可比较的上一修订。");
      return;
    }
    setBusy("compare");
    try {
      const result = await compareLessonPlanRevisions(
        SCOPE,
        plan.current_revision_number - 1,
        plan.current_revision_number,
      );
      setComparison(
        `字段变化：${String(result.fields_changed ?? "无")}；环节变化：${String(result.segments_changed ?? "无")}；分钟变化：${String(result.planned_minutes_delta ?? 0)}。`,
      );
    } catch (error) {
      setComparison(error instanceof Error ? error.message : "修订比较失败。");
    } finally {
      setBusy(null);
    }
  }

  async function handleRestore(revisionNumber: number) {
    if (plan === null || saveState.includes("未保存") || saveState.includes("正在")) {
      setNotice("请等待当前修改保存后再恢复历史修订。");
      return;
    }
    setBusy(`restore-${revisionNumber}`);
    try {
      const restored = await restoreLessonPlanRevision(
        SCOPE,
        revisionNumber,
        plan.current_revision_number,
      );
      setPlan(restored);
      setSaveState(`修订 ${restored.current_revision_number} · 已恢复 · 教师尚未确认`);
      await refreshRevisions();
      setNotice(`已将修订 ${revisionNumber} 恢复为新修订，历史未被覆盖。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "修订恢复失败。");
    } finally {
      setBusy(null);
    }
  }

  async function handleConfirm() {
    if (plan === null) return;
    if (!plan.revision.content.confirmation_ready) {
      setNotice("当前仍有证据、排课、时间或实验安全阻断项，不能确认。");
      return;
    }
    if (saveState.includes("未保存") || saveState.includes("正在")) {
      setNotice("请等待自动保存完成后再确认。");
      return;
    }
    setBusy("confirm");
    try {
      const confirmed = await confirmLessonPlan(SCOPE, plan.current_revision_number);
      setPlan(confirmed);
      setSaveState(`修订 ${confirmed.current_revision_number} · 教师已确认 · 可导出`);
      setNotice("确认已记录；这不代表学校批准，也不会自动发送给学生或家长。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "教师确认失败。");
    } finally {
      setBusy(null);
    }
  }

  async function handleExport() {
    try {
      await exportLessonPlan(SCOPE);
      setNotice("已导出教师确认的结构化 JSON；教材原页未被复制到导出物。 ");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "教案导出失败。");
    }
  }

  const content = plan?.revision.content ?? null;
  const budget = content?.budget ?? null;
  const requiredMinutes =
    content?.lesson_segments
      .filter((segment) => segment.priority === "required")
      .reduce((total, segment) => total + segment.minutes, 0) ?? 0;
  const otherMinutes = (budget?.planned_minutes ?? 0) - requiredMinutes;

  return (
    <main className="app-shell">
      <header className="topbar">
        <div><span className="eyebrow">Project Athena</span><h1>教材备课工作台</h1></div>
        <div className="context" aria-label="当前教学范围">
          <span>{SCOPE.schoolId}</span><span>{SCOPE.subject} · {SCOPE.grade}</span>
          <span className={plan?.status === "teacher_confirmed" ? "confirmed" : "draft"}>
            {plan?.status === "teacher_confirmed" ? "教师已确认" : "草稿"}
          </span>
        </div>
      </header>

      <section className="workspace" aria-label="教师备课工作区">
        <aside className="conversation">
          <h2>对话与版本</h2>
          <div className="message teacher">真实任务：1.1 空气的成分，约 140 分钟；保留演示，并用 40 分钟连续完成制氧、气密性检测和收集学生实验。</div>
          <div className="message system">生成物默认是草稿；证据不足或实验安全未确认时不能由教师确认。</div>
          <button type="button" className="pilot-task-button"
            onClick={() => void handleRealTaskGenerate()} disabled={busy !== null}>
            {busy === "real-task" ? "载入中" : "载入 1.1 真实任务样例"}
          </button>
          <label htmlFor="instruction">修改要求</label>
          <textarea id="instruction" value={instruction} onChange={(event) => setInstruction(event.target.value)} />
          <button type="button" onClick={applyInstruction} disabled={plan === null}>应用到工作区</button>
          <p className="save-state" role="status">{saveState}</p>
          <div className="revision-list">
            <h3>修订历史</h3>
            {revisions.length === 0 && <p>尚无修订。</p>}
            {revisions.map((revision) => (
              <div className="revision-item" key={revision.revision_number}>
                <div><strong>修订 {revision.revision_number}</strong><span>{revision.change_summary}</span></div>
                {plan !== null && revision.revision_number !== plan.current_revision_number && (
                  <button type="button" className="link-button" disabled={busy !== null}
                    onClick={() => void handleRestore(revision.revision_number)}>
                    {busy === `restore-${revision.revision_number}` ? "恢复中" : "恢复为新修订"}
                  </button>
                )}
              </div>
            ))}
          </div>
        </aside>

        <article className="artifact">
          <div className="artifact-heading">
            <div><span className="eyebrow">教案草稿</span><h2>{content?.title ?? "尚未生成"}</h2></div>
            <strong className={budget?.status === "over_budget" ? "over-budget" : ""}>
              {budget === null ? "— / 40 分钟" : `${budget.planned_minutes} / ${budget.available_minutes} 分钟`}
            </strong>
          </div>
          <p className="evidence-rule">所有教材性主张均需证据支持；教师保留最终判断权。隐藏思维链不会被保存。</p>
          {content === null ? (
            <div className="empty-plan">
              <p>先在右侧检索并选择教材证据，再生成 40 分钟教案草稿。</p>
              <button type="button" onClick={() => void handleGenerate()}
                disabled={selectedEvidenceIds.length === 0 || busy !== null}>
                {busy === "generate" ? "生成中" : "生成教案草稿"}
              </button>
            </div>
          ) : (
            <>
              {content.sessions.length > 0 && (
                <section className="plan-section" aria-labelledby="session-heading">
                  <div className="section-heading">
                    <h3 id="session-heading">课时结构</h3>
                    <span>{content.sessions.reduce((total, session) => total + session.minutes, 0)} 分钟</span>
                  </div>
                  <div className="session-grid">
                    {content.sessions.map((session) => {
                      const sessionBudget = content.session_budgets.find(
                        (item) => item.session_id === session.session_id,
                      );
                      return (
                        <article className="session-card" key={session.session_id}>
                          <strong>{session.title}</strong>
                          <span>{SESSION_KIND_LABEL[session.kind]}</span>
                          <small>
                            {sessionBudget?.planned_minutes ?? 0} / {session.minutes} 分钟
                          </small>
                        </article>
                      );
                    })}
                  </div>
                </section>
              )}
              <ol className="segments editable-segments">
                {content.lesson_segments.map((segment, index) => (
                  <li key={segment.segment_id}>
                    <div className="segment-main">
                      <input aria-label={`环节 ${index + 1} 标题`} value={segment.title}
                        disabled={saveState.includes("正在") || segment.locked}
                        onChange={(event) => updateContent((next) => {
                          next.lesson_segments[index].title = event.target.value;
                        })} />
                      <small>
                        {segment.priority}{segment.locked ? " · 实验已锁定" : ""}
                        {segment.session_id ? ` · ${segment.session_id}` : ""}
                        {` · ${segment.topic_ids.length} 个知识点 · ${segment.evidence_ids.length} 条证据`}
                      </small>
                    </div>
                    <label className="minutes-input">
                      <input aria-label={`环节 ${index + 1} 分钟`} type="number" min="1"
                        value={segment.minutes} disabled={saveState.includes("正在") || segment.locked}
                        onChange={(event) => updateContent((next) => {
                          next.lesson_segments[index].minutes = Math.max(1, Number(event.target.value) || 1);
                        })} /> 分钟
                    </label>
                  </li>
                ))}
              </ol>
              {content.topic_coverage.length > 0 && (
                <section className="plan-section" aria-labelledby="coverage-heading">
                  <div className="section-heading">
                    <h3 id="coverage-heading">必讲知识点与证据</h3>
                    <span>{content.topic_coverage.filter((topic) => topic.status === "covered").length} / {content.topic_coverage.length} 已覆盖</span>
                  </div>
                  <div className="coverage-list">
                    {content.topic_coverage.map((topic, index) => (
                      <article className={`coverage-row ${topic.status}`} key={topic.topic_id}>
                        <span className="topic-number">{index + 1}</span>
                        <div><strong>{topic.title}</strong><small>{topic.notes || "等待教师复核"}</small></div>
                        <span>{COVERAGE_STATUS_LABEL[topic.status]} · {topic.evidence_ids.length} 条</span>
                      </article>
                    ))}
                  </div>
                </section>
              )}
              {content.experiments.length > 0 && (
                <section className="plan-section" aria-labelledby="experiment-heading">
                  <div className="section-heading"><h3 id="experiment-heading">实验链路</h3><span>安全确认由教师完成</span></div>
                  <div className="experiment-list">
                    {content.experiments.map((experiment, index) => (
                      <article className="experiment-card" key={experiment.experiment_id}>
                        <div><strong>{experiment.title}</strong><small>{EXPERIMENT_MODE_LABEL[experiment.mode]} · {experiment.minutes} 分钟 · {experiment.session_id}</small></div>
                        <p>{experiment.integrated_steps.join(" → ")}</p>
                        {experiment.safety_notes.map((note) => <small key={note}>{note}</small>)}
                        <label className="safety-check"><input type="checkbox"
                          checked={experiment.teacher_safety_confirmed}
                          disabled={saveState.includes("正在")}
                          onChange={(event) => updateContent((next) => {
                            next.experiments[index].teacher_safety_confirmed = event.target.checked;
                          })} /> 教师已完成本实验安全复核</label>
                      </article>
                    ))}
                  </div>
                </section>
              )}
              {content.confirmation_blockers.length > 0 && (
                <section className="confirmation-blockers" aria-labelledby="blocker-heading">
                  <h3 id="blocker-heading">确认前仍需处理</h3>
                  <ul>{content.confirmation_blockers.map((blocker) => (
                    <li key={blocker}>{confirmationBlockerLabel(blocker, content)}</li>
                  ))}</ul>
                </section>
              )}
              {comparison !== null && <p className="comparison">{comparison}</p>}
              <div className="actions">
                <button className="secondary" type="button" onClick={() => void handleCompare()} disabled={busy !== null}>比较上一修订</button>
                <button className="secondary" type="button" disabled={!plan?.export_ready || busy !== null}
                  onClick={() => void handleExport()}>导出已确认 JSON</button>
                <button type="button" onClick={() => void handleConfirm()}
                  disabled={plan?.status === "teacher_confirmed" || busy !== null || !content.confirmation_ready}>
                  {busy === "confirm" ? "确认中" : "教师确认"}
                </button>
              </div>
            </>
          )}
        </article>

        <aside className="evidence-panel">
          <div className="panel-heading">
            <div><h2>教材证据</h2><p>{sourceLabel}</p></div><span className="traceable">可追溯</span>
          </div>
          <form className="search-form" onSubmit={handleSearch}>
            <label htmlFor="textbook-query">只检索当前固定教材</label>
            <div><input id="textbook-query" value={query} onChange={(event) => setQuery(event.target.value)} />
              <button type="submit" disabled={loading}>{loading ? "检索中" : "检索"}</button></div>
          </form>
          <p className="search-status" role="status">{notice}</p>
          <div className="evidence-list">
            {items.map((item) => (
              <section className="evidence-card" key={item.id}>
                {item.id !== SYNTHETIC_EVIDENCE.id && (
                  <label className="evidence-select"><input type="checkbox"
                    checked={selectedEvidenceIds.includes(item.id)}
                    onChange={(event) => setSelectedEvidenceIds((current) =>
                      event.target.checked ? [...new Set([...current, item.id])] : current.filter((id) => id !== item.id)
                    )} /> 用于教案</label>
                )}
                <h3>{item.title}</h3><p className="location">{item.location}</p><p className="excerpt">{item.excerpt}</p>
                <button className="link-button" type="button" onClick={() => setSelected(item)}>打开原页并高亮</button>
              </section>
            ))}
          </div>
          {plan === null && selectedEvidenceIds.length > 0 && (
            <button className="generate-button" type="button" onClick={() => void handleGenerate()} disabled={busy !== null}>
              {busy === "generate" ? "生成中" : "用所选证据生成教案"}
            </button>
          )}
          <div className="budget"><h3>时间预算</h3>
            <p><span>必讲</span><strong>{requiredMinutes} 分钟</strong></p>
            <p><span>建议／可选</span><strong>{otherMinutes} 分钟</strong></p>
            <p><span>{(budget?.over_by_minutes ?? 0) > 0 ? "超出" : "余量"}</span>
              <strong>{budget === null ? "—" : `${budget.over_by_minutes > 0 ? budget.over_by_minutes : budget.available_minutes - budget.planned_minutes} 分钟`}</strong></p>
          </div>
        </aside>
      </section>

      {selected !== null && (
        <div className="viewer-backdrop" onMouseDown={(event) => {
          if (event.target === event.currentTarget) setSelected(null);
        }}>
          <section className="evidence-viewer" role="dialog" aria-modal="true" aria-labelledby="viewer-title">
            <header className="viewer-header"><div><span className="eyebrow">受控教材页图</span>
              <h2 id="viewer-title">{selected.title}</h2><p>{selected.location}</p></div>
              <button ref={closeButton} className="close-button" type="button" onClick={() => setSelected(null)}>关闭</button>
            </header>
            <div className="viewer-body"><div className="page-stage">
              {selected.renderUrl === null ? <div className="render-unavailable">该页暂无可用页图。</div>
                : pageImageUrl !== null ? <div className="page-image-wrap"><img src={pageImageUrl} alt={`教材 ${selected.pageLabel} 页`} />
                  <span className="evidence-highlight" style={highlightStyle(selected)} aria-label="证据原文区域" /></div>
                  : <div className="render-unavailable">{pageImageStatus ?? "正在读取受控教材页图……"}</div>}
            </div><aside className="viewer-evidence"><span className="traceable">证据原文</span>
              <blockquote>{selected.excerpt}</blockquote><dl>
                <div><dt>教材版本</dt><dd>{selected.editionId}</dd></div>
                <div><dt>PDF 页</dt><dd>{selected.pdfPageIndex}</dd></div>
                <div><dt>证据编号</dt><dd>{selected.id}</dd></div>
              </dl><p>如内容或位置有误，应提交纠正并保留历史。</p></aside></div>
          </section>
        </div>
      )}
    </main>
  );
}

export default EvidenceWorkspace;
