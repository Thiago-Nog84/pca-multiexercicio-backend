"""
Management command: importar_arp_pncp
=======================================
Importa ATAs do PNCP (Portal Nacional de Contratações Públicas) para ARPs que
não estão disponíveis na API do dadosabertos.compras.gov.br.

Fluxo por compra:
    1. GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{seq}/atas     → cabeçalho(s) da ATA
    2. GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{seq}/itens    → itens do pregão
    3. GET /v1/orgaos/{cnpj}/compras/{anoCompra}/{seq}/itens/{n}/resultados
                                                                → fornecedor + valor registrado

Usos:
    # Importa todas as ATAs de uma compra específica
    python manage.py importar_arp_pncp --cnpj 05805924000189 --ano-compra 2025 --seq-compra 71

    # Atualiza registros já existentes
    python manage.py importar_arp_pncp --cnpj 05805924000189 --ano-compra 2025 --seq-compra 71 --atualizar

    # Importa pelo número de controle PNCP (ex: 05805924000189-1-000071/2025)
    python manage.py importar_arp_pncp --numero-controle 05805924000189-1-000071/2025

    # Modo seco (sem gravar no banco)
    python manage.py importar_arp_pncp --cnpj 05805924000189 --ano-compra 2025 --seq-compra 71 --dry-run
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.core.models import Orgao
from apps.srp.models import AtaRegistroPrecos, ItemARP

BASE_URL = "https://pncp.gov.br/api/pncp/v1"
TIMEOUT = 30


class Command(BaseCommand):
    help = "Importa ATAs do PNCP para ARPs não disponíveis no dadosabertos.compras.gov.br"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cnpj",
            default="05805924000189",
            help="CNPJ do órgão no PNCP (MPPI = 05805924000189)",
        )
        parser.add_argument(
            "--ano-compra",
            type=int,
            help="Ano da compra no PNCP (ex: 2025)",
        )
        parser.add_argument(
            "--seq-compra",
            type=int,
            help="Sequencial da compra no PNCP (ex: 71)",
        )
        parser.add_argument(
            "--numero-controle",
            help="Número de controle PNCP (ex: 05805924000189-1-000071/2025). "
                 "Substitui --cnpj, --ano-compra e --seq-compra.",
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

    def handle(self, *args, **options):
        cnpj = options["cnpj"].strip().replace(".", "").replace("/", "").replace("-", "")
        ano_compra = options["ano_compra"]
        seq_compra = options["seq_compra"]
        numero_controle = options.get("numero_controle")
        atualizar = options["atualizar"]
        dry_run = options["dry_run"]

        # Parseia --numero-controle se fornecido (ex: 05805924000189-1-000071/2025)
        if numero_controle:
            cnpj, ano_compra, seq_compra = self._parsear_numero_controle(numero_controle)

        if not ano_compra or not seq_compra:
            raise CommandError(
                "Forneça --ano-compra e --seq-compra, "
                "ou --numero-controle (ex: 05805924000189-1-000071/2025)."
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN — nenhuma alteração será gravada.\n"))

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"PNCP | CNPJ: {cnpj} | Compra: {ano_compra}/{seq_compra}")
        self.stdout.write(f"{'='*60}")

        # 1. Busca ATAs da compra
        self.stdout.write(f"→ Buscando ATAs em /orgaos/{cnpj}/compras/{ano_compra}/{seq_compra}/atas ...")
        atas = self._get(f"/orgaos/{cnpj}/compras/{ano_compra}/{seq_compra}/atas")
        if isinstance(atas, dict):
            atas = atas.get("data") or atas.get("resultado") or []
        if not atas:
            raise CommandError("Nenhuma ATA encontrada para esta compra no PNCP.")
        self.stdout.write(self.style.SUCCESS(f"  {len(atas)} ATA(s) encontrada(s)."))

        # 2. Busca itens da compra (compartilhados entre todas as ATAs)
        self.stdout.write(f"→ Buscando itens em /orgaos/{cnpj}/compras/{ano_compra}/{seq_compra}/itens ...")
        itens_compra = self._get(f"/orgaos/{cnpj}/compras/{ano_compra}/{seq_compra}/itens")
        if isinstance(itens_compra, dict):
            itens_compra = itens_compra.get("data") or itens_compra.get("resultado") or []
        self.stdout.write(self.style.SUCCESS(f"  {len(itens_compra)} item(ns) encontrado(s)."))

        # 3. Busca resultados (vencedor + valor registrado) para cada item
        self.stdout.write("→ Buscando resultados (fornecedor e valor registrado) por item ...")
        resultados_por_item = {}
        for item in itens_compra:
            num = item.get("numeroItem")
            if not num:
                continue
            try:
                res = self._get(f"/orgaos/{cnpj}/compras/{ano_compra}/{seq_compra}/itens/{num}/resultados")
                if isinstance(res, dict):
                    res = res.get("data") or res.get("resultado") or []
                if res:
                    resultados_por_item[num] = res
            except CommandError:
                pass  # item sem resultado (cancelado/deserto)
        self.stdout.write(self.style.SUCCESS(f"  {len(resultados_por_item)} item(ns) com resultado."))

        # 4. Importa cada ATA
        orgao = Orgao.objects.first()
        if not orgao:
            raise CommandError("Nenhum Órgão cadastrado. Cadastre o MPPI primeiro.")

        resumo = {"arps_criadas": 0, "arps_atualizadas": 0, "arps_ignoradas": 0,
                  "itens_criados": 0, "itens_atualizados": 0, "itens_ignorados": 0}

        for ata in atas:
            seq_ata = ata.get("sequencialAta", 1)
            numero_arp = f"{str(ata.get('numeroAtaRegistroPreco', '')).zfill(5)}/{ata.get('anoAta', date.today().year)}"
            objeto = ata.get("objetoCompra") or ata.get("objeto") or ""
            numero_pncp = ata.get("numeroControlePNCP") or ""
            data_assinatura = self._parse_data(ata.get("dataAssinatura"))
            data_inicio = self._parse_data(ata.get("dataVigenciaInicio") or ata.get("dataVigenciaInicial"))
            data_fim = self._parse_data(ata.get("dataVigenciaFim") or ata.get("dataVigenciaFinal"))
            uasg = (ata.get("unidadeOrgao") or {}).get("codigoUnidade", "")

            self.stdout.write(f"\n→ ATA {numero_arp} | PNCP: {numero_pncp}")
            self.stdout.write(f"  Vigência: {data_inicio} → {data_fim}")
            self.stdout.write(f"  Objeto: {objeto[:80]}")

            # Determina fornecedor principal (primeiro resultado do item 1)
            fornecedor_nome = ""
            fornecedor_cnpj = ""
            for num_item, res_list in resultados_por_item.items():
                if res_list:
                    primeiro = res_list[0]
                    fornecedor_nome = primeiro.get("nomeRazaoSocialFornecedor") or ""
                    fornecedor_cnpj = primeiro.get("niFornecedor") or ""
                    break
            self.stdout.write(f"  Fornecedor: {fornecedor_nome or '(não encontrado)'}")

            if dry_run:
                resumo["arps_criadas"] += 1
                resumo["itens_criados"] += len(itens_compra)
                continue

            with transaction.atomic():
                hoje = date.today()
                from datetime import timedelta
                defaults = {
                    "objeto": objeto,
                    "modalidade_origem": "pregao_eletronico",
                    "fornecedor_razao_social": fornecedor_nome[:255],
                    "fornecedor_cnpj_cpf": fornecedor_cnpj,
                    "data_assinatura": data_assinatura or hoje,
                    "data_inicio_vigencia": data_inicio or hoje,
                    "data_fim_vigencia": data_fim or (hoje + timedelta(days=365)),
                    "numero_pncp": numero_pncp,
                    "numero_controle_pncp_ata": numero_pncp,
                    "codigo_uasg_gerenciadora": uasg,
                    "importada_da_api": True,
                }

                arp_obj, criada = AtaRegistroPrecos.objects.get_or_create(
                    orgao_gerenciador=orgao,
                    numero_arp=numero_arp,
                    defaults=defaults,
                )

                if not criada and not atualizar:
                    resumo["arps_ignoradas"] += 1
                    self.stdout.write("  Ignorada (já existe — use --atualizar para sobrescrever)")
                    continue

                if not criada and atualizar:
                    for campo, valor in defaults.items():
                        setattr(arp_obj, campo, valor)
                    arp_obj.save()
                    resumo["arps_atualizadas"] += 1
                    self.stdout.write(self.style.WARNING("  ATUALIZADA"))
                else:
                    resumo["arps_criadas"] += 1
                    self.stdout.write(self.style.SUCCESS("  CRIADA"))

                # Importa itens usando valores dos resultados (valor real registrado)
                for item in itens_compra:
                    num_item = item.get("numeroItem")
                    res_list = resultados_por_item.get(num_item, [])

                    # Usa resultado do vencedor se disponível (valor homologado > estimado)
                    if res_list:
                        resultado = res_list[0]
                        qtd = self._parse_decimal(resultado.get("quantidadeHomologada") or item.get("quantidade"))
                        valor = self._parse_decimal(resultado.get("valorUnitarioHomologado") or item.get("valorUnitarioEstimado"))
                        qtd_contratada = Decimal("0")
                    else:
                        qtd = self._parse_decimal(item.get("quantidade"))
                        valor = self._parse_decimal(item.get("valorUnitarioEstimado"))
                        qtd_contratada = Decimal("0")

                    descricao = item.get("descricao") or ""
                    unidade = item.get("unidadeMedida") or ""

                    item_defaults = {
                        "descricao": descricao,
                        "unidade_fornecimento": unidade,
                        "quantidade_registrada": qtd,
                        "quantidade_contratada": qtd_contratada,
                        "valor_unitario": valor,
                        "codigo_catmat_catser": str(item.get("catalogoCodigoItem") or ""),
                        "importado_da_api": True,
                        "numero_lote": "",
                    }

                    item_obj, item_criado = ItemARP.objects.get_or_create(
                        arp=arp_obj,
                        numero_item=num_item,
                        defaults=item_defaults,
                    )

                    if not item_criado and atualizar:
                        for campo, v in item_defaults.items():
                            setattr(item_obj, campo, v)
                        item_obj.save()
                        resumo["itens_atualizados"] += 1
                    elif item_criado:
                        resumo["itens_criados"] += 1
                    else:
                        resumo["itens_ignorados"] += 1

        # Sumário
        self.stdout.write(f"\n{'='*60}")
        msg = (
            f"{'DRY-RUN — ' if dry_run else ''}Importação PNCP concluída:\n"
            f"  ARPs criadas:     {resumo['arps_criadas']}\n"
            f"  ARPs atualizadas: {resumo['arps_atualizadas']}\n"
            f"  ARPs ignoradas:   {resumo['arps_ignoradas']}\n"
            f"  Itens criados:    {resumo['itens_criados']}\n"
            f"  Itens atualizados:{resumo['itens_atualizados']}\n"
            f"  Itens ignorados:  {resumo['itens_ignorados']}"
        )
        self.stdout.write(self.style.SUCCESS(msg) if not dry_run else self.style.WARNING(msg))

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _get(self, path):
        url = f"{BASE_URL}{path}"
        try:
            resp = requests.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as exc:
            raise CommandError(f"Erro HTTP em {path}: {exc}")
        except requests.RequestException as exc:
            raise CommandError(f"Erro de conexão em {path}: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parsear_numero_controle(self, numero):
        """
        Parseia número de controle PNCP para (cnpj, ano_compra, seq_compra).
        Formato esperado: 05805924000189-1-000071/2025
        ou: 05805924000189-1-000071/2025-000001
        """
        # Remove CNPJ (14 dígitos), depois o restante
        # Formato: {cnpj14}-{tipoCompra}-{sequencialCompra}/{anoCompra}[-{sequencialAta}]
        # ex:      05805924000189-1-000071/2025
        m = re.match(r"(\d{14})-\d+-(\d+)/(\d{4})", numero.strip())
        if not m:
            raise CommandError(
                f"Formato de número de controle inválido: '{numero}'. "
                "Esperado: 05805924000189-1-000071/2025"
            )
        cnpj = m.group(1)
        seq_compra = int(m.group(2))   # sequencial da compra (000071 → 71)
        ano_compra = int(m.group(3))   # ano (2025)
        return cnpj, ano_compra, seq_compra

    def _parse_data(self, valor):
        if not valor:
            return None
        s = str(valor)
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
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
