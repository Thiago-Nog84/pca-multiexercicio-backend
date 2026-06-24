"""
Management command: importar_arp_compras_gov
============================================
Importa ARPs do Compras.gov.br via API aberta (dadosabertos.compras.gov.br).

Modos de uso:
    # Importa TODAS as ARPs do MPPI de 2026 em diante (recomendado)
    python manage.py importar_arp_compras_gov --uasg 926092

    # Importa ARPs a partir de um ano específico
    python manage.py importar_arp_compras_gov --uasg 926092 --ano-inicio 2025

    # Lista as ARPs disponíveis sem importar
    python manage.py importar_arp_compras_gov --uasg 926092 --listar

    # Atualiza registros já existentes no banco
    python manage.py importar_arp_compras_gov --uasg 926092 --atualizar

    # Execução seca (sem gravar no banco)
    python manage.py importar_arp_compras_gov --uasg 926092 --dry-run

Fluxo:
    1. Busca todas as ARPs do UASG no período (Endpoint 1 — /modulo-arp/1_consultarARP)
    2. Busca TODOS os itens do UASG de uma vez (Endpoint 2 — /modulo-arp/2_consultarARPItem)
       e agrupa localmente por numeroAtaRegistroPreco (o filtro da API não funciona).
    3. Importa AtaRegistroPrecos + ItemARP no banco local

Importante:
    Os parâmetros dataVigenciaInicialMin e dataVigenciaInicialMax são OBRIGATÓRIOS na API.
    O comando usa ANO-INICIO/01/01 até ANO-ATUAL/12/31 como intervalo (API rejeita anos futuros).
    O número da ARP (numeroAtaRegistroPreco) é lido diretamente da resposta da API,
    eliminando problemas de formato (002/2026 vs 2/2026 vs 002 etc.).
"""

import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Orgao
from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://dadosabertos.compras.gov.br"
TIMEOUT = 30
TAMANHO_PAGINA = 500


