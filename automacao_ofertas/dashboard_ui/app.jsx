const { useEffect, useMemo, useState } = React;

const IMPORT_OPTIONS = [
  { key: "mercadolivre", label: "Mercado Livre", note: "API/OAuth pronta para importar agora." },
  { key: "shopee", label: "Shopee", note: "Estrutura pronta; depende de credenciais/liberacao." },
  { key: "amazon", label: "Amazon", note: "Conector futuro para feed/API." },
  { key: "tiktok", label: "TikTok", note: "Conector futuro para catalogo social." },
];

const SOCIAL_OPTIONS = [
  { key: "facebook:feed", label: "Facebook Feed", note: "Posta direto na pagina do projeto." },
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
  const data = text ? JSON.parse(text) : {};
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
  return <div className={`toast ${toast.type === "error" ? "is-error" : "is-success"}`}>{toast.message}</div>;
}

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [socialPreview, setSocialPreview] = useState(null);
  const [importLoading, setImportLoading] = useState(false);
  const [socialLoading, setSocialLoading] = useState(false);
  const [runLoading, setRunLoading] = useState({ import: false, social: false, batch: false });
  const [jobRunLoading, setJobRunLoading] = useState({ import: false, social: false });
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [nowTs, setNowTs] = useState(Date.now());
  const [importForm, setImportForm] = useState({
    providers: ["mercadolivre"],
    previewProvider: "mercadolivre",
    keyword: "fone bluetooth",
    limit: 12,
    pages: 1,
  });
  const [socialForm, setSocialForm] = useState({ selected: "facebook:feed", limit: 3 });
  const [settingsForm, setSettingsForm] = useState({
    manager_username: "admin",
    manager_password: "",
    auto_import_enabled: true,
    auto_import_times: "06:30,12:30,18:30",
    auto_import_providers: ["mercadolivre"],
    auto_social_enabled: true,
    auto_social_times: "07:00,13:00,19:00",
    auto_social_platform: "facebook",
    auto_social_mode: "feed",
    auto_social_limit: 3,
  });

  const socialSplit = useMemo(() => {
    const [platform, mode] = socialForm.selected.split(":");
    return { platform, mode };
  }, [socialForm.selected]);

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
      auto_import_enabled: Boolean(settings.auto_import_enabled),
      auto_import_times: settings.auto_import_times || "",
      auto_import_providers: settings.auto_import_providers || ["mercadolivre"],
      auto_social_enabled: Boolean(settings.auto_social_enabled),
      auto_social_times: settings.auto_social_times || "",
      auto_social_platform: settings.auto_social_platform || "facebook",
      auto_social_mode: settings.auto_social_mode || "feed",
      auto_social_limit: Number(settings.auto_social_limit || 3),
    }));
  }, [snapshot?.settings]);

  async function loadSocialPreview(limit = socialForm.limit) {
    setSocialLoading(true);
    try {
      setSocialPreview(await fetchJson(`/social/meta/post-previews?limit=${limit}`));
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

  async function handleSocialRun() {
    setRunLoading((state) => ({ ...state, social: true }));
    try {
      const payload = { ...socialSplit, limit: Number(socialForm.limit) };
      const data = await fetchJson("/dashboard/api/social/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const errorCount = Number((data.errors || []).length);
      setToast({ type: errorCount ? "error" : "success", message: `Publicacao ${payload.platform}/${payload.mode}: ${data.count} concluido(s), ${errorCount} erro(s).` });
      await Promise.all([loadSnapshot(), loadSocialPreview(Number(socialForm.limit))]);
    } catch (error) {
      setToast({ type: "error", message: `Falha na publicacao social: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, social: false }));
    }
  }

  async function handleFacebookBatch() {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const data = await fetchJson("/social/meta/facebook/publish-batch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit: Number(socialForm.limit) }),
      });
      setToast({ type: "success", message: `Facebook em lote: ${data.count} publicacao(oes) concluida(s).` });
      await Promise.all([loadSnapshot(), loadSocialPreview(Number(socialForm.limit))]);
    } catch (error) {
      setToast({ type: "error", message: `Falha no lote do Facebook: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleRunJobNow(jobKey) {
    setJobRunLoading((state) => ({ ...state, [jobKey]: true }));
    try {
      const url = jobKey === "import" ? "/dashboard/api/automation/import/run-now" : "/dashboard/api/automation/social/run-now";
      const payload = jobKey === "import"
        ? { providers: settingsForm.auto_import_providers }
        : {
            platform: settingsForm.auto_social_platform,
            mode: settingsForm.auto_social_mode,
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
        auto_import_enabled: settingsForm.auto_import_enabled,
        auto_import_times: settingsForm.auto_import_times,
        auto_import_providers: settingsForm.auto_import_providers,
        auto_social_enabled: settingsForm.auto_social_enabled,
        auto_social_times: settingsForm.auto_social_times,
        auto_social_platform: settingsForm.auto_social_platform,
        auto_social_mode: settingsForm.auto_social_mode,
        auto_social_limit: Number(settingsForm.auto_social_limit || 1),
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

  const overview = snapshot?.overview || {};
  const charts = snapshot?.charts || {};
  const importStatus = snapshot?.status?.imports || [];
  const socialStatus = snapshot?.status?.social || [];
  const automation = snapshot?.automation || {};
  const manager = snapshot?.manager || {};

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
              {["import", "social"].map((jobKey) => {
                const job = automation?.jobs?.[jobKey] || {};
                return (
                  <article className={`status-card ${job.last_status === "error" ? "is-error" : job.last_status === "success" ? "is-success" : ""}`} key={jobKey}>
                    <div className="status-card-head">
                      <h4>{jobKey === "import" ? "Job de importacao" : "Job social"}</h4>
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
                  <input type="text" placeholder="Deixe vazio para manter a atual" value={settingsForm.manager_password} onChange={(e) => setSettingsForm((state) => ({ ...state, manager_password: e.target.value }))} />
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
                  <label>Auto social</label>
                  <label className="check-chip">
                    <input type="checkbox" checked={settingsForm.auto_social_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_enabled: e.target.checked }))} />
                    Ativar postagem automatica
                  </label>
                </div>
                <div className="field">
                  <label>Horarios do social</label>
                  <input type="text" value={settingsForm.auto_social_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_times: e.target.value }))} />
                  <small>Ex: 07:00,13:00,19:00</small>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Canal automatico</label>
                  <select value={settingsForm.auto_social_platform} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_platform: e.target.value }))}>
                    <option value="facebook">facebook</option>
                    <option value="instagram">instagram</option>
                  </select>
                </div>
                <div className="field">
                  <label>Modo automatico</label>
                  <select value={settingsForm.auto_social_mode} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_mode: e.target.value }))}>
                    <option value="feed">feed</option>
                    <option value="story">story</option>
                  </select>
                </div>
                <div className="field">
                  <label>Quantidade por rodada</label>
                  <input type="number" min="1" max="10" value={settingsForm.auto_social_limit} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_limit: Number(e.target.value || 1) }))} />
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
                        Incluir na execucao
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="surface">
              <h4>Preview pontual do importador</h4>
              <p>Valide termos, volume e qualidade antes de rodar a importacao real.</p>
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
                  <label>Paginas</label>
                  <input type="number" min="1" max="5" value={importForm.pages} onChange={(e) => setImportForm((state) => ({ ...state, pages: Number(e.target.value || 1) }))} />
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label>Execucao selecionada</label>
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
            </div>
          </section>

          <section className="panel" id="social" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Publicacao social</h3>
                <p className="panel-subtitle">Escolha canal, quantidade e formato para disparar feed, lote ou stories.</p>
              </div>
              <div className="provider-actions">
                <button className="button is-primary" onClick={handleSocialRun} disabled={runLoading.social}>
                  {runLoading.social ? "Publicando..." : "Rodar publicacao"}
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
            </div>

            <div className="surface">
              <h4>Execucao social</h4>
              <p>O preview abaixo usa as melhores ofertas atuais do banco e monta os payloads das APIs da Meta.</p>
              <div className="field-grid" style={{ marginTop: 16 }}>
                <div className="field">
                  <label>Canal selecionado</label>
                  <select value={socialForm.selected} onChange={(e) => setSocialForm((state) => ({ ...state, selected: e.target.value }))}>
                    {SOCIAL_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Quantidade</label>
                  <input type="number" min="1" max="10" value={socialForm.limit} onChange={(e) => setSocialForm((state) => ({ ...state, limit: Number(e.target.value || 1) }))} />
                </div>
                <div className="field">
                  <label>Split atual</label>
                  <div className="check-grid">
                    <span className="meta-chip">{socialSplit.platform}</span>
                    <span className="meta-chip">{socialSplit.mode}</span>
                  </div>
                </div>
              </div>

              <div style={{ marginTop: 18 }}>
                {socialLoading ? <div className="empty-state">Montando previews sociais...</div> : !socialPreview?.items?.length ? (
                  <div className="empty-state">Sem preview social carregado.</div>
                ) : (
                  <div className="preview-grid">
                    {socialPreview.items.slice(0, Number(socialForm.limit)).map((item) => (
                      <div className="surface" key={item.offer_id}>
                        <h4>{item.title}</h4>
                        <p>{item.store || "Loja nao informada"}</p>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">{fmtMoney(item.price)}</span>
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
