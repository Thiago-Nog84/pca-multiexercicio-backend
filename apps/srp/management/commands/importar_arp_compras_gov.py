"""
Management command: importar_arp_compras_gov
============================================
Importa uma ARP do Compras.gov.br via API aberta (dadosabertos.compras.gov.br).

Uso:
    python manage.py importar_arp_compras_gov --uasg 926092 --arp 002/2026
    python manage.py importar_arp_compras_gov --uasg 926092 --arp 012/2026 --atualizar

Parâmetros:
    --uasg      Código UASG do órgão gerenciador (MPPI = 926092)
    --arp       Número da ARP no formato NNN/AAAA (ex: 002/2026 ou 012/2026)
    --atualizar Se informado, atualiza registro existente; caso contrário, pula

Endpoints utilizados (API dadosabertos.compras.gov.br — Módulo ARP):
    1. GET /modulo-arp/1_consultarARP
       Params obrigatórios: dataVigenciaInicialMin, dataVigenciaInicialMax
       Params opcionais:    codigoUnidadeGerenciadora, numeroAtaRegistroPreco
       → Retorna dados cadastrais da ARP (objeto, fornecedor, vigência, etc.)

    2. GET /modulo-arp/2_consultarARPItem
       Params obrigatórios: dataVigenciaInicialMin, dataVigenciaInicialMax
       Params opcionais:    codigoUnidadeGerenciadora, numeroAtaRegistroPreco
       → Retorna os itens registrados com preços, quantidades e limite de adesão

A API retorna resultados paginados. O comando percorre todas as páginas automaticamente.

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

BASE_URL = "https://dadosabertos.compras.gov.br"
TIMEOUT = 30
TAMANHO_PAGINA = 100  # máximo por página


class Command(BaseCommand):
    help = "Importa uma ARP do Compras.gov.br via API dadosabertos (/modulo-arp/)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            required=True,
            help="Código UASG do órgão gerenciador (ex: 926092)",
        )
        parser.add_argument(
            "--arp",
            required=True,
            help="Número da ARP no formato NNN/AAAA (ex: 002/2026 ou 012/2026)",
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

        # Normaliza para NNN/AAAA (ex: "2/2026" → "002/2026")
        match = re.match(r"^(\d+)/(\d{4})$", arp_raw)
        if not match:
            raise CommandError(
                f"Formato inválido para --arp: '{arp_raw}'. Use NNN/AAAA (ex: 002/2026)."
            )
        numero_seq = match.group(1)
        ano = match.group(2)
        numero_arp = f"{numero_seq.zfill(3)}/{ano}"

        # Intervalo de datas de vigência para filtrar (ano completo)
        data_min = f"{ano}-01-01"
        data_max = f"{ano}-12-31"

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"UASG: {uasg} | ARP: {numero_arp}")
        self.stdout.write(f"Intervalo de vigência: {data_min} a {data_max}")
        self.stdout.write(f"{'='*60}")

        # Endpoint 1 — dados cadastrais da ARP
        self.stdout.write("→ Consultando dados da ARP (/modulo-arp/1_consultarARP)...")
        registros_arp = self._consultar_paginado(
            "/modulo-arp/1_consultarARP",
            {
                "codigoUnidadeGerenciadora": uasg,
                "numeroAtaRegistroPreco": numero_arp,
                "dataVigenciaInicialMin": data_min,
                "dataVigenciaInicialMax": data_max,
            },
        )

        if not registros_arp:
            # Tenta sem zero padding (ex: "2/2026" em vez de "002/2026")
            numero_arp_sem_pad = f"{numero_seq}/{ano}"
            self.stdout.write(
                f"  Sem resultado com '{numero_arp}'. Tentando '{numero_arp_sem_pad}'..."
            )
            registros_arp = self._consultar_paginado(
                "/modulo-arp/1_consultarARP",
                {
                    "codigoUnidadeGerenciadora": uasg,
                    "numeroAtaRegistroPreco": numero_arp_sem_pad,
                    "dataVigenciaInicialMin": data_min,
                    "dataVigenciaInicialMax": data_max,
                },
            )

        if not registros_arp:
            raise CommandError(
                f"ARP {numero_arp} não encontrada na API para UASG {uasg}.\n"
                f"Verifique o número da ARP e o UASG. A ARP precisa estar com vigência "
                f"inicial em {data_min} a {data_max}."
            )

        dados_arp = registros_arp[0]
        self.stdout.write(f"  Encontrada: {dados_arp.get('objeto') or dados_arp.get('descricaoObjeto') or '(sem descrição)'[:60]}")

        # Endpoint 2 — itens da ARP
        self.stdout.write("→ Consultando itens (/modulo-arp/2_consultarARPItem)...")
        itens_api = self._consultar_paginado(
            "/modulo-arp/2_consultarARPItem",
            {
                "codigoUnidadeGerenciadora": uasg,
                "numeroAtaRegistroPreco": numero_arp,
                "dataVigenciaInicialMin": data_min,
                "dataVigenciaInicialMax": data_max,
            },
        )

        if not itens_api and numero_seq != numero_seq.zfill(3):
            itens_api = self._consultar_paginado(
                "/modulo-arp/2_consultarARPItem",
                {
                    "codigoUnidadeGerenciadora": uasg,
                    "numeroAtaRegistroPreco": f"{numero_seq}/{ano}",
                    "dataVigenciaInicialMin": data_min,
                    "dataVigenciaInicialMax": data_max,
                },
            )

        self.stdout.write(f"  Itens encontrados: {len(itens_api)}")

        # Órgão gerenciador no banco local
        orgao = Orgao.objects.first()
        if not orgao:
            raise CommandError("Nenhum Órgão cadastrado. Cadastre o MPPI primeiro.")

        # Importa com transação atômica
        with transaction.atomic():
            arp, criada = self._importar_arp(dados_arp, orgao, uasg, numero_arp, atualizar)

            if not criada and not atualizar:
                self.stdout.write(
                    self.style.WARNING(
                        f"ARP {numero_arp} já existe. Use --atualizar para sobrescrever."
                    )
                )
                return

            status_arp = "CRIADA" if criada else "ATUALIZADA"
            self.stdout.write(self.style.SUCCESS(f"  ARP {status_arp}: {arp}"))

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
                f"  ARP:              {status_arp}\n"
                f"  Itens criados:    {criados}\n"
                f"  Itens atualizados:{atualizados}\n"
                f"  Itens ignorados:  {ignorados}"
            )
        )

    # ------------------------------------------------------------------
    # Consulta paginada genérica
    # ------------------------------------------------------------------

    def _consultar_paginado(self, endpoint, params_base):
        """
        Percorre todas as páginas de um endpoint e retorna lista consolidada.
        A API retorna: { "data": [...], "pagina": N, "totalItens": N }
        ou diretamente uma lista.
        """
        resultados = []
        pagina = 1

        while True:
            params = {**params_base, "pagina": pagina, "tamanhoPagina": TAMANHO_PAGINA}
            url = f"{BASE_URL}{endpoint}"
            try:
                resp = requests.get(url, params=params, timeout=TIMEOUT)
                resp.raise_for_status()
                payload = resp.json()
            except requests.HTTPError as exc:
                raise CommandError(
                    f"Erro HTTP ao consultar {endpoint}: {exc}"
                )
            except requests.RequestException as exc:
                raise CommandError(
                    f"Erro de conexão ao consultar {endpoint}: {exc}"
                )

            # Normaliza resposta: lista direta ou paginada
            if isinstance(payload, list):
                resultados.extend(payload)
                break  # lista direta, sem paginação
            elif isinstance(payload, dict):
                # Tenta campos comuns de resposta paginada
                dados = (
                    payload.get("data")
                    or payload.get("itens")
                    or payload.get("resultado")
                    or payload.get("content")
                    or []
                )
                resultados.extend(dados)

                # Verifica se há mais páginas
                total = payload.get("totalItens") or payload.get("total") or 0
                if len(resultados) >= total or len(dados) < TAMANHO_PAGINA:
                    break
                pagina += 1
            else:
                break

        return resultados

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _importar_arp(self, dados, orgao, uasg, numero_arp, atualizar):
        """Cria ou atualiza AtaRegistroPrecos a partir dos dados da API."""
        # Mapeamento defensivo dos campos (nomes podem variar entre versões da API)
        objeto = (
            dados.get("objeto")
            or dados.get("descricaoObjeto")
            or dados.get("objetoAta")
            or ""
        )
        fornecedor = (
            dados.get("nomeRazaoSocial")
            or dados.get("razaoSocialFornecedor")
            or dados.get("fornecedor")
            or ""
        )
        cnpj = (
            dados.get("niFornecedor")
            or dados.get("cnpjFornecedor")
            or dados.get("cnpj")
            or ""
        )
        data_assinatura = self._parse_data(
            dados.get("dataAssinatura") or dados.get("dataPublicacao")
        )
        data_inicio = self._parse_data(
            dados.get("dataVigenciaInicial")
            or dados.get("dataInicioVigencia")
            or dados.get("dataAssinatura")
        )
        data_fim = self._parse_data(
            dados.get("dataVigenciaFinal")
            or dados.get("dataFimVigencia")
            or dados.get("dataVencimentoAta")
        )
        numero_pncp = (
            dados.get("numeroControlePncpAta")
            or dados.get("numeroPncp")
            or dados.get("numeroControlePNCP")
            or ""
        )
        id_compra = dados.get("idCompra") or dados.get("codigoCompra") or ""

        if not data_assinatura or not data_inicio or not data_fim:
            # Usa fallbacks razoáveis se a API não retornar datas completas
            from datetime import date, timedelta
            hoje = date.today()
            data_assinatura = data_assinatura or hoje
            data_inicio = data_inicio or hoje
            data_fim = data_fim or (hoje + timedelta(days=365))
            self.stdout.write(
                self.style.WARNING(
                    "  Aviso: datas não encontradas na resposta da API — usando fallback."
                )
            )

        defaults = {
            "objeto": objeto,
            "modalidade_origem": "pregao_eletronico",
            "fornecedor_razao_social": fornecedor,
            "fornecedor_cnpj_cpf": cnpj,
            "data_assinatura": data_assinatura,
            "data_inicio_vigencia": data_inicio,
            "data_fim_vigencia": data_fim,
            "numero_pncp": numero_pncp,
            "codigo_uasg_gerenciadora": uasg,
            "numero_controle_pncp_ata": numero_pncp,
            "id_compra_compras_gov": str(id_compra),
            "importada_da_api": True,
        }

        arp, criada = AtaRegistroPrecos.objects.get_or_create(
            orgao_gerenciador=orgao,
            numero_arp=numero_arp,
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
                or item_data.get("item")
                or 0
            )
        except (TypeError, ValueError):
            self.stdout.write(
                self.style.WARNING(f"  Item sem número válido — ignorado: {str(item_data)[:80]}")
            )
            return "ignorado"

        descricao = (
            item_data.get("descricaoItem")
            or item_data.get("descricao")
            or item_data.get("nome")
            or item_data.get("nomeItem")
            or ""
        )
        unidade = (
            item_data.get("unidadeFornecimento")
            or item_data.get("unidadeMedida")
            or item_data.get("siglaUnidadeFornecimento")
            or ""
        )
        qtd_registrada = self._parse_decimal(
            item_data.get("quantidadeRegistrada")
            or item_data.get("quantidade")
            or item_data.get("quantidadeItem")
        )
        valor_unitario = self._parse_decimal(
            item_data.get("valorUnitario")
            or item_data.get("valorUnitarioAjustado")
            or item_data.get("precoUnitario")
        )
        maximo_adesao = self._parse_decimal_nullable(item_data.get("maximoAdesao"))

        codigo_catmat = str(
            item_data.get("codigoItem")
            or item_data.get("codigoCatmat")
            or item_data.get("codigoPdm")
            or ""
        )
        codigo_item_int = None
        try:
            v = item_data.get("codigoItem") or item_data.get("codigoPdm")
            codigo_item_int = int(v) if v else None
        except (TypeError, ValueError):
            pass

        numero_lote = str(item_data.get("numeroLote") or item_data.get("lote") or "")

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

        if maximo_adesao is not None and maximo_adesao == Decimal("0"):
            self.stdout.write(
                self.style.WARNING(
                    f"  [AVISO] Item {numero_item} — carona desabilitada (maximoAdesao=0). "
                    f"Adesão exigirá SEI de autorização do MPPI."
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
        if not valor:
            return None
        formatos = [
            "%Y-%m-%d", "%d/%m/%Y",
            "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
        ]
        s = str(valor)
        for fmt in formatos:
            try:
                return datetime.strptime(s[:len(fmt)], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_decimal(self, valor):
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")

    def _parse_decimal_nullable(self, valor):
        """Retorna None se ausente, Decimal("0") se explicitamente zero."""
        if valor is None:
            return None
        try:
            return Decimal(str(valor).replace(",", "."))
        except InvalidOperation:
            return None
