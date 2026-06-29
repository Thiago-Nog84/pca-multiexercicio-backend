"""
Management command: vincular_contratos_planilha
================================================
Lê os arquivos de contratos do Portal da Transparência do MPPI (ODS ou HTML)
e preenche Contrato.arp_origem para contratos cuja coluna "Nº do Edital"
menciona uma Ata de Registro de Preços.

Fontes suportadas:
  - .ods (LibreOffice Calc) — exportados de dezembro/2023 e dezembro/2024
  - .html — exportados de dezembro/2025 e maio/2026

Estratégia de matching:
  1. Extrai número_arp (ex: "00014/2025") e número_contrato (ex: "119/2025 FMMPPI")
     do arquivo.
  2. Normaliza numero_contrato removendo prefixos de órgão, espaços e barras extras.
  3. Busca Contrato no banco com numero_contrato que contenha o número base.
  4. Busca AtaRegistroPrecos pelo numero_arp (com ou sem zeros à esquerda).
  5. Se ambos encontrados: preenche Contrato.arp_origem.

Uso:
    python manage.py vincular_contratos_planilha \\
        planilhas/2023-12.ods planilhas/2024-12.ods \\
        planilhas/2025-12.html planilhas/2026-05.html
    python manage.py vincular_contratos_planilha <arquivos> --dry-run
    python manage.py vincular_contratos_planilha <arquivos> --dry-run --relatorio
"""
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Regex para extrair número da ARP da coluna "Nº do Edital" ou do "Objeto"
RE_ARP = re.compile(
    r"(?:ARP|Ata\s+de\s+Registro\s+de\s+Pre[çc]os|Ata)\s*n[°º\.o]?\s*0*(\d+)\s*/\s*(\d{4})",
    re.IGNORECASE,
)

# Normaliza número do contrato: extrai apenas "NNN/AAAA" ou "NNN/AAAA/SUFIXO"
RE_NUM_BASE = re.compile(r"(\d+)\s*/\s*(\d{4})")


def _norm_arp(num: int, ano: int) -> str:
    """Retorna numero_arp no formato utilizado pelo banco: '00014/2025'."""
    return f"{num:05d}/{ano}"


