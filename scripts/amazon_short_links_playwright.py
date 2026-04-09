from __future__ import annotations

import argparse
import sys
from pathlib import Path


DEFAULT_START_URL = "https://www.amazon.com.br/deals?ref_=nav_cs_gb"


SCRIPT_TEMPLATE = r"""
(async () => {
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const isVisible = (el) => {
  if (!el) return false;
  const rect = el.getBoundingClientRect();
  const style = window.getComputedStyle(el);
  return (
    rect.width > 20 &&
    rect.height > 20 &&
    rect.bottom > 0 &&
    rect.right > 0 &&
    rect.top < window.innerHeight &&
    rect.left < window.innerWidth &&
    style.visibility !== "hidden" &&
    style.display !== "none"
  );
};

const getOfferLinks = (limit) => {
  const links = [...document.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"]')]
    .filter((a) => isVisible(a))
    .map((a) => a.href.split("?")[0])
    .filter((href) => href.includes("amazon.com.br"));

  return [...new Set(links)].slice(0, limit);
};

const getShortField = () => {
  const fields = [...document.querySelectorAll("input[type='text'], textarea")];
  return fields.find((field) => {
    const value = String(field.value || field.textContent || "").trim();
    return value.includes("amzn.to/");
  }) || null;
};

const findExactText = (selector, text) =>
  [...document.querySelectorAll(selector)].find(
    (el) => el.innerText?.trim() === text && isVisible(el)
  ) || null;

const extractProductData = async () => {
  const openBtn =
    findExactText("button, a, span, div", "Obter link") ||
    [...document.querySelectorAll("button, a, span, div")].find(
      (el) => el.innerText?.includes("Obter link") && isVisible(el)
    ) ||
    null;

  if (!openBtn) {
    return { ok: false, error: "sem botao Obter link" };
  }

  openBtn.click();
  await sleep(1500);

  const shortRadio = findExactText("label, span, div", "Link curto");
  if (shortRadio) {
    shortRadio.click();
    await sleep(400);
  }

  const modalGetBtn = [...document.querySelectorAll("button")]
    .find((el) => el.innerText?.trim() === "Obter link" && isVisible(el));
  if (modalGetBtn) {
    modalGetBtn.click();
    await sleep(1200);
  }

  const field = getShortField();
  if (!field) {
    return { ok: false, error: "sem campo amzn.to" };
  }

  const shortUrl = String(field.value || field.textContent || "").trim();
  const titleNode = document.querySelector("#productTitle");
  const title = String(titleNode?.textContent || document.title || "").trim();
  return { ok: !!shortUrl, short_url: shortUrl, title };
};

return { offer_links: getOfferLinks(%(limit)s), product: await extractProductData() };
})()
"""


def ensure_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Instale as dependencias primeiro:\n"
            "pip install playwright\n"
            "python -m playwright install chrome"
        ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta links curtos do SiteStripe Amazon a partir da pagina de ofertas."
    )
    parser.add_argument("--start-url", default=DEFAULT_START_URL)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="amazon-short-links.txt")
    parser.add_argument(
        "--profile-dir",
        default="",
        help=(
            "Diretorio de perfil do Chrome/Chromium para usar em modo persistente. "
            "Ex.: C:\\Users\\Windows\\AppData\\Local\\Google\\Chrome\\User Data\\Default"
        ),
    )
    parser.add_argument(
        "--manual-login",
        action="store_true",
        help="Abre o navegador e pausa para voce fazer login manual antes da coleta.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Executa sem UI. Nao recomendado para SiteStripe.",
    )
    return parser.parse_args()


def normalize_limit(value: int) -> int:
    return max(1, min(int(value or 10), 10))


def build_output(lines: list[str], output_path: Path) -> None:
    output_path.write_text("\n".join(lines), encoding="utf-8")


def run() -> int:
    ensure_playwright()
    from playwright.sync_api import Error, TimeoutError, sync_playwright

    args = parse_args()
    limit = normalize_limit(args.limit)
    output_path = Path(args.output).resolve()
    profile_dir = Path(args.profile_dir).expanduser().resolve() if args.profile_dir else None

    with sync_playwright() as pw:
        browser_context = None
        browser = None
        try:
            if profile_dir:
                browser_context = pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile_dir),
                    channel="chrome",
                    headless=bool(args.headless),
                )
                page = browser_context.new_page()
            else:
                browser = pw.chromium.launch(channel="chrome", headless=bool(args.headless))
                browser_context = browser.new_context()
                page = browser_context.new_page()

            page.goto(args.start_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(4_000)

            if args.manual_login:
                print("Faça login no Amazon/Associados nessa janela e pressione Enter aqui para continuar.")
                input()
                page.bring_to_front()
                page.goto(args.start_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(4_000)

            offer_data = page.evaluate(SCRIPT_TEMPLATE % {"limit": limit})
            offer_links = list(offer_data.get("offer_links") or [])
            if not offer_links:
                raise RuntimeError("Nao encontrei produtos visiveis na pagina inicial.")

            collected: list[str] = []
            for index, offer_url in enumerate(offer_links[:limit], start=1):
                product_page = browser_context.new_page()
                try:
                    product_page.goto(str(offer_url), wait_until="domcontentloaded", timeout=60_000)
                    product_page.wait_for_timeout(4_000)
                    result = product_page.evaluate(SCRIPT_TEMPLATE % {"limit": 1})
                    product_info = dict(result.get("product") or {})
                    if not product_info.get("ok"):
                        print(f"[SKIP {index}] {offer_url} -> {product_info.get('error') or 'erro'}")
                        continue
                    short_url = str(product_info.get("short_url") or "").strip()
                    if not short_url:
                        print(f"[SKIP {index}] {offer_url} -> link vazio")
                        continue
                    collected.append(short_url)
                    print(f"[OK {index}] {short_url}")
                except (Error, TimeoutError) as exc:
                    print(f"[SKIP {index}] {offer_url} -> {exc}")
                finally:
                    product_page.close()

            build_output(collected, output_path)
            print(f"\nArquivo salvo em: {output_path}")
            print(f"Total coletado: {len(collected)}")
            return 0
        finally:
            try:
                if browser_context is not None:
                    browser_context.close()
            except Exception:
                pass
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(run())
