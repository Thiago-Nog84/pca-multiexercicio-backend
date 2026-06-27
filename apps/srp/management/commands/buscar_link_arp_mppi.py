"""
Busca automaticamente o PDF de cada ARP no site do MPPI e preenche
o campo `link_documento_mppi` em AtaRegistroPrecos.

Estratégia principal — scraping das páginas oficiais do MPPI:
  Para cada página CLC configurada em PAGINAS_CLC, faz GET com headers
  de navegador, parseia o HTML com BeautifulSoup e extrai pares
  (num_arp, ano) → url_download seguindo a lógica:
    heading "Ata de Registro de Preços nº X/YYYY"  →  link "Download"
  Funciona independentemente do nome do arquivo (cobre ARP-9.pdf,
  ARP-54-2025_merged.pdf, SEI_...pdf, ilovepdf_...pdf, etc.).

Fallback — catálogo WordPress REST API:
  Se uma ARP não for encontrada nas páginas CLC, tenta a API
  /wp-json/wp/v2/media paginando todos os PDFs do site.

Uso:
    python manage.py buscar_link_arp_mppi
    python manage.py buscar_link_arp_mppi --todos       # reprocessa quem já tem link
    python manage.py buscar_link_arp_mppi --arp 54/2025 # só esta ARP
    python manage.py buscar_link_arp_mppi --dry-run     # mostra sem salvar
    python manage.py buscar_link_arp_mppi --sem-fallback  # só páginas CLC
"""

import re
import time

import requests
from django.core.management.base import BaseCommand, CommandError

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

from apps.srp.models import AtaRegistroPrecos

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

MPPI_BASE = "https://www.mppi.mp.br/internet"
WP_MEDIA  = f"{MPPI_BASE}/wp-json/wp/v2/media"
TIMEOUT   = 20
DELAY     = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": f"{MPPI_BASE}/coordenadoria-de-licitacoes-e-contratos/",
}

# Páginas do MPPI que listam as ARPs com links para Download
PAGINAS_CLC = [
    (
        "2026",
        f"{MPPI_BASE}/coordenadoria-de-licitacoes-e-contratos/"
        "?sub=2026-editais-informacoes-anteriores-a-resolucao-cnmp-no-86-2012"
        ":atas-de-registro-de-preco-2026-editais-informacoes-anteriores-a-resolucao-cnmp-no-86-2012",
    ),
    (
        "2025",
        f"{MPPI_BASE}/coordenadoria-de-licitacoes-e-contratos/"
        "?sub=2025-editais-informacoes-anteriores-a-resolucao-cnmp-no-86-2012"
        ":termo-aditivo-2025-editais-informacoes-anteriores-a-resolucao-cnmp-no-86-2012"
        ":2025-atas-de-registro-de-preco",
    ),
    (
        "2024",
        f"{MPPI_BASE}/coordenadoria-de-licitacoes-e-contratos/"
        "?sub=2024-editais-informacoes-anteriores-a-resolucao-cnmp-no-86-2012-documentos-clc"
        ":2024-atas-de-registro-de-preco",
    ),
]

# Regex para extrair nº da ARP do texto do heading
# Cobre: "n° 20/2026", "nº 09/2026", "n. 5/2025", "No 34/2025"
RE_NUM_ARP = re.compile(r'n[°º\.o]\s*0*(\d+)\s*[\/\-]\s*(\d{4})', re.IGNORECASE)

