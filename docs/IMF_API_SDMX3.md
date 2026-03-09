# IMF Data SDMX API 3.0 - Documentación Técnica

> **Versión de API:** SDMX 3.0  
> **Base URL:** `https://api.imf.org/external/sdmx/3.0`  
> **Última actualización:** Marzo 2026

---

## 1. Visión General

La IMF proporciona acceso a sus bases de datos económicas y financieras a través de una API basada en el estándar **SDMX 3.0 (Statistical Data and Metadata eXchange)**. Esta API permite recuperar series temporales, metadatos estructurales, y consultar la disponibilidad de datos.

### Características Principales

| Característica | Descripción |
|----------------|-------------|
| **Estándar** | SDMX 3.0 |
| **Autenticación** | API Key (OAuth 2.0) |
| **Rate Limit** | 10 requests cada 5 segundos |
| **Formatos** | JSON (principal), XML, CSV |
| **Datasets** | IFS, DOT, PCPS, WEO, BOP, CPI, y más |

---

## 2. Autenticación

### Obtención de API Key

1. Registrarse en [IMF API Portal](https://portal.api.imf.org/)
2. Crear una aplicación
3. Obtener las credenciales:
   - **Product Key:** `75867736d82f4cb9883fd4e417398a55`
   - **Primary Key:** `8e244147061a4bca897a475f4dacc0a9`

### Uso de API Key

La autenticación se realiza mediante **OAuth 2.0** con el flujo **Client Credentials**:

```bash
# Obtener token de acceso
curl -X POST "https://api.imf.org/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_id=8e244147061a4bca897a475f4dacc0a9" \
  -d "client_secret=75867736d82f4cb9883fd4e417398a55"
```

**Respuesta:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

### Uso del Token

```bash
# Incluir en header Authorization
curl "https://api.imf.org/external/sdmx/3.0/data/..." \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## 3. Rate Limiting

| Límite | Ventana |
|--------|---------|
| 10 requests | 5 segundos |

### Estrategias de Mitigación

```rust
// Ejemplo: Token Bucket con Rust
struct RateLimiter {
    max_requests: u32,
    window_secs: f64,
    last_reset: Instant,
    tokens: f64,
}

impl RateLimiter {
    fn try_acquire(&mut self) -> bool {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_reset).as_secs_f64();
        
        // Recargar tokens
        self.tokens = (self.tokens + elapsed * (self.max_requests as f64 / self.window_secs))
            .min(self.max_requests as f64);
        
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            true
        } else {
            false
        }
    }
}
```

### Manejo de 429 Too Many Requests

```python
import time
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

def create_session():
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session
```

---

## 4. Estructura de Endpoints

### 4.1 Data Availability Queries

Consulta qué datos están disponibles sin recuperar los datos.

```
GET https://api.imf.org/external/sdmx/3.0/availability/{context}/{agencyID}/{resourceID}/{version}/{key}/{componentID}
```

**Parámetros:**

| Parámetro | Tipo | Requerido | Descripción |
|-----------|------|-----------|-------------|
| context | string | ✅ | Contexto de recuperación (usa `*` para todos) |
| agencyID | array | ✅ | Maintainer(s) de los artefactos |
| resourceID | array | ✅ | ID del recurso (dataset) |
| version | array | ✅ | Versión (`+` = latest stable, `~` = latest) |
| key | array | ✅ | Combinación de valores de dimensiones |
| componentID | array | ✅ | ID de la dimensión a consultar |
| c | object | ❌ | Filtros por componente |
| updatedAfter | string | ❌ | RFC3339 datetime |
| references | string | ❌ | Referencias a incluir |
| mode | string | ❌ | `exact` o `available` |

**Ejemplo:**
```bash
curl "https://api.imf.org/external/sdmx/3.0/availability/\
data/IMF/PCPS/+/*/.*?c[TIME_PERIOD]=ge:2020-01" \
  -H "Authorization: Bearer TOKEN"
