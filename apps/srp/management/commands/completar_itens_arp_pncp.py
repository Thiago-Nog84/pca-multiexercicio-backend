"""
Management command: completar_itens_arp_pncp
================================================
Busca os itens + resultados homologados de uma ARP direto na API pública
do PNCP (via `AtaRegistroPrecos.numero_controle_pncp_ata`) e CRIA os
`ItemARP` que ainda não existem localmente — nunca sobrescreve/apaga um
item que já exista, só acrescenta o que falta.

Motivação (achado 2026-07-28): a validação de valor homologado feita por
`importar_processo_licitatorio_planilha` encontrou a ARP 00054/2025
(NTSEC — Firewall NGFW) com só 1 de 8 itens cadastrados (R$6,3M de
R$11,4M homologados). Confirmado ao vivo contra a API do PNCP: os 8
itens da compra 000060/2025 pertencem TODOS ao mesmo fornecedor
(NTSEC, CNPJ 09137728000215) e a soma dos 8 bate exatamente com o valor
homologado da planilha de controle — não era erro de digitação, era item
faltando mesmo.

Casamento fornecedor: filtra os itens da compra pelo CNPJ do resultado
homologado (`niFornecedor`) igual ao `AtaRegistroPrecos.fornecedor_cnpj_cpf`
— mesma lógica de `resolver_quantidade_por_valor_homologado`
(apps/srp/services/dadosabertos_contratos.py), que também expõe as
funções de acesso à API reaproveitadas aqui
(`parse_numero_controle_pncp_ata`, `buscar_itens_compra_pncp`,
`buscar_resultados_item_pncp`).

Uso:
  python manage.py completar_itens_arp_pncp --arp 00054/2025 --dry-run
  python manage.py completar_itens_arp_pncp --arp 00054/2025
"""

import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.srp.models import AtaRegistroPrecos, ItemARP
from apps.srp.services.dadosabertos_contratos import (
    buscar_itens_compra_pncp,
    buscar_resultados_item_pncp,
    parse_numero_controle_pncp_ata,
)


class Command(BaseCommand):
    help = "Completa ItemARP faltantes de uma ARP buscando itens+resultados homologados no PNCP"

    def add_arguments(self, parser):
        parser.add_argument("--arp", required=True, help="Número da ARP (ex: 00054/2025)")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Mostra o que seria criado sem salvar",
        )

    def handle(self, *args, **options):
        numero_arp = options["arp"]
        dry_run = options["dry_run"]

        try:
            arp = AtaRegistroPrecos.objects.get(numero_arp=numero_arp)
        except AtaRegistroPrecos.DoesNotExist:
            raise CommandError(f"ARP {numero_arp} não encontrada.")
        except AtaRegistroPrecos.MultipleObjectsReturned:
            raise CommandError(f"Mais de uma ARP com número {numero_arp!r} no banco — ambíguo.")

        parsed = parse_numero_controle_pncp_ata(arp.numero_controle_pncp_ata)
        if not parsed:
            raise CommandError(
                f"ARP {numero_arp} não tem numero_controle_pncp_ata válido "
                f"({arp.numero_controle_pncp_ata!r}) — não dá pra consultar o PNCP."
            )
        cnpj, ano, compra_seq = parsed

        cnpj_arp_digits = re.sub(r"\D", "", arp.fornecedor_cnpj_cpf or "")
        if not cnpj_arp_digits:
            raise CommandError(f"ARP {numero_arp} não tem fornecedor_cnpj_cpf preenchido.")

        itens_compra = buscar_itens_compra_pncp(cnpj, ano, compra_seq)
        if not itens_compra:
            raise CommandError(
                f"API do PNCP não devolveu itens para a compra {ano}/{compra_seq} (cnpj {cnpj})."
            )

        itens_locais_existentes = {i.numero_item for i in arp.itens.all()}

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        self.stdout.write(
            f"ARP {numero_arp} — fornecedor {arp.fornecedor_razao_social} ({arp.fornecedor_cnpj_cpf})\n"
            f"Compra PNCP: cnpj={cnpj} ano={ano} sequencial={compra_seq}\n"
            f"Itens já cadastrados localmente: {sorted(itens_locais_existentes) or 'nenhum'}\n"
        )

        criados = 0
        ja_existiam = 0
        sem_resultado_fornecedor = 0
        erros_validacao = 0

        for item_compra in sorted(itens_compra, key=lambda i: i.get("numeroItem") or 0):
            numero_item = item_compra.get("numeroItem")
            if numero_item is None:
                continue
            if numero_item in itens_locais_existentes:
                ja_existiam += 1
                continue

            resultados = buscar_resultados_item_pncp(cnpj, ano, compra_seq, numero_item)
            resultado_fornecedor = None
            for r in resultados:
                if r.get("dataCancelamento") or r.get("motivoCancelamento"):
                    continue
                cnpj_resultado = re.sub(r"\D", "", str(r.get("niFornecedor") or ""))
                if cnpj_resultado == cnpj_arp_digits:
                    resultado_fornecedor = r
                    break

            if not resultado_fornecedor:
                sem_resultado_fornecedor += 1
                self.stdout.write(self.style.WARNING(
                    f"  item {numero_item}: sem resultado homologado para o CNPJ desta ARP — pulando"
                ))
                continue

            descricao = (item_compra.get("descricao") or f"Item {numero_item}").strip()
            unidade = (item_compra.get("unidadeMedida") or "").strip()

            try:
                qtd_dec = Decimal(str(resultado_fornecedor.get("quantidadeHomologada")))
                valor_dec = Decimal(str(resultado_fornecedor.get("valorUnitarioHomologado")))
            except (InvalidOperation, TypeError):
                self.stdout.write(self.style.WARNING(f"  item {numero_item}: qtd/valor inválido na API — pulando"))
                continue

            self.stdout.write(
                f"  [novo] item {numero_item}: {descricao[:65]} | "
                f"qtd={qtd_dec} {unidade} | unit=R$ {valor_dec:,.2f} | "
                f"total=R$ {(qtd_dec * valor_dec):,.2f}"
            )

            if not dry_run:
                try:
                    ItemARP.objects.create(
                        arp=arp,
                        numero_item=numero_item,
                        descricao=descricao,
                        unidade_fornecimento=unidade,
                        quantidade_registrada=qtd_dec,
                        valor_unitario=valor_dec,
                        importado_da_api=True,
                    )
                except ValidationError as exc:
                    erros_validacao += 1
                    self.stdout.write(self.style.ERROR(
                        f"  item {numero_item}: erro ao salvar — {exc}"
                    ))
                    continue

            criados += 1

        self.stdout.write("\n" + "=" * 70)
        self.stdout.write(self.style.SUCCESS(
            f"ARP {numero_arp}: {criados} itens {'seriam criados' if dry_run else 'criados'}, "
            f"{ja_existiam} já existiam (mantidos), "
            f"{sem_resultado_fornecedor} sem resultado homologado pro CNPJ desta ARP, "
            f"{erros_validacao} com erro de validação."
        ))
