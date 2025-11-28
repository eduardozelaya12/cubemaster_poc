"""
Módulo responsável pela transformação de respostas JSON da API CubeMaster em Excel.

Este módulo implementa a lógica de negócio para:
1. Extrair dados do loadSummary (planilha "summary")
2. Extrair dados de cada container e seu manifest (planilhas por container)
3. Gerar arquivo Excel estruturado com múltiplas abas
"""

import pandas as pd
import re
import logging
from pathlib import Path
from typing import Dict, Any, Tuple

from .config import get_settings

logger = logging.getLogger(__name__)

# Carregar configurações
settings = get_settings()


def sanitize_sheet_name(name: str) -> str:
    """
    Sanitiza o nome da planilha para remover caracteres inválidos do Excel.
    
    Args:
        name: Nome original da planilha
        
    Returns:
        Nome sanitizado (máximo 31 caracteres, sem caracteres especiais)
    """
    # Remove caracteres inválidos para nomes de planilhas Excel: \ / * ? : [ ]
    name = re.sub(r'[\\/*?:\[\]]', '_', name)
    
    # Limita a 31 caracteres (limite do Excel para nomes de planilhas)
    if len(name) > 31:
        name = name[:31]
    
    return name


def criar_planilha_summary(data: Dict[str, Any]) -> pd.DataFrame:
    """
    Cria a planilha de resumo geral a partir do loadSummary da resposta.
    
    Esta planilha contém métricas gerais de todos os containers combinados.
    
    Args:
        data: Dicionário com a resposta completa da API CubeMaster
        
    Returns:
        DataFrame com uma linha contendo as métricas do summary
    """
    load_summary = data.get('loadSummary', {})
    
    # Campos esperados na planilha summary (conforme modelo fornecido)
    summary_data = {
        'cargoesLoaded': [load_summary.get('cargoesLoaded', 0)],
        'piecesLoaded': [load_summary.get('piecesLoaded', 0)],
        'cargoesLeft': [load_summary.get('cargoesLeft', 0)],
        'piecesLeft': [load_summary.get('piecesLeft', 0)],
        'unitloadsLoaded': [load_summary.get('unitloadsLoaded', 0)],
        'volumeLoaded': [load_summary.get('volumeLoaded', 0)],
        'weightLoaded': [load_summary.get('weightLoaded', 0)],
        'priceLoaded': [load_summary.get('priceLoaded', 0)],
        'containersLoaded': [load_summary.get('containersLoaded', 0)],
        'containersLeft': [load_summary.get('containersLeft', 0)]
    }
    
    return pd.DataFrame(summary_data)


def criar_planilha_container(container: Dict[str, Any]) -> pd.DataFrame:
    """
    Cria a planilha detalhada de um container a partir do seu manifest.
    
    Cada linha representa um item de carga (cargo) dentro do container.
    
    Args:
        container: Dicionário com os dados de um container específico
        
    Returns:
        DataFrame com os dados expandidos do manifest
    """
    manifest = container.get('manifest', [])
    
    # Lista para armazenar cada linha (item de carga)
    rows = []
    
    for item in manifest:
        cargo = item.get('cargo', {})
        
        # Estrutura conforme modelo do Excel fornecido
        row = {
            'sequence': item.get('sequence', ''),
            'cargoName': cargo.get('name', ''),
            'qty': cargo.get('qty', 0),
            'pieces': item.get('piecesLoaded', 0),
            'length': cargo.get('length', 0),
            'width': cargo.get('width', 0),
            'height': cargo.get('height', 0),
            'weight': cargo.get('weight', 0)
        }
        
        rows.append(row)
    
    return pd.DataFrame(rows)