```

**Respuesta:**
```json
{
  "data": {
    "dataConstraints": [{
      "agencyID": "IMF",
      "cubeRegions": [{
        "components": [{
          "id": "FREQ",
          "values": [{"value": "A"}, {"value": "Q"}, {"value": "M"}]
        }]
      }]
    }]
  }
}
```

---

### 4.2 Data Queries

Recuperar series temporales.

```
GET https://api.imf.org/external/sdmx/3.0/data/{context}/{agencyID}/{resourceID}/{version}/{key}
```

**Parámetros:**

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| context | template | Contexto (`data`, `*`) |
| agencyID | template | Agencia (ej: `IMF`) |
| resourceID | template | Dataset ID (ej: `PCPS`, `IFS`) |
| version | template | Versión (`+` = latest) |
| key | template | Key de la serie (ej: `PGold.PP0000`) |
| c | query | Filtros adicionales |
| firstNObservations | integer | Primeras N observaciones |
| lastNObservations | integer | Últimas N observaciones |
| dimensionAtObservation | string | `TIME_PERIOD` o `AllDimensions` |
| attributes | array | Atributos a incluir |
| measures | array | Medidas a incluir |
| includeHistory | boolean | Incluir historial de revisiones |
| asOf | string | RFC3339 datetime (time travel) |

**Ejemplo - Precios del Oro:**
```bash
# Oro - precios mensual
curl "https://api.imf.org/external/sdmx/3.0/data/\
IMF/PCPS/+/PGold.PP0000?\
dimensionAtObservation=TIME_PERIOD&\
c[TIME_PERIOD]=ge:2020-01" \
  -H "Authorization: Bearer TOKEN"
```

**Estructura de Respuesta:**
```json
{
  "data": {
    "dataSets": [{
      "series": {
        "0:0:0:0:0": {
          "attributes": [null],
          "observations": {
            "0": ["1832.5", 0, null],
            "1": ["1845.3", 0, null]
          }
        }
      },
      "structure": 0
    }],
    "structures": [{
      "dimensions": {
        "observation": [{
          "id": "TIME_PERIOD",
          "values": [{"value": "2020-01"}, {"value": "2020-02"}]
        }],
        "series": [{
          "id": "INDICATOR",
          "values": [{"id": "PGold", "name": "Gold Price"}]
        }]
      }
    }]
  }
}
```

---

### 4.3 Structure Queries

Consultar metadatos estructurales.

#### 4.3.1 Estructura de Datasets

```
GET https://api.imf.org/external/sdmx/3.0/structure/dataflows/{agencyID}/{resourceID}/{version}
```

**Ejemplo:**
```bash
curl "https://api.imf.org/external/sdmx/3.0/\
structure/dataflows/IMF?\
detail=full" \
  -H "Authorization: Bearer TOKEN"
```

**Respuesta:**
```json
{
  "data": {
    "dataflows": [{
      "id": "PCPS",
      "name": "Primary Commodity Prices",
      "description": "...",
      "structure": {
        "id": "PCPS_DSD"
      }
    }]
  }
}
```

#### 4.3.2 Estructura de Codelists

```
GET https://api.imf.org/external/sdmx/3.0/structure/codelists/{agencyID}/{resourceID}
```

**Ejemplo - Frecuencias:**
```bash
curl "https://api.imf.org/external/sdmx/3.0/\
structure/codelists/SDMX/CL_FREQ" \
  -H "Authorization: Bearer TOKEN"
