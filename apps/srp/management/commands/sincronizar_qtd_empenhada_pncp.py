"""
Sincroniza ItemARP.quantidade_contratada com o campo `quantidadeEmpenhada`
retornado pela API dadosabertos.compras.gov.br via endpoint:

    GET /modulo-arp/2.1_consultarARPItem_Id?numeroControlePncpAta=<valor>

Uso:
    python manage.py sincronizar_qtd_empenhada_pncp
    python manage.py sincronizar_qtd_empenhada_pncp --arp 00015/2025
    python manage.py sincronizar_qtd_empenhada_pncp --dry-run
"""

import requests
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://dadosabertos.compras.gov.br"
ENDPOINT = "/modulo-arp/2.1_consultarARPItem_Id"
TAMANHO_PAGINA = 500
TIMEOUT = 30


def _parse_decimal(v) -> Decimal:
    try:
        return Decimal(str(v)).quantize(Decimal("0.0001"))
    except (InvalidOperation, TypeError):
        return Decimal("0")


class Command(BaseCommand):
    help = "Sincroniza quantidade_contratada de ItemARP via quantidadeEmpenhada do PNCP"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--arp", type=str, help="Filtrar por número de ARP (ex: 00015/2025)")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        filtro = options["arp"]

        if dry:
            self.stdout.write("*** DRY-RUN — nenhuma alteração será salva ***\n")

        qs = AtaRegistroPrecos.objects.exclude(numero_controle_pncp_ata="")
        if filtro:
            qs = qs.filter(numero_arp=filtro)

        total_arps = qs.count()
        if not total_arps:
            self.stdout.write("Nenhuma ARP com numero_controle_pncp_ata encontrada.")
            return

        self.stdout.write(f"ARPs a sincronizar: {total_arps}\n")

        atualizados = 0
        sem_alteracao = 0
        erros = 0

        for arp in qs.order_by("numero_arp"):
            pncp_id = arp.numero_controle_pncp_ata
            self.stdout.write(f"\n→ ARP {arp.numero_arp} | pncp_id={pncp_id}")

            # Busca itens paginado
            itens_api = []
            pagina = 1
            while True:
                url = f"{BASE_URL}{ENDPOINT}"
                params = {
                    "numeroControlePncpAta": pncp_id,
                    "pagina": pagina,
                    "tamanhoPagina": TAMANHO_PAGINA,
                }
                try:
                    resp = requests.get(url, params=params, timeout=TIMEOUT)
                    resp.raise_for_status()
                    payload = resp.json()
                except requests.HTTPError as exc:
                    self.stdout.write(self.style.ERROR(f"  HTTP error: {exc}"))
                    erros += 1
                    break
                except requests.RequestException as exc:
                    self.stdout.write(self.style.ERROR(f"  Conexão: {exc}"))
                    erros += 1
                    break

                if isinstance(payload, list):
                    itens_api.extend(payload)
                    break
                elif isinstance(payload, dict):
                    resultados = payload.get("resultado") or payload.get("data") or []
                    itens_api.extend(resultados)
                    paginas_restantes = payload.get("paginasRestantes", 0)
                    if paginas_restantes <= 0:
                        break
                    pagina += 1
                else:
                    break

            if not itens_api:
                self.stdout.write("  Nenhum item retornado pela API.")
                continue

            self.stdout.write(f"  {len(itens_api)} itens recebidos da API")

            # Indexa itens do banco por numero_item
            itens_db = {
                i.numero_item: i
                for i in ItemARP.objects.filter(arp=arp)
            }

            for item_api in itens_api:
                try:
                    numero_item = int(
                        item_api.get("numeroItem")
                        or item_api.get("numeroItemAta")
                        or 0
                    )
                except (TypeError, ValueError):
                    continue

                qtd_empenhada = _parse_decimal(item_api.get("quantidadeEmpenhada"))

                item_db = itens_db.get(numero_item)
                if item_db is None:
                    self.stdout.write(
                        self.style.WARNING(f"  Item {numero_item} não encontrado no banco — execute importar_arp_compras_gov primeiro")
                    )
                    continue

                if item_db.quantidade_contratada == qtd_empenhada:
                    sem_alteracao += 1
                    continue

                self.stdout.write(
                    f"  item={numero_item}: {item_db.quantidade_contratada} → {qtd_empenhada}"
                )

                if not dry:
                    ItemARP.objects.filter(pk=item_db.pk).update(
                        quantidade_contratada=qtd_empenhada
                    )
                atualizados += 1

        self.stdout.write(
            f"\n{'[DRY-RUN] ' if dry else ''}Concluído — "
            f"atualizados={atualizados} | sem_alteracao={sem_alteracao} | erros={erros}"
        )
