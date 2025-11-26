import httpx
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class CubeMasterClient:
    def __init__(self, api_url: str, token_id: str):
        self.api_url = api_url
        self.token_id = token_id
        logger.info(f"🔧 CubeMaster Client inicializado: {api_url}")
    
    async def optimize_load(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Chama a API do CubeMaster e retorna resultado
        """
        headers = {
            "Content-Type": "application/json",
            "TokenID": self.token_id
        }
        
        logger.info(f"📤 Enviando requisição para CubeMaster API...")
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    self.api_url,
                    json=payload,
                    headers=headers
                )
                
                response.raise_for_status()
                result = response.json()
                logger.info(f"✅ Resposta recebida com sucesso!")
                return result
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Erro HTTP: {e.response.status_code}")
            logger.error(f"Resposta: {e.response.text}")
            # Tentar extrair mensagem detalhada da API CubeMaster
            try:
                error_detail = e.response.json()
                error_message = error_detail.get("message", e.response.text)
                raise Exception(f"Erro {e.response.status_code} da API CubeMaster: {error_message}")
            except:
                raise Exception(f"Erro {e.response.status_code} da API CubeMaster: {e.response.text}")
        except Exception as e:
            logger.error(f"❌ Erro ao chamar API: {str(e)}")
            raise
    
    async def test_connection(self) -> bool:
        """Testa conexão com a API"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.api_url.replace('/loads', ''))
                return response.status_code < 500
        except:
            return False