const { useEffect, useMemo, useState } = React;

const IMPORT_OPTIONS = [
  { key: "mercadolivre", label: "Mercado Livre", note: "API/OAuth pronta para importar agora." },
  { key: "shopee", label: "Shopee", note: "Estrutura pronta; depende de credenciais/liberacao." },
  { key: "amazon", label: "Amazon", note: "Conector futuro para feed/API." },
  { key: "tiktok", label: "TikTok", note: "Conector futuro para catalogo social." },
];

const IMPORT_BATCH_OPTIONS = [
  { value: "1", label: "1 produto" },
  { value: "5", label: "5 produtos" },
  { value: "10", label: "10 produtos" },
  { value: "50", label: "50 produtos" },
  { value: "100", label: "100 produtos" },
  { value: "all", label: "Todos" },
];

function parseImportRunLimit(value) {
  if (value === "all" || value === "" || value == null) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null;
  }
  return parsed;
}

function formatImportRunLimitLabel(value) {
  const parsed = parseImportRunLimit(value);
  return parsed == null ? "todos" : String(parsed);
}

const SOCIAL_OPTIONS = [
  { key: "facebook:feed", label: "Facebook Feed", note: "Posta direto na pagina do projeto." },
  { key: "facebook:reel", label: "Facebook Reel", note: "Gera um MP4 vertical e publica na pagina do Facebook." },
  { key: "both:reel_story", label: "Facebook + Instagram Reel + Story", note: "Publica reel e story nos dois canais para a mesma oferta." },
  { key: "both:reel", label: "Facebook + Instagram Reel", note: "Publica reel nos dois canais para a mesma oferta." },
  { key: "both:feed_story", label: "Facebook + Instagram Feed + Story", note: "Publica Facebook feed, Facebook story, Instagram feed e Instagram story na mesma execucao." },
  { key: "instagram:feed", label: "Instagram Feed", note: "Publica no feed do Instagram via Graph API." },
  { key: "instagram:reel", label: "Instagram Reel", note: "Usa video da Shopee quando existir e cai para MP4 gerado quando nao existir." },
  { key: "instagram:reel_story", label: "Instagram Reel + Story", note: "Publica reel e story juntos para a mesma oferta." },
  { key: "instagram:feed_story", label: "Instagram Feed + Story", note: "Publica o feed e o story juntos para a mesma oferta." },
  { key: "instagram:story", label: "Instagram Story", note: "Usa a arte gerada automaticamente." },
  { key: "whatsapp:web", label: "WhatsApp Web Local", note: "Modo gratis: monta a mensagem e abre o WhatsApp Web para envio manual." },
  { key: "whatsapp:group", label: "WhatsApp Grupo", note: "Prepara o lote e a mensagem para grupo; envio real entra na proxima etapa." },
];

const AUTO_SOCIAL_MODE_OPTIONS = {
  facebook: [
    { value: "feed", label: "Feed" },
    { value: "reel", label: "Reel" },
    { value: "reel_story", label: "Reel + Story" },
  ],
  instagram: [
    { value: "feed", label: "Feed" },
    { value: "reel", label: "Reel" },
    { value: "story", label: "Story" },
    { value: "reel_story", label: "Reel + Story" },
  ],
  both: [
    { value: "reel", label: "Reel" },
    { value: "reel_story", label: "Reel + Story" },
    { value: "feed_story", label: "Feed + Story" },
  ],
  whatsapp: [
    { value: "group", label: "Grupo" },
  ],
};

function normalizeAutoSocialAction(platform, mode) {
  const normalizedPlatform = AUTO_SOCIAL_MODE_OPTIONS[platform] ? platform : "facebook";
  const allowedModes = AUTO_SOCIAL_MODE_OPTIONS[normalizedPlatform] || AUTO_SOCIAL_MODE_OPTIONS.facebook;
  const preferredMode = normalizedPlatform === "both" && mode === "feed" ? "feed_story" : mode;
  const normalizedMode = allowedModes.some((item) => item.value === preferredMode) ? preferredMode : allowedModes[0].value;
  return { platform: normalizedPlatform, mode: normalizedMode };
}

const SOCIAL_STORE_FALLBACK_OPTIONS = ["Amazon", "Mercado Livre", "Shopee"];

const NAV_ITEMS = [
  { id: "painel", label: "Painel", note: "Resumo geral do projeto, métricas e atalhos rápidos." },
  { id: "configuracoes", label: "Configurações", note: "Automação, credenciais, horários e parâmetros do manager." },
  { id: "importadores", label: "Importadores", note: "Prévia, importação por página, arquivo e links manuais." },
  { id: "social", label: "Execução social", note: "Fila de Facebook e Instagram com seleção manual." },
  { id: "youtube_cortes", label: "Cortes YouTube", note: "Intake inicial para podcasts, briefing e pauta de cortes." },
  { id: "analytics", label: "Analytics", note: "Cliques, categorias, lojas e produtos mais fortes." },
  { id: "execucoes", label: "Execuções", note: "Histórico operacional consolidado do backend Python." },
];
NAV_ITEMS.splice(4, 0, { id: "crescimento", label: "Crescimento", note: "Radar de concorrentes, checklist oficial e fila manual para ganhar seguidores." });

function fmtMoney(value) {
  const numeric = Number(value || 0);
  return numeric.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}

function fmtWhatsappMoney(value) {
  return `R$ ${Number(value || 0).toFixed(2).replace(".", ",")}`;
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

function truncateText(value, max = 88) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
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

function humanizeImportError(message) {
  const text = String(message || "").trim();
  if (!text) return "Falha ao processar requisicao.";
  const lowered = text.toLowerCase();
  if (lowered.includes("mercado livre bloqueou") || lowered.includes("negative_traffic") || lowered.includes("forbidden")) {
    return "Mercado Livre bloqueado temporariamente. Aguarde alguns minutos e tente de novo.";
  }
  if (lowered.includes("amazon bloqueou")) {
    return "Amazon bloqueou a leitura automatica desta pagina agora.";
  }
  return text;
}

function humanizeSocialError(message) {
  const text = String(message || "").trim();
  const lowered = text.toLowerCase();
  if (!text) return "Falha ao publicar nas redes sociais.";
  if (lowered.includes("limite da api do instagram") || lowered.includes("número máximo de posts") || lowered.includes("numero maximo de posts") || lowered.includes("too many actions")) {
    return "Instagram bloqueado por cota da API de publicação. A conta atingiu o limite da janela de 24h e precisa aguardar liberar saldo.";
  }
  if (lowered.includes("token da meta expirou") || lowered.includes("\"code\":190") || lowered.includes("session has expired")) {
    return "Token da Meta expirado. Gere um novo token no Graph API Explorer e salve no manager para voltar a publicar.";
  }
  if (lowered.includes("meta_access_token")) {
    return "META_ACCESS_TOKEN ausente ou inválido no manager.";
  }
  return text;
}

function commerceMetaLines(item) {
  const lines = [];
  const discount = Number(item?.discount_percent || item?.desconto_percentual || 0);
  const pixPrice = Number(item?.pix_price ?? item?.preco_pix ?? 0);
  const otherPrice = Number(item?.other_price ?? item?.preco_outros_meios ?? 0);
  const installments = String(item?.installments || item?.parcelas_texto || "").trim();
  const shipping = String(item?.shipping || item?.frete_texto || "").trim();
  const promotion = String(item?.promotion_text || item?.promocao_texto || "").trim();
  const rating = Number(item?.rating ?? item?.avaliacao_nota ?? 0);
  const ratingCount = Number(item?.rating_count ?? item?.avaliacao_total ?? 0);

  if (discount > 0) lines.push(`${discount}% OFF`);
  if (pixPrice > 0) lines.push(`No Pix: ${fmtWhatsappMoney(pixPrice)}`);
  if (otherPrice > 0) lines.push(`Outros meios: ${fmtWhatsappMoney(otherPrice)}`);
  if (installments) lines.push(`Parcelamento: ${installments}`);
  if (shipping) lines.push(`Frete: ${shipping}`);
  if (rating > 0 && ratingCount > 0) lines.push(`Avaliacao: ${rating.toFixed(1).replace('.', ',')}/5 (${fmtInt(ratingCount)})`);
  else if (rating > 0) lines.push(`Avaliacao: ${rating.toFixed(1).replace('.', ',')}/5`);
  if (promotion) lines.push(`Promocao: ${promotion}`);
  return lines;
}

function commerceMetaChips(item) {
  return commerceMetaLines(item).map((line) => (line.length > 56 ? `${line.slice(0, 55)}...` : line));
}

function importPreviewExtraImages(item) {
  const primary = String(item?.image || "").trim();
  const gallery = Array.isArray(item?.image_urls) ? item.image_urls : [];
  const extras = [];
  for (const rawUrl of gallery) {
    const url = String(rawUrl || "").trim();
    if (!url || url === primary || extras.includes(url)) continue;
    extras.push(url);
  }
  return extras.slice(0, 6);
}

function renderImportPreviewGallery(item) {
  const extras = importPreviewExtraImages(item);
  if (!extras.length) return null;
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 12 }}>
      {extras.map((url, index) => (
        <a key={`${url}-${index}`} href={url} target="_blank" rel="noreferrer" title={`Imagem extra ${index + 1}`}>
          <img
            src={url}
            alt={`Imagem extra ${index + 1}`}
            style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 12, border: "1px solid rgba(15,23,42,.12)" }}
          />
        </a>
      ))}
    </div>
  );
}

function importGalleryStatusChip(item) {
  const provider = String(item?.provider || item?.store || "").toLowerCase();
  const imageCount = Array.isArray(item?.image_urls) ? item.image_urls.length : 0;
  if (!provider.includes("shopee")) return null;
  if (imageCount > 1) return `galeria profunda ok (${imageCount})`;
  if (imageCount === 1) return "1 imagem só";
  return "sem imagem detectada";
}

function hasDeepImportGallery(item) {
  const imageCount = Array.isArray(item?.image_urls)
    ? item.image_urls.filter((url) => String(url || "").trim()).length
    : 0;
  return imageCount > 1;
}

function whatsappCaptionForItem(item) {
    const lines = [];

    const title = String(item?.title || "").trim();
    const store = String(item?.store || "").trim();
    const coupon = String(item?.coupon || "").trim();
    const link = String(item?.cta_url || item?.offer_url || "").trim();

    if (title) lines.push(title);
    if (store) lines.push(store);

    if (Number(item?.price || 0) > 0) {
        lines.push(`Preco: ${fmtWhatsappMoney(item.price)}`);
    }

    if (Number(item?.old_price || 0) > 0) {
        lines.push(`De: ${fmtWhatsappMoney(item.old_price)}`);
    }

    if (coupon) {
        lines.push(`Cupom: ${coupon}`);
    }

    const metaLines = commerceMetaLines(item);
    if (Array.isArray(metaLines) && metaLines.length) {
        lines.push(...metaLines.filter(l => String(l || "").trim()));
    }

    if (link) {
        lines.push(`Link: ${link}`);
    }

    return lines.join("\n");
}

function whatsappPreviewImageUrl(item) {
  if (item?.generated_filename) return `/dashboard/api/stories/${encodeURIComponent(item.generated_filename)}`;
  return item?.image_url || item?.product_image_url || "";
}

function socialChannelPreviewTitle(platform, mode) {
  if (platform === "facebook" && mode === "feed") return "Preview Facebook Feed";
  if (platform === "facebook" && mode === "reel") return "Preview Facebook Reel";
  if (platform === "instagram" && mode === "feed") return "Preview Instagram Feed";
  if (platform === "instagram" && mode === "reel") return "Preview Instagram Reel";
  if (platform === "instagram" && mode === "story") return "Preview Instagram Story";
  if (platform === "instagram" && mode === "reel_story") return "Preview Instagram Reel + Story";
  if (platform === "instagram" && mode === "feed_story") return "Preview Instagram Feed + Story";
  if ((platform === "both" || platform === "facebook_instagram") && mode === "reel") return "Preview Facebook + Instagram Reel";
  if ((platform === "both" || platform === "facebook_instagram") && mode === "reel_story") return "Preview Facebook + Instagram Reel + Story";
  if ((platform === "both" || platform === "facebook_instagram") && mode === "feed") return "Preview Facebook + Instagram Feed";
  if ((platform === "both" || platform === "facebook_instagram") && mode === "feed_story") return "Preview Facebook + Instagram Feed + Story";
  return "Preview social";
}

function defaultPreviewSelection(item) {
  if (item?.import_allowed === false) return false;
  if (item?.provider === "mercadolivre" && item?.affiliate_detected === false) return false;
  if (item?.provider === "mercadolivre" && Number(item?.price || 0) <= 0) return false;
  return true;
}

function isImportablePreviewItem(item) {
  return defaultPreviewSelection(item);
}

function applyPreviewFieldUpdate(item, field, value) {
  const nextItem = { ...item, [field]: value };
  if (field === "price" && nextItem?.provider === "mercadolivre") {
    nextItem.selected = isImportablePreviewItem(nextItem);
  }
  return nextItem;
}

function matchesManualProvider(link, provider) {
  const value = String(link || "").toLowerCase();
  if (!provider || provider === "auto") return true;
  if (provider === "amazon") return value.includes("amazon.") || value.includes("amzn.to");
  if (provider === "mercadolivre") return value.includes("mercadolivre") || value.includes("mercadolibre");
  if (provider === "shopee") return value.includes("shopee");
  if (provider === "tiktok") return value.includes("tiktok");
  return true;
}

async function fetchJson(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    throw new Error("Nao foi possivel conectar ao backend agora.");
  }
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

