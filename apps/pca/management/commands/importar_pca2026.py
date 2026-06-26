"""
Management command: importar_pca2026
Importa o CSV de demandas do PCA 2026 exportado do projeto legado (pca-mppi/Supabase)
para os models Django: PlanoContratacaoAnual, DocumentoFormalizacaoDemanda, ItemPCA.

Uso:
    python manage.py importar_pca2026 --csv caminho/para/demandas2026.csv [--dry-run]

O comando e idempotente: pode ser executado multiplas vezes sem duplicar dados.
Cada item e identificado pelo campo IDENTIFICADOR DA CONTRATACAO (ex: "CAA 1").
"""

import csv
import decimal
import re
import sys
from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

User = get_user_model()

# ---------------------------------------------------------------------------
# Mapeamentos de campos do CSV -> choices do modelo Django
# ---------------------------------------------------------------------------

CLASSE_PARA_CATEGORIA = {
    "Material de Consumo":              "material",
    "Material Permanente":              "material",
    "Servico":                          "servico",
    "Serviço":                          "servico",
    "Servico Tercerizado":              "servico",
    "Serviço Tercerizado":              "servico",
    "Treinamento - Qualificacao Profissional": "servico",
    "Treinamento - Qualificação Profissional": "servico",
    "Servico de TI":                    "solucao_ti",
    "Serviço de TI":                    "solucao_ti",
    "Software":                         "solucao_ti",
    "Servico de Engenharia":            "obras",
    "Serviço de Engenharia":            "obras",
    "Obra":                             "obras",
}

TIPO_PARA_TIPO_DEMANDA = {
    "Nova Contratacao":          "nova",
    "Nova Contratação":          "nova",
    "Nova contratacao":          "nova",
    "Nova contratação":          "nova",
    "Contrato - Renovacao":      "renovacao",
    "Contrato - Renovação":      "renovacao",
    "Contrato - Apostilamento":  "apostilamento",
    "Contrato - Repactuacao":    "repactuacao",
    "Contrato - Repactuação":    "repactuacao",
    "Contrato - Nao Renovavel":  "nova",
    "Contrato - Não Renovável":  "nova",
    "Contrato - Indeterminado":  "indeterminado",
}

MODO_PARA_CLASSIFICACAO = {
    "Fornecimento Continuado":  "continuo_fornecimento",
    "Servico Continuado":       "continuo_servico",
    "Serviço Continuado":       "continuo_servico",
    "Recorrente":               "continuo_fornecimento",
    "Fornecimento Unico":       "eventual",
    "Fornecimento Único":       "eventual",
}

MODALIDADE_PARA_MODALIDADE = {
    "Pregao Eletronico":  "pregao_eletronico",
    "Pregão Eletrônico":  "pregao_eletronico",
    "Concorrencia":       "concorrencia",
    "Concorrência":       "concorrencia",
    "Concurso":           "concurso",
    "Dispensa":           "dispensa",
    "Inexigibilidade":    "inexigibilidade",
    "Ata Vigente":        "arp_carona",
    "Outros":             "dispensa",
}

NORMATIVO_PARA_NORMATIVO = {
    "Lei 14.133/2021": "14133_2021",
    "Lei 8.666/1993":  "8666_1993",
}

PRIORIDADE_PARA_GRAU = {
    "Alta":  "alto",
    "Media": "medio",
    "Média": "medio",
    "Baixa": "baixo",
}

ETAPA_PARA_STATUS = {
    "":                                                  "nao_iniciado",
    "PLANEJAMENTO - DFD":                               "nao_iniciado",
    "PLANEJAMENTO - CORRECAO TR":                       "nao_iniciado",
    "PLANEJAMENTO - CORREÇÃO TR":                       "nao_iniciado",
    "PLANEJAMENTO -CORRECAO MAPA DE PRECOS E MAPA DE RISCOS": "nao_iniciado",
    "PLANEJAMENTO -CORREÇÃO MAPA DE PREÇOS E MAPA DE RISCOS": "nao_iniciado",
    "ANALISE DOS ARTEFATOS DA CONTRATACAO":             "em_andamento",
    "ANÁLISE DOS ARTEFATOS DA CONTRATAÇÃO":             "em_andamento",
    "PARECER ORCAMENTARIO":                             "em_andamento",
    "PARECER ORÇAMENTÁRIO":                             "em_andamento",
    "PARECER DA FASE EXTERNA":                          "em_andamento",
    "FISCAL - EM EXECUCAO":                             "em_andamento",
    "FISCAL - EM EXECUÇÃO":                             "em_andamento",
    "FISCAL - EM RENOVACAO CONTRATO":                   "em_andamento",
    "FISCAL - EM RENOVAÇÃO CONTRATO":                   "em_andamento",
    "ANALISANDO ADITAMENTO":                            "em_andamento",
    "AGUARDANDO DECISAO":                               "em_diligencia",
    "AGUARDANDO DECISÃO":                               "em_diligencia",
    "CANCELADO/ARQUIVADO":                              "suspenso",
}

