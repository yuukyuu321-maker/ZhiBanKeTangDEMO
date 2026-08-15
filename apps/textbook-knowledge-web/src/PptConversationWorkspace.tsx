import { useRef, useState, type FormEvent } from "react";

type ConversationMessage = {
  id: number;
  role: "teacher" | "assistant";
  content: string;
};

const INITIAL_MESSAGES: ConversationMessage[] = [
  {
    id: 1,
    role: "assistant",
    content:
      "把课题、课时、必讲要求和实验安排发给我。也可以直接附上图片、学校模板或已有 PPT；我会生成标准 PPTX，您仍在 PowerPoint 或 WPS 中完成最后调整。",
  },
];

function PptConversationWorkspace() {
  const [messages, setMessages] = useState(INITIAL_MESSAGES);
  const [instruction, setInstruction] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [notice, setNotice] = useState(
    "界面已转向“对话 + PPT 文件”；PPTX 文档引擎仍待接入，当前不会假装生成文件。",
  );
  const fileInput = useRef<HTMLInputElement>(null);

  function handleFiles(files: FileList | null) {
    if (files === null) return;
    setAttachments((current) => [...current, ...Array.from(files)]);
  }

  function removeAttachment(index: number) {
    setAttachments((current) => current.filter((_, itemIndex) => itemIndex !== index));
  }

  function submitInstruction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = instruction.trim();
    if (text.length === 0 && attachments.length === 0) return;

    const attachmentSummary = attachments.length > 0
      ? `\n附件：${attachments.map((file) => file.name).join("、")}`
      : "";
    setMessages((current) => [
      ...current,
      { id: Date.now(), role: "teacher", content: `${text}${attachmentSummary}`.trim() },
      {
        id: Date.now() + 1,
        role: "assistant",
        content:
          "要求已保留在本地界面，但当前分支尚未接入 PPTX 文档引擎，因此没有创建或修改文件。接入完成后，同一条指令将直接形成新的 PPTX 修订。",
      },
    ]);
    setInstruction("");
    setAttachments([]);
    setNotice("没有生成 PPTX；OfficeCLI 概念验证与文件修订服务尚待实现。");
  }

  return (
    <main className="ppt-conversation-shell">
      <header className="ppt-conversation-header">
        <div>
          <p className="eyebrow">教师备课 · PPT</p>
          <h1>和 AI 一起做 PPT</h1>
          <p>说出要求，拿到可编辑 PPTX；最后仍用您熟悉的 PowerPoint 或 WPS。</p>
        </div>
        <span className="engine-status">PPTX 引擎待接入</span>
      </header>

      <p className="ppt-transition-notice" role="status">{notice}</p>

      <section className="ppt-conversation-card">
        <div className="ppt-chat-log" aria-live="polite">
          {messages.map((message) => (
            <article className={`ppt-chat-message ${message.role}`} key={message.id}>
              <strong>{message.role === "teacher" ? "您" : "AI"}</strong>
              <p>{message.content}</p>
            </article>
          ))}
        </div>

        <aside className="ppt-file-card" aria-label="当前 PPT 文件">
          <div className="ppt-file-icon">PPT</div>
          <div>
            <p className="eyebrow">当前文件</p>
            <h2>尚未生成 PPTX</h2>
            <p>接入文档引擎后，这里只显示文件、缩略预览、版本和“下载／打开 PPT”。</p>
          </div>
          <button type="button" disabled>下载／打开 PPT</button>
        </aside>

        <form className="ppt-composer" onSubmit={submitInstruction}>
          {attachments.length > 0 ? (
            <div className="ppt-attachment-list" aria-label="待发送附件">
              {attachments.map((file, index) => (
                <span key={`${file.name}-${file.lastModified}-${index}`}>
                  {file.name}
                  <button type="button" onClick={() => removeAttachment(index)} aria-label={`移除 ${file.name}`}>×</button>
                </span>
              ))}
            </div>
          ) : null}
          <textarea
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            placeholder="例如：补充高锰酸钾法、向上排空气法和错误装置图；删掉第 8 个必讲要求……"
            aria-label="PPT 生成或修改要求"
          />
          <div className="ppt-composer-actions">
            <input
              ref={fileInput}
              type="file"
              multiple
              accept="image/png,image/jpeg,image/gif,image/svg+xml,.ppt,.pptx"
              onChange={(event) => handleFiles(event.target.files)}
              hidden
            />
            <button type="button" className="secondary" onClick={() => fileInput.current?.click()}>
              ＋ 图片／模板／已有 PPT
            </button>
            <button type="submit">发送要求</button>
          </div>
        </form>
      </section>

      <details className="ppt-boundary-details">
        <summary>教材依据与教师补充如何处理</summary>
        <p>
          教材内容继续固定到具体版本和页码；您上传或明确补充的内容标为“教师补充”，可以进入草稿，但不会冒充教材原文。故事板、证据编号和 JSON 只在后台用于生成、校验和追溯。
        </p>
      </details>
    </main>
  );
}

export default PptConversationWorkspace;