```

---

### 4.4 Metadata Queries

Consultar metadatos.

```
GET https://api.imf.org/external/sdmx/3.0/metadata/metadataflow/{flowAgencyID}/{flowID}/{flowVersion}/{providerRef}
```

---

## 5. Datasets Disponibles

### 5.1 Datasets Principales para XAUUSD

| Dataset | ID | Descripción | Relevancia |
|---------|-----|-------------|------------|
| **Primary Commodity Prices** | `PCPS` | Precios de commodities (incluye oro) | ⭐⭐⭐ |
| **International Financial Statistics** | `IFS` | Tasas interés, inflación, money supply | ⭐⭐⭐ |
| **Direction of Trade** | `DOT` | Comercio internacional | ⭐⭐ |
| **World Economic Outlook** | `WEO` | Pronósticos macroeconómicos | ⭐⭐ |
| **Balance of Payments** | `BOP` | Balanza de pagos | ⭐⭐ |
| **Consumer Price Index** | `CPI` | Inflación por país | ⭐⭐ |
| **Interest Rates** | `IR` | Tasas de interés oficiales | ⭐⭐ |
| **Real Effective Exchange Rate** | `REER` | Tipo de cambio real efectivo | ⭐ |

### 5.2 Códigos de Comodities (PCPS)

| Código | Descripción |
|--------|-------------|
| `PGold` | Oro (Gold) |
| `PSilver` | Plata (Silver) |
| `PPlatinum` | Platino |
| `PCopper` | Cobre |
| `POilCrude` | Crudo (Brent) |
| `PNaturalGas` | Gas natural |
| `PWheat` | Trigo |
| `PCorn` | Maíz |

### 5.3 Códigos de Frecuencia

| Código | Descripción |
|--------|-------------|
| `A` | Anual |
| `Q` | Trimestral |
| `M` | Mensual |
| `W` | Semanal |
| `D` | Diario |

---

## 6. Ejemplos de Uso

### 6.1 Python - Cliente Básico

```python
import requests
import pandas as pd
from datetime import datetime

class IMFClient:
    BASE_URL = "https://api.imf.org/external/sdmx/3.0"
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        })
        self.rate_limiter = RateLimiter(max_requests=10, window_secs=5)
    
    def _wait_for_rate_limit(self):
        while not self.rate_limiter.try_acquire():
            time.sleep(0.1)
    
    def get_data(self, dataset: str, key: str, 
                  start: str = None, end: str = None) -> pd.DataFrame:
        """Obtener series temporales."""
        self._wait_for_rate_limit()
        
        url = f"{self.BASE_URL}/data/IMF/{dataset}/+/{key}"
        params = {"dimensionAtObservation": "TIME_PERIOD"}
        
        if start or end:
            time_filter = []
            if start:
                time_filter.append(f"ge:{start}")
            if end:
                time_filter.append(f"le:{end}")
            params["c"] = f"TIME_PERIOD={'+'.join(time_filter)}"
        
        response = self.session.get(url, params=params)
        response.raise_for_status()
        
        return self._parse_response(response.json())
    
    def get_availability(self, dataset: str, key: str = "*") -> dict:
        """Consultar disponibilidad de datos."""
        self._wait_for_rate_limit()
        
        url = f"{self.BASE_URL}/availability/data/IMF/{dataset}/+/{key}/*"
        response = self.session.get(url)
        response.raise_for_status()
        
        return response.json()
    
    def get_dataflows(self) -> list:
        """Listar todos los datasets disponibles."""
        self._wait_for_rate_limit()
        
        url = f"{self.BASE_URL}/structure/dataflows/IMF"
        response = self.session.get(url, params={"detail": "full"})
        response.raise_for_status()
        
        return response.json()["data"]["dataflows"]
    
    def _parse_response(self, data: dict) -> pd.DataFrame:
        """Parsear respuesta JSON a DataFrame."""
        # Implementación del parser SDMX JSON
        series = data["data"]["dataSets"][0]["series"]
        # ... (parser completo en implementación)
        pass


# Uso
client = IMFClient(api_key="tu-api-key")

# Obtener precio del oro
gold_df = client.get_data(
    dataset="PCPS",
    key="PGold.PP0000",
    start="2020-01",
    end="2025-01"
)

# Obtener inflación US
cpi_df = client.get_data(
    dataset="IFS",
    key="USCPI+PCPI_IX",
    start="2019"
)
```

### 6.2 Rust - Cliente de Alto Rendimiento

```rust
// engine/data/src/imf/client.rs

