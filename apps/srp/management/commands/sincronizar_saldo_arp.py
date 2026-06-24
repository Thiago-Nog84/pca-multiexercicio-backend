"""
Management command: sincronizar_saldo_arp
==========================================
Sincroniza os saldos (quantidade_contratada) dos itens de ARP que foram
importados via API Compras.gov.br (importado_da_api=True).

Usa o Endpoint 4 da API:
    GET /modulo-arp/4_consultarEmpenhosSaldoItem
    Params obrigatórios: numeroAta, unidadeGerenciadora
    → Retorna empenhos e saldo por item da ARP

Uso:
    # Sincroniza todas as ARPs importadas da API para UASG 926092
    python manage.py sincronizar_saldo_arp --uasg 926092

    # Sincroniza apenas uma ARP específica
    python manage.py sincronizar_saldo_arp --uasg 926092 --arp 002/2026

    # Execução seca — mostra o que seria alterado sem gravar
    python manage.py sincronizar_saldo_arp --uasg 926092 --dry-run
"""

import re
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://dadosabertos.compras.gov.br"
TIMEOUT = 30
TAMANHO_PAGINA = 100


class Command(BaseCommand):
    help = "Sincroniza saldos dos itens de ARP via /modulo-arp/4_consultarEmpenhosSaldoItem"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            required=True,
            help="Código UASG do órgão gerenciador (ex: 926092)",
        )
        parser.add_argument(
            "--arp",
            default=None,
            help="Número da ARP no formato NNN/AAAA (opcional — sincroniza todas se omitido)",
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

        qs = AtaRegistroPrecos.objects.filter(
            codigo_uasg_gerenciadora=uasg,
            importada_da_api=True,
        )

        if arp_filtro:
            match = re.match(r"^(\d+)/(\d{4})$", arp_filtro.strip())
            if not match:
                raise CommandError(f"Formato inválido para --arp: '{arp_filtro}'. Use NNN/AAAA.")
            numero_fmt = f"{match.group(1).zfill(3)}/{match.group(2)}"
            qs = qs.filter(numero_arp=numero_fmt)

        arps = list(qs)
        if not arps:
            self.stdout.write(self.style.WARNING("Nenhuma ARP encontrada para sincronizar."))
            return

        self.stdout.write(f"ARPs a sincronizar: {len(arps)}\n{'='*60}")

        total_atualizados = total_sem_alteracao = total_erros = 0

        for arp in arps:
            self.stdout.write(f"\n→ ARP {arp.numero_arp} — {arp.fornecedor_razao_social[:40]}")

            try:
                empenhos = self._consultar_empenhos(arp.numero_arp, uasg)
            except CommandError as exc:
                self.stdout.write(self.style.ERROR(f"  Erro: {exc}"))
                total_erros += 1
                continue

            self.stdout.write(f"  Registros de empenho encontrados: {len(empenhos)}")

            # Agrupa quantidade empenhada/contratada por número de item
            # O endpoint retorna empenhos individuais — soma por item
            saldo_por_item: dict[int, Decimal] = {}
            for emp in empenhos:
                try:
                    num_item = int(
                        emp.get("numeroItem")
                        or emp.get("item")
                        or 0
                    )
                    # Usa quantidadeEmpenhada ou quantidadeContratada, o que estiver disponível
                    qtd = self._parse_decimal(
                        emp.get("quantidadeEmpenhada")
                        or emp.get("quantidadeContratada")
                        or emp.get("quantidade")
                    )
                    saldo_por_item[num_item] = saldo_por_item.get(num_item, Decimal("0")) + qtd
                except (TypeError, ValueError):
                    continue

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
                        f"({'DRY-RUN' if dry_run else 'ATUALIZADO'})"
                    )

                    if not dry_run:
                        item.quantidade_contratada = nova_qtd
                        item.save(update_fields=["quantidade_contratada"])

                    total_atualizados += 1

                if dry_run:
                    transaction.set_rollback(True)

        self.stdout.write(f"\n{'='*60}")
        resumo = (
            f"Sincronização {'(DRY-RUN) ' if dry_run else ''}concluída:\n"
            f"  Itens atualizados:   {total_atualizados}\n"
            f"  Itens sem alteração: {total_sem_alteracao}\n"
            f"  ARPs com erro:       {total_erros}"
        )
        self.stdout.write(self.style.SUCCESS(resumo) if not dry_run else self.style.WARNING(resumo))

    # ------------------------------------------------------------------
    # Consulta de empenhos (Endpoint 4)
    # ------------------------------------------------------------------

    def _consultar_empenhos(self, numero_arp, uasg):
        """
        GET /modulo-arp/4_consultarEmpenhosSaldoItem
        Params obrigatórios: numeroAta, unidadeGerenciadora
        """
        url = f"{BASE_URL}/modulo-arp/4_consultarEmpenhosSaldoItem"
        resultados = []
        pagina = 1

        while True:
            params = {
                "numeroAta": numero_arp,
                "unidadeGerenciadora": uasg,
                "pagina": pagina,
                "tamanhoPagina": TAMANHO_PAGINA,
            }
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT)
                resp.raise_for_status()
                payload = resp.json()
            except requests.HTTPError as exc:
                raise CommandError(f"Erro HTTP ao consultar empenhos: {exc}")
            except requests.RequestException as exc:
                raise CommandError(f"Erro de conexão ao consultar empenhos: {exc}")

            if isinstance(payload, list):
                resultados.extend(payload)
                break
            elif isinstance(payload, dict):
                dados = (
                    payload.get("data")
                    or payload.get("itens")
                    or payload.get("resultado")
                    or payload.get("content")
                    or []
                )
                resultados.extend(dados)
                total = payload.get("totalItens") or payload.get("total") or 0
                if len(resultados) >= total or len(dados) < TAMANHO_PAGINA:
                    break
                pagina += 1
            else:
                break

        return resultados

    def _parse_decimal(self, valor):
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")