def transformar_json_para_excel(
    response_data: Dict[str, Any], 
    excel_path: Path
) -> Tuple[Path, Dict[str, Any]]:
    """
    Transforma a resposta JSON da API CubeMaster em arquivo Excel estruturado.
    
    Estrutura do Excel gerado:
    - Planilha "summary": Métricas gerais do loadSummary
    - Planilhas por container: Uma planilha para cada container com seus itens de carga
    
    Args:
        response_data: Dicionário com a resposta completa da API CubeMaster
        excel_path: Caminho completo onde o arquivo Excel será salvo
        
    Returns:
        Tupla com (caminho do arquivo, estatísticas do processamento)
        
    Raises:
        Exception: Se houver erro na criação do Excel
    """
    logger.info("📊 Iniciando transformação JSON → Excel")
    
    stats = {
        'total_sheets': 0,
        'summary_created': False,
        'containers_processed': 0,
        'total_cargo_items': 0
    }
    
    try:
        # Criar o Excel Writer usando openpyxl (suporta múltiplas abas)
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            
            # ========== PLANILHA 1: SUMMARY ==========
            logger.info("   → Criando planilha 'summary'")
            df_summary = criar_planilha_summary(response_data)
            df_summary.to_excel(writer, sheet_name='summary', index=False)
            stats['summary_created'] = True
            stats['total_sheets'] += 1
            
            # ========== PLANILHAS 2+: CONTAINERS ==========
            filled_containers = response_data.get('filledContainers', [])
            logger.info(f"   → Processando {len(filled_containers)} container(s)")
            
            for container in filled_containers:
                sequence = container.get('sequence', 0)
                name = container.get('name', f'Container_{sequence}')
                
                # Criar nome da planilha no formato: container_X_Nome
                sheet_name = f"container_{sequence}_{name}"
                sheet_name = sanitize_sheet_name(sheet_name)
                
                logger.info(f"      • Criando planilha: {sheet_name}")
                
                # Criar DataFrame com os dados do manifest
                df_container = criar_planilha_container(container)
                
                # Escrever no Excel
                df_container.to_excel(writer, sheet_name=sheet_name, index=False)
                
                stats['containers_processed'] += 1
                stats['total_cargo_items'] += len(df_container)
                stats['total_sheets'] += 1
        
        logger.info(f"✅ Excel criado com sucesso: {excel_path}")
        logger.info(f"   📋 Total de planilhas: {stats['total_sheets']}")
        logger.info(f"   📦 Containers: {stats['containers_processed']}")
        logger.info(f"   📊 Itens de carga: {stats['total_cargo_items']}")
        
        return excel_path, stats
        
    except Exception as e:
        logger.error(f"❌ Erro ao criar Excel: {str(e)}")
        raise


def save_to_excel_procesado(
    response_data: Dict[str, Any],
    request_id: str,
    timestamp: str
) -> Tuple[Path, Dict[str, Any]]:
    """
    Salva a resposta da API como arquivo Excel no diretório csv_procesado.
    
    Args:
        response_data: Resposta da API CubeMaster
        request_id: ID único da requisição
        timestamp: Timestamp da requisição
        
    Returns:
        Tupla com (caminho do arquivo, estatísticas)
    """
    # Excel salvo no mesmo diretório dos CSVs
    excel_dir = settings.csv_procesado_dir
    excel_dir.mkdir(parents=True, exist_ok=True)
    
    # Gerar nome do arquivo
    filename = f"result_{timestamp}_{request_id}.xlsx"
    excel_path = excel_dir / filename
    
    # Transformar e salvar
    return transformar_json_para_excel(response_data, excel_path)


def save_to_excel_with_name(
    response_data: Dict[str, Any],
    base_filename: str
) -> Tuple[Path, Dict[str, Any]]:
    """
    Salva a resposta da API como Excel usando um nome específico.
    
    Usado para manter o mesmo nome do arquivo JSON original.
    
    Args:
        response_data: Resposta da API CubeMaster
        base_filename: Nome base do arquivo (sem extensão)
        
    Returns:
        Tupla com (caminho do arquivo, estatísticas)
    """
    excel_dir = settings.csv_procesado_dir
    excel_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{base_filename}.xlsx"
    excel_path = excel_dir / filename
    
    return transformar_json_para_excel(response_data, excel_path)

