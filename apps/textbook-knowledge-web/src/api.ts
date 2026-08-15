export type BoundingBox = {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
};

export type EvidenceItem = {
  id: string;
  title: string;
  location: string;
  excerpt: string;
  editionId: string;
  sourceSha256: string;
  pdfPageIndex: number;
  pageLabel: string;
  pageWidth: number;
  pageHeight: number;
  bbox: BoundingBox;
  renderUrl: string | null;
};

export type SearchScope = {
  workspaceId: string;
  principalId: string;
  schoolId: string;
  academicYear: string;
  grade: string;
  subject: string;
  classId?: string;
  onDate?: string;
};

export type AssignedSearchResult = {
  evidence: EvidenceItem[];
  editionId: string;
  assignmentId: string;
};

type ApiEvidence = {
  evidence_id: string;
  textbook_edition_id: string;
  source_sha256: string;
  pdf_page_index: number;
  page_label: string;
  printed_page?: number | null;
  chapter_id?: string | null;
  section_id?: string | null;
  quote: string;
  bbox: BoundingBox;
};

type ApiResult = {
  evidence: ApiEvidence;
  page: {
    width: number;
    height: number;
    render_available: boolean;
  };
  render_url: string | null;
};

type ApiWorkspace = {
  workspace_id: string;
  assignment_id: string;
  textbook: {
    edition_id: string;
    source_sha256: string;
  };
};

type WorkspaceCreateResponse = {
  workspace: ApiWorkspace;
  reused: boolean;
};

type WorkspaceSearchResponse = {
  results: ApiResult[];
  workspace: ApiWorkspace;
};

const API_BASE = (
  import.meta.env.VITE_ATHENA_API_BASE ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

function renderUrl(path: string | null): string | null {
  if (path === null) {
    return null;
  }
  return path.startsWith("http://") || path.startsWith("https://")
    ? path
    : `${API_BASE}${path}`;
}

function evidenceLocation(evidence: ApiEvidence): string {
  const page = evidence.printed_page ?? evidence.page_label;
  const structure = [evidence.chapter_id, evidence.section_id].filter(Boolean).join(" · ");
  return [structure, `第 ${page} 页`, `PDF 第 ${evidence.pdf_page_index} 页`]
    .filter(Boolean)
    .join(" · ");
}

async function responseProblem(response: Response, fallback: string): Promise<never> {
  const problem = (await response.json().catch(() => null)) as
    | { detail?: string }
    | null;
  throw new Error(problem?.detail ?? `${fallback}（HTTP ${response.status}）`);
}

export async function searchWorkspaceTextbook(
  query: string,
  scope: SearchScope,
): Promise<AssignedSearchResult> {
  const createResponse = await fetch(`${API_BASE}/v1/workspaces`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Athena-Principal-Id": scope.principalId,
    },
    body: JSON.stringify({
      workspace_id: scope.workspaceId,
      school_id: scope.schoolId,
      academic_year: scope.academicYear,
      grade: scope.grade,
      subject: scope.subject,
      class_id: scope.classId,
      on_date: scope.onDate,
    }),
  });
  if (!createResponse.ok) {
    return responseProblem(createResponse, "教材工作区固定失败");
  }
  const created = (await createResponse.json()) as WorkspaceCreateResponse;

  const params = new URLSearchParams({
    q: query,
    school_id: scope.schoolId,
  });
  const response = await fetch(
    `${API_BASE}/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/search?${params}`,
    { headers: { "X-Athena-Principal-Id": scope.principalId } },
  );
  if (!response.ok) {
    return responseProblem(response, "教材检索失败");
  }

  const payload = (await response.json()) as WorkspaceSearchResponse;
  if (
    payload.workspace.assignment_id !== created.workspace.assignment_id ||
    payload.workspace.textbook.edition_id !== created.workspace.textbook.edition_id
  ) {
    throw new Error("工作区固定记录与检索响应不一致");
  }

  return {
    editionId: payload.workspace.textbook.edition_id,
    assignmentId: payload.workspace.assignment_id,
    evidence: payload.results.map((result) => {
      const evidence = result.evidence;
      if (
        !Number.isFinite(result.page.width) ||
        !Number.isFinite(result.page.height) ||
        result.page.width <= 0 ||
        result.page.height <= 0
      ) {
        throw new Error("教材页尺寸无效，无法定位证据区域");
      }
      return {
        id: evidence.evidence_id,
        title: evidence.section_id ?? evidence.chapter_id ?? "教材证据",
        location: evidenceLocation(evidence),
        excerpt: evidence.quote,
        editionId: evidence.textbook_edition_id,
        sourceSha256: evidence.source_sha256,
        pdfPageIndex: evidence.pdf_page_index,
        pageLabel: evidence.page_label,
        pageWidth: result.page.width,
        pageHeight: result.page.height,
        bbox: evidence.bbox,
        renderUrl: renderUrl(result.render_url),
      };
    }),
  };
}

