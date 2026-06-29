"""
Management command: vincular_contratos_arp_origem
==================================================
Identifica contratos decorrentes de ARPs e preenche os campos:
  - Contrato.arp_origem         → ARP própria (MPPI como gerenciadora)
  - Contrato.arp_externa_origem → ARP externa (MPPI como aderente/carona)

Estratégias (aplicadas em cascata):

  P1 — Varredura do campo `objeto`:
       Detecta padrões textuais como:
         "ata de registro de preços nº 02/2025"
         "decorrente da ata nº 3/2024"
         "adesão nº 07/2025 à ata de registro de preços nº 01/2025"
       Associa o número encontrado ao registro em AtaRegistroPrecos ou ARPExterna.

  P2 — API dadosabertos.compras.gov.br:
       Consulta /modulo-arp/3_consultarContratosARP?codigoUnidadeGerenciadora=926092
       Cruza por numero_contrato + CNPJ do contratado.
       Para cada match cria/atualiza ContratoARP e popula arp_origem.

  P3 — PNCP via link_ata_pncp das ARPs cadastradas:
       Para cada AtaRegistroPrecos com link_ata_pncp preenchido, consulta
       GET /orgaos/{cnpj}/compras/{ano}/{seq}/atas/{ata}/contratos e cruza
       com Contrato local.

Uso:
    python manage.py vincular_contratos_arp_origem --dry-run
    python manage.py vincular_contratos_arp_origem
    python manage.py vincular_contratos_arp_origem --uasg 926092 --ano-inicio 2024
    python manage.py vincular_contratos_arp_origem --so-texto   # só P1
    python manage.py vincular_contratos_arp_origem --relatorio  # gera XLSX
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

BASE_DB   = "https://dadosabertos.compras.gov.br"
PNCP_API  = "https://pncp.gov.br/api/pncp/v1"
TIMEOUT   = 30
PAGE_SIZE = 500

# ---------------------------------------------------------------------------
# Regex para varredura textual do campo `objeto`
# ---------------------------------------------------------------------------

# Captura: "ata de registro de preços nº 02/2025" / "ata nº 2/2025"
RE_ARP_PROPRIO = re.compile(
    r"\bata\b.*?\bn[°º\.o]\s*0*(\d+)\s*/\s*(\d{4})",
    re.IGNORECASE | re.DOTALL,
)

# Captura: "adesão nº 07/2025 à ata de registro de preços nº 01/2025"
# Grupo 1=num_adesao, Grupo 2=ano_adesao, Grupo 3=num_ata (opcional), Grupo 4=ano_ata
RE_ADESAO = re.compile(
    r"\bades[aã]o\b.*?\bn[°º\.o]\s*0*(\d+)\s*/\s*(\d{4})"
    r"(?:.*?\bata\b.*?\bn[°º\.o]\s*0*(\d+)\s*/\s*(\d{4}))?",
    re.IGNORECASE | re.DOTALL,
)

# Número de contrato normalizado
RE_NUMERO_CONTRATO = re.compile(r"(\d+)/((19|20)\d{2})")


def _norm_numero(num: str) -> str:
    m = RE_NUMERO_CONTRATO.search(str(num or ""))
    if m:
        seq = m.group(1).lstrip("0") or "0"
        return f"{seq}/{m.group(2)}"
    return str(num or "").strip().upper()


def _parse_data(valor):
    if not valor:
        return None
    s = str(valor).strip()
    for fmt in ["%Y-%m-%d", "%d/%m/%Y"]:
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(valor):
    if valor is None:
        return Decimal("0")
    try:
        return Decimal(str(valor).replace(",", ".").strip())
    except InvalidOperation:
        return Decimal("0")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Vincula Contrato.arp_origem / arp_externa_origem detectando ARPs no objeto e na API"

    def add_arguments(self, parser):
        parser.add_argument("--uasg", default="926092",
                            help="UASG do MPPI (padrão: 926092)")
        parser.add_argument("--ano-inicio", type=int, default=2024,
                            help="Ano mínimo de vigência das ARPs (padrão: 2024)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Simula sem salvar")
        parser.add_argument("--force", action="store_true",
                            help="Sobrescreve vínculos já existentes")
        parser.add_argument("--so-texto", action="store_true",
                            help="Executa apenas a varredura textual (P1), sem API")
        parser.add_argument("--relatorio", action="store_true",
                            help="Gera XLSX com resultado da identificação")
        parser.add_argument("--debug", action="store_true",
                            help="Exibe detalhes das requisições API")

    def handle(self, *args, **options):
        from apps.contratos.models import Contrato
        from apps.srp.models import AtaRegistroPrecos, ARPExterna, ContratoARP

        self.dry_run = options["dry_run"]
        self.force   = options["force"]
        self.debug   = options["debug"]
        uasg         = options["uasg"]
        ano_inicio   = options["ano_inicio"]

        if self.dry_run:
            self.stdout.write(self.style.WARNING("⚠ DRY-RUN — nenhuma alteração será salva\n"))

        # Índices em memória
        arps_proprias   = {a.numero_arp: a for a in AtaRegistroPrecos.objects.all()}
        arps_externas   = {
            f"{a.numero_arp_origem}|{a.orgao_gerenciador_cnpj}": a
            for a in ARPExterna.objects.all()
        }
        contratos_qs    = Contrato.objects.select_related("arp_origem", "arp_externa_origem")
        contratos_db    = list(contratos_qs)

        stats = {
            "p1_texto_proprio": 0,
            "p1_texto_externo": 0,
            "p2_api": 0,
            "p3_pncp": 0,
            "ja_vinculados": 0,
            "sem_match": 0,
        }
        linhas_relatorio = []

        # ── P1 — Varredura textual ────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n── P1: Varredura textual do campo objeto ──"))
        for c in contratos_db:
            if c.arp_origem_id and not self.force:
                stats["ja_vinculados"] += 1
                continue
            if c.arp_externa_origem_id and not self.force:
                stats["ja_vinculados"] += 1
                continue

            obj = c.objeto or ""

            # Detecta adesão (carona recebida) PRIMEIRO — tem "adesão" + "ata"
            m_adesao = RE_ADESAO.search(obj)
            if m_adesao and ("ades" in obj.lower()):
                # Tenta mapear para ARPExterna; se não existir, cria pendência
                num_ata  = m_adesao.group(3) or m_adesao.group(1)
                ano_ata  = m_adesao.group(4) or m_adesao.group(2)
                chave = f"{int(num_ata)}/{ano_ata}"
                linhas_relatorio.append({
                    "numero_contrato": c.numero_contrato,
                    "objeto": (obj or "")[:120],
                    "tipo_arp": "ADESÃO (carona recebida)",
                    "arp_detectada": chave,
                    "vinculo_atual": (
                        f"ARPExterna:{c.arp_externa_origem.numero_arp_origem}"
                        if c.arp_externa_origem_id else "—"
                    ),
                    "status": "já vinculado" if c.arp_externa_origem_id else "pendente",
                })
                stats["p1_texto_externo"] += 1
                self.stdout.write(
                    f"  [ADESÃO] {c.numero_contrato} → ARP externa {chave}"
                )
                continue

            # Detecta ARP própria
            m_arp = RE_ARP_PROPRIO.search(obj)
            if m_arp:
                num = m_arp.group(1)
                ano = m_arp.group(2)
                chave_busca = f"{int(num)}/{ano}"
                # Tenta match por número puro ou zero-padded
                arp_obj = (
                    arps_proprias.get(chave_busca)
                    or arps_proprias.get(f"{int(num):03d}/{ano}")
                    or arps_proprias.get(f"{int(num):05d}/{ano}")
                )
                linhas_relatorio.append({
                    "numero_contrato": c.numero_contrato,
                    "objeto": (obj or "")[:120],
                    "tipo_arp": "ARP PRÓPRIA",
                    "arp_detectada": chave_busca,
                    "vinculo_atual": (
                        f"ARP:{c.arp_origem.numero_arp}" if c.arp_origem_id else "—"
                    ),
                    "status": "match" if arp_obj else "ARP não no banco",
                })
                if arp_obj:
                    stats["p1_texto_proprio"] += 1
                    self._vincular_proprio(c, arp_obj)
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [ARP PRÓPRIA] {c.numero_contrato} → "
                            f"ARP {chave_busca} não encontrada no banco"
                        )
                    )
                continue

        # ── P2 — API dadosabertos ─────────────────────────────────────────
        if not options["so_texto"]:
            self.stdout.write(
                self.style.MIGRATE_HEADING("\n── P2: API dadosabertos.compras.gov.br ──")
            )
            contratos_api = self._buscar_contratos_api(uasg, ano_inicio)
            self.stdout.write(f"  {len(contratos_api)} contratos na API")

            # Índice local: numero_norm + CNPJ → Contrato
            idx_local = {}
            for c in contratos_db:
                chave = (_norm_numero(c.numero_contrato), (c.contratado_cnpj_cpf or "").strip())
                idx_local.setdefault(chave, []).append(c)

            for dados in contratos_api:
                num_api   = dados.get("numeroContrato") or dados.get("numero") or ""
                cnpj_api  = str(dados.get("niFornecedor") or dados.get("cnpjFornecedor") or "").strip()
                num_arp   = dados.get("numeroAtaRegistroPreco") or dados.get("numeroAta") or ""

                if not num_arp:
                    continue

                _num_arp_str = str(num_arp or "")
                if "/" in _num_arp_str:
                    _seq = re.sub(r"\D", "", _num_arp_str.split("/")[0]) or "0"
                    _ano = _num_arp_str.split("/")[-1]
                    arp_obj = (
                        arps_proprias.get(_num_arp_str)
                        or arps_proprias.get(f"{int(_seq):03d}/{_ano}")
                        or arps_proprias.get(f"{int(_seq)}/{_ano}")
                    )
                else:
                    arp_obj = None

                chave_local = (_norm_numero(num_api), cnpj_api)
                matches = idx_local.get(chave_local, [])

                for c in matches:
                    if c.arp_origem_id and not self.force:
                        continue
                    if arp_obj:
                        stats["p2_api"] += 1
                        self._vincular_proprio(c, arp_obj)
                        if self.debug:
                            self.stdout.write(
                                f"  [API] {c.numero_contrato} → ARP {num_arp}"
                            )

                if not matches and self.debug:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [API] Sem match local: contrato {num_api} "
                            f"(CNPJ {cnpj_api}) — ARP {num_arp}"
                        )
                    )

            # ── P3 — PNCP via link_ata_pncp ──────────────────────────────
            RE_LINK = re.compile(r"pncp\.gov\.br/app/atas/(\d+)/(\d+)/(\d+)/(\d+)")
            arps_com_link = [
                a for a in arps_proprias.values()
                if a.link_ata_pncp and RE_LINK.search(a.link_ata_pncp)
            ]
            if arps_com_link:
                self.stdout.write(
                    self.style.MIGRATE_HEADING(
                        f"\n── P3: PNCP ({len(arps_com_link)} ARPs com link) ──"
                    )
                )
                for arp in arps_com_link:
                    m = RE_LINK.search(arp.link_ata_pncp)
                    if not m:
                        continue
                    cnpj, ano, compra_seq, ata_seq = m.groups()
                    contratos_pncp = self._buscar_contratos_pncp(
                        cnpj, ano, compra_seq, ata_seq
                    )
                    for dados in contratos_pncp:
                        num  = dados.get("numeroContratoEmpenho") or dados.get("numero") or ""
                        forn = (dados.get("fornecedor") or {})
                        cnpj_f = str(forn.get("cnpjCpf") or forn.get("ni") or "").strip()
                        chave  = (_norm_numero(num), cnpj_f)
                        for c in idx_local.get(chave, []):
                            if c.arp_origem_id and not self.force:
                                continue
                            stats["p3_pncp"] += 1
                            self._vincular_proprio(c, arp)

        # ── Relatório XLSX ────────────────────────────────────────────────
        if options["relatorio"] and linhas_relatorio:
            self._gerar_relatorio(linhas_relatorio)

        # ── Resumo ────────────────────────────────────────────────────────
        total_vinculados = stats["p1_texto_proprio"] + stats["p2_api"] + stats["p3_pncp"]
        self.stdout.write(f"\n{'─'*60}")
        self.stdout.write(self.style.SUCCESS(
            f"{'[DRY-RUN] ' if self.dry_run else ''}Resultado:\n"
            f"  P1 texto (ARP própria):   {stats['p1_texto_proprio']}\n"
            f"  P1 texto (adesão/carona): {stats['p1_texto_externo']}\n"
            f"  P2 API dadosabertos:      {stats['p2_api']}\n"
            f"  P3 PNCP:                  {stats['p3_pncp']}\n"
            f"  ─────────────────────────────\n"
            f"  Total vinculados:         {total_vinculados}\n"
            f"  Já vinculados (skip):     {stats['ja_vinculados']}\n"
        ))

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _vincular_proprio(self, contrato, arp_obj):
        """Seta contrato.arp_origem = arp_obj."""
        if self.dry_run:
            self.stdout.write(
                f"  [DRY] {contrato.numero_contrato} → ARP {arp_obj.numero_arp}"
            )
            return
        contrato.arp_origem = arp_obj
        contrato.save(update_fields=["arp_origem"])
        self.stdout.write(
            self.style.SUCCESS(
                f"  ✓ {contrato.numero_contrato} → ARP {arp_obj.numero_arp}"
            )
        )

    # ------------------------------------------------------------------
    # API dadosabertos
    # ------------------------------------------------------------------

    def _buscar_contratos_api(self, uasg, ano_inicio):
        resultados = []
        ano_fim = date.today().year
        endpoints = [
            "/modulo-arp/3_consultarContratosARP",
            "/modulo-contrato/1_consultarContrato",
        ]
        for ep in endpoints:
            dados = self._get_paginado(
                ep,
                {
                    "codigoUnidadeGerenciadora": uasg,
                    "dataAssinaturaMin": f"{ano_inicio}-01-01",
                    "dataAssinaturaMax": f"{ano_fim}-12-31",
                },
            )
            if dados:
                self.stdout.write(
                    self.style.SUCCESS(f"  Endpoint: {ep} ({len(dados)} registros)")
                )
                resultados.extend(dados)
        return resultados

    def _get_paginado(self, endpoint, params_base):
        resultados = []
        pagina = 1
        while True:
            params = {**params_base, "pagina": pagina, "tamanhoPagina": PAGE_SIZE}
            url = f"{BASE_DB}{endpoint}"
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT)
                if resp.status_code != 200:
                    return resultados
                payload = resp.json()
            except Exception as exc:
                if self.debug:
                    self.stdout.write(f"  [DEBUG] Erro {endpoint}: {exc}")
                return resultados

            if isinstance(payload, list):
                resultados.extend(payload)
                break
            dados = (
                payload.get("resultado")
                or payload.get("data")
                or payload.get("itens")
                or []
            )
            resultados.extend(dados)
            if not dados or payload.get("paginasRestantes", 0) == 0:
                break
            pagina += 1
        return resultados

    # ------------------------------------------------------------------
    # PNCP
    # ------------------------------------------------------------------

    def _buscar_contratos_pncp(self, cnpj, ano, compra_seq, ata_seq):
        for url in [
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/atas/{ata_seq}/contratos",
            f"{PNCP_API}/orgaos/{cnpj}/compras/{ano}/{compra_seq}/contratos",
        ]:
            try:
                resp = requests.get(url, timeout=TIMEOUT)
                if resp.status_code == 200:
                    payload = resp.json()
                    if isinstance(payload, list):
                        return payload
                    return (
                        payload.get("data")
                        or payload.get("resultado")
                        or []
                    )
            except Exception:
                pass
        return []

    # ------------------------------------------------------------------
    # Relatório XLSX
    # ------------------------------------------------------------------

    def _gerar_relatorio(self, linhas):
        import os
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            self.stdout.write(self.style.ERROR("openpyxl não instalado."))
            return

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Contratos ARP"

        fill_h   = PatternFill("solid", start_color="1F3864")
        fill_ext = PatternFill("solid", start_color="FFF2CC")   # amarelo — adesão
        fill_own = PatternFill("solid", start_color="E2EFDA")   # verde — própria
        fill_pnd = PatternFill("solid", start_color="FCE4D6")   # salmão — pendente

        headers = ["Nº Contrato", "Tipo ARP", "ARP Detectada", "Vínculo Atual", "Status", "Objeto (120 chars)"]
        for col, h in enumerate(headers, 1):
            c = ws.cell(1, col, h)
            c.font = Font(bold=True, color="FFFFFF", name="Arial")
            c.fill = fill_h
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        col_widths = [20, 22, 18, 22, 16, 60]
        from openpyxl.utils import get_column_letter
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

        for r, linha in enumerate(linhas, 2):
            fill = (
                fill_ext if "ADESÃO" in linha.get("tipo_arp", "")
                else fill_own if linha.get("status") == "match"
                else fill_pnd
            )
            for col, campo in enumerate(
                ["numero_contrato", "tipo_arp", "arp_detectada",
                 "vinculo_atual", "status", "objeto"],
                1
            ):
                cell = ws.cell(r, col, linha.get(campo, ""))
                cell.fill = fill
                cell.font = Font(name="Arial", size=9)
                cell.alignment = Alignment(wrap_text=True, vertical="center")

        default_out = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "data", "contratos",
                "contratos_arp_identificados.xlsx",
            )
        )
        os.makedirs(os.path.dirname(default_out), exist_ok=True)
        wb.save(default_out)
        self.stdout.write(self.style.SUCCESS(f"\nRelatório: {default_out}"))
