import os
import re
import sys
import openpyxl
from django.core.management.base import BaseCommand
from apps.contratos.models import Contrato
from apps.srp.models import AtaRegistroPrecos


class Command(BaseCommand):
    help = 'Analisa a planilha Painel de Contratos e vincula automaticamente os contratos com as ARPs do sistema por CNPJ e número.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--arquivo',
            type=str,
            default=r'C:\Dev\Base\PAINEL DE CONTRATOS 2026 (atualizada).xlsx',
            help='Caminho completo para o arquivo Excel do Painel de Contratos.'
        )
        parser.add_argument(
            '--simular',
            action='store_true',
            help='Executa em modo simulação (não altera o banco de dados).'
        )

    def handle(self, *args, **options):
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        arquivo = options['arquivo']
        simular = options['simular']

        if not os.path.exists(arquivo):
            self.stdout.write(self.style.ERROR(f"Arquivo não encontrado: {arquivo}"))
            return

        self.stdout.write(f"Lendo planilha: {arquivo}...")
        wb = openpyxl.load_workbook(arquivo, data_only=True)
        ws = wb['PAINEL']

        # Mapear ARPs por CNPJ limpo
        arps_por_cnpj = {}
        for arp in AtaRegistroPrecos.objects.all():
            cnpj = re.sub(r'\D', '', str(arp.fornecedor_cnpj_cpf or ''))
            if cnpj:
                arps_por_cnpj.setdefault(cnpj, []).append(arp)

        # Buscar contratos no DB sem ARP vinculada
        contratos_sem_arp = list(Contrato.objects.filter(arp_origem__isnull=True))
        self.stdout.write(f"Contratos no banco sem ARP vinculada: {len(contratos_sem_arp)}")

        vinculados = 0
        linhas = list(ws.iter_rows(values_only=True))
        
        for idx, r in enumerate(linhas[1:], start=2):
            numero_excel = str(r[1] or '').strip()
            ano_excel = str(r[2] or '').strip()
            cnpj_excel = re.sub(r'\D', '', str(r[9] or ''))
            razao_excel = str(r[10] or '').strip()

            if not cnpj_excel or cnpj_excel not in arps_por_cnpj:
                continue

            arps_candidatas = arps_por_cnpj[cnpj_excel]
            num_formatado = f"{numero_excel}/{ano_excel}" if numero_excel and ano_excel else numero_excel

            for contrato in contratos_sem_arp:
                if contrato.arp_origem is not None:
                    continue  # já foi vinculado nesta execução

                c_cnpj = re.sub(r'\D', '', str(contrato.contratado_cnpj_cpf or ''))
                
                # Critério de match: CNPJ igual E (número compatível OU fornecedor único para a ARP)
                match_numero = (
                    (num_formatado and num_formatado in contrato.numero_contrato) or
                    (numero_excel and numero_excel in contrato.numero_contrato and ano_excel in contrato.numero_contrato)
                )

                if match_numero or (c_cnpj == cnpj_excel and len(arps_candidatas) == 1):
                    arp_escolhida = arps_candidatas[0]
                    
                    msg = (
                        f"[Linha {idx}] Contrato DB '{contrato.numero_contrato}' (R$ {contrato.valor_inicial}) "
                        f"-> ARP '{arp_escolhida.numero_arp}' ({razao_excel[:30]})"
                    )
                    msg = msg.encode('cp1252', errors='replace').decode('cp1252')
                    
                    if simular:
                        self.stdout.write(self.style.WARNING(f"[SIMULAÇÃO] {msg}"))
                    else:
                        contrato.arp_origem = arp_escolhida
                        contrato.save(update_fields=['arp_origem'])
                        self.stdout.write(self.style.SUCCESS(f"[VINCULADO] {msg}"))
                    
                    vinculados += 1
                    break

        if simular:
            self.stdout.write(self.style.SUCCESS(f"\n[SIMULAÇÃO CONCLUÍDA] {vinculados} contratos seriam vinculados automaticamente."))
        else:
            self.stdout.write(self.style.SUCCESS(f"\n[CONCLUÍDO] {vinculados} contratos vinculados com sucesso!"))
