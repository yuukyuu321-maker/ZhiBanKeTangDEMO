import { useEffect, useState } from "react";

import {
  confirmSlideStoryboard,
  exportSlideStoryboard,
  generateSlideStoryboard,
  getSlideStoryboard,
  saveSlideStoryboard,
  type SearchScope,
  type SlideStoryboard,
  type SlideStoryboardContent,
  type StoryboardSlide,
} from "./api";

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

const IS_TECHNICAL_QA = SCOPE.principalId === "codex-visual-qa";

const LAYOUT_LABEL = {
  opening: "问题导入",
  concept: "概念讲解",
  evidence: "教材证据",
  experiment: "实验流程",
  summary: "总结回扣",
} as const;

function StoryboardWorkspace() {
  const [storyboard, setStoryboard] = useState<SlideStoryboard | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [saveState, setSaveState] = useState("尚未生成故事板");
  const [notice, setNotice] = useState(
    "故事板只从当前教师已确认的教案生成，不会补写教案外内容。",
  );
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    getSlideStoryboard(SCOPE)
      .then((existing) => {
        if (disposed || existing === null) return;
        setStoryboard(existing);
        if (!existing.source_current) {
          setSaveState(
            `内容修订 ${existing.current_revision_number} · 源教案已变化，当前只读`,
          );
          setNotice(
            "源教案已变化；当前故事板只供查看。请回到教案工作区确认最新修订后重新生成。",
          );
        } else {
          setSaveState(
            existing.status === "teacher_confirmed"
              ? `内容修订 ${existing.current_revision_number} · 教师已确认`
              : `内容修订 ${existing.current_revision_number} · 已保存`,
          );
        }
      })
      .catch((error: unknown) => {
        if (!disposed) {
          setNotice(error instanceof Error ? error.message : "故事板读取失败。");
        }
      });
    return () => {
      disposed = true;
    };
  }, []);

  useEffect(() => {
    if (storyboard === null || saveState !== "有未保存修改") return undefined;
    const snapshot = storyboard;
    const timer = window.setTimeout(() => {
      setSaveState("正在自动保存……");
      saveSlideStoryboard(
        SCOPE,
        snapshot.current_revision_number,
        snapshot.revision.content,
        "自动保存：教师局部调整幻灯片故事板",
      )
        .then((saved) => {
          setStoryboard(saved);
          setSaveState(`内容修订 ${saved.current_revision_number} · 已自动保存`);
        })
        .catch((error: unknown) => {
          setSaveState(
            error instanceof Error ? `自动保存失败：${error.message}` : "自动保存失败。",
          );
        });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [storyboard, saveState]);

  async function handleGenerate() {
    setBusy("generate");
    try {
      const generated = await generateSlideStoryboard(SCOPE);
      setStoryboard(generated);
      setSelectedIndex(0);
      setSaveState(`内容修订 ${generated.current_revision_number} · 已保存`);
      setNotice(
        `已从教师确认的教案修订 ${generated.source_lesson_revision} 生成 ${generated.revision.content.slides.length} 页故事板。`,
      );
    } catch (error) {
      setNotice(
        error instanceof Error
          ? error.message
          : "故事板生成失败；请先回到教案工作区完成教师确认。",
      );
    } finally {
      setBusy(null);
    }
  }

  function updateContent(change: (content: SlideStoryboardContent) => void) {
    if (storyboard?.source_current === false) {
      setNotice(
        "源教案已变化；当前故事板只供查看。请回到教案工作区确认最新修订后重新生成。",
      );
      setSaveState(
        `内容修订 ${storyboard.current_revision_number} · 源教案已变化，当前只读`,
      );
      return;
    }
    setStoryboard((current) => {
      if (current === null) return current;
      const content = structuredClone(current.revision.content);
      change(content);
      const evidence = new Set(content.slides.flatMap((slide) => slide.evidence_ids));
      content.summary = {
        slide_count: content.slides.length,
        estimated_minutes: content.slides.reduce(
          (total, slide) => total + slide.estimated_minutes,
          0,
        ),
        evidence_count: evidence.size,
      };
      return {
        ...current,
        status: "draft",
        confirmed_revision_number: null,
        export_ready: false,
        revision: { ...current.revision, content },
      };
    });
    setSaveState("有未保存修改");
  }

  function updateSlide(change: (slide: StoryboardSlide) => void) {
    updateContent((content) => change(content.slides[selectedIndex]));
  }

  function moveSlide(direction: -1 | 1) {
    if (storyboard === null) return;
    if (!storyboard.source_current) {
      setNotice("源教案已变化，当前故事板只供查看，不能调整页面顺序。");
      return;
    }
    const target = selectedIndex + direction;
    if (target < 0 || target >= storyboard.revision.content.slides.length) return;
    updateContent((content) => {
      [content.slides[selectedIndex], content.slides[target]] = [
        content.slides[target],
        content.slides[selectedIndex],
      ];
    });
    setSelectedIndex(target);
  }

  function removeSlide() {
    if (storyboard?.source_current === false) {
      setNotice("源教案已变化，当前故事板只供查看，不能删除页面。");
      return;
    }
    if (storyboard === null || storyboard.revision.content.slides.length <= 1) {
      setNotice("至少保留一页故事板。当前未执行删除。");
      return;
    }
    updateContent((content) => content.slides.splice(selectedIndex, 1));
    setSelectedIndex((current) => Math.max(0, current - 1));
  }

  async function handleConfirm() {
    if (storyboard === null) return;
    if (IS_TECHNICAL_QA) {
      setNotice("当前为技术体验数据；请由真实教师在正式工作区完成最终确认。");
      return;
    }
    if (!storyboard.source_current) {
      setNotice("源教案已变化；请基于最新确认教案重新生成故事板。");
      return;
    }
    if (saveState.includes("未保存") || saveState.includes("正在")) {
      setNotice("请等待自动保存完成后再确认。");
      return;
    }
    setBusy("confirm");
    try {
      const confirmed = await confirmSlideStoryboard(
        SCOPE,
        storyboard.current_revision_number,
      );
      setStoryboard(confirmed);
      setSaveState(`内容修订 ${confirmed.current_revision_number} · 教师已确认`);
      setNotice("故事板确认已记录；这不代表学校发布批准，也不会自动发送给学生。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "故事板确认失败。");
    } finally {
      setBusy(null);
    }
  }

  async function handleExport() {
    setBusy("export");
    try {
      await exportSlideStoryboard(SCOPE);
      setNotice("已导出可审计的结构化故事板 JSON；正式 PPTX 仍处于渲染验证阶段。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "故事板导出失败。");
    } finally {
      setBusy(null);
    }
  }

  const content = storyboard?.revision.content ?? null;
  const slide = content?.slides[selectedIndex] ?? null;

  return (
    <main className="storyboard-shell">
      <header className="storyboard-topbar">
        <div>
          <p className="eyebrow">Increment 4 · 教师备课工作区</p>
          <h1>幻灯片故事板</h1>
        </div>
        <div className="storyboard-meta">
          <span>模板：简洁课堂</span>
          <span>设计版本：{content?.template_version ?? "尚未生成"}</span>
          {IS_TECHNICAL_QA ? <span className="technical">技术体验数据</span> : null}
          <span className={storyboard?.source_current === false ? "stale" : "current"}>
            {storyboard?.source_current === false ? "源教案已变化" : "源教案当前有效"}
          </span>
        </div>
      </header>

      <p className="storyboard-notice" role="status">{notice}</p>

      {storyboard === null || content === null || slide === null ? (
        <section className="storyboard-empty">
          <h2>从教师已确认教案开始</h2>
          <p>生成会继承教案顺序、时间、知识点和证据，不联网，也不会补写缺少的教材内容。</p>
          <button type="button" onClick={handleGenerate} disabled={busy !== null}>
            {busy === "generate" ? "正在生成……" : "生成幻灯片故事板"}
          </button>
        </section>
      ) : (
        <section className="storyboard-workspace">
          <aside className="slide-rail" aria-label="幻灯片顺序">
            <div className="rail-heading">
              <strong>{content.slides.length} 页</strong>
              <span>{content.summary.estimated_minutes} 分钟</span>
            </div>
            {content.slides.map((item, index) => (
              <button
                type="button"
                className={index === selectedIndex ? "slide-thumb selected" : "slide-thumb"}
                onClick={() => setSelectedIndex(index)}
                key={item.slide_id}
              >
                <span>{index + 1}</span>
                <div>
                  <strong>{item.title}</strong>
                  <small>{LAYOUT_LABEL[item.layout]} · {item.estimated_minutes} 分钟</small>
                </div>
              </button>
            ))}
          </aside>

          <section className="slide-stage-column">
            <div className={`slide-stage layout-${slide.layout}`}>
              <div className="slide-kicker">{LAYOUT_LABEL[slide.layout]} · {slide.session_id}</div>
              <h2>{slide.title}</h2>
              <p className="slide-purpose">{slide.purpose}</p>
              <ul>
                {slide.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}
              </ul>
              <div className="slide-visual-note">{slide.visual_suggestion}</div>
              <footer>
                <span>证据 {slide.evidence_ids.length} 条</span>
                <span>{selectedIndex + 1} / {content.slides.length}</span>
              </footer>
            </div>
            <div className="stage-controls">
              <button type="button" className="secondary" onClick={() => moveSlide(-1)} disabled={!storyboard.source_current || selectedIndex === 0}>上移</button>
              <button type="button" className="secondary" onClick={() => moveSlide(1)} disabled={!storyboard.source_current || selectedIndex === content.slides.length - 1}>下移</button>
              <button type="button" className="secondary danger" onClick={removeSlide} disabled={!storyboard.source_current}>删除本页</button>
            </div>
          </section>

          <aside className="slide-inspector">
            <p className="eyebrow">当前页内容</p>
            <label>
              标题
              <input disabled={!storyboard.source_current} value={slide.title} onChange={(event) => updateSlide((item) => { item.title = event.target.value; })} />
            </label>
            <label>
              用途
              <textarea disabled={!storyboard.source_current} value={slide.purpose} onChange={(event) => updateSlide((item) => { item.purpose = event.target.value; })} />
            </label>
            <label>
              要点（每行一项）
              <textarea disabled={!storyboard.source_current} value={slide.bullets.join("\n")} onChange={(event) => updateSlide((item) => { item.bullets = event.target.value.split("\n").filter((value) => value.trim()); })} />
            </label>
            <label>
              预计分钟
              <input disabled={!storyboard.source_current} type="number" min="1" value={slide.estimated_minutes} onChange={(event) => updateSlide((item) => { item.estimated_minutes = Math.max(1, Number(event.target.value)); })} />
            </label>
            <div className="evidence-chip-list">
              {slide.evidence_ids.map((evidenceId) => <code key={evidenceId}>{evidenceId}</code>)}
            </div>
            <p className="save-state">{saveState}</p>
            <div className="storyboard-actions">
              <button type="button" onClick={handleConfirm} disabled={busy !== null || !storyboard.source_current || IS_TECHNICAL_QA}>
                {IS_TECHNICAL_QA ? "技术体验不执行教师确认" : "教师确认"}
              </button>
              <button type="button" className="secondary" onClick={handleExport} disabled={busy !== null || !storyboard.export_ready}>导出 JSON</button>
            </div>
          </aside>
        </section>
      )}
    </main>
  );
}

export default StoryboardWorkspace;
