"""Views Django Templates — Módulo Contratos."""

import json
from datetime import date, timedelta
from decimal import Decimal

import io
import urllib.request
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from .models import Aditivo, Contrato
from .models_empenho import Empenho

# Modelos importados de fontes externas (srp app)
try:
    from apps.srp.models import ContratoARP, ContratoComprasnet
    _tem_dados_externos = True
except ImportError:
    _tem_dados_externos = False


@login_required
def proxy_instrumento_pdf(request, pk):
    """
    Serve o PDF do instrumento contratual assinado, em nova aba (inline).

    Prioridade da fonte:
      1. Upload manual (Contrato.arquivo_instrumento) — usado quando não há
         link automático (ex: contratos de fundos FPDC/FEPDC, só disponíveis
         no SEI, sem contrapartida pública no Comprasnet).
      2. Link remoto (Contrato.link_contrato) — PDF importado do Comprasnet
         Contratos, buscado ao vivo e repassado com Content-Disposition: inline.
    """
    contrato = get_object_or_404(Contrato, pk=pk)

    if contrato.arquivo_instrumento:
        try:
            with contrato.arquivo_instrumento.open("rb") as f:
                content = f.read()
        except Exception as exc:
            return HttpResponse(f"Não foi possível ler o arquivo enviado: {exc}", status=500)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = "inline; filename=\"instrumento.pdf\""
        return response

    url = contrato.link_contrato
    if not url:
        return HttpResponse("Link do instrumento não disponível para este contrato.", status=404)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = "inline; filename=\"instrumento.pdf\""
        return response
    except Exception as exc:
        return HttpResponse(
            f"Não foi possível recuperar o instrumento contratual: {exc}",
            status=502,
        )


