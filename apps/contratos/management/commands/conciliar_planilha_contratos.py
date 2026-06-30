"""
Management command: conciliar_planilha_contratos
=================================================
Concilia os dados da planilha 'PAINEL DE CONTRATOS 2026.xlsx'
com os contratos registrados na base Django.

Campos atualizados:
  - valor_atual, valor_inicial (de VALOR ATUALIZADO / VALOR DO CONTRATO)
  - data_fim_vigencia (de VIGÊNCIA ATUAL)
  - objeto (de OBJETO)
  - contratado_razao_social (de CONTRATADO(A))
  - contratado_cnpj_cpf (de CNPJ/CPF)
  - numero_sei / PGEA

Chave de correspondência: número + ano + órgão (CONTRATANTE)
"""

import os
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.db import transaction

try:
    import openpyxl
except ImportError:
    openpyxl = None

from apps.contratos.models import Contrato
from apps.core.models import Orgao

PLANILHA = r"C:\Dev\PAINEL DE CONTRATOS 2026.xlsx"

# Mapeamento de sigla da planilha → sigla do Orgao no banco
ORGAO_MAP = {
    "PGJ": "PGJ",
    "FMMPPI": "FMMPPI",
    "FEPDC": "FPDC",   # Na planilha aparece FEPDC; no banco é FPDC
    "FPDC": "FPDC",
    "FMMP": "FMMPPI",
    "FPROCON": "FPDC",
}

# Mapeamento modalidade/lei da planilha → tipo Contrato
TIPO_MAP = {
    "DISPENSA": "fornecimento",
    "INEXIGIBILIDADE": "fornecimento",
    "PREGÃO ELETRÔNICO": "fornecimento",
    "PREGAO ELETRONICO": "fornecimento",
    "CONCORRÊNCIA": "obra",
    "CONCORRENCIA": "obra",
}

TIPO_CONTRATO_MAP = {
    "LOCAÇÃO": "locacao",
    "LOCACAO": "locacao",
    "SERVIÇOS CONTINUADOS": "servico_continuo",
    "SERVICOS CONTINUADOS": "servico_continuo",
    "SERVIÇO CONTINUADO": "servico_continuo",
    "SERVICO CONTINUADO": "servico_continuo",
    "SERVIÇOS NÃO CONTINUADOS": "servico_nao_continuo",
    "SERVICO NAO CONTINUO": "servico_nao_continuo",
    "OBRAS": "obra",
    "ENGENHARIA": "obra",
    "TIC": "solucao_ti",
    "TECNOLOGIA DA INFORMAÇÃO": "solucao_ti",
    "TECNOLOGIA": "solucao_ti",
    "FORNECIMENTO": "fornecimento",
}


