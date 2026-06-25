"""
Management command: sincronizar_contratos_comprasnet
=====================================================
Sincroniza contratos e empenhos do Comprasnet Contratos com o banco local,
vinculando-os às ARPs quando possível e atualizando saldos.

Fluxo em duas fases:

  FASE 1 — Contratos (sem autenticação):
    Busca todos os contratos ativos (e opcionalmente inativos) da UG via
    GET /api/contrato/ug/{uasg} e salva como ContratoComprasnet.
    Tenta vincular cada contrato a uma AtaRegistroPrecos pelo licitacao_numero.

  FASE 2 — Empenhos por item (requer autenticação JWT):
    Para cada ItemARP que tem codigo_catmat_catser, busca via
    GET /api/v1/empenho/pdm/{catmat}/ug/{uasg}/ano/{ano} os empenhos do ano.
    Salva como EmpenhoComprasnet vinculados ao ItemARP.
    Atualiza ItemARP.quantidade_contratada com a soma dos empenhos
    (útil para ARPs importadas via PNCP que não têm quantidadeEmpenhada).

Usos:
    # Fase 1 apenas (sem credenciais)
    python manage.py sincronizar_contratos_comprasnet --uasg 926092

    # Fase 1 + Fase 2 (com credenciais no .env)
    python manage.py sincronizar_contratos_comprasnet --uasg 926092 --com-empenhos

    # Incluir contratos inativos
    python manage.py sincronizar_contratos_comprasnet --uasg 926092 --incluir-inativos

    # Especificar ano para empenhos (padrão: ano atual)
    python manage.py sincronizar_contratos_comprasnet --uasg 926092 --com-empenhos --ano 2026

    # Forçar credenciais via args (em vez do .env)
    python manage.py sincronizar_contratos_comprasnet --uasg 926092 --com-empenhos \\
        --cpf 000.000.000-00 --senha MinhasSenha123

    # Modo seco
    python manage.py sincronizar_contratos_comprasnet --uasg 926092 --com-empenhos --dry-run
"""

from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.srp.models import AtaRegistroPrecos, ContratoComprasnet, EmpenhoComprasnet, ItemARP
from apps.srp.services.comprasnet_contratos import (
    ComprasnetContratosAuthError,
    ComprasnetContratosClient,
    ComprasnetContratosError,
)