export type LessonSession = {
  session_id: string;
  title: string;
  minutes: number;
  kind: "instruction" | "demonstration" | "student_lab" | "mixed";
};

export type TopicEvidenceCoverage = {
  topic_id: string;
  title: string;
  status: "covered" | "partial" | "missing";
  evidence_ids: string[];
  notes: string;
};

export type LessonExperiment = {
  experiment_id: string;
  title: string;
  session_id: string;
  minutes: number;
  mode: "demonstration" | "student_lab" | "demonstration_and_student";
  topic_ids: string[];
  evidence_ids: string[];
  integrated_steps: string[];
  safety_notes: string[];
  teacher_safety_confirmed: boolean;
};

export type LessonSegment = {
  segment_id: string;
  title: string;
  minutes: number;
  priority: "required" | "recommended" | "optional";
  teacher_activity: string;
  student_activity: string;
  evidence_ids: string[];
  locked: boolean;
  session_id: string;
  topic_ids: string[];
};

export type BudgetSummary = {
  planned_minutes: number;
  available_minutes: number;
  over_by_minutes: number;
  status: "within_budget" | "over_budget";
};

export type SessionBudgetSummary = BudgetSummary & {
  session_id: string;
};

export type LessonPlanContent = {
  schema_version: "athena.lesson-plan.v1" | "athena.lesson-plan.v2";
  title: string;
  objectives: string[];
  required_topics: string[];
  available_minutes: number;
  sessions: LessonSession[];
  topic_coverage: TopicEvidenceCoverage[];
  experiments: LessonExperiment[];
  lesson_segments: LessonSegment[];
  board_plan: string[];
  checks_for_understanding: string[];
  materials: string[];
  omissions: string[];
  limitations: string[];
  budget: BudgetSummary;
  session_budgets: SessionBudgetSummary[];
  confirmation_ready: boolean;
  confirmation_blockers: string[];
};

export type LessonPlanGenerationConfig = {
  objectives: string[];
  requiredTopics: string[];
  lessonCount: number;
  minutesPerLesson: number;
  preserveExperiment: boolean;
  instruction: string;
  sessions?: LessonSession[];
  topicCoverage?: TopicEvidenceCoverage[];
  experiments?: LessonExperiment[];
};

export type LessonPlan = {
  plan_id: string;
  workspace_id: string;
  status: "draft" | "teacher_confirmed";
  current_revision_number: number;
  confirmed_revision_number: number | null;
  export_ready: boolean;
  revision: {
    revision_number: number;
    source: "generated" | "teacher_edit" | "restored";
    restored_from_revision: number | null;
    change_summary: string;
    content: LessonPlanContent;
  };
};

export type LessonPlanRevisionSummary = {
  revision_number: number;
  source: "generated" | "teacher_edit" | "restored";
  restored_from_revision: number | null;
  created_by: string;
  created_at: string;
  change_summary: string;
  content_sha256: string;
};

type LessonPlanResponse = {
  plan: LessonPlan;
  reused: boolean;
};

function principalHeaders(scope: SearchScope): Record<string, string> {
  return { "X-Athena-Principal-Id": scope.principalId };
}

function mutationHeaders(scope: SearchScope): Record<string, string> {
  return {
    ...principalHeaders(scope),
    "Content-Type": "application/json",
    "X-Athena-Request-Id": crypto.randomUUID(),
  };
}

function lessonPlanPath(scope: SearchScope): string {
  return `${API_BASE}/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/lesson-plan`;
}

export async function generateLessonPlan(
  scope: SearchScope,
  title: string,
  evidenceIds: string[],
  config?: LessonPlanGenerationConfig,
): Promise<LessonPlan> {
  const generation = config ?? {
    objectives: ["能够定位教材证据并用可审查步骤说明本课关键内容"],
    requiredTopics: [title],
    lessonCount: 1,
    minutesPerLesson: 40,
    preserveExperiment: true,
    instruction: "按 40 分钟生成一份教案，并保留实验环节。",
  };
  const response = await fetch(`${lessonPlanPath(scope)}/generate`, {
    method: "POST",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      title,
      objectives: generation.objectives,
      required_topics: generation.requiredTopics,
      lesson_count: generation.lessonCount,
      minutes_per_lesson: generation.minutesPerLesson,
      evidence_ids: evidenceIds,
      preserve_experiment: generation.preserveExperiment,
      instruction: generation.instruction,
      sessions: generation.sessions ?? [],
      topic_coverage: generation.topicCoverage ?? [],
      experiments: generation.experiments ?? [],
    }),
  });
  if (!response.ok) {
    return responseProblem(response, "教案草稿生成失败");
  }
  return ((await response.json()) as LessonPlanResponse).plan;
}