def _extrair_num_base(numero: str) -> str | None:
    """Extrai a parte 'NNN/AAAA' de um número de contrato com sufixo de órgão."""
    m = RE_NUM_BASE.search(numero)
    if m:
        return f"{int(m.group(1))}/{m.group(2)}"
    return None


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_html(path: str) -> list[dict]:
    """Extrai linhas de contrato de arquivo HTML (Portal da Transparência)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise CommandError("Instale beautifulsoup4: pip install beautifulsoup4 lxml --break-system-packages")

    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    tables = soup.find_all("table")
    if not tables:
        return []

    rows = tables[0].find_all("tr")
    contratos = []
    for row in rows:
        cells = [td.get_text(" ", strip=True) for td in row.find_all("td")]
        if len(cells) < 4 or not cells[0] or cells[0] in ("Nº", "(a)", "6.2.5. Contratos", ""):
            continue
        numero = cells[0].strip()
        objeto = cells[1].strip() if len(cells) > 1 else ""
        edital = cells[3].strip() if len(cells) > 3 else ""

        arp_m = RE_ARP.search(edital) or RE_ARP.search(objeto)
        if not arp_m:
            continue

        contratos.append({
            "numero":   numero,
            "arp":      _norm_arp(int(arp_m.group(1)), int(arp_m.group(2))),
            "edital":   edital,
            "objeto":   objeto[:120],
        })
    return contratos


def _parse_ods(path: str) -> list[dict]:
    """Extrai linhas de contrato de arquivo ODS (LibreOffice)."""
    try:
        from odf.opendocument import load
        from odf.table import Table, TableRow, TableCell
    except ImportError:
        raise CommandError("Instale odfpy: pip install odfpy --break-system-packages")

    doc = load(path)
    sheet = doc.spreadsheet.getElementsByType(Table)[0]
    rows = sheet.getElementsByType(TableRow)

    def cell_text(cell):
        s = str(cell)
        return re.sub(r"<[^>]+>", " ", s).strip()

    contratos = []
    for row in rows:
        cells = row.getElementsByType(TableCell)
        vals = [cell_text(c) for c in cells]
        if len(vals) < 4 or not vals[0] or vals[0] in ("Nº", "(a)", "6.2.5. Contratos", ""):
            continue
        numero = vals[0].strip()
        objeto = vals[1].strip() if len(vals) > 1 else ""
        edital = vals[3].strip() if len(vals) > 3 else ""

        arp_m = RE_ARP.search(edital) or RE_ARP.search(objeto)
        if not arp_m:
            continue

        contratos.append({
            "numero":   numero,
            "arp":      _norm_arp(int(arp_m.group(1)), int(arp_m.group(2))),
            "edital":   edital,
            "objeto":   objeto[:120],
        })
    return contratos


def _parse_xlsx_painel(path: str) -> list[dict]:
    """
    Lê a aba PAINEL do arquivo XLSX do Painel de Contratos.
    Colunas relevantes:
      [1]  N°            → número do contrato
      [2]  ANO           → ano
      [3]  CONTRATANTE   → PGJ, FMMPPI, FPDC...
      [4]  CÓDIGO        → CONTRATO-NN-AAAA-CONT (chave única)
      [8]  OBJETO        → texto livre (busca ARP se houver)
      [21] ST REQUISIT   → sigla da unidade (CAA, CLC, CPPT...)
    """
    try:
        import openpyxl
    except ImportError:
        raise CommandError("Instale openpyxl: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["PAINEL"] if "PAINEL" in wb.sheetnames else wb.active
    contratos = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        num        = row[1]
        ano        = row[2]
        contrat    = str(row[3] or "").strip()
        objeto     = str(row[8] or "").strip()
        unidade_st = str(row[21] or "").strip()

        if not num or not ano:
            continue

        # Monta número base "NNN/AAAA"
        base = f"{int(num)}/{int(ano)}"

        arp_m = RE_ARP.search(objeto)
        arp = _norm_arp(int(arp_m.group(1)), int(arp_m.group(2))) if arp_m else None

        contratos.append({
            "numero":     f"{int(num)}/{int(ano)}/{contrat}",
            "numero_base": base,
            "arp":         arp,
            "objeto":      objeto[:120],
            "edital":      "",
            "unidade_st":  unidade_st,
        })
    return contratos


def parse_arquivo(path: str) -> list[dict]:
    ext = Path(path).suffix.lower()
    if ext == ".html":
        return _parse_html(path)
    elif ext == ".ods":
        return _parse_ods(path)
    elif ext in (".xlsx", ".xlsm"):
        return _parse_xlsx_painel(path)
    else:
        raise CommandError(f"Formato não suportado: {ext}. Use .html, .ods ou .xlsx")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Vincula Contrato.arp_origem e unidade_requisitante a partir de planilhas do Portal da Transparência"

    def add_arguments(self, parser):
        parser.add_argument(
            "arquivos",
            nargs="+",
            help="Caminhos para os arquivos .ods, .html ou .xlsx (Painel)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Não persiste nada.")
        parser.add_argument("--relatorio", action="store_true", help="Lista todos os matches.")

    def handle(self, *args, **options):
        from apps.contratos.models import Contrato
        from apps.core.models import UnidadeRequisitante
        from apps.srp.models import AtaRegistroPrecos

        dry_run = options["dry_run"]
        relatorio = options["relatorio"]

        if dry_run:
            self.stdout.write(self.style.WARNING("⚠ DRY-RUN — nenhuma alteração será salva\n"))

        # Índices do banco
        # Contratos: todos (não filtra por arp_origem pois o XLSX também pode setar unidade)
        contratos_db: dict[str, list] = {}
        for c in Contrato.objects.only("id", "numero_contrato", "arp_origem_id", "unidade_requisitante_id"):
            base = c.numero_base if hasattr(c, "numero_base") else _extrair_num_base(c.numero_contrato)
            if base:
                contratos_db.setdefault(base, []).append(c)

        # ARPs
        arps_db: dict[str, object] = {}
        for a in AtaRegistroPrecos.objects.only("id", "numero_arp"):
            arps_db[a.numero_arp] = a
            m = RE_NUM_BASE.match(a.numero_arp)
            if m:
                arps_db.setdefault(f"{int(m.group(1))}/{m.group(2)}", a)

        # Unidades por sigla
        unidades_db: dict[str, object] = {
            u.sigla.upper(): u
            for u in UnidadeRequisitante.objects.only("id", "sigla")
        }

        self.stdout.write(f"Contratos no banco: {sum(len(v) for v in contratos_db.values())}")
        self.stdout.write(f"ARPs no banco: {len({a.id for a in arps_db.values()})}")
        self.stdout.write(f"Unidades no banco: {len(unidades_db)}\n")

        # Processa arquivos — separa xlsx (painel) dos demais
        todos_arp: list[dict] = []    # registros com ARP para setar arp_origem
        todos_unidade: list[dict] = [] # registros com unidade para setar unidade_requisitante

        for arq in options["arquivos"]:
            registros = parse_arquivo(arq)
            ext = Path(arq).suffix.lower()
            if ext in (".xlsx", ".xlsm"):
                com_arp = [r for r in registros if r.get("arp")]
                self.stdout.write(
                    f"  {Path(arq).name}: {len(registros)} contratos, "
                    f"{len(com_arp)} com ARP, "
                    f"{sum(1 for r in registros if r.get('unidade_st'))} com unidade"
                )
                todos_arp.extend(com_arp)
                todos_unidade.extend(registros)
            else:
                self.stdout.write(f"  {Path(arq).name}: {len(registros)} contratos com ARP")
                todos_arp.extend(registros)

        # --- Matching ARP ---
        vistos_arp: dict[tuple, dict] = {}
        for r in todos_arp:
            base = r.get("numero_base") or _extrair_num_base(r["numero"])
            if base and r.get("arp"):
                vistos_arp.setdefault((base, r["arp"]), r)

        matches_arp = []
        sem_contrato_arp = []
        sem_arp_db = []

        for (base, num_arp), reg in vistos_arp.items():
            arp_obj = arps_db.get(num_arp)
            cs = [c for c in contratos_db.get(base, []) if not c.arp_origem_id]
            if not arp_obj:
                sem_arp_db.append((reg["numero"], num_arp))
            elif not cs:
                sem_contrato_arp.append((reg["numero"], num_arp))
            else:
                for c in cs:
                    matches_arp.append((c, arp_obj, reg))

        # --- Matching Unidade ---
        vistos_unid: dict[str, dict] = {}
        for r in todos_unidade:
            base = r.get("numero_base") or _extrair_num_base(r["numero"])
            if base and r.get("unidade_st"):
                vistos_unid.setdefault(base, r)

        matches_unid = []
        sem_contrato_unid = []
        sem_unidade_db = []

        for base, reg in vistos_unid.items():
            sigla = reg["unidade_st"].upper()
            unidade_obj = unidades_db.get(sigla)
            cs = [c for c in contratos_db.get(base, []) if not c.unidade_requisitante_id]
            if not unidade_obj:
                sem_unidade_db.append((reg["numero"], sigla))
            elif not cs:
                sem_contrato_unid.append((reg["numero"], sigla))
            else:
                for c in cs:
                    matches_unid.append((c, unidade_obj, reg))

        self.stdout.write(f"\n── ARP ──")
        self.stdout.write(f"Matches arp_origem:    {len(matches_arp)}")
        self.stdout.write(f"Sem contrato no banco: {len(sem_contrato_arp)}")
        self.stdout.write(f"ARP não importada:     {len(sem_arp_db)}")
        self.stdout.write(f"\n── Unidade ──")
        self.stdout.write(f"Matches unidade:       {len(matches_unid)}")
        self.stdout.write(f"Sem contrato no banco: {len(sem_contrato_unid)}")
        self.stdout.write(f"Unidade não encontrada:{len(sem_unidade_db)}\n")

        if relatorio:
            self.stdout.write("\n── Matches ARP ──")
            for c, a, r in matches_arp:
                self.stdout.write(f"  {c.numero_contrato:<35} → ARP {a.numero_arp}")
            self.stdout.write("\n── Matches Unidade (primeiros 30) ──")
            for c, u, r in matches_unid[:30]:
                self.stdout.write(f"  {c.numero_contrato:<35} → {u.sigla}")
            if sem_unidade_db[:10]:
                self.stdout.write("\n── Unidades não encontradas ──")
                for num, sigla in sem_unidade_db[:10]:
                    self.stdout.write(f"  {num:<35} → {sigla} (não existe no banco)")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run concluído."))
            return

        arp_ok = 0
        unid_ok = 0
        with transaction.atomic():
            for c, a, _ in matches_arp:
                c.arp_origem = a
                c.save(update_fields=["arp_origem"])
                arp_ok += 1
            for c, u, _ in matches_unid:
                c.unidade_requisitante = u
                c.save(update_fields=["unidade_requisitante"])
                unid_ok += 1

        self.stdout.write(self.style.SUCCESS(
            f"Concluído: {arp_ok} arp_origem, {unid_ok} unidade_requisitante vinculado(s)."
        ))
