"""
Management command: sincronizar_saldo_arp
==========================================
Sincroniza os saldos (quantidade_contratada) dos itens de ARP que foram
importados via API Compras.gov.br (importado_da_api=True).

Usa o Endpoint 4 da API:
    /modulo-ata-registro-preco/contratacao?codigoUasg=&numeroAtaRegistroPreco=&anoAta=
    Retorna as contratações decorrentes registradas no Compras.gov.br para a ARP.

Uso:
    # Sincroniza todas as ARPs importadas da API para UASG 926092
    python manage.py sincronizar_saldo_arp --uasg 926092

    # Sincroniza apenas uma ARP específica
    python manage.py sincronizar_saldo_arp --uasg 926092 --arp 2/2026

    # Execução seca — mostra o que seria alterado sem gravar
    python manage.py sincronizar_saldo_arp --uasg 926092 --dry-run

Importante:
    O saldo calculado pela API representa o total contratado no âmbito
    federal/SIASG. Se o MPPI realiza contratações fora do SIASG, este
    comando pode não refletir o saldo real. Use com discernimento.

Fundamento legal:
    Decreto 11.462/2023 (SRP Federal)
    Lei 14.133/2021, arts. 82–86
"""

import re
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://dadosabertos.compras.gov.br/modulo-ata-registro-preco"

TIMEOUT = 30


class Command(BaseCommand):
    help = "Sincroniza saldos (quantidade_contratada) dos itens de ARP via API Compras.gov.br"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            required=True,
            help="Código UASG do órgão gerenciador (ex: 926092)",
        )
        parser.add_argument(
            "--arp",
            default=None,
            help="Número da ARP no formato NUMERO/ANO (opcional — sincroniza todas se omitido)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula a sincronização sem gravar no banco",
        )

    def handle(self, *args, **options):
        uasg = options["uasg"].strip()
        arp_filtro = options["arp"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN — nenhuma alteração será gravada.\n"))

        # Determina quais ARPs sincronizar
        qs = AtaRegistroPrecos.objects.filter(
            codigo_uasg_gerenciadora=uasg,
            importada_da_api=True,
        )

        if arp_filtro:
            match = re.match(r"^(\d+)/(\d{4})$", arp_filtro.strip())
            if not match:
                raise CommandError(
                    f"Formato inválido para --arp: '{arp_filtro}'. Use NUMERO/ANO."
                )
            numero = match.group(1).zfill(3)
            ano = match.group(2)
            numero_formatado = f"{numero}/{ano}"
            qs = qs.filter(numero_arp=numero_formatado)

        arps = list(qs)
        if not arps:
            self.stdout.write(self.style.WARNING("Nenhuma ARP encontrada para sincronizar."))
            return

        self.stdout.write(f"ARPs a sincronizar: {len(arps)}\n{'='*60}")

        total_atualizados = 0
        total_sem_alteracao = 0
        total_erros = 0

        for arp in arps:
            self.stdout.write(f"\n→ ARP {arp.numero_arp} — {arp.fornecedor_razao_social[:40]}")

            # Parseia numero/ano da ARP para a API
            m = re.match(r"^(\d+)/(\d{4})$", arp.numero_arp)
            if not m:
                self.stdout.write(
                    self.style.WARNING(f"  Formato de número de ARP não reconhecido: {arp.numero_arp}")
                )
                total_erros += 1
                continue

            numero_api = str(int(m.group(1)))  # Remove zeros à esquerda para a API
            ano_api = m.group(2)

            try:
                contratacoes = self._consultar_contratacoes(uasg, numero_api, ano_api)
            except CommandError as exc:
                self.stdout.write(self.style.ERROR(f"  Erro: {exc}"))
                total_erros += 1
                continue

            self.stdout.write(f"  Contratações encontradas na API: {len(contratacoes)}")

            # Agrupa contratações por número de item
            saldo_por_item: dict[int, Decimal] = {}
            for c in contratacoes:
                try:
                    num_item = int(
                        c.get("numeroItem")
                        or c.get("numeroItemAta")
                        or 0
                    )
                    quantidade = self._parse_decimal(
                        c.get("quantidadeContratada") or c.get("quantidade")
                    )
                    saldo_por_item[num_item] = saldo_por_item.get(num_item, Decimal("0")) + quantidade
                except (TypeError, ValueError):
                    continue

            # Atualiza itens no banco
            itens = ItemARP.objects.filter(arp=arp, importado_da_api=True)
            with transaction.atomic():
                for item in itens:
                    nova_qtd = saldo_por_item.get(item.numero_item, Decimal("0"))
                    if nova_qtd == item.quantidade_contratada:
                        total_sem_alteracao += 1
                        continue

                    self.stdout.write(
                        f"  Item {item.numero_item}: "
                        f"{item.quantidade_contratada} → {nova_qtd} "
                        f"({'dry-run' if dry_run else 'ATUALIZADO'})"
                    )

                    if not dry_run:
                        item.quantidade_contratada = nova_qtd
                        item.save(update_fields=["quantidade_contratada"])

                    total_atualizados += 1

                if dry_run:
                    # Desfaz a transação no dry-run
                    transaction.set_rollback(True)

        self.stdout.write(f"\n{'='*60}")
        resumo = (
            f"Sincronização {'(DRY-RUN) ' if dry_run else ''}concluída:\n"
            f"  Itens atualizados:    {total_atualizados}\n"
            f"  Itens sem alteração:  {total_sem_alteracao}\n"
            f"  ARPs com erro:        {total_erros}"
        )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry_run else self.style.WARNING(resumo))

    # ------------------------------------------------------------------
    # Helpers de API
    # ------------------------------------------------------------------

    def _consultar_contratacoes(self, uasg, numero, ano):
        """
        Endpoint 4 — contratações decorrentes registradas na ARP.
        Retorna lista de contratações com quantidades por item.
        """
        url = f"{BASE_URL}/contratacao"
        params = {
            "codigoUasg": uasg,
            "numeroAtaRegistroPreco": numero,
            "anoAta": ano,
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("contratacoes") or data.get("data") or []
            return []
        except requests.RequestException as exc:
            raise CommandError(f"Erro ao consultar endpoint /contratacao: {exc}")

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def _parse_decimal(self, valor):
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")
