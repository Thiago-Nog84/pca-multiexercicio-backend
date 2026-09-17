"""
Seletores de dados (query layer) para a fase de Planejamento da Contratação.
Consultas isoladas com otimizações de prefetch/select_related e tipagem estrita (PEP 484).
"""
from typing import Any, Dict, Optional
from django.db.models import QuerySet, Q
from .models import DocumentoOficializacaoDemanda, ETP, MatrizRisco, TermoReferencia


def get_dods_queryset(filtros: Optional[Dict[str, Any]] = None) -> QuerySet[DocumentoOficializacaoDemanda]:
    """Retorna QuerySet otimizado de DODs com prefetch de itens e relações."""
    filtros = filtros or {}
    qs = DocumentoOficializacaoDemanda.objects.select_related(
        "pca", "responsavel_preenchimento", "etp", "equipe_planejamento_ti"
    ).prefetch_related("itens")

    if filtros.get("pca"):
        qs = qs.filter(pca_id=filtros["pca"])
    if filtros.get("status"):
        qs = qs.filter(status=filtros["status"])
    if filtros.get("natureza"):
        qs = qs.filter(natureza_objeto=filtros["natureza"])
    if filtros.get("uo"):
        qs = qs.filter(unidade_orcamentaria=filtros["uo"])
    if filtros.get("q"):
        termo = filtros["q"].strip()
        qs = qs.filter(
            Q(identificador__icontains=termo)
            | Q(numero_sei__icontains=termo)
            | Q(objeto__icontains=termo)
        )
    return qs


def get_etps_queryset(filtros: Optional[Dict[str, Any]] = None) -> QuerySet[ETP]:
    """Retorna QuerySet otimizado de ETPs."""
    filtros = filtros or {}
    qs = ETP.objects.select_related(
        "dod", "ia_revisado_por", "matriz_risco", "termo_referencia"
    )
    if filtros.get("status"):
        qs = qs.filter(status=filtros["status"])
    if filtros.get("dod"):
        qs = qs.filter(dod_id=filtros["dod"])
    return qs


def get_termos_referencia_queryset(filtros: Optional[Dict[str, Any]] = None) -> QuerySet[TermoReferencia]:
    """Retorna QuerySet otimizado de Termos de Referência."""
    filtros = filtros or {}
    qs = TermoReferencia.objects.select_related("etp__dod")
    if filtros.get("status"):
        qs = qs.filter(status=filtros["status"])
    if filtros.get("etp"):
        qs = qs.filter(etp_id=filtros["etp"])
    return qs


def get_matrizes_risco_queryset(filtros: Optional[Dict[str, Any]] = None) -> QuerySet[MatrizRisco]:
    """Retorna QuerySet otimizado de Matrizes de Risco com itens."""
    filtros = filtros or {}
    qs = MatrizRisco.objects.select_related("etp__dod").prefetch_related("itens")
    if filtros.get("fase"):
        qs = qs.filter(fase_atual=filtros["fase"])
    if filtros.get("etp"):
        qs = qs.filter(etp_id=filtros["etp"])
    return qs