use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::RwLock;
use std::time::{Duration, Instant};

pub struct ImfClient {
    http: Client,
    api_key: String,
    rate_limiter: Arc<RwLock<RateLimiter>>,
    cache: Arc<ImfCache>,
}

pub struct RateLimiter {
    max_requests: u32,
    window_secs: f64,
    tokens: f64,
    last_reset: Instant,
}

impl RateLimiter {
    pub fn new(max_requests: u32, window_secs: f64) -> Self {
        Self {
            max_requests,
            window_secs,
            tokens: max_requests as f64,
            last_reset: Instant::now(),
        }
    }

    pub async fn try_acquire(&mut self) -> bool {
        let now = Instant::now();
        let elapsed = now.duration_since(self.last_reset).as_secs_f64();
        
        // Recargar tokens
        self.tokens = (self.tokens + elapsed * (self.max_requests as f64 / self.window_secs))
            .min(self.max_requests as f64);
        
        if self.tokens >= 1.0 {
            self.tokens -= 1.0;
            self.last_reset = now;
            true
        } else {
            false
        }
    }
}

impl ImfClient {
    pub fn new(api_key: String) -> Self {
        Self {
            http: Client::new(),
            api_key,
            rate_limiter: Arc::new(RwLock::new(RateLimiter::new(10, 5.0))),
            cache: Arc::new(ImfCache::new(1000)),
        }
    }

    pub async fn get_data(
        &self,
        dataset: &str,
        key: &str,
        start: Option<&str>,
        end: Option<&str>,
    ) -> Result<ImfDataResponse, ImfError> {
        // Verificar cache
        let cache_key = format!("{}:{}:{}:{}", dataset, key, start, end);
        if let Some(cached) = self.cache.get(&cache_key).await {
            return Ok(cached);
        }

        // Esperar rate limit
        {
            let mut limiter = self.rate_limiter.write().await;
            while !limiter.try_acquire().await {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
        }

        // Construir URL
        let mut url = format!(
            "{}/data/IMF/{}/+/{key}",
            BASE_URL, dataset
        );

        // Añadir filtros
        let mut params = vec![("dimensionAtObservation", "TIME_PERIOD")];
        
        if start.is_some() || end.is_some() {
            let time_parts: Vec<String> = [
                start.map(|s| format!("ge:{}", s)),
                end.map(|e| format!("le:{}", e)),
            ]
            .into_iter()
            .flatten()
            .collect();
            
            if !time_parts.is_empty() {
                params.push(("c", &format!("TIME_PERIOD={}", time_parts.join("+"))));
            }
        }

        // Hacer request
        let response = self.http
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .query(&params)
            .send()
            .await?;

        if response.status() == 429 {
            // Rate limited - backoff exponencial
            tokio::time::sleep(Duration::from_secs(5)).await;
            return self.get_data(dataset, key, start, end).await;
        }

        let data: ImfDataResponse = response.json().await?;
        
        // Guardar en cache
        self.cache.set(cache_key, data.clone()).await;
        
        Ok(data)
    }
}
```

---

## 7. Cache Strategy

### 7.1 TTL Recomendados

| Tipo de Dato | Frecuencia Actualización | TTL Sugerido |
|--------------|------------------------|--------------|
| Metadatos de estructura | Rara vez | 30 días |
| Observaciones mensuales | Mensual | 7 días |
| Observaciones diarias | Diaria | 24 horas |
| Disponibilidad datos | Diaria | 1 día |
| Actualizaciones | Cada 15 min | 5 min |

### 7.2 Implementación de Cache

```rust
// engine/data/src/imf/cache.rs

use std::time::{Duration, Instant};
use std::collections::HashMap;
use tokio::sync::RwLock;

pub struct ImfCache {
    entries: Arc<RwLock<HashMap<String, CacheEntry>>>,
    max_entries: usize,
    default_ttl: Duration,
}

struct CacheEntry {
    data: Vec<u8>,
    expires_at: Instant,
}

impl ImfCache {
    pub async fn get(&self, key: &str) -> Option<Vec<u8>> {
        let entries = self.entries.read().await;
        if let Some(entry) = entries.get(key) {
            if Instant::now() < entry.expires_at {
                return Some(entry.data.clone());
            }
        }
        None
    }