@method_decorator(login_required, name="dispatch")
class DashboardContratosView(View):
    template_name = "contratos/dashboard.html"

    def get(self, request):
        hoje = date.today()
        d30  = hoje + timedelta(days=30)
        d60  = hoje + timedelta(days=60)
        d90  = hoje + timedelta(days=90)
        d120 = hoje + timedelta(days=120)

        # ── Contratos locais ──────────────────────────────────────────────
        contratos = Contrato.objects.select_related("orgao", "gestor")
        total_local    = contratos.count()
        vigentes_local = contratos.filter(status="vigente").count()
        encerrados     = contratos.filter(status="encerrado").count()
        rescindidos    = contratos.filter(status="rescindido").count()

        vencendo_30  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d30)).count()
        vencendo_60  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d60)).count()
        vencendo_90  = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d90)).count()
        vencendo_120 = contratos.filter(status="vigente", data_fim_vigencia__range=(hoje, d120)).count()

        valor_local      = contratos.filter(status="vigente").aggregate(v=Sum("valor_atual"))["v"] or 0
        saldo_disponivel = contratos.filter(status="vigente").aggregate(v=Sum("saldo_disponivel"))["v"] or 0
        valor_empenhado  = contratos.filter(status="vigente").aggregate(v=Sum("valor_empenhado"))["v"] or 0
        pct_empenhado    = round(float(valor_empenhado) / float(valor_local) * 100, 1) if valor_local else 0
        com_execucao     = contratos.filter(valor_empenhado__gt=0).count()
        ultima_sync_siafe = (
            contratos.filter(ultima_atualizacao_siafe__isnull=False)
            .order_by("-ultima_atualizacao_siafe")
            .values_list("ultima_atualizacao_siafe", flat=True)
            .first()
        )

        # Top contratos por valor empenhado (para tabela de execução)
        top_empenhados = list(
            contratos.filter(valor_empenhado__gt=0)
            .order_by("-valor_empenhado")[:10]
        )

        por_tipo = list(
            contratos.filter(status="vigente")
            .values("tipo")
            .annotate(qtd=Count("id"), valor=Sum("valor_atual"))
            .order_by("-valor")
        )

        # Alertas: TI → 120 dias; outros → 90 dias
        alertas_ti = list(
            contratos.filter(
                status="vigente", tipo="solucao_ti",
                data_fim_vigencia__range=(hoje, d120),
            ).order_by("data_fim_vigencia")[:5]
        )
        alertas_outros = list(
            contratos.filter(
                status="vigente",
                data_fim_vigencia__range=(hoje, d90),
            ).exclude(tipo="solucao_ti").order_by("data_fim_vigencia")[:5]
        )

        recentes = list(contratos.order_by("-criado_em")[:8])

        # ── Prazo Transparência CNMP: dias até dia 10 do mês subsequente ──
        if hoje.month == 12:
            dia_10_prox = date(hoje.year + 1, 1, 10)
        else:
            dia_10_prox = date(hoje.year, hoje.month + 1, 10)
        dias_ate_transparencia = (dia_10_prox - hoje).days

        # ── Contratos vigentes sem empenho registrado ──────────────────────
        contratos_sem_empenho = contratos.filter(
            status="vigente", valor_empenhado=0
        ).count()

        # ── Dados para gráfico de rosca — distribuição por status ─────────
        suspensos = contratos.filter(status="suspenso").count()
        grafico_status = json.dumps({
            "labels": ["Vigente", "Encerrado", "Rescindido", "Suspenso"],
            "data": [vigentes_local, encerrados, rescindidos, suspensos],
            "cores": ["#198754", "#6c757d", "#dc3545", "#f59e0b"],
        })

        # ── Dados para gráfico de barras — Empenhado vs Saldo (top 10) ───
        grafico_execucao = json.dumps({
            "labels": [c.numero_contrato for c in top_empenhados],
            "empenhado": [float(c.valor_empenhado or 0) for c in top_empenhados],
            "saldo": [float(c.saldo_disponivel or 0) for c in top_empenhados],
        })

        # ── Contratos Comprasnet (importados) ─────────────────────────────
        if _tem_dados_externos:
            cc_qs = ContratoComprasnet.objects.all()
            total_comprasnet   = cc_qs.count()
            ativos_comprasnet  = cc_qs.filter(situacao="Ativo").count()
            inativos_comprasnet = cc_qs.filter(situacao="Inativo").count()
            valor_comprasnet   = cc_qs.filter(situacao="Ativo").aggregate(v=Sum("valor_global"))["v"] or 0
            cc_venc_30 = cc_qs.filter(
                situacao="Ativo", vigencia_fim__range=(hoje, d30)
            ).count()
            cc_venc_90 = cc_qs.filter(
                situacao="Ativo", vigencia_fim__range=(hoje, d90)
            ).count()
            comprasnet_recentes = list(
                cc_qs.filter(situacao="Ativo").order_by("-data_assinatura")[:8]
            )
            comprasnet_vencendo = list(
                cc_qs.filter(situacao="Ativo", vigencia_fim__gte=hoje)
                .order_by("vigencia_fim")[:5]
            )
            ultima_importacao_cc = cc_qs.order_by("-importado_em").values_list(
                "importado_em", flat=True
            ).first()

            # ── Contratos decorrentes de ARP (importados) ─────────────────
            ca_qs = ContratoARP.objects.select_related("arp")
            total_contratos_arp  = ca_qs.count()
            caronas_cedidas      = ca_qs.filter(is_carona=True).count()
            proprios_arp         = ca_qs.filter(is_carona=False).count()
            valor_contratos_arp  = ca_qs.aggregate(v=Sum("valor_total"))["v"] or 0
            ca_vigentes          = ca_qs.filter(data_fim_vigencia__gte=hoje).count()
            ca_venc_30           = ca_qs.filter(
                is_carona=False, data_fim_vigencia__range=(hoje, d30)
            ).count()
            contratos_arp_recentes = list(
                ca_qs.filter(is_carona=False).order_by("-data_assinatura")[:6]
            )
            caronas_recentes = list(
                ca_qs.filter(is_carona=True).order_by("-data_assinatura")[:6]
            )
            ultima_importacao_arp = ca_qs.order_by("-importado_em").values_list(
                "importado_em", flat=True
            ).first()

        else:
            total_comprasnet = ativos_comprasnet = inativos_comprasnet = 0
            valor_comprasnet = cc_venc_30 = cc_venc_90 = 0
            comprasnet_recentes = comprasnet_vencendo = []
            ultima_importacao_cc = None
            total_contratos_arp = caronas_cedidas = proprios_arp = 0
            valor_contratos_arp = ca_vigentes = ca_venc_30 = 0
            contratos_arp_recentes = caronas_recentes = []
            ultima_importacao_arp = None

        # ── Conciliação: contratos no Comprasnet mas não cadastrados localmente ──
        # Heurística normalizada por número de contrato (ex: 00001/2026 -> 1/2026)
        import re
        def _norm_num(s):
            m = re.match(r"^0*(\d+)[/-](\d{4})", str(s or "").strip())
            return f"{int(m.group(1))}/{m.group(2)}" if m else str(s or "").strip()

        locais_norm = {_norm_num(num) for num in contratos.values_list("numero_contrato", flat=True)}
        nao_cadastrados = 0
        if _tem_dados_externos:
            nao_cadastrados = sum(
                1 for cc in ContratoComprasnet.objects.filter(situacao="Ativo")
                if _norm_num(cc.numero) not in locais_norm
            )

        context = {
            "hoje": hoje,
            # locais
            "total_local": total_local,
            "vigentes_local": vigentes_local,
            "encerrados": encerrados,
            "rescindidos": rescindidos,
            "valor_local": valor_local,
            "saldo_disponivel": saldo_disponivel,
            "vencendo_30": vencendo_30,
            "vencendo_60": vencendo_60,
            "vencendo_90": vencendo_90,
            "vencendo_120": vencendo_120,
            "por_tipo": por_tipo,
            "alertas_ti": alertas_ti,
            "alertas_outros": alertas_outros,
            "recentes": recentes,
            # execução orçamentária SIAFE
            "valor_empenhado": valor_empenhado,
            "pct_empenhado": pct_empenhado,
            "com_execucao": com_execucao,
            "top_empenhados": top_empenhados,
            "ultima_sync_siafe": ultima_sync_siafe,
            # comprasnet
            "total_comprasnet": total_comprasnet,
            "ativos_comprasnet": ativos_comprasnet,
            "inativos_comprasnet": inativos_comprasnet,
            "valor_comprasnet": valor_comprasnet,
            "cc_venc_30": cc_venc_30,
            "cc_venc_90": cc_venc_90,
            "comprasnet_recentes": comprasnet_recentes,
            "comprasnet_vencendo": comprasnet_vencendo,
            "ultima_importacao_cc": ultima_importacao_cc,
            # contratos arp
            "total_contratos_arp": total_contratos_arp,
            "caronas_cedidas": caronas_cedidas,
            "proprios_arp": proprios_arp,
            "valor_contratos_arp": valor_contratos_arp,
            "ca_vigentes": ca_vigentes,
            "ca_venc_30": ca_venc_30,
            "contratos_arp_recentes": contratos_arp_recentes,
            "caronas_recentes": caronas_recentes,
            "ultima_importacao_arp": ultima_importacao_arp,
            # conciliação
            "nao_cadastrados": nao_cadastrados,
            "tem_dados_externos": _tem_dados_externos,
            # novos: transparência, empenho pendente, gráficos
            "dias_ate_transparencia": dias_ate_transparencia,
            "dia_10_prox": dia_10_prox,
            "contratos_sem_empenho": contratos_sem_empenho,
            "grafico_status": grafico_status,
            "grafico_execucao": grafico_execucao,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class EmpenhosSIAFEView(View):
    template_name = "contratos/empenhos.html"

    def get(self, request):
        hoje = date.today()

        # Contratos com e sem empenho vinculado
        contratos_vigentes = Contrato.objects.select_related("orgao", "unidade_requisitante").filter(status="vigente")
        sem_empenho = contratos_vigentes.filter(valor_empenhado=0).order_by("orgao__sigla", "numero_contrato")
        com_empenho = contratos_vigentes.filter(valor_empenhado__gt=0).order_by("-valor_empenhado")

        # Totais gerais
        total_vigentes = contratos_vigentes.count()
        total_sem_empenho = sem_empenho.count()
        total_com_empenho = com_empenho.count()

        agg = contratos_vigentes.aggregate(
            val=Sum("valor_atual"),
            emp=Sum("valor_empenhado"),
        )
        valor_total_vigentes = agg["val"] or Decimal("0.00")
        valor_total_empenhado = agg["emp"] or Decimal("0.00")
        pct_empenhado = round(float(valor_total_empenhado) / float(valor_total_vigentes) * 100, 1) if valor_total_vigentes else 0

        # Empenhos registrados
        empenhos = Empenho.objects.select_related("contrato", "contrato__orgao").order_by(
            "-ano_exercicio", "contrato__orgao__sigla", "numero_empenho"
        )
        total_empenhos = empenhos.count()
        agg_emp = empenhos.aggregate(
            val_emp=Sum("valor_empenhado"),
            val_liq=Sum("valor_liquidado"),
            val_pago=Sum("valor_pago"),
        )
        total_valor_empenhado = agg_emp["val_emp"] or Decimal("0.00")
        total_valor_liquidado = agg_emp["val_liq"] or Decimal("0.00")
        total_valor_pago = agg_emp["val_pago"] or Decimal("0.00")

        # Distribuição por órgão
        por_orgao = (
            contratos_vigentes.values("orgao__sigla")
            .annotate(qtd=Count("id"), emp=Sum("valor_empenhado"), val=Sum("valor_atual"))
            .order_by("orgao__sigla")
        )

        # Filtros GET
        filtro_orgao = request.GET.get("orgao", "")
        filtro_status = request.GET.get("status", "")
        filtro_fonte = request.GET.get("fonte", "")
        filtro_elemento = request.GET.get("elemento", "")
        filtro_exercicio = request.GET.get("exercicio", "")
        busca = request.GET.get("q", "").strip()

        qs_empenhos = empenhos
        if filtro_orgao:
            qs_empenhos = qs_empenhos.filter(contrato__orgao__sigla=filtro_orgao)
        if filtro_status:
            qs_empenhos = qs_empenhos.filter(status_liquidacao=filtro_status)
        if filtro_fonte:
            qs_empenhos = qs_empenhos.filter(fonte_recurso=filtro_fonte)
        if filtro_elemento:
            qs_empenhos = qs_empenhos.filter(elemento_despesa=filtro_elemento)
        if filtro_exercicio:
            qs_empenhos = qs_empenhos.filter(ano_exercicio=filtro_exercicio)
        if busca:
            qs_empenhos = qs_empenhos.filter(
                Q(numero_empenho__icontains=busca)
                | Q(nome_favorecido__icontains=busca)
                | Q(contrato__numero_contrato__icontains=busca)
                | Q(descricao__icontains=busca)
            )

        # Ordenação por coluna (cabeçalhos clicáveis)
        ORDENAVEIS = {
            "ne": "numero_empenho",
            "contrato": "contrato__numero_contrato",
            "orgao": "contrato__orgao__sigla",
            "favorecido": "nome_favorecido",
            "elemento": "elemento_despesa",
            "valor": "valor_empenhado",
            "liquidado": "valor_liquidado",
            "status": "status_liquidacao",
            "data": "data_emissao",
        }
        sort = request.GET.get("sort", "valor")
        direcao = request.GET.get("dir", "desc")
        campo_ord = ORDENAVEIS.get(sort, "valor_empenhado")
        prefixo = "-" if direcao == "desc" else ""
        qs_empenhos = qs_empenhos.order_by(f"{prefixo}{campo_ord}", "-ano_exercicio")

        # ─── Agregações para gráficos gerenciais (drill-down) ───
        import json

        agg_org = list(
            qs_empenhos.values("contrato__orgao__sigla")
            .annotate(valor=Sum("valor_empenhado"), n=Count("id"))
            .order_by("-valor")
        )
        agg_fonte = list(
            qs_empenhos.values("fonte_recurso")
            .annotate(valor=Sum("valor_empenhado"), n=Count("id"))
            .order_by("-valor")
        )
        agg_elemento = list(
            qs_empenhos.exclude(elemento_despesa="")
            .values("elemento_despesa")
            .annotate(valor=Sum("valor_empenhado"), n=Count("id"))
            .order_by("-valor")[:10]
        )
        agg_favorecido = list(
            qs_empenhos.exclude(nome_favorecido="")
            .values("nome_favorecido")
            .annotate(valor=Sum("valor_empenhado"), n=Count("id"))
            .order_by("-valor")[:10]
        )

        chart_org = json.dumps({
            "labels": [x["contrato__orgao__sigla"] or "—" for x in agg_org],
            "valores": [float(x["valor"] or 0) for x in agg_org],
        })
        chart_fonte = json.dumps({
            "labels": [x["fonte_recurso"] or "—" for x in agg_fonte],
            "chaves": [x["fonte_recurso"] or "" for x in agg_fonte],
            "valores": [float(x["valor"] or 0) for x in agg_fonte],
        })
        chart_elemento = json.dumps({
            "labels": [x["elemento_despesa"] for x in agg_elemento],
            "chaves": [x["elemento_despesa"] for x in agg_elemento],
            "valores": [float(x["valor"] or 0) for x in agg_elemento],
        })
        chart_favorecido = json.dumps({
            "labels": [(x["nome_favorecido"] or "—")[:32] for x in agg_favorecido],
            "valores": [float(x["valor"] or 0) for x in agg_favorecido],
        })

        # Totais do recorte filtrado (para os cards da aba de empenhos)
        agg_filtrado = qs_empenhos.aggregate(v=Sum("valor_empenhado"), n=Count("id"))

        context = {
            "hoje": hoje,
            "total_vigentes": total_vigentes,
            "total_sem_empenho": total_sem_empenho,
            "total_com_empenho": total_com_empenho,
            "valor_total_vigentes": valor_total_vigentes,
            "valor_total_empenhado": valor_total_empenhado,
            "pct_empenhado": pct_empenhado,
            "contratos_sem_empenho": sem_empenho,
            "contratos_com_empenho": com_empenho[:20],
            "empenhos": qs_empenhos[:400],
            "total_empenhos": total_empenhos,
            "empenhos_filtrados": agg_filtrado["n"] or 0,
            "valor_empenhos_filtrados": agg_filtrado["v"] or Decimal("0.00"),
            "total_valor_empenhado": total_valor_empenhado,
            "total_valor_liquidado": total_valor_liquidado,
            "total_valor_pago": total_valor_pago,
            "por_orgao": list(por_orgao),
            "filtro_orgao": filtro_orgao,
            "filtro_status": filtro_status,
            "filtro_fonte": filtro_fonte,
            "filtro_elemento": filtro_elemento,
            "filtro_exercicio": filtro_exercicio,
            "busca": busca,
            "sort": sort,
            "dir": direcao,
            "orgaos": Contrato.objects.values_list("orgao__sigla", flat=True).distinct().order_by("orgao__sigla"),
            "status_choices": Empenho.STATUS_LIQUIDACAO,
            "fontes": Empenho.objects.exclude(fonte_recurso="").values_list("fonte_recurso", flat=True).distinct().order_by("fonte_recurso"),
            "exercicios": Empenho.objects.values_list("ano_exercicio", flat=True).distinct().order_by("-ano_exercicio"),
            "chart_org": chart_org,
            "chart_fonte": chart_fonte,
            "chart_elemento": chart_elemento,
            "chart_favorecido": chart_favorecido,
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class SincronizarExecucaoSIAFEView(View):
    """
    Dispara sincronização da execução orçamentária do SIAFE-PI (Notas de Empenho) para os contratos locais.
    """

    def post(self, request):
        saida = io.StringIO()
        try:
            call_command("atualizar_execucao_siafe", stdout=saida, stderr=saida)
            messages.success(request, "Execução Orçamentária do SIAFE-PI sincronizada com sucesso para todos os contratos.")
        except Exception as exc:
            messages.warning(request, f"Sincronização com o SIAFE-PI concluída com avisos/erros: {exc}")

        return redirect("contratos:dashboard")


# ---------------------------------------------------------------------------
# Painel de Vencimentos — alertas progressivos 120/90/60/30 dias
# ---------------------------------------------------------------------------

def _faixa_vencimento(dias):
    """Classifica dias restantes em faixa progressiva de alerta."""
    if dias < 0:
        return "vencido", "Vencido", "danger"
    if dias <= 30:
        return "d30", "Até 30 dias", "danger"
    if dias <= 60:
        return "d60", "31–60 dias", "warning"
    if dias <= 90:
        return "d90", "61–90 dias", "warning"
    if dias <= 120:
        return "d120", "91–120 dias", "info"
    return None, None, None


@method_decorator(login_required, name="dispatch")
class VencimentosView(View):
    """
    Painel consolidado de vencimentos: contratos, ARPs próprias e ARPs
    externas (caronas recebidas) com vigência encerrando em até 120 dias,
    em faixas progressivas 120/90/60/30 (padrão de mercado para gestão
    contratual — Lei 14.133/2021 exige planejamento tempestivo de
    renovações e novas licitações).
    """

    template_name = "contratos/vencimentos.html"
    HORIZONTE_DIAS = 120

    def get(self, request):
        from django.urls import reverse

        from apps.srp.models import ARPExterna, AtaRegistroPrecos

        hoje = date.today()
        limite = hoje + timedelta(days=self.HORIZONTE_DIAS)
        tipo_filtro = request.GET.get("tipo", "")
        faixa_filtro = request.GET.get("faixa", "")

        alertas = []

        contratos = Contrato.objects.filter(
            status="vigente", data_fim_vigencia__lte=limite
        ).select_related("unidade_requisitante", "gestor")
        for c in contratos:
            dias = (c.data_fim_vigencia - hoje).days
            faixa, faixa_label, cor = _faixa_vencimento(dias)
            alertas.append({
                "tipo": "contrato",
                "tipo_label": "Contrato",
                "numero": c.numero_contrato,
                "descricao": c.objeto,
                "parte": c.contratado_razao_social,
                "unidade": c.unidade_requisitante.sigla if c.unidade_requisitante else "",
                "data_fim": c.data_fim_vigencia,
                "dias": dias,
                "faixa": faixa,
                "faixa_label": faixa_label,
                "cor": cor,
                "url": reverse("admin:contratos_contrato_change", args=[c.pk]),
            })

        arps = AtaRegistroPrecos.objects.filter(
            status="vigente", data_fim_vigencia__lte=limite
        )
        for a in arps:
            dias = (a.data_fim_vigencia - hoje).days
            faixa, faixa_label, cor = _faixa_vencimento(dias)
            alertas.append({
                "tipo": "arp",
                "tipo_label": "ARP própria",
                "numero": a.numero_arp,
                "descricao": a.objeto,
                "parte": a.fornecedor_razao_social,
                "unidade": "",
                "data_fim": a.data_fim_vigencia,
                "dias": dias,
                "faixa": faixa,
                "faixa_label": faixa_label,
                "cor": cor,
                "url": reverse("srp:arp_detalhe", args=[a.pk]),
            })

        arps_ext = ARPExterna.objects.filter(
            status="ativa", data_fim_vigencia__lte=limite
        ).select_related("unidade_beneficiaria")
        for ae in arps_ext:
            dias = (ae.data_fim_vigencia - hoje).days
            faixa, faixa_label, cor = _faixa_vencimento(dias)
            alertas.append({
                "tipo": "arp_externa",
                "tipo_label": "Carona (ARP externa)",
                "numero": ae.numero_arp_origem,
                "descricao": ae.objeto,
                "parte": ae.orgao_gerenciador_nome,
                "unidade": ae.unidade_beneficiaria.sigla if ae.unidade_beneficiaria else "",
                "data_fim": ae.data_fim_vigencia,
                "dias": dias,
                "faixa": faixa,
                "faixa_label": faixa_label,
                "cor": cor,
                "url": reverse("admin:srp_arpexterna_change", args=[ae.pk]),
            })

        # Contadores por faixa (antes dos filtros, para os cards)
        contadores = {"vencido": 0, "d30": 0, "d60": 0, "d90": 0, "d120": 0}
        for al in alertas:
            if al["faixa"]:
                contadores[al["faixa"]] += 1

        if tipo_filtro:
            alertas = [al for al in alertas if al["tipo"] == tipo_filtro]
        if faixa_filtro:
            alertas = [al for al in alertas if al["faixa"] == faixa_filtro]

        for al in alertas:
            al["dias_abs"] = abs(al["dias"])
        alertas.sort(key=lambda al: al["dias"])

        context = {
            "alertas": alertas,
            "contadores": contadores,
            "total": len(alertas),
            "hoje": hoje,
            "horizonte": self.HORIZONTE_DIAS,
            "tipo_filtro": tipo_filtro,
            "faixa_filtro": faixa_filtro,
        }
        return render(request, self.template_name, context)
