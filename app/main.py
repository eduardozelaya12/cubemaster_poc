from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging
import json
import httpx
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .cubemaster_client import CubeMasterClient
from .config import get_settings
from .excel_transformer import save_to_excel_procesado, save_to_excel_with_name

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Carregar configurações
settings = get_settings()

# Criar aplicação FastAPI
app = FastAPI(
    title=settings.app_name,
    description="API PoC CubeMaster",
    version=settings.app_version
)

# CORS - permitir requisições de qualquer origem (ajuste em produção)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inicializar cliente CubeMaster
cubemaster = CubeMasterClient(
    api_url=settings.cubemaster_api_url,
    token_id=settings.cubemaster_token_id
)

@app.on_event("startup")
async def startup_event():
    """Evento executado no startup da aplicação"""
    logger.info(f"Iniciando {settings.app_name} v{settings.app_version}")
    logger.info(f"Ambiente: {settings.environment}")
    logger.info(f"CubeMaster API: {settings.cubemaster_api_url}")
    
    # Garantir que os diretórios existam (especialmente importante no Docker)
    settings.ensure_directories_exist()
    logger.info(f"Diretórios criados em: {settings.response_output_dir}")

@app.get("/")
async def root():
    """Endpoint raiz para verificar se a API está funcionando"""
    return {
        "message": f"{settings.app_name} - HU 3873",
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health",
            "upload_csv": "/upload-csv",
            "optimize_load": "/optimize-load",
            "process_pending_files": "/process-pending-files"
        }
    }

@app.get("/health")
async def health_check():
    """Verifica saúde da aplicação e conexão com CubeMaster"""
    cubemaster_status = await cubemaster.test_connection()
    
    return {
        "status": "healthy" if cubemaster_status else "degraded",
        "api": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "cubemaster_api": "connected" if cubemaster_status else "disconnected",
        "timestamp": datetime.now().isoformat()
    }



@app.post("/optimize-load")
async def optimize_container_load(payload: Dict[str, Any] = Body(...)):
    """
    Endpoint principal: recebe payload JSON, processa via CubeMaster,
    e salva nos diretórios apropriados seguindo o fluxo completo.
    """
    # Gerar ID único para rastreamento
    request_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    logger.info(f"🆔 Nova requisição - ID: {request_id}, Timestamp: {timestamp}")
    
    # Passo 1: Salvar em json_pendiente
    try:
        pendiente_path = save_to_json_pendiente(payload, request_id, timestamp)
    except Exception as e:
        logger.error(f"Erro ao salvar em json_pendiente: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar payload: {str(e)}")
    
    # Passo 2: Processar via API CubeMaster
    try:
        logger.info(f"Processando via CubeMaster API...")
        result = await cubemaster.optimize_load(payload)
        logger.info(f"Otimização concluída com sucesso")
        
    except httpx.HTTPStatusError as e:
        error_msg = f"Erro {e.response.status_code} da API CubeMaster"
        save_error_log(request_id, timestamp, error_msg)
        logger.error(f"❌ {error_msg}")
        
        try:
            error_detail = e.response.json()
            error_message = error_detail.get("message", e.response.text)
        except:
            error_message = e.response.text
            
        status_code = e.response.status_code if e.response.status_code < 500 else 502
        raise HTTPException(
            status_code=status_code,
            detail={
                "error": error_msg,
                "message": error_message,
                "request_id": request_id,
                "timestamp": timestamp
            }
        )
    
    except Exception as e:
        error_msg = f"Erro no processamento: {str(e)}"
        save_error_log(request_id, timestamp, error_msg)
        logger.error(f"❌ {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)
    
    # Passo 3: Mover para json_procesado
    try:
        procesado_path = move_to_json_procesado(pendiente_path, request_id, timestamp)
    except Exception as e:
        logger.error(f"Erro ao mover para json_procesado: {str(e)}")
        procesado_path = None
    
    # Passo 4: Gerar Excel Estruturado
    try:
        logger.info(f"Gerando Excel estruturado...")
        excel_path, excel_stats = save_to_excel_procesado(result, request_id, timestamp)
        logger.info(f"Excel gerado: {excel_stats['total_sheets']} planilhas, {excel_stats['total_cargo_items']} itens")
    except Exception as e:
        logger.error(f"Erro ao gerar Excel: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao gerar Excel: {str(e)}")
    
    # Retornar resposta de sucesso
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "request_id": request_id,
            "timestamp": timestamp,
            "files": {
                "json_procesado": str(procesado_path) if procesado_path else None,
                "excel_file": str(excel_path)
            },
            "excel_stats": excel_stats,
            "processed_at": datetime.now().isoformat()
        }
    )


