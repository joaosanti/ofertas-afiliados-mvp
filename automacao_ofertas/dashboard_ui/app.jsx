const { useEffect, useMemo, useState } = React;

const IMPORT_OPTIONS = [
  { key: "mercadolivre", label: "Mercado Livre", note: "API/OAuth pronta para importar agora." },
  { key: "shopee", label: "Shopee", note: "Estrutura pronta; depende de credenciais/liberacao." },
  { key: "amazon", label: "Amazon", note: "Conector futuro para feed/API." },
  { key: "tiktok", label: "TikTok", note: "Conector futuro para catalogo social." },
];

const SOCIAL_OPTIONS = [
  { key: "facebook:feed", label: "Facebook Feed", note: "Posta direto na pagina do projeto." },
  { key: "both:feed", label: "Facebook + Instagram Feed", note: "Publica a mesma oferta nos dois canais." },
  { key: "instagram:feed", label: "Instagram Feed", note: "Publica no feed do Instagram via Graph API." },
  { key: "instagram:story", label: "Instagram Story", note: "Usa a arte gerada automaticamente." },
];

function fmtMoney(value) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtInt(value) {
  return Number(value || 0).toLocaleString("pt-BR");
}

function fmtDate(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString("pt-BR");
  } catch {
    return value;
  }
}

function fmtCountdown(value, nowTs) {
  if (!value) return "desligado";
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return "-";
  const diff = target - nowTs;
  if (diff <= 0) return "agora";
  const totalMinutes = Math.floor(diff / 60000);
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  const parts = [];
  if (days) parts.push(`${days}d`);
  if (hours || days) parts.push(`${hours}h`);
  parts.push(`${minutes}min`);
  return parts.join(" ");
}

function fmtJobStatus(value) {
  if (!value) return "aguardando";
  if (value === "success") return "sucesso";
  if (value === "error") return "erro";
  return value;
}

function summarizeJobResult(jobKey, result) {
  if (!result) return "Nenhuma execucao concluida ainda.";
  if (result.error) return `Erro: ${result.error}`;
  if (jobKey === "import") {
    if (Array.isArray(result.items)) {
      const processed = result.items.reduce((sum, item) => sum + Number(item.processed || item.imported || 0), 0);
      const created = result.items.reduce((sum, item) => sum + Number(item.created || 0), 0);
      const updated = result.items.reduce((sum, item) => sum + Number(item.updated || 0), 0);
      const errors = Number(result.error || 0);
      return `${processed} processado(s): ${created} criado(s), ${updated} atualizado(s), ${errors} com erro.`;
    }
    const processed = Number(result.processed || result.imported || 0);
    const created = Number(result.created || 0);
    const updated = Number(result.updated || 0);
    return `${processed} processado(s): ${created} criado(s), ${updated} atualizado(s).`;
  }
  if (jobKey === "social") {
    const count = Number(result.count || 0);
    const errors = Array.isArray(result.errors) ? result.errors.length : Number(result.error || 0);
    return `${count} publicacao(oes), ${errors} erro(s).`;
  }
  return JSON.stringify(result);
}

function statusClass(enabled, mode) {
  if (enabled) return "is-success";
  if ((mode || "").toLowerCase().includes("futuro")) return "is-neutral";
  return "is-warning";
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const text = await response.text();
  let data = {};
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = data.detail || data.error || text || "Falha ao processar requisicao.";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return data;
}