class Command(BaseCommand):
    help = "Sincroniza contratos e empenhos do Comprasnet Contratos com o banco local"

    def add_arguments(self, parser):
        parser.add_argument(
            "--uasg",
            default="926092",
            help="Código UASG da unidade gestora (padrão: 926092)",
        )
        parser.add_argument(
            "--incluir-inativos",
            action="store_true",
            default=False,
            help="Inclui contratos inativos/encerrados na sincronização",
        )
        parser.add_argument(
            "--com-empenhos",
            action="store_true",
            default=False,
            help="Executa a Fase 2: sincroniza empenhos por CATMAT (requer autenticação JWT)",
        )
        parser.add_argument(
            "--ano",
            type=int,
            default=date.today().year,
            help="Ano fiscal dos empenhos a sincronizar (padrão: ano atual)",
        )
        parser.add_argument(
            "--cpf",
            default="",
            help="CPF do usuário Comprasnet (substitui COMPRASNET_CONTRATOS_CPF do .env)",
        )
        parser.add_argument(
            "--senha",
            default="",
            help="Senha do usuário Comprasnet (substitui COMPRASNET_CONTRATOS_SENHA do .env)",
        )
        parser.add_argument(
            "--atualizar-saldo",
            action="store_true",
            default=False,
            help="Atualiza ItemARP.quantidade_contratada com a soma dos empenhos importados",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula sem gravar no banco",
        )

    def handle(self, *args, **options):
        uasg = options["uasg"].strip()
        incluir_inativos = options["incluir_inativos"]
        com_empenhos = options["com_empenhos"]
        ano = options["ano"]
        cpf = options["cpf"].strip()
        senha = options["senha"].strip()
        atualizar_saldo = options["atualizar_saldo"]
        dry_run = options["dry_run"]

        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN — nenhuma alteração será gravada.\n"))

        client = ComprasnetContratosClient(
            cpf=cpf or None,
            senha=senha or None,
        )

        resumo = {
            "contratos_criados": 0, "contratos_atualizados": 0,
            "contratos_vinculados": 0,
            "empenhos_criados": 0, "empenhos_atualizados": 0,
            "itens_saldo_atualizados": 0,
        }

        # ----------------------------------------------------------------
        # FASE 1 — Contratos (público)
        # ----------------------------------------------------------------
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"FASE 1 — Contratos públicos | UG: {uasg}")
        self.stdout.write(f"{'='*60}")

        contratos_api = client.get_contratos_ug(uasg, ativos=True)
        self.stdout.write(self.style.SUCCESS(f"  {len(contratos_api)} contrato(s) ativo(s) encontrado(s)."))

        if incluir_inativos:
            inativos = client.get_contratos_ug(uasg, ativos=False)
            self.stdout.write(self.style.SUCCESS(f"  {len(inativos)} contrato(s) inativo(s) encontrado(s)."))
            contratos_api.extend(inativos)

        # Monta índice de ARPs para linkagem com contratos.
        # Estratégia dupla:
        #   1. Por numero_arp (ex: "00036/2025") — campo licitacao_numero dos contratos
        #      frequentemente contém o número da ARP diretamente.
        #   2. Por processo_licitatorio (quando preenchido) — fallback para contratos
        #      cujo licitacao_numero é o número do pregão, não da ARP.
        # A chave 1 tem prioridade; a chave 2 pode sobrescrever se houver colisão
        # (improvável — formatos diferentes).
        arps_por_licitacao = {}
        for arp in AtaRegistroPrecos.objects.all():
            arps_por_licitacao[arp.numero_arp.strip().upper()] = arp
            if arp.processo_licitatorio:
                arps_por_licitacao[arp.processo_licitatorio.strip().upper()] = arp

        for dados in contratos_api:
            contrato_id = dados.get("id")
            if not contrato_id:
                continue

            numero = dados.get("numero") or ""
            objeto = dados.get("objeto") or ""
            fornecedor = dados.get("fornecedor") or {}
            fornecedor_nome = fornecedor.get("nome") or ""
            fornecedor_cnpj = fornecedor.get("cnpj_cpf_idgener") or ""
            licitacao_numero = dados.get("licitacao_numero") or ""
            modalidade = dados.get("modalidade") or ""
            categoria = dados.get("categoria") or ""
            situacao = dados.get("situacao") or "Ativo"
            processo = dados.get("processo") or ""
            valor_inicial = client.parse_decimal(dados.get("valor_inicial"))
            valor_global = client.parse_decimal(dados.get("valor_global"))
            valor_acumulado_raw = dados.get("valor_acumulado")
            valor_acumulado = client.parse_decimal(valor_acumulado_raw) if valor_acumulado_raw else None
            data_assinatura = client.parse_date(dados.get("data_assinatura"))
            vigencia_inicio = client.parse_date(dados.get("vigencia_inicio"))
            vigencia_fim = client.parse_date(dados.get("vigencia_fim"))

            # Tenta vincular à ARP
            arp_obj = None
            chave = licitacao_numero.strip().upper()
            if chave:
                arp_obj = arps_por_licitacao.get(chave)

            self.stdout.write(
                f"\n→ Contrato {numero} | {fornecedor_nome[:35]}"
                + (f" [→ ARP {arp_obj.numero_arp}]" if arp_obj else "")
            )

            if dry_run:
                resumo["contratos_criados"] += 1
                if arp_obj:
                    resumo["contratos_vinculados"] += 1
                continue

            defaults = {
                "numero": numero,
                "objeto": objeto,
                "fornecedor_nome": fornecedor_nome[:255],
                "fornecedor_cnpj": fornecedor_cnpj[:18],
                "licitacao_numero": licitacao_numero,
                "modalidade": modalidade[:50],
                "categoria": categoria[:50],
                "situacao": situacao[:20],
                "processo": processo[:60],
                "valor_inicial": valor_inicial,
                "valor_global": valor_global,
                "valor_acumulado": valor_acumulado,
                "data_assinatura": data_assinatura,
                "vigencia_inicio": vigencia_inicio,
                "vigencia_fim": vigencia_fim,
                "uasg": uasg,
                "arp": arp_obj,
            }

            with transaction.atomic():
                obj, criado = ContratoComprasnet.objects.update_or_create(
                    contrato_comprasnet_id=contrato_id,
                    defaults=defaults,
                )

            if criado:
                resumo["contratos_criados"] += 1
                self.stdout.write(self.style.SUCCESS("  CRIADO"))
            else:
                resumo["contratos_atualizados"] += 1
                self.stdout.write(self.style.WARNING("  ATUALIZADO"))

            if arp_obj:
                resumo["contratos_vinculados"] += 1
                self.stdout.write(f"  Vinculado à ARP {arp_obj.numero_arp}")

        # ----------------------------------------------------------------
        # FASE 2 — Empenhos por CATMAT (autenticado)
        # ----------------------------------------------------------------
        if not com_empenhos:
            self._exibir_resumo(resumo, dry_run)
            return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"FASE 2 — Empenhos por CATMAT (v1 auth) | UG: {uasg} | Ano: {ano}")
        self.stdout.write(f"{'='*60}")

        try:
            client.authenticate()
            self.stdout.write(self.style.SUCCESS("  Autenticado com sucesso."))
        except ComprasnetContratosAuthError as exc:
            self.stdout.write(self.style.ERROR(f"  Falha de autenticação: {exc}"))
            self.stdout.write(self.style.WARNING(
                "  Fase 2 cancelada. Defina COMPRASNET_CONTRATOS_CPF e "
                "COMPRASNET_CONTRATOS_SENHA no .env ou use --cpf e --senha."
            ))
            self._exibir_resumo(resumo, dry_run)
            return

        # Coleta itens com código catmat/catser
        itens_com_catmat = ItemARP.objects.exclude(codigo_catmat_catser="").select_related("arp")
        self.stdout.write(f"  {itens_com_catmat.count()} item(ns) com código CATMAT/CATSER.")

        # Agrupa por código (evita chamadas duplicadas)
        codigos_processados: dict[str, list[dict]] = {}

        for item in itens_com_catmat:
            codigo = item.codigo_catmat_catser.strip()
            if not codigo:
                continue

            if codigo not in codigos_processados:
                self.stdout.write(f"\n→ CATMAT {codigo} — {item.descricao[:50]}")
                try:
                    # Tenta primeiro como código PDM (material)
                    empenhos = client.get_empenhos_pdm(pdm=codigo, uasg=uasg, ano=ano)
                    if not empenhos:
                        # Se vazio, tenta como código de serviço
                        empenhos = client.get_empenhos_servico(codigo=codigo, uasg=uasg, ano=ano)
                    codigos_processados[codigo] = empenhos
                    self.stdout.write(f"  {len(empenhos)} empenho(s) encontrado(s).")
                except ComprasnetContratosError as exc:
                    self.stdout.write(self.style.WARNING(f"  Erro ao buscar empenhos: {exc}"))
                    codigos_processados[codigo] = []
            else:
                empenhos = codigos_processados[codigo]

            if not empenhos:
                continue

            qtd_total = self._importar_empenhos(
                empenhos, item, uasg, ano, dry_run, resumo
            )

            # Atualiza saldo do item com base nos empenhos importados
            if atualizar_saldo and not dry_run and qtd_total is not None:
                if item.quantidade_contratada != qtd_total:
                    saldo_anterior = item.quantidade_contratada   # captura antes de sobrescrever
                    item.quantidade_contratada = qtd_total
                    item.save(update_fields=["quantidade_contratada"])
                    resumo["itens_saldo_atualizados"] += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Saldo atualizado: {qtd_total} (era {saldo_anterior})"
                        )
                    )

        self._exibir_resumo(resumo, dry_run)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _importar_empenhos(
        self, empenhos: list[dict], item: ItemARP, uasg: str, ano: int,
        dry_run: bool, resumo: dict
    ):
        """
        Salva empenhos no banco e retorna a quantidade total empenhada.
        Retorna None se a lista de empenhos estiver vazia.
        """
        qtd_total = Decimal("0")

        for emp in empenhos:
            emp_id = emp.get("id") or emp.get("empenho_id")
            if not emp_id:
                continue

            numero = str(emp.get("numero") or emp.get("numero_empenho") or "")
            tipo = str(emp.get("tipo") or emp.get("tipo_empenho") or "")
            descricao = str(emp.get("descricao") or emp.get("descricao_item") or "")
            unidade = str(emp.get("unidade") or emp.get("unidade_medida") or "")

            # Usa parse_decimal do cliente (já importado no topo) para consistência
            qtd = ComprasnetContratosClient.parse_decimal(
                emp.get("quantidade") or emp.get("qtd") or 0
            )
            valor_unit = ComprasnetContratosClient.parse_decimal(
                emp.get("valor_unitario") or emp.get("valorunitario") or "0"
            )
            valor_total_emp = ComprasnetContratosClient.parse_decimal(
                emp.get("valor_total") or emp.get("valortotal") or "0"
            )
            data_emissao = ComprasnetContratosClient.parse_date(
                emp.get("data_emissao") or emp.get("data")
            )

            qtd_total += qtd

            if dry_run:
                resumo["empenhos_criados"] += 1
                continue

            with transaction.atomic():
                obj, criado = EmpenhoComprasnet.objects.update_or_create(
                    empenho_comprasnet_id=emp_id,
                    defaults={
                        "item_arp": item,
                        "numero": numero[:50],
                        "tipo": tipo[:50],
                        "codigo_catmat": item.codigo_catmat_catser[:20],
                        "descricao": descricao,
                        "unidade": unidade[:30],
                        "quantidade": qtd,
                        "valor_unitario": valor_unit,
                        "valor_total": valor_total_emp,
                        "data_emissao": data_emissao,
                        "ano": ano,
                        "uasg": uasg,
                    },
                )

            if criado:
                resumo["empenhos_criados"] += 1
            else:
                resumo["empenhos_atualizados"] += 1

        return qtd_total if empenhos else None

    def _exibir_resumo(self, resumo: dict, dry_run: bool):
        self.stdout.write(f"\n{'='*60}")
        prefixo = "DRY-RUN — " if dry_run else ""
        msg = (
            f"{prefixo}Sincronização concluída:\n"
            f"  Contratos criados:    {resumo['contratos_criados']}\n"
            f"  Contratos atualizados:{resumo['contratos_atualizados']}\n"
            f"  Contratos c/ ARP:     {resumo['contratos_vinculados']}\n"
            f"  Empenhos criados:     {resumo['empenhos_criados']}\n"
            f"  Empenhos atualizados: {resumo['empenhos_atualizados']}\n"
            f"  Itens saldo atualizados: {resumo['itens_saldo_atualizados']}"
        )
        self.stdout.write(self.style.SUCCESS(msg) if not dry_run else self.style.WARNING(msg))