@app.get("/process-pending-files")
async def process_pending_files():
    """
    Endpoint para processar arquivos JSON depositados manualmente na pasta json_pendiente.
    
    Comportamento:
    1. Varre todos os arquivos .json em json_pendiente/
    2. Para cada arquivo encontrado:
       - Lê o conteúdo como payload
       - Envia para API CubeMaster
       - Move o JSON para json_procesado/ (mantendo o nome original)
       - Salva o CSV em csv_procesado/ (mesmo nome base + .csv)
    
    Retorna estatísticas do processamento.
    """
    logger.info("Iniciando processamento de arquivos pendentes...")
    
    pendiente_dir = settings.json_pendiente_dir
    pendiente_dir.mkdir(parents=True, exist_ok=True)
    
    # Buscar todos os arquivos .json na pasta
    json_files = list(pendiente_dir.glob("*.json"))
    
    if not json_files:
        logger.info("Nenhum arquivo JSON encontrado em json_pendiente/")
        return JSONResponse(
            status_code=200,
            content={
                "status": "no_files",
                "message": "Nenhum arquivo pendente para processar",
                "total_files": 0,
                "processed": 0,
                "failed": 0
            }
        )
    
    logger.info(f"Encontrados {len(json_files)} arquivo(s) para processar")
    
    results = {
        "total_files": len(json_files),
        "processed": 0,
        "failed": 0,
        "details": []
    }
    
    for json_file in json_files:
        file_name = json_file.name
        base_name = json_file.stem  # Nome sem extensão
        
        logger.info(f"Processando arquivo: {file_name}")
        
        try:
            # Ler o conteúdo do arquivo JSON
            payload = json.loads(json_file.read_text(encoding="utf-8"))
            logger.info(f"Arquivo {file_name} lido com sucesso")
            
            # Processar via API CubeMaster
            logger.info(f"Enviando para CubeMaster API: {file_name}")
            result = await cubemaster.optimize_load(payload)
            logger.info(f"Resposta recebida da API para: {file_name}")
            
            # Mover o JSON para json_procesado (mantendo o nome original)
            procesado_dir = settings.json_procesado_dir
            procesado_dir.mkdir(parents=True, exist_ok=True)
            procesado_path = procesado_dir / file_name
            
            procesado_path.write_text(json_file.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info(f"JSON movido para json_procesado: {file_name}")
            
            # Gerar Excel com mesmo nome do JSON
            logger.info(f"Gerando Excel estruturado: {file_name}")
            excel_path, excel_stats = save_to_excel_with_name(result, base_name)
            logger.info(f"Excel salvo: {base_name}.xlsx - {excel_stats['total_sheets']} planilhas")
            
            # Remover o arquivo original de json_pendiente após sucesso
            json_file.unlink()
            logger.info(f"Arquivo removido de json_pendiente: {file_name}")
            
            results["processed"] += 1
            results["details"].append({
                "file": file_name,
                "status": "success",
                "json_procesado": str(procesado_path),
                "excel_file": str(excel_path),
                "excel_stats": excel_stats
            })
            
        except httpx.HTTPStatusError as e:
            error_msg = f"Erro {e.response.status_code} da API CubeMaster"
            logger.error(f"❌ Erro ao processar {file_name}: {error_msg}")
            
            results["failed"] += 1
            results["details"].append({
                "file": file_name,
                "status": "failed",
                "error": error_msg,
                "details": str(e)
            })
            
        except Exception as e:
            error_msg = f"Erro no processamento: {str(e)}"
            logger.error(f"Erro ao processar {file_name}: {error_msg}")
            
            results["failed"] += 1
            results["details"].append({
                "file": file_name,
                "status": "failed",
                "error": error_msg
            })
    
    logger.info(f"Processamento concluído: {results['processed']} sucesso, {results['failed']} falhas")
    
    return JSONResponse(
        status_code=200,
        content={
            "status": "completed",
            "message": f"Processamento concluído: {results['processed']} arquivo(s) processado(s), {results['failed']} falha(s)",
            **results,
            "processed_at": datetime.now().isoformat()
        }
    )



# ==================== FUNÇÕES DE GERENCIAMENTO DE ARQUIVOS ====================

def save_to_json_pendiente(payload: Dict[str, Any], request_id: str, timestamp: str) -> Path:
    """Salva payload na pasta json_pendiente"""
    pendiente_dir = settings.json_pendiente_dir
    pendiente_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"request_{timestamp}_{request_id}.json"
    file_path = pendiente_dir / filename
    
    payload_with_metadata = {
        "request_id": request_id,
        "timestamp": timestamp,
        "received_at": datetime.now().isoformat(),
        "status": "pending",
        "payload": payload
    }
    
    file_path.write_text(json.dumps(payload_with_metadata, indent=2), encoding="utf-8")
    logger.info(f"✅ Payload salvo em json_pendiente: {file_path}")
    return file_path


def move_to_json_procesado(pendiente_path: Path, request_id: str, timestamp: str) -> Path:
    """Move arquivo de json_pendiente para json_procesado"""
    procesado_dir = settings.json_procesado_dir
    procesado_dir.mkdir(parents=True, exist_ok=True)
    
    # Ler arquivo original
    payload_data = json.loads(pendiente_path.read_text(encoding="utf-8"))
    
    # Atualizar metadados
    payload_data["status"] = "processed"
    payload_data["processed_at"] = datetime.now().isoformat()
    
    # Salvar em json_procesado
    filename = f"processed_{timestamp}_{request_id}.json"
    procesado_path = procesado_dir / filename
    procesado_path.write_text(json.dumps(payload_data, indent=2), encoding="utf-8")
    
    # Remover de json_pendiente
    pendiente_path.unlink()
    
    logger.info(f"✅ Payload movido para json_procesado: {procesado_path}")
    return procesado_path


def save_error_log(request_id: str, timestamp: str, error_message: str) -> None:
    """Salva log de erro para requests que falharam"""
    error_log_dir = settings.json_pendiente_dir
    error_log_path = error_log_dir / f"error_{timestamp}_{request_id}.log"
    
    error_data = {
        "request_id": request_id,
        "timestamp": timestamp,
        "error_at": datetime.now().isoformat(),
        "error_message": error_message
    }
    
    error_log_path.write_text(json.dumps(error_data, indent=2), encoding="utf-8")
    logger.error(f"❌ Erro salvo: {error_log_path}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app", 
        host=settings.host, 
        port=settings.port, 
        reload=True
    )

