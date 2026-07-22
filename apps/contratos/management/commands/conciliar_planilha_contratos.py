"""
Management command: conciliar_planilha_contratos
=================================================
Concilia os dados da planilha / painel oficial de contratos (CSV ou XLSX)
com os contratos registrados na base Django do MPPI.

Suporta:
  - CSV oficial: 'PAINEL DE CONTRATOS 2026(PAINEL).csv'
  - XLSX oficial: 'PAINEL DE CONTRATOS 2026.xlsx'

Campos conciliados e atualizados:
  - valor_atual (de VALOR ATUALIZADO)
  - valor_inicial (de VALOR DO CONTRATO)
  - data_fim_vigencia (de VIGÊNCIA ATUAL / VIGÊNCIA FINAL)
  - data_assinatura (de ASSINATURA)
  - contratado_razao_social (de CONTRATADO (A))
  - contratado_cnpj_cpf (de CNPJ / CPF)
  - numero_sei (de PGEA)

Possui TRAVA DE SEGURANÇA que detecta e bloqueia colisões de número de edital
(evita sobrescrever contratos distintos que tenham o mesmo número de edital em anos/órgãos diferentes).

Uso:
    python manage.py conciliar_planilha_contratos --dry-run
    python manage.py conciliar_planilha_contratos --aplicar
    python manage.py conciliar_planilha_contratos --planilha "C:\\caminho\\planilha.csv" --aplicar
"""

import csv
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand
from django.db import transaction

try:
    import openpyxl
except ImportError:
    openpyxl = None

from apps.contratos.models import Contrato
from apps.core.models import Orgao

DEFAULT_CSV = r"C:\Users\thiagonogueira\Downloads\PAINEL DE CONTRATOS 2026(PAINEL).csv"
DEFAULT_XLSX = r"C:\Dev\PAINEL DE CONTRATOS 2026.xlsx"

ORGAO_MAP = {
    "PGJ": "PGJ",
    "FMMPPI": "FMMPPI",
    "FMMP": "FMMPPI",
    "FMMP-PI": "FMMPPI",
    "FEPDC": "FPDC",
    "FPDC": "FPDC",
    "FPROCON": "FPDC",
}


def parse_date(val):
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    v = str(val).strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", v)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m2 = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    if m2:
        return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
    return None


def parse_decimal(val):
    if not val:
        return None
    v = str(val).replace("R$", "").replace(".", "").replace(",", ".").strip()
    try:
        return Decimal(v)
    except (InvalidOperation, ValueError):
        return None


def normalizar_cnpj(val):
    if not val:
        return ""
    return re.sub(r"\D", "", str(val))


def sim_text(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, str(a).lower()[:100], str(b).lower()[:100]).ratio()


def canonical_keys(num, ano, contratante, codigo=""):
    """
    Gera conjunto de chaves canônicas para cruzamento preciso entre banco e planilha.
    Ex: ('27/2025/PGJ', 'CONTRATO-27-2025-PGJ', '27/2025')
    """
    keys = set()
    if codigo:
        c_clean = str(codigo).strip().upper()
        keys.add(c_clean)
        m = re.match(r"^(?:CONTRATO|NOTA DE EMPENHO)-(\d+)-(\d{4})-(.+)$", c_clean)
        if m:
            n, a, o = str(int(m.group(1))), m.group(2), ORGAO_MAP.get(m.group(3), m.group(3))
            keys.add(f"{n}/{a}/{o}")
            keys.add(f"{n}/{a}")
            keys.add(f"{int(m.group(1)):02d}/{a}/{o}")
            keys.add(f"{int(m.group(1)):03d}/{a}/{o}")

    if num and ano:
        n_str = str(num).strip()
        n_clean = str(int(n_str)) if n_str.isdigit() else n_str.upper()
        a_clean = str(ano).strip()
        o_clean = ORGAO_MAP.get(str(contratante).strip().upper(), str(contratante).strip().upper())
        if o_clean:
            keys.add(f"{n_clean}/{a_clean}/{o_clean}")
            keys.add(f"{n_clean}/{a_clean}")
            keys.add(f"CONTRATO-{n_clean}-{a_clean}-{o_clean}")
            keys.add(f"CONTRATO-{n_str}-{a_clean}-{o_clean}")
        else:
            keys.add(f"{n_clean}/{a_clean}")
            keys.add(f"{n_str}/{a_clean}")

    return {k for k in keys if k}