def parse_date(val):
    if not val:
        return None
    if isinstance(val, (date, datetime)):
        return val.date() if isinstance(val, datetime) else val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def parse_decimal(val):
    if not val:
        return None
    try:
        return Decimal(str(val).replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None


def normalizar_numero(num, orgao_sigla):
    """Formata o número do contrato para cruzamento com a base."""
    if not num:
        return []
    n = str(num).strip()
    candidatos = [n]
    # Formatos alternativos que podem estar no banco
    candidatos.extend([
        f"{n}/2025",
        f"{n}/2025/{orgao_sigla}",
        f"{n}/2025/PGJ",
        f"{n}/2025/FPDC",
        f"{n}/2025/FMMP/PI",
        f"{n}/2025/FMMPPI",
        f"{n}/2026",
        f"{n}/2026/{orgao_sigla}",
        f"{n}/2026/FPDC",
        f"{n}/2026/FMMPPI",
        f"Contrato nº {n}/2025",
        f"Contrato nº {n}/2026",
    ])
    return candidatos


class Command(BaseCommand):
    help = "Concilia contratos da base com a planilha PAINEL DE CONTRATOS 2026.xlsx"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula a conciliação sem salvar alterações",
        )
        parser.add_argument(
            "--planilha",
            type=str,
            default=PLANILHA,
            help="Caminho para a planilha XLSX",
        )
        parser.add_argument(
            "--anos",
            nargs="+",
            type=int,
            default=[2025, 2026],
            help="Anos a processar",
        )

    def handle(self, *args, **options):
        if not openpyxl:
            self.stderr.write("Instale openpyxl: pip install openpyxl")
            return

        planilha = options["planilha"]
        dry_run = options["dry_run"]
        anos = options["anos"]

        if not os.path.exists(planilha):
            self.stderr.write(f"Planilha não encontrada: {planilha}")
            return

        self.stdout.write(f"\n{'='*65}")
        self.stdout.write(f"CONCILIAÇÃO PAINEL DE CONTRATOS ↔ BASE DJANGO")
        self.stdout.write(f"{'='*65}")
        self.stdout.write(f"Anos: {anos} | Modo: {'SIMULAÇÃO' if dry_run else 'GRAVAÇÃO'}\n")

        wb = openpyxl.load_workbook(planilha, read_only=True, data_only=True)
        ws = wb["PAINEL"]

        atualizados = 0
        criados = 0
        nao_encontrados = []
        erros = []

        # Cache de órgãos
        orgaos_db = {o.sigla: o for o in Orgao.objects.all()}

        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i == 0:
                continue  # skip header
            if not row[0]:
                continue

            tipo_planilha = str(row[0]).strip().upper()
            if tipo_planilha not in ("CONTRATO",):
                continue  # Só processa CONTRATO (ignora NE)

            try:
                ano = int(row[2]) if row[2] else 0
            except (ValueError, TypeError):
                continue

            if ano not in anos:
                continue

            num = str(row[1]).strip() if row[1] else ""
            orgao_planilha = str(row[3]).strip().upper() if row[3] else ""
            orgao_sigla_db = ORGAO_MAP.get(orgao_planilha, orgao_planilha)

            pgea = str(row[5]).strip() if row[5] else ""
            objeto = str(row[8]).strip()[:500] if row[8] else ""
            cnpj = str(row[9]).strip() if row[9] else ""
            contratado = str(row[10]).strip()[:255] if row[10] else ""
            data_assinatura = parse_date(row[11])
            data_vigencia_original = parse_date(row[12])
            data_vigencia_atual = parse_date(row[13])
            valor_contrato = parse_decimal(row[17])
            valor_atualizado = parse_decimal(row[19])
            tipo_contratual = str(row[37]).strip().upper() if row[37] else ""
            continuado = str(row[38]).strip().upper() if row[38] else ""

            # Determina tipo para eventual criação
            tipo_db = "fornecimento"
            for kw, tp in TIPO_CONTRATO_MAP.items():
                if kw in tipo_contratual:
                    tipo_db = tp
                    break
            if "LOCAÇÃO" in objeto.upper() or "LOCACAO" in objeto.upper():
                tipo_db = "locacao"
            if continuado in ("SIM", "S"):
                tipo_db = "servico_continuo"

            # === Localizar contrato na base ===
            ct = None
            orgao_obj = orgaos_db.get(orgao_sigla_db)

            # 1. Tenta por número exato com órgão
            candidatos = normalizar_numero(num, orgao_sigla_db)
            for c in candidatos:
                q = Contrato.objects.filter(numero_contrato=c)
                if orgao_obj:
                    q = q.filter(orgao=orgao_obj)
                ct = q.first()
                if ct:
                    break

            # 2. Tenta sem filtro de órgão
            if not ct:
                for c in candidatos:
                    ct = Contrato.objects.filter(numero_contrato=c).first()
                    if ct:
                        break

            # 3. Matching por número parcial (número aparece dentro do numero_contrato)
            if not ct:
                # Ex: planilha "102/2025" encontra "102/2025 FMMPPI"
                for sufixo_ano in [f"/{ano}", f"/{ano}/"]:
                    qs = Contrato.objects.filter(numero_contrato__icontains=f"{num}{sufixo_ano}")
                    if orgao_obj:
                        qs = qs.filter(orgao=orgao_obj)
                    ct = qs.first()
                    if ct:
                        break
                    # Sem filtro de órgão
                    ct = Contrato.objects.filter(numero_contrato__icontains=f"{num}{sufixo_ano}").first()
                    if ct:
                        break

            # 4. Por PGEA / numero_sei
            if not ct and pgea:
                ct = Contrato.objects.filter(numero_sei__icontains=pgea.split("/")[0]).first()

            # 5. Por contratado + valor (matching aproximado)
            if not ct and contratado and valor_atualizado:
                # Usa as primeiras 20 letras do nome do contratado
                nome_curto = contratado[:20]
                ct = Contrato.objects.filter(
                    contratado_razao_social__icontains=nome_curto,
                    data_assinatura__year=ano,
                ).first()

            # 6. Por contratado + ano sem valor
            if not ct and contratado:
                ct = Contrato.objects.filter(
                    contratado_razao_social__icontains=contratado[:25],
                ).filter(data_assinatura__year=ano).first()

            if ct:
                # === Atualizar contrato encontrado ===
                alteracoes = {}
                if valor_atualizado and ct.valor_atual != valor_atualizado:
                    alteracoes["valor_atual"] = (ct.valor_atual, valor_atualizado)
                if valor_contrato and ct.valor_inicial != valor_contrato:
                    alteracoes["valor_inicial"] = (ct.valor_inicial, valor_contrato)
                if data_vigencia_atual and ct.data_fim_vigencia != data_vigencia_atual:
                    alteracoes["data_fim_vigencia"] = (ct.data_fim_vigencia, data_vigencia_atual)
                if objeto and ct.objeto != objeto:
                    alteracoes["objeto"] = (ct.objeto[:40], objeto[:40])
                if contratado and ct.contratado_razao_social != contratado:
                    alteracoes["contratado_razao_social"] = (ct.contratado_razao_social[:30], contratado[:30])
                if cnpj and ct.contratado_cnpj_cpf != cnpj:
                    alteracoes["contratado_cnpj_cpf"] = (ct.contratado_cnpj_cpf, cnpj)
                if pgea and not ct.numero_sei:
                    alteracoes["numero_sei"] = ("(vazio)", pgea)

                if alteracoes:
                    if not dry_run:
                        with transaction.atomic():
                            if "valor_atual" in alteracoes:
                                ct.valor_atual = alteracoes["valor_atual"][1]
                            if "valor_inicial" in alteracoes:
                                ct.valor_inicial = alteracoes["valor_inicial"][1]
                            if "data_fim_vigencia" in alteracoes:
                                ct.data_fim_vigencia = alteracoes["data_fim_vigencia"][1]
                            if "objeto" in alteracoes:
                                ct.objeto = objeto
                            if "contratado_razao_social" in alteracoes:
                                ct.contratado_razao_social = contratado
                            if "contratado_cnpj_cpf" in alteracoes:
                                ct.contratado_cnpj_cpf = cnpj
                            if "numero_sei" in alteracoes:
                                ct.numero_sei = pgea
                            ct.save()

                    atualizados += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  ✓ {orgao_planilha} | {num}/{ano} [{ct.numero_contrato}]")
                    )
                    for campo, (ant, nov) in alteracoes.items():
                        self.stdout.write(f"      {campo}: {ant!r} → {nov!r}")
                else:
                    self.stdout.write(f"  = {orgao_planilha} | {num}/{ano} já conciliado")
            else:
                nao_encontrados.append({
                    "num": num, "ano": ano, "orgao": orgao_planilha,
                    "contratado": contratado[:40], "valor": valor_atualizado,
                    "vigencia": data_vigencia_atual
                })

        # Sumário final
        self.stdout.write(f"\n{'='*65}")
        self.stdout.write(self.style.SUCCESS(
            f"Conciliação concluída!\n"
            f"  Contratos atualizados:     {atualizados}\n"
            f"  Não encontrados na base:   {len(nao_encontrados)}"
        ))

        if nao_encontrados:
            self.stdout.write(f"\n{'─'*65}")
            self.stdout.write(self.style.WARNING("Contratos da planilha NÃO encontrados na base:"))
            for nf in nao_encontrados:
                self.stdout.write(
                    f"  • {nf['orgao']} | {nf['num']}/{nf['ano']} | {nf['contratado']} | "
                    f"R$ {nf['valor']:,.2f}" if nf.get('valor') else
                    f"  • {nf['orgao']} | {nf['num']}/{nf['ano']} | {nf['contratado']}"
                )
        self.stdout.write(f"{'='*65}\n")