    pub async fn set(&self, key: String, data: Vec<u8>, ttl: Option<Duration>) {
        let mut entries = self.entries.write().await;
        
        // LRU eviction si está lleno
        if entries.len() >= self.max_entries {
            if let Some(oldest) = entries.iter()
                .min_by_key(|(_, e)| e.expires_at)
                .map(|(k, _)| k.clone())
            {
                entries.remove(&oldest);
            }
        }

        entries.insert(key, CacheEntry {
            data,
            expires_at: Instant::now() + ttl.unwrap_or(self.default_ttl),
        });
    }
}
```

---

## 8. Errores Comunes

| Código | Significado | Solución |
|--------|-------------|----------|
| 401 | No autorizado | Verificar API key |
| 403 | Forbidden | Verificar permisos |
| 404 | No encontrado | Verificar dataset/key |
| 429 | Rate limited | Implementar backoff |
| 500 | Error servidor | Reintentar más tarde |
| 503 | Service unavailable | Reintentar con backoff |

---

## 9. Integración con QuantFund

### 9.1 Arquitectura Propuesta

```
engine/
├── data/src/
│   ├── fred/           ✅ Existiente
│   └── imf/           ← NUEVO
│       ├── mod.rs
│       ├── client.rs       # HTTP + rate limiting
│       ├── endpoints.rs    # Todos los endpoints
│       ├── models.rs       # Structs respuesta
│       ├── cache.rs       # Cache LRU
│       └── error.rs
│
├── integration/
│   └── macro_data.rs   # Unificar FRED + IMF
```

### 9.2 Traits para el Engine

```rust
use quantfund_core::types::{Timestamp, Decimal};

pub trait MacroDataProvider: Send + Sync {
    fn get_commodity_price(&self, commodity: &str, date: Timestamp) -> Result<Decimal, Error>;
    fn get_interest_rate(&self, country: &str, date: Timestamp) -> Result<Decimal, Error>;
    fn get_inflation(&self, country: &str, date: Timestamp) -> Result<Decimal, Error>;
    fn get_gdp(&self, country: &str, date: Timestamp) -> Result<Decimal, Error>;
}
```

---

## 10. Referencia Rápida

### Endpoints Principales

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/data/{dataset}/+/{key}` | GET | Obtener datos |
| `/availability/{context}/...` | GET | Consultar disponibilidad |
| `/structure/dataflows/...` | GET | Listar datasets |
| `/structure/codelists/...` | GET | Listar códigos |
| `/metadata/...` | GET | Metadatos |

### Ejemplos Rápidos

```bash
# Precio oro mensual desde 2020
/data/IMF/PCPS/+/PGold.PP0000?c[TIME_PERIOD]=ge:2020-01

# Inflación US (CPI)
/data/IMF/IFS/+/USCPI.PCPI_IX?c[TIME_PERIOD]=ge:2019

# Existencias de oro (US)
/data/IMF/IFS/+/USDODDTSAMGDMGNO

# Balanza de pagos US
/data/IMF/BOP/+/USA.BOP.current.BOPCA.BXR.A
```

---

## 11. Links Útiles

- [IMF API Portal](https://portal.api.imf.org/)
- [IMF Data](https://data.imf.org/)
- [SDMX 3.0 Specification](https://sdmx.org/?page_id=4345)
- [Documentación SDMX JSON](https://github.com/sdmx-twg/sdmx-json)

---

*Documento generado para QuantFund - Proyecto de Trading Cuantitativo*
*Versión: 1.0 - Marzo 2026*
