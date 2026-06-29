"""
Management command: vincular_contratos_cnpj
============================================
Vincula Contrato.arp_origem às ARPs do MPPI usando a lógica:

  CRITÉRIO PRINCIPAL
  ──────────────────
  Para cada contrato sem arp_origem:
    1. Busca ARPs cujo fornecedor_cnpj_cpf corresponde a contratado_cnpj_cpf
    2. Filtra ARPs em que a data_assinatura do contrato está dentro do período
       de vigência (data_inicio_vigencia ≤ data_assinatura ≤ data_fim_vigencia)
    3. Se exatamente 1 ARP: vincula (confiança ALTA)
    4. Se múltiplas ARPs: usa similaridade de objeto para escolher a mais
       provável (confiança MÉDIA — reporta para revisão humana)
    5. Se nenhuma ARP: registra como não-vinculado

  NORMALIZAÇÃO DE CNPJ
  ────────────────────
  Remove pontuação (. / -) antes de comparar, para evitar miss por formatação.

  SIMILARIDADE DE OBJETO
  ──────────────────────
  Usa difflib.SequenceMatcher sobre os primeiros 120 chars de cada objeto.
  Threshold mínimo: 0.25 (25% de tokens em comum) para considerar match válido
  quando há múltiplas ARPs candidatas.

Fluxo real identificado (Contrato 30/2025/PGJ):
  ─ ARP 15/2025 (P.E. 90001/2025) — LAÍS G DE SOUSA, CNPJ 39.853.645/0001-02
  ─ Contrato 30/2025/PGJ, assinado 14/04/2025 — mesmo CNPJ, dentro da vigência
  ─ Processo 00510/2025-66 aparece no "Acompanhamento da ARP" SEI como aquisição

Uso:
    python manage.py vincular_contratos_cnpj
    python manage.py vincular_contratos_cnpj --dry-run
    python manage.py vincular_contratos_cnpj --dry-run --relatorio
    python manage.py vincular_contratos_cnpj --min-similaridade 0.3
    python manage.py vincular_contratos_cnpj --incluir-ja-vinculados
"""
import re
from difflib import SequenceMatcher

from django.core.management.base import BaseCommand
from django.db import transaction


def _norm_cnpj(cnpj: str) -> str:
    """Remove toda pontuação e espaços, retorna apenas dígitos."""
    return re.sub(r"\D", "", cnpj or "")


def _similaridade(a: str, b: str) -> float:
    """SequenceMatcher ratio entre os primeiros 120 chars de cada string."""
    return SequenceMatcher(None, (a or "")[:120].lower(), (b or "")[:120].lower()).ratio()