class Command(BaseCommand):
    help = "Importa todas as ARPs do Compras.gov.br para um UASG (/modulo-arp/)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            required=True,
            help="Código UASG do órgão gerenciador (MPPI = 926092)",
        )
        parser.add_argument(
            "--ano-inicio",
            type=int,
            default=2026,
            help="Ano mínimo de vigência inicial das ARPs (padrão: 2026)",
        )
        parser.add_argument(
            "--atualizar",
            action="store_true",
            default=False,
            help="Atualiza registros já existentes no banco",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula a importação sem gravar no banco",
        )
        parser.add_argument(
            "--listar",
            action="store_true",
            default=False,
            help="Apenas lista as ARPs disponíveis na API sem importar",
        )

    def handle(self, *args, **options):
        uasg = options["uasg"].strip()
        ano_inicio = options["ano_inicio"]
        atualizar = options["atualizar"]
        dry_run = options["dry_run"]
        listar = options["listar"]

        ano_fim = date.today().year  # API rejeita datas futuras além do ano corrente

        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN — nenhuma alteração será gravada.\n"))

        # A API rejeita intervalos que cruzam anos — iteramos ano a ano
        anos = list(range(ano_inicio, ano_fim + 1))

        arps_api = []
        todos_itens_api = []

        for ano in anos:
            data_min = f"{ano}-01-01"
            data_max = f"{ano}-12-31"

            self.stdout.write(f"\n{'='*60}")
            self.stdout.write(f"UASG: {uasg} | Vigência: {data_min} a {data_max}")
            self.stdout.write(f"{'='*60}")

            # Passo 1 — Busca ARPs do ano
            self.stdout.write("→ Buscando ARPs disponíveis (/modulo-arp/1_consultarARP)...")
            arps_ano = self._consultar_paginado(
                "/modulo-arp/1_consultarARP",
                {
                    "codigoUnidadeGerenciadora": uasg,
                    "dataVigenciaInicialMin": data_min,
                    "dataVigenciaInicialMax": data_max,
                },
            )
            self.stdout.write(self.style.SUCCESS(f"  {len(arps_ano)} ARP(s) encontrada(s)."))
            arps_api.extend(arps_ano)

            if arps_ano:
                # Passo 2 — Busca itens do ano
                self.stdout.write("→ Buscando itens (/modulo-arp/2_consultarARPItem)...")
                itens_ano = self._consultar_paginado(
                    "/modulo-arp/2_consultarARPItem",
                    {
                        "codigoUnidadeGerenciadora": uasg,
                        "dataVigenciaInicialMin": data_min,
                        "dataVigenciaInicialMax": data_max,
                    },
                )
                self.stdout.write(self.style.SUCCESS(f"  {len(itens_ano)} item(ns) encontrado(s)."))
                todos_itens_api.extend(itens_ano)

        if not arps_api:
            self.stdout.write(self.style.WARNING(
                f"Nenhuma ARP encontrada para UASG {uasg} com vigência a partir de {ano_inicio}.\n"
                "Verifique o UASG ou tente um --ano-inicio menor."
            ))
            return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS(
            f"Total: {len(arps_api)} ARP(s) e {len(todos_itens_api)} item(ns) em {len(anos)} ano(s)."
        ))

        # Modo --listar: exibe tabela e encerra
        if listar:
            self._exibir_lista(arps_api)
            return

        # Agrupa itens por número de ARP
        itens_por_arp = defaultdict(list)
        for item in todos_itens_api:
            num = (
                item.get("numeroAtaRegistroPreco")
                or item.get("numeroAta")
                or item.get("numero")
                or ""
            )
            itens_por_arp[num].append(item)

        # Passo 3 — Importa cada ARP e seus itens
        orgao = Orgao.objects.first()
        if not orgao:
            raise CommandError("Nenhum Órgão cadastrado. Cadastre o MPPI primeiro.")

        resumo = {"arps_criadas": 0, "arps_atualizadas": 0, "arps_ignoradas": 0,
                  "itens_criados": 0, "itens_atualizados": 0, "itens_ignorados": 0}

        for dados_arp in arps_api:
            numero_arp_api = self._extrair_numero_arp(dados_arp)
            self.stdout.write(f"\n→ ARP {numero_arp_api or '(sem número)'} — "
                              f"{str(dados_arp.get('objeto') or dados_arp.get('descricaoObjeto') or '')[:50]}")

            # Usa os itens pré-agrupados para esta ARP
            itens_api = itens_por_arp.get(numero_arp_api, [])
            self.stdout.write(f"  Itens: {len(itens_api)}")

            if dry_run:
                resumo["arps_criadas"] += 1
                resumo["itens_criados"] += len(itens_api)
                continue

            # Extrai fornecedor do primeiro item (endpoint 1 não retorna fornecedor)
            fornecedor_nome = ""
            fornecedor_cnpj = ""
            if itens_api:
                fornecedor_nome = itens_api[0].get("nomeRazaoSocialFornecedor") or ""
                fornecedor_cnpj = itens_api[0].get("niFornecedor") or ""

            with transaction.atomic():
                arp_obj, criada, ignorada = self._importar_arp(
                    dados_arp, orgao, uasg, numero_arp_api, atualizar,
                    fornecedor_nome=fornecedor_nome,
                    fornecedor_cnpj=fornecedor_cnpj,
                )

                if ignorada:
                    resumo["arps_ignoradas"] += 1
                    self.stdout.write(f"  Ignorada (já existe — use --atualizar para sobrescrever)")
                    continue
                elif criada:
                    resumo["arps_criadas"] += 1
                    self.stdout.write(self.style.SUCCESS("  CRIADA"))
                else:
                    resumo["arps_atualizadas"] += 1
                    self.stdout.write(self.style.WARNING("  ATUALIZADA"))

                # Ao atualizar: remove itens que não existem mais na API
                if atualizar and itens_api:
                    numeros_api = set()
                    for item_data in itens_api:
                        try:
                            n = int(item_data.get("numeroItem") or item_data.get("numeroItemAta") or item_data.get("item") or 0)
                            if n:
                                numeros_api.add(n)
                        except (TypeError, ValueError):
                            pass
                    removidos = arp_obj.itens.exclude(numero_item__in=numeros_api).delete()
                    if removidos[0]:
                        self.stdout.write(self.style.WARNING(f"  {removidos[0]} item(ns) obsoleto(s) removido(s)."))

                for item_data in itens_api:
                    r = self._importar_item(item_data, arp_obj, atualizar)
                    resumo[f"itens_{r}s"] = resumo.get(f"itens_{r}s", 0) + 1

        # Sumário final
        self.stdout.write(f"\n{'='*60}")
        msg = (
            f"{'DRY-RUN — ' if dry_run else ''}Importação concluída:\n"
            f"  ARPs criadas:     {resumo['arps_criadas']}\n"
            f"  ARPs atualizadas: {resumo['arps_atualizadas']}\n"
            f"  ARPs ignoradas:   {resumo['arps_ignoradas']}\n"
            f"  Itens criados:    {resumo['itens_criados']}\n"
            f"  Itens atualizados:{resumo['itens_atualizados']}\n"
            f"  Itens ignorados:  {resumo['itens_ignorados']}"
        )
        self.stdout.write(self.style.SUCCESS(msg) if not dry_run else self.style.WARNING(msg))

    # ------------------------------------------------------------------
    # Consulta paginada
    # ------------------------------------------------------------------

    def _consultar_paginado(self, endpoint, params_base):
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
                raise CommandError(f"Erro HTTP em {endpoint}: {exc}")
            except requests.RequestException as exc:
                raise CommandError(f"Erro de conexão em {endpoint}: {exc}")

            if isinstance(payload, list):
                resultados.extend(payload)
                break

            if isinstance(payload, dict):
                dados = (
                    payload.get("resultado")
                    or payload.get("data")
                    or payload.get("itens")
                    or payload.get("content")
                    or []
                )
                resultados.extend(dados)
                paginas_restantes = payload.get("paginasRestantes", 0)
                total = (
                    payload.get("totalRegistros")
                    or payload.get("totalItens")
                    or payload.get("total")
                    or 0
                )
                if not dados or paginas_restantes == 0 or len(dados) < TAMANHO_PAGINA:
                    break
                pagina += 1
            else:
                break

        return resultados

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extrair_numero_arp(self, dados):
        """Extrai o número da ARP da resposta da API (formato variável)."""
        return (
            dados.get("numeroAtaRegistroPreco")
            or dados.get("numeroAta")
            or dados.get("numero")
            or ""
        )

    def _exibir_lista(self, arps_api):
        """Exibe lista formatada de ARPs encontradas na API."""
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"{'Nº ARP':<15} {'Fornecedor':<35} {'Vigência':<25} Objeto")
        self.stdout.write(f"{'-'*15} {'-'*35} {'-'*25} {'-'*30}")
        for a in arps_api:
            numero = self._extrair_numero_arp(a) or "?"
            fornecedor = str(a.get("nomeRazaoSocial") or a.get("razaoSocialFornecedor") or "")[:34]
            inicio = str(a.get("dataVigenciaInicial") or a.get("dataInicioVigencia") or "")[:10]
            fim = str(a.get("dataVigenciaFinal") or a.get("dataFimVigencia") or "")[:10]
            objeto = str(a.get("objeto") or a.get("descricaoObjeto") or "")[:40]
            self.stdout.write(f"{numero:<15} {fornecedor:<35} {inicio} → {fim}  {objeto}")
        self.stdout.write(f"\nTotal: {len(arps_api)} ARP(s)")

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------

    def _importar_arp(self, dados, orgao, uasg, numero_arp, atualizar,
                      fornecedor_nome="", fornecedor_cnpj=""):
        """Retorna (arp_obj, criada, ignorada)."""
        objeto = dados.get("objeto") or dados.get("descricaoObjeto") or dados.get("objetoAta") or ""
        # Endpoint 1 não retorna fornecedor — vem dos itens (endpoint 2)
        fornecedor = fornecedor_nome or dados.get("nomeRazaoSocial") or dados.get("razaoSocialFornecedor") or ""
        cnpj = fornecedor_cnpj or dados.get("niFornecedor") or dados.get("cnpjFornecedor") or ""
        data_assinatura = self._parse_data(dados.get("dataAssinatura") or dados.get("dataPublicacao"))
        data_inicio = self._parse_data(dados.get("dataVigenciaInicial") or dados.get("dataInicioVigencia") or dados.get("dataAssinatura"))
        data_fim = self._parse_data(dados.get("dataVigenciaFinal") or dados.get("dataFimVigencia") or dados.get("dataVencimentoAta"))
        numero_pncp = dados.get("numeroControlePncpAta") or dados.get("numeroPncp") or dados.get("numeroControlePNCP") or ""
        id_compra = str(dados.get("idCompra") or dados.get("codigoCompra") or "")

        hoje = date.today()
        from datetime import timedelta
        data_assinatura = data_assinatura or hoje
        data_inicio = data_inicio or hoje
        data_fim = data_fim or (hoje + timedelta(days=365))

        numero_banco = numero_arp or f"ARP-{id_compra or 'sem-numero'}"

        defaults = {
            "objeto": objeto,
            "modalidade_origem": "pregao_eletronico",
            "fornecedor_razao_social": fornecedor[:255],
            "fornecedor_cnpj_cpf": cnpj,
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
            numero_arp=numero_banco,
            defaults=defaults,
        )

        if not criada and not atualizar:
            return arp, False, True  # ignorada

        if not criada and atualizar:
            for campo, valor in defaults.items():
                setattr(arp, campo, valor)
            arp.save()
            return arp, False, False  # atualizada

        return arp, True, False  # criada

    def _importar_item(self, item_data, arp, atualizar):
        try:
            numero_item = int(
                item_data.get("numeroItem") or item_data.get("numeroItemAta") or item_data.get("item") or 0
            )
        except (TypeError, ValueError):
            return "ignorado"

        # Campos confirmados pela API (2_consultarARPItem):
        descricao = (item_data.get("descricaoItem") or item_data.get("descricao") or item_data.get("nomePdm") or "")
        unidade = (item_data.get("unidadeFornecimento") or item_data.get("siglaUnidadeFornecimento") or item_data.get("unidadeMedida") or "")
        qtd = self._parse_decimal(
            item_data.get("quantidadeHomologadaItem")  # campo confirmado
            or item_data.get("quantidadeRegistrada")
            or item_data.get("quantidade")
        )
        qtd_empenhada = self._parse_decimal(item_data.get("quantidadeEmpenhada"))  # disponível no endpoint 2
        valor = self._parse_decimal(item_data.get("valorUnitario") or item_data.get("valorUnitarioAjustado"))
        maximo_adesao = self._parse_decimal_nullable(item_data.get("maximoAdesao"))
        # codigoItem = código do catálogo (ex: 297847); codigoPdm = grupo PDM (ex: 1115)
        codigo_catmat = str(item_data.get("codigoItem") or item_data.get("codigoCatmat") or "")
        codigo_item_int = None
        try:
            v = item_data.get("codigoItem")
            codigo_item_int = int(v) if v else None
        except (TypeError, ValueError):
            pass
        numero_lote = str(item_data.get("numeroLote") or item_data.get("lote") or "")

        defaults = {
            "descricao": descricao,
            "unidade_fornecimento": unidade,
            "quantidade_registrada": qtd,
            "quantidade_contratada": qtd_empenhada,  # atualiza saldo empenhado
            "valor_unitario": valor,
            "codigo_catmat_catser": codigo_catmat,
            "codigo_item_compras_gov": codigo_item_int,
            "maximo_adesao_api": maximo_adesao,
            "importado_da_api": True,
            "numero_lote": numero_lote,
        }

        if maximo_adesao is not None and maximo_adesao == Decimal("0"):
            self.stdout.write(
                self.style.WARNING(f"  [AVISO] Item {numero_item} — carona desabilitada (maximoAdesao=0).")
            )

        item, criado = ItemARP.objects.get_or_create(arp=arp, numero_item=numero_item, defaults=defaults)

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
        s = str(valor)
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%f"]:
            try:
                return datetime.strptime(s[:len(fmt)], fmt).date()
            except ValueError:
                continue
        return None

    def _parse_decimal(self, valor):
        if valor is None:
            return Decimal("0")
        try:
            return Decimal(str(valor).replace(",", ".").strip())
        except InvalidOperation:
            return Decimal("0")

    def _parse_decimal_nullable(self, valor):
        if valor is None:
            return None
        try:
            return Decimal(str(valor).replace(",", ".").strip())
        except InvalidOperation:
            return None
