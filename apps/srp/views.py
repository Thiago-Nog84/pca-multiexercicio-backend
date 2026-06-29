"""
Views do módulo SRP — Dashboard de Atas de Registro de Preços

Acesso: requer login (session auth via admin Django).
Rotas:
    /srp/                       → DashboardSRPView
    /srp/arp/<pk>/              → ARPDetalheView
    /srp/importar/              → ImportarARPView
    /srp/unidade/<sigla>/       → SRPUnidadeView
"""

import io
from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, Q, Sum
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import AtaRegistroPrecos, ContratoARP, ItemARP, VinculoARPUnidade


@method_decorator(login_required, name="dispatch")
class DashboardSRPView(View):
    """
    Dashboard principal do módulo SRP.
    Exibe estatísticas gerais e lista todas as ARPs do MPPI.
    """

    template_name = "srp/dashboard.html"

    def get(self, request):
        import json
        from collections import defaultdict
        from apps.core.models import UnidadeRequisitante

        hoje = date.today()
        arps = (
            AtaRegistroPrecos.objects.select_related("orgao_gerenciador")
            .prefetch_related("itens", "contratos_decorrentes", "contratos_arp", "vinculos_unidades__unidade")
            .order_by("-data_inicio_vigencia")
        )

        total_arps = arps.count()
        arps_vigentes = arps.filter(data_fim_vigencia__gte=hoje).exclude(status__in=["cancelada", "suspensa"]).count()
        arps_encerradas = arps.filter(
            Q(data_fim_vigencia__lt=hoje) | Q(status__in=["encerrada", "cancelada"])
        ).count()
        arps_criticas = arps.filter(
            data_fim_vigencia__gte=hoje,
            data_fim_vigencia__lte=hoje.replace(day=hoje.day)
        ).exclude(status__in=["cancelada", "suspensa"]).filter(
            data_fim_vigencia__lte=models.Value(hoje)
        )

        total_itens = ItemARP.objects.count()

        # Valores agregados
        valor_total = 0
        valor_contratado_total = 0

        arps_lista = []
        # Dados para gráficos
        por_status = defaultdict(int)       # {status: count}
        por_ano = defaultdict(float)        # {ano: valor}
        por_ano_count = defaultdict(int)    # {ano: count}
        top_valor = []                      # [(numero_arp, objeto, valor)]
        unidade_arps = defaultdict(list)    # {sigla: [arp_pk, ...]}

        for arp in arps:
            itens = list(arp.itens.all())
            valor_arp = float(sum(i.quantidade_registrada * i.valor_unitario for i in itens))
            valor_contratado_arp = float(sum(i.quantidade_contratada * i.valor_unitario for i in itens))
            dias_restantes = (arp.data_fim_vigencia - hoje).days if arp.data_fim_vigencia else None

            if arp.status in ("cancelada", "suspensa"):
                status_efetivo = arp.status
            elif arp.data_fim_vigencia and arp.data_fim_vigencia < hoje:
                status_efetivo = "encerrada"
            else:
                status_efetivo = "vigente"

            total_contratos_arp = (
                arp.contratos_decorrentes.count() +
                arp.contratos_arp.count()
            )
            percentual = round(valor_contratado_arp / valor_arp * 100, 1) if valor_arp else 0

            valor_total += valor_arp
            valor_contratado_total += valor_contratado_arp
            por_status[status_efetivo] += 1

            if arp.data_inicio_vigencia:
                ano = arp.data_inicio_vigencia.year
                por_ano[ano] += valor_arp
                por_ano_count[ano] += 1

            # Unidades vinculadas
            for v in arp.vinculos_unidades.all():
                unidade_arps[v.unidade.sigla].append(arp.pk)

            arps_lista.append({
                "arp": arp,
                "total_itens": len(itens),
                "valor_total": valor_arp,
                "valor_contratado": valor_contratado_arp,
                "percentual_consumido": percentual,
                "importada": arp.importada_da_api,
                "dias_restantes": dias_restantes,
                "status_efetivo": status_efetivo,
                "total_contratos": total_contratos_arp,
            })
            top_valor.append((arp.numero_arp, arp.objeto[:50], valor_arp, arp.pk))

        anos_disponiveis = sorted({
            a["arp"].data_inicio_vigencia.year
            for a in arps_lista if a["arp"].data_inicio_vigencia
        }, reverse=True)

        # Top 10 por valor
        top_valor.sort(key=lambda x: x[2], reverse=True)
        top_valor = top_valor[:10]

        # Unidades com ARPs — ordenadas por count desc
        unidades_com_arps = []
        for sigla, pks in sorted(unidade_arps.items(), key=lambda x: -len(x[1])):
            try:
                u = UnidadeRequisitante.objects.get(sigla=sigla)
                unidades_com_arps.append({"sigla": sigla, "nome": u.nome, "total": len(pks)})
            except UnidadeRequisitante.DoesNotExist:
                unidades_com_arps.append({"sigla": sigla, "nome": sigla, "total": len(pks)})

        # ARPs críticas (< 30 dias)
        arps_criticas_lista = [
            a for a in arps_lista
            if a["dias_restantes"] is not None and 0 <= a["dias_restantes"] < 30
        ]

        # JSON para Chart.js
        chart_status = json.dumps({
            "labels": list(por_status.keys()),
            "data": list(por_status.values()),
        })
        anos_sorted = sorted(por_ano.keys())
        chart_ano = json.dumps({
            "labels": [str(a) for a in anos_sorted],
            "valores": [round(por_ano[a], 2) for a in anos_sorted],
            "counts": [por_ano_count[a] for a in anos_sorted],
        })
        chart_top = json.dumps({
            "labels": [t[0] for t in top_valor],
            "objetos": [t[1] for t in top_valor],
            "valores": [round(t[2], 2) for t in top_valor],
            "pks": [t[3] for t in top_valor],
        })

        context = {
            "arps_lista": arps_lista,
            "total_arps": total_arps,
            "arps_vigentes": arps_vigentes,
            "arps_encerradas": arps_encerradas,
            "valor_total": valor_total,
            "valor_contratado_total": valor_contratado_total,
            "valor_disponivel_total": valor_total - valor_contratado_total,
            "total_itens": total_itens,
            "anos_disponiveis": anos_disponiveis,
            "unidades_com_arps": unidades_com_arps,
            "arps_criticas_lista": arps_criticas_lista,
            "chart_status": chart_status,
            "chart_ano": chart_ano,
            "chart_top": chart_top,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ARPDetalheView(View):
    """
    Detalhe de uma ARP: itens com saldos e vínculos PCA.
    """

    template_name = "srp/arp_detalhe.html"

    def get(self, request, pk):
        arp = get_object_or_404(
            AtaRegistroPrecos.objects.select_related("orgao_gerenciador", "criado_por"),
            pk=pk,
        )

        itens = (
            ItemARP.objects.filter(arp=arp)
            .prefetch_related("vinculos_pca__item_pca__dfd__unidade")
            .order_by("numero_lote", "numero_item")
        )

        itens_detalhados = []
        for item in itens:
            vinculos = item.vinculos_pca.select_related(
                "item_pca__dfd__unidade", "criado_por"
            ).all()

            itens_detalhados.append(
                {
                    "item": item,
                    "valor_total": item.quantidade_registrada * item.valor_unitario,
                    "comprometida_pca": item.quantidade_comprometida_pca,
                    "disponivel_eventual": item.quantidade_disponivel_eventual,
                    "disponivel": item.quantidade_disponivel,
                    "vinculos": vinculos,
                    "carona_bloqueada": (
                        item.maximo_adesao_api is not None
                        and item.maximo_adesao_api == 0
                    ),
                }
            )

        valor_total_arp = sum(d["valor_total"] for d in itens_detalhados)
        qtd_total_registrada = sum(i.quantidade_registrada for i in itens)
        qtd_total_contratada = sum(i.quantidade_contratada for i in itens)

        # Agrupa itens por lote para exibição no template.
        # Itens sem lote ficam num grupo com numero_lote="" (exibidos individualmente).
        # A ordem preserva a ordenação original (numero_lote, numero_item).
        lotes_agrupados = []
        lote_atual = None
        for det in itens_detalhados:
            nl = det["item"].numero_lote or ""
            if lote_atual is None or lote_atual["numero_lote"] != nl:
                lote_atual = {
                    "numero_lote": nl,
                    "tem_lote": bool(nl),
                    "itens": [],
                    "valor_total_lote": 0,
                    "qtd_registrada_lote": 0,
                    "qtd_contratada_lote": 0,
                }
                lotes_agrupados.append(lote_atual)
            lote_atual["itens"].append(det)
            lote_atual["valor_total_lote"] += det["valor_total"]
            lote_atual["qtd_registrada_lote"] += det["item"].quantidade_registrada
            lote_atual["qtd_contratada_lote"] += det["item"].quantidade_contratada

        # Contratos decorrentes desta ARP (com itens pré-carregados)
        contratos = (
            ContratoARP.objects.filter(arp=arp)
            .prefetch_related("itens__item_arp")
            .order_by("-data_assinatura", "uasg_contratante")
        )
        total_valor_contratos = sum(c.valor_total for c in contratos)

        context = {
            "arp": arp,
            "itens_detalhados": itens_detalhados,
            "lotes_agrupados": lotes_agrupados,
            "valor_total_arp": valor_total_arp,
            "qtd_total_registrada": qtd_total_registrada,
            "qtd_total_contratada": qtd_total_contratada,
            "total_itens": len(itens_detalhados),
            "total_lotes": sum(1 for l in lotes_agrupados if l["tem_lote"]),
            "contratos": contratos,
            "total_valor_contratos": total_valor_contratos,
            "total_contratos": contratos.count(),
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ImportarARPView(View):
    """
    Formulário para importar uma ARP via API Compras.gov.br.
    """

    template_name = "srp/importar_arp.html"

    def get(self, request):
        return render(request, self.template_name, {"uasg_padrao": "926092"})

    def post(self, request):
        uasg = request.POST.get("uasg", "926092").strip()
        ano_inicio = request.POST.get("ano_inicio", "2026").strip()
        atualizar = request.POST.get("atualizar") == "on"

        saida = io.StringIO()
        erro_cmd = None
        try:
            call_command(
                "importar_arp_compras_gov",
                uasg=uasg,
                ano_inicio=int(ano_inicio) if ano_inicio.isdigit() else 2026,
                atualizar=atualizar,
                stdout=saida,
                stderr=saida,
                no_color=True,
            )
        except Exception as exc:
            erro_cmd = str(exc)

        log = saida.getvalue()

        context = {
            "uasg_padrao": uasg,
            "ano_inicio": ano_inicio,
            "log": log,
            "erro_cmd": erro_cmd,
            "sucesso": erro_cmd is None,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class SRPUnidadeView(View):
    """
    Dashboard SRP por unidade requisitante.
    Responde: quais ARPs a unidade possui (como gestora ou demandante),
    quantos contratos cada uma originou, e qual o saldo ainda disponível.

    Também lista itens de ARPs vig entes com saldo para referenciar no PCA.
    """

    template_name = "srp/unidade_dashboard.html"

    def get(self, request, sigla):
        from apps.core.models import UnidadeRequisitante

        unidade = get_object_or_404(UnidadeRequisitante, sigla=sigla.upper())
        hoje = date.today()

        # Vínculos da unidade com ARPs (gestora e demandante)
        vinculos = (
            VinculoARPUnidade.objects.filter(unidade=unidade)
            .select_related("arp__orgao_gerenciador")
            .prefetch_related(
                "arp__itens__vinculos_pca",
                "arp__contratacoes_decorrentes",
                "arp__contratos_arp",
                "arp__contratos_decorrentes",  # Contrato.arp_origem
            )
            .order_by("papel", "-arp__data_inicio_vigencia")
        )

        arps_gestora = []
        arps_demandante = []

        for vinculo in vinculos:
            arp = vinculo.arp
            itens = list(arp.itens.all())

            valor_registrado = sum(i.quantidade_registrada * i.valor_unitario for i in itens)
            valor_contratado = sum(i.valor_total_contratado for i in itens)
            valor_disponivel = sum(i.valor_disponivel for i in itens)
            valor_comprometido_pca = sum(i.valor_comprometido_pca for i in itens)

            total_contratacoes = arp.contratacoes_decorrentes.count()
            total_contratos_api = arp.contratos_arp.count()
            # Contratos do módulo contratos com arp_origem preenchido
            total_contratos_mppi = arp.contratos_decorrentes.count() if hasattr(arp, "contratos_decorrentes") else 0

            # Deriva status efetivo
            if arp.status in ("cancelada", "suspensa"):
                status_efetivo = arp.status
            elif arp.data_fim_vigencia and arp.data_fim_vigencia < hoje:
                status_efetivo = "encerrada"
            else:
                status_efetivo = "vigente"

            dias_restantes = (arp.data_fim_vigencia - hoje).days if arp.data_fim_vigencia else None

            percentual_consumido = 0
            if valor_registrado:
                percentual_consumido = round(float(valor_contratado / valor_registrado) * 100, 1)

            info = {
                "arp": arp,
                "status_efetivo": status_efetivo,
                "dias_restantes": dias_restantes,
                "total_itens": len(itens),
                "valor_registrado": valor_registrado,
                "valor_contratado": valor_contratado,
                "valor_disponivel": valor_disponivel,
                "valor_comprometido_pca": valor_comprometido_pca,
                "total_contratos": total_contratacoes + total_contratos_api + total_contratos_mppi,
                "total_contratacoes_dec": total_contratacoes,
                "total_contratos_api": total_contratos_api,
                "total_contratos_mppi": total_contratos_mppi,
                "percentual_consumido": percentual_consumido,
            }

            if vinculo.papel == "gestora":
                arps_gestora.append(info)
            else:
                arps_demandante.append(info)

        # Itens com saldo disponivel para referenciar no PCA
        from django.db.models import F as _F
        itens_disponiveis = (
            ItemARP.objects.filter(
                arp__vinculos_unidades__unidade=unidade,
                arp__status="vigente",
                arp__data_fim_vigencia__gte=hoje,
                quantidade_registrada__gt=_F("quantidade_contratada") + _F("quantidade_cedida_carona"),
            )
            .select_related("arp")
            .prefetch_related("vinculos_pca")
            .distinct()
            .order_by("arp__numero_arp", "numero_item")
        )

        # Outras unidades que compartilham ARPs desta unidade
        todas_unidades = (
            UnidadeRequisitante.objects.filter(
                vinculos_arp__arp__vinculos_unidades__unidade=unidade
            )
            .exclude(pk=unidade.pk)
            .distinct()
            .order_by("sigla")
        )

        context = {
            "unidade": unidade,
            "arps_gestora": arps_gestora,
            "arps_demandante": arps_demandante,
            "total_arps": len(arps_gestora) + len(arps_demandante),
            "itens_disponiveis": itens_disponiveis,
            "total_itens_disponiveis": itens_disponiveis.count(),
            "outras_unidades": todas_unidades,
        }
        return render(request, self.template_name, context)
