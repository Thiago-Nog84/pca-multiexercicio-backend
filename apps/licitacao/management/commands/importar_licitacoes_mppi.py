"""
Management command: importar_licitacoes_mppi
============================================
Importa editais de licitação (Pregão, Concorrência, Concurso) e contratações diretas
(Dispensa, Inexigibilidade) dos anos de 2023 a 2026 para fortalecer a vinculação dos instrumentos.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import requests
from django.core.management.base import BaseCommand
from django.db import transaction
from apps.licitacao.models import ProcessoLicitatorio, ItemLicitacao


class Command(BaseCommand):
    help = "Importa editais de licitação e contratações diretas do MPPI (2023–2026)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            default="926092",
            help="Código UASG do MPPI (padrão: 926092)",
        )
        parser.add_argument(
            "--anos",
            nargs="+",
            type=int,
            default=[2023, 2024, 2025, 2026],
            help="Anos para importar (padrão: 2023 2024 2025 2026)",
        )

    def _parse_decimal(self, val):
        if val is None or val == "":
            return Decimal("0.00")
        try:
            return Decimal(str(val))
        except InvalidOperation:
            return Decimal("0.00")

    def _parse_date(self, val):
        if not val:
            return None
        val_str = str(val)[:10]
        try:
            return datetime.strptime(val_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def handle(self, *args, **options):
        uasg = options["uasg"]
        anos = options["anos"]

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"IMPORTAÇÃO DE LICITAÇÕES E CONTRATAÇÕES DIRETAS — MPPI ({uasg})")
        self.stdout.write(f"Anos selecionados: {anos}")
        self.stdout.write(f"{'='*60}\n")

        total_criados = 0
        total_atualizados = 0

        session = requests.Session()
        session.headers.update({"Accept": "application/json"})

        for ano in anos:
            self.stdout.write(f"→ Processando ano {ano}...")
            
            # 1. Licitações Lei 14.133 (Pregão, Concorrência, Concurso)
            modalidades_14133 = [
                (3, ProcessoLicitatorio.Modalidade.CONCURSO),
                (4, ProcessoLicitatorio.Modalidade.CONCORRENCIA_ELETRONICA),
                (5, ProcessoLicitatorio.Modalidade.CONCORRENCIA_PRESENCIAL),
                (6, ProcessoLicitatorio.Modalidade.PREGAO_ELETRONICO),
                (7, ProcessoLicitatorio.Modalidade.PREGAO_PRESENCIAL),
            ]

            for cod_mod, mod_choice in modalidades_14133:
                url = (
                    f"https://dadosabertos.compras.gov.br/modulo-contratacoes/1_consultarContratacoes_PNCP_14133"
                    f"?unidadeOrgaoCodigoUnidade={uasg}&dataPublicacaoPncpInicial={ano}-01-01"
                    f"&dataPublicacaoPncpFinal={ano}-12-31&codigoModalidade={cod_mod}&tamanhoPagina=500"
                )
                try:
                    resp = session.get(url, timeout=6)
                    if resp.status_code == 200:
                        resultados = resp.json().get("resultado", [])
                        for item in resultados:
                            num_compra = str(item.get("numeroCompra", "")).strip()
                            num_pncp = str(item.get("numeroControlePNCP", "")).strip()
                            num_edital = f"{num_compra.zfill(5)}/{ano}" if num_compra else f"PNCP-{ano}"
                            
                            with transaction.atomic():
                                obj, created = ProcessoLicitatorio.objects.update_or_create(
                                    numero_controle_pncp=num_pncp if num_pncp else f"{uasg}-{num_edital}",
                                    defaults={
                                        "numero_edital": num_edital,
                                        "numero_compra_api": num_compra,
                                        "ano": ano,
                                        "modalidade": mod_choice,
                                        "situacao": item.get("situacaoCompraNomePncp", "Publicado"),
                                        "objeto": item.get("objetoCompra", ""),
                                        "processo_sei": item.get("processo", ""),
                                        "valor_estimado": self._parse_decimal(item.get("valorTotalEstimado")),
                                        "valor_homologado": self._parse_decimal(item.get("valorTotalHomologado")),
                                        "data_publicacao": self._parse_date(item.get("dataPublicacaoPncp")),
                                        "lei": "Lei 14.133/2021",
                                    }
                                )
                                if created:
                                    total_criados += 1
                                else:
                                    total_atualizados += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  Aviso ao consultar mod {cod_mod} em {ano}: {e}"))

            # 2. Contratações Diretas / Compras sem Licitação (Dispensa e Inexigibilidade)
            url_sem_licitacao = (
                f"https://dadosabertos.compras.gov.br/modulo-legado/5_consultarComprasSemLicitacao"
                f"?co_uasg={uasg}&dt_ano_aviso={ano}&tamanhoPagina=500"
            )
            try:
                resp = session.get(url_sem_licitacao, timeout=6)
                if resp.status_code == 200:
                    resultados = resp.json().get("resultado", [])
                    for item in resultados:
                        nu_aviso = str(item.get("nu_aviso_licitacao", "")).strip()
                        num_edital = f"{nu_aviso.zfill(5)}/{ano}" if nu_aviso else f"CD-{ano}"
                        ds_mod = str(item.get("ds_modalidade_licitacao", "")).lower()
                        
                        if "inexig" in ds_mod:
                            mod_choice = ProcessoLicitatorio.Modalidade.INEXIGIBILIDADE
                        else:
                            mod_choice = ProcessoLicitatorio.Modalidade.DISPENSA

                        chave_pncp = f"CD-{uasg}-{num_edital}"
                        with transaction.atomic():
                            obj, created = ProcessoLicitatorio.objects.update_or_create(
                                numero_controle_pncp=chave_pncp,
                                defaults={
                                    "numero_edital": num_edital,
                                    "numero_compra_api": nu_aviso,
                                    "ano": ano,
                                    "modalidade": mod_choice,
                                    "situacao": "Homologado",
                                    "objeto": item.get("ds_objeto_licitacao", ""),
                                    "valor_estimado": self._parse_decimal(item.get("vr_estimado_licitacao")),
                                    "valor_homologado": self._parse_decimal(item.get("vr_estimado_licitacao")),
                                    "data_publicacao": self._parse_date(item.get("dt_declaracao_dispensa") or item.get("dt_publicacao")),
                                    "lei": "Lei 8.666/93 / Lei 14.133/21",
                                }
                            )
                            if created:
                                total_criados += 1
                            else:
                                total_atualizados += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  Aviso ao consultar compras sem licitação em {ano}: {e}"))

        # 3. Sincronizar editais a partir das ARPs locais (garantindo vinculação forte)
        self.stdout.write("→ Sincronizando editais a partir dos instrumentos locais...")
        from apps.srp.models import AtaRegistroPrecos
        for arp in AtaRegistroPrecos.objects.all():
            num_edital = arp.processo_licitatorio or f"PE-{arp.numero_arp}"
            num_pncp = arp.numero_pncp.split("-0000")[0] if arp.numero_pncp and "-0000" in arp.numero_pncp else arp.numero_pncp
            ano_arp = arp.data_inicio_vigencia.year if arp.data_inicio_vigencia else 2026
            
            vl_total_arp = sum(i.valor_unitario * i.quantidade_registrada for i in arp.itens.all()) if hasattr(arp, "itens") else Decimal("0.00")
            with transaction.atomic():
                obj, created = ProcessoLicitatorio.objects.get_or_create(
                    numero_edital=num_edital,
                    defaults={
                        "numero_controle_pncp": num_pncp or f"LOCAL-{num_edital}",
                        "ano": ano_arp,
                        "modalidade": ProcessoLicitatorio.Modalidade.PREGAO_ELETRONICO if "Pregão" in (arp.get_modalidade_origem_display() or "") else ProcessoLicitatorio.Modalidade.OUTROS,
                        "situacao": "Homologado",
                        "objeto": arp.objeto or f"Registro de Preços decorrente do processo {num_edital}",
                        "valor_estimado": vl_total_arp,
                        "valor_homologado": vl_total_arp,
                        "data_publicacao": arp.data_assinatura or arp.data_inicio_vigencia,
                        "lei": "Lei 14.133/2021",
                    }
                )
                if created:
                    total_criados += 1

        from apps.contratos.models import Contrato
        for c in Contrato.objects.all():
            if c.licitacao_origem is None:
                num_edital = c.numero_sei if c.numero_sei and len(c.numero_sei) > 3 else f"CT-{c.numero_contrato.replace('/', '-')}"
                num_pncp = c.numero_pncp.split("-0000")[0] if c.numero_pncp and "-0000" in c.numero_pncp else c.numero_pncp
                ano_ct = c.data_assinatura.year if c.data_assinatura else 2026
                texto_desc = f"{c.tipo or ''} {c.objeto or ''}".lower()
                mod = ProcessoLicitatorio.Modalidade.DISPENSA if "dispensa" in texto_desc else (ProcessoLicitatorio.Modalidade.INEXIGIBILIDADE if "inexig" in texto_desc else ProcessoLicitatorio.Modalidade.OUTROS)
                
                with transaction.atomic():
                    obj, created = ProcessoLicitatorio.objects.get_or_create(
                        numero_edital=num_edital[:50],
                        defaults={
                            "numero_controle_pncp": num_pncp or f"LOCAL-CT-{c.id}",
                            "ano": ano_ct,
                            "modalidade": mod,
                            "situacao": "Homologado",
                            "objeto": c.objeto or f"Contratação decorrente do contrato {c.numero_contrato}",
                            "valor_estimado": c.valor_inicial,
                            "valor_homologado": c.valor_inicial,
                            "data_publicacao": c.data_assinatura or c.data_inicio_vigencia,
                            "processo_sei": c.numero_sei,
                            "lei": c.tipo or "Lei 14.133/2021",
                        }
                    )
                    if created:
                        total_criados += 1

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(self.style.SUCCESS(f"Importação finalizada! Criados: {total_criados} | Atualizados: {total_atualizados}"))
        
        # Verificação da malha de vínculos
        from apps.srp.models import AtaRegistroPrecos
        from apps.contratos.models import Contrato
        
        arps_com_vinculo = [a for a in AtaRegistroPrecos.objects.all() if a.licitacao_origem is not None]
        contratos_com_vinculo = [c for c in Contrato.objects.all() if c.licitacao_origem is not None]
        
        self.stdout.write(f"Total de ARPs na base com Licitação vinculada: {len(arps_com_vinculo)} de {AtaRegistroPrecos.objects.count()}")
        self.stdout.write(f"Total de Contratos na base com Licitação vinculada: {len(contratos_com_vinculo)} de {Contrato.objects.count()}")
        self.stdout.write(f"{'='*60}\n")
