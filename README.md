# 📊 CubeMaster POC - Estrutura Final

## Visão Geral

API para processar requisições de cubicagem via CubeMaster, gerando arquivo Excel estruturado com múltiplas planilhas.

---

## 📁 Estrutura de Diretórios

```
app/response_data/                  (Volume Docker: /mnt/psappt1/AJ_LOGISTICA_TST/)
├── json_pendiente/                 ← Arquivos JSON para processar
├── json_procesado/                 ← JSONs processados (histórico)
└── csv_procesado/                  ← Arquivos Excel gerados
    └── nome_arquivo.xlsx           (mesmo nome do JSON original)
```

---

## 🔄 Fluxo de Processamento

```
1. JSON depositado em json_pendiente/
   ↓
2. Endpoint /process-pending-files processa via API
   ↓
3. JSON movido para json_procesado/
   ↓
4. Excel gerado em csv_procesado/
   ↓
5. JSON removido de json_pendiente/
```

---

## 📊 Estrutura do Excel Gerado

Cada arquivo `.xlsx` contém:

### Planilha 1: `summary`
- Métricas gerais (cargoesLoaded, piecesLoaded, volumeLoaded, etc.)

### Planilhas 2+: `container_X_Nome`
- Detalhes de cada container
- Colunas: sequence, cargoName, qty, pieces, length, width, height, weight

---

## 🚀 Endpoints

### `GET /process-pending-files`
Processa todos os arquivos `.json` em `json_pendiente/`

**Resposta:**
```json
{
  "status": "completed",
  "total_files": 1,
  "processed": 1,
  "details": [
    {
      "file": "pedido_007.json",
      "json_procesado": ".../json_procesado/pedido_007.json",
      "excel_file": ".../csv_procesado/pedido_007.xlsx",
      "excel_stats": {
        "total_sheets": 4,
        "containers_processed": 3,
        "total_cargo_items": 25
      }
    }
  ]
}
```

### `POST /optimize-load`
Recebe payload JSON inline e processa

---

## 🐳 Docker

### docker-compose.yml
```yaml
volumes:
  - /mnt/psappt1/AJ_LOGISTICA_TST:/code/app/response_data
```

Todos os arquivos salvos em `/code/app/response_data/` no container são persistidos em `/mnt/psappt1/AJ_LOGISTICA_TST/` no servidor.

---

## ⚙️ Configuração

### .env
```env
CUBEMASTER_API_URL=https://api.cubemaster.com
CUBEMASTER_TOKEN_ID=xxx
RESPONSE_OUTPUT_DIR=app/response_data
```

---

## 📝 Arquivos Principais

```
app/
├── main.py                 # Endpoints e lógica de fluxo
├── config.py               # Configuração centralizada
├── excel_transformer.py    # Transformação JSON → Excel
└── cubemaster_client.py    # Cliente API CubeMaster
```

---

## ✅ Checklist de Deploy

- [ ] Build: `docker-compose build`
- [ ] Start: `docker-compose up -d`
- [ ] Verificar logs: `docker logs cubemaster_poc_prod`
- [ ] Verificar diretórios criados
- [ ] Permissões no volume `/mnt/psappt1/AJ_LOGISTICA_TST/`
- [ ] Testar processamento de arquivo

---

**Data**: 2025-11-28  
**Versão**: 1.0.0  
**Status**: ✅ Produção