class Command(BaseCommand):
    help = "Concilia dados do Painel de Contratos oficial (CSV/XLSX) com a base Django"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula a conciliação sem alterar o banco",
        )
        parser.add_argument(
            "--aplicar",
            action="store_true",
            default=False,
            help="Grava as alterações no banco de dados",
        )
        parser.add_argument(
            "--planilha",
            type=str,
            default=None,
            help="Caminho para o arquivo CSV ou XLSX (padrão: Painel CSV de Downloads)",
        )

    def handle(self, *args, **options):
        aplicar = options["aplicar"]
        dry_run = options["dry_run"] or not aplicar
        caminho = options["planilha"]

        if not caminho:
            if os.path.exists(DEFAULT_CSV):
                caminho = DEFAULT_CSV
            elif os.path.exists(DEFAULT_XLSX):
                caminho = DEFAULT_XLSX
            else:
                self.stderr.write(self.style.ERROR(f"Nenhum arquivo encontrado em:\n  {DEFAULT_CSV}\n  {DEFAULT_XLSX}"))
                return

        if not os.path.exists(caminho):
            self.stderr.write(self.style.ERROR(f"Arquivo não encontrado: {caminho}"))
            return

        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(f"CONCILIACAO PAINEL DE CONTRATOS <-> BASE DJANGO")
        self.stdout.write(f"{'='*70}")
        self.stdout.write(f"Arquivo: {caminho}")
        self.stdout.write(f"Modo:    {'SIMULAÇÃO (DRY-RUN)' if dry_run else self.style.SUCCESS('APLICAR NO BANCO (ATÔMICO)')}\n")

        rows_dict = self.carregar_linhas(caminho)
        if not rows_dict:
            self.stderr.write(self.style.ERROR("Nenhuma linha válida encontrada no arquivo."))
            return

        # Monta índice do arquivo por chaves canônicas
        file_by_key = {}
        for idx, r in enumerate(rows_dict, start=2):
            num = r.get("num", "")
            ano = r.get("ano", "")
            contratante = r.get("contratante", "")
            codigo = r.get("codigo", "")

            for ckey in canonical_keys(num, ano, contratante, codigo):
                if ckey not in file_by_key:
                    file_by_key[ckey] = (idx, r)

        db_contratos = list(Contrato.objects.select_related("orgao").all())

        atualizados = 0
        sem_alteracao = 0
        colisoes = 0
        nao_encontrados = 0

        with transaction.atomic():
            for ct in db_contratos:
                n = ct.numero_contrato or ""
                m = re.match(r"^0*(\d+)/(\d{4})(?:/([A-Z0-9/-]+))?$", n.strip().upper())
                if m:
                    num, ano, org = m.group(1), m.group(2), (m.group(3) or "")
                    if ct.orgao and ct.orgao.sigla:
                        org = ct.orgao.sigla
                    cands = canonical_keys(num, ano, org, codigo=n)
                else:
                    cands = canonical_keys("", "", "", codigo=n)

                match_tuple = None
                for cand in cands:
                    if cand in file_by_key:
                        match_tuple = file_by_key[cand]
                        break

                # Fallback seguro por PGEA / numero_sei
                if not match_tuple and ct.numero_sei:
                    pgea_clean = ct.numero_sei.strip().upper()
                    for idx, r in enumerate(rows_dict, start=2):
                        r_pgea = r.get("pgea", "").upper()
                        if r_pgea and pgea_clean in r_pgea:
                            match_tuple = (idx, r)
                            break

                if not match_tuple:
                    nao_encontrados += 1
                    continue

                idx, r = match_tuple
                val_atual_file = r.get("valor_atualizado") or r.get("valor_contrato")
                val_orig_file = r.get("valor_contrato")
                dt_fim_file = r.get("vigencia_atual") or r.get("vigencia_fim")
                dt_ass_file = r.get("assinatura")
                cnpj_file = r.get("cnpj")
                razao_file = r.get("contratado")
                pgea_file = r.get("pgea")

                # TRAVA DE SEGURANÇA: Bloqueia falsos positivos se CNPJ, Valor e Fornecedor divergirem totalmente
                cnpj_bd = normalizar_cnpj(ct.contratado_cnpj_cpf)
                cnpj_diff = bool(cnpj_file and cnpj_bd and cnpj_file != cnpj_bd)
                val_bd = ct.valor_atual or ct.valor_inicial or Decimal("0")
                val_target = val_atual_file or val_orig_file or Decimal("0")
                ratio_val = (float(val_target) / float(val_bd)) if val_bd > 0 and val_target > 0 else 1.0
                val_diff = (ratio_val > 2.5 or ratio_val < 0.4)
                sim_razao = sim_text(razao_file, ct.contratado_razao_social)

                # Trava se Razao Social diverge MUITO (sim_razao < 0.3) e CNPJ divergem,
                # OU se (CNPJ diverge E val_diff E sim_razao < 0.5)
                if (cnpj_diff and sim_razao < 0.3) or (cnpj_diff and val_diff and sim_razao < 0.5):
                    colisoes += 1
                    s_razao = str(razao_file).encode("ascii", "replace").decode("ascii")
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [BLOQUEADO - Colisao de Edital]: BD PK={ct.pk} ({ct.numero_contrato}) "
                            f"diverge de Linha {idx} ({s_razao})"
                        )
                    )
                    continue

                diffs = {}
                if val_atual_file and ct.valor_atual and abs(val_atual_file - ct.valor_atual) > Decimal("0.05"):
                    diffs["valor_atual"] = (ct.valor_atual, val_atual_file)
                if val_orig_file and ct.valor_inicial and abs(val_orig_file - ct.valor_inicial) > Decimal("0.05"):
                    diffs["valor_inicial"] = (ct.valor_inicial, val_orig_file)
                if dt_fim_file and ct.data_fim_vigencia and dt_fim_file != ct.data_fim_vigencia:
                    diffs["data_fim_vigencia"] = (ct.data_fim_vigencia, dt_fim_file)
                if dt_ass_file and ct.data_assinatura and dt_ass_file != ct.data_assinatura:
                    diffs["data_assinatura"] = (ct.data_assinatura, dt_ass_file)
                if cnpj_file and ct.contratado_cnpj_cpf and cnpj_file != normalizar_cnpj(ct.contratado_cnpj_cpf):
                    diffs["contratado_cnpj_cpf"] = (ct.contratado_cnpj_cpf, cnpj_file)
                if razao_file and ct.contratado_razao_social and razao_file.lower() != ct.contratado_razao_social.lower():
                    diffs["contratado_razao_social"] = (ct.contratado_razao_social, razao_file)
                if pgea_file and not ct.numero_sei:
                    diffs["numero_sei"] = (ct.numero_sei, pgea_file)

                if diffs:
                    atualizados += 1
                    s_num = str(ct.numero_contrato).encode("ascii", "replace").decode("ascii")
                    self.stdout.write(self.style.SUCCESS(f"  [OK] PK={ct.pk} | {s_num} (Linha {idx})"))
                    for campo, (ant, nov) in diffs.items():
                        s_ant = str(ant).encode("ascii", "replace").decode("ascii")
                        s_nov = str(nov).encode("ascii", "replace").decode("ascii")
                        self.stdout.write(f"      {campo}: {s_ant} -> {s_nov}")

                    if aplicar:
                        if "valor_atual" in diffs:
                            ct.valor_atual = diffs["valor_atual"][1]
                        if "valor_inicial" in diffs:
                            ct.valor_inicial = diffs["valor_inicial"][1]
                        if "data_fim_vigencia" in diffs:
                            ct.data_fim_vigencia = diffs["data_fim_vigencia"][1]
                        if "data_assinatura" in diffs:
                            ct.data_assinatura = diffs["data_assinatura"][1]
                        if "contratado_cnpj_cpf" in diffs:
                            ct.contratado_cnpj_cpf = diffs["contratado_cnpj_cpf"][1]
                        if "contratado_razao_social" in diffs:
                            ct.contratado_razao_social = diffs["contratado_razao_social"][1]
                        if "numero_sei" in diffs:
                            ct.numero_sei = diffs["numero_sei"][1]
                        ct.save()
                else:
                    sem_alteracao += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(f"\n{'='*70}")
        self.stdout.write(
            self.style.SUCCESS(
                f"CONCILIACAO CONCLUIDA!\n"
                f"  - Contratos no BD:                {len(db_contratos)}\n"
                f"  - Contratos reconciliados/updates: {atualizados}\n"
                f"  - Contratos sem divergencia:       {sem_alteracao}\n"
                f"  - Colisoes de numero bloqueadas:  {colisoes}\n"
                f"  - Nao encontrados no arquivo:     {nao_encontrados}"
            )
        )
        if dry_run and atualizados > 0:
            self.stdout.write(self.style.WARNING("\nPara aplicar as alterações no banco, execute com '--aplicar'."))
        self.stdout.write(f"{'='*70}\n")

    def carregar_linhas(self, caminho):
        if caminho.lower().endswith(".csv"):
            return self.carregar_csv(caminho)
        elif caminho.lower().endswith(".xlsx"):
            return self.carregar_xlsx(caminho)
        return []

    def carregar_csv(self, caminho):
        linhas = []
        with open(caminho, mode="r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=";")
            for r in reader:
                keys = list(r.keys())
                linhas.append({
                    "tipo": r.get(keys[0], "").strip(),
                    "num": r.get(keys[1], "").strip(),
                    "ano": r.get(keys[2], "").strip(),
                    "contratante": r.get(keys[3], "").strip(),
                    "codigo": r.get(keys[4], "").strip(),
                    "pgea": r.get(keys[5], "").strip(),
                    "objeto": r.get(keys[8], "").strip(),
                    "cnpj": normalizar_cnpj(r.get(keys[9], "")),
                    "contratado": r.get(keys[10], "").strip(),
                    "assinatura": parse_date(r.get(keys[11], "")),
                    "vigencia_fim": parse_date(r.get(keys[12], "")),
                    "vigencia_atual": parse_date(r.get(keys[13], "")),
                    "valor_contrato": parse_decimal(r.get(keys[17], "")),
                    "valor_atualizado": parse_decimal(r.get(keys[19], "") or r.get(keys[18], "")),
                })
        return linhas

    def carregar_xlsx(self, caminho):
        if not openpyxl:
            self.stderr.write("Instale openpyxl: pip install openpyxl")
            return []
        wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
        ws = wb.active
        linhas = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0 or not row or not row[0]:
                continue
            linhas.append({
                "tipo": str(row[0]).strip(),
                "num": str(row[1]).strip() if row[1] else "",
                "ano": str(row[2]).strip() if row[2] else "",
                "contratante": str(row[3]).strip() if len(row) > 3 and row[3] else "",
                "codigo": str(row[4]).strip() if len(row) > 4 and row[4] else "",
                "pgea": str(row[5]).strip() if len(row) > 5 and row[5] else "",
                "objeto": str(row[8]).strip() if len(row) > 8 and row[8] else "",
                "cnpj": normalizar_cnpj(row[9]) if len(row) > 9 else "",
                "contratado": str(row[10]).strip() if len(row) > 10 and row[10] else "",
                "assinatura": parse_date(row[11]) if len(row) > 11 else None,
                "vigencia_fim": parse_date(row[12]) if len(row) > 12 else None,
                "vigencia_atual": parse_date(row[13]) if len(row) > 13 else None,
                "valor_contrato": parse_decimal(row[17]) if len(row) > 17 else None,
                "valor_atualizado": parse_decimal(row[19]) if len(row) > 19 else None,
            })
        return linhas
