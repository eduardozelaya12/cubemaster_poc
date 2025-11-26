from fastapi import FastAPI, File, UploadFile, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
import io
import logging
import json
import httpx
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .cubemaster_client import CubeMasterClient
from .config import get_settings

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
    request_id = str(uuid.uuid4())[:8]  # Usar primeiros 8 caracteres
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
        logger.info(f"⚙️ Processando via CubeMaster API...")
        result = await cubemaster.optimize_load(payload)
        logger.info(f"✅ Otimização concluída com sucesso")
        
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
    
    # Passo 4: Converter para CSV
    try:
        logger.info(f"📊 Convertendo resposta para CSV...")
        csv_content, row_count = convert_cubemaster_response_to_csv(result)
    except Exception as e:
        logger.error(f"Erro na conversão para CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro na conversão CSV: {str(e)}")
    
    # Passo 5: Salvar CSV em csv_procesado
    try:
        csv_path = save_to_csv_procesado(csv_content, request_id, timestamp)
    except Exception as e:
        logger.error(f"Erro ao salvar CSV: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar CSV: {str(e)}")
    
    # Retornar resposta de sucesso
    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "request_id": request_id,
            "timestamp": timestamp,
            "files": {
                "json_procesado": str(procesado_path) if procesado_path else None,
                "csv_file": str(csv_path)
            },
            "csv_rows": row_count,
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
    logger.info("🔍 Iniciando processamento de arquivos pendentes...")
    
    pendiente_dir = Path("app/response_data/json_pendiente")
    pendiente_dir.mkdir(parents=True, exist_ok=True)
    
    # Buscar todos os arquivos .json na pasta
    json_files = list(pendiente_dir.glob("*.json"))
    
    if not json_files:
        logger.info("ℹ️ Nenhum arquivo JSON encontrado em json_pendiente/")
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
    
    logger.info(f"📁 Encontrados {len(json_files)} arquivo(s) para processar")
    
    results = {
        "total_files": len(json_files),
        "processed": 0,
        "failed": 0,
        "details": []
    }
    
    for json_file in json_files:
        file_name = json_file.name
        base_name = json_file.stem  # Nome sem extensão
        
        logger.info(f"📄 Processando arquivo: {file_name}")
        
        try:
            # Ler o conteúdo do arquivo JSON
            payload = json.loads(json_file.read_text(encoding="utf-8"))
            logger.info(f"✅ Arquivo {file_name} lido com sucesso")
            
            # Processar via API CubeMaster
            logger.info(f"⚙️ Enviando para CubeMaster API: {file_name}")
            result = await cubemaster.optimize_load(payload)
            logger.info(f"✅ Resposta recebida da API para: {file_name}")
            
            # Mover o JSON para json_procesado (mantendo o nome original)
            procesado_dir = Path("app/response_data/json_procesado")
            procesado_dir.mkdir(parents=True, exist_ok=True)
            procesado_path = procesado_dir / file_name
            
            # Copiar (ao invés de mover) para manter se der erro no CSV
            procesado_path.write_text(json_file.read_text(encoding="utf-8"), encoding="utf-8")
            logger.info(f"✅ JSON movido para json_procesado: {file_name}")
            
            # Converter resposta para CSV
            logger.info(f"📊 Convertendo resposta para CSV: {file_name}")
            csv_content, row_count = convert_cubemaster_response_to_csv(result)
            
            # Salvar CSV com o mesmo nome base
            csv_dir = Path("app/response_data/csv_procesado")
            csv_dir.mkdir(parents=True, exist_ok=True)
            csv_path = csv_dir / f"{base_name}.csv"
            csv_path.write_text(csv_content, encoding="utf-8")
            logger.info(f"✅ CSV salvo em csv_procesado: {base_name}.csv")
            
            # Remover o arquivo original de json_pendiente apenas após sucesso total
            json_file.unlink()
            logger.info(f"✅ Arquivo removido de json_pendiente: {file_name}")
            
            results["processed"] += 1
            results["details"].append({
                "file": file_name,
                "status": "success",
                "json_procesado": str(procesado_path),
                "csv_file": str(csv_path),
                "csv_rows": row_count
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
            logger.error(f"❌ Erro ao processar {file_name}: {error_msg}")
            
            results["failed"] += 1
            results["details"].append({
                "file": file_name,
                "status": "failed",
                "error": error_msg
            })
    
    logger.info(f"🎯 Processamento concluído: {results['processed']} sucesso, {results['failed']} falhas")
    
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
    pendiente_dir = Path("app/response_data/json_pendiente")
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
    procesado_dir = Path("app/response_data/json_procesado")
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


def save_to_csv_procesado(csv_content: str, request_id: str, timestamp: str) -> Path:
    """Salva CSV na pasta csv_procesado"""
    csv_dir = Path("app/response_data/csv_procesado")
    csv_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"result_{timestamp}_{request_id}.csv"
    file_path = csv_dir / filename
    
    file_path.write_text(csv_content, encoding="utf-8")
    logger.info(f"✅ CSV salvo em csv_procesado: {file_path}")
    return file_path


def save_error_log(request_id: str, timestamp: str, error_message: str) -> None:
    """Salva log de erro para requests que falharam"""
    error_log_dir = Path("app/response_data/json_pendiente")
    error_log_path = error_log_dir / f"error_{timestamp}_{request_id}.log"
    
    error_data = {
        "request_id": request_id,
        "timestamp": timestamp,
        "error_at": datetime.now().isoformat(),
        "error_message": error_message
    }
    
    error_log_path.write_text(json.dumps(error_data, indent=2), encoding="utf-8")
    logger.error(f"❌ Erro salvo: {error_log_path}")


def convert_cubemaster_response_to_csv(response_data: Any) -> Tuple[str, int]:
    """
    Converte a resposta da API CubeMaster (JSON) em um CSV legível.
    Identifica automaticamente listas de registros dentro da resposta e as transforma em linhas.
    """
    df = _response_to_dataframe(response_data)
    
    if df.empty:
        df = pd.DataFrame([{"message": "CubeMaster response was empty"}])
    
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)
    return csv_buffer.getvalue(), len(df.index)


def _response_to_dataframe(response_data: Any) -> pd.DataFrame:
    """
    Transforma a resposta arbitrária do CubeMaster em DataFrame.
    """
    if isinstance(response_data, list):
        if not response_data:
            return pd.DataFrame()
        if all(isinstance(item, dict) for item in response_data):
            df = pd.json_normalize(response_data, sep='.')
        else:
            df = pd.DataFrame({"value": response_data})
    elif isinstance(response_data, dict):
        candidate_keys: List[str] = [
            key for key, value in response_data.items()
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value)
        ]
        
        if candidate_keys:
            frames: List[pd.DataFrame] = []
            context = {k: v for k, v in response_data.items() if k not in candidate_keys}
            context_flat = pd.json_normalize([context], sep='.') if context else None
            
            for key in candidate_keys:
                records = response_data.get(key, [])
                if not records:
                    continue
                df_key = pd.json_normalize(records, sep='.')
                df_key.columns = [f"{key}.{col}" for col in df_key.columns]
                
                if context_flat is not None:
                    for column in context_flat.columns:
                        df_key[column] = context_flat.iloc[0][column]
                
                frames.append(df_key)
            
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        else:
            df = pd.json_normalize([response_data], sep='.')
    else:
        df = pd.DataFrame([{"value": response_data}])
    
    if df.empty:
        return df
    
    def _serialize_cell(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value)
            except Exception:
                return str(value)
        return value
    
    for column in df.columns:
        df[column] = df[column].apply(_serialize_cell)
    
    return df

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app", 
        host=settings.host, 
        port=settings.port, 
        reload=True
    )