export async function getLessonPlan(
  scope: SearchScope,
): Promise<LessonPlan | null> {
  const params = new URLSearchParams({ school_id: scope.schoolId });
  const response = await fetch(`${lessonPlanPath(scope)}?${params}`, {
    headers: principalHeaders(scope),
  });
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    return responseProblem(response, "教案草稿读取失败");
  }
  return ((await response.json()) as LessonPlanResponse).plan;
}

export async function saveLessonPlan(
  scope: SearchScope,
  baseRevisionNumber: number,
  content: LessonPlanContent,
  changeSummary: string,
): Promise<LessonPlan> {
  const response = await fetch(lessonPlanPath(scope), {
    method: "PUT",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      base_revision_number: baseRevisionNumber,
      change_summary: changeSummary,
      content,
    }),
  });
  if (!response.ok) {
    return responseProblem(response, "教案自动保存失败");
  }
  return ((await response.json()) as LessonPlanResponse).plan;
}

export async function listLessonPlanRevisions(
  scope: SearchScope,
): Promise<LessonPlanRevisionSummary[]> {
  const params = new URLSearchParams({ school_id: scope.schoolId });
  const response = await fetch(`${lessonPlanPath(scope)}/revisions?${params}`, {
    headers: principalHeaders(scope),
  });
  if (!response.ok) {
    return responseProblem(response, "修订记录读取失败");
  }
  return ((await response.json()) as { revisions: LessonPlanRevisionSummary[] }).revisions;
}

export async function compareLessonPlanRevisions(
  scope: SearchScope,
  fromRevision: number,
  toRevision: number,
): Promise<Record<string, unknown>> {
  const params = new URLSearchParams({
    school_id: scope.schoolId,
    from_revision: String(fromRevision),
    to_revision: String(toRevision),
  });
  const response = await fetch(`${lessonPlanPath(scope)}/compare?${params}`, {
    headers: principalHeaders(scope),
  });
  if (!response.ok) {
    return responseProblem(response, "修订比较失败");
  }
  return (await response.json()) as Record<string, unknown>;
}

export async function restoreLessonPlanRevision(
  scope: SearchScope,
  revisionNumber: number,
  baseRevisionNumber: number,
): Promise<LessonPlan> {
  const response = await fetch(
    `${lessonPlanPath(scope)}/revisions/${revisionNumber}/restore`,
    {
      method: "POST",
      headers: mutationHeaders(scope),
      body: JSON.stringify({
        school_id: scope.schoolId,
        base_revision_number: baseRevisionNumber,
        change_summary: `恢复修订 ${revisionNumber}`,
      }),
    },
  );
  if (!response.ok) {
    return responseProblem(response, "修订恢复失败");
  }
  return ((await response.json()) as LessonPlanResponse).plan;
}

export async function confirmLessonPlan(
  scope: SearchScope,
  revisionNumber: number,
): Promise<LessonPlan> {
  const response = await fetch(`${lessonPlanPath(scope)}/confirm`, {
    method: "POST",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      revision_number: revisionNumber,
    }),
  });
  if (!response.ok) {
    return responseProblem(response, "教师确认失败");
  }
  return ((await response.json()) as LessonPlanResponse).plan;
}