# Setores do CSV que nao existem identicamente nas UnidadeRequisitante — remapear
SETOR_REMAP = {
    "PLANEJAMENTO": "APG",
}

UO_MAP = {
    "PGJ":   "pgj",
    "FMMP":  "fmmp",
    "FEPDC": "fepdc",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalizar(s):
    """Remove acentos e normaliza espacos para lookup em dicionarios."""
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii").strip()


def parse_decimal(val):
    """Converte 'R$ 1.234,56' ou '1234.56' para Decimal."""
    if not val or val.strip() in ("-", "nao se aplica", "nao se aplica"):
        return decimal.Decimal("0.00")
    val = re.sub(r"[R$\s]", "", val)   # remove R$ e espacos
    val = val.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    try:
        return decimal.Decimal(val)
    except decimal.InvalidOperation:
        return decimal.Decimal("0.00")


def parse_date(val):
    """Converte 'd/m/yyyy' ou 'dd/mm/yyyy' para date, retorna None se invalido."""
    if not val or val.strip() in ("-", ""):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def lookup(mapping, raw, field_name, row_id, warn_list):
    """Busca no mapeamento normalizando a chave; adiciona aviso se nao encontrar."""
    normalized = normalizar(raw)
    for k, v in mapping.items():
        if normalizar(k) == normalized:
            return v
    warn_list.append(f"  [{row_id}] Campo '{field_name}': valor desconhecido '{raw}'")
    return None


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = "Importa demandas do PCA 2026 a partir do CSV exportado do projeto legado pca-mppi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default="",
            help="Caminho para o arquivo demandas2026.csv",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a importacao sem gravar no banco",
        )
        parser.add_argument(
            "--orgao-pk",
            type=int,
            default=1,
            help="PK do Orgao a usar (padrao=1)",
        )
        parser.add_argument(
            "--exercicio",
            type=int,
            default=2026,
            help="Exercicio do PCA a criar/usar (padrao=2026)",
        )

    def handle(self, *args, **options):
        from apps.core.models import Orgao, UnidadeRequisitante
        from apps.pca.models import (
            DocumentoFormalizacaoDemanda,
            ItemPCA,
            PlanoContratacaoAnual,
        )

        csv_path = options["csv"]
        dry_run = options["dry_run"]
        exercicio = options["exercicio"]
        orgao_pk = options["orgao_pk"]

        if not csv_path:
            # Tenta localizar automaticamente
            import os
            candidates = [
                "apps/pca/fixtures/demandas2026.csv",
                "../pca-mppi/public/demandas2026.csv",
            ]
            for c in candidates:
                if os.path.exists(c):
                    csv_path = c
                    break
            if not csv_path:
                raise CommandError(
                    "Informe o caminho do CSV com --csv CAMINHO.\n"
                    "Exemplo: python manage.py importar_pca2026 "
                    "--csv apps/pca/fixtures/demandas2026.csv"
                )

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Importacao PCA {exercicio} — {csv_path} ==="
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("  [DRY RUN] Nenhum dado sera gravado."))

        # ── 1. Carrega CSV ──────────────────────────────────────────────────
        try:
            with open(csv_path, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError:
            raise CommandError(f"Arquivo nao encontrado: {csv_path}")

        self.stdout.write(f"  Linhas no CSV: {len(rows)}")

        # ── 2. Orgao e PCA ──────────────────────────────────────────────────
        try:
            orgao = Orgao.objects.get(pk=orgao_pk)
        except Orgao.DoesNotExist:
            raise CommandError(
                f"Orgao pk={orgao_pk} nao encontrado. "
                "Crie o orgao primeiro ou use --orgao-pk."
            )

        warnings = []
        criados = 0
        ignorados = 0
        erros = 0

        with transaction.atomic():
            pca, pca_criado = PlanoContratacaoAnual.objects.get_or_create(
                orgao=orgao,
                exercicio=exercicio,
                defaults={"status": "aprovado"},
            )
            if pca_criado:
                self.stdout.write(f"  PCA {exercicio} criado (pk={pca.pk})")
            else:
                self.stdout.write(f"  PCA {exercicio} ja existe (pk={pca.pk})")

            # ── 3. Pre-carrega unidades ─────────────────────────────────────
            unidades = {u.sigla: u for u in UnidadeRequisitante.objects.filter(orgao=orgao)}

            # ── 4. DFDs por setor (um por setor) ───────────────────────────
            dfds = {}  # sigla -> DFD

            for row in rows:
                setor_raw = row.get("SETOR REQUISITANTE", "").strip()
                setor = SETOR_REMAP.get(setor_raw, setor_raw)
                if setor not in unidades:
                    warnings.append(
                        f"  Setor '{setor}' nao encontrado nas UnidadeRequisitante — "
                        "crie-o no Admin primeiro."
                    )
                    continue
                if setor not in dfds:
                    unidade = unidades[setor]
                    dfd, _ = DocumentoFormalizacaoDemanda.objects.get_or_create(
                        pca=pca,
                        numero_dfd=f"IMP-{exercicio}-{setor}",
                        defaults={
                            "unidade": unidade,
                            "descricao_objeto": (
                                f"Demandas importadas do PCA {exercicio} "
                                f"— {setor} ({unidade.nome})"
                            ),
                            "justificativa": (
                                f"Importacao automatica do PCA {exercicio} a partir "
                                f"do sistema legado pca-mppi (Supabase)."
                            ),
                            "prazo_necessidade": date(exercicio, 12, 31),
                            "grau_prioridade": "medio",
                            "status": "aprovado",
                        },
                    )
                    dfds[setor] = dfd

            # ── 5. Itens ────────────────────────────────────────────────────
            contadores_numero = {}  # dfd_pk -> proximo numero_item

            for row in rows:
                identificador = row.get("IDENTIFICADOR DA CONTRATACAO", "").strip() or \
                                row.get("IDENTIFICADOR DA CONTRATAÇÃO", "").strip()
                setor_raw = row.get("SETOR REQUISITANTE", "").strip()
                setor = SETOR_REMAP.get(setor_raw, setor_raw)

                if setor not in dfds:
                    erros += 1
                    continue

                dfd = dfds[setor]

                # Idempotencia: usa o identificador original como codigo_pca legado
                codigo_legado = f"LEG-{identificador.replace(' ', '-')}-{exercicio}"
                if ItemPCA.objects.filter(codigo_pca=codigo_legado).exists():
                    ignorados += 1
                    continue

                # Mapeamentos
                classe_raw = row.get("CLASSE", "").strip()
                categoria = lookup(CLASSE_PARA_CATEGORIA, classe_raw, "CLASSE", identificador, warnings)
                if not categoria:
                    categoria = "servico"  # fallback

                tipo_raw = row.get("TIPO DE CONTRATACAO", "").strip() or \
                           row.get("TIPO DE CONTRATAÇÃO", "").strip()
                tipo_demanda = lookup(TIPO_PARA_TIPO_DEMANDA, tipo_raw, "TIPO DE CONTRATACAO", identificador, warnings) or "nova"

                modo_raw = row.get("MODO DE PRESTACAO DO OBJETO", "").strip() or \
                           row.get("MODO DE PRESTAÇAO DO OBJETO", "").strip()
                classificacao = lookup(MODO_PARA_CLASSIFICACAO, modo_raw, "MODO DE PRESTACAO", identificador, warnings) or "eventual"

                modalidade_raw = row.get("MODALIDADE DE CONTRATACAO", "").strip() or \
                                 row.get("MODALIDADE DE CONTRATAÇÃO", "").strip()
                modalidade = lookup(MODALIDADE_PARA_MODALIDADE, modalidade_raw, "MODALIDADE", identificador, warnings) or "pregao_eletronico"

                normativo_raw = row.get("NORMATIVO", "").strip()
                normativo = lookup(NORMATIVO_PARA_NORMATIVO, normativo_raw, "NORMATIVO", identificador, warnings) or "14133_2021"

                uo_raw = row.get("UNIDADE ORCAMENTARIA", "").strip() or \
                         row.get("UNIDADE ORÇAMENTÁRIA", "").strip()
                unidade_orcamentaria = UO_MAP.get(uo_raw, "pgj")

                etapa_raw = row.get("ETAPA DO PROCESSO", "").strip()
                status_key = normalizar(etapa_raw)
                status = next(
                    (v for k, v in ETAPA_PARA_STATUS.items() if normalizar(k) == status_key),
                    "nao_iniciado",
                )
                sobrestado = row.get("SOBRESTADO", "Nao").strip().lower() == "sim"
                if sobrestado:
                    status = "suspenso"

                # Valores numericos
                qtd_raw = row.get("QUANTIDADE ITENS", "1").strip()
                try:
                    qtd = decimal.Decimal(qtd_raw) if qtd_raw else decimal.Decimal("1")
                except decimal.InvalidOperation:
                    qtd = decimal.Decimal("1")

                valor_unit = parse_decimal(row.get("VALOR UNITARIO", "") or row.get("VALOR UNITÁRIO", ""))
                valor_total = parse_decimal(row.get("VALOR ESTIMADO PARA 2026", ""))
                valor_contratado = parse_decimal(row.get("VALOR LICITADO / CONTRATADO", ""))

                # Se valor_unit for zero mas temos total e qtd, calcula
                if valor_unit == 0 and qtd > 0 and valor_total > 0:
                    valor_unit = (valor_total / qtd).quantize(decimal.Decimal("0.01"))

                # Datas
                data_envio = parse_date(
                    row.get("DATA PARA ENVIAR O PGEA PARA CONTRATACAO", "") or
                    row.get("DATA PARA ENVIAR O PGEA PARA CONTRATAÇÃO", "")
                )
                data_termino = parse_date(
                    row.get("TERMINO DO CONTRATO / PREVISAO DE CONTRATACAO", "") or
                    row.get("TÉRMINO DO CONTRATO / PREVISÃO DE CONTRATAÇÃO", "")
                )
                data_conclusao_pretendida = parse_date(
                    row.get("DATA DFD PARA COMPRA", "")
                )
                data_fin_licitacao = parse_date(
                    row.get("DATA DE FINALIZACAO DA LICITACAO", "") or
                    row.get("DATA DE FINALIZAÇÃO DA LICITAÇÃO", "")
                )
                data_conclusao_efetiva = parse_date(
                    row.get("DATA DE CONCLUSAO", "") or
                    row.get("DATA DE CONCLUSÃO", "")
                )

                # Numero do item dentro do DFD
                contadores_numero.setdefault(dfd.pk, 0)
                contadores_numero[dfd.pk] += 1
                numero_item = contadores_numero[dfd.pk]

                # Campos textuais
                descricao = row.get("DESCRICAO DO OBJETO", "").strip() or \
                            row.get("DESCRIÇÃO DO OBJETO", "").strip()
                pdm = row.get("PDM/CATSER", "").strip()
                unidade_forn = row.get("UNIDADE DE FORNECIMENTO", "").strip() or "UN"
                numero_sei = row.get("No SEI / LICITACAO", "").strip() or \
                             row.get("Nº SEI / LICITAÇÃO", "").strip()
                numero_contrato = row.get("NUMERO DO CONTRATO", "").strip() or \
                                  row.get("NÚMERO DO CONTRATO", "").strip()

                observacoes_parts = []
                if numero_contrato and numero_contrato.lower() not in ("nao se aplica", ""):
                    observacoes_parts.append(f"Contrato anterior: {numero_contrato}")
                observacoes_parts.append(f"Importado de: {identificador} (sistema legado pca-mppi)")
                observacoes = " | ".join(observacoes_parts)

                if not dry_run:
                    try:
                        ItemPCA.objects.create(
                            dfd=dfd,
                            numero_item=numero_item,
                            codigo_pca=codigo_legado,
                            categoria=categoria,
                            codigo_catmat_catser=pdm,
                            descricao=descricao or identificador,
                            unidade_fornecimento=unidade_forn,
                            quantidade_estimada=qtd,
                            valor_unitario_estimado=valor_unit,
                            valor_total_estimado=valor_total,
                            valor_empenhado=valor_contratado,
                            tipo_demanda=tipo_demanda,
                            modalidade=modalidade,
                            normativo=normativo,
                            unidade_orcamentaria=unidade_orcamentaria,
                            classificacao_continuidade=classificacao,
                            data_envio_pgea=data_envio,
                            data_vencimento_contrato_anterior=data_termino,
                            data_pretendida_conclusao=data_conclusao_pretendida,
                            data_finalizacao_licitacao=data_fin_licitacao,
                            data_conclusao_efetiva=data_conclusao_efetiva,
                            status=status,
                            observacoes=observacoes,
                        )
                        criados += 1
                    except Exception as exc:
                        erros += 1
                        warnings.append(f"  [{identificador}] ERRO ao criar: {exc}")
                else:
                    criados += 1

            if dry_run:
                transaction.set_rollback(True)

        # ── 6. Relatorio ────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  Itens criados  : {criados}"))
        if ignorados:
            self.stdout.write(self.style.WARNING(f"  Ja existiam    : {ignorados}"))
        if erros:
            self.stdout.write(self.style.ERROR(f"  Erros          : {erros}"))

        if warnings:
            self.stdout.write(self.style.WARNING("\nAvisos:"))
            seen = set()
            for w in warnings:
                if w not in seen:
                    self.stdout.write(w)
                    seen.add(w)

        if dry_run:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] Nada foi gravado."))
        else:
            self.stdout.write(self.style.SUCCESS("\nImportacao concluida."))
