"""
Management command: importar_processo_licitatorio_planilha
=============================================================
Lê a planilha de controle de licitações/ARPs mantida manualmente pela
área de licitação ("CONTROLES - LICITAÇÕES(ATAS DE REGISTRO DE
PREÇOS).csv", colunas N° ATA;ANO;PREGÃO;N° PROCESSO;OBJETO;EMPRESA;
VALOR PREVISTO;VALOR HOMOLOGADO;PERCENTUAL ECONOMIA;REGIME LEGAL) e:

  1. Popula AtaRegistroPrecos.processo_licitatorio (só quando ainda
     vazio, a menos que --force) — esse campo já existe no model mas
     raramente é preenchido. A planilha é a fonte oficial do processo
     SEI da LICITAÇÃO ORIGINAL (diferente do processo do CONTRATO
     individual, que é outro número — ver "N° PROCESSO" desta planilha
     vs. o campo `processo` do contrato no PNCP, que diverge; achado
     registrado em project_pca_erros_apis_contratos.md).

  2. Reporta divergências entre a coluna VALOR HOMOLOGADO da planilha e
     Σ(quantidade_registrada × valor_unitario) dos ItemARP já cadastrados
     em cada ARP no banco — cada linha da planilha já é 1 ata = 1
     fornecedor, mesma premissa do model (uma AtaRegistroPrecos tem um
     único `fornecedor_cnpj_cpf`). Não altera nada por conta disso, só
     avisa — a correção de itens é manual.

Casamento: por (N° ATA, ANO) normalizados como inteiros, contra
AtaRegistroPrecos.numero_arp (que pode estar em formatos diferentes,
ex: "27/2025" ou "00027/2025" — ambos normalizam pra (27, 2025)).

Uso:
  python manage.py importar_processo_licitatorio_planilha --dry-run
  python manage.py importar_processo_licitatorio_planilha
  python manage.py importar_processo_licitatorio_planilha --arquivo "outro/caminho.csv"
  python manage.py importar_processo_licitatorio_planilha --force
"""

import csv
import os
import re
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.srp.models import AtaRegistroPrecos


def _parse_valor_brl(valor: str):
    """'R$ 5.763.362,00' -> Decimal('5763362.00'). None se não der pra converter."""
    if not valor:
        return None
    limpo = re.sub(r"[^\d,.\-]", "", valor).strip()
    limpo = limpo.replace(".", "").replace(",", ".")
    try:
        return Decimal(limpo)
    except InvalidOperation:
        return None


def _parse_ata_ano(numero_arp: str):
    """'00027/2025' ou '27/2025' -> (27, 2025). None se não bater o padrão NN/AAAA."""
    if not numero_arp:
        return None
    m = re.search(r"(\d+)\s*/\s*(\d{4})", numero_arp)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