export async function exportLessonPlan(scope: SearchScope): Promise<void> {
  const params = new URLSearchParams({ school_id: scope.schoolId });
  const response = await fetch(`${lessonPlanPath(scope)}/export?${params}`, {
    headers: principalHeaders(scope),
  });
  if (!response.ok) {
    return responseProblem(response, "教案导出失败");
  }
  const blob = new Blob([JSON.stringify(await response.json(), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${scope.workspaceId}-lesson-plan.json`;
  link.click();
  URL.revokeObjectURL(url);
}

export async function loadEvidenceRender(
  url: string,
  principalId: string,
): Promise<string> {
  if (!url.includes("/v1/workspaces/")) {
    return url;
  }
  const response = await fetch(url, {
    headers: { "X-Athena-Principal-Id": principalId },
  });
  if (!response.ok) {
    return responseProblem(response, "教材证据页读取失败");
  }
  return URL.createObjectURL(await response.blob());
}


export type StoryboardSlide = {
  slide_id: string;
  title: string;
  purpose: string;
  bullets: string[];
  evidence_ids: string[];
  session_id: string;
  topic_ids: string[];
  speaker_notes: string[];
  estimated_minutes: number;
  layout: "opening" | "concept" | "evidence" | "experiment" | "summary";
  visual_suggestion: string;
};

export type SlideStoryboardContent = {
  schema_version: "athena.slide-storyboard.v1";
  title: string;
  source_lesson_plan_id: string;
  source_lesson_revision: number;
  source_lesson_content_sha256: string;
  template_id: string;
  template_version: string;
  slides: StoryboardSlide[];
  summary: {
    slide_count: number;
    estimated_minutes: number;
    evidence_count: number;
  };
};

export type SlideStoryboard = {
  storyboard_id: string;
  workspace_id: string;
  lesson_plan_id: string;
  source_lesson_revision: number;
  status: "draft" | "teacher_confirmed";
  current_revision_number: number;
  confirmed_revision_number: number | null;
  source_current: boolean;
  export_ready: boolean;
  revision: {
    revision_number: number;
    source: "generated" | "teacher_edit" | "restored";
    change_summary: string;
    content: SlideStoryboardContent;
  };
};

type SlideStoryboardResponse = {
  storyboard: SlideStoryboard;
  reused: boolean;
};

function slideStoryboardPath(scope: SearchScope): string {
  return `${API_BASE}/v1/workspaces/${encodeURIComponent(scope.workspaceId)}/slide-storyboard`;
}

export async function generateSlideStoryboard(
  scope: SearchScope,
): Promise<SlideStoryboard> {
  const response = await fetch(`${slideStoryboardPath(scope)}/generate`, {
    method: "POST",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      template_id: "simple-classroom",
    }),
  });
  if (!response.ok) return responseProblem(response, "故事板生成失败");
  return ((await response.json()) as SlideStoryboardResponse).storyboard;
}

export async function getSlideStoryboard(
  scope: SearchScope,
): Promise<SlideStoryboard | null> {
  const params = new URLSearchParams({ school_id: scope.schoolId });
  const response = await fetch(`${slideStoryboardPath(scope)}?${params}`, {
    headers: principalHeaders(scope),
  });
  if (response.status === 404) return null;
  if (!response.ok) return responseProblem(response, "故事板读取失败");
  return ((await response.json()) as SlideStoryboardResponse).storyboard;
}

function canonicalStoryboardContent(
  content: SlideStoryboardContent,
): SlideStoryboardContent {
  return {
    ...content,
    summary: {
      slide_count: content.slides.length,
      estimated_minutes: content.slides.reduce(
        (total, slide) => total + slide.estimated_minutes,
        0,
      ),
      evidence_count: new Set(
        content.slides.flatMap((slide) => slide.evidence_ids),
      ).size,
    },
  };
}

export async function saveSlideStoryboard(
  scope: SearchScope,
  baseRevisionNumber: number,
  content: SlideStoryboardContent,
  changeSummary: string,
): Promise<SlideStoryboard> {
  const response = await fetch(slideStoryboardPath(scope), {
    method: "PUT",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      base_revision_number: baseRevisionNumber,
      change_summary: changeSummary,
      content: canonicalStoryboardContent(content),
    }),
  });
  if (!response.ok) return responseProblem(response, "故事板保存失败");
  return ((await response.json()) as SlideStoryboardResponse).storyboard;
}

export async function confirmSlideStoryboard(
  scope: SearchScope,
  revisionNumber: number,
): Promise<SlideStoryboard> {
  const response = await fetch(`${slideStoryboardPath(scope)}/confirm`, {
    method: "POST",
    headers: mutationHeaders(scope),
    body: JSON.stringify({
      school_id: scope.schoolId,
      revision_number: revisionNumber,
    }),
  });
  if (!response.ok) return responseProblem(response, "故事板确认失败");
  return ((await response.json()) as SlideStoryboardResponse).storyboard;
}

export async function exportSlideStoryboard(scope: SearchScope): Promise<void> {
  const params = new URLSearchParams({ school_id: scope.schoolId });
  const response = await fetch(`${slideStoryboardPath(scope)}/export?${params}`, {
    headers: principalHeaders(scope),
  });
  if (!response.ok) return responseProblem(response, "故事板导出失败");
  const blob = new Blob([JSON.stringify(await response.json(), null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${scope.workspaceId}-slide-storyboard.json`;
  link.click();
  URL.revokeObjectURL(url);
}
