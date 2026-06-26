"""
Validacao de Demandas Clonadas -- fluxo similar ao IRPF.

GET  /pca/validar/<exercicio>/        -- lista itens pendentes por setor
POST /pca/validar/<exercicio>/acao/   -- acao em um item (confirmar/suspender/excluir/editar)
"""
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db import models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.models import UnidadeRequisitante
from .models import ItemPCA, PlanoContratacaoAnual


def _pca_by_exercicio(exercicio):
    return get_object_or_404(PlanoContratacaoAnual, exercicio=exercicio)


@method_decorator(login_required, name="dispatch")
class ValidacaoDemandas(View):
    template_name = "pca/validacao.html"

    def get(self, request, exercicio):
        pca = _pca_by_exercicio(exercicio)
        setor = request.GET.get("setor", "")
        q = request.GET.get("q", "").strip()

        pendentes = ItemPCA.objects.filter(
            dfd__pca=pca, status="pendente_validacao"
        ).select_related("dfd", "dfd__unidade", "origem_item", "origem_item__dfd")

        if setor:
            pendentes = pendentes.filter(dfd__unidade__sigla=setor)
        if q:
            pendentes = pendentes.filter(
                Q(descricao__icontains=q) | Q(codigo_pca__icontains=q)
            )
        pendentes = pendentes.order_by("dfd__unidade__sigla", "codigo_pca")

        # Resumo por setor
        resumo_setores = (
            ItemPCA.objects
            .filter(dfd__pca=pca, status="pendente_validacao")
            .values("dfd__unidade__sigla")
            .annotate(qtd=Count("id"))
            .order_by("dfd__unidade__sigla")
        )

        # Total ja validados neste PCA
        ja_confirmados = ItemPCA.objects.filter(
            dfd__pca=pca, origem_item__isnull=False
        ).exclude(status__in=["pendente_validacao", "suspenso"]).count()

        setores = UnidadeRequisitante.objects.order_by("sigla")

        # Itens pendentes vinculados a pelo menos uma ARP
        qtd_vinculados_arp = (
            ItemPCA.objects
            .filter(dfd__pca=pca, status="pendente_validacao", vinculos_arp__isnull=False)
            .distinct()
            .count()
        )

        context = {
            "pca": pca,
            "exercicio": exercicio,
            "pendentes": pendentes,
            "qtd_pendentes": ItemPCA.objects.filter(dfd__pca=pca, status="pendente_validacao").count(),
            "ja_confirmados": ja_confirmados,
            "qtd_vinculados_arp": qtd_vinculados_arp,
            "resumo_setores": resumo_setores,
            "setores": setores,
            "filtros": {"setor": setor, "q": q},
        }
        return render(request, self.template_name, context)


@method_decorator(login_required, name="dispatch")
class ValidacaoAcao(View):
    """Processa acao de um item: confirmar / suspender / excluir / editar."""

    def post(self, request, exercicio):
        acao = request.POST.get("acao")
        item_id = request.POST.get("item_id")
        item = get_object_or_404(ItemPCA, pk=item_id, status="pendente_validacao")
        pca = item.dfd.pca

        redirect_url = f"/pca/validar/{exercicio}/"
        setor = request.GET.get("setor", "")
        if setor:
            redirect_url += f"?setor={setor}"

        if acao == "confirmar":
            item.status = "nao_iniciado"
            item.save(update_fields=["status"])
            messages.success(request, f"Item {item.codigo_pca} confirmado para o PCA {exercicio}.")

        elif acao == "suspender":
            item.status = "suspenso"
            item.tipo_suspensao = request.POST.get("tipo_suspensao", "total")
            item.save(update_fields=["status", "tipo_suspensao"])
            messages.warning(request, f"Item {item.codigo_pca} marcado como suspenso.")

        elif acao == "excluir":
            codigo = item.codigo_pca
            item.delete()
            messages.info(request, f"Item {codigo} removido do PCA {exercicio}.")

        elif acao == "editar":
            # Atualiza valores e confirma
            campos = ["quantidade_estimada", "valor_unitario_estimado"]
            try:
                qtd = request.POST.get("quantidade_estimada")
                vunit = request.POST.get("valor_unitario_estimado")
                if qtd:
                    item.quantidade_estimada = float(qtd.replace(",", "."))
                if vunit:
                    item.valor_unitario_estimado = float(vunit.replace(",", "."))
                if qtd or vunit:
                    item.valor_total_estimado = item.quantidade_estimada * item.valor_unitario_estimado
                item.status = "nao_iniciado"
                item.save()
                messages.success(request, f"Item {item.codigo_pca} atualizado e confirmado.")
            except (ValueError, TypeError) as e:
                messages.error(request, f"Erro ao atualizar item: {e}")

        elif acao == "confirmar_todos":
            # Confirma todos pendentes do setor atual
            qs = ItemPCA.objects.filter(dfd__pca=pca, status="pendente_validacao")
            if setor:
                qs = qs.filter(dfd__unidade__sigla=setor)
            n = qs.update(status="nao_iniciado")
            messages.success(request, f"{n} item(ns) confirmado(s) em bloco.")

        return redirect(redirect_url)


# ---------------------------------------------------------------------------
# API JSON — ARPs vigentes para vinculação durante validação
# ---------------------------------------------------------------------------

