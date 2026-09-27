import { useEffect, useMemo, useState, type ChangeEvent } from "react";

import { api } from "./api";
import type { CounterpartyImportBatch, CounterpartyImportMappingTemplate } from "./types";


type Notice = { kind: "error" | "success"; text: string };
type Props = { onCommitted: () => Promise<void>; onNotice: (notice: Notice) => void };

const statusLabels: Record<CounterpartyImportBatch["status"], string> = {
  prechecked: "预检通过",
  blocked: "预检阻断",
  committed: "已提交",
};

const actionLabels: Record<string, string> = {
  create: "新增",
  update: "覆盖更新",
  skip: "保留现有",
  reject: "拒绝",
};

function nextImportKey() {
  return `CP-IMPORT-${new Date().toISOString().replace(/[-:TZ.]/g, "").slice(0, 14)}`;
}

function parseMapping(text: string): Record<string, string> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("字段映射必须是 JSON 对象");
  return Object.fromEntries(Object.entries(parsed).map(([key, value]) => [key, String(value)]));
}

export default function CounterpartyImportPanel({ onCommitted, onNotice }: Props) {
  const [history, setHistory] = useState<CounterpartyImportBatch[]>([]);
  const [historyStatus, setHistoryStatus] = useState<"all" | CounterpartyImportBatch["status"]>("all");
  const [batch, setBatch] = useState<CounterpartyImportBatch | null>(null);
  const [templates, setTemplates] = useState<CounterpartyImportMappingTemplate[]>([]);
  const [templateId, setTemplateId] = useState("");
  const [templateKey, setTemplateKey] = useState("ERP-SUPPLIER-V1");
  const [templateName, setTemplateName] = useState("ERP 供应商字段映射");
  const [templateDescription, setTemplateDescription] = useState("用于已核验的 ERP 客商主数据迁移");
  const [templateReason, setTemplateReason] = useState("建立可复用的客商迁移字段映射");
  const [importKey, setImportKey] = useState(nextImportKey);
  const [fileName, setFileName] = useState("counterparties.json");
  const [fileFormat, setFileFormat] = useState<"json" | "csv">("json");
  const [content, setContent] = useState("");
  const [duplicateStrategy, setDuplicateStrategy] = useState<"reject" | "skip" | "update">("reject");
  const [mappingText, setMappingText] = useState("{}");
  const [precheckReason, setPrecheckReason] = useState("客户首批客商主数据迁移预检");
  const [commitReason, setCommitReason] = useState("确认逐行预检结果并提交客商迁移批次");
  const [busy, setBusy] = useState<"load" | "precheck" | "commit" | "draft" | "receipt" | "template" | null>(null);
  const problemRows = useMemo(() => batch?.row_receipts.filter((item) => item.errors.length || item.warnings.length) ?? [], [batch]);

  useEffect(() => { void loadHistory(); }, [historyStatus]);

  useEffect(() => {
    void api.counterpartyImportMappingTemplates().then(setTemplates).catch((error: Error) => {
      onNotice({ kind: "error", text: error.message });
    });
  }, []);

  async function loadHistory(selectId?: string) {
    setBusy((current) => current ?? "load");
    try {
      const result = await api.counterpartyImports(historyStatus === "all" ? undefined : historyStatus);
      setHistory(result.items);
      if (selectId) setBatch((current) => result.items.find((item) => item.id === selectId) ?? current);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "导入批次加载失败" });
    } finally {
      setBusy((current) => current === "load" ? null : current);
    }
  }

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      onNotice({ kind: "error", text: "导入文件不能超过 2MB" });
      event.target.value = "";
      return;
    }
    const format = file.name.toLowerCase().endsWith(".csv") ? "csv" : file.name.toLowerCase().endsWith(".json") ? "json" : null;
    if (!format) {
      onNotice({ kind: "error", text: "只支持 UTF-8 JSON 或 CSV 文件" });
      event.target.value = "";
      return;
    }
    setFileName(file.name);
    setFileFormat(format);
    setContent(await file.text());
    setBatch(null);
    setImportKey(nextImportKey());
  }

  async function precheck() {
    let mapping: Record<string, string>;
    try {
      mapping = parseMapping(mappingText);
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段映射格式不正确" });
      return;
    }
    setBusy("precheck");
    try {
      const result = await api.precheckCounterpartyImport({
        import_key: importKey, file_name: fileName, file_format: fileFormat, content,
        duplicate_strategy: duplicateStrategy, field_mapping: mapping, reason: precheckReason,
      });
      setBatch(result);
      await loadHistory(result.id);
      onNotice({
        kind: result.status === "blocked" ? "error" : "success",
        text: result.status === "blocked"
          ? `预检已阻断：${result.invalid_count} 行错误，未写入任何客商`
          : `预检通过：新增 ${result.create_count}、更新 ${result.update_count}、跳过 ${result.skip_count}`,
      });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商导入预检失败" });
    } finally { setBusy(null); }
  }

  async function commit() {
    if (!batch) return;
    setBusy("commit");
    try {
      const result = await api.commitCounterpartyImport(batch.id, {
        expected_row_version: batch.row_version, preview_hash: batch.preview_hash, reason: commitReason,
      });
      setBatch(result);
      await Promise.all([loadHistory(result.id), onCommitted()]);
      onNotice({ kind: "success", text: `${result.import_key} 已原子提交，共写入 ${result.committed_count} 户客商` });
      setImportKey(nextImportKey());
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "客商导入提交失败" });
    } finally { setBusy(null); }
  }

  function selectTemplate(id: string) {
    setTemplateId(id);
    const template = templates.find((item) => item.id === id);
    if (!template) return;
    setTemplateKey(template.template_key);
    setTemplateName(template.name);
    setTemplateDescription(template.description);
    setMappingText(JSON.stringify(template.mapping, null, 2));
    setFileFormat(template.file_format);
    setBatch(null);
    onNotice({ kind: "success", text: `${template.name} 已应用到当前导入草稿` });
  }

  function newTemplate() {
    setTemplateId("");
    setTemplateKey(`MAPPING-${new Date().toISOString().slice(0, 10).replaceAll("-", "")}`);
    setTemplateName("新字段映射模板");
    setTemplateDescription("用于已核验来源系统的客商主数据迁移");
  }

  async function saveTemplate() {
    let mapping: Record<string, string>;
    try { mapping = parseMapping(mappingText); }
    catch (error) { onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段映射格式不正确" }); return; }
    setBusy("template");
    try {
      const current = templates.find((item) => item.id === templateId);
      const saved = current
        ? await api.updateCounterpartyImportMappingTemplate(current.id, {
          name: templateName, file_format: fileFormat, mapping, description: templateDescription,
          expected_row_version: current.row_version, reason: templateReason,
        })
        : await api.createCounterpartyImportMappingTemplate({
          template_key: templateKey, name: templateName, file_format: fileFormat, mapping,
          description: templateDescription, reason: templateReason,
        });
      const next = await api.counterpartyImportMappingTemplates();
      setTemplates(next); setTemplateId(saved.id);
      onNotice({ kind: "success", text: `${saved.name} 已保存为 v${saved.row_version} 可复用模板` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段映射模板保存失败" });
    } finally { setBusy(null); }
  }

  async function archiveTemplate() {
    const current = templates.find((item) => item.id === templateId);
    if (!current) return;
    setBusy("template");
    try {
      await api.archiveCounterpartyImportMappingTemplate(current.id, {
        expected_row_version: current.row_version, reason: templateReason,
      });
      setTemplates(await api.counterpartyImportMappingTemplates());
      newTemplate();
      onNotice({ kind: "success", text: `${current.name} 已归档，不再出现在活动模板中` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "字段映射模板归档失败" });
    } finally { setBusy(null); }
  }

  async function copyCorrectionDraft() {
    if (!batch) return;
    setBusy("draft");
    try {
      const draft = await api.counterpartyImportCorrectionDraft(batch.id);
      setImportKey(draft.suggested_import_key); setFileName(draft.file_name); setFileFormat(draft.file_format);
      setContent(draft.content); setDuplicateStrategy(draft.duplicate_strategy);
      setMappingText(JSON.stringify(draft.field_mapping, null, 2)); setBatch(null);
      document.getElementById("counterparty-import-builder")?.scrollIntoView({ behavior: "smooth", block: "start" });
      onNotice({ kind: "success", text: `${draft.source_import_key} 已复制为新草稿，请修正后使用新批次编号重新预检` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "修正草稿加载失败" });
    } finally { setBusy(null); }
  }

  async function downloadReceipt() {
    if (!batch) return;
    setBusy("receipt");
    try {
      await api.downloadCounterpartyImportReceipt(batch.id, batch.import_key);
      onNotice({ kind: "success", text: `${batch.import_key} 行级回执已下载` });
    } catch (error) {
      onNotice({ kind: "error", text: error instanceof Error ? error.message : "导入回执下载失败" });
    } finally { setBusy(null); }
  }

  return <section className="panel counterparty-import-panel">
    <header className="counterparty-import-head">
      <div><span>MASTER DATA ONBOARDING</span><h2>客商主数据批量导入</h2><p>先冻结文件、映射和逐行预检结果，再显式提交；有错误时整批不落库。</p></div>
      <details className="function-note"><summary>功能说明</summary><p><b>拒绝重复</b>适合首次迁移，发现存量即阻断；<b>跳过存量</b>只新增不存在的主体；<b>覆盖更新</b>按客商编号更新完整主数据。提交前若存量发生变化，整批回滚并要求重新预检。</p></details>
    </header>
    <div className="counterparty-import-layout">
      <div className="counterparty-import-builder" id="counterparty-import-builder">
        <div className="counterparty-import-fields">
          <label><span>选择 UTF-8 文件</span><input type="file" accept=".json,.csv,application/json,text/csv" onChange={(event) => void chooseFile(event)} /></label>
          <label><span>批次编号</span><input value={importKey} onChange={(event) => { setImportKey(event.target.value); setBatch(null); }} /></label>
          <label><span>文件格式</span><select value={fileFormat} onChange={(event) => setFileFormat(event.target.value as "json" | "csv")}><option value="json">JSON</option><option value="csv">CSV</option></select></label>
          <label><span>重复策略</span><select value={duplicateStrategy} onChange={(event) => { setDuplicateStrategy(event.target.value as typeof duplicateStrategy); setBatch(null); }}><option value="reject">拒绝重复</option><option value="skip">跳过存量</option><option value="update">覆盖更新</option></select></label>
        </div>
        <section className="counterparty-mapping-workbench">
          <header><div><strong>字段映射模板</strong><p>将来源系统列名转换为平台标准字段，避免每批重复录入；模板变更保留版本与审计证据。</p></div><button className="secondary" onClick={newTemplate}>＋ 新模板</button></header>
          <div className="counterparty-mapping-selector"><label><span>应用已有模板</span><select aria-label="字段映射模板" value={templateId} onChange={(event) => selectTemplate(event.target.value)}><option value="">不使用已有模板</option>{templates.map((item) => <option key={item.id} value={item.id}>{item.name} · v{item.row_version}</option>)}</select></label>{templateId && <code title={templates.find((item) => item.id === templateId)?.mapping_hash}>{templates.find((item) => item.id === templateId)?.mapping_hash.slice(0, 12)}</code>}</div>
          <div className="counterparty-mapping-fields">
            <label><span>模板编号</span><input value={templateKey} disabled={Boolean(templateId)} onChange={(event) => setTemplateKey(event.target.value)} /></label>
            <label><span>模板名称</span><input value={templateName} onChange={(event) => setTemplateName(event.target.value)} /></label>
            <label className="wide"><span>适用说明</span><input value={templateDescription} onChange={(event) => setTemplateDescription(event.target.value)} /></label>
            <label className="wide"><span>模板维护原因</span><input value={templateReason} onChange={(event) => setTemplateReason(event.target.value)} /></label>
          </div>
          <footer><small>保存时会校验目标字段、重复映射和当前模板版本。</small><div>{templateId && <button className="danger-outline" disabled={busy !== null || templateReason.trim().length < 5} onClick={() => void archiveTemplate()}>归档模板</button>}<button className="secondary" disabled={busy !== null || templateKey.trim().length < 3 || templateName.trim().length < 2 || templateDescription.trim().length < 5 || templateReason.trim().length < 5} onClick={() => void saveTemplate()}>{busy === "template" ? "保存中…" : templateId ? "校验版本并更新" : "保存新模板"}</button></div></footer>
        </section>
        <label className="counterparty-import-content"><span>文件内容预览</span><textarea value={content} onChange={(event) => { setContent(event.target.value); setBatch(null); }} placeholder={'JSON 示例：[ { "id": "cp_001", "credit_code": "...", "name": "...", "counterparty_type": "supplier" } ]'} /></label>
        <div className="counterparty-import-config">
          <label><span>字段映射 JSON</span><textarea value={mappingText} onChange={(event) => { setMappingText(event.target.value); setBatch(null); }} placeholder={'{"供应商编码":"counterparty_id","企业名称":"name"}'} /></label>
          <label><span>预检业务原因</span><textarea value={precheckReason} onChange={(event) => setPrecheckReason(event.target.value)} /></label>
        </div>
        <button className="primary-button" disabled={busy !== null || content.trim().length < 2 || importKey.trim().length < 4 || precheckReason.trim().length < 5} onClick={() => void precheck()}>{busy === "precheck" ? "逐行预检中…" : "执行预检并冻结证据"}</button>
      </div>
      <aside className="counterparty-import-history">
        <div className="counterparty-import-history-filter"><label><span>批次状态</span><select value={historyStatus} onChange={(event) => { setHistoryStatus(event.target.value as typeof historyStatus); setBatch(null); }}><option value="all">全部状态</option><option value="blocked">预检阻断</option><option value="prechecked">预检通过</option><option value="committed">已提交</option></select></label><label className="batch"><span>最近导入批次</span><select value={batch?.id ?? ""} onChange={(event) => setBatch(history.find((item) => item.id === event.target.value) ?? null)}><option value="">选择批次查看证据</option>{history.map((item) => <option key={item.id} value={item.id}>{item.import_key} · {statusLabels[item.status]}</option>)}</select></label></div>
        {batch ? <>
          <div className={`counterparty-import-status ${batch.status}`}><strong>{statusLabels[batch.status]}</strong><code>{batch.preview_hash.slice(0, 12)}</code><small>{batch.file_name} · v{batch.row_version}</small></div>
          <div className="counterparty-import-metrics"><div><span>总行数</span><b>{batch.total_count}</b></div><div><span>新增</span><b>{batch.create_count}</b></div><div><span>更新</span><b>{batch.update_count}</b></div><div><span>跳过</span><b>{batch.skip_count}</b></div><div className={batch.invalid_count ? "danger" : ""}><span>错误</span><b>{batch.invalid_count}</b></div></div>
          <div className="counterparty-import-hashes"><span>原文 SHA-256</span><code>{batch.source_hash}</code><span>预检证据</span><code>{batch.preview_hash}</code></div>
          <div className="counterparty-import-evidence-actions"><button disabled={busy !== null} onClick={() => void downloadReceipt()}>{busy === "receipt" ? "生成回执中…" : "下载行级 CSV 回执"}</button>{batch.status === "blocked" && <button className="warning" disabled={busy !== null} onClick={() => void copyCorrectionDraft()}>{busy === "draft" ? "复制中…" : "复制为修正草稿"}</button>}</div>
          {problemRows.length > 0 && <div className="counterparty-import-receipts"><strong>异常与提示（{problemRows.length} 行）</strong>{problemRows.map((item) => <article className={item.errors.length ? "error" : "warning"} key={item.row_number}><header><span>第 {item.row_number} 行</span><b>{actionLabels[item.action]}</b><code>{item.counterparty_id ?? "未识别主体"}</code></header>{item.errors.map((error) => <p key={`${error.field}-${error.code}`}>{error.field}：{error.message}</p>)}{item.warnings.map((warning) => <p key={warning.code}>{warning.message}</p>)}</article>)}</div>}
          {batch.status === "prechecked" && <div className="counterparty-import-commit"><label><span>提交业务原因</span><textarea value={commitReason} onChange={(event) => setCommitReason(event.target.value)} /></label><button className="primary-button" disabled={busy !== null || commitReason.trim().length < 5} onClick={() => void commit()}>{busy === "commit" ? "原子提交中…" : "确认哈希并提交整批"}</button><small>提交将再次核验原文、预检证据及存量客商版本。</small></div>}
        </> : <div className="counterparty-import-empty"><strong>尚未选择预检批次</strong><p>上传文件并执行预检后，逐行错误和提交门禁会显示在这里。</p></div>}
      </aside>
    </div>
  </section>;
}