class Command(BaseCommand):
    help = (
        "Vincula Contrato.arp_origem às ARPs do MPPI por CNPJ do fornecedor "
        "+ data de assinatura dentro da vigência da ARP"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra o que seria feito sem persistir nada.",
        )
        parser.add_argument(
            "--relatorio",
            action="store_true",
            help="Exibe lista detalhada de matches e ambiguidades.",
        )
        parser.add_argument(
            "--min-similaridade",
            type=float,
            default=0.25,
            dest="min_sim",
            help="Threshold mínimo de similaridade de objeto para aceitar match ambíguo (padrão: 0.25).",
        )
        parser.add_argument(
            "--incluir-ja-vinculados",
            action="store_true",
            dest="relinkar",
            help="Tenta revisar contratos que já têm arp_origem (útil para correção de vínculos).",
        )
        parser.add_argument(
            "--tolerancia-dias",
            type=int,
            default=0,
            dest="tolerancia_dias",
            help=(
                "Aceita contratos cuja data_assinatura está até N dias ANTES do "
                "início da vigência da ARP (útil para casos onde a ARP e o contrato "
                "foram assinados com poucos dias de diferença e o DB tem a data levemente errada). "
                "Padrão: 0 (sem tolerância)."
            ),
        )
        parser.add_argument(
            "--usar-itens",
            action="store_true",
            dest="usar_itens",
            help=(
                "No relatório de ambíguos, compara o objeto do contrato com as "
                "descrições dos itens de cada ARP candidata (mais preciso que "
                "comparar com o objeto genérico da ARP)."
            ),
        )
        parser.add_argument(
            "--flex-placeholder",
            action="store_true",
            dest="flex_placeholder",
            help=(
                "2ª passagem: contratos com data_assinatura = 1º de janeiro "
                "(placeholder do SIAFE) são reanalisados usando apenas CNPJ + "
                "similaridade de objeto, sem filtro de data. "
                "Requer --min-similaridade ≥ 0.20 para evitar falsos positivos."
            ),
        )

    def handle(self, *args, **options):
        from apps.contratos.models import Contrato
        from apps.srp.models import AtaRegistroPrecos

        dry_run          = options["dry_run"]
        relatorio        = options["relatorio"]
        min_sim          = options["min_sim"]
        relinkar         = options["relinkar"]
        flex_placeholder = options["flex_placeholder"]
        usar_itens       = options["usar_itens"]
        tolerancia_dias  = options["tolerancia_dias"]

        if dry_run:
            self.stdout.write(self.style.WARNING("*** DRY-RUN — nenhuma alteração será salva ***\n"))

        # Regex para detectar caronas no objeto do contrato.
        # Cobre: "adesão à ata", "adesão nº 06/2025 à ata", "adesão ao registro", "carona"
        RE_CARONA = re.compile(
            r"ades[aã]o\b.{0,30}[aà]\s+ata|carona|ades[aã]o\s+ao\s+registro",
            re.IGNORECASE,
        )

        # ── Carrega ARPs indexadas por CNPJ normalizado ────────────────────────
        arps = list(
            AtaRegistroPrecos.objects
            .only("id", "numero_arp", "fornecedor_cnpj_cpf",
                  "data_inicio_vigencia", "data_fim_vigencia", "objeto")
        )

        # Índice: cnpj_digits → [arp, arp, ...]
        indice_cnpj: dict[str, list] = {}
        for arp in arps:
            key = _norm_cnpj(arp.fornecedor_cnpj_cpf)
            if key:
                indice_cnpj.setdefault(key, []).append(arp)

        self.stdout.write(f"ARPs no banco: {len(arps)} (de {len(indice_cnpj)} CNPJs únicos)")

        # ── Carrega itens das ARPs (quando --usar-itens) ──────────────────────
        itens_por_arp: dict[int, list[str]] = {}
        if usar_itens:
            from apps.srp.models import ItemARP
            for item in ItemARP.objects.only("arp_id", "descricao"):
                itens_por_arp.setdefault(item.arp_id, []).append(item.descricao or "")
            self.stdout.write(
                f"Itens carregados: {sum(len(v) for v in itens_por_arp.values())} "
                f"em {len(itens_por_arp)} ARPs\n"
            )

        def _score_combinado(obj_contrato: str, arp) -> float:
            """Retorna max(score_objeto, melhor_score_item)."""
            s_obj = _similaridade(obj_contrato, arp.objeto)
            if not usar_itens or arp.pk not in itens_por_arp:
                return s_obj
            s_item = max((_similaridade(obj_contrato, d) for d in itens_por_arp[arp.pk]), default=0.0)
            return max(s_obj, s_item)

        # ── Carrega contratos ──────────────────────────────────────────────────
        qs = Contrato.objects.only(
            "id", "numero_contrato", "contratado_cnpj_cpf",
            "data_assinatura", "objeto", "arp_origem_id"
        )
        if not relinkar:
            qs = qs.filter(arp_origem__isnull=True, arp_externa_origem__isnull=True)

        contratos = list(qs)
        # Filtra caronas: contrato cujo objeto indica adesão a ARP externa
        caronas_detectadas = [c for c in contratos if RE_CARONA.search(c.objeto or "")]
        if caronas_detectadas:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠ {len(caronas_detectadas)} contrato(s) detectado(s) como carona "
                    f"(\"adesão à ata\" no objeto) — ignorados neste command:\n"
                    + "\n".join(f"  {c.numero_contrato}: {(c.objeto or '')[:80]}" for c in caronas_detectadas)
                    + "\n  → Use o Admin para setar arp_externa_origem nestes contratos.\n"
                )
            )
            ids_carona = {c.pk for c in caronas_detectadas}
            contratos = [c for c in contratos if c.pk not in ids_carona]
        self.stdout.write(f"Contratos a analisar:  {len(contratos)}\n")

        # ── Resultados ────────────────────────────────────────────────────────
        matches_alta   = []   # (contrato, arp)                — 1 ARP candidata
        matches_media  = []   # (contrato, arp, score, rivais)  — melhor dentre vários
        sem_cnpj       = []   # contratos sem CNPJ no banco
        sem_arp        = []   # CNPJ não encontrado em ARP alguma
        sem_vigencia   = []   # CNPJ achado mas data fora de todas as vigências
        ambiguos_sem_match = []  # múltiplas ARPs mas nenhuma atingiu min_sim

        for c in contratos:
            cnpj_key = _norm_cnpj(c.contratado_cnpj_cpf)
            if not cnpj_key:
                sem_cnpj.append(c)
                continue

            candidatas = indice_cnpj.get(cnpj_key, [])
            if not candidatas:
                sem_arp.append(c)
                continue

            # Detecta data placeholder (1º de janeiro = SIAFE sem data real)
            data = c.data_assinatura
            eh_placeholder = (data.month == 1 and data.day == 1)

            if eh_placeholder and flex_placeholder:
                # 2ª passagem: ignora data, usa objeto para desempatar
                dentro = candidatas  # todas as ARPs do CNPJ
            else:
                # Filtra por período de vigência (com tolerância opcional)
                from datetime import timedelta
                delta = timedelta(days=tolerancia_dias)
                dentro = [
                    a for a in candidatas
                    if (a.data_inicio_vigencia - delta) <= data <= a.data_fim_vigencia
                ]

            if not dentro:
                sem_vigencia.append((c, candidatas))
                continue

            if len(dentro) == 1:
                if eh_placeholder and flex_placeholder:
                    # Placeholder: usa score combinado (objeto + itens) — respeita min_sim
                    score = _score_combinado(c.objeto, dentro[0])
                    if score >= min_sim:
                        matches_media.append((c, dentro[0], score, []))
                    else:
                        ambiguos_sem_match.append((c, [(dentro[0], score)]))
                else:
                    matches_alta.append((c, dentro[0]))
            else:
                # Desempate por score combinado (objeto + itens)
                scores = [
                    (a, _score_combinado(c.objeto, a))
                    for a in dentro
                ]
                scores.sort(key=lambda x: -x[1])
                melhor_arp, melhor_score = scores[0]
                rivais = scores[1:]

                if melhor_score >= min_sim:
                    matches_media.append((c, melhor_arp, melhor_score, rivais))
                else:
                    ambiguos_sem_match.append((c, scores))

        # ── Sumário ────────────────────────────────────────────────────────────
        if flex_placeholder:
            self.stdout.write(self.style.WARNING(
                "⚠ Modo --flex-placeholder ativo: datas 01/01/AAAA tratadas sem filtro de vigência\n"
            ))
        if tolerancia_dias:
            self.stdout.write(self.style.WARNING(
                f"⚠ Tolerância de {tolerancia_dias} dia(s) aplicada ao início de vigência das ARPs\n"
            ))
        self.stdout.write(f"══ RESULTADO ════════════════════════════════════════")
        self.stdout.write(f"  Confiança ALTA  (1 ARP candidata):  {len(matches_alta)}")
        self.stdout.write(f"  Confiança MÉDIA (melhor por objeto): {len(matches_media)}")
        self.stdout.write(f"  Sem CNPJ no contrato:               {len(sem_cnpj)}")
        self.stdout.write(f"  CNPJ sem ARP correspondente:        {len(sem_arp)}")
        self.stdout.write(f"  Data fora de todas as vigências:    {len(sem_vigencia)}")
        self.stdout.write(f"  Ambíguos (score < {min_sim:.2f}):           {len(ambiguos_sem_match)}")
        self.stdout.write("")

        if relatorio:
            self._imprimir_relatorio(
                matches_alta, matches_media, sem_vigencia,
                ambiguos_sem_match, sem_arp, min_sim,
                usar_itens=options.get("usar_itens", False),
            )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run concluído. Nenhum dado salvo."))
            return

        # ── Persistência ───────────────────────────────────────────────────────
        ok = 0
        with transaction.atomic():
            for c, arp in matches_alta:
                c.arp_origem = arp
                c.save(update_fields=["arp_origem"])
                ok += 1
            for c, arp, score, _ in matches_media:
                c.arp_origem = arp
                c.save(update_fields=["arp_origem"])
                ok += 1

        self.stdout.write(
            self.style.SUCCESS(f"Concluído: {ok} contrato(s) vinculado(s) às ARPs.")
        )
        if ambiguos_sem_match:
            self.stdout.write(
                self.style.WARNING(
                    f"⚠ {len(ambiguos_sem_match)} contrato(s) com múltiplas ARPs candidatas "
                    f"e score abaixo de {min_sim:.2f} — requerem revisão manual. "
                    f"Use --relatorio para ver detalhes."
                )
            )

    # ── Helpers de relatório ────────────────────────────────────────────────────

    def _imprimir_relatorio(self, alta, media, sem_vig, ambiguos, sem_arp, min_sim, usar_itens=False):
        sep = "─" * 70

        if alta:
            self.stdout.write(f"\n{sep}")
            self.stdout.write("CONFIANÇA ALTA — 1 ARP candidata por CNPJ + data")
            self.stdout.write(sep)
            for c, arp in alta:
                self.stdout.write(
                    f"  {c.numero_contrato:<30} → ARP {arp.numero_arp}"
                    f"  [{arp.data_inicio_vigencia} – {arp.data_fim_vigencia}]"
                )

        if media:
            self.stdout.write(f"\n{sep}")
            self.stdout.write(f"CONFIANÇA MÉDIA — melhor objeto (score ≥ {min_sim:.2f})")
            self.stdout.write(sep)
            for c, arp, score, rivais in media:
                self.stdout.write(
                    f"  {c.numero_contrato:<30} → ARP {arp.numero_arp}  (score={score:.2f})"
                )
                for rival_arp, rival_score in rivais:
                    self.stdout.write(
                        f"    rival: ARP {rival_arp.numero_arp}  (score={rival_score:.2f})"
                    )

        if ambiguos:
            self.stdout.write(f"\n{sep}")
            self.stdout.write(f"AMBÍGUOS — score < {min_sim:.2f} — REVISÃO MANUAL")
            self.stdout.write(sep)
            # Carrega itens das ARPs envolvidas para comparação semântica mais rica
            from apps.srp.models import ItemARP
            arp_pks_envolvidas = {a.pk for _, scores in ambiguos for a, _ in scores}
            itens_por_arp: dict[int, list[str]] = {}
            if usar_itens:
                for item in ItemARP.objects.filter(arp_id__in=arp_pks_envolvidas).only("arp_id", "descricao"):
                    itens_por_arp.setdefault(item.arp_id, []).append(item.descricao or "")

            for c, scores in ambiguos:
                obj_contrato = (c.objeto or "")
                self.stdout.write(f"\n  Contrato: {c.numero_contrato}")
                self.stdout.write(f"  Objeto:   {obj_contrato[:100]}")
                for arp_c, sc in scores:
                    # Score extra: melhor similaridade com qualquer item da ARP
                    score_item = 0.0
                    melhor_item = ""
                    if usar_itens and arp_c.pk in itens_por_arp:
                        for desc in itens_por_arp[arp_c.pk]:
                            s = _similaridade(obj_contrato, desc)
                            if s > score_item:
                                score_item = s
                                melhor_item = desc[:60]
                    score_str = f"obj={sc:.2f}"
                    if usar_itens:
                        score_str += f"  item={score_item:.2f} ({melhor_item})"
                    self.stdout.write(
                        f"    ARP {arp_c.numero_arp:<15} {score_str}"
                        f"  [{arp_c.data_inicio_vigencia} – {arp_c.data_fim_vigencia}]"
                    )

        if sem_vig:
            self.stdout.write(f"\n{sep}")
            self.stdout.write("DATA DE ASSINATURA FORA DAS VIGÊNCIAS (CNPJ encontrado)")
            self.stdout.write(sep)
            for c, candidatas in sem_vig[:20]:
                self.stdout.write(
                    f"  {c.numero_contrato:<30}  assinatura={c.data_assinatura}"
                )
                for a in candidatas:
                    self.stdout.write(
                        f"    ARP {a.numero_arp}  [{a.data_inicio_vigencia} – {a.data_fim_vigencia}]"
                    )

        if sem_arp:
            self.stdout.write(f"\n{sep}")
            self.stdout.write("CNPJ SEM ARP NO BANCO (primeiros 20)")
            self.stdout.write(sep)
            for c in sem_arp[:20]:
                self.stdout.write(
                    f"  {c.numero_contrato:<30}  CNPJ={c.contratado_cnpj_cpf}"
                    f"  {(c.objeto or '')[:60]}"
                )