# Regex para extrair nº de arquivo que não segue padrão mas tem o número no nome
RE_ARP_FNAME = re.compile(r'ARP-0*(\d+)-(\d{4})', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Scraping das páginas CLC
# ---------------------------------------------------------------------------

def _extrair_links_pagina(html: str) -> dict[tuple[str, str], str]:
    """
    Parseia o HTML de uma página CLC e extrai {(num, ano): url_download}.
    Lógica: percorre todos os elementos da <article>; quando encontra um
    heading com o padrão "Ata nº X/YYYY", memoriza o número; quando encontra
    um link com texto "Download", associa a URL ao número memorizado.
    """
    if not BS4_OK:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return {}

    resultado: dict[tuple[str, str], str] = {}
    ultimo_num = ultimo_ano = None
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "strong"}

    for el in article.find_all(True):
        txt = el.get_text(" ", strip=True)
        m = RE_NUM_ARP.search(txt)
        if m and el.name in HEADING_TAGS and len(txt) < 100:
            ultimo_num = m.group(1)
            ultimo_ano = m.group(2)

        if el.name == "a" and ultimo_num:
            link_txt = el.get_text(strip=True).lower()
            href = el.get("href", "")
            if link_txt == "download" and href:
                chave = (ultimo_num, ultimo_ano)
                if chave not in resultado:
                    resultado[chave] = href
                ultimo_num = ultimo_ano = None  # consume

    return resultado


def _raspar_paginas_clc(session: requests.Session, stdout) -> dict[tuple[str, str], str]:
    """Raspa todas as páginas CLC e retorna o catálogo combinado."""
    catalogo: dict[tuple[str, str], str] = {}

    for ano_label, url in PAGINAS_CLC:
        stdout.write(f"  Raspando página {ano_label}: {url[:80]}...")
        try:
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            encontrados = _extrair_links_pagina(resp.text)
            catalogo.update(encontrados)
            stdout.write(f"    → {len(encontrados)} ARPs encontradas")
        except requests.RequestException as exc:
            stdout.write(f"    ⚠ Erro: {exc}")
        time.sleep(DELAY)

    return catalogo


# ---------------------------------------------------------------------------
# Fallback: catálogo WordPress REST API
# ---------------------------------------------------------------------------