@method_decorator(login_required, name="dispatch")
class ARPsVigentesJSON(View):
    """Retorna ARPs vigentes com seus itens para o modal de vinculação."""

    def get(self, request, exercicio):
        import datetime
        from apps.srp.models import AtaRegistroPrecos, VinculoARPUnidade

        hoje = datetime.date.today()
        q = request.GET.get("q", "").strip()
        setor = request.GET.get("setor", "").strip()  # filtro opcional por sigla

        arps_qs = (
            AtaRegistroPrecos.objects
            .filter(status="vigente", data_fim_vigencia__gte=hoje)
            .prefetch_related("vinculos_unidades__unidade")
        )
        if q:
            arps_qs = arps_qs.filter(
                models.Q(numero_arp__icontains=q) |
                models.Q(objeto__icontains=q) |
                models.Q(fornecedor_razao_social__icontains=q)
            )

        # Particionar: ARPs do setor primeiro (gestora/demandante), depois o restante
        if setor:
            arps_setor = arps_qs.filter(
                vinculos_unidades__unidade__sigla=setor
            ).distinct()
            ids_setor = set(arps_setor.values_list("pk", flat=True))
            arps_outras = arps_qs.exclude(pk__in=ids_setor)
            arps_ordenadas = list(arps_setor.order_by("numero_arp")[:50]) +                              list(arps_outras.order_by("numero_arp")[:20])
        else:
            arps_ordenadas = list(arps_qs.order_by("numero_arp")[:50])

        data = []
        for arp in arps_ordenadas:
            # Unidades vinculadas
            vinculos = [
                {
                    "sigla": v.unidade.sigla,
                    "nome": v.unidade.nome,
                    "papel": v.papel,
                    "papel_label": v.get_papel_display(),
                    "do_setor": v.unidade.sigla == setor if setor else False,
                }
                for v in arp.vinculos_unidades.all()
            ]
            eh_do_setor = any(v["do_setor"] for v in vinculos)

            itens = []
            for item in arp.itens.order_by("numero_item"):
                itens.append({
                    "id": item.pk,
                    "numero": item.numero_item,
                    "descricao": item.descricao[:120],
                    "unidade": item.unidade_fornecimento,
                    "valor_unitario": float(item.valor_unitario),
                    "qtd_registrada": float(item.quantidade_registrada),
                    "qtd_disponivel": float(item.quantidade_disponivel),
                    "qtd_comprometida_pca": float(item.quantidade_comprometida_pca),
                    "lote": item.numero_lote or "",
                })
            data.append({
                "id": arp.pk,
                "numero_arp": arp.numero_arp,
                "objeto": arp.objeto[:180],
                "fornecedor": arp.fornecedor_razao_social,
                "cnpj": arp.fornecedor_cnpj_cpf,
                "vigencia_fim": arp.data_fim_vigencia.strftime("%d/%m/%Y"),
                "vinculos": vinculos,
                "eh_do_setor": eh_do_setor,
                "itens": itens,
            })
        return JsonResponse({"arps": data})


@method_decorator(login_required, name="dispatch")
class ValidacaoVincularARP(View):
    """Cria ou remove VinculoPCAItemARP durante a validação."""

    def post(self, request, exercicio):
        from apps.srp.models import ItemARP, VinculoPCAItemARP
        from django.core.exceptions import ValidationError

        acao = request.POST.get("acao_arp")  # "vincular" | "desvincular"
        item_pca_id = request.POST.get("item_pca_id")
        item_arp_id = request.POST.get("item_arp_id")
        qtd_raw = request.POST.get("quantidade_comprometida", "").replace(",", ".")

        setor = request.GET.get("setor", "")
        redirect_url = f"/pca/validar/{exercicio}/" + (f"?setor={setor}" if setor else "")

        item_pca = get_object_or_404(ItemPCA, pk=item_pca_id)

        if acao == "desvincular":
            deleted, _ = VinculoPCAItemARP.objects.filter(
                item_pca=item_pca, item_arp_id=item_arp_id
            ).delete()
            if deleted:
                # Limpa is_srp se não houver mais vínculos
                if not item_pca.vinculos_arp.exists():
                    item_pca.is_srp = False
                    item_pca.save(update_fields=["is_srp"])
                messages.success(request, "Vínculo com ARP removido.")
            else:
                messages.warning(request, "Vínculo não encontrado.")
            return redirect(redirect_url)

        # Vincular
        try:
            qtd = float(qtd_raw) if qtd_raw else None
            if not qtd or qtd <= 0:
                messages.error(request, "Informe uma quantidade válida.")
                return redirect(redirect_url)

            item_arp = get_object_or_404(ItemARP, pk=item_arp_id)

            # Ativa is_srp automaticamente
            if not item_pca.is_srp:
                item_pca.is_srp = True
                item_pca.save(update_fields=["is_srp"])

            vinculo, created = VinculoPCAItemARP.objects.get_or_create(
                item_pca=item_pca,
                item_arp=item_arp,
                defaults={
                    "quantidade_comprometida": qtd,
                    "criado_por": request.user,
                },
            )
            if not created:
                # Atualiza quantidade
                from decimal import Decimal
                vinculo.quantidade_comprometida = Decimal(str(qtd))
                vinculo.save(update_fields=["quantidade_comprometida"])

            vinculo.full_clean()

            arp_str = f"ARP {item_arp.arp.numero_arp} — Item {item_arp.numero_item}"
            messages.success(
                request,
                f"Item {item_pca.codigo_pca or item_pca.pk} vinculado a {arp_str} "
                f"({qtd} {item_arp.unidade_fornecimento})."
            )
        except ValidationError as e:
            messages.error(request, f"Erro de validação: {'; '.join(e.messages)}")
        except (ValueError, TypeError):
            messages.error(request, "Quantidade inválida.")

        return redirect(redirect_url)