class Command(BaseCommand):
    help = (
        "Importa processo_licitatorio da planilha de controle de licitações "
        "e valida o valor homologado contra os itens já cadastrados"
    )

    def add_arguments(self, parser):
        default = os.path.normpath(
            os.path.join(
                os.path.dirname(__file__),
                "..", "..", "..", "..", "data", "srp",
                "CONTROLES - LICITAÇÕES(ATAS DE REGISTRO DE PREÇOS).csv",
            )
        )
        parser.add_argument(
            "--arquivo", default=default,
            help="Caminho do CSV (padrão: data/srp/CONTROLES - LICITAÇÕES(ATAS DE REGISTRO DE PREÇOS).csv)",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Mostra o que seria feito sem salvar",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Sobrescreve processo_licitatorio mesmo se já estiver preenchido",
        )

    def handle(self, *args, **options):
        path = options["arquivo"]
        dry_run = options["dry_run"]
        force = options["force"]

        if not os.path.exists(path):
            raise CommandError(f"Arquivo não encontrado: {path}")

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        # ── Índice local: (numero_ata_int, ano) -> AtaRegistroPrecos ──────────
        arps_por_chave = {}
        for arp in AtaRegistroPrecos.objects.prefetch_related("itens").all():
            chave = _parse_ata_ano(arp.numero_arp)
            if chave:
                arps_por_chave.setdefault(chave, []).append(arp)

        atualizados = 0
        ignorados_preenchidos = 0
        nao_encontrados = 0
        ambiguos = 0
        sem_itens = 0
        divergencias_valor = []

        with open(path, encoding="cp1252", newline="") as f:
            reader = csv.DictReader(f, delimiter=";")
            for linha_num, row in enumerate(reader, start=2):
                ata_raw = (row.get("N° ATA") or "").strip()
                ano_raw = (row.get("ANO") or "").strip()
                processo = (row.get("N° PROCESSO") or "").strip()
                pregao = (row.get("PREGÃO") or "").strip()
                empresa = (row.get("EMPRESA") or "").strip()
                valor_homologado_str = (row.get("VALOR HOMOLOGADO") or "").strip()

                if not ata_raw or not ano_raw:
                    continue
                try:
                    chave = (int(ata_raw), int(ano_raw))
                except ValueError:
                    self.stdout.write(self.style.WARNING(
                        f"  linha {linha_num}: N° ATA/ANO inválido ({ata_raw!r}/{ano_raw!r}) — pulando"
                    ))
                    continue

                candidatos = arps_por_chave.get(chave)
                if not candidatos:
                    nao_encontrados += 1
                    self.stdout.write(
                        f"  [não encontrado] Ata {ata_raw}/{ano_raw} "
                        f"(pregão {pregao}, {empresa[:40]}) — sem ARP correspondente no banco"
                    )
                    continue
                if len(candidatos) > 1:
                    ambiguos += 1
                    self.stdout.write(self.style.WARNING(
                        f"  [ambíguo] Ata {ata_raw}/{ano_raw} bate com {len(candidatos)} ARPs no banco — pulando"
                    ))
                    continue

                arp = candidatos[0]

                # 1. processo_licitatorio ------------------------------------
                if processo:
                    if arp.processo_licitatorio and not force:
                        if arp.processo_licitatorio != processo:
                            self.stdout.write(self.style.WARNING(
                                f"  [mantido — já preenchido] ARP {arp.numero_arp}: "
                                f"banco={arp.processo_licitatorio!r} vs planilha={processo!r} "
                                "(use --force pra sobrescrever)"
                            ))
                        ignorados_preenchidos += 1
                    elif arp.processo_licitatorio != processo:
                        self.stdout.write(
                            f"  [processo] ARP {arp.numero_arp}: "
                            f"{arp.processo_licitatorio!r} -> {processo!r}"
                        )
                        if not dry_run:
                            arp.processo_licitatorio = processo
                            arp.save(update_fields=["processo_licitatorio"])
                        atualizados += 1

                # 2. validação de valor homologado ----------------------------
                valor_planilha = _parse_valor_brl(valor_homologado_str)
                if valor_planilha is None:
                    continue

                itens = list(arp.itens.all())
                if not itens:
                    sem_itens += 1
                    continue

                valor_banco = sum(
                    (item.quantidade_registrada * item.valor_unitario) for item in itens
                )
                if abs(valor_banco - valor_planilha) > Decimal("0.05"):
                    divergencias_valor.append(
                        (arp.numero_arp, empresa, valor_planilha, valor_banco)
                    )

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS(
            f"processo_licitatorio: {atualizados} atualizados, "
            f"{ignorados_preenchidos} já preenchidos (mantidos), "
            f"{nao_encontrados} sem ARP correspondente, {ambiguos} ambíguos."
        ))
        if sem_itens:
            self.stdout.write(
                f"{sem_itens} ARP(s) casadas mas sem ItemARP cadastrado — validação de valor pulada nelas."
            )

        if divergencias_valor:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ {len(divergencias_valor)} ARP(s) com valor homologado divergente "
                "(planilha × banco) — revisar manualmente:"
            ))
            for numero_arp, empresa, valor_planilha, valor_banco in divergencias_valor:
                self.stdout.write(
                    f"  ARP {numero_arp} ({empresa[:40]}): "
                    f"planilha=R$ {valor_planilha:,.2f} | banco=R$ {valor_banco:,.2f} | "
                    f"diferença=R$ {(valor_planilha - valor_banco):,.2f}"
                )
        else:
            self.stdout.write(self.style.SUCCESS("Nenhuma divergência de valor homologado encontrada."))
