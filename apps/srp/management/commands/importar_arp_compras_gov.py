"""
Management command: importar_arp_compras_gov
============================================
Importa uma ARP do Compras.gov.br via API aberta (dadosabertos.compras.gov.br).

Uso:
    python manage.py importar_arp_compras_gov --uasg 926092 --arp 2/2026
    python manage.py importar_arp_compras_gov --uasg 926092 --arp 12/2026 --atualizar

Parâmetros:
    --uasg      Código UASG do órgão gerenciador (MPPI = 926092)
    --arp       Número da ARP no formato NUMERO/ANO (ex: 2/2026 ou 12/2026)
    --atualizar Se informado, atualiza registro existente; caso contrário, pula

Endpoints utilizados:
    1. /modulo-ata-registro-preco/ata?codigoUasg=&numeroAtaRegistroPreco=&anoAta=
       Retorna dados cadastrais da ARP (objeto, fornecedor, vigência, etc.)

    2. /modulo-ata-registro-preco/item?codigoUasg=&numeroAtaRegistroPreco=&anoAta=
       Retorna os itens registrados na ARP com preços, quantidades e limites de adesão

Fundamento legal:
    Decreto 11.462/2023 (SRP Federal — aplicado subsidiariamente ao MPPI)
    Lei 14.133/2021, arts. 82–86
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Orgao
from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://dadosabertos.compras.gov.br/modulo-ata-registro-preco"

TIMEOUT = 30  # segundos


class Command(BaseCommand):
    help = "Importa uma ARP do Compras.gov.br via API dadosabertos"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            required=True,
            help="Código UASG do órgão gerenciador (ex: 926092)",
        )
        parser.add_argument(
            "--arp",
            required=True,
            help="Número da ARP no formato NUMERO/ANO (ex: 2/2026 ou 12/2026)",
        )
        parser.add_argument(
            "--atualizar",
            action="store_true",
            default=False,
            help="Atualiza o registro se já existir no banco",
        )

    def handle(self, *args, **options):
        uasg = options["uasg"].strip()
        arp_raw = options["arp"].strip()
        atualizar = options["atualizar"]

        # Parseia NUMERO/ANO
        match = re.match(r"^(\d+)/(\d{4})$", arp_raw)
        if not match:
            raise CommandError(
                f"Formato inválido para --arp: '{arp_raw}'. Use NUMERO/ANO (ex: 2/2026)."
            )
        numero_arp_api = match.group(1)
        ano_arp = match.group(2)
        numero_arp_formatado = f"{numero_arp_api.zfill(3)}/{ano_arp}"

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"UASG: {uasg} | ARP: {numero_arp_formatado}")
        self.stdout.write(f"{'='*60}")

        # Busca dados cadastrais da ARP (Endpoint 1)
        self.stdout.write("→ Consultando dados da ARP na API...")
        dados_arp = self._consultar_arp(uasg, numero_arp_api, ano_arp)

        if not dados_arp:
            raise CommandError(
                f"ARP {numero_arp_formatado} não encontrada na API para UASG {uasg}."
            )

        # Busca itens da ARP (Endpoint 2)
        self.stdout.write("→ Consultando itens da ARP na API...")
        itens_api = self._consultar_itens(uasg, numero_arp_api, ano_arp)

        self.stdout.write(
            f"  Encontrado: {len(itens_api)} item(ns) para importar."
        )

        # Identifica o órgão gerenciador no banco local
        orgao = Orgao.objects.first()
        if not orgao:
            raise CommandError(
                "Nenhum Órgão cadastrado no banco. Cadastre o MPPI primeiro."
            )

        # Importa com transação atômica
        with transaction.atomic():
            arp, criada = self._importar_arp(
                dados_arp, orgao, uasg, numero_arp_formatado, atualizar
            )

            if not criada and not atualizar:
                self.stdout.write(
                    self.style.WARNING(
                        f"ARP {numero_arp_formatado} já existe. Use --atualizar para sobrescrever."
                    )
                )
                return

            status_arp = "CRIADA" if criada else "ATUALIZADA"
            self.stdout.write(self.style.SUCCESS(f"  ARP {status_arp}: {arp}"))

            # Importa itens
            criados = atualizados = ignorados = 0
            for item_data in itens_api:
                resultado = self._importar_item(item_data, arp, atualizar)
                if resultado == "criado":
                    criados += 1
                elif resultado == "atualizado":
                    atualizados += 1
                else:
                    ignorados += 1

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(
            self.style.SUCCESS(
                f"Importação concluída:\n"
                f"  ARP: {status_arp}\n"
                f"  Itens criados:    {criados}\n"
                f"  Itens atualizados:{atualizados}\n"
                f"  Itens ignorados:  {ignorados}"
            )
        )

    # ------------------------------------------------------------------
    # Helpers de API
    # ------------------------------------------------------------------

    def _consultar_arp(self, uasg, numero, ano):
        """Endpoint 1 — dados cadastrais da ARP."""
        url = f"{BASE_URL}/ata"
        params = {
            "codigoUasg": uasg,
            "numeroAtaRegistroPreco": numero,
            "anoAta": ano,
        }
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            # A API retorna lista; pega o primeiro resultado
            if isinstance(data, list) and data:
                return data[0]
            if isinstance(data, dict):
                return data
            return None
        except requests.RequestException as exc:
            raise CommandError(f"Erro ao consultar API (endpoint /ata): {exc}")

    def _consultar_itens(self, uasg, numero, ano):
        """Endpoint 2 — itens registrados na ARP."""
        url = f"{BASE_URL}/item"
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
            # Algumas respostas vêm paginadas com campo "itens" ou "data"
            if isinstance(data, dict):
                return data.get("itens") or data.get("data") or []
            return []
        except requests.RequestException as exc:
            raise CommandError(f"Erro ao consultar API (endpoint /item): {exc}")

    # ------------------------------------------------------------------
    # Helpers de persistência
    # ------------------------------------------------------------------

    def _importar_arp(self, dados, orgao, uasg, numero_formatado, atualizar):
        """Cria ou atualiza AtaRegistroPrecos a partir dos dados da API."""
        # Mapeia campos da API → modelo
        # Os nomes dos campos podem variar — tratamos os mais comuns
        objeto = (
            dados.get("objetoAta")
            or dados.get("objeto")
            or dados.get("descricaoObjeto")
            or ""
        )
        fornecedor = (
            dados.get("razaoSocialFornecedor")
            or dados.get("nomeRazaoSocial")
            or dados.get("fornecedor")
            or ""
        )
        cnpj_fornecedor = (
            dados.get("cnpjFornecedor")
            or dados.get("cnpj")
            or ""
        )
        data_assinatura = self._parse_data(
            dados.get("dataAssinatura") or dados.get("dataPublicacaoAta")
        )
        data_inicio = self._parse_data(
            dados.get("dataInicioVigencia") or dados.get("dataAssinatura")
        )
        data_fim = self._parse_data(
            dados.get("dataFimVigencia") or dados.get("dataVencimentoAta")
        )
        numero_pncp = dados.get("numeroControlePNCP") or dados.get("numeroPncp") or ""
        id_compra = dados.get("idCompra") or dados.get("codigoCompra") or ""

        if not data_assinatura or not data_inicio or not data_fim:
            raise CommandError(
                f"Datas obrigatórias ausentes nos dados da API: "
                f"assinatura={dados.get('dataAssinatura')}, "
                f"fim={dados.get('dataFimVigencia')}"
            )

        defaults = {
            "objeto": objeto,
            "modalidade_origem": "pregao_eletronico",  # padrão para ARPs importadas
            "fornecedor_razao_social": fornecedor,
            "fornecedor_cnpj_cpf": cnpj_fornecedor,
            "data_assinatura": data_assinatura,
            "data_inicio_vigencia": data_inicio,
            "data_fim_vigencia": data_fim,
            "numero_pncp": numero_pncp,
            "codigo_uasg_gerenciadora": uasg,
            "numero_controle_pncp_ata": numero_pncp,
            "id_compra_compras_gov": id_compra,
            "importada_da_api": True,
        }

        arp, criada = AtaRegistroPrecos.objects.get_or_create(
            orgao_gerenciador=orgao,
            numero_arp=numero_formatado,
            defaults=defaults,
        )

        if not criada and atualizar:
            for campo, valor in defaults.items():
                setattr(arp, campo, valor)
            arp.save()

        return arp, criada

    def _importar_item(self, item_data, arp, atualizar):
        """Cria ou atualiza ItemARP a partir de um item da API."""
        try:
            numero_item = int(
                item_data.get("numeroItem")
                or item_data.get("numeroItemAta")
                or 0
            )
        except (TypeError, ValueError):
            self.stdout.write(
                self.style.WARNING(f"  Item sem número válido — ignorado: {item_data}")
            )
            return "ignorado"

        descricao = (
            item_data.get("descricaoItem")
            or item_data.get("descricao")
            or item_data.get("nome")
            or ""
        )
        unidade = (
            item_data.get("unidadeFornecimento")
            or item_data.get("unidadeMedida")
            or ""
        )
        qtd_registrada = self._parse_decimal(
            item_data.get("quantidadeRegistrada")
            or item_data.get("quantidade")
        )
        valor_unitario = self._parse_decimal(
            item_data.get("valorUnitario")
            or item_data.get("valorUnitarioAjustado")
        )
        maximo_adesao = self._parse_decimal(item_data.get("maximoAdesao"))
        codigo_catmat = str(
            item_data.get("codigoItem")
            or item_data.get("codigoCatmat")
            or ""
        )
        codigo_item_int = None
        try:
            codigo_item_int = int(item_data.get("codigoItem") or 0) or None
        except (TypeError, ValueError):
            pass

        numero_lote = str(item_data.get("numeroLote") or "")

        defaults = {
            "descricao": descricao,
            "unidade_fornecimento": unidade,
            "quantidade_registrada": qtd_registrada,
            "valor_unitario": valor_unitario,
            "codigo_catmat_catser": codigo_catmat,
            "codigo_item_compras_gov": codigo_item_int,
            "maximo_adesao_api": maximo_adesao,
            "importado_da_api": True,
            "numero_lote": numero_lote,
        }

        # Aviso se carona bloqueada (maximoAdesao = 0)
        if maximo_adesao is not None and maximo_adesao == Decimal("0"):
            self.stdout.write(
                self.style.WARNING(
                    f"  [AVISO] Item {numero_item} — carona desabilitada no Compras.gov "
                    f"(maximoAdesao=0). Adesão exigirá SEI de autorização do MPPI."
                )
            )

        item, criado = ItemARP.objects.get_or_create(
            arp=arp,
            numero_item=numero_item,
            defaults=defaults,
        )

        if not criado and atualizar:
            for campo, valor in defaults.items():
                setattr(item, campo, valor)
            item.save()
            return "atualizado"

        return "criado" if criado else "ignorado"

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------

    def _parse_data(self, valor):
        """Converte string de data da API para objeto date."""
        if not valor:
            return None
        formatos = ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]
        for fmt in formatos:
            try:
                return datetime.strptime(str(valor)[:len(fmt)], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_decimal(self, valor):
        """Converte valor numérico da API para Decimal."""
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")