def _baixar_catalogo_wp(
    session: requests.Session,
    stdout,
    *,
    parar_apos_n_sem_novidade: int = 50,
) -> dict[tuple[str, str], str]:
    """
    Pagina a WP REST API e indexa todos os PDFs com padrão ARP-N-YYYY.

    Para automaticamente após `parar_apos_n_sem_novidade` páginas consecutivas
    sem nenhuma ARP nova — evita varrer centenas de páginas desnecessárias.
    """
    catalogo: dict[tuple[str, str], str] = {}
    pagina = 1
    paginas_sem_novidade = 0
    stdout.write("  Fallback: baixando catálogo via WordPress REST API...")

    while True:
        try:
            resp = session.get(
                WP_MEDIA,
                params={"mime_type": "application/pdf", "per_page": 100, "page": pagina},
                timeout=TIMEOUT,
            )
            if resp.status_code in (400, 404):
                break
            resp.raise_for_status()
            itens = resp.json()
            if not itens:
                break

            total_pag = int(resp.headers.get("X-WP-TotalPages", 1))
            antes = len(catalogo)
            for item in itens:
                url = item.get("source_url", "")
                m = RE_ARP_FNAME.search(url.split("/")[-1])
                if m:
                    chave = (m.group(1), m.group(2))
                    if chave not in catalogo:
                        catalogo[chave] = url

            if len(catalogo) > antes:
                paginas_sem_novidade = 0
            else:
                paginas_sem_novidade += 1

            stdout.write(f"    Página {pagina}/{total_pag} — {len(catalogo)} ARPs indexadas")

            if paginas_sem_novidade >= parar_apos_n_sem_novidade:
                stdout.write(
                    f"    ⏹ Early-exit: {parar_apos_n_sem_novidade} páginas sem novidade — encerrando busca."
                )
                break
            if pagina >= total_pag:
                break
            pagina += 1
            time.sleep(DELAY)
        except requests.RequestException as exc:
            stdout.write(f"    ⚠ Erro na página {pagina}: {exc}")
            break

    return catalogo


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def _parse_numero_arp(numero_arp: str) -> tuple[str, str]:
    partes = numero_arp.strip().split("/")
    if len(partes) != 2:
        raise ValueError(f"Formato inesperado: {numero_arp!r}")
    return str(int(partes[0])), partes[1].strip()


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Busca e preenche link_documento_mppi via scraping das páginas CLC do MPPI."

    def add_arguments(self, parser):
        parser.add_argument("--todos", action="store_true",
            help="Reprocessa também ARPs que já possuem link.")
        parser.add_argument("--arp", metavar="NUMERO_ARP",
            help="Processa apenas esta ARP (ex: 54/2025).")
        parser.add_argument("--dry-run", action="store_true",
            help="Exibe o que faria sem salvar.")
        parser.add_argument("--sem-fallback", action="store_true",
            help="Usa apenas as páginas CLC, sem consultar a WP REST API.")

    def handle(self, *args, **options):
        if not BS4_OK:
            self.stderr.write(
                self.style.ERROR(
                    "BeautifulSoup não instalado. Execute:\n"
                    "  pip install beautifulsoup4 --break-system-packages"
                )
            )
            return

        todos      = options["todos"]
        dry_run    = options["dry_run"]
        sem_fb     = options["sem_fallback"]
        filtro_arp = options.get("arp")

        qs = AtaRegistroPrecos.objects.all()
        if filtro_arp:
            qs = qs.filter(numero_arp__iexact=filtro_arp.strip())
            if not qs.exists():
                raise CommandError(f"ARP '{filtro_arp}' não encontrada.")
        if not todos:
            qs = qs.filter(link_documento_mppi="")

        total = qs.count()
        prefixo = "[DRY-RUN] " if dry_run else ""
        self.stdout.write(
            self.style.MIGRATE_HEADING(f"\n{prefixo}Processando {total} ARP(s)...\n")
        )

        with requests.Session() as session:
            session.headers.update(HEADERS)

            # 1. Raspa páginas CLC
            catalogo = _raspar_paginas_clc(session, self.stdout)
            self.stdout.write(
                self.style.SUCCESS(f"\n  Total no catálogo CLC: {len(catalogo)} ARPs\n")
            )

            # 2. Fallback WP API para ARPs ainda sem link
            if not sem_fb:
                pendentes = []
                for arp in qs.iterator():
                    try:
                        num, ano = _parse_numero_arp(arp.numero_arp)
                        if (num, ano) not in catalogo:
                            pendentes.append((num, ano))
                    except ValueError:
                        pass

                if pendentes:
                    self.stdout.write(
                        f"  {len(pendentes)} ARP(s) não encontradas no CLC — "
                        f"tentando WP REST API...\n"
                    )
                    wp_catalogo = _baixar_catalogo_wp(session, self.stdout)
                    # Adiciona ao catálogo apenas o que falta
                    for chave, url in wp_catalogo.items():
                        if chave not in catalogo:
                            catalogo[chave] = url
                    self.stdout.write("")

            # 3. Cruzamento e salvamento
            encontrados = 0
            nao_encontrados = []

            for arp in qs.iterator():
                try:
                    num, ano = _parse_numero_arp(arp.numero_arp)
                except ValueError as exc:
                    self.stderr.write(self.style.WARNING(f"  ✗ {arp.numero_arp} — {exc}"))
                    continue

                url = catalogo.get((num, ano))
                if url:
                    encontrados += 1
                    if dry_run:
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✔ {arp.numero_arp} → {url}")
                        )
                    else:
                        arp.link_documento_mppi = url
                        arp.save(update_fields=["link_documento_mppi"])
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✔ Salvo {arp.numero_arp}: {url}")
                        )
                else:
                    nao_encontrados.append(arp.numero_arp)
                    self.stdout.write(
                        self.style.WARNING(f"  ✗ {arp.numero_arp} — não publicado no MPPI")
                    )

        # Sumário
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Encontrados e {'simulados' if dry_run else 'salvos'}: {encontrados}/{total}"
            )
        )
        if nao_encontrados:
            self.stdout.write(
                self.style.WARNING("Não publicados: " + ", ".join(nao_encontrados))
            )