function App() {
  const [snapshot, setSnapshot] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [manualLinkPreview, setManualLinkPreview] = useState(null);
  const [manualLinkDeepGalleryOnly, setManualLinkDeepGalleryOnly] = useState(false);
  const [manualLinkStatus, setManualLinkStatus] = useState(null);
  const [mlRelinkText, setMlRelinkText] = useState("");
  const [mlRelinkPreview, setMlRelinkPreview] = useState(null);
  const [socialPreview, setSocialPreview] = useState(null);
  const [socialRunPreview, setSocialRunPreview] = useState(null);
  const [socialHiddenIds, setSocialHiddenIds] = useState([]);
  const [socialCheckedIds, setSocialCheckedIds] = useState([]);
  const [socialSelectedItems, setSocialSelectedItems] = useState([]);
  const [importLoading, setImportLoading] = useState(false);
  const [manualLinkLoading, setManualLinkLoading] = useState(false);
  const [mlRelinkLoading, setMlRelinkLoading] = useState(false);
  const [socialLoading, setSocialLoading] = useState(false);
  const [runLoading, setRunLoading] = useState({ import: false, manualLinks: false, social: false, batch: false, deployStories: false, deploySite: false, deployAutomation: false });
  const [jobRunLoading, setJobRunLoading] = useState({ import: false, social: false, story: false });
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [nowTs, setNowTs] = useState(Date.now());
  const [importForm, setImportForm] = useState({
    providers: ["mercadolivre"],
    previewProvider: "mercadolivre",
    keyword: "fone bluetooth",
    limit: 12,
    pages: 1,
    runLimit: "5",
  });
  const [manualLinkText, setManualLinkText] = useState("");
  const [manualLinkProvider, setManualLinkProvider] = useState("auto");
  const [manualLinkRetry, setManualLinkRetry] = useState(null);
  const [manualPageForm, setManualPageForm] = useState({ provider: "mercadolivre", url: "", limit: 10 });
  const [manualPagePreview, setManualPagePreview] = useState(null);
  const [manualPageLoading, setManualPageLoading] = useState(false);
  const [fileImportProvider, setFileImportProvider] = useState("shopee");
  const [fileImportFile, setFileImportFile] = useState(null);
  const [fileImportPreview, setFileImportPreview] = useState(null);
  const [fileImportDeepGalleryOnly, setFileImportDeepGalleryOnly] = useState(false);
  const [fileImportLoading, setFileImportLoading] = useState(false);
  const [productQuery, setProductQuery] = useState("");
  const [productResults, setProductResults] = useState([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [productPage, setProductPage] = useState(1);
  const [productTotalPages, setProductTotalPages] = useState(1);
  const [productTotalCount, setProductTotalCount] = useState(0);
  const [productSaving, setProductSaving] = useState(false);
  const [productDeleting, setProductDeleting] = useState(false);
  const [selectedProductId, setSelectedProductId] = useState(null);
  const [productForm, setProductForm] = useState({
    titulo: "",
    slug: "",
    descricao: "",
    preco: "",
    preco_antigo: "",
    loja: "",
    url_afiliado: "",
    cupom: "",
    imagem_url: "",
    categoria: "",
    tags: "",
    destaque: false,
    ativo: true,
    expira_em: "",
  });

  function resetProductForm() {
    setProductForm({
      titulo: "",
      slug: "",
      descricao: "",
      preco: "",
      preco_antigo: "",
      loja: "",
      url_afiliado: "",
      cupom: "",
      imagem_url: "",
      categoria: "",
      tags: "",
      destaque: false,
      ativo: true,
      expira_em: "",
    });
  }

  function resetGrowthForm() {
    setGrowthForm({
      platform: "instagram",
      target_type: "profile",
      name: "",
      handle: "",
      url: "",
      niche: "",
      priority: "media",
      status: "novo",
      notes: "",
    });
  }
  function resetYoutubeChannelForm(overrides = {}) {
    setYoutubeChannelEditingId(null);
    setYoutubeChannelForm({
      name: "",
      handle: "",
      notes: "",
      avoid_terms: "",
      preferred_terms: "",
      viral_tone: "",
      client_id: snapshot?.settings?.youtube?.client_id || "",
      client_secret: "",
      redirect_uri: snapshot?.settings?.youtube?.redirect_uri || "",
      is_default: false,
      is_active: true,
      ...overrides,
    });
  }
  const [socialForm, setSocialForm] = useState({ selected: "both:reel_story", limit: 120, query: "" });
  const [socialFilters, setSocialFilters] = useState({ store: "all", category: "all" });
  const [activeSection, setActiveSection] = useState("painel");
  const [youtubeCutUrl, setYoutubeCutUrl] = useState("");
  const [youtubeCutMode, setYoutubeCutMode] = useState("short");
  const [youtubeShortSelectionStrategy, setYoutubeShortSelectionStrategy] = useState("openai_heuristica");
  const [youtubeCutAnalysis, setYoutubeCutAnalysis] = useState(null);
  const [youtubeCutLoading, setYoutubeCutLoading] = useState(false);
  const [youtubeCutsPhase2, setYoutubeCutsPhase2] = useState(null);
  const [youtubeCutsPhase2Loading, setYoutubeCutsPhase2Loading] = useState(false);
  const [growthRadar, setGrowthRadar] = useState(null);
  const [growthLoading, setGrowthLoading] = useState(false);
  const [growthSaving, setGrowthSaving] = useState(false);
  const [growthForm, setGrowthForm] = useState({
    platform: "instagram",
    target_type: "profile",
    name: "",
    handle: "",
    url: "",
    niche: "",
    priority: "media",
    status: "novo",
    notes: "",
  });
  const [youtubeOauthStatus, setYoutubeOauthStatus] = useState(null);
  const [youtubeOauthLoading, setYoutubeOauthLoading] = useState(false);
  const [youtubeChannelProfiles, setYoutubeChannelProfiles] = useState([]);
  const [youtubeChannelsLoading, setYoutubeChannelsLoading] = useState(false);
  const [youtubeChannelSaving, setYoutubeChannelSaving] = useState(false);
  const [youtubeChannelEditingId, setYoutubeChannelEditingId] = useState(null);
  const [youtubeSelectedChannelId, setYoutubeSelectedChannelId] = useState(null);
  const [youtubeChannelForm, setYoutubeChannelForm] = useState({
    name: "",
    handle: "",
    notes: "",
    avoid_terms: "",
    preferred_terms: "",
    viral_tone: "",
    client_id: "",
    client_secret: "",
    redirect_uri: "",
    is_default: false,
    is_active: true,
  });
  const [youtubeTrendIdeas, setYoutubeTrendIdeas] = useState(null);
  const [youtubeTrendIdeasLoading, setYoutubeTrendIdeasLoading] = useState(false);
  const [youtubePublishingCutId, setYoutubePublishingCutId] = useState(null);
  const [whatsappGroups, setWhatsappGroups] = useState([]);
  const [whatsappGroupsLoading, setWhatsappGroupsLoading] = useState(false);
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
    auto_social_mode: "reel_story",
    auto_social_limit: 3,
    auto_social_repeat_block_minutes: 1440,
    auto_story_enabled: false,
    auto_story_times: "07:05,13:05,19:05",
    auto_story_platform: "instagram",
    auto_story_limit: 1,
    whatsapp_api_base_url: "",
    whatsapp_api_token: "",
    whatsapp_group_target: "",
    sftp_host: "",
    sftp_port: 22,
    sftp_username: "",
    sftp_password: "",
    sftp_remote_path: "",
    stories_public_base_url: "",
    youtube_client_id: "",
    youtube_client_secret: "",
    youtube_redirect_uri: "",
    ytdlp_cookies_from_browser: "",
    ytdlp_cookies_file: "",
  });

  const socialSplit = useMemo(() => {
    const [platform, mode] = socialForm.selected.split(":");
    return { platform, mode };
  }, [socialForm.selected]);
  const isWhatsappGroupSelected = socialSplit.platform === "whatsapp" && socialSplit.mode === "group";
  const isWhatsappWebSelected = socialSplit.platform === "whatsapp" && socialSplit.mode === "web";
  const normalizedAutoSocial = useMemo(
    () => normalizeAutoSocialAction(settingsForm.auto_social_platform, settingsForm.auto_social_mode),
    [settingsForm.auto_social_platform, settingsForm.auto_social_mode]
  );
  const autoSocialModeOptions = AUTO_SOCIAL_MODE_OPTIONS[normalizedAutoSocial.platform] || AUTO_SOCIAL_MODE_OPTIONS.facebook;
  const isCombinedStoryAuto = normalizedAutoSocial.platform === "both" && ["reel_story", "feed_story"].includes(normalizedAutoSocial.mode);

  const socialCandidates = useMemo(() => socialPreview?.items || [], [socialPreview]);
  const socialStoreOptions = useMemo(() => {
    const values = [...new Set([...SOCIAL_STORE_FALLBACK_OPTIONS, ...socialCandidates.map((item) => item.store).filter(Boolean)])];
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
      const query = (socialForm.query || "").trim().toLowerCase();
      const haystack = [item.title, item.store, item.category, item.slug]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      const matchQuery = !query || haystack.includes(query);
      return matchStore && matchCategory && matchQuery;
    }),
    [socialCandidates, socialFilters, socialForm.query]
  );
  const socialQueue = useMemo(
    () => filteredSocialCandidates.filter((item) => !socialHiddenIds.includes(item.offer_id)),
    [filteredSocialCandidates, socialHiddenIds]
  );
  const socialPinnedQueue = useMemo(
    () => socialSelectedItems.filter((item) => item && socialCheckedIds.includes(item.offer_id)),
    [socialSelectedItems, socialCheckedIds]
  );
  const socialVisibleQueue = useMemo(() => {
    const selectedIds = new Set(socialPinnedQueue.map((item) => item.offer_id));
    return [...socialPinnedQueue, ...socialQueue.filter((item) => !selectedIds.has(item.offer_id))];
  }, [socialPinnedQueue, socialQueue]);
  const whatsappPreviewItems = useMemo(() => {
    if (
      socialRunPreview?.platform === "whatsapp" &&
      socialRunPreview?.mode === socialSplit.mode &&
      Array.isArray(socialRunPreview?.items) &&
      socialRunPreview.items.length
    ) {
      return socialRunPreview.items.slice(0, 3);
    }
    if (socialSplit.platform === "whatsapp" && socialPinnedQueue.length) {
      return socialPinnedQueue.slice(0, 3).map((item) => ({
        offer_id: item.offer_id,
        slug: item.slug,
        title: item.title,
        store: item.store,
        category: item.category,
        price: item.price,
        old_price: item.old_price,
        coupon: item.coupon,
        image_url: item.image_url,
        product_image_url: item.image_url,
        cta_url: item.cta_url || item.url_afiliado || item.offer_url,
        offer_url: item.offer_url,
      }));
    }
    return [];
  }, [socialPinnedQueue, socialRunPreview, socialSplit.mode, socialSplit.platform]);
  const whatsappBatchText = useMemo(
    () => whatsappPreviewItems.map((item, index) => `Mensagem ${index + 1}\n${whatsappCaptionForItem(item)}`).join("\n\n--------------------\n\n"),
    [whatsappPreviewItems]
  );
  const hasInvalidSelectedManualMl = useMemo(
    () => (manualLinkPreview?.items || []).some((item) => item.selected && item.provider === "mercadolivre" && Number(item.price || 0) <= 0),
    [manualLinkPreview]
  );
  const hasInvalidSelectedFileMl = useMemo(
    () => (fileImportPreview?.items || []).some((item) => item.selected && item.provider === "mercadolivre" && Number(item.price || 0) <= 0),
    [fileImportPreview]
  );
  const manualLinkDeepGalleryCount = useMemo(
    () => (manualLinkPreview?.items || []).filter((item) => hasDeepImportGallery(item)).length,
    [manualLinkPreview]
  );
  const visibleManualLinkPreviewItems = useMemo(
    () => (manualLinkPreview?.items || []).flatMap((item, originalIndex) => {
      if (manualLinkDeepGalleryOnly && !hasDeepImportGallery(item)) return [];
      return [{ item, originalIndex }];
    }),
    [manualLinkDeepGalleryOnly, manualLinkPreview]
  );
  const fileImportDeepGalleryCount = useMemo(
    () => (fileImportPreview?.items || []).filter((item) => hasDeepImportGallery(item)).length,
    [fileImportPreview]
  );
  const visibleFileImportPreviewItems = useMemo(
    () => (fileImportPreview?.items || []).flatMap((item, originalIndex) => {
      if (fileImportDeepGalleryOnly && !hasDeepImportGallery(item)) return [];
      return [{ item, originalIndex }];
    }),
    [fileImportDeepGalleryOnly, fileImportPreview]
  );
  const siteBaseUrl = snapshot?.site_base_url || "";

  function siteOfferUrl(slug) {
    if (!slug) return "#";
    return siteBaseUrl ? `${siteBaseUrl}/oferta.php?slug=${encodeURIComponent(slug)}` : `/oferta.php?slug=${encodeURIComponent(slug)}`;
  }

  function siteStoreUrl(slug) {
    if (!slug) return "#";
    return siteBaseUrl ? `${siteBaseUrl}/oferta.php?slug=${encodeURIComponent(slug)}&go=1` : `/oferta.php?slug=${encodeURIComponent(slug)}&go=1`;
  }

  function toDatetimeLocalValue(value) {
    if (!value) return "";
    return String(value).replace(" ", "T").slice(0, 16);
  }

  function selectProduct(item) {
    if (!item) return;
    setSelectedProductId(item.id);
    setProductForm({
      titulo: item.titulo || "",
      slug: item.slug || "",
      descricao: item.descricao || "",
      preco: item.preco ?? "",
      preco_antigo: item.preco_antigo ?? "",
      loja: item.loja || "",
      url_afiliado: item.url_afiliado || "",
      cupom: item.cupom || "",
      imagem_url: item.imagem_url || "",
      categoria: item.categoria || "",
      tags: item.tags || "",
      destaque: Boolean(item.destaque),
      ativo: Boolean(item.ativo),
      expira_em: toDatetimeLocalValue(item.expira_em),
    });
  }

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
    const normalizedAuto = normalizeAutoSocialAction(settings.auto_social_platform || "facebook", settings.auto_social_mode || "feed");
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
      auto_social_platform: normalizedAuto.platform,
      auto_social_mode: normalizedAuto.mode,
      auto_social_limit: Number(settings.auto_social_limit || 3),
      auto_social_repeat_block_minutes: Number(settings.auto_social_repeat_block_minutes || 1440),
      auto_story_enabled: Boolean(settings.auto_story_enabled),
      auto_story_times: settings.auto_story_times || "",
      auto_story_platform: settings.auto_story_platform || "instagram",
      auto_story_limit: Number(settings.auto_story_limit || 1),
      whatsapp_api_base_url: settings.whatsapp?.api_base_url || "",
      whatsapp_api_token: "",
      whatsapp_group_target: settings.whatsapp?.group_target || "",
      sftp_host: settings.sftp?.host || "",
      sftp_port: Number(settings.sftp?.port || 22),
      sftp_username: settings.sftp?.username || "",
      sftp_password: "",
      sftp_remote_path: settings.sftp?.remote_path || "",
      stories_public_base_url: settings.sftp?.stories_public_base_url || "",
      youtube_client_id: settings.youtube?.client_id || "",
      youtube_client_secret: "",
      youtube_redirect_uri: settings.youtube?.redirect_uri || "",
      ytdlp_cookies_from_browser: settings.youtube?.cookies_from_browser || "",
      ytdlp_cookies_file: settings.youtube?.cookies_file || "",
    }));
    const channels = settings.youtube?.channels || [];
    setYoutubeChannelProfiles(channels);
    if (!youtubeSelectedChannelId && channels.length) {
      const preferred = channels.find((item) => item.is_default) || channels[0];
      setYoutubeSelectedChannelId(Number(preferred.id));
    }
  }, [snapshot?.settings]);

  useEffect(() => {
    if (activeSection === "youtube_cortes") {
      loadYoutubeChannels();
      loadYoutubeOauthStatus();
    }
    if (activeSection === "crescimento") {
      loadGrowthRadar();
    }
  }, [activeSection]);

  useEffect(() => {
    if (activeSection === "youtube_cortes") {
      loadYoutubeOauthStatus(youtubeSelectedChannelId);
    }
  }, [youtubeSelectedChannelId]);

  async function loadSocialPreview(limit = socialForm.limit, query = socialForm.query) {
    setSocialLoading(true);
    try {
      const params = new URLSearchParams({
        limit: String(Math.max(36, Number(limit || 120))),
      });
      const normalizedQuery = String(query || "").trim();
      if (normalizedQuery) params.set("q", normalizedQuery);
      if (socialFilters.store && socialFilters.store !== "all") params.set("store", socialFilters.store);
      setSocialPreview(await fetchJson(`/social/meta/post-previews?${params.toString()}`));
    } catch (error) {
      setToast({ type: "error", message: `Falha ao montar previews sociais: ${error.message}` });
    } finally {
      setSocialLoading(false);
    }
  }

  useEffect(() => {
    loadSnapshot();
    loadSocialPreview();
    handleProductSearch("", 1);
  }, []);

  useEffect(() => {
    loadSocialPreview(socialForm.limit, socialForm.query);
  }, [socialFilters.store]);

  useEffect(() => {
    setSocialRunPreview(null);
  }, [socialForm.selected]);

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
    setSocialSelectedItems((current) => {
      if (!current.length) return current;
      const nextById = new Map(current.map((item) => [item.offer_id, item]));
      socialCandidates.forEach((item) => {
        if (nextById.has(item.offer_id)) {
          nextById.set(item.offer_id, item);
        }
      });
      return socialCheckedIds.map((id) => nextById.get(id)).filter(Boolean);
    });
  }, [socialCandidates, socialCheckedIds]);

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
      const limit = parseImportRunLimit(importForm.runLimit);
      const data = await fetchJson("/dashboard/api/import/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ providers: importForm.providers, limit }),
      });
      const processed = (data.items || []).reduce((sum, item) => sum + Number(item.processed || item.imported || 0), 0);
      const created = (data.items || []).reduce((sum, item) => sum + Number(item.created || 0), 0);
      const updated = (data.items || []).reduce((sum, item) => sum + Number(item.updated || 0), 0);
      const selected = (data.items || []).reduce((sum, item) => sum + Number(item.offers_selected || 0), 0);
      setToast({
        type: data.error ? "error" : "success",
        message: `Importacao concluida: lote ${formatImportRunLimitLabel(importForm.runLimit)}, ${selected} selecionado(s), ${processed} processado(s), ${created} criado(s), ${updated} atualizado(s), ${data.error} erro(s).`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha na importacao: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, import: false }));
    }
  }

  function parseLinksText(value) {
    return String(value || "")
      .split(/\r?\n|,|;/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function parseManualLinks() {
    return parseLinksText(manualLinkText).filter((link) => matchesManualProvider(link, manualLinkProvider));
  }

  function selectValidFileItems() {
    setFileImportPreview((current) => {
      if (!current?.items?.length) return current;
      const items = current.items.map((item) => ({ ...item, selected: isImportablePreviewItem(item) }));
      return { ...current, items };
    });
  }

  function selectValidManualItems() {
    setManualLinkPreview((current) => {
      if (!current?.items?.length) return current;
      const items = current.items.map((item) => ({ ...item, selected: isImportablePreviewItem(item) }));
      return { ...current, items };
    });
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
      setManualLinkDeepGalleryOnly(false);
      setManualLinkPreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: defaultPreviewSelection(item) })),
      });
      const blockedMlCount = (data.items || []).filter((item) => item.provider === "mercadolivre" && item.affiliate_detected === false).length;
      setManualLinkStatus({
        type: blockedMlCount ? "info" : "success",
        message: blockedMlCount
          ? `${data.count} link(s) analisado(s). ${blockedMlCount} item(ns) do Mercado Livre ficaram desmarcados porque nao trazem link oficial de afiliado.`
          : `${data.count} link(s) analisado(s) com sucesso. Preview pronto para revisar e importar.`,
      });
      setToast({ type: blockedMlCount ? "info" : "success", message: blockedMlCount ? `${blockedMlCount} item(ns) do Mercado Livre exigem link oficial.` : `${data.count} link(s) analisado(s).` });
    } catch (error) {
      if (!skipRetrySchedule && retryAttempt === 1) {
        setManualLinkRetry({ active: true, ready: false, attempt: retryAttempt, secondsLeft: 30 });
        setManualLinkStatus({
          type: "retry",
          message: `A primeira tentativa falhou. O sistema vai tentar de novo em 30s. Erro atual: ${humanizeImportError(error.message)}`,
        });
        setToast({ type: "info", message: "Primeira tentativa falhou. Nova tentativa automatica agendada para 30s." });
      } else {
        setManualLinkStatus({
          type: "error",
          message: `Preview manual por link falhou mesmo apos a nova tentativa. Detalhe: ${humanizeImportError(error.message)}`,
        });
        setToast({ type: "error", message: `Preview manual por link falhou: ${humanizeImportError(error.message)}` });
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
      setFileImportDeepGalleryOnly(false);
      setFileImportPreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: defaultPreviewSelection(item) })),
      });
      const blockedMlCount = (data.items || []).filter((item) => item.provider === "mercadolivre" && item.affiliate_detected === false).length;
      setToast({
        type: blockedMlCount ? "info" : "success",
        message: blockedMlCount
          ? `${data.count} item(ns) lido(s). ${blockedMlCount} do Mercado Livre ficaram desmarcados por falta de link oficial.`
          : `${data.count} item(ns) carregado(s) do arquivo ${data.filename || ""}.`,
      });
    } catch (error) {
      setToast({ type: "error", message: `Preview por arquivo falhou: ${humanizeImportError(error.message)}` });
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

  async function handleManualPagePreview() {
    const url = String(manualPageForm.url || "").trim();
    if (!url) {
      setToast({ type: "error", message: "Informe a URL da pagina do Mercado Livre." });
      return;
    }
    setManualPageLoading(true);
    try {
      const data = await fetchJson("/dashboard/api/import/manual-page/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: manualPageForm.provider, url, limit: Number(manualPageForm.limit || 10) }),
      });
      setManualPagePreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: true })),
      });
      setToast({ type: "success", message: `${data.count} item(ns) carregado(s) da pagina de ${manualPageForm.provider === "amazon" ? "Amazon" : "Mercado Livre"}.` });
    } catch (error) {
      setToast({ type: "error", message: `Preview da pagina ${manualPageForm.provider === "amazon" ? "Amazon" : "Mercado Livre"} falhou: ${humanizeImportError(error.message)}` });
    } finally {
      setManualPageLoading(false);
    }
  }

  async function handleProductSearch(query = productQuery, page = 1) {
    setProductsLoading(true);
    try {
      const normalizedQuery = String(query || "").trim();
      const normalizedPage = Math.max(1, Number(page || 1));
      const params = new URLSearchParams({
        q: normalizedQuery,
        limit: "10",
        page: String(normalizedPage),
      });
      const data = await fetchJson(`/dashboard/api/offers?${params.toString()}`);
      setProductResults(data.items || []);
      setProductPage(Number(data.page || normalizedPage));
      setProductTotalPages(Math.max(1, Number(data.pages || 1)));
      setProductTotalCount(Number(data.total || 0));
      if ((data.items || []).length && !(data.items || []).some((item) => item.id === selectedProductId)) {
        selectProduct(data.items[0]);
      }
    } catch (error) {
      setToast({ type: "error", message: `Busca de produtos falhou: ${error.message}` });
    } finally {
      setProductsLoading(false);
    }
  }

  async function handleProductSave() {
    if (!selectedProductId) {
      setToast({ type: "error", message: "Selecione um produto para editar." });
      return;
    }
    setProductSaving(true);
    try {
      const data = await fetchJson(`/dashboard/api/offers/${selectedProductId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(productForm),
      });
      setToast({ type: "success", message: "Produto atualizado no dashboard." });
      const savedItem = data.item;
      setProductResults((current) => {
        const next = current.map((item) => (item.id === savedItem.id ? savedItem : item));
        return next.some((item) => item.id === savedItem.id) ? next : [savedItem, ...next];
      });
      selectProduct(savedItem);
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao salvar produto: ${error.message}` });
    } finally {
      setProductSaving(false);
    }
  }

  async function handleYoutubeCutsAnalyze() {
    const normalizedUrl = String(youtubeCutUrl || "").trim();
    if (!normalizedUrl) {
      setToast({ type: "error", message: "Cole um link do YouTube para analisar." });
      return;
    }

    setYoutubeCutLoading(true);
    try {
      const data = await fetchJson("/dashboard/api/youtube/cuts/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: normalizedUrl }),
      });
      setYoutubeCutAnalysis(data);
      const suggestionCount = youtubeCutMode === "long" ? Number(data?.long_suggestions?.length || 0) : Number(data?.suggestions?.length || 0);
      setToast({ type: "success", message: `${suggestionCount} sugestao(oes) iniciais de ${youtubeCutMode === "long" ? "corte longo" : "short"} montadas.` });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao analisar vídeo do YouTube: ${error.message}` });
    } finally {
      setYoutubeCutLoading(false);
    }
  }

  async function handleYoutubeCutsProcess() {
    const normalizedUrl = String(youtubeCutUrl || "").trim();
    if (!normalizedUrl) {
      setToast({ type: "error", message: "Cole um link do YouTube para processar." });
      return;
    }

    setYoutubeCutsPhase2Loading(true);
    try {
      const data = await fetchJson("/dashboard/api/youtube/cuts/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: normalizedUrl,
          limit: youtubeCutMode === "long" ? 3 : 5,
          mode: youtubeCutMode,
          selection_strategy: youtubeShortSelectionStrategy,
          channel_profile_id: youtubeSelectedChannelId || null,
        }),
      });
      setYoutubeCutsPhase2(data);
      setYoutubeOauthStatus(data.youtube_auth || null);
      setToast({ type: "success", message: `${Number(data?.cuts?.length || 0)} ${youtubeCutMode === "long" ? "corte(s) longos" : "short(s)"} gerado(s).` });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao gerar cortes: ${error.message}` });
    } finally {
      setYoutubeCutsPhase2Loading(false);
    }
  }

  async function loadYoutubeChannels() {
    setYoutubeChannelsLoading(true);
    try {
      const data = await fetchJson("/dashboard/api/youtube/channels");
      const profiles = data?.profiles || [];
      setYoutubeChannelProfiles(profiles);
      setYoutubeSelectedChannelId((current) => {
        if (current && profiles.some((item) => Number(item.id) === Number(current))) return current;
        const preferred = profiles.find((item) => item.is_default) || profiles[0];
        return preferred ? Number(preferred.id) : null;
      });
    } catch (error) {
      setYoutubeChannelProfiles([]);
      setToast({ type: "error", message: `Falha ao carregar canais do YouTube: ${error.message}` });
    } finally {
      setYoutubeChannelsLoading(false);
    }
  }

  async function handleYoutubeChannelSave() {
    const normalizedName = String(youtubeChannelForm.name || "").trim();
    if (!normalizedName) {
      setToast({ type: "error", message: "Informe um nome para o perfil do canal." });
      return;
    }
    setYoutubeChannelSaving(true);
    try {
      const url = youtubeChannelEditingId ? `/dashboard/api/youtube/channels/${youtubeChannelEditingId}` : "/dashboard/api/youtube/channels";
      const data = await fetchJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(youtubeChannelForm),
      });
      await loadYoutubeChannels();
      const profileId = Number(data?.profile?.id || 0);
      if (profileId) {
        setYoutubeSelectedChannelId(profileId);
      }
      resetYoutubeChannelForm();
      setToast({ type: "success", message: youtubeChannelEditingId ? "Perfil do canal atualizado." : "Perfil do canal criado." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao salvar perfil do canal: ${error.message}` });
    } finally {
      setYoutubeChannelSaving(false);
    }
  }

  async function handleYoutubeChannelDelete(profileId) {
    if (!profileId) return;
    if (!window.confirm("Remover este perfil de canal do YouTube?")) return;
    try {
      await fetchJson(`/dashboard/api/youtube/channels/${profileId}`, { method: "DELETE" });
      if (Number(youtubeSelectedChannelId) === Number(profileId)) {
        setYoutubeSelectedChannelId(null);
      }
      await loadYoutubeChannels();
      setToast({ type: "success", message: "Perfil do canal removido." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao remover perfil do canal: ${error.message}` });
    }
  }

  async function loadYoutubeOauthStatus(channelId = youtubeSelectedChannelId) {
    setYoutubeOauthLoading(true);
    try {
      const suffix = channelId ? `?channel_profile_id=${encodeURIComponent(channelId)}` : "";
      const data = await fetchJson(`/dashboard/api/youtube/oauth/status${suffix}`);
      setYoutubeOauthStatus(data.youtube_auth || null);
    } catch (error) {
      setYoutubeOauthStatus(null);
      setToast({ type: "error", message: `Falha ao ler status do YouTube: ${error.message}` });
    } finally {
      setYoutubeOauthLoading(false);
    }
  }

  async function handleYoutubeConnect() {
    try {
      const suffix = youtubeSelectedChannelId ? `?channel_profile_id=${encodeURIComponent(youtubeSelectedChannelId)}` : "";
      const data = await fetchJson(`/dashboard/api/youtube/oauth/url${suffix}`);
      window.open(data.auth_url, "_blank", "noopener,noreferrer");
      setToast({ type: "info", message: "Abrimos a autorizacao do Google em uma nova aba." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao iniciar OAuth do YouTube: ${error.message}` });
    }
  }

  async function handleLoadYoutubeTrendIdeas() {
    setYoutubeTrendIdeasLoading(true);
    try {
      const params = new URLSearchParams({
        recent_limit: "4",
        videos_per_topic: "4",
      });
      if (youtubeSelectedChannelId) params.set("channel_profile_id", String(youtubeSelectedChannelId));
      const data = await fetchJson(`/dashboard/api/youtube/trends/themes?${params.toString()}`);
      setYoutubeTrendIdeas(data);
      const ideaCount = Number(data?.ideas?.length || 0);
      setToast({
        type: ideaCount ? "success" : "info",
        message: ideaCount
          ? `${ideaCount} canal(is) com videos recentes para corte carregados das suas inscricoes.`
          : "Nao encontrei videos de podcast/guerra/politica nas inscricoes nas ultimas 48 horas.",
      });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao buscar temas em alta: ${error.message}` });
    } finally {
      setYoutubeTrendIdeasLoading(false);
    }
  }

  async function loadGrowthRadar() {
    setGrowthLoading(true);
    try {
      const data = await fetchJson("/dashboard/api/growth/radar");
      setGrowthRadar(data);
    } catch (error) {
      setToast({ type: "error", message: `Falha ao carregar radar de crescimento: ${error.message}` });
    } finally {
      setGrowthLoading(false);
    }
  }

  async function handleGrowthTargetSave() {
    const normalizedName = String(growthForm.name || "").trim();
    const normalizedUrl = String(growthForm.url || "").trim();
    if (!normalizedName || !normalizedUrl) {
      setToast({ type: "error", message: "Informe pelo menos nome e URL do perfil/pagina." });
      return;
    }

    setGrowthSaving(true);
    try {
      await fetchJson("/dashboard/api/growth/targets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(growthForm),
      });
      resetGrowthForm();
      await loadGrowthRadar();
      setToast({ type: "success", message: "Perfil/pagina adicionado ao radar de crescimento." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao salvar alvo de crescimento: ${error.message}` });
    } finally {
      setGrowthSaving(false);
    }
  }

  async function updateGrowthTarget(target, updates) {
    if (!target?.id) return;
    try {
      await fetchJson(`/dashboard/api/growth/targets/${target.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: updates.platform || target.platform,
          target_type: updates.target_type || target.target_type,
          name: updates.name ?? target.name,
          handle: updates.handle ?? target.handle,
          url: updates.url || target.url,
          niche: updates.niche ?? target.niche,
          priority: updates.priority || target.priority,
          status: updates.status || target.status,
          notes: updates.notes ?? target.notes,
          last_checked_at: updates.last_checked_at ?? target.last_checked_at,
        }),
      });
      await loadGrowthRadar();
      if (updates.status) {
        setToast({ type: "success", message: `Status atualizado para ${updates.status}.` });
      }
    } catch (error) {
      setToast({ type: "error", message: `Falha ao atualizar alvo: ${error.message}` });
    }
  }

  async function removeGrowthTarget(targetId) {
    if (!targetId) return;
    try {
      await fetchJson(`/dashboard/api/growth/targets/${targetId}`, { method: "DELETE" });
      await loadGrowthRadar();
      setToast({ type: "success", message: "Alvo removido do radar de crescimento." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao remover alvo: ${error.message}` });
    }
  }

  function updateYoutubeCutDraft(cutId, field, value) {
    setYoutubeCutsPhase2((current) => {
      if (!current?.cuts?.length) return current;
      const cuts = current.cuts.map((item) => {
        if (Number(item.cut_id) !== Number(cutId)) return item;
        return {
          ...item,
          publish_draft: {
            ...(item.publish_draft || {}),
            [field]: value,
          },
        };
      });
      return { ...current, cuts };
    });
  }

  async function handleYoutubeCutPublish(item) {
    const draft = item?.publish_draft || {};
    if (!item?.job_id || !item?.cut_id) {
      setToast({ type: "error", message: "Corte invalido para publicar no YouTube." });
      return;
    }
    setYoutubePublishingCutId(Number(item.cut_id));
    try {
      const data = await fetchJson("/dashboard/api/youtube/cuts/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: item.job_id,
          cut_id: Number(item.cut_id),
          title: draft.title || item.title,
          description: draft.description || item.caption_draft || "",
          privacy_status: draft.privacy_status || "public",
          mode: item.mode || draft.mode || youtubeCutMode,
          channel_profile_id: draft.channel_profile_id || youtubeSelectedChannelId || null,
        }),
      });
      const uploadedThumbnail = Boolean(data.thumbnail_result && !data.thumbnail_error);
      const isLong = (item.mode || draft.mode) === "long";
      setToast({
        type: "success",
        message: `${isLong ? "Video" : "Short"} publicado no YouTube${data.youtube_video_id ? ` (${data.youtube_video_id})` : ""}${isLong && uploadedThumbnail ? " com thumbnail aplicada." : "."}`,
      });
      setYoutubeCutsPhase2((current) => {
        if (!current?.cuts?.length) return current;
        const cuts = current.cuts.map((entry) => {
          if (Number(entry.cut_id) !== Number(item.cut_id)) return entry;
          return {
            ...entry,
            publish_result: data,
            status: "published",
          };
        });
        return { ...current, cuts };
      });
      await loadYoutubeOauthStatus(youtubeSelectedChannelId);
    } catch (error) {
      setToast({ type: "error", message: `Falha ao publicar no YouTube: ${error.message}` });
    } finally {
      setYoutubePublishingCutId(null);
    }
  }

  async function handleProductDelete() {
    if (!selectedProductId) {
      setToast({ type: "error", message: "Selecione um produto para excluir." });
      return;
    }
    const title = String(productForm.titulo || "").trim() || `#${selectedProductId}`;
    if (!window.confirm(`Excluir o produto "${title}"? Essa acao nao pode ser desfeita.`)) {
      return;
    }
    setProductDeleting(true);
    try {
      const data = await fetchJson(`/dashboard/api/offers/${selectedProductId}`, {
        method: "DELETE",
      });
      setToast({ type: "success", message: `Produto excluido: ${data.deleted?.titulo || title}.` });
      setProductResults((current) => current.filter((item) => item.id !== selectedProductId));
      setSelectedProductId(null);
      resetProductForm();
      await handleProductSearch(productQuery, productPage);
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao excluir produto: ${error.message}` });
    } finally {
      setProductDeleting(false);
    }
  }

  async function handleMercadoLivreExistingPreview() {
    setMlRelinkLoading(true);
    try {
      const links = parseLinksText(mlRelinkText);
      const data = await fetchJson("/dashboard/api/import/store/mercadolivre/relink-existing/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ links }),
      });
      setMlRelinkPreview({
        ...data,
        items: (data.items || []).map((item) => ({ ...item, selected: Boolean(item.match_found) })),
      });
      const matched = (data.items || []).filter((item) => item.match_found).length;
      const unmatched = (data.items || []).length - matched;
      setToast({ type: unmatched ? "info" : "success", message: `ML relink: ${matched} link(s) com match, ${unmatched} sem match.` });
    } catch (error) {
      setToast({ type: "error", message: `Preview de relink do Mercado Livre falhou: ${humanizeImportError(error.message)}` });
    } finally {
      setMlRelinkLoading(false);
    }
  }

  async function handleMercadoLivreExistingRun() {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const items = (mlRelinkPreview?.items || []).filter((item) => item.selected);
      if (!items.length) {
        throw new Error("Selecione ao menos um link oficial do Mercado Livre com match encontrado.");
      }
      const data = await fetchJson("/dashboard/api/import/store/mercadolivre/relink-existing/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      setToast({
        type: "success",
        message: `ML vinculado: ${data.processed} processado(s), ${data.updated} atualizado(s), ${data.reactivated} reativado(s), ${data.invalid} invalido(s), ${data.skipped} ignorado(s).`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Vinculo em lote do Mercado Livre falhou: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleManualPageImport() {
    setRunLoading((state) => ({ ...state, manualLinks: true }));
    try {
      const items = (manualPagePreview?.items || []).filter((item) => item.selected);
      if (!items.length) {
        throw new Error("Selecione ao menos um item da pagina para importar.");
      }
      const data = await fetchJson("/dashboard/api/import/manual-links/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items }),
      });
      setToast({ type: "success", message: `Importacao da pagina: ${data.processed} processado(s), ${data.created} criado(s), ${data.updated} atualizado(s).` });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Importacao da pagina falhou: ${error.message}` });
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

  async function handleAmazonRepairReactivate(onlyInactive = true) {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const data = await fetchJson("/dashboard/api/import/store/amazon/repair-affiliate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ only_inactive: onlyInactive }),
      });
      setToast({
        type: "success",
        message: `Amazon corrigida: ${data.processed} verificado(s), ${data.updated} atualizado(s), ${data.reactivated} reativado(s), ${data.invalid} invalido(s), ${data.skipped} sem mudanca.`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao corrigir links da Amazon: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleShopeeRepairReactivate(onlyInactive = true) {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const data = await fetchJson("/dashboard/api/import/store/shopee/repair-affiliate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ only_inactive: onlyInactive }),
      });
      setToast({
        type: "success",
        message: `Shopee revisada: ${data.processed} verificado(s), ${data.updated} atualizado(s), ${data.reactivated} reativado(s), ${data.invalid} invalido(s), ${data.skipped} sem mudanca.`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao corrigir links da Shopee: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleShopeeReimportWithoutVideo() {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const limit = parseImportRunLimit(importForm.runLimit);
      const data = await fetchJson("/dashboard/api/import/store/shopee/reimport-without-video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ limit }),
      });
      setToast({
        type: "success",
        message: `Shopee sem vídeo: lote ${formatImportRunLimitLabel(importForm.runLimit)}, ${Number(data.processed || 0)} processado(s), ${Number(data.updated || 0)} atualizado(s), ${Number(data.with_video || 0)} com vídeo, ${Number(data.without_video || 0)} ainda sem vídeo, ${Number(data.invalid || 0)} inválido(s).`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao reimportar Shopee sem vídeo: ${humanizeImportError(error.message)}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleMercadoLivreRepairReactivate(onlyInactive = true) {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const data = await fetchJson("/dashboard/api/import/store/mercadolivre/repair-affiliate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ only_inactive: onlyInactive }),
      });
      setToast({
        type: "success",
        message: `Mercado Livre corrigido: ${data.processed} verificado(s), ${data.updated} atualizado(s), ${data.reactivated} reativado(s), ${data.invalid} invalido(s), ${data.skipped} sem mudanca.`,
      });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao corrigir links do Mercado Livre: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  function updateManualPreviewItem(index, field, value) {
    setManualLinkPreview((current) => {
      if (!current?.items?.length) return current;
      const items = current.items.map((item, itemIndex) => (
        itemIndex === index ? applyPreviewFieldUpdate(item, field, value) : item
      ));
      return { ...current, items };
    });
  }

  async function handleSocialRun() {
    setRunLoading((state) => ({ ...state, social: true }));
    try {
      const selectedIds = [...socialCheckedIds];
      if (!selectedIds.length) {
        throw new Error("Selecione ao menos uma oferta da fila pronta.");
      }
      if (socialSplit.platform === "whatsapp") {
        setSocialRunPreview(null);
      }
      const payload = { ...socialSplit, limit: selectedIds.length, offer_ids: selectedIds };
      const data = await fetchJson("/dashboard/api/social/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (payload.platform === "whatsapp" && (!Array.isArray(data.items) || !data.items.length)) {
        throw new Error("Nenhuma oferta elegivel voltou do backend para montar o lote do WhatsApp.");
      }
      if (payload.platform === "whatsapp") {
        setSocialRunPreview(data);
      } else {
        setSocialRunPreview(null);
      }
      const errorCount = Number((data.errors || []).length);
      const errorSummary = humanizeSocialError(data.error_summary || (data.errors || [])[0]?.error || "");
      const warningSummary = humanizeSocialError(data.warning_summary || (data.warnings || [])[0]?.warning || "");
      setToast({
        type: errorCount ? "error" : "success",
        message: payload.platform === "whatsapp"
          ? `${payload.mode === "web" ? "WhatsApp Web" : "WhatsApp grupo"}: ${data.count} item(ns) preparado(s) para envio.`
          : errorCount
            ? `Publicacao ${payload.platform}/${payload.mode}: ${data.count} concluido(s), ${errorCount} erro(s). ${errorSummary}`
            : warningSummary && warningSummary !== "Falha ao publicar nas redes sociais."
              ? `Publicacao ${payload.platform}/${payload.mode}: ${data.count} concluido(s). ${warningSummary}`
            : `Publicacao ${payload.platform}/${payload.mode}: ${data.count} concluido(s), ${errorCount} erro(s).`,
      });
      setSocialHiddenIds((current) => [...new Set([...current, ...selectedIds])]);
      setSocialCheckedIds((current) => current.filter((id) => !selectedIds.includes(id)));
      setSocialSelectedItems((current) => current.filter((item) => !selectedIds.includes(item.offer_id)));
      await Promise.all([loadSnapshot(), loadSocialPreview(socialForm.limit, socialForm.query)]);
    } catch (error) {
      if (socialSplit.platform === "whatsapp") {
        setSocialRunPreview(null);
      }
      setToast({ type: "error", message: `Falha na publicacao social: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, social: false }));
    }
  }

  async function handleFacebookBatch() {
    setRunLoading((state) => ({ ...state, batch: true }));
    try {
      const selectedIds = [...socialCheckedIds];
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
      setSocialCheckedIds((current) => current.filter((id) => !selectedIds.includes(id)));
      setSocialSelectedItems((current) => current.filter((item) => !selectedIds.includes(item.offer_id)));
      await Promise.all([loadSnapshot(), loadSocialPreview(socialForm.limit, socialForm.query)]);
    } catch (error) {
      setToast({ type: "error", message: `Falha no lote do Facebook: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, batch: false }));
    }
  }

  async function handleRunJobNow(jobKey) {
    setJobRunLoading((state) => ({ ...state, [jobKey]: true }));
    try {
      const normalizedAuto = normalizeAutoSocialAction(settingsForm.auto_social_platform, settingsForm.auto_social_mode);
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
            platform: normalizedAuto.platform,
            mode: normalizedAuto.mode,
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
      const normalizedAuto = normalizeAutoSocialAction(settingsForm.auto_social_platform, settingsForm.auto_social_mode);
      const payload = {
        manager_username: settingsForm.manager_username,
        manager_password: settingsForm.manager_password || null,
        meta_access_token: settingsForm.meta_access_token || null,
        auto_import_enabled: settingsForm.auto_import_enabled,
        auto_import_times: settingsForm.auto_import_times,
        auto_import_providers: settingsForm.auto_import_providers,
        auto_social_enabled: settingsForm.auto_social_enabled,
        auto_social_times: settingsForm.auto_social_times,
        auto_social_platform: normalizedAuto.platform,
        auto_social_mode: normalizedAuto.mode,
        auto_social_limit: Number(settingsForm.auto_social_limit || 1),
        auto_social_repeat_block_minutes: Number(settingsForm.auto_social_repeat_block_minutes || 1440),
        auto_story_enabled: settingsForm.auto_story_enabled,
        auto_story_times: settingsForm.auto_story_times,
        auto_story_platform: settingsForm.auto_story_platform,
        auto_story_limit: Number(settingsForm.auto_story_limit || 1),
        whatsapp_api_base_url: settingsForm.whatsapp_api_base_url,
        whatsapp_api_token: settingsForm.whatsapp_api_token || null,
        whatsapp_group_target: settingsForm.whatsapp_group_target,
        sftp_host: settingsForm.sftp_host,
        sftp_port: Number(settingsForm.sftp_port || 22),
        sftp_username: settingsForm.sftp_username,
        sftp_password: settingsForm.sftp_password || null,
        sftp_remote_path: settingsForm.sftp_remote_path,
        stories_public_base_url: settingsForm.stories_public_base_url,
        youtube_client_id: settingsForm.youtube_client_id,
        youtube_client_secret: settingsForm.youtube_client_secret || null,
        youtube_redirect_uri: settingsForm.youtube_redirect_uri,
        ytdlp_cookies_from_browser: settingsForm.ytdlp_cookies_from_browser,
        ytdlp_cookies_file: settingsForm.ytdlp_cookies_file,
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

  async function handleLoadWhatsappGroups() {
    setWhatsappGroupsLoading(true);
    try {
      const data = await fetchJson("/dashboard/api/whatsapp/groups?limit=100");
      setWhatsappGroups(Array.isArray(data.items) ? data.items : []);
      setToast({ type: "success", message: `${Number(data.count || 0)} grupo(s) carregado(s) do WhatsApp.` });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao carregar grupos do WhatsApp: ${error.message}` });
    } finally {
      setWhatsappGroupsLoading(false);
    }
  }

  async function handleCopyText(text, successMessage) {
    try {
      if (!navigator?.clipboard?.writeText) {
        throw new Error("Clipboard indisponivel neste navegador.");
      }
      await navigator.clipboard.writeText(String(text || ""));
      setToast({ type: "success", message: successMessage || "Texto copiado." });
    } catch (error) {
      setToast({ type: "error", message: `Falha ao copiar texto: ${error.message}` });
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

  async function handleDeployAutomation() {
    setRunLoading((state) => ({ ...state, deployAutomation: true }));
    try {
      const data = await fetchJson("/dashboard/api/deploy/automation", {
        method: "POST",
      });
      setToast({ type: "success", message: `Atualizar automacao concluido: ${data.count || 0} arquivo(s) enviados ao DreamHost.` });
      await loadSnapshot();
    } catch (error) {
      setToast({ type: "error", message: `Falha ao atualizar automacao: ${error.message}` });
    } finally {
      setRunLoading((state) => ({ ...state, deployAutomation: false }));
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
  const activeNavItem = NAV_ITEMS.find((item) => item.id === activeSection) || NAV_ITEMS[0];

  function toggleSocialSelection(item) {
    if (!item?.offer_id) return;
    setSocialCheckedIds((current) => (
      current.includes(item.offer_id)
        ? current.filter((id) => id !== item.offer_id)
        : [...current, item.offer_id]
    ));
    setSocialSelectedItems((current) => {
      const exists = current.some((entry) => entry.offer_id === item.offer_id);
      if (exists) {
        return current.filter((entry) => entry.offer_id !== item.offer_id);
      }
      return [...current, item];
    });
  }

  function dismissSocialOffer(offerId) {
    setSocialHiddenIds((current) => [...new Set([...current, offerId])]);
  }

  function clearSocialSelection() {
    setSocialCheckedIds([]);
    setSocialSelectedItems([]);
  }

  return (
    <>
      <div className="app-shell">
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">
              <img src="/manager-assets/logo-zp.png" alt="Zero Preço" className="brand-logo" />
            </div>
            <div>
              <h1>Zero Preço Control</h1>
              <p>Operação de afiliados, importação e social em um painel só.</p>
            </div>
          </div>
          <div className="sidebar-nav">
            {NAV_ITEMS.map(({ id, label, note }) => (
              <button key={id} className={`nav-button ${activeSection === id ? "is-active" : ""}`} onClick={() => setActiveSection(id)}>
                <span className="nav-label">{label}</span>
                <span className="nav-note">{note}</span>
              </button>
            ))}
          </div>
          <div className="sidebar-card">
            <h3>Status rápido</h3>
            <p>Facebook Feed, lote do Facebook e Instagram Feed já estão validados. Story do Instagram segue no painel para ajuste fino.</p>
          </div>
          <div className="sidebar-card">
            <h3>Próximos pontos sugeridos</h3>
            <p>Agendamento por horário, fila por prioridade, aprovação manual, score por CTR e alertas de erro por canal.</p>
          </div>
        </aside>

        <main className="main">
          <section className="workspace-header">
            <h2>{activeNavItem.label}</h2>
          </section>

          {activeSection === "painel" ? (
            <>
          <section className="hero" id="painel">
            <div className="hero-head">
              <div className="hero-copy">
                <span className="hero-kicker">Painel de operação</span>
                <h2>Visão geral do manager.</h2>
              </div>
              <div className="hero-actions">
                <span className="status-pill is-ok">API online</span>
                <span className={`status-pill ${socialStatus.some((item) => !item.enabled) ? "is-warn" : "is-info"}`}>Social</span>
                <span className={`status-pill ${manager.auth_enabled ? "is-protected" : "is-danger"}`}>{manager.auth_enabled ? "Protegido" : "Sem auth"}</span>
                <button className="button" onClick={loadSnapshot} disabled={loading}>{loading ? "Atualizando..." : "Atualizar dados"}</button>
                <button className="ghost-button" onClick={() => loadSocialPreview(Number(socialForm.limit))} disabled={socialLoading}>{socialLoading ? "Montando prévias..." : "Atualizar prévias sociais"}</button>
                <form method="post" action="/manager/logout">
                  <button className="ghost-button" type="submit">Sair</button>
                </form>
              </div>
            </div>
          </section>

          <div className="toolbar">
            <div className="toolbar-copy">
              <h3>Radar operacional</h3>
            </div>
          </div>

          <div className="metric-grid">
            <div className="metric-card">
              <div className="metric-label">Ofertas ativas</div>
              <div className="metric-value">{fmtInt(overview.active_offers)}</div>
              <div className="metric-foot">{fmtInt(overview.featured_offers)} em destaque agora.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Cliques nos últimos 7 dias</div>
              <div className="metric-value">{fmtInt(overview.clicks_7d)}</div>
              <div className="metric-foot">{fmtInt(overview.clicks_30d)} acumulados em 30 dias.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Lojas rastreadas</div>
              <div className="metric-value">{fmtInt(overview.tracked_stores)}</div>
              <div className="metric-foot">{fmtMoney(overview.average_price)} de preço médio das ofertas ativas.</div>
            </div>
            <div className="metric-card">
              <div className="metric-label">Execuções recentes</div>
              <div className="metric-value">{fmtInt((overview.import_runs_7d || 0) + (overview.social_posts_7d || 0))}</div>
              <div className="metric-foot">{fmtInt(overview.import_runs_7d)} importações + {fmtInt(overview.social_posts_7d)} posts sociais nos últimos 7 dias.</div>
            </div>
          </div>

          <section className="panel" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Gerenciador de produtos</h3>
                <p className="panel-subtitle">Preview rápido das ofertas mais recentes, no mesmo estilo visual novo do painel.</p>
              </div>
            </div>
            {!snapshot?.recent_offers?.length ? (
              <div className="empty-state">Nenhuma oferta ativa recente encontrada.</div>
            ) : (
              <div className="product-manager-grid">
                {snapshot.recent_offers.slice(0, 4).map((offer) => (
                  <article className="product-card" key={`painel-${offer.id}`}>
                    <div className="product-card-media">
                      {offer.imagem_url ? (
                        <img className="product-card-image" src={offer.imagem_url} alt={offer.titulo} />
                      ) : (
                        <div className="product-card-fallback">{String(offer.loja || "of").slice(0, 2)}</div>
                      )}
                      <span className="badge is-neutral product-card-stamp">{truncateText(offer.loja || "Loja", 20)}</span>
                    </div>
                    <div className="product-card-body">
                      <div className="product-card-topline">
                        <span className="badge is-success">{offer.categoria || "Geral"}</span>
                        <span className="badge is-neutral">{offer.cupom ? `Cupom ${offer.cupom}` : "Sem cupom"}</span>
                      </div>
                      <h4 className="product-card-title">{offer.titulo}</h4>
                      <p className="product-card-copy">Atualizado {fmtDate(offer.atualizado_em)} · slug {truncateText(offer.slug, 28)}</p>
                      <div className="product-card-price">
                        <span className="product-price-main">{fmtMoney(offer.preco)}</span>
                        {offer.preco_antigo && Number(offer.preco_antigo) > Number(offer.preco) ? (
                          <span className="product-price-old">{fmtMoney(offer.preco_antigo)}</span>
                        ) : null}
                      </div>
                      <div className="product-card-actions">
                        <a className="tiny-button is-soft" href={siteOfferUrl(offer.slug)} target="_blank" rel="noreferrer">Abrir no site</a>
                        <a className="tiny-button" href={siteStoreUrl(offer.slug)} target="_blank" rel="noreferrer">Ir para a loja</a>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="panel" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Pesquisar e editar produtos</h3>
                <p className="panel-subtitle">Busque produtos antigos pelo título, slug, loja ou categoria e edite sem sair do dashboard.</p>
              </div>
            </div>
            <div className="product-manager-shell">
              <div className="surface">
                <div className="product-search-toolbar">
                  <input
                    className="product-search-input"
                    type="text"
                    placeholder="Buscar por título, slug, loja, categoria ou tags"
                    value={productQuery}
                    onChange={(e) => setProductQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleProductSearch(productQuery, 1);
                      }
                    }}
                  />
                  <button className="button is-secondary" onClick={() => handleProductSearch(productQuery, 1)} disabled={productsLoading}>
                    {productsLoading ? "Buscando..." : "Pesquisar"}
                  </button>
                </div>
                <div className="product-result-stack">
                  {!productResults.length ? (
                    <div className="empty-state">Nenhum produto encontrado ainda.</div>
                  ) : (
                    productResults.map((item) => (
                      <button
                        key={item.id}
                        className={`product-result-card ${selectedProductId === item.id ? "is-active" : ""}`}
                        onClick={() => selectProduct(item)}
                        style={{ cursor: "pointer" }}
                      >
                        {item.imagem_url ? (
                          <img className="product-result-thumb" src={item.imagem_url} alt={item.titulo} />
                        ) : (
                          <div className="product-result-thumb product-card-fallback">{String(item.loja || "of").slice(0, 2)}</div>
                        )}
                        <div style={{ textAlign: "left" }}>
                          <strong>{item.titulo}</strong>
                          <small>{item.loja} · {item.categoria || "Geral"} · {truncateText(item.slug, 34)}</small>
                          <div className="offer-meta" style={{ marginTop: 8 }}>
                            <span className="meta-chip">{fmtMoney(item.preco)}</span>
                            {item.cupom ? <span className="meta-chip">Cupom {item.cupom}</span> : null}
                          </div>
                        </div>
                        <span className="badge is-neutral">#{item.id}</span>
                      </button>
                    ))
                  )}
                </div>
                <div className="panel-head" style={{ marginTop: 14 }}>
                  <p className="panel-subtitle">
                    {productTotalCount > 0 ? `${productTotalCount} produto(s) encontrado(s) | pagina ${productPage} de ${productTotalPages}` : "Nenhum resultado para paginar."}
                  </p>
                  <div className="provider-actions">
                    <button className="tiny-button is-soft" type="button" disabled={productsLoading || productPage <= 1} onClick={() => handleProductSearch(productQuery, productPage - 1)}>
                      Anterior
                    </button>
                    <button className="tiny-button is-soft" type="button" disabled={productsLoading || productPage >= productTotalPages} onClick={() => handleProductSearch(productQuery, productPage + 1)}>
                      Proxima
                    </button>
                  </div>
                </div>
              </div>

              <div className="surface">
                <h4>Editor rápido</h4>
                <p>{selectedProductId ? "Ajuste os campos abaixo e salve no banco." : "Selecione um produto na busca para editar."}</p>
                {!selectedProductId ? (
                  <div className="empty-state">Nenhum produto selecionado.</div>
                ) : (
                  <>
                    <div className="product-edit-grid">
                      <div className="field is-full">
                        <label>Título</label>
                        <input type="text" value={productForm.titulo} onChange={(e) => setProductForm((state) => ({ ...state, titulo: e.target.value }))} />
                      </div>
                      <div className="field is-full">
                        <label>Slug</label>
                        <input type="text" value={productForm.slug} onChange={(e) => setProductForm((state) => ({ ...state, slug: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Preço</label>
                        <input type="text" value={productForm.preco} onChange={(e) => setProductForm((state) => ({ ...state, preco: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Preço antigo</label>
                        <input type="text" value={productForm.preco_antigo} onChange={(e) => setProductForm((state) => ({ ...state, preco_antigo: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Loja</label>
                        <input type="text" value={productForm.loja} onChange={(e) => setProductForm((state) => ({ ...state, loja: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Categoria</label>
                        <input type="text" value={productForm.categoria} onChange={(e) => setProductForm((state) => ({ ...state, categoria: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Cupom</label>
                        <input type="text" value={productForm.cupom} onChange={(e) => setProductForm((state) => ({ ...state, cupom: e.target.value }))} />
                      </div>
                      <div className="field">
                        <label>Expira em</label>
                        <input type="datetime-local" value={productForm.expira_em} onChange={(e) => setProductForm((state) => ({ ...state, expira_em: e.target.value }))} />
                      </div>
                      <div className="field is-full">
                        <label>Imagem URL</label>
                        <input type="text" value={productForm.imagem_url} onChange={(e) => setProductForm((state) => ({ ...state, imagem_url: e.target.value }))} />
                      </div>
                      <div className="field is-full">
                        <label>URL afiliado</label>
                        <input type="text" value={productForm.url_afiliado} onChange={(e) => setProductForm((state) => ({ ...state, url_afiliado: e.target.value }))} />
                      </div>
                      <div className="field is-full">
                        <label>Tags</label>
                        <input type="text" value={productForm.tags} onChange={(e) => setProductForm((state) => ({ ...state, tags: e.target.value }))} />
                      </div>
                      <div className="field is-full">
                        <label>Descrição</label>
                        <textarea value={productForm.descricao} onChange={(e) => setProductForm((state) => ({ ...state, descricao: e.target.value }))} />
                      </div>
                    </div>
                    <div className="product-check-row" style={{ marginTop: 14 }}>
                      <label className="check-chip">
                        <input type="checkbox" checked={productForm.ativo} onChange={(e) => setProductForm((state) => ({ ...state, ativo: e.target.checked }))} />
                        Ativa
                      </label>
                      <label className="check-chip">
                        <input type="checkbox" checked={productForm.destaque} onChange={(e) => setProductForm((state) => ({ ...state, destaque: e.target.checked }))} />
                        Destaque
                      </label>
                    </div>
                    <div className="product-edit-actions">
                      <button className="button is-primary" onClick={handleProductSave} disabled={productSaving || productDeleting}>
                        {productSaving ? "Salvando..." : "Salvar produto"}
                      </button>
                      <button
                        className="button is-secondary"
                        onClick={handleProductDelete}
                        disabled={productSaving || productDeleting}
                        style={{ background: "#9f2432", color: "#fff", borderColor: "#9f2432" }}
                      >
                        {productDeleting ? "Excluindo..." : "Excluir produto"}
                      </button>
                      <a className="tiny-button is-soft" href={siteOfferUrl(productForm.slug)} target="_blank" rel="noreferrer">Abrir página</a>
                      <a className="tiny-button" href={siteStoreUrl(productForm.slug)} target="_blank" rel="noreferrer">Abrir loja</a>
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>
            </>
          ) : null}

          {activeSection === "configuracoes" ? (
            <>
          <section className="panel" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Automação e agendamento</h3>
                <p className="panel-subtitle">Jobs periódicos do backend Python para importação e social.</p>
              </div>
            </div>
            <div className="status-grid">
              {["import", "social", "story"].filter((jobKey) => !(jobKey === "story" && isCombinedFeedStoryAuto)).map((jobKey) => {
                const job = automation?.jobs?.[jobKey] || {};
                return (
                  <article className={`status-card ${job.last_status === "error" ? "is-error" : job.last_status === "success" ? "is-success" : ""}`} key={jobKey}>
                    <div className="status-card-head">
                      <h4>
                        {jobKey === "import"
                          ? "Job de importacao"
                          : jobKey === "story"
                            ? "Job de stories"
                            : isCombinedFeedStoryAuto
                              ? "Job automatico Feed + Story"
                              : "Job de feed"}
                      </h4>
                      <span className={`badge ${job.enabled ? "is-success" : job.last_run_at ? "is-warning" : "is-neutral"}`}>
                        {job.enabled ? "Ativo" : job.last_run_at ? "Manual somente" : "Desligado"}
                      </span>
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
                        {jobRunLoading[jobKey]
                          ? "Rodando..."
                          : jobKey === "social"
                            ? "Testar job social automatico agora"
                            : jobKey === "story"
                              ? "Testar job de story agora"
                              : "Rodar agora"}
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
                <h3 className="panel-title">Configurações do manager</h3>
                <p className="panel-subtitle">Troque usuário, senha, Meta e automações sem editar o .env na mão.</p>
              </div>
              <div className="provider-actions">
                <button className="button is-secondary" onClick={handleDeployAutomation} disabled={runLoading.deployAutomation}>
                  {runLoading.deployAutomation ? "Publicando automacao..." : "Publicar automacao Python"}
                </button>
                <button className="button is-secondary" onClick={handleDeploySite} disabled={runLoading.deploySite}>
                  {runLoading.deploySite ? "Publicando site..." : "Publicar arquivos do site"}
                </button>
                <button className="button is-secondary" onClick={handleDeployStories} disabled={runLoading.deployStories}>
                  {runLoading.deployStories ? "Publicando stories..." : "Publicar stories"}
                </button>
                <button className="button is-primary" onClick={handleSettingsSave} disabled={settingsLoading}>
                  {settingsLoading ? "Salvando..." : "Salvar configurações"}
                </button>
              </div>
            </div>

            <div className="surface">
              <div className="field-grid">
                <div className="field">
                  <label>Usuário do manager</label>
                  <input type="text" value={settingsForm.manager_username} onChange={(e) => setSettingsForm((state) => ({ ...state, manager_username: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Nova senha do manager</label>
                  <input type="password" placeholder="Deixe vazio para manter a atual" value={settingsForm.manager_password} onChange={(e) => setSettingsForm((state) => ({ ...state, manager_password: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Token Meta</label>
                  <input type="password" placeholder={metaTokenConfigured ? "Token ja configurado" : "Cole um token novo"} value={settingsForm.meta_access_token} onChange={(e) => setSettingsForm((state) => ({ ...state, meta_access_token: e.target.value }))} />
                </div>
              </div>
              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>YouTube Client ID</label>
                  <input type="text" value={settingsForm.youtube_client_id} onChange={(e) => setSettingsForm((state) => ({ ...state, youtube_client_id: e.target.value }))} />
                </div>
                <div className="field">
                  <label>YouTube Client Secret</label>
                  <input type="password" placeholder={snapshot?.settings?.youtube?.client_secret_configured ? "Ja configurado" : "Cole um secret novo"} value={settingsForm.youtube_client_secret} onChange={(e) => setSettingsForm((state) => ({ ...state, youtube_client_secret: e.target.value }))} />
                </div>
                <div className="field">
                  <label>YouTube Redirect URI</label>
                  <input type="text" value={settingsForm.youtube_redirect_uri} onChange={(e) => setSettingsForm((state) => ({ ...state, youtube_redirect_uri: e.target.value }))} />
                  <small>Use a mesma URL cadastrada no Google OAuth.</small>
                </div>
              </div>
              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>yt-dlp cookies do navegador</label>
                  <input
                    type="text"
                    value={settingsForm.ytdlp_cookies_from_browser}
                    onChange={(e) => setSettingsForm((state) => ({ ...state, ytdlp_cookies_from_browser: e.target.value }))}
                  />
                  <small>Ex.: chrome:Default,chrome:Profile 1,edge:Default</small>
                </div>
                <div className="field">
                  <label>yt-dlp cookies.txt</label>
                  <input
                    type="text"
                    value={settingsForm.ytdlp_cookies_file}
                    onChange={(e) => setSettingsForm((state) => ({ ...state, ytdlp_cookies_file: e.target.value }))}
                  />
                  <small>Use um cookies.txt exportado do navegador se o YouTube pedir confirmacao anti-bot.</small>
                </div>
              </div>


              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Auto importacao</label>
                  <label className="check-chip">
                    <input type="checkbox" checked={settingsForm.auto_import_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_import_enabled: e.target.checked }))} />
                    Ativar importacao automatica
                  </label>
                </div>
                <div className="field">
                  <label>Horarios da importacao</label>
                  <input type="text" value={settingsForm.auto_import_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_import_times: e.target.value }))} />
                  <small>Ex.: 06:30,12:30,18:30</small>
                </div>
                <div className="field">
                  <label>Provedores automaticos</label>
                  <div className="check-grid">
                    {IMPORT_OPTIONS.map((item) => (
                      <label className="check-chip" key={item.key}>
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
                    Ativar publicacao automatica
                  </label>
                </div>
                <div className="field">
                  <label>Horarios do social</label>
                  <input type="text" value={settingsForm.auto_social_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_times: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Canal automatico</label>
                  <select value={normalizedAutoSocial.platform} onChange={(e) => setSettingsForm((state) => ({ ...state, ...normalizeAutoSocialAction(e.target.value, state.auto_social_mode) }))}>
                    <option value="facebook">Facebook</option>
                    <option value="instagram">Instagram</option>
                    <option value="both">Facebook + Instagram</option>
                    <option value="whatsapp">WhatsApp</option>
                  </select>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Modo automatico</label>
                  <select value={normalizedAutoSocial.mode} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_mode: e.target.value }))}>
                    {autoSocialModeOptions.map((item) => (
                      <option key={item.value} value={item.value}>{item.label}</option>
                    ))}
                  </select>
                </div>
                <div className="field">
                  <label>Limite do social</label>
                  <input type="number" min="1" max="20" value={settingsForm.auto_social_limit} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_limit: Number(e.target.value || 1) }))} />
                </div>
                <div className="field">
                  <label>Prazo para repetir oferta</label>
                  <input type="number" min="60" step="60" value={settingsForm.auto_social_repeat_block_minutes} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_social_repeat_block_minutes: Number(e.target.value || 1440) }))} />
                  <small>Em minutos. Ex.: 1440 = 24 horas sem repetir no auto social/story.</small>
                </div>
                <div className="field">
                  <label>Status do token</label>
                  <div className="check-grid">
                    <span className={`badge ${metaTokenConfigured ? "is-success" : "is-warning"}`}>{metaTokenConfigured ? "Token salvo" : "Token ausente"}</span>
                  </div>
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                {isCombinedStoryAuto ? (
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Stories automaticos</label>
                    <div className="inline-note is-info">
                      Com `both / reel_story` ou `both / feed_story`, o story ja roda junto no mesmo job automatico. O card separado de stories fica oculto para evitar duplicidade.
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="field">
                      <label>Auto story</label>
                      <label className="check-chip">
                        <input type="checkbox" checked={settingsForm.auto_story_enabled} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_enabled: e.target.checked }))} />
                        Ativar story automatico
                      </label>
                    </div>
                    <div className="field">
                      <label>Horarios do story</label>
                      <input type="text" value={settingsForm.auto_story_times} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_times: e.target.value }))} />
                    </div>
                    <div className="field">
                      <label>Plataforma do story</label>
                      <select value={settingsForm.auto_story_platform} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_platform: e.target.value }))}>
                        <option value="instagram">Instagram</option>
                      </select>
                    </div>
                  </>
                )}
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                {!isCombinedFeedStoryAuto ? (
                  <div className="field">
                    <label>Limite do story</label>
                    <input type="number" min="1" max="10" value={settingsForm.auto_story_limit} onChange={(e) => setSettingsForm((state) => ({ ...state, auto_story_limit: Number(e.target.value || 1) }))} />
                  </div>
                ) : null}
                <div className="field">
                  <label>SFTP host</label>
                  <input type="text" value={settingsForm.sftp_host} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_host: e.target.value }))} />
                </div>
                <div className="field">
                  <label>SFTP porta</label>
                  <input type="number" min="1" value={settingsForm.sftp_port} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_port: Number(e.target.value || 22) }))} />
                </div>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>SFTP usuario</label>
                  <input type="text" value={settingsForm.sftp_username} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_username: e.target.value }))} />
                </div>
                <div className="field">
                  <label>SFTP senha</label>
                  <input type="password" placeholder={sftpSettings.username ? "Deixe vazio para manter" : "Informe a senha"} value={settingsForm.sftp_password} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_password: e.target.value }))} />
                </div>
                <div className="field">
                  <label>Pasta remota</label>
                  <input type="text" value={settingsForm.sftp_remote_path} onChange={(e) => setSettingsForm((state) => ({ ...state, sftp_remote_path: e.target.value }))} />
                </div>
              </div>

              <div className="field" style={{ marginTop: 12 }}>
                <label>Base publica dos stories</label>
                <input type="text" value={settingsForm.stories_public_base_url} onChange={(e) => setSettingsForm((state) => ({ ...state, stories_public_base_url: e.target.value }))} />
              </div>
            </div>
          </section>
            </>
          ) : null}

          {activeSection === "analytics" ? (
          <>
          <section className="panel" id="analytics-products" style={{ marginBottom: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Gerenciador de produtos</h3>
                <p className="panel-subtitle">Cards visuais para revisar ofertas recentes com foto, cupom, slug e atalhos de abertura.</p>
              </div>
            </div>
            {!snapshot?.recent_offers?.length ? (
              <div className="empty-state">Nenhuma oferta ativa recente encontrada.</div>
            ) : (
              <div className="product-manager-grid">
                {snapshot.recent_offers.map((offer) => (
                  <article className="product-card" key={offer.id}>
                    <div className="product-card-media">
                      {offer.imagem_url ? (
                        <img className="product-card-image" src={offer.imagem_url} alt={offer.titulo} />
                      ) : (
                        <div className="product-card-fallback">{String(offer.loja || "of").slice(0, 2)}</div>
                      )}
                      <span className="badge is-neutral product-card-stamp">{truncateText(offer.loja || "Loja", 20)}</span>
                    </div>
                    <div className="product-card-body">
                      <div className="product-card-topline">
                        <span className="badge is-success">{offer.categoria || "Geral"}</span>
                        <span className="badge is-neutral">Atualizado {fmtDate(offer.atualizado_em)}</span>
                      </div>
                      <h4 className="product-card-title">{offer.titulo}</h4>
                      <p className="product-card-copy">Slug {offer.slug} {offer.cupom ? `· cupom ${offer.cupom}` : "· sem cupom ativo"}</p>
                      <div className="product-card-price">
                        <span className="product-price-main">{fmtMoney(offer.preco)}</span>
                        {offer.preco_antigo && Number(offer.preco_antigo) > Number(offer.preco) ? (
                          <span className="product-price-old">{fmtMoney(offer.preco_antigo)}</span>
                        ) : null}
                      </div>
                      <div className="offer-meta">
                        {offer.cupom ? <span className="meta-chip">Cupom {offer.cupom}</span> : null}
                        <span className="meta-chip">{truncateText(offer.slug, 32)}</span>
                      </div>
                      <div className="product-card-actions">
                        <a className="tiny-button is-soft" href={siteOfferUrl(offer.slug)} target="_blank" rel="noreferrer">Abrir no site</a>
                        <a className="tiny-button" href={siteStoreUrl(offer.slug)} target="_blank" rel="noreferrer">Ir para a loja</a>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
          <div className="content-grid" style={{ marginBottom: 18 }}>
            <section className="panel" id="analytics">
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Produtos mais clicados</h3>
                <p className="panel-subtitle">Baseado na tabela de cliques do site público.</p>
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
                          <a className="tiny-button is-soft" href={siteOfferUrl(offer.slug)} target="_blank" rel="noreferrer">Abrir</a>
                      </div>
                    ))}
                  </div>
                )}
            </section>

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
          </>
          ) : null}

          {activeSection === "importadores" ? (
          <section className="panel" id="importadores" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h3 className="panel-title">Importadores afiliados</h3>
                <p className="panel-subtitle">Execute prévia, importação real e acompanhe o estado dos conectores.</p>
              </div>
              <div className="provider-actions">
                <div className="field" style={{ minWidth: 132 }}>
                  <label>Lote do job</label>
                  <select value={importForm.runLimit} onChange={(e) => setImportForm((state) => ({ ...state, runLimit: e.target.value || "5" }))}>
                    {IMPORT_BATCH_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </div>
                <button className="button is-primary" onClick={handleImportRun} disabled={runLoading.import || !importForm.providers.length}>{runLoading.import ? "Rodando importação..." : "Rodar importação"}</button>
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
                      {item.key === "shopee" ? (
                        <button className="button is-secondary" onClick={handleShopeeReimportWithoutVideo} disabled={runLoading.batch}>
                          {runLoading.batch ? "Reimportando Shopee..." : "Reimportar sem vídeo"}
                        </button>
                      ) : null}
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
                          {commerceMetaChips(item).map((chip) => <span className="meta-chip" key={`${item.title}-${chip}`}>{chip}</span>)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="deploy-divider">
                <span>Importacao por pagina</span>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Marketplace da pagina</label>
                  <select value={manualPageForm.provider} onChange={(e) => setManualPageForm((current) => ({ ...current, provider: e.target.value }))}>
                    <option value="mercadolivre">Mercado Livre</option>
                    <option value="amazon">Amazon Experimental</option>
                  </select>
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label>URL da pagina</label>
                  <input
                    type="text"
                    value={manualPageForm.url}
                    onChange={(e) => setManualPageForm((current) => ({ ...current, url: e.target.value }))}
                    placeholder={manualPageForm.provider === "amazon" ? "Cole uma pagina de vitrine/lista da Amazon" : "Cole uma pagina de categoria/lista do Mercado Livre com links afiliados"}
                  />
                  <small>
                    {manualPageForm.provider === "amazon"
                      ? "Modo experimental. O sistema tenta extrair links de produto e aplicar o tag da URL/env. Se a Amazon bloquear, o preview falha com erro claro."
                      : "Use pagina de categoria, busca ou vitrine do painel de afiliados. O sistema tenta preservar o `wid` afiliado vindo da listagem."}
                  </small>
                </div>
                <div className="field">
                  <label>Limite de itens</label>
                  <input
                    type="number"
                    min="1"
                    max="30"
                    value={manualPageForm.limit}
                    onChange={(e) => setManualPageForm((current) => ({ ...current, limit: Number(e.target.value || 1) }))}
                  />
                </div>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={handleManualPagePreview} disabled={manualPageLoading}>
                  {manualPageLoading ? "Lendo pagina..." : manualPageForm.provider === "amazon" ? "Analisar pagina Amazon" : "Analisar pagina ML"}
                </button>
                <button className="button is-primary" onClick={handleManualPageImport} disabled={runLoading.manualLinks}>
                  {runLoading.manualLinks ? "Importando pagina..." : "Importar pagina"}
                </button>
              </div>
              <div style={{ marginTop: 18 }}>
                {!manualPagePreview?.items?.length ? (
                  <div className="empty-state">Nenhuma pagina analisada ainda.</div>
                ) : (
                  <div className="preview-grid">
                    {manualPagePreview.items.map((item, index) => (
                      <div className="surface" key={`${item.item_id || item.url || item.title}-${index}`}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>{item.store || item.provider || "Mercado Livre"}</h4>
                            <p>{item.item_id ? `wid detectado: ${item.item_id}` : "wid nao detectado"}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={Boolean(item.selected)}
                              onChange={(e) => setManualPagePreview((current) => {
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
                            <label>Titulo</label>
                            <input
                              type="text"
                              value={item.title || ""}
                              onChange={(e) => setManualPagePreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, title: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field">
                            <label>Preco</label>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={item.price ?? 0}
                              onChange={(e) => setManualPagePreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? applyPreviewFieldUpdate(entry, "price", e.target.value) : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                          <div className="field">
                            <label>Categoria</label>
                            <input
                              type="text"
                              value={item.category || ""}
                              onChange={(e) => setManualPagePreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, category: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                          <div className="field">
                            <label>Cupom</label>
                            <input
                              type="text"
                              value={item.coupon || ""}
                              onChange={(e) => setManualPagePreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, coupon: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          {item.canonical_url ? <a className="tiny-button is-soft" href={item.canonical_url} target="_blank" rel="noreferrer">Abrir produto</a> : null}
                          {item.image ? <a className="tiny-button is-soft" href={item.image} target="_blank" rel="noreferrer">Abrir imagem</a> : null}
                          {item.item_id ? <span className="meta-chip">wid ok</span> : null}
                          {commerceMetaChips(item).map((chip) => <span className="meta-chip" key={`${item.title}-${chip}`}>{chip}</span>)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="deploy-divider">
                <span>Importacao por arquivo</span>
              </div>

              <div className="field-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Marketplace do arquivo</label>
                  <select value={fileImportProvider} onChange={(e) => setFileImportProvider(e.target.value)}>
                    <option value="shopee">Shopee CSV</option>
                    <option value="mercadolivre">Mercado Livre TXT</option>
                    <option value="amazon">Amazon TXT</option>
                    <option value="amazon_html">Amazon HTML salvo</option>
                  </select>
                </div>
                <div className="field" style={{ gridColumn: "span 2" }}>
                  <label>Arquivo exportado</label>
                  <input
                    type="file"
                    accept={fileImportProvider === "shopee" ? ".csv,text/csv" : fileImportProvider === "amazon_html" ? ".html,.htm,text/html" : ".txt,text/plain"}
                    onChange={(e) => setFileImportFile(e.target.files?.[0] || null)}
                  />
                  <small>
                    {fileImportProvider === "amazon_html"
                      ? "Salve a vitrine da Amazon no navegador como HTML e envie esse arquivo. O sistema tenta extrair os links de produto do HTML salvo sem depender da leitura direta da URL."
                      : fileImportProvider === "amazon"
                      ? "Use um TXT com um link da Amazon por linha. Links encurtados amzn.to sao aceitos e recomendados. Evite dois links na mesma linha para ter o preview mais estavel."
                      : fileImportProvider === "mercadolivre"
                        ? "Use um TXT com um link oficial de afiliado do Mercado Livre por linha. Link comum do produto serve para preview, mas nao entra na importacao."
                        : "Use o CSV exportado do painel da Shopee. O preco do arquivo vira a fonte principal do preview."}
                  </small>
                </div>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={handleFileImportPreview} disabled={fileImportLoading}>
                  {fileImportLoading ? "Lendo arquivo..." : "Analisar arquivo"}
                </button>
                <button className="button is-primary" onClick={handleFileImportRun} disabled={runLoading.manualLinks || hasInvalidSelectedFileMl}>
                  {runLoading.manualLinks ? "Importando arquivo..." : hasInvalidSelectedFileMl ? "Revise precos ML antes de importar" : "Importar arquivo"}
                </button>
                <button className="button is-ghost" onClick={selectValidFileItems} disabled={!fileImportPreview?.items?.length}>
                  Marcar validos
                </button>
                <button className="button is-secondary" onClick={() => handleShopeeRecategorize(false)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo categorias..." : "Recategorizar toda Shopee"}
                </button>
                <button className="button is-ghost" onClick={() => handleShopeeRecategorize(true)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo categorias..." : "Corrigir so 'ofertas'"}
                </button>
                <button className="button is-secondary" onClick={() => handleShopeeRepairReactivate(true)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Reativando Shopee..." : "Reativar Shopee inativa"}
                </button>
                <button className="button is-ghost" onClick={() => handleShopeeRepairReactivate(false)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Reativando Shopee..." : "Revisar toda Shopee"}
                </button>
                <button className="button is-secondary" onClick={() => handleMercadoLivreRepairReactivate(true)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo ML..." : "Reativar ML inativo"}
                </button>
                <button className="button is-ghost" onClick={() => handleMercadoLivreRepairReactivate(false)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo ML..." : "Corrigir todo ML"}
                </button>
                <button className="button is-secondary" onClick={() => handleAmazonRepairReactivate(true)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo Amazon..." : "Reativar Amazon inativa"}
                </button>
                <button className="button is-ghost" onClick={() => handleAmazonRepairReactivate(false)} disabled={runLoading.batch}>
                  {runLoading.batch ? "Corrigindo Amazon..." : "Corrigir toda Amazon"}
                </button>
              </div>
              <div style={{ marginTop: 18 }}>
                {!fileImportPreview?.items?.length ? (
                  <div className="empty-state">Nenhum arquivo analisado ainda.</div>
                ) : (
                  <>
                    <div className="provider-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                      <button
                        className={`button ${fileImportDeepGalleryOnly ? "is-primary" : "is-ghost"}`}
                        onClick={() => setFileImportDeepGalleryOnly((current) => !current)}
                        disabled={!fileImportDeepGalleryCount}
                      >
                        {fileImportDeepGalleryOnly ? "Mostrando so galeria profunda" : `Mostrar so galeria profunda (${fileImportDeepGalleryCount})`}
                      </button>
                      {fileImportDeepGalleryOnly ? (
                        <button className="button is-secondary" onClick={() => setFileImportDeepGalleryOnly(false)}>
                          Mostrar todos
                        </button>
                      ) : null}
                    </div>
                    {!visibleFileImportPreviewItems.length ? (
                      <div className="empty-state">Nenhum item deste arquivo trouxe galeria profunda.</div>
                    ) : (
                  <div className="preview-grid">
                    {visibleFileImportPreviewItems.map(({ item, originalIndex }, index) => (
                      <div className="surface" key={`${item.item_id || item.url || item.title}-${originalIndex}-${index}`}>
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
                                const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? { ...entry, selected: e.target.checked } : entry);
                                return { ...current, items };
                              })}
                            />
                            Importar
                          </label>
                        </div>
                        <div className="field-grid">
                          <div className="field" style={{ gridColumn: "1 / -1" }}>
                            <label>Titulo</label>
                            <input
                              type="text"
                              value={item.title || ""}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? { ...entry, title: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field">
                            <label>Preco</label>
                            <input
                              type="number"
                              min="0"
                              step="0.01"
                              value={item.price ?? 0}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? applyPreviewFieldUpdate(entry, "price", e.target.value) : entry);
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
                                const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? { ...entry, category: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                          <div className="field">
                            <label>Cupom</label>
                            <input
                              type="text"
                              value={item.coupon || ""}
                              onChange={(e) => setFileImportPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? { ...entry, coupon: e.target.value } : entry);
                                return { ...current, items };
                              })}
                            />
                          </div>
                        </div>
                        <div className="field" style={{ marginTop: 12 }}>
                          <label>Descricao</label>
                          <textarea
                            rows="3"
                            value={item.description || ""}
                            onChange={(e) => setFileImportPreview((current) => {
                              if (!current?.items?.length) return current;
                              const items = current.items.map((entry, itemIndex) => itemIndex === originalIndex ? { ...entry, description: e.target.value } : entry);
                              return { ...current, items };
                            })}
                          />
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          {item.image ? <a className="tiny-button is-soft" href={item.image} target="_blank" rel="noreferrer">Abrir imagem</a> : null}
                          {item.video_url ? <a className="tiny-button is-soft" href={item.video_url} target="_blank" rel="noreferrer">Abrir video</a> : null}
                          {item.url ? <span className="meta-chip">link ok</span> : null}
                          {(item.image_urls || []).length ? <span className="meta-chip">{(item.image_urls || []).length} imagem(ns)</span> : null}
                          {importGalleryStatusChip(item) ? <span className="meta-chip">{importGalleryStatusChip(item)}</span> : null}
                          {item.video_url ? <span className="meta-chip">video existente</span> : null}
                          {(item.video_urls || []).length > 1 ? <span className="meta-chip">{(item.video_urls || []).length} videos detectados</span> : null}
                          {item.provider === "mercadolivre" ? (
                            <span className="meta-chip">{item.affiliate_detected ? "link afiliado oficial" : "link ML sem afiliado oficial"}</span>
                          ) : null}
                          {item.provider === "mercadolivre" && Number(item.price || 0) <= 0 ? (
                            <span className="meta-chip">dados incompletos: revise preco</span>
                          ) : null}
                          {commerceMetaChips(item).map((chip) => <span className="meta-chip" key={`${item.title}-${chip}`}>{chip}</span>)}
                          {item.affiliate_warning ? <span className="meta-chip">{item.affiliate_warning}</span> : null}
                          {item.file_warning ? <span className="meta-chip">{item.file_warning}</span> : null}
                        </div>
                        {renderImportPreviewGallery(item)}
                      </div>
                    ))}
                  </div>
                    )}
                  </>
                )}
              </div>

              <div className="deploy-divider">
                <span>Importacao manual por link</span>
              </div>

              <div className="field" style={{ marginTop: 12 }}>
                <label>Importador manual</label>
                <select value={manualLinkProvider} onChange={(e) => setManualLinkProvider(e.target.value)}>
                  <option value="auto">Auto detectar</option>
                  <option value="amazon">Amazon</option>
                  <option value="mercadolivre">Mercado Livre</option>
                  <option value="shopee">Shopee</option>
                  <option value="tiktok">TikTok</option>
                </select>
              </div>
              <div className="field" style={{ marginTop: 12 }}>
                <label>Links afiliados manuais</label>
                <textarea
                  rows="5"
                  value={manualLinkText}
                  onChange={(e) => setManualLinkText(e.target.value)}
                  placeholder={
                    manualLinkProvider === "amazon"
                      ? "Cole aqui links da Amazon, um por linha"
                      : manualLinkProvider === "mercadolivre"
                        ? "Cole aqui links oficiais do Mercado Livre, um por linha"
                        : manualLinkProvider === "shopee"
                          ? "Cole aqui links da Shopee, um por linha"
                          : manualLinkProvider === "tiktok"
                            ? "Cole aqui links do TikTok, um por linha"
                            : "Cole aqui links da Shopee, Mercado Livre, Amazon ou TikTok, um por linha"
                  }
                />
                <small>
                  {manualLinkProvider === "amazon"
                    ? "Use links da Amazon com tag ou shortlinks amzn.to. Se a Amazon bloquear a leitura, o sistema tenta um fallback para revisar e importar."
                    : manualLinkProvider === "mercadolivre"
                      ? "Use links oficiais do Mercado Livre. Se a pagina bloquear, o sistema tenta fallback com dados minimos para revisao."
                      : manualLinkProvider === "shopee"
                        ? "Use links de afiliado da Shopee. O sistema tenta identificar produto, foto, preco e categoria."
                        : manualLinkProvider === "tiktok"
                          ? "Use links do TikTok Shop. O sistema tenta identificar os dados do produto automaticamente."
                          : "O sistema tenta identificar loja, titulo, foto, preco e categoria. Para Mercado Livre, so link oficial de afiliado entra na importacao."}
                </small>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={() => handleManualLinksPreview()} disabled={manualLinkLoading}>
                  {manualLinkLoading ? "Analisando links..." : "Analisar links"}
                </button>
                <button className="button is-primary" onClick={handleManualLinksImport} disabled={runLoading.manualLinks || hasInvalidSelectedManualMl}>
                  {runLoading.manualLinks ? "Importando selecionados..." : hasInvalidSelectedManualMl ? "Revise precos ML antes de importar" : "Importar selecionados"}
                </button>
                <button className="button is-ghost" onClick={selectValidManualItems} disabled={!manualLinkPreview?.items?.length}>
                  Marcar validos
                </button>
              </div>
              {hasInvalidSelectedFileMl ? (
                <div className="inline-note is-info" style={{ marginTop: 12 }}>
                  Existem itens selecionados do Mercado Livre no arquivo com preco zero. Revise o preco antes de importar.
                </div>
              ) : null}
              {hasInvalidSelectedManualMl ? (
                <div className="inline-note is-info" style={{ marginTop: 12 }}>
                  Existem itens selecionados do Mercado Livre com preco zero. Revise o preco antes de importar.
                </div>
              ) : null}
              {manualLinkStatus ? (
                <div className={`inline-note ${manualLinkStatus.type === "error" ? "is-error" : manualLinkStatus.type === "info" ? "is-info" : "is-success"}`} style={{ marginTop: 16 }}>
                  {manualLinkStatus.message}
                  {manualLinkRetry?.active ? ` Repetindo automaticamente em ${manualLinkRetry.secondsLeft}s.` : ""}
                </div>
              ) : null}
              <div style={{ marginTop: 18 }}>
                {!manualLinkPreview?.items?.length ? (
                  <div className="empty-state">Nenhum link manual analisado ainda.</div>
                ) : (
                  <>
                    <div className="provider-actions" style={{ marginTop: 0, marginBottom: 12 }}>
                      <button
                        className={`button ${manualLinkDeepGalleryOnly ? "is-primary" : "is-ghost"}`}
                        onClick={() => setManualLinkDeepGalleryOnly((current) => !current)}
                        disabled={!manualLinkDeepGalleryCount}
                      >
                        {manualLinkDeepGalleryOnly ? "Mostrando so galeria profunda" : `Mostrar so galeria profunda (${manualLinkDeepGalleryCount})`}
                      </button>
                      {manualLinkDeepGalleryOnly ? (
                        <button className="button is-secondary" onClick={() => setManualLinkDeepGalleryOnly(false)}>
                          Mostrar todos
                        </button>
                      ) : null}
                    </div>
                    {!visibleManualLinkPreviewItems.length ? (
                      <div className="empty-state">Nenhum link deste lote trouxe galeria profunda.</div>
                    ) : (
                  <div className="preview-grid">
                    {visibleManualLinkPreviewItems.map(({ item, originalIndex }, index) => (
                      <div className="surface" key={`${item.url || item.title}-${originalIndex}-${index}`}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>{item.store || item.provider || "Marketplace"}</h4>
                            <p>{item.affiliate_code ? `Afiliado detectado: ${item.affiliate_code}` : "Sem codigo de afiliado visivel."}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={Boolean(item.selected)}
                              onChange={(e) => updateManualPreviewItem(originalIndex, "selected", e.target.checked)}
                            />
                            Importar
                          </label>
                        </div>
                        <div className="field-grid">
                          <div className="field" style={{ gridColumn: "1 / -1" }}>
                            <label>Titulo</label>
                            <input type="text" value={item.title || ""} onChange={(e) => updateManualPreviewItem(originalIndex, "title", e.target.value)} />
                          </div>
                        </div>
                        <div className="field-grid" style={{ marginTop: 12 }}>
                          <div className="field">
                            <label>Preco</label>
                            <input type="number" min="0" step="0.01" value={item.price ?? 0} onChange={(e) => updateManualPreviewItem(originalIndex, "price", e.target.value)} />
                          </div>
                          <div className="field">
                            <label>Preco antigo</label>
                            <input type="number" min="0" step="0.01" value={item.old_price ?? ""} onChange={(e) => updateManualPreviewItem(originalIndex, "old_price", e.target.value)} />
                          </div>
                          <div className="field">
                            <label>Categoria</label>
                            <input type="text" value={item.category || ""} onChange={(e) => updateManualPreviewItem(originalIndex, "category", e.target.value)} />
                          </div>
                          <div className="field">
                            <label>Cupom</label>
                            <input type="text" value={item.coupon || ""} onChange={(e) => updateManualPreviewItem(originalIndex, "coupon", e.target.value)} />
                          </div>
                        </div>
                        <div className="field" style={{ marginTop: 12 }}>
                          <label>Descricao</label>
                          <textarea rows="3" value={item.description || ""} onChange={(e) => updateManualPreviewItem(originalIndex, "description", e.target.value)} />
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          {item.image ? <a className="tiny-button is-soft" href={item.image} target="_blank" rel="noreferrer">Abrir imagem</a> : null}
                          {item.video_url ? <a className="tiny-button is-soft" href={item.video_url} target="_blank" rel="noreferrer">Abrir video</a> : null}
                          {item.canonical_url ? <a className="tiny-button is-soft" href={item.canonical_url} target="_blank" rel="noreferrer">Abrir produto</a> : null}
                          {(item.image_urls || []).length ? <span className="meta-chip">{(item.image_urls || []).length} imagem(ns)</span> : null}
                          {importGalleryStatusChip(item) ? <span className="meta-chip">{importGalleryStatusChip(item)}</span> : null}
                          {item.video_url ? <span className="meta-chip">video existente</span> : null}
                          {(item.video_urls || []).length > 1 ? <span className="meta-chip">{(item.video_urls || []).length} videos detectados</span> : null}
                          {item.provider === "mercadolivre" ? (
                            <span className="meta-chip">{item.affiliate_detected ? "link afiliado oficial" : "link ML sem afiliado oficial"}</span>
                          ) : null}
                          {item.provider === "mercadolivre" && Number(item.price || 0) <= 0 ? (
                            <span className="meta-chip">dados incompletos: revise preco</span>
                          ) : null}
                          {item.affiliate_warning ? <span className="meta-chip">{item.affiliate_warning}</span> : null}
                        </div>
                        {renderImportPreviewGallery(item)}
                      </div>
                    ))}
                  </div>
                    )}
                  </>
                )}
              </div>

              <div className="deploy-divider">
                <span>Reativar ML existente por links oficiais</span>
              </div>

              <div className="field" style={{ marginTop: 12 }}>
                <label>Links oficiais do Mercado Livre</label>
                <textarea
                  rows="5"
                  value={mlRelinkText}
                  onChange={(e) => setMlRelinkText(e.target.value)}
                  placeholder="Cole aqui varios links oficiais do Mercado Livre, um por linha"
                />
                <small>Cole os links oficiais gerados pela Barra/Central de Afiliados. O sistema tenta casar cada item com uma oferta ja cadastrada e reativar as correspondentes.</small>
              </div>
              <div className="provider-actions" style={{ marginTop: 16 }}>
                <button className="button is-secondary" onClick={handleMercadoLivreExistingPreview} disabled={mlRelinkLoading}>
                  {mlRelinkLoading ? "Analisando relink..." : "Analisar relink ML"}
                </button>
                <button className="button is-primary" onClick={handleMercadoLivreExistingRun} disabled={runLoading.batch}>
                  {runLoading.batch ? "Vinculando ML..." : "Vincular e reativar ML"}
                </button>
              </div>
              <div style={{ marginTop: 18 }}>
                {!mlRelinkPreview?.items?.length ? (
                  <div className="empty-state">Nenhum relink do Mercado Livre analisado ainda.</div>
                ) : (
                  <div className="preview-grid">
                    {mlRelinkPreview.items.map((item, index) => (
                      <div className="surface" key={`${item.url || item.title}-${index}`}>
                        <div className="panel-head" style={{ marginBottom: 12 }}>
                          <div>
                            <h4>{item.title || "Produto Mercado Livre"}</h4>
                            <p>{item.match_found ? `Match: ${item.matched_offer_title}` : item.match_reason || "Sem match"}</p>
                          </div>
                          <label className="check-chip">
                            <input
                              type="checkbox"
                              checked={Boolean(item.selected)}
                              onChange={(e) => setMlRelinkPreview((current) => {
                                if (!current?.items?.length) return current;
                                const items = current.items.map((entry, itemIndex) => itemIndex === index ? { ...entry, selected: e.target.checked } : entry);
                                return { ...current, items };
                              })}
                            />
                            Vincular
                          </label>
                        </div>
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          {item.url ? <a className="tiny-button is-soft" href={item.url} target="_blank" rel="noreferrer">Abrir link oficial</a> : null}
                          {item.matched_offer_slug ? <span className="meta-chip">{item.matched_offer_slug}</span> : null}
                          {item.product_id ? <span className="meta-chip">{item.product_id}</span> : null}
                          <span className="meta-chip">{item.affiliate_detected ? "link oficial detectado" : "link oficial nao confirmado"}</span>
                          <span className="meta-chip">{item.match_reason || (item.match_found ? "match ok" : "sem match")}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
            </section>
          ) : null}

          {activeSection === "social" ? (
            <section className="panel" id="social" style={{ marginTop: 18 }}>
              <div className="panel-head">
                <div>
                  <h3 className="panel-title">Execução social</h3>
                  <p className="panel-subtitle">
                    {isWhatsappWebSelected
                      ? "Fila pronta para montar links locais do WhatsApp Web sem mensalidade, com envio manual pela sua sessao logada."
                      : isWhatsappGroupSelected
                      ? "Fila pronta para montar mensagens no estilo WhatsApp antes da integração do envio real."
                      : "Fila pronta para Facebook e Instagram com seleção manual antes da publicação."}
                  </p>
                </div>
                <div className="provider-actions">
                  <button className="button is-secondary" onClick={() => loadSocialPreview(Number(socialForm.limit))} disabled={socialLoading}>
                    {socialLoading ? "Atualizando fila..." : "Atualizar fila"}
                  </button>
                  <button className="button is-secondary" onClick={() => handleRunJobNow("social")} disabled={jobRunLoading.social}>
                    {jobRunLoading.social ? "Testando job..." : "Testar job automatico"}
                  </button>
                  <button className="button is-primary" onClick={handleSocialRun} disabled={runLoading.social}>
                    {runLoading.social ? ((isWhatsappGroupSelected || isWhatsappWebSelected) ? "Preparando..." : "Publicando...") : ((isWhatsappGroupSelected || isWhatsappWebSelected) ? "Preparar lote" : "Publicar selecionados")}
                  </button>
                  {!(isWhatsappGroupSelected || isWhatsappWebSelected) ? (
                    <button className="button is-secondary" onClick={handleFacebookBatch} disabled={runLoading.batch}>
                      {runLoading.batch ? "Rodando lote..." : "Facebook em lote"}
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="field-grid social-filter-grid" style={{ marginTop: 12 }}>
                <div className="field">
                  <label>Canal selecionado</label>
                  <select value={socialForm.selected} onChange={(e) => setSocialForm((state) => ({ ...state, selected: e.target.value }))}>
                    {SOCIAL_OPTIONS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
                  </select>
                </div>
                <div className="field social-search-field">
                  <label>Pesquisa de produto</label>
                  <div className="social-search-row">
                    <input
                      type="text"
                      value={socialForm.query}
                      placeholder="Buscar por titulo, slug, loja ou categoria"
                      onChange={(e) => setSocialForm((state) => ({ ...state, query: e.target.value }))}
                    />
                    <button className="tiny-button" onClick={() => loadSocialPreview(socialForm.limit, socialForm.query)} disabled={socialLoading}>
                      Buscar
                    </button>
                  </div>
                </div>
                <div className="field">
                  <label>Itens carregados</label>
                  <input
                    type="number"
                    min="36"
                    max="200"
                    step="12"
                    value={socialForm.limit}
                    onChange={(e) => setSocialForm((state) => ({ ...state, limit: Number(e.target.value || 120) }))}
                  />
                </div>
                <div className="field">
                  <label>Loja</label>
                  <select value={socialFilters.store} onChange={(e) => setSocialFilters((state) => ({ ...state, store: e.target.value }))}>
                    <option value="all">Todas as lojas</option>
                    {socialStoreOptions.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>Categoria</label>
                  <select value={socialFilters.category} onChange={(e) => setSocialFilters((state) => ({ ...state, category: e.target.value }))}>
                    <option value="all">Todas as categorias</option>
                    {socialCategoryOptions.map((item) => <option key={item} value={item}>{item}</option>)}
                  </select>
                </div>
              </div>

              <div className="inline-stat" style={{ marginTop: 16 }}>
                <span className="meta-chip">{fmtInt(socialCheckedIds.length)} selecionada(s)</span>
                <span className="meta-chip">{fmtInt(socialVisibleQueue.length)} visivel(is)</span>
                <span className="meta-chip">{fmtInt(socialCandidates.length)} carregada(s)</span>
                {socialPreview?.database?.ok === false ? <span className="meta-chip">Banco indisponivel</span> : null}
              </div>

              {socialPinnedQueue.length ? (
                <div className="surface social-pinned-panel" style={{ marginTop: 18 }}>
                  <div className="panel-head social-pinned-head">
                    <div>
                      <h4 className="panel-title" style={{ fontSize: "1.05rem" }}>Selecionados para envio</h4>
                      <p className="panel-subtitle">Esses itens continuam salvos mesmo mudando a busca, loja ou categoria.</p>
                    </div>
                    <button className="tiny-button is-soft" type="button" onClick={clearSocialSelection}>
                      Limpar selecao
                    </button>
                  </div>
                  <div className="social-pinned-list">
                    {socialPinnedQueue.map((item) => (
                      <div className="social-pinned-chip" key={`selected-${item.offer_id}`}>
                        {item.image_url ? <img src={item.image_url} alt={item.title} className="social-pinned-thumb" loading="lazy" /> : null}
                        <div className="social-pinned-copy">
                          <strong>{truncateText(item.title, 80)}</strong>
                          <span>{item.store || "Loja"}{item.category ? ` | ${item.category}` : ""}</span>
                        </div>
                        <button className="tiny-button is-soft" type="button" onClick={() => toggleSocialSelection(item)}>
                          Remover
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}

              {(isWhatsappGroupSelected || isWhatsappWebSelected) ? (
                <div className="surface" style={{ marginTop: 18, padding: 0, overflow: "hidden" }}>
                  <div style={{ padding: "16px 18px", borderBottom: "1px solid rgba(16, 24, 40, 0.08)", background: "linear-gradient(135deg, #103a7a 0%, #1d4ed8 100%)", color: "#fff" }}>
                    <strong style={{ display: "block", fontSize: 18 }}>{isWhatsappWebSelected ? "Preview WhatsApp Web Local" : "Preview WhatsApp Grupo"}</strong>
                    <span style={{ opacity: 0.86, fontSize: 13 }}>
                      {isWhatsappWebSelected
                        ? "Sessao local do WhatsApp Web · mensagem pronta com link para abrir e enviar manualmente"
                        : `${settingsForm.whatsapp_group_target || "Grupo ainda não definido"} · mensagem pronta no formato do lote`}
                    </span>
                  </div>
                  <div style={{ background: "#e9ded3", padding: 18 }}>
                    {!whatsappPreviewItems.length ? (
                      <div className="empty-state" style={{ margin: 0 }}>Selecione ofertas para visualizar o preview do WhatsApp.</div>
                    ) : (
                      <div style={{ display: "grid", gap: 14 }}>
                        {isWhatsappWebSelected ? (
                          <div className="surface" style={{ padding: 14, background: "#f8fafc" }}>
                            <strong style={{ display: "block", marginBottom: 10 }}>Lote rapido do WhatsApp Web</strong>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
                              <button
                                className="tiny-button is-soft"
                                type="button"
                                onClick={() => handleCopyText(whatsappBatchText, "Lote completo copiado.")}
                              >
                                Copiar lote completo
                              </button>
                            </div>
                            <div style={{ display: "grid", gap: 8 }}>
                              {whatsappPreviewItems.map((item, index) => (
                                <div key={`wa-batch-${item.offer_id}`} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                                  <span className="meta-chip">Legenda {index + 1}</span>
                                  <a
                                    className="tiny-button"
                                    href={`https://web.whatsapp.com/send?text=${encodeURIComponent(whatsappCaptionForItem(item))}`}
                                    target="_blank"
                                    rel="noreferrer"
                                  >
                                    Abrir link {index + 1}
                                  </a>
                                  <button
                                    className="tiny-button is-soft"
                                    type="button"
                                    onClick={() => handleCopyText(whatsappCaptionForItem(item), `Legenda ${index + 1} copiada.`)}
                                  >
                                    Copiar legenda
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        ) : null}

                        {whatsappPreviewItems.map((item, index) => (
                          <div key={`wa-preview-${item.offer_id}`} style={{ marginLeft: "auto", width: "min(100%, 720px)", display: "grid", gap: 10 }}>
                            <div style={{ background: "#ffffff", borderRadius: 18, padding: 12, boxShadow: "0 10px 24px rgba(15, 23, 42, 0.08)" }}>
                              {whatsappPreviewImageUrl(item) ? (
                                <img
                                  src={whatsappPreviewImageUrl(item)}
                                  alt={item.title}
                                  style={{ width: "100%", maxHeight: 760, objectFit: "contain", borderRadius: 14, background: "#fff" }}
                                />
                              ) : null}
                            </div>
                            <div style={{ marginLeft: "auto", maxWidth: 620, background: "#dcf8c6", borderRadius: "18px 18px 4px 18px", padding: 14, boxShadow: "0 10px 24px rgba(15, 23, 42, 0.08)" }}>
                              <div style={{ whiteSpace: "pre-wrap", color: "#102a43", fontSize: 14, lineHeight: 1.55 }}>{whatsappCaptionForItem(item)}</div>
                              {item.coupon ? (
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                                  <span className="meta-chip">Cupom {item.coupon}</span>
                                </div>
                              ) : null}
                              {isWhatsappWebSelected ? (
                                <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                                  <a className="tiny-button" href={`https://web.whatsapp.com/send?text=${encodeURIComponent(whatsappCaptionForItem(item))}`} target="_blank" rel="noreferrer">
                                    Abrir legenda no WhatsApp Web
                                  </a>
                                  <button
                                    className="tiny-button is-soft"
                                    type="button"
                                    onClick={() => handleCopyText(whatsappCaptionForItem(item), `Legenda ${index + 1} copiada.`)}
                                  >
                                    Copiar legenda
                                  </button>
                                </div>
                              ) : null}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              ) : null}

              <div style={{ marginTop: 18 }}>
                {!socialVisibleQueue.length ? (
                  <div className="empty-state">Sem produto para essa busca/filtro.</div>
                ) : (
                  <div className="social-queue-list">
                    {socialVisibleQueue.map((item) => (
                      <div className="surface social-queue-item" key={item.offer_id}>
                        <label className="check-chip social-check-cell">
                          <input
                            type="checkbox"
                            checked={socialCheckedIds.includes(item.offer_id)}
                            onChange={() => toggleSocialSelection(item)}
                          />
                          <span>Selecionar</span>
                        </label>
                        <div className="social-thumb-wrap">
                          {item.image_url ? <img className="offer-thumb social-offer-thumb" src={item.image_url} alt={item.title} loading="lazy" /> : <div className="offer-thumb social-offer-thumb" />}
                        </div>
                        <div className="social-main-cell">
                          <div className="social-item-title-row">
                            <strong>{truncateText(item.title, 110)}</strong>
                          </div>
                          <div className="social-item-subtitle">{item.store || "Loja"} | {item.category || "Geral"}</div>
                          <div className="offer-meta">
                            <span className="meta-chip">{fmtMoney(item.price)}</span>
                            <span className="meta-chip">{fmtInt(item.clicks || 0)} cliques</span>
                            {item.old_price ? <span className="meta-chip">de {fmtMoney(item.old_price)}</span> : null}
                            {item.coupon ? <span className="meta-chip">cupom: {item.coupon}</span> : null}
                            {commerceMetaChips(item).map((chip) => <span className="meta-chip" key={`${item.offer_id}-${chip}`}>{chip}</span>)}
                          </div>
                          {item.coupon ? <div className="social-item-subtitle">Cupom disponivel: <strong>{item.coupon}</strong></div> : null}
                          {commerceMetaLines(item).length ? <div className="social-item-subtitle">{commerceMetaLines(item).join(" ? ")}</div> : null}
                        </div>
                        <div className="social-links-cell">
                          {item.offer_url ? <a className="tiny-button is-soft" href={item.offer_url} target="_blank" rel="noreferrer">Oferta</a> : null}
                          {item.cta_url ? <a className="tiny-button is-soft" href={item.cta_url} target="_blank" rel="noreferrer">Link afiliado</a> : null}
                          {item.image_url ? <a className="tiny-button is-soft" href={item.image_url} target="_blank" rel="noreferrer">Imagem</a> : null}
                        </div>
                        <div className="social-actions-cell">
                          <button className="tiny-button is-soft" onClick={() => dismissSocialOffer(item.offer_id)}>Ocultar</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          ) : null}

          {activeSection === "crescimento" ? (
            <>
              <section className="hero" style={{ marginTop: 18 }}>
                <div className="hero-head">
                  <div className="hero-copy">
                    <span className="hero-kicker">Crescimento seguro</span>
                    <h2>Radar de seguidores e concorrentes.</h2>
                    <p className="panel-subtitle">Area para mapear perfis e paginas de referencia, descobrir taticas seguras de crescimento e organizar a abordagem manual.</p>
                  </div>
                  <div className="hero-actions">
                    <span className="status-pill is-info">Manual only</span>
                    <span className="status-pill is-ok">Sem follow automatico</span>
                    <button className="button" onClick={loadGrowthRadar} disabled={growthLoading}>
                      {growthLoading ? "Atualizando..." : "Atualizar radar"}
                    </button>
                  </div>
                </div>
              </section>

              <section className="panel" style={{ marginTop: 18, marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Adicionar referencia</h3>
                    <p className="panel-subtitle">Salve grupos, paginas e perfis para acompanhar manualmente o que traz alcance, comentarios e seguidores.</p>
                  </div>
                </div>
                <div className="field-grid">
                  <div className="field">
                    <label>Plataforma</label>
                    <select value={growthForm.platform} onChange={(e) => setGrowthForm((state) => ({ ...state, platform: e.target.value }))}>
                      <option value="instagram">Instagram</option>
                      <option value="facebook">Facebook</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Tipo</label>
                    <select value={growthForm.target_type} onChange={(e) => setGrowthForm((state) => ({ ...state, target_type: e.target.value }))}>
                      <option value="profile">Perfil</option>
                      <option value="creator">Creator</option>
                      <option value="page">Pagina</option>
                      <option value="group">Grupo</option>
                    </select>
                  </div>
                  <div className="field">
                    <label>Prioridade</label>
                    <select value={growthForm.priority} onChange={(e) => setGrowthForm((state) => ({ ...state, priority: e.target.value }))}>
                      <option value="alta">Alta</option>
                      <option value="media">Media</option>
                      <option value="baixa">Baixa</option>
                    </select>
                  </div>
                  <div className="field is-full">
                    <label>Nome</label>
                    <input type="text" value={growthForm.name} onChange={(e) => setGrowthForm((state) => ({ ...state, name: e.target.value }))} placeholder="@achadosdeangel ou nome da pagina/grupo" />
                  </div>
                  <div className="field">
                    <label>Handle</label>
                    <input type="text" value={growthForm.handle} onChange={(e) => setGrowthForm((state) => ({ ...state, handle: e.target.value }))} placeholder="achadosdeangel" />
                  </div>
                  <div className="field">
                    <label>Nicho</label>
                    <input type="text" value={growthForm.niche} onChange={(e) => setGrowthForm((state) => ({ ...state, niche: e.target.value }))} placeholder="achados, cupons, ofertas, compras" />
                  </div>
                  <div className="field is-full">
                    <label>URL</label>
                    <input type="text" value={growthForm.url} onChange={(e) => setGrowthForm((state) => ({ ...state, url: e.target.value }))} placeholder="https://www.instagram.com/... ou https://www.facebook.com/..." />
                  </div>
                  <div className="field is-full">
                    <label>Observacoes</label>
                    <textarea rows="4" value={growthForm.notes} onChange={(e) => setGrowthForm((state) => ({ ...state, notes: e.target.value }))} placeholder="O que voce quer observar: comentarios, formatos, collabs, CTA, frequencia, estilo visual..." />
                  </div>
                </div>
                <div className="provider-actions" style={{ marginTop: 14 }}>
                  <button className="button is-primary" type="button" onClick={handleGrowthTargetSave} disabled={growthSaving}>
                    {growthSaving ? "Salvando..." : "Salvar referencia"}
                  </button>
                  <button className="button is-secondary" type="button" onClick={resetGrowthForm}>
                    Limpar
                  </button>
                </div>
                <div style={{ marginTop: 12 }}>
                  <div className="inline-note is-warning">
                    Esta area nao automatiza follow em massa nem leitura de seguidores de terceiros. O uso aqui e para pesquisa, acompanhamento e abordagem manual segura.
                  </div>
                </div>
              </section>

              <section className="panel" style={{ marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Checklist oficial de crescimento</h3>
                    <p className="panel-subtitle">Acoes que fazem sentido implementar e acompanhar sem colocar a conta em risco.</p>
                  </div>
                </div>
                <div className="offer-meta" style={{ marginBottom: 14 }}>
                  <span className="meta-chip">total {fmtInt(growthRadar?.summary?.total || 0)}</span>
                  <span className="meta-chip">instagram {fmtInt(growthRadar?.summary?.instagram || 0)}</span>
                  <span className="meta-chip">facebook {fmtInt(growthRadar?.summary?.facebook || 0)}</span>
                  <span className="meta-chip">alta prioridade {fmtInt(growthRadar?.summary?.high_priority || 0)}</span>
                </div>
                <div className="preview-grid">
                  {(growthRadar?.guidance || []).map((item, index) => (
                    <article className="surface" key={`growth-guidance-${index}`}>
                      <div className="panel-head" style={{ marginBottom: 10 }}>
                        <div>
                          <h4>{item.title}</h4>
                          <p>{item.summary}</p>
                        </div>
                        <span className="badge is-success">{item.platform}</span>
                      </div>
                      <div className="inline-note is-info">{item.action}</div>
                      <div className="provider-actions" style={{ marginTop: 12 }}>
                        {item.source_url ? <a className="tiny-button is-soft" href={item.source_url} target="_blank" rel="noreferrer">{item.source_label || "Fonte"}</a> : null}
                        {item.verified ? <span className="meta-chip">oficial</span> : <span className="meta-chip">operacional</span>}
                      </div>
                    </article>
                  ))}
                </div>
                {(growthRadar?.guardrails || []).length ? (
                  <div style={{ marginTop: 14 }}>
                    {(growthRadar.guardrails || []).map((item, index) => (
                      <div className="inline-note is-warning" key={`growth-guardrail-${index}`} style={{ marginTop: index ? 8 : 0 }}>
                        {item}
                      </div>
                    ))}
                  </div>
                ) : null}
              </section>

              <section className="panel">
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Fila manual de acompanhamento</h3>
                    <p className="panel-subtitle">Abra os perfis/paginas, estude o que funciona, comente manualmente e teste temas parecidos no seu conteudo.</p>
                  </div>
                </div>
                {growthLoading ? (
                  <div className="empty-state">Carregando radar de crescimento...</div>
                ) : !(growthRadar?.targets || []).length ? (
                  <div className="empty-state">Nenhuma referencia salva ainda. Adicione perfis do Instagram, paginas e grupos do Facebook para montar sua fila manual.</div>
                ) : (
                  <div className="preview-grid">
                    {(growthRadar.targets || []).map((target) => (
                      <article className="surface" key={`growth-target-${target.id}`}>
                        <div className="panel-head" style={{ marginBottom: 10 }}>
                          <div>
                            <h4>{target.name}</h4>
                            <p>{target.handle ? `@${target.handle}` : target.url}</p>
                          </div>
                          <span className="badge is-success">{target.platform}</span>
                        </div>
                        <div className="offer-meta" style={{ marginBottom: 12 }}>
                          <span className="meta-chip">{target.target_type}</span>
                          <span className="meta-chip">{target.priority}</span>
                          <span className="meta-chip">{target.status}</span>
                          {target.niche ? <span className="meta-chip">{target.niche}</span> : null}
                        </div>
                        {target.notes ? (
                          <div className="inline-note is-info">{target.notes}</div>
                        ) : (
                          <div className="inline-note is-info">Sem observacoes ainda. Use este alvo para estudar CTA, comentarios, frequencia e formatos que geram alcance.</div>
                        )}
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <span className="meta-chip">criado {fmtDate(target.created_at)}</span>
                          <span className="meta-chip">atualizado {fmtDate(target.updated_at)}</span>
                          {target.last_checked_at ? <span className="meta-chip">checado {fmtDate(target.last_checked_at)}</span> : null}
                        </div>
                        <div className="provider-actions" style={{ marginTop: 12 }}>
                          <a className="tiny-button is-soft" href={target.url} target="_blank" rel="noreferrer">Abrir</a>
                          <button className="tiny-button is-soft" type="button" onClick={() => updateGrowthTarget(target, { status: "monitorando", last_checked_at: new Date().toISOString().slice(0, 19) })}>
                            Monitorando
                          </button>
                          <button className="tiny-button is-soft" type="button" onClick={() => updateGrowthTarget(target, { status: "pronto_para_testar", last_checked_at: new Date().toISOString().slice(0, 19) })}>
                            Pronto para testar
                          </button>
                          <button className="tiny-button is-soft" type="button" onClick={() => updateGrowthTarget(target, { status: "arquivado", last_checked_at: new Date().toISOString().slice(0, 19) })}>
                            Arquivar
                          </button>
                          <button className="tiny-button is-soft" type="button" onClick={() => removeGrowthTarget(target.id)}>
                            Remover
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </>
          ) : null}

          {activeSection === "youtube_cortes" ? (
            <>
              <section className="hero" style={{ marginTop: 18 }}>
                <div className="hero-head">
                  <div className="hero-copy">
                    <span className="hero-kicker">Fase 1</span>
                    <h2>Cortes YouTube</h2>
                    <p className="panel-subtitle">Intake inicial para podcasts, briefing editorial e pauta de cortes antes da automação completa.</p>
                  </div>
                  <div className="hero-actions">
                    <span className="status-pill is-info">Roadmap salvo</span>
                    <span className="status-pill is-ok">docs/youtube-cuts-roadmap.md</span>
                  </div>
                </div>
              </section>

              <section className="panel" style={{ marginTop: 18, marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Perfis de canal</h3>
                    <p className="panel-subtitle">Cadastre varios canais, conecte cada um com seu proprio OAuth e escolha qual perfil sera usado nos cortes, radar e uploads.</p>
                  </div>
                  <div className="provider-actions">
                    <button className="button is-secondary" type="button" onClick={loadYoutubeChannels} disabled={youtubeChannelsLoading}>
                      {youtubeChannelsLoading ? "Atualizando..." : "Atualizar canais"}
                    </button>
                    <button className="button is-secondary" type="button" onClick={() => resetYoutubeChannelForm()}>
                      Novo perfil
                    </button>
                  </div>
                </div>
                <div className="field-grid">
                  <div className="field">
                    <label>Perfil ativo no fluxo</label>
                    <select value={youtubeSelectedChannelId || ""} onChange={(e) => setYoutubeSelectedChannelId(Number(e.target.value) || null)}>
                      <option value="">Selecione</option>
                      {youtubeChannelProfiles.map((profile) => (
                        <option key={`yt-channel-option-${profile.id}`} value={profile.id}>
                          {profile.name}{profile.is_default ? " �?� padrao" : ""}{profile.is_active ? "" : " �?� inativo"}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label>Nome do perfil</label>
                    <input type="text" value={youtubeChannelForm.name} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, name: e.target.value }))} placeholder="Ex.: Zero Cortes Guerra" />
                  </div>
                  <div className="field">
                    <label>Handle interno</label>
                    <input type="text" value={youtubeChannelForm.handle} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, handle: e.target.value }))} placeholder="@zerocortes" />
                  </div>
                  <div className="field">
                    <label>Client ID</label>
                    <input type="text" value={youtubeChannelForm.client_id} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, client_id: e.target.value }))} placeholder="Se vazio, usa o padrao do .env" />
                  </div>
                  <div className="field">
                    <label>Client secret</label>
                    <input type="password" value={youtubeChannelForm.client_secret} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, client_secret: e.target.value }))} placeholder={youtubeChannelEditingId ? "Deixe vazio para manter o atual" : "Opcional se usar o padrao do .env"} />
                  </div>
                  <div className="field">
                    <label>Redirect URI</label>
                    <input type="text" value={youtubeChannelForm.redirect_uri} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, redirect_uri: e.target.value }))} placeholder="https://seu-dominio/integrations/youtube/oauth/callback" />
                  </div>
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Palavras para evitar</label>
                    <textarea rows="2" value={youtubeChannelForm.avoid_terms} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, avoid_terms: e.target.value }))} placeholder="Uma por linha ou separadas por virgula. Ex.: tragedia, morte, assunto tecnico demais" />
                  </div>
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Palavras para priorizar</label>
                    <textarea rows="2" value={youtubeChannelForm.preferred_terms} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, preferred_terms: e.target.value }))} placeholder="Ex.: polemica, bastidores, reacao, provocacao, arbitragem" />
                  </div>
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Tom viral do canal</label>
                    <textarea rows="2" value={youtubeChannelForm.viral_tone} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, viral_tone: e.target.value }))} placeholder="Ex.: risadas, zoacao, brincadeira, sentimento, provocacao, deboche leve" />
                  </div>
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Notas</label>
                    <textarea rows="3" value={youtubeChannelForm.notes} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, notes: e.target.value }))} placeholder="Nicho, linguagem e observacoes desse canal." />
                  </div>
                </div>
                <div className="offer-meta" style={{ marginTop: 12 }}>
                  <label className="tiny-button is-soft" style={{ cursor: "pointer" }}>
                    <input type="checkbox" checked={Boolean(youtubeChannelForm.is_default)} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, is_default: e.target.checked }))} />
                    Perfil padrao
                  </label>
                  <label className="tiny-button is-soft" style={{ cursor: "pointer" }}>
                    <input type="checkbox" checked={Boolean(youtubeChannelForm.is_active)} onChange={(e) => setYoutubeChannelForm((current) => ({ ...current, is_active: e.target.checked }))} />
                    Perfil ativo
                  </label>
                </div>
                <div className="provider-actions" style={{ marginTop: 16 }}>
                  <button className="button is-primary" type="button" onClick={handleYoutubeChannelSave} disabled={youtubeChannelSaving}>
                    {youtubeChannelSaving ? "Salvando..." : youtubeChannelEditingId ? "Salvar perfil" : "Criar perfil"}
                  </button>
                  {youtubeChannelEditingId ? (
                    <button className="button is-secondary" type="button" onClick={() => resetYoutubeChannelForm()}>
                      Cancelar edicao
                    </button>
                  ) : null}
                </div>
                {!youtubeChannelProfiles.length ? (
                  <div className="empty-state" style={{ marginTop: 16 }}>Nenhum perfil de canal cadastrado ainda.</div>
                ) : (
                  <div className="preview-grid" style={{ marginTop: 16 }}>
                    {youtubeChannelProfiles.map((profile) => (
                      <article className="surface" key={`yt-profile-${profile.id}`}>
                        <div className="panel-head" style={{ marginBottom: 10 }}>
                          <div>
                            <h4>{profile.name}</h4>
                            <p>{profile.channel_title || profile.handle || "Canal ainda nao autenticado"}</p>
                          </div>
                          <span className={`badge ${profile.is_active ? "is-success" : "is-warning"}`}>{profile.is_active ? "ativo" : "inativo"}</span>
                        </div>
                        <div className="offer-meta">
                          {profile.is_default ? <span className="meta-chip">padrao</span> : null}
                          {profile.channel_custom_url ? <span className="meta-chip">{profile.channel_custom_url}</span> : null}
                          <span className="meta-chip">id {profile.id}</span>
                        </div>
                        {profile.preferred_terms ? (
                          <div className="inline-note is-info" style={{ marginTop: 12 }}>
                            <strong>Priorizar:</strong> {profile.preferred_terms}
                          </div>
                        ) : null}
                        {profile.avoid_terms ? (
                          <div className="inline-note is-info" style={{ marginTop: 8 }}>
                            <strong>Evitar:</strong> {profile.avoid_terms}
                          </div>
                        ) : null}
                        {profile.viral_tone ? (
                          <div className="inline-note is-info" style={{ marginTop: 8 }}>
                            <strong>Tom viral:</strong> {profile.viral_tone}
                          </div>
                        ) : null}
                        <div className="provider-actions" style={{ marginTop: 12 }}>
                          <button className="tiny-button is-soft" type="button" onClick={() => setYoutubeSelectedChannelId(Number(profile.id))}>
                            Usar neste fluxo
                          </button>
                          <button
                            className="tiny-button is-soft"
                            type="button"
                            onClick={() => {
                              setYoutubeChannelEditingId(Number(profile.id));
                              setYoutubeChannelForm({
                                name: profile.name || "",
                                handle: profile.handle || "",
                                notes: profile.notes || "",
                                avoid_terms: profile.avoid_terms || "",
                                preferred_terms: profile.preferred_terms || "",
                                viral_tone: profile.viral_tone || "",
                                client_id: profile.client_id || "",
                                client_secret: "",
                                redirect_uri: profile.redirect_uri || "",
                                is_default: Boolean(profile.is_default),
                                is_active: Boolean(profile.is_active),
                              });
                            }}
                          >
                            Editar
                          </button>
                          <button className="tiny-button is-soft" type="button" onClick={() => handleYoutubeChannelDelete(profile.id)}>
                            Remover
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="panel" style={{ marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Analisar video</h3>
                    <p className="panel-subtitle">Cole um link do YouTube para montar sugestoes iniciais de cortes e legenda.</p>
                  </div>
                </div>
                <div className="field-grid">
                  <div className="field">
                    <label>Modo de corte</label>
                    <select value={youtubeCutMode} onChange={(e) => setYoutubeCutMode(e.target.value)}>
                      <option value="short">Short</option>
                      <option value="long">Corte longo 10-15 min</option>
                    </select>
                  </div>
                  {youtubeCutMode === "short" ? (
                    <div className="field">
                      <label>Selecao dos shorts</label>
                      <select value={youtubeShortSelectionStrategy} onChange={(e) => setYoutubeShortSelectionStrategy(e.target.value)}>
                        <option value="openai_heuristica">OpenAI + Heuristica</option>
                        <option value="openai">OpenAI</option>
                        <option value="heuristica">Heuristica melhorada</option>
                      </select>
                    </div>
                  ) : null}
                  <div className="field" style={{ gridColumn: "1 / -1" }}>
                    <label>Link do YouTube</label>
                    <input
                      type="text"
                      value={youtubeCutUrl}
                      onChange={(e) => setYoutubeCutUrl(e.target.value)}
                      placeholder="https://www.youtube.com/watch?v=..."
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleYoutubeCutsAnalyze();
                        }
                      }}
                    />
                  </div>
                </div>
                <div className="provider-actions" style={{ marginTop: 16 }}>
                  <button className="button is-primary" onClick={handleYoutubeCutsAnalyze} disabled={youtubeCutLoading}>
                    {youtubeCutLoading ? "Analisando..." : `Analisar ${youtubeCutMode === "long" ? "corte longo" : "short"}`}
                  </button>
                  <button className="button is-secondary" onClick={handleYoutubeCutsProcess} disabled={youtubeCutsPhase2Loading}>
                    {youtubeCutsPhase2Loading ? "Gerando cortes..." : `Gerar ${youtubeCutMode === "long" ? "cortes longos" : "cortes reais"}`}
                  </button>
                </div>
              </section>

              <section className="panel" style={{ marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Fase 3: conexao com YouTube</h3>
                    <p className="panel-subtitle">OAuth Google por perfil, status do canal escolhido e publicacao dos cortes gerados.</p>
                  </div>
                  <div className="provider-actions">
                    <button className="button is-secondary" onClick={() => loadYoutubeOauthStatus(youtubeSelectedChannelId)} disabled={youtubeOauthLoading}>
                      {youtubeOauthLoading ? "Atualizando..." : "Atualizar status"}
                    </button>
                    <button className="button is-secondary" onClick={handleLoadYoutubeTrendIdeas} disabled={youtubeTrendIdeasLoading || !youtubeOauthStatus?.authenticated || !youtubeSelectedChannelId}>
                      {youtubeTrendIdeasLoading ? "Buscando temas..." : "Inscricoes 48h para corte"}
                    </button>
                    <button className="button is-primary" onClick={handleYoutubeConnect} disabled={!youtubeSelectedChannelId}>
                      Conectar YouTube
                    </button>
                  </div>
                </div>
                <div className="status-grid">
                  <article className={`status-card ${youtubeOauthStatus?.authenticated ? "is-success" : youtubeOauthStatus?.error ? "is-error" : ""}`}>
                    <div className="status-card-head">
                      <h4>Conta YouTube do perfil</h4>
                      <span className={`badge ${youtubeOauthStatus?.authenticated ? "is-success" : "is-warning"}`}>{youtubeOauthStatus?.authenticated ? "Conectado" : "Pendente"}</span>
                    </div>
                    <p>Perfil: {youtubeOauthStatus?.profile?.name || "nenhum selecionado"}</p>
                    <p>Client ID: {youtubeOauthStatus?.client_id_configured ? "configurado" : "ausente"}</p>
                    <p>Client secret: {youtubeOauthStatus?.client_secret_configured ? "configurado" : "ausente"}</p>
                    <p>Redirect URI: {youtubeOauthStatus?.redirect_uri || "nao definido"}</p>
                    <p>Cookies browser: {snapshot?.settings?.youtube?.cookies_from_browser || "nao definido"}</p>
                    <p>Cookies file: {snapshot?.settings?.youtube?.cookies_file || "nao definido"}</p>
                    <p>Refresh token: {youtubeOauthStatus?.refresh_token_configured ? "ok" : "pendente"}</p>
                    <p>Canal: {youtubeOauthStatus?.channel?.title || "nenhum canal autenticado ainda"}</p>
                    {youtubeOauthStatus?.channel?.custom_url ? <p>Handle: {youtubeOauthStatus.channel.custom_url}</p> : null}
                    {youtubeOauthStatus?.error ? <div className="inline-note is-info" style={{ marginTop: 12 }}>{youtubeOauthStatus.error}</div> : null}
                  </article>
                </div>
              </section>

              <section className="panel" style={{ marginBottom: 18 }}>
                <div className="panel-head">
                  <div>
                    <h3 className="panel-title">Radar de videos para cortar</h3>
                    <p className="panel-subtitle">Olha os canais em que voce ja e inscrito, filtra videos das ultimas 48 horas e prioriza podcasts sobre guerra e politica com melhor potencial de corte.</p>
                  </div>
                  <div className="provider-actions">
                    <button className="button is-secondary" type="button" onClick={handleLoadYoutubeTrendIdeas} disabled={youtubeTrendIdeasLoading || !youtubeOauthStatus?.authenticated || !youtubeSelectedChannelId}>
                      {youtubeTrendIdeasLoading ? "Buscando..." : "Atualizar lista"}
                    </button>
                  </div>
                </div>
                {!youtubeOauthStatus?.authenticated ? (
                  <div className="empty-state">Selecione um perfil e conecte o canal do YouTube primeiro para ler suas inscricoes e buscar videos das ultimas 48 horas para corte.</div>
                ) : !youtubeTrendIdeas?.ideas?.length ? (
                  <div className="empty-state">Clique em "Inscricoes 48h para corte" para montar a lista dos melhores videos base vindos dos canais que voce ja segue.</div>
                ) : (
                  <>
                    <div className="offer-meta" style={{ marginBottom: 14 }}>
                      <span className="meta-chip">{youtubeTrendIdeas.target_profile?.name || youtubeTrendIdeas.channel?.title || "Canal conectado"}</span>
                      {youtubeTrendIdeas.channel?.custom_url ? <span className="meta-chip">{youtubeTrendIdeas.channel.custom_url}</span> : null}
                      <span className="meta-chip">{Number(youtubeTrendIdeas.ideas?.length || 0)} tema(s)</span>
                      <span className="meta-chip">{Number(youtubeTrendIdeas.recent_uploads?.length || 0)} upload(s) recentes lidos</span>
                    </div>
                    <div className="preview-grid">
                      {(youtubeTrendIdeas.ideas || []).map((idea, ideaIndex) => (
                        <article className="surface" key={`youtube-trend-${idea.seed_video_id || ideaIndex}`}>
                          <div className="panel-head" style={{ marginBottom: 12 }}>
                            <div>
                              <h4>{truncateText(idea.seed_title || `Canal ${ideaIndex + 1}`, 88)}</h4>
                              <p>Canal inscrito com uploads recentes alinhados a podcast, guerra ou politica.</p>
                            </div>
                            <span className="badge is-success">canal {ideaIndex + 1}</span>
                          </div>
                          <div className="offer-meta" style={{ marginBottom: 12 }}>
                            {idea.query ? <span className="meta-chip">{idea.query}</span> : null}
                            <span className="meta-chip">ultimas 48h</span>
                            {idea.seed_url ? <a className="tiny-button is-soft" href={idea.seed_url} target="_blank" rel="noreferrer">Abrir canal</a> : null}
                          </div>
                          <div style={{ display: "grid", gap: 10 }}>
                            {(idea.videos || []).map((video, videoIndex) => (
                              <div key={`trend-video-${ideaIndex}-${video.video_id || videoIndex}`} className="surface" style={{ padding: 12, display: "grid", gap: 8 }}>
                                <strong>{video.title || "Video sugerido"}</strong>
                                <div className="social-item-subtitle">
                                  {video.channel_title || "Canal"}
                                  {video.view_count ? ` | ${fmtInt(video.view_count)} views` : ""}
                                </div>
                                <div className="offer-meta">
                                  {video.cut_score ? <span className="meta-chip">Potencial {video.cut_score}/100</span> : null}
                                  {video.duration_label ? <span className="meta-chip">{video.duration_label}</span> : null}
                                  {video.published_at ? <span className="meta-chip">{fmtDate(video.published_at)}</span> : null}
                                  <a className="tiny-button is-soft" href={video.url} target="_blank" rel="noreferrer">Abrir link</a>
                                  <button className="tiny-button is-soft" type="button" onClick={() => setYoutubeCutUrl(video.url || "")}>
                                    Usar no corte
                                  </button>
                                  <button className="tiny-button is-soft" type="button" onClick={() => handleCopyText(video.url || "", "Link do video copiado.")}>
                                    Copiar link
                                  </button>
                                </div>
                                {(video.cut_reasons || []).length ? (
                                  <div style={{ display: "grid", gap: 6 }}>
                                    {(video.cut_reasons || []).map((reason, reasonIndex) => (
                                      <div className="inline-note is-info" key={`trend-reason-${ideaIndex}-${videoIndex}-${reasonIndex}`}>
                                        {reason}
                                      </div>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            ))}
                          </div>
                        </article>
                      ))}
                    </div>
                  </>
                )}
              </section>

              {!youtubeCutAnalysis ? (
                <section className="panel">
                  <div className="empty-state">Nenhum vídeo analisado ainda. Esta fase guarda o briefing e as sugestões para seguirmos nas próximas etapas sem perder o plano.</div>
                </section>
              ) : (
                <>
                  <section className="panel" style={{ marginBottom: 18 }}>
                    <div className="panel-head">
                      <div>
                        <h3 className="panel-title">Preview do vídeo</h3>
                        <p className="panel-subtitle">{youtubeCutAnalysis.video?.title || "Vídeo analisado"}</p>
                      </div>
                    </div>
                    <div className="product-manager-shell">
                      <div className="surface">
                        <div style={{ position: "relative", width: "100%", paddingTop: "56.25%", borderRadius: 24, overflow: "hidden", background: "#0f172a" }}>
                          <iframe
                            src={youtubeCutAnalysis.video?.embed_url}
                            title={youtubeCutAnalysis.video?.title || "Preview YouTube"}
                            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                            allowFullScreen
                            style={{ position: "absolute", inset: 0, width: "100%", height: "100%", border: 0 }}
                          />
                        </div>
                      </div>
                      <div className="surface">
                        <h4>Resumo da análise</h4>
                        <p><strong>Título:</strong> {youtubeCutAnalysis.video?.title || "-"}</p>
                        <p><strong>Canal:</strong> {youtubeCutAnalysis.video?.author_name || "-"}</p>
                        <p><strong>Etapa atual:</strong> briefing editorial</p>
                        {youtubeCutAnalysis.strategy?.profile ? <p><strong>Perfil aplicado:</strong> {youtubeCutAnalysis.strategy.profile}</p> : null}
                        <div className="offer-meta" style={{ marginTop: 12 }}>
                          <a className="tiny-button is-soft" href={youtubeCutAnalysis.video?.url} target="_blank" rel="noreferrer">Abrir vídeo</a>
                          {youtubeCutAnalysis.roadmap_path ? <span className="meta-chip">{youtubeCutAnalysis.roadmap_path}</span> : null}
                          {youtubeCutAnalysis.oembed_error ? <span className="meta-chip">metadados com fallback</span> : <span className="meta-chip">metadados OK</span>}
                        </div>
                        {youtubeCutAnalysis.strategy ? (
                          <div className="panel" style={{ marginTop: 14, padding: 16, borderRadius: 18 }}>
                            <div className="panel-head" style={{ marginBottom: 10 }}>
                              <div>
                                <h4>Pacote editorial</h4>
                                <p className="panel-subtitle">Base fixa para melhorar descoberta, clique e retenção.</p>
                              </div>
                            </div>
                            <p><strong>Posicionamento:</strong> {youtubeCutAnalysis.strategy.positioning}</p>
                            <p><strong>Fórmula de título:</strong> {youtubeCutAnalysis.strategy.title_formula}</p>
                            <div className="offer-meta" style={{ marginTop: 10 }}>
                              {(youtubeCutMode === "long" ? youtubeCutAnalysis.strategy.long_opening_checklist : youtubeCutAnalysis.strategy.short_opening_checklist || []).map((item, index) => (
                                <span className="meta-chip" key={`yt-strategy-${index}`}>{item}</span>
                              ))}
                            </div>
                            {youtubeCutAnalysis.strategy.subtitle_style ? (
                              <div className="inline-note is-info" style={{ marginTop: 12 }}>
                                Legenda padrao: {youtubeCutAnalysis.strategy.subtitle_style.base_color} com borda {youtubeCutAnalysis.strategy.subtitle_style.outline}, destaque {youtubeCutAnalysis.strategy.subtitle_style.active_color} e comportamento "{youtubeCutAnalysis.strategy.subtitle_style.behavior}".
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                        <div style={{ marginTop: 14 }}>
                          {(youtubeCutAnalysis.notes || []).map((note, index) => (
                            <div className="inline-note is-info" key={`youtube-note-${index}`} style={{ marginTop: index ? 8 : 0 }}>
                              {note}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </section>

                  <section className="panel">
                    <div className="panel-head">
                      <div>
                        <h3 className="panel-title">{youtubeCutMode === "long" ? "Sugestoes iniciais de cortes longos" : "Sugestoes iniciais de cortes"}</h3>
                        <p className="panel-subtitle">{youtubeCutMode === "long" ? "Saem com tema, duracao alvo de 10 a 15 minutos e foco em retencao para video normal do canal." : "Saem com gancho, duracao alvo e legenda base para voce validar o tema antes da geracao real."}</p>
                      </div>
                    </div>
                    <div className="preview-grid">
                      {((youtubeCutMode === "long" ? youtubeCutAnalysis.long_suggestions : youtubeCutAnalysis.suggestions) || []).map((item, index) => (
                        <article className="surface" key={`youtube-cut-${index}`}>
                          <div className="panel-head" style={{ marginBottom: 12 }}>
                            <div>
                              <h4>{item.angle}</h4>
                              <p>{item.title}</p>
                            </div>
                            <span className="badge is-success">score {item.score}</span>
                          </div>
                          <div className="offer-meta" style={{ marginBottom: 12 }}>
                            <span className="meta-chip">{item.duration_label}</span>
                            <span className="meta-chip">{item.status}</span>
                            {(item.topic_tags || []).map((tag) => <span className="meta-chip" key={`${item.angle}-${tag}`}>{tag}</span>)}
                          </div>
                          <div className="field">
                            <label>Gancho</label>
                            <textarea rows="2" value={item.hook || ""} readOnly />
                          </div>
                          <div className="field" style={{ marginTop: 12 }}>
                            <label>Texto do primeiro frame</label>
                            <input type="text" value={item.first_frame_text || ""} readOnly />
                          </div>
                          {(item.title_variants || []).length ? (
                            <div className="field" style={{ marginTop: 12 }}>
                              <label>Variações de título</label>
                              <textarea rows="4" value={(item.title_variants || []).join("\n")} readOnly />
                            </div>
                          ) : null}
                          <div className="field" style={{ marginTop: 12 }}>
                            <label>Legenda sugerida</label>
                            <textarea rows="5" value={item.caption_draft || ""} readOnly />
                          </div>
                          {(item.packaging_notes || []).length ? (
                            <div style={{ marginTop: 12 }}>
                              {(item.packaging_notes || []).map((note, noteIndex) => (
                                <div className="inline-note is-info" key={`packaging-${index}-${noteIndex}`} style={{ marginTop: noteIndex ? 8 : 0 }}>
                                  {note}
                                </div>
                              ))}
                            </div>
                          ) : null}
                          <div className="inline-note is-info" style={{ marginTop: 12 }}>
                            {item.reason}
                          </div>
                        </article>
                      ))}
                    </div>
                  </section>

                  {youtubeCutsPhase2 ? (
                    <>
                      <section className="panel" style={{ marginTop: 18, marginBottom: 18 }}>
                        <div className="panel-head">
                          <div>
                            <h3 className="panel-title">Transcrição base</h3>
                            <p className="panel-subtitle">
                              {youtubeCutsPhase2.transcript?.segments_count || 0} bloco(s) detectado(s) a partir de {youtubeCutsPhase2.transcript?.source === "openai_audio" ? "fallback por áudio" : "legendas automáticas do YouTube"}.
                            </p>
                          </div>
                          <div className="offer-meta">
                            <span className="meta-chip">job {youtubeCutsPhase2.job_id}</span>
                            <span className="meta-chip">fase 2</span>
                            {youtubeCutsPhase2?.mode === "short" ? <span className="meta-chip">selecao {youtubeCutsPhase2.selection_strategy || "openai"}</span> : null}
                            <span className="meta-chip">{youtubeCutsPhase2.transcript?.source === "openai_audio" ? "OpenAI áudio" : "YouTube VTT"}</span>
                          </div>
                        </div>
                        {youtubeCutsPhase2.transcript?.warning ? (
                          <div className="inline-note is-info" style={{ marginBottom: 12 }}>
                            Falha na legenda do YouTube: {youtubeCutsPhase2.transcript.warning}
                          </div>
                        ) : null}
                        <div className="field">
                          <label>Texto base</label>
                          <textarea rows="10" value={youtubeCutsPhase2.transcript?.text || ""} readOnly />
                        </div>
                        {youtubeCutsPhase2.strategy ? (
                          <div className="panel" style={{ marginTop: 14, padding: 16, borderRadius: 18 }}>
                            <div className="panel-head" style={{ marginBottom: 12 }}>
                              <div>
                                <h4>Estrategia aplicada na renderizacao</h4>
                                <p className="panel-subtitle">{youtubeCutsPhase2.strategy.profile || "Perfil editorial"}</p>
                              </div>
                            </div>
                            <p><strong>Posicionamento:</strong> {youtubeCutsPhase2.strategy.positioning}</p>
                            <p><strong>Formula de titulo:</strong> {youtubeCutsPhase2.strategy.title_formula}</p>
                            {youtubeCutsPhase2.strategy.subtitle_style ? (
                              <div className="inline-note is-info" style={{ marginTop: 12 }}>
                                Legenda renderizada em {youtubeCutsPhase2.strategy.subtitle_style.base_color} com borda {youtubeCutsPhase2.strategy.subtitle_style.outline}; palavra ativa fica {youtubeCutsPhase2.strategy.subtitle_style.active_color}.
                              </div>
                            ) : null}
                          </div>
                        ) : null}
                      </section>

                      <section className="panel">
                        <div className="panel-head">
                          <div>
                            <h3 className="panel-title">Cortes gerados</h3>
                            <p className="panel-subtitle">{youtubeCutsPhase2?.mode === "long" ? "Os videos abaixo saem como cortes longos em horizontal com abertura forte e thumbnail mais limpa." : "Os videos abaixo ja saem em vertical com abertura de impacto e legenda dinamica."}</p>
                          </div>
                        </div>
                        <div className="preview-grid">
                          {(youtubeCutsPhase2.cuts || []).map((item) => (
                            <article className="surface" key={`generated-cut-${item.cut_id}`}>
                              <div className="panel-head" style={{ marginBottom: 12 }}>
                                <div>
                                  {item.mode === "long" && item.publish_draft?.editorial_role ? (
                                    <div className="offer-meta" style={{ marginBottom: 8 }}>
                                      <span className={`badge ${item.publish_draft.editorial_role === "principal" ? "is-success" : "is-neutral"}`}>
                                        {item.publish_draft.editorial_role === "principal" ? "Corte principal" : "Corte secundario"}
                                      </span>
                                    </div>
                                  ) : null}
                                </div>
                                <span className="badge is-success">score {item.score}</span>
                              </div>
                              {item.mode === "long" && item.thumbnail_asset_url ? (
                                <div style={{ marginBottom: 12 }}>
                                  <img
                                    src={item.thumbnail_asset_url}
                                    alt={`Thumbnail ${item.title}`}
                                    style={{ width: "100%", borderRadius: 18, background: "#0f172a" }}
                                  />
                                </div>
                              ) : null}
                              <video
                                controls
                                preload="metadata"
                                style={{ width: "100%", borderRadius: 18, background: "#0f172a" }}
                                src={item.video_asset_url}
                              />
                              <div className="offer-meta" style={{ marginTop: 12 }}>
                                <span className="meta-chip">{item.start_label}</span>
                                <span className="meta-chip">{item.end_label}</span>
                                <span className="meta-chip">{item.duration_label}</span>
                                <span className="meta-chip">{item.status}</span>
                                {item.mode === "short" ? <span className="meta-chip">{item.series_mode === "series" ? "serie" : "single"}</span> : null}
                                {item.series_label ? <span className="meta-chip">{item.series_label}</span> : null}
                                {(item.topic_tags || []).map((tag) => <span className="meta-chip" key={`${item.cut_id}-${tag}`}>{tag}</span>)}
                                <a className="tiny-button is-soft" href={item.video_asset_url} target="_blank" rel="noreferrer">Abrir vídeo</a>
                                {item.subtitle_asset_url ? <a className="tiny-button is-soft" href={item.subtitle_asset_url} target="_blank" rel="noreferrer">Legenda</a> : null}
                                <a className="tiny-button is-soft" href={item.download_url} download>Baixar vídeo</a>
                                <button className="tiny-button is-soft" type="button" onClick={() => handleCopyText(item.copy_title || item.title, "Título copiado.")}>
                                  Copiar título
                                </button>
                                <button className="tiny-button is-soft" type="button" onClick={() => handleCopyText(item.copy_description || item.caption_draft, "Descrição copiada.")}>
                                  Copiar descrição
                                </button>
                              </div>
                              <div className="field" style={{ marginTop: 12 }}>
                                <label>Trecho detectado</label>
                                <textarea rows="5" value={item.transcript_excerpt || ""} readOnly />
                              </div>
                              <div className="field" style={{ marginTop: 12 }}>
                                <label>Texto do primeiro frame</label>
                                <input type="text" value={item.first_frame_text || ""} readOnly />
                              </div>
                              {item.opening_score ? (
                                <div className="offer-meta" style={{ marginTop: 12 }}>
                                  <span className="meta-chip">Abertura {item.opening_score}</span>
                                </div>
                              ) : null}
                              <div className="field" style={{ marginTop: 12 }}>
                                <label>Descricao sugerida</label>
                                <textarea rows="5" value={item.caption_draft || ""} readOnly />
                              </div>
                              {(item.packaging_notes || []).length ? (
                                <div style={{ marginTop: 12 }}>
                                  {(item.packaging_notes || []).map((note, noteIndex) => (
                                    <div className="inline-note is-info" key={`cut-note-${item.cut_id}-${noteIndex}`} style={{ marginTop: noteIndex ? 8 : 0 }}>
                                      {note}
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                              {item.mode === "long" && (item.publish_draft?.chapters || []).length ? (
                                <div className="field" style={{ marginTop: 12 }}>
                                  <label>Capitulos automáticos</label>
                                  <textarea rows="5" value={(item.publish_draft.chapters || []).join("\n")} readOnly />
                                </div>
                              ) : null}
                              {(item.publish_draft?.scorecard || (item.publish_draft?.title_variants || []).length) ? (
                                <div className="panel" style={{ marginTop: 14, padding: 16, borderRadius: 18 }}>
                                  <div className="panel-head" style={{ marginBottom: 12 }}>
                                    <div>
                                      <h4>{item.mode === "long" ? "Score editorial" : "Empacotamento editorial"}</h4>
                                      <p className="panel-subtitle">{item.mode === "long" ? "Leitura rapida de potencial para clique, retencao e tema." : "Variacoes de titulo para testar embalagens mais fortes."}</p>
                                    </div>
                                    {item.publish_draft?.scorecard ? <span className="meta-chip">overall {item.publish_draft.scorecard.overall || 0}</span> : null}
                                  </div>
                                  {item.publish_draft?.scorecard ? (
                                    <div className="offer-meta">
                                      <span className="meta-chip">CTR {item.publish_draft.scorecard.ctr || 0}</span>
                                      <span className="meta-chip">Retencao {item.publish_draft.scorecard.retention || 0}</span>
                                      <span className="meta-chip">{item.mode === "long" ? `Tema ${item.publish_draft.scorecard.topic || 0}` : `Contexto ${item.publish_draft.scorecard.context || 0}`}</span>
                                    </div>
                                  ) : null}
                                  {(item.publish_draft.title_variants || []).length ? (
                                  <div style={{ marginTop: 14, display: "grid", gap: 8 }}>
                                    {(item.publish_draft.title_variants || []).map((variant, variantIndex) => (
                                      <div key={`variant-${item.cut_id}-${variantIndex}`} className="surface" style={{ padding: 12, display: "grid", gap: 8 }}>
                                        <strong>Variacao {variantIndex + 1}</strong>
                                        <div>{variant}</div>
                                          <div className="provider-actions">
                                            <button className="tiny-button is-soft" type="button" onClick={() => updateYoutubeCutDraft(item.cut_id, "title", variant)}>
                                              Usar este titulo
                                            </button>
                                            <button className="tiny-button is-soft" type="button" onClick={() => handleCopyText(variant, `Titulo ${variantIndex + 1} copiado.`)}>
                                              Copiar titulo
                                            </button>
                                          </div>
                                        </div>
                                      ))}
                                    </div>
                                  ) : null}
                                  {item.mode === "long" && (item.publish_draft.thumbnail_text_variants || []).length ? (
                                    <div style={{ marginTop: 14, display: "grid", gap: 8 }}>
                                      {(item.publish_draft.thumbnail_text_variants || []).map((variant, variantIndex) => (
                                        <div key={`thumb-variant-${item.cut_id}-${variantIndex}`} className="surface" style={{ padding: 12, display: "grid", gap: 8 }}>
                                          <strong>Texto da thumb {variantIndex + 1}</strong>
                                          <div>{variant}</div>
                                          <button className="tiny-button is-soft" type="button" onClick={() => handleCopyText(variant, `Texto da thumb ${variantIndex + 1} copiado.`)}>
                                            Copiar texto
                                          </button>
                                        </div>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              ) : null}
                              <div className="panel" style={{ marginTop: 14, padding: 16, borderRadius: 18 }}>
                                <div className="panel-head" style={{ marginBottom: 12 }}>
                                  <div>
                                    <h4>{item.mode === "long" ? "Fase 4: publicacao do video" : "Fase 4: publicacao do Short"}</h4>
                                    <p className="panel-subtitle">{item.mode === "long" ? "Descricao e thumbnail alinhadas com analise, crise e impacto no Brasil." : "Descricao e titulo preparados para Shorts de economia e geopolítica."}</p>
                                  </div>
                                  <span className="meta-chip">{item.publish_draft?.privacy_status || "public"}</span>
                                </div>
                                <div className="offer-meta" style={{ marginBottom: 12 }}>
                                  {item.mode === "short" ? <span className="meta-chip">{item.publish_draft?.series_mode === "series" ? "serie" : "single"}</span> : null}
                                  {item.publish_draft?.series_label ? <span className="meta-chip">{item.publish_draft.series_label}</span> : null}
                                  {(item.publish_draft?.topic_tags || []).map((tag) => <span className="meta-chip" key={`draft-tag-${item.cut_id}-${tag}`}>{tag}</span>)}
                                </div>
                                {item.publish_draft?.first_frame_text ? (
                                  <div className="field" style={{ marginBottom: 12 }}>
                                    <label>Hook visual usado no video</label>
                                    <input type="text" value={item.publish_draft.first_frame_text || ""} readOnly />
                                  </div>
                                ) : null}
                                <div className="field">
                                  <label>Titulo do YouTube</label>
                                  <input type="text" value={item.publish_draft?.title || ""} onChange={(e) => updateYoutubeCutDraft(item.cut_id, "title", e.target.value)} />
                                </div>
                                <div className="field" style={{ marginTop: 12 }}>
                                  <label>Privacidade</label>
                                  <select value={item.publish_draft?.privacy_status || "public"} onChange={(e) => updateYoutubeCutDraft(item.cut_id, "privacy_status", e.target.value)}>
                                    <option value="public">Public</option>
                                    <option value="unlisted">Unlisted</option>
                                    <option value="private">Private</option>
                                  </select>
                                </div>
                                <div className="field" style={{ marginTop: 12 }}>
                                  <label>Descricao enriquecida</label>
                                  <textarea rows="9" value={item.publish_draft?.description || ""} onChange={(e) => updateYoutubeCutDraft(item.cut_id, "description", e.target.value)} />
                                </div>
                                {(item.publish_draft?.packaging_notes || []).length ? (
                                  <div style={{ marginTop: 12 }}>
                                    {(item.publish_draft.packaging_notes || []).map((note, noteIndex) => (
                                      <div className="inline-note is-info" key={`draft-note-${item.cut_id}-${noteIndex}`} style={{ marginTop: noteIndex ? 8 : 0 }}>
                                        {note}
                                      </div>
                                    ))}
                                  </div>
                                ) : null}
                                {(item.publish_draft?.distribution_notes || []).length ? (
                                  <div style={{ marginTop: 12 }}>
                                    {(item.publish_draft.distribution_notes || []).map((note, noteIndex) => (
                                      <div className="inline-note is-info" key={`distribution-note-${item.cut_id}-${noteIndex}`} style={{ marginTop: noteIndex ? 8 : 0 }}>
                                        {note}
                                      </div>
                                    ))}
                                  </div>
                                ) : null}
                                <div className="provider-actions" style={{ marginTop: 12 }}>
                                  <button className="button is-primary" type="button" onClick={() => handleYoutubeCutPublish(item)} disabled={youtubePublishingCutId === Number(item.cut_id) || !youtubeOauthStatus?.authenticated}>
                                    {youtubePublishingCutId === Number(item.cut_id) ? "Publicando no YouTube..." : (item.publish_draft?.publish_label || (item.mode === "long" ? "Publicar video" : "Publicar Short"))}
                                  </button>
                                  <button className="button is-secondary" type="button" onClick={() => handleCopyText(item.publish_draft?.description || "", "Descricao do YouTube copiada.")}>
                                    Copiar descricao
                                  </button>
                                  {item.publish_result?.youtube_url ? <a className="tiny-button is-soft" href={item.publish_result.youtube_url} target="_blank" rel="noreferrer">Abrir no YouTube</a> : null}
                                </div>
                                {item.mode === "long" && item.publish_result?.thumbnail_result ? (
                                  <div className="inline-note is-info" style={{ marginTop: 12 }}>
                                    Thumbnail enviada junto com o video no YouTube.
                                  </div>
                                ) : null}
                                {item.mode === "long" && item.publish_result?.thumbnail_error ? (
                                  <div className="inline-note is-warning" style={{ marginTop: 12 }}>
                                    O video foi publicado, mas a thumbnail falhou: {item.publish_result.thumbnail_error}
                                  </div>
                                ) : null}
                              </div>
                            </article>
                          ))}
                        </div>
                      </section>
                    </>
                  ) : null}
                </>
              )}
            </>
          ) : null}

          {activeSection === "execucoes" ? (
            <section className="panel" id="execucoes" style={{ marginTop: 18 }}>
              <div className="panel-head">
                <div>
                  <h3 className="panel-title">Execuções recentes</h3>
                  <p className="panel-subtitle">Histórico operacional consolidado do backend Python.</p>
                </div>
              </div>
              {!snapshot?.recent_runs?.length ? (
                <div className="empty-state">Nenhuma execução recente registrada.</div>
              ) : (
                <div className="offer-list">
                  {snapshot.recent_runs.slice(0, 3).map((run) => (
                    <div className="offer-row" key={run.id}>
                      <div style={{ flex: 1 }}>
                        <strong>{run.tipo} · {run.provider || run.canal || "-"}</strong>
                        <small>{run.modo || "-"} · solicitado {fmtInt(run.requested_count)} · processado {fmtInt(run.processed_count)}</small>
                        <div className="offer-meta">
                          <span className={`badge ${run.status === "success" ? "is-success" : run.status === "error" ? "is-warning" : "is-neutral"}`}>{fmtJobStatus(run.status)}</span>
                          <span className="meta-chip">inicio {fmtDate(run.criado_em)}</span>
                          <span className="meta-chip">fim {fmtDate(run.finalizado_em)}</span>
                        </div>
                        {run.error_message ? <p style={{ marginTop: 8 }}>{run.error_message}</p> : null}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </main>
      </div>
      <Toast toast={toast} onClose={() => setToast(null)} />
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