function MiniBarChart({ title, subtitle, items, color = "#2b66ff" }) {
  const max = Math.max(...(items || []).map((item) => Number(item.value || 0)), 1);
  return (
    <div className="chart-box">
      <div className="panel-head" style={{ marginBottom: 12 }}>
        <div>
          <h4 className="panel-title">{title}</h4>
          <p className="panel-subtitle">{subtitle}</p>
        </div>
      </div>
      {!items?.length ? (
        <div className="empty-state">Sem dados suficientes ainda.</div>
      ) : (
        <div className="list">
          {items.map((item) => {
            const width = `${Math.max(8, (Number(item.value || 0) / max) * 100)}%`;
            return (
              <div key={item.label} style={{ display: "grid", gap: 6 }}>
                <div className="inline-stat" style={{ justifyContent: "space-between" }}>
                  <strong>{item.label}</strong>
                  <span>{fmtInt(item.value)}</span>
                </div>
                <div style={{ height: 10, borderRadius: 999, background: "rgba(16,33,58,0.08)", overflow: "hidden" }}>
                  <div style={{ width, height: "100%", borderRadius: 999, background: color }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MultiLineChart({ title, subtitle, rows }) {
  const width = 760;
  const height = 260;
  const padding = 26;
  const values = rows.flatMap((row) => [row.import || 0, row.social || 0, row.processed || 0]);
  const max = Math.max(...values, 1);

  function buildPath(field) {
    return rows
      .map((row, index) => {
        const x = padding + (index * (width - padding * 2)) / Math.max(rows.length - 1, 1);
        const y = height - padding - ((Number(row[field] || 0) / max) * (height - padding * 2));
        return `${index === 0 ? "M" : "L"} ${x} ${y}`;
      })
      .join(" ");
  }

  return (
    <div className="chart-box">
      <div className="panel-head">
        <div>
          <h4 className="panel-title">{title}</h4>
          <p className="panel-subtitle">{subtitle}</p>
        </div>
        <div className="legend">
          <span style={{ color: "#2b66ff" }}>Importacoes</span>
          <span style={{ color: "#167b53" }}>Social</span>
          <span style={{ color: "#b66a00" }}>Itens processados</span>
        </div>
      </div>
      {!rows?.length ? (
        <div className="empty-state">Ainda nao ha execucoes suficientes para o grafico.</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", minWidth: 620 }}>
            {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
              const y = height - padding - ratio * (height - padding * 2);
              return (
                <g key={ratio}>
                  <line x1={padding} y1={y} x2={width - padding} y2={y} stroke="rgba(16,33,58,0.08)" strokeWidth="1" />
                  <text x="2" y={y + 4} fill="#617089" fontSize="11">
                    {fmtInt(Math.round(max * ratio))}
                  </text>
                </g>
              );
            })}
            <path d={buildPath("import")} fill="none" stroke="#2b66ff" strokeWidth="4" strokeLinecap="round" />
            <path d={buildPath("social")} fill="none" stroke="#167b53" strokeWidth="4" strokeLinecap="round" />
            <path d={buildPath("processed")} fill="none" stroke="#b66a00" strokeWidth="4" strokeLinecap="round" />
            {rows.map((row, index) => {
              const x = padding + (index * (width - padding * 2)) / Math.max(rows.length - 1, 1);
              return (
                <text key={row.label} x={x} y={height - 4} textAnchor="middle" fill="#617089" fontSize="11">
                  {row.label.slice(5)}
                </text>
              );
            })}
          </svg>
        </div>
      )}
    </div>
  );
}

function Toast({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(onClose, 5000);
    return () => window.clearTimeout(timer);
  }, [toast, onClose]);

  if (!toast) return null;
  return <div className={`toast ${toast.type === "error" ? "is-error" : toast.type === "info" ? "is-info" : "is-success"}`}>{toast.message}</div>;
}

function balanceSocialItems(items, activeStoreFilter) {
  if (activeStoreFilter !== "all") return items;
  const groups = new Map();
  const order = [];
  items.forEach((item) => {
    const key = item.store || "Loja";
    if (!groups.has(key)) {
      groups.set(key, []);
      order.push(key);
    }
    groups.get(key).push(item);
  });
  const mixed = [];
  let hasItems = true;
  while (hasItems) {
    hasItems = false;
    order.forEach((key) => {
      const bucket = groups.get(key) || [];
      if (bucket.length) {
        mixed.push(bucket.shift());
        hasItems = true;
      }
    });
  }
  return mixed;
}

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [manualLinkPreview, setManualLinkPreview] = useState(null);
  const [manualLinkStatus, setManualLinkStatus] = useState(null);
  const [socialPreview, setSocialPreview] = useState(null);
  const [socialHiddenIds, setSocialHiddenIds] = useState([]);
  const [socialCheckedIds, setSocialCheckedIds] = useState([]);
  const [importLoading, setImportLoading] = useState(false);
  const [manualLinkLoading, setManualLinkLoading] = useState(false);
  const [socialLoading, setSocialLoading] = useState(false);
  const [runLoading, setRunLoading] = useState({ import: false, manualLinks: false, social: false, batch: false, deployStories: false, deploySite: false });
  const [jobRunLoading, setJobRunLoading] = useState({ import: false, social: false, story: false });
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [nowTs, setNowTs] = useState(Date.now());
  const [importForm, setImportForm] = useState({
    providers: ["mercadolivre"],
    previewProvider: "mercadolivre",
    keyword: "fone bluetooth",
    limit: 12,
    pages: 1,
  });
  const [manualLinkText, setManualLinkText] = useState("");
  const [manualLinkRetry, setManualLinkRetry] = useState(null);
  const [fileImportProvider, setFileImportProvider] = useState("shopee");
  const [fileImportFile, setFileImportFile] = useState(null);
  const [fileImportPreview, setFileImportPreview] = useState(null);
  const [fileImportLoading, setFileImportLoading] = useState(false);
  const [socialForm, setSocialForm] = useState({ selected: "facebook:feed", limit: 3 });
  const [socialFilters, setSocialFilters] = useState({ store: "all", category: "all" });
  const [settingsForm, setSettingsForm] = useState({
    manager_username: "admin",
    manager_password: "",
    meta_access_token: "",
    auto_import_enabled: true,
    auto_import_times: "06:30,12:30,18:30",
    auto_import_providers: ["mercadolivre"],
    auto_social_enabled: true,
    auto_social_times: "07:00,13:00,19:00",
    auto_social_platform: "facebook",
    auto_social_mode: "feed",
    auto_social_limit: 3,
    auto_story_enabled: false,
    auto_story_times: "07:05,13:05,19:05",
    auto_story_platform: "instagram",
    auto_story_limit: 1,
    sftp_host: "",
    sftp_port: 22,
    sftp_username: "",
    sftp_password: "",
    sftp_remote_path: "",
    stories_public_base_url: "",
  });

  const socialSplit = useMemo(() => {
    const [platform, mode] = socialForm.selected.split(":");
    return { platform, mode };
  }, [socialForm.selected]);

  const socialCandidates = useMemo(() => socialPreview?.items || [], [socialPreview]);
  const socialStoreOptions = useMemo(() => {
    const values = [...new Set(socialCandidates.map((item) => item.store).filter(Boolean))];
    return values.sort((a, b) => a.localeCompare(b, "pt-BR"));
  }, [socialCandidates]);
  const socialCategoryOptions = useMemo(() => {
    const values = [...new Set(socialCandidates.map((item) => item.category).filter(Boolean))];
    return values.sort((a, b) => a.localeCompare(b, "pt-BR"));
  }, [socialCandidates]);
  const filteredSocialCandidates = useMemo(
    () => socialCandidates.filter((item) => {
      const matchStore = socialFilters.store === "all" || item.store === socialFilters.store;
      const matchCategory = socialFilters.category === "all" || item.category === socialFilters.category;
      return matchStore && matchCategory;
    }),
    [socialCandidates, socialFilters]
  );
  const balancedSocialCandidates = useMemo(
    () => balanceSocialItems(filteredSocialCandidates, socialFilters.store),
    [filteredSocialCandidates, socialFilters.store]
  );
  const socialQueue = useMemo(
    () => balancedSocialCandidates.filter((item) => !socialHiddenIds.includes(item.offer_id)),
    [balancedSocialCandidates, socialHiddenIds]
  );

  async function loadSnapshot() {
    setLoading(true);
    try {
      setSnapshot(await fetchJson("/dashboard/api/overview"));
    } catch (error) {
      setToast({ type: "error", message: `Falha ao carregar dashboard: ${error.message}` });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const settings = snapshot?.settings;
    if (!settings) return;
    setSettingsForm((current) => ({
      ...current,
      manager_username: settings.manager_username || "admin",
      manager_password: "",
      meta_access_token: "",
      auto_import_enabled: Boolean(settings.auto_import_enabled),
      auto_import_times: settings.auto_import_times || "",
      auto_import_providers: settings.auto_import_providers || ["mercadolivre"],
      auto_social_enabled: Boolean(settings.auto_social_enabled),
      auto_social_times: settings.auto_social_times || "",
      auto_social_platform: settings.auto_social_platform || "facebook",
      auto_social_mode: settings.auto_social_mode || "feed",
      auto_social_limit: Number(settings.auto_social_limit || 3),
      auto_story_enabled: Boolean(settings.auto_story_enabled),
      auto_story_times: settings.auto_story_times || "",
      auto_story_platform: settings.auto_story_platform || "instagram",
      auto_story_limit: Number(settings.auto_story_limit || 1),
      sftp_host: settings.sftp?.host || "",
      sftp_port: Number(settings.sftp?.port || 22),
      sftp_username: settings.sftp?.username || "",
      sftp_password: "",
      sftp_remote_path: settings.sftp?.remote_path || "",
      stories_public_base_url: settings.sftp?.stories_public_base_url || "",
    }));
  }, [snapshot?.settings]);

  async function loadSocialPreview(limit = socialForm.limit) {
    setSocialLoading(true);
    try {
      setSocialPreview(await fetchJson(`/social/meta/post-previews?limit=${Math.max(24, Number(limit || 5), 36)}`));
    } catch (error) {
      setToast({ type: "error", message: `Falha ao montar previews sociais: ${error.message}` });
    } finally {
      setSocialLoading(false);
    }
  }

  useEffect(() => {
    loadSnapshot();
    loadSocialPreview();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNowTs(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!manualLinkRetry?.active) return undefined;
    const timer = window.setTimeout(() => {
      setManualLinkRetry((current) => {
        if (!current?.active) return current;
        if (current.secondsLeft <= 1) {
          return { ...current, active: false, secondsLeft: 0, ready: true };
        }
        return { ...current, secondsLeft: current.secondsLeft - 1 };
      });
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [manualLinkRetry]);

  useEffect(() => {
    if (!manualLinkRetry?.ready) return;
    handleManualLinksPreview({ retryAttempt: manualLinkRetry.attempt + 1, skipRetrySchedule: true });
  }, [manualLinkRetry]);

  useEffect(() => {
    const validIds = new Set(socialCandidates.map((item) => item.offer_id));
    setSocialHiddenIds((current) => current.filter((id) => validIds.has(id)));
  }, [socialCandidates]);

  useEffect(() => {
    const visibleIds = socialQueue.map((item) => item.offer_id);
    setSocialCheckedIds((current) => {
      const kept = current.filter((id) => visibleIds.includes(id));
      if (kept.length) return kept;
      return visibleIds.slice(0, 5);
    });
  }, [socialQueue]);

  function toggleProvider(providerKey) {
    setImportForm((current) => {
      const exists = current.providers.includes(providerKey);
      return {
        ...current,
        providers: exists ? current.providers.filter((item) => item !== providerKey) : [...current.providers, providerKey],
      };
    });
  }

  async function handleImportPreview() {
    setImportLoading(true);
    try {
      const query = new URLSearchParams({
        provider: importForm.previewProvider,
        keyword: importForm.keyword,
        limit: String(importForm.limit),
        pages: String(importForm.pages),
      });
      const data = await fetchJson(`/dashboard/api/import/preview?${query.toString()}`);
      setImportPreview(data);
      setToast({ type: "success", message: `${data.count} itens de preview carregados para ${data.provider}.` });
    } catch (error) {
      setToast({ type: "error", message: `Preview de importacao falhou: ${error.message}` });
    } finally {
      setImportLoading(false);
    }
  }

  async function handleImportRun() {
    setRunLoading((state) => ({ ...state, import: true }));
    try {
      const data = await fetchJson("/dashboard/api/import/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ providers: importForm.providers }),
      });
      const processed = (data.items || []).reduce((sum, item) => sum + Number(item.processed || item.imported || 0), 0);
      const created = (data.items || []).reduce((sum, item) => sum + Number(item.created || 0), 0);
      const updated = (data.items || []).reduce((sum, item) => sum + Number(item.updated || 0), 0);
      setToast({
        type: data.error ? "error" : "success",
        message: `Importacao concluida: ${processed} processado(s), ${created} criado(s), ${updated} atualizado(s), ${data.error} erro(s).`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha na importacao: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, import: false }));
    }
  }

  function parseManualLinks() {
    return manualLinkText
      .split(/\r?\n|,|;/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  async function handleManualLinksPreview(options = {}) {
    const { retryAttempt = 1, skipRetrySchedule = false } = options;
    setManualLinkLoading(true);
    setManualLinkRetry(null);
    setManualLinkStatus({
      type: "loading",
      message: retryAttempt > 1 ? `Nova tentativa em andamento (${retryAttempt}/2)...` : "Analisando links e tentando identificar os dados do produto...",
    });
    try {
      const links = parseManualLinks();
      const data = await fetchJson("/dashboard/api/import/manual-links/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ links }),
      });
      setManualLinkPreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: true })),
      });
      setManualLinkStatus({
        type: "success",
        message: `${data.count} link(s) analisado(s) com sucesso. Preview pronto para revisar e importar.`,
      });
      setToast({ type: "success", message: `${data.count} link(s) analisado(s).` });
    } catch (error) {
      if (!skipRetrySchedule && retryAttempt === 1) {
        setManualLinkRetry({ active: true, ready: false, attempt: retryAttempt, secondsLeft: 30 });
        setManualLinkStatus({
          type: "retry",
          message: `A primeira tentativa falhou. O sistema vai tentar de novo em 30s. Erro atual: ${error.message}`,
        });
        setToast({ type: "info", message: "Primeira tentativa falhou. Nova tentativa automatica agendada para 30s." });
      } else {
        setManualLinkStatus({
          type: "error",
          message: `Preview manual por link falhou mesmo apos a nova tentativa. Detalhe: ${error.message}`,
        });
        setToast({ type: "error", message: `Preview manual por link falhou: ${error.message}` });
      }
    } finally {
      setManualLinkLoading(false);
    }
  }

  async function handleManualLinksImport() {
    setRunLoading((state) => ({ ...state, manualLinks: true }));
    try {
      const items = (manualLinkPreview?.items || []).filter((item) => item.selected);
      if (!items.length) {
        throw new Error("Selecione ao menos um item manual para importar.");
      }
      const data = await fetchJson("/dashboard/api/import/manual-links/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      setManualLinkStatus({
        type: "success",
        message: `Importacao manual concluida: ${data.processed} processado(s), ${data.created} criado(s) e ${data.updated} atualizado(s).`,
      });
      setToast({ type: "success", message: `Importacao manual: ${data.processed} processado(s), ${data.created} criado(s), ${data.updated} atualizado(s).` });
      await loadSnapshot();
    } catch (error) {
      setManualLinkStatus({
        type: "error",
        message: `Importacao manual por link falhou. Detalhe: ${error.message}`,
      });
      setToast({ type: "error", message: `Importacao manual por link falhou: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, manualLinks: false }));
    }
  }

  async function handleFileImportPreview() {
    if (!fileImportFile) {
      setToast({ type: "error", message: "Selecione primeiro um arquivo exportado do afiliado." });
      return;
    }
    setFileImportLoading(true);
    try {
      const body = new FormData();
      body.append("provider", fileImportProvider);
      body.append("upload", fileImportFile);
      const data = await fetchJson("/dashboard/api/import/file/preview", {
        method: "POST",
        body,
      });
      setFileImportPreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: true })),
      });
      setToast({ type: "success", message: `${data.count} item(ns) carregado(s) do arquivo ${data.filename || ""}.` });
    } catch (error) {
      setToast({ type: "error", message: `Preview por arquivo falhou: ${error.message}` });
    } finally {
      setFileImportLoading(false);
    }
  }

  async function handleFileImportRun() {
    setRunLoading((state) => ({ ...state, manualLinks: true }));
    try {
      const items = (fileImportPreview?.items || []).filter((item) => item.selected);
      if (!items.length) {
        throw new Error("Selecione ao menos um item do arquivo para importar.");
      }
      const data = await fetchJson("/dashboard/api/import/manual-links/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      setToast({ type: "success", message: `Importacao por arquivo: ${data.processed} processado(s), ${data.created} criado(s), ${data.updated} atualizado(s).` });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Importacao por arquivo falhou: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, manualLinks: false }));
    }
  }

  async function handleShopeeRecategorize(onlyUncategorized = true) {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const data = await fetchJson("/dashboard/api/import/store/recategorize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ store: "Shopee", only_uncategorized: onlyUncategorized }),
      });
      setToast({
        type: "success",
        message: onlyUncategorized
          ? `Shopee recategorizada em ofertas: ${data.updated} atualizada(s), ${data.skipped} mantida(s).`
          : `Shopee recategorizada por completo: ${data.updated} atualizada(s), ${data.skipped} mantida(s).`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao corrigir categorias da Shopee: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  function updateManualPreviewItem(index, field, value) {
    setManualLinkPreview((current) => {
      if (!current?.items?.length) return current;
      const items = current.items.map((item, itemIndex) => (
        itemIndex === index ? { ...item, [field]: value } : item
      ));
      return { ...current, items };
    });
  }

  async function handleSocialRun() {
    setRunLoading((state) => ({ ...state, social: true }));
    try {
      const selectedIds = socialCheckedIds.filter((id) => socialQueue.some((item) => item.offer_id === id));
      if (!selectedIds.length) {
        throw new Error("Selecione ao menos uma oferta da fila pronta.");
      }
      const payload = { ...socialSplit, limit: selectedIds.length, offer_ids: selectedIds };
      const data = await fetchJson("/dashboard/api/social/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const errorCount = Number((data.errors || []).length);
      setToast({ type: errorCount ? "error" : "success", message: `Publicacao ${payload.platform}/${payload.mode}: ${data.count} concluido(s), ${errorCount} erro(s).` });
      setSocialHiddenIds((current) => [...new Set([...current, ...selectedIds])]);
      await Promise.all([loadSnapshot(), loadSocialPreview(20)]);
    } catch (error) {
      setToast({ type: "error", message: `Falha na publicacao social: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, social: false }));
    }
  }

  async function handleFacebookBatch() {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const selectedIds = socialCheckedIds.filter((id) => socialQueue.some((item) => item.offer_id === id));
      if (!selectedIds.length) {
        throw new Error("Selecione ao menos uma oferta da fila pronta.");
      }
      const data = await fetchJson("/social/meta/facebook/publish-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: selectedIds.length, offer_ids: selectedIds }),
      });
      setToast({ type: "success", message: `Facebook em lote: ${data.count} publicacao(oes) concluida(s).` });
      setSocialHiddenIds((current) => [...new Set([...current, ...selectedIds])]);
      await Promise.all([loadSnapshot(), loadSocialPreview(20)]);
    } catch (error) {
      setToast({ type: "error", message: `Falha no lote do Facebook: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleRunJobNow(jobKey) {
    setJobRunLoading((state) => ({ ...state, [jobKey]: true }));
    try {
      const url = jobKey === "import"
        ? "/dashboard/api/automation/import/run-now"
        : jobKey === "story"
          ? "/dashboard/api/automation/story/run-now"
          : "/dashboard/api/automation/social/run-now";
      const payload = jobKey === "import"
        ? { providers: settingsForm.auto_import_providers }
        : jobKey === "story"
          ? {
              platform: settingsForm.auto_story_platform,
              mode: "story",
              limit: Number(settingsForm.auto_story_limit || 1),
            }
        : {
            platform: settingsForm.auto_social_platform,
            mode: "feed",
            limit: Number(settingsForm.auto_social_limit || 1),
          };
      const data = await fetchJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setToast({
        type: "success",
        message: jobKey === "import"
          ? `Importacao manual concluida: ${(data.items || []).reduce((sum, item) => sum + Number(item.processed || item.imported || 0), 0)} processado(s), ${(data.items || []).reduce((sum, item) => sum + Number(item.created || 0), 0)} criado(s), ${(data.items || []).reduce((sum, item) => sum + Number(item.updated || 0), 0)} atualizado(s), ${data.error || 0} erro(s).`
          : jobKey === "story"
            ? `Stories manuais concluidos: ${data.count || 0} publicacao(oes).`
            : `Social manual concluido: ${data.count || 0} publicacao(oes).`,
      });
      await Promise.all([loadSnapshot(), loadSocialPreview(Number(socialForm.limit))]);
    } catch (error) {
      setToast({ type: "error", message: `Falha ao rodar job ${jobKey}: ${error.message}` });
    } finally {
      setJobRunLoading((state) => ({ ...state, [jobKey]: false }));
    }
  }

  function toggleSettingsProvider(providerKey) {
    setSettingsForm((current) => {
      const exists = current.auto_import_providers.includes(providerKey);
      return {
        ...current,
        auto_import_providers: exists
          ? current.auto_import_providers.filter((item) => item !== providerKey)
          : [...current.auto_import_providers, providerKey],
      };
    });
  }

  async function handleSettingsSave() {
    setSettingsLoading(true);
    try {
      const payload = {
        manager_username: settingsForm.manager_username,
        manager_password: settingsForm.manager_password || null,
        meta_access_token: settingsForm.meta_access_token || null,
        auto_import_enabled: settingsForm.auto_import_enabled,
        auto_import_times: settingsForm.auto_import_times,
        auto_import_providers: settingsForm.auto_import_providers,
        auto_social_enabled: settingsForm.auto_social_enabled,
        auto_social_times: settingsForm.auto_social_times,
        auto_social_platform: settingsForm.auto_social_platform,
        auto_social_mode: settingsForm.auto_social_mode,
        auto_social_limit: Number(settingsForm.auto_social_limit || 1),
        auto_story_enabled: settingsForm.auto_story_enabled,
        auto_story_times: settingsForm.auto_story_times,
        auto_story_platform: settingsForm.auto_story_platform,
        auto_story_limit: Number(settingsForm.auto_story_limit || 1),
        sftp_host: settingsForm.sftp_host,
        sftp_port: Number(settingsForm.sftp_port || 22),
        sftp_username: settingsForm.sftp_username,
        sftp_password: settingsForm.sftp_password || null,
        sftp_remote_path: settingsForm.sftp_remote_path,
        stories_public_base_url: settingsForm.stories_public_base_url,
      };
      const data = await fetchJson("/dashboard/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setToast({ type: "success", message: data.message || "Configuracoes atualizadas." });
      await loadSnapshot();
      if (data.reauth_required) {
        window.setTimeout(() => {
          window.location.href = "/manager/login";
        }, 900);
      }
    } catch (error) {
      setToast({ type: "error", message: `Falha ao salvar configuracoes: ${error.message}` });
    } finally {
      setSettingsLoading(false);
    }
  }

  async function handleDeployStories() {
    setRunLoading((state) => ({ ...state, deployStories: true }));
    try {
      const data = await fetchJson("/dashboard/api/deploy/stories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ only_files: null }),
      });
      setToast({ type: "success", message: `Deploy de stories concluido: ${data.count || 0} arquivo(s) enviados.` });
      await Promise.all([loadSnapshot(), loadSocialPreview(Number(socialForm.limit))]);
    } catch (error) {
      setToast({ type: "error", message: `Falha no deploy de stories: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, deployStories: false }));
    }
  }

  async function handleDeploySite() {
    setRunLoading((state) => ({ ...state, deploySite: true }));
    try {
      const data = await fetchJson("/dashboard/api/deploy/site", {
        method: "POST",
      });
      setToast({ type: "success", message: `Atualizar pagina concluido: ${data.count || 0} arquivo(s) enviados ao DreamHost.` });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao atualizar pagina: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, deploySite: false }));
    }
  }

  const overview = snapshot?.overview || {};
  const charts = snapshot?.charts || {};
  const importStatus = snapshot?.status?.imports || [];
  const socialStatus = snapshot?.status?.social || [];
  const automation = snapshot?.automation || {};
  const manager = snapshot?.manager || {};
  const sftpSettings = snapshot?.settings?.sftp || {};
  const metaTokenConfigured = Boolean(snapshot?.settings?.meta_access_token_configured);

  function toggleSocialSelection(offerId) {
    setSocialCheckedIds((current) => (
      current.includes(offerId)
        ? current.filter((id) => id !== offerId)
        : [...current, offerId]
    ));
  }

  function dismissSocialOffer(offerId) {
    setSocialHiddenIds((current) => [...new Set([...current, offerId])]);
  }

  return (
    <>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">ZP</div>
            <div>
              <h1>Zero Preco Control</h1>
              <p>Operacao de afiliados, importacao e social em um painel so.</p>
            </div>
          </div>
          <div className="sidebar-nav">
            {[
              ["visao-geral", "Visao geral", "KPI, health e tendencias do funil."],
              ["importadores", "Importadores", "Rodar preview e execucao dos conectores."],
              ["social", "Social", "Facebook, Instagram feed e stories."],
              ["analytics", "Analytics", "Cliques, ofertas e categorias em destaque."],
              ["execucoes", "Execucoes", "Historico operacional do backend Python."],
            ].map(([id, label, note], index) => (
              <button key={id} className={`nav-button ${index === 0 ? "is-active" : ""}`} onClick={() => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" })}>
                <span className="nav-label">{label}</span>
                <span className="nav-note">{note}</span>
              </button>
            ))}
          </div>
          <div className="sidebar-card">
            <h3>Status rapido</h3>
            <p>Facebook feed, Facebook lote e Instagram feed ja estao validados. Story do Instagram segue visivel no painel para ajuste fino.</p>
          </div>
          <div className="sidebar-card">
            <h3>Proximos pontos sugeridos</h3>
            <p>Agendamento horario, fila por prioridade, aprovacao manual, score por CTR e alertas de erro por canal.</p>
          </div>
        </aside>

        <main className="main">
          <section className="hero" id="visao-geral">
            <div className="hero-head">
              <div className="hero-copy">
                <span className="hero-kicker">Painel de operacao</span>
                <h2>Gerenciador React para o backend de afiliados.</h2>
                <p>Controle importacoes, publicacoes sociais, cliques, graficos e os provedores atuais e futuros em uma interface unica, limpa e pronta para crescer.</p>
              </div>
              <div className="hero-actions">
                <button className="button" onClick={loadSnapshot} disabled={loading}>{loading ? "Atualizando..." : "Atualizar dados"}</button>
                <button className="ghost-button" onClick={() => loadSocialPreview(Number(socialForm.limit))} disabled={socialLoading}>{socialLoading ? "Montando previews..." : "Atualizar previews sociais"}</button>
              </div>
            </div>
          </section>

          <div className="toolbar">
            <div className="toolbar-copy">
              <h3>Radar operacional</h3>
              <p>Visao rapida de estoque ativo, engajamento, importacoes e social.</p>
            </div>
            <div className="toolbar-actions">
              <span className="status-pill is-ok">API Python online</span>
              <span className={`status-pill ${socialStatus.some((item) => !item.enabled) ? "is-warn" : "is-ok"}`}>Social monitorado</span>
              <span className={`status-pill ${manager.auth_enabled ? "is-ok" : "is-warn"}`}>{manager.auth_enabled ? `Manager protegido (${manager.username})` : "Manager sem auth"}</span>
              <form method="post" action="/manager/logout">
                <button className="ghost-button" type="submit">Sair</button>
              </form>
            </div>
          </div>

          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-label">Ofertas ativas</div>
              <div className="metric-value">{fmtInt(overview.active_offers)}</div>
              <div className="metric-foot">{fmtInt(overview.featured_offers)} em destaque agora.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Cliques nos ultimos 7 dias</div>
              <div className="metric-value">{fmtInt(overview.clicks_7d)}</div>
              <div className="metric-foot">{fmtInt(overview.clicks_30d)} acumulados em 30 dias.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Lojas rastreadas</div>
              <div className="metric-value">{fmtInt(overview.tracked_stores)}</div>
              <div className="metric-foot">{fmtMoney(overview.average_price)} de preco medio das ofertas ativas.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Execucoes recentes</div>
              <div className="metric-value">{fmtInt((overview.import_runs_7d || 0) + (overview.social_posts_7d || 0))}</div>
              <div className="metric-foot">{fmtInt(overview.import_runs_7d)} importacoes + {fmtInt(overview.social_posts_7d)} posts sociais nos ultimos 7 dias.</div>
            </div>
          </div>

          <section className="panel" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Automacao e agendamento</h3>
                <p className="panel-subtitle">Jobs periodicos do backend Python para importacao e social.</p>
              </div>
            </div>
            <div className="status-grid">
              {["import", "social", "story"].map((jobKey) => {
                const job = automation?.jobs?.[jobKey] || {};
                return (
                  <article className={`status-card ${job.last_status === "error" ? "is-error" : job.last_status === "success" ? "is-success" : ""}`} key={jobKey}>
                    <div className="status-card-head">
                      <h4>{jobKey === "import" ? "Job de importacao" : jobKey === "story" ? "Job de stories" : "Job de feed"}</h4>
                      <span className={`badge ${job.enabled ? "is-success" : "is-neutral"}`}>{job.enabled ? "Ativo" : "Desligado"}</span>
                    </div>
                    <p>{jobKey === "import" ? `Provedores: ${(job.providers || []).join(", ") || "nenhum"}` : `Canal: ${job.platform || "-"} / ${job.mode || "-"} / limite ${job.limit || 0}`}</p>
                    <p>Intervalo de fallback: {job.interval_minutes || 0} min</p>
                    <p>Ultima execucao: {fmtDate(job.last_run_at) || "ainda nao rodou"}</p>
                    <p>Proxima execucao: {job.next_run_at ? fmtDate(job.next_run_at) : "desligado"}</p>
                    <p>Contagem regressiva: {fmtCountdown(job.next_run_at, nowTs)}</p>
                    <p>
                      Ultimo status:{" "}
                      <span className={`badge ${job.last_status === "success" ? "is-success" : job.last_status === "error" ? "is-warning" : "is-neutral"}`}>
                        {fmtJobStatus(job.last_status)}
                      </span>
                    </p>
                    <p>Ultimo resultado: {summarizeJobResult(jobKey, job.last_result)}</p>
                    <div className="provider-actions" style={{ marginTop: 12 }}>
                      <button
                        className="tiny-button is-soft"
                        onClick={() => handleRunJobNow(jobKey)}
                        disabled={jobRunLoading[jobKey]}
                      >
                        {jobRunLoading[jobKey] ? "Rodando..." : "Rodar agora"}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <section className="panel" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Configuracoes do manager</h3>
                <p className="panel-subtitle">Troque usuario, senha e horarios fixos sem editar o .env na mao.</p>
              </div>
              <div className="provider-actions">
                <button className="button is-primary" onClick={handleSettingsSave} disabled={settingsLoading}>
                  {settingsLoading ? "Salvando..." : "Salvar configuracoes"}
                </button>
              </div>
            </div>

            <div className="surface">
              <div className="field-grid">
                <div className="field">
                  <label>Usuario do manager</label>
                  <input type="text" value={settingsForm.manager_username} onChange={(e) => setSettingsForm((state) => ({ ...state, manager_username: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Nova senha do manager</label>
                  <input type="password" placeholder="Deixe vazio para manter a atual" value={settingsForm.manager_password} onChange={(e) => setSettingsForm((state) => ({ ...state, manager_password: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Auto importacao</label>
                  <label className="check-chip">
                    <input type="checkbox" checked={settingsForm.auto_import_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_import_enabled: e.target.checked }))} />
                    Ativar importacao automatica
                  </label>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Horarios de importacao</label>
                  <input type="text" value={settingsForm.auto_import_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_import_times: e.target.value }))} />
                  <small>Use HH:MM separado por virgula. Ex: 06:30,12:30,18:30</small>
                </div>
                <div className="field">
                  <label>Provedores da importacao</label>
                  <div className="check-grid">
                    {IMPORT_OPTIONS.map((item) => (
                      <label className="check-chip" key={`settings-${item.key}`}>
                        <input type="checkbox" checked={settingsForm.auto_import_providers.includes(item.key)} onChange={() => toggleSettingsProvider(item.key)} />
                        {item.label}
                      </label>
                    ))}
                  </div>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>META_ACCESS_TOKEN</label>
                  <input type="password" placeholder={metaTokenConfigured ? "Token atual salvo. Cole outro para substituir." : "Cole aqui o token novo da Meta"} value={settingsForm.meta_access_token} onChange={(e) => setSettingsForm((state) => ({ ...state, meta_access_token: e.target.value }))} />
                  <small>{metaTokenConfigured ? "O valor atual fica oculto. Se deixar vazio, o token salvo sera mantido." : "Ainda nao ha token salvo no backend."}</small>
                </div>
                <div className="field">
                  <label>Auto social</label>
                  <label className="check-chip">
                    <input type="checkbox" checked={settingsForm.auto_social_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_enabled: e.target.checked }))} />
                    Ativar feed automatico
                  </label>
                </div>
                <div className="field">
                  <label>Horarios do feed</label>
                  <input type="text" value={settingsForm.auto_social_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_times: e.target.value }))} />
                  <small>Ex: 07:00,13:00,19:00</small>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Canal automatico do feed</label>
                  <select value={settingsForm.auto_social_platform} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_platform: e.target.value }))}>
                    <option value="facebook">facebook</option>
                    <option value="both">facebook + instagram</option>
                    <option value="instagram">instagram</option>
                  </select>
                </div>
                <div className="field">
                  <label>Modo automatico</label>
                  <input type="text" value="feed" disabled />
                </div>
                <div className="field">
                  <label>Quantidade por rodada</label>
                  <input type="number" min="1" max="10" value={settingsForm.auto_social_limit} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_limit: Number(e.target.value || 1) }))} />
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Auto stories</label>
                  <label className="check-chip">
                    <input type="checkbox" checked={settingsForm.auto_story_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_enabled: e.target.checked }))} />
                    Ativar stories automaticos
                  </label>
                </div>
                <div className="field">
                  <label>Horarios dos stories</label>
                  <input type="text" value={settingsForm.auto_story_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_times: e.target.value }))} />
                  <small>Ex: 07:05,13:05,19:05</small>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Canal automatico dos stories</label>
                  <select value={settingsForm.auto_story_platform} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_platform: e.target.value }))}>
                    <option value="instagram">instagram</option>
                  </select>
                </div>
                <div className="field">
                  <label>Modo dos stories</label>
                  <input type="text" value="story" disabled />
                </div>
                <div className="field">
                  <label>Quantidade por rodada</label>
                  <input type="number" min="1" max="10" value={settingsForm.auto_story_limit} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_limit: Number(e.target.value || 1) }))} />
                </div>
              </div>

              <div className="deploy-divider">
                <span>Deploy DreamHost</span>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Host SFTP</label>
                  <input type="text" value={settingsForm.sftp_host} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_host: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Porta</label>
                  <input type="number" min="1" value={settingsForm.sftp_port} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_port: Number(e.target.value || 22) }))} />
                </div>
                <div className="field">
                  <label>Usuario SFTP</label>
                  <input type="text" value={settingsForm.sftp_username} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_username: e.target.value }))} />
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Senha SFTP</label>
                  <input type="password" placeholder="Deixe vazio para manter a senha atual" value={settingsForm.sftp_password} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_password: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Destino remoto</label>
                  <input type="text" value={settingsForm.sftp_remote_path} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_remote_path: e.target.value }))} />
                  <small>Ex: /home/usuario/zeropreco.com.br/public_html</small>
                </div>
                <div className="field">
                  <label>Base publica dos stories</label>
                  <input type="text" value={settingsForm.stories_public_base_url} onChange={(e) => setSettingsForm((state) => ({ ...state, stories_public_base_url: e.target.value }))} />
                  <small>Ex: https://zeropreco.com.br/stories</small>
                </div>
              </div>

              <div className="deploy-summary">
                <div className={`status-card ${sftpSettings.enabled ? "is-success" : "is-error"}`}>
                  <div className="status-card-head">
                    <h4>SFTP atual</h4>
                    <span className={`badge ${sftpSettings.enabled ? "is-success" : "is-warning"}`}>{sftpSettings.enabled ? "Pronto" : "Incompleto"}</span>
                  </div>
                  <p>Host: {sftpSettings.host || "-"}</p>
                  <p>Porta: {sftpSettings.port || 22}</p>
                  <p>Usuario: {sftpSettings.username || "-"}</p>
                  <p>Destino: {sftpSettings.remote_path || "-"}</p>
                  <p>Stories: {sftpSettings.stories_public_base_url || "-"}</p>
                </div>
                <div className="status-card">
                  <div className="status-card-head">
                    <h4>Acoes de deploy</h4>
                    <span className="badge is-neutral">Backend Python</span>
                  </div>
                  <p>Atualizar stories envia `public_html/stories`. Atualizar pagina envia todo `public_html` para o DreamHost.</p>
                  <div className="provider-actions">
                    <button className="button is-secondary" onClick={handleDeployStories} disabled={runLoading.deployStories}>
                      {runLoading.deployStories ? "Enviando stories..." : "Atualizar stories"}
                    </button>
                    <button className="button is-primary" onClick={handleDeploySite} disabled={runLoading.deploySite}>
                      {runLoading.deploySite ? "Atualizando pagina..." : "Atualizar pagina"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <div className="content-grid">
            <div className="stack">
              <section className="panel">
                <MultiLineChart title="Linha operacional" subtitle="Importacoes, social e itens processados nos ultimos 14 dias." rows={charts.runs_by_day || []} />
              </section>
              <section className="panel" id="analytics">
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Produtos mais clicados</h3>
                    <p className="panel-subtitle">Baseado na tabela de cliques do site publico.</p>
                  </div>
                </div>
                {!snapshot?.top_clicked?.length ? <div className="empty-state">Sem cliques suficientes para ranking.</div> : (
                  <div className="offer-list">
                    {snapshot.top_clicked.map((offer) => (
                      <div className="offer-row" key={offer.id}>
                        <img className="offer-thumb" src={offer.imagem_url} alt={offer.titulo} />
                        <div style={{ flex: 1 }}>
                          <strong>{offer.titulo}</strong>
                          <small>{offer.loja} · {offer.categoria || "Geral"}</small>
                          <div className="offer-meta">
                            <span className="meta-chip">{fmtMoney(offer.preco)}</span>
                            <span className="meta-chip">{fmtInt(offer.clicks)} cliques</span>
                          </div>
                        </div>
                        <a className="tiny-button is-soft" href={`/oferta.php?slug=${offer.slug}`} target="_blank" rel="noreferrer">Abrir</a>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>

            <div className="stack">
              <section className="panel">
                <MiniBarChart title="Cliques por dia" subtitle="Volume dos ultimos 14 dias." items={charts.clicks_by_day || []} color="#2b66ff" />
              </section>
              <section className="panel">
                <MiniBarChart title="Ofertas por loja" subtitle="Onde o catalogo esta mais forte." items={charts.offers_by_store || []} color="#167b53" />
              </section>
              <section className="panel">
                <MiniBarChart title="Categorias com mais volume" subtitle="Prioridade de sortimento ativo." items={charts.offers_by_category || []} color="#b66a00" />
              </section>
            </div>
          </div>

          <section className="panel" id="importadores" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Importadores afiliados</h3>
                <p className="panel-subtitle">Execute preview, importacao real e acompanhe o estado dos conectores.</p>
              </div>
              <div className="provider-actions">
                <button className="button is-primary" onClick={handleImportRun} disabled={runLoading.import || !importForm.providers.length}>{runLoading.import ? "Rodando importacao..." : "Rodar importacao"}</button>
              </div>
            </div>

            <div className="providers-grid" style={{ marginBottom: 18 }}>
              {IMPORT_OPTIONS.map((item) => {
                const providerStatus = importStatus.find((entry) => entry.provider === item.label);
                return (
                  <div className="provider-card" key={item.key}>
                    <div className="panel-head" style={{ marginBottom: 12 }}>
                      <div>
                        <h4>{item.label}</h4>
                        <p>{item.note}</p>
                      </div>
                      <span className={`badge ${statusClass(providerStatus?.enabled, providerStatus?.mode)}`}>{providerStatus?.enabled ? "Pronto" : "Dependente"}</span>
                    </div>
                    <p>{providerStatus?.notes || "Ainda sem status calculado."}</p>
                    <div className="provider-actions">
                      <label className="check-chip">
                        <input type="checkbox" checked={importForm.providers.includes(item.key)} onChange={() => toggleProvider(item.key)} />
                        Incluir na execução
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="surface">
              <h4>Preview pontual do importador</h4>
              <p>Valide termos, volume e qualidade antes de rodar a importação real.</p>
              <div className="field-grid" style={{ marginTop: 16 }}>
                <div className="field">
                  <label>Provedor</label>
                  <select value={importForm.previewProvider} onChange={(e) => setImportForm((state) => ({ ...state, previewProvider: e.target.value }))}>
                    {IMPORT_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Palavra-chave</label>
                  <input type="text" value={importForm.keyword} onChange={(e) => setImportForm((state) => ({ ...state, keyword: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Limite</label>
                  <input type="number" min="1" max="30" value={importForm.limit} onChange={(e) => setImportForm((state) => ({ ...state, limit: Number(e.target.value || 1) }))} />
                </div>
              </div>
              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Páginas</label>
                  <input type="number" min="1" max="5" value={importForm.pages} onChange={(e) => setImportForm((state) => ({ ...state, pages: Number(e.target.value || 1) }))} />
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label>Execução selecionada</label>
                  <div className="check-grid">
                    {importForm.providers.map((provider) => <span className="meta-chip" key={provider}>{provider}</span>)}
                  </div>
                </div>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-primary" onClick={handleImportPreview} disabled={importLoading}>{importLoading ? "Buscando preview..." : "Carregar preview"}</button>
              </div>
              <div style={{ marginTop: 18 }}>
                {!importPreview?.items?.length ? <div className="empty-state">Nenhum preview carregado ainda.</div> : (
                  <div className="preview-grid">
                    {importPreview.items.slice(0, 6).map((item, index) => (
                      <div className="surface" key={`${item.id || item.slug || index}`}>
                        <h4>{item.title || item.titulo || item.name || "Item sem titulo"}</h4>
                        <p>{item.store || item.loja || item.seller_name || importPreview.provider}</p>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">{fmtMoney(item.price || item.preco || 0)}</span>
                          {"sold_quantity" in item ? <span className="meta-chip">{fmtInt(item.sold_quantity || 0)} vendas</span> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="deploy-divider">
                <span>Importação por arquivo</span>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                  <div className="field">
                    <label>Marketplace do arquivo</label>
                    <select value={fileImportProvider} onChange={(e) => setFileImportProvider(e.target.value)}>
                      <option value="shopee">Shopee CSV</option>
                      <option value="amazon">Amazon TXT</option>
                    </select>
                  </div>
                  <div className="field" style={{ gridColumn: "span 2" }}>
                    <label>Arquivo exportado</label>
                    <input
                      type="file"
                      accept={fileImportProvider === "amazon" ? ".txt,text/plain" : ".csv,text/csv"}
                      onChange={(e) => setFileImportFile(e.target.files?.[0] || null)}
                    />
                    <small>
                      {fileImportProvider === "amazon"
                        ? "Use um TXT com um link da Amazon por linha. Evite dois links na mesma linha para ter o preview mais estavel."
                        : "Use o CSV exportado do painel da Shopee. O preço do arquivo vira a fonte principal do preview."}
                    </small>
                  </div>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={handleFileImportPreview} disabled={fileImportLoading}>
                  {fileImportLoading ? "Lendo arquivo..." : "Analisar arquivo"}
                </button>
                <button className="button is-primary" onClick={handleFileImportRun} disabled={runLoading.manualLinks}>
                  {runLoading.manualLinks ? "Importando arquivo..." : "Importar arquivo"}
                </button>
                  <button className="button is-secondary" onClick={() => handleShopeeRecategorize(false)} disabled={runLoading.batch}>
                    {runLoading.batch ? "Corrigindo categorias..." : "Recategorizar toda Shopee"}
                  </button>
                  <button className="button is-ghost" onClick={() => handleShopeeRecategorize(true)} disabled={runLoading.batch}>
                    {runLoading.batch ? "Corrigindo categorias..." : "Corrigir so 'ofertas'"}
                  </button>
                </div>
              <div style={{ marginTop: 18 }}>
                {!fileImportPreview?.items?.length ? (
                  <div className="empty-state">Nenhum arquivo analisado ainda.</div>
                ) : (
                  <div className="preview-grid">
                    {fileImportPreview.items.map((item, index) => (
                      <div className="surface" key={`${item.item_id || item.url || item.title}-${index}`}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>{item.store || item.provider || "Marketplace"}</h4>
                            <p>{item.source_file ? `Arquivo: ${item.source_file}` : "Arquivo importado"}{item.affiliate_code ? ` | Afiliado: ${item.affiliate_code}` : ""}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={Boolean(item.selected)}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, selected: e.target.checked } : entry);
                                return { ...current, items };
                              })}
                            />
                            Importar
                          </label>
                        </div>
                        <div className="field-grid">
                          <div className="field" style={{ gridColumn: "1 / -1" }}>
                            <label>Título</label>
                            <input
                              type="text"
                              value={item.title || ""}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, title: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field">
                            <label>Preço</label>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={item.price ?? 0}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, price: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                          <div className="field">
                            <label>Categoria</label>
                            <input
                              type="text"
                              value={item.category || ""}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, category: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                          <div className="field">
                            <label>Vendas / comissão</label>
                            <input type="text" value={[item.sales_label, item.commission_rate].filter(Boolean).join(" | ")} readOnly />
                          </div>
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">{fmtMoney(item.price || 0)}</span>
                          {item.sales_label ? <span className="meta-chip">{item.sales_label}</span> : null}
                          {item.commission_value ? <span className="meta-chip">{item.commission_value}</span> : null}
                        </div>
                        <div className="list" style={{ marginTop: 14 }}>
                          {item.image ? <a className="tiny-button is-soft" href={item.image} target="_blank" rel="noreferrer">Abrir imagem</a> : null}
                          {item.url ? <a className="tiny-button" href={item.url} target="_blank" rel="noreferrer">Abrir link afiliado</a> : null}
                          {item.canonical_url && item.canonical_url !== item.url ? <a className="tiny-button is-soft" href={item.canonical_url} target="_blank" rel="noreferrer">Abrir produto</a> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="deploy-divider">
                <span>Importação manual por link</span>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field" style={{ gridColumn: "1 / -1" }}>
                  <label>Links afiliados manuais</label>
                  <textarea
                    rows="5"
                    placeholder="Cole aqui links da Shopee, Mercado Livre, Amazon ou TikTok, um por linha"
                    value={manualLinkText}
                    onChange={(e) => setManualLinkText(e.target.value)}
                  />
                  <small>O sistema tenta identificar loja, título, foto, preço e categoria. Antes de importar, você pode corrigir qualquer campo no preview.</small>
                </div>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={handleManualLinksPreview} disabled={manualLinkLoading}>
                  {manualLinkLoading ? "Lendo links..." : "Analisar links"}
                </button>
                <button className="button is-primary" onClick={handleManualLinksImport} disabled={runLoading.manualLinks}>
                  {runLoading.manualLinks ? "Importando links..." : "Importar selecionados"}
                </button>
              </div>
              {manualLinkStatus ? (
                <div className={`status-card manual-link-status ${manualLinkStatus.type === "error" ? "is-error" : manualLinkStatus.type === "success" ? "is-success" : ""}`} style={{ marginTop: 16 }}>
                  <div className="status-card-head">
                    <h4>
                      {manualLinkStatus.type === "loading" ? "Analisando links" : manualLinkStatus.type === "retry" ? "Nova tentativa agendada" : manualLinkStatus.type === "success" ? "Pronto" : "Falha no preview"}
                    </h4>
                    {manualLinkRetry?.active ? <span className="manual-link-countdown">{manualLinkRetry.secondsLeft}s</span> : null}
                  </div>
                  <p>{manualLinkStatus.message}</p>
                </div>
              ) : null}
              <div style={{ marginTop: 18 }}>
                {!manualLinkPreview?.items?.length ? (
                  <div className="empty-state">Nenhum link manual analisado ainda.</div>
                ) : (
                  <div className="preview-grid">
                    {manualLinkPreview.items.map((item, index) => (
                      <div className="surface" key={`${item.url || item.title}-${index}`}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>{item.store || item.provider || "Marketplace"}</h4>
                            <p>{item.affiliate_detected ? `Afiliado detectado${item.affiliate_code ? `: ${item.affiliate_code}` : ""}` : "Link sem rastreamento afiliado confirmado"}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={Boolean(item.selected)}
                              onChange={(e) => updateManualPreviewItem(index, "selected", e.target.checked)}
                            />
                            Importar
                          </label>
                        </div>
                        <div className="field-grid">
                          <div className="field" style={{ gridColumn: "1 / -1" }}>
                            <label>Titulo</label>
                            <input type="text" value={item.title || ""} onChange={(e) => updateManualPreviewItem(index, "title", e.target.value)} />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field">
                            <label>Preco</label>
                            <input type="number" min="0" step="0.01" value={item.price ?? 0} onChange={(e) => updateManualPreviewItem(index, "price", e.target.value)} />
                          </div>
                          <div className="field">
                            <label>Preco antigo</label>
                            <input type="number" min="0" step="0.01" value={item.old_price ?? ""} onChange={(e) => updateManualPreviewItem(index, "old_price", e.target.value)} />
                          </div>
                          <div className="field">
                            <label>Categoria</label>
                            <input type="text" value={item.category || ""} onChange={(e) => updateManualPreviewItem(index, "category", e.target.value)} />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field" style={{ gridColumn: "1 / -1" }}>
                            <label>Descricao</label>
                            <textarea rows="4" value={item.description || ""} onChange={(e) => updateManualPreviewItem(index, "description", e.target.value)} />
                          </div>
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">{item.provider || "manual"}</span>
                          <span className="meta-chip">{fmtMoney(item.price || 0)}</span>
                          {item.old_price ? <span className="meta-chip">{fmtMoney(item.old_price)}</span> : null}
                        </div>
                        <div className="list" style={{ marginTop: 14 }}>
                          {item.image ? <a className="tiny-button is-soft" href={item.image} target="_blank" rel="noreferrer">Abrir imagem</a> : null}
                          {item.url ? <a className="tiny-button" href={item.url} target="_blank" rel="noreferrer">Abrir link</a> : null}
                          {item.canonical_url && item.canonical_url !== item.url ? <a className="tiny-button is-soft" href={item.canonical_url} target="_blank" rel="noreferrer">Abrir destino final</a> : null}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel" id="social" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Publicação social</h3>
                <p className="panel-subtitle">Escolha canal, quantidade e formato para disparar feed, lote ou stories.</p>
              </div>
              <div className="provider-actions">
                <button className="button is-primary" onClick={handleSocialRun} disabled={runLoading.social}>
                  {runLoading.social ? "Publicando..." : "Rodar publicação"}
                </button>
                <button className="ghost-button" onClick={handleFacebookBatch} disabled={runLoading.batch}>
                  {runLoading.batch ? "Enviando lote..." : "Facebook em lote"}
                </button>
              </div>
            </div>

            <div className="providers-grid" style={{ marginBottom: 18 }}>
              {SOCIAL_OPTIONS.map((item) => {
                const [platform, mode] = item.key.split(":");
                const currentStatus = socialStatus.find((entry) => entry.platform === platform && entry.mode === mode);
                return (
                  <div className="provider-card" key={item.key}>
                    <div className="panel-head" style={{ marginBottom: 12 }}>
                      <div>
                        <h4>{item.label}</h4>
                        <p>{item.note}</p>
                      </div>
                      <span className={`badge ${statusClass(currentStatus?.enabled, currentStatus?.mode)}`}>
                        {currentStatus?.enabled ? "Ativo" : "Ajustar"}
                      </span>
                    </div>
                    <p>{currentStatus?.notes || "Canal monitorado pelo painel."}</p>
                    <label className="check-chip">
                      <input
                        type="radio"
                        name="social-mode"
                        checked={socialForm.selected === item.key}
                        onChange={() => setSocialForm((state) => ({ ...state, selected: item.key }))}
                      />
                      Usar este modo
                    </label>
                  </div>
                );
              })}
              <div className="provider-card provider-card-accent">
                <div className="panel-head" style={{ marginBottom: 12 }}>
                  <div>
                    <h4>Deploy do site</h4>
                    <p>Estado atual lido do `.env` ativo no backend.</p>
                  </div>
                  <span className={`badge ${sftpSettings.enabled ? "is-success" : "is-warning"}`}>{sftpSettings.enabled ? "DreamHost pronto" : "Configurar SFTP"}</span>
                </div>
                <p>{sftpSettings.remote_path ? `Destino remoto: ${sftpSettings.remote_path}` : "Preencha host, usuario, senha e destino remoto para liberar o deploy."}</p>
                <div className="offer-meta" style={{ marginTop: 12 }}>
                  <span className="meta-chip">{sftpSettings.host || "sem host"}</span>
                  <span className="meta-chip">{sftpSettings.stories_public_base_url || "sem URL publica"}</span>
                </div>
                <div className="provider-actions">
                  <button className="tiny-button is-soft" onClick={handleDeployStories} disabled={runLoading.deployStories}>
                    {runLoading.deployStories ? "Enviando..." : "Atualizar stories"}
                  </button>
                  <button className="tiny-button" onClick={handleDeploySite} disabled={runLoading.deploySite}>
                    {runLoading.deploySite ? "Atualizando..." : "Atualizar pagina"}
                  </button>
                </div>
              </div>
            </div>

            <div className="surface">
              <h4>Execução social</h4>
              <p>O ranking abaixo mostra todas as ofertas ordenadas por potencial de venda. Você escolhe quais publicar e pode esconder qualquer uma para focar no restante da lista.</p>
              <div className="field-grid" style={{ marginTop: 16 }}>
                <div className="field">
                  <label>Canal selecionado</label>
                  <select value={socialForm.selected} onChange={(e) => setSocialForm((state) => ({ ...state, selected: e.target.value }))}>
                    {SOCIAL_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Loja</label>
                  <select value={socialFilters.store} onChange={(e) => setSocialFilters((state) => ({ ...state, store: e.target.value }))}>
                    <option value="all">Todas as lojas</option>
                    {socialStoreOptions.map((store) => <option key={store} value={store}>{store}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Categoria</label>
                  <select value={socialFilters.category} onChange={(e) => setSocialFilters((state) => ({ ...state, category: e.target.value }))}>
                    <option value="all">Todas as categorias</option>
                    {socialCategoryOptions.map((category) => <option key={category} value={category}>{category}</option>)}
                  </select>
                </div>
              </div>
              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Fila pronta</label>
                  <div className="check-grid">
                    <span className="meta-chip">{socialCheckedIds.length} selecionada(s)</span>
                    <span className="meta-chip">{socialQueue.length} visível(is)</span>
                  </div>
                </div>
                <div className="field">
                  <label>Split atual</label>
                  <div className="check-grid">
                    <span className="meta-chip">{socialSplit.platform}</span>
                    <span className="meta-chip">{socialSplit.mode}</span>
                  </div>
                </div>
                <div className="field">
                  <label>Filtro ativo</label>
                  <div className="check-grid">
                    <span className="meta-chip">{socialFilters.store === "all" ? "todas as lojas" : socialFilters.store}</span>
                    <span className="meta-chip">{socialFilters.category === "all" ? "todas as categorias" : socialFilters.category}</span>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 18 }}>
                {socialLoading ? <div className="empty-state">Montando previews sociais...</div> : !socialPreview?.items?.length ? (
                  <div className="empty-state">Sem preview social carregado.</div>
                ) : !socialQueue.length ? (
                  <div className="empty-state">A fila atual foi consumida. Clique em atualizar previews sociais para montar mais opções.</div>
                ) : (
                  <div className="preview-grid">
                    {socialQueue.map((item, index) => (
                      <div className="surface social-queue-card" key={item.offer_id}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>#{index + 1} {item.title}</h4>
                            <p>{item.store || "Loja não informada"} · {item.category || "Categoria"}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={socialCheckedIds.includes(item.offer_id)}
                              onChange={() => toggleSocialSelection(item.offer_id)}
                            />
                            Selecionar
                          </label>
                        </div>
                        <p>{item.store || "Loja não informada"}</p>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">{fmtMoney(item.price)}</span>
                          <span className="meta-chip">{fmtInt(item.clicks || 0)} cliques</span>
                          <span className="meta-chip">{item.slug}</span>
                        </div>
                        <div className="list" style={{ marginTop: 14 }}>
                          {item.facebook_payload?.message ? (
                            <div>
                              <strong>Facebook</strong>
                              <p className="panel-subtitle">{item.facebook_payload.message.slice(0, 180)}...</p>
                            </div>
                          ) : null}
                          {item.instagram_payload?.caption ? (
                            <div>
                              <strong>Instagram</strong>
                              <p className="panel-subtitle">{item.instagram_payload.caption.slice(0, 180)}...</p>
                            </div>
                          ) : null}
                          {item.story_payload?.image_url ? (
                            <a className="tiny-button is-soft" href={item.story_payload.image_url} target="_blank" rel="noreferrer">
                              Abrir arte de story
                            </a>
                          ) : null}
                          <button className="tiny-button" type="button" onClick={() => dismissSocialOffer(item.offer_id)}>
                            Trocar por outra
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section className="panel" id="execucoes" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Execucoes recentes</h3>
                <p className="panel-subtitle">Historico operacional consolidado do backend Python.</p>
              </div>
            </div>
            {!snapshot?.recent_runs?.length ? (
              <div className="empty-state">Ainda nao ha execucoes registradas.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Tipo</th>
                      <th>Provider / Canal</th>
                      <th>Modo</th>
                      <th>Status</th>
                      <th>Solicitado</th>
                      <th>Processado</th>
                      <th>Inicio</th>
                      <th>Fim</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.recent_runs.map((run) => (
                      <tr key={run.id}>
                        <td>{run.tipo}</td>
                        <td>{run.provider || run.canal || "-"}</td>
                        <td>{run.modo || "-"}</td>
                        <td><span className={`badge ${run.status === "success" ? "is-success" : run.status === "error" ? "is-warning" : "is-neutral"}`}>{run.status}</span></td>
                        <td>{fmtInt(run.requested_count)}</td>
                        <td>{fmtInt(run.processed_count)}</td>
                        <td>{fmtDate(run.started_at)}</td>
                        <td>{fmtDate(run.finished_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="panel" style={{ marginTop: 18, marginBottom: 30 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Ofertas recentes</h3>
                <p className="panel-subtitle">Ultimos itens publicados no site para revisao rapida da vitrine.</p>
              </div>
            </div>
            {!snapshot?.recent_offers?.length ? (
              <div className="empty-state">Nenhuma oferta recente encontrada.</div>
            ) : (
              <div className="offer-list">
                {snapshot.recent_offers.map((offer) => (
                  <div className="offer-row" key={offer.id}>
                    <img className="offer-thumb" src={offer.imagem_url} alt={offer.titulo} />
                    <div style={{ flex: 1 }}>
                      <strong>{offer.titulo}</strong>
                      <small>{offer.loja} · {offer.categoria || "Geral"} · {fmtDate(offer.data_criacao)}</small>
                      <div className="offer-meta">
                        <span className="meta-chip">{fmtMoney(offer.preco)}</span>
                        <span className="meta-chip">{offer.slug}</span>
                      </div>
                    </div>
                    <a className="tiny-button is-soft" href={`/oferta.php?slug=${offer.slug}`} target="_blank" rel="noreferrer">Abrir oferta</a>
                  </div>
                ))}
              </div>
            )}
          </section>
        </main>
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
