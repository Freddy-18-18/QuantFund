# FRED API: Plan de Implementación "Total"

Este documento estructura la integración del 100% de la API de la FRED en QuantFund.

## 1. Módulo de Categorías (✅ Implementado)
- `fred/category` (Metadata)
- `fred/category/children` (Navegación)
- `fred/category/series` (Contenido)
- `fred/category/related` (Relaciones)
- `fred/category/tags` (Filtros)

## 2. Módulo de Lanzamientos (Releases) - 🚧 Prioridad Alta
**Objetivo:** Calendario económico institucional.
- [ ] `fred/releases`: Listado maestro de todos los reportes económicos.
- [ ] `fred/releases/dates`: Calendario de próximos lanzamientos.
- [ ] `fred/release`: Detalle de un release específico.
- [ ] `fred/release/series`: Indicadores dentro de un release.
- [ ] `fred/release/sources`: Quién publica el release.
- [ ] `fred/release/tables`: Tablas estructuradas (HTML/PDF replication).

## 3. Módulo de Series (Series) - ⚠️ Núcleo
**Objetivo:** Análisis profundo de datos.
- [x] `fred/series`: Info básica.
- [x] `fred/series/observations`: Datos numéricos.
- [x] `fred/series/search`: Buscador global.
- [ ] `fred/series/categories`: "Breadcrumbs" inversos.
- [ ] `fred/series/release`: A qué reporte pertenece.
- [ ] `fred/series/updates`: Feed de actualizaciones en tiempo real.
- [ ] `fred/series/vintagedates`: Historial de revisiones (Revision History).

## 4. Módulo de Fuentes (Sources) - 🚧 Pendiente
**Objetivo:** Navegación por autoridad (Credibilidad).
- [ ] `fred/sources`: Lista de 100+ fuentes (Bancos Centrales, Ministerios).
- [ ] `fred/source`: Detalle de la fuente.
- [ ] `fred/source/releases`: Todo lo que publica una fuente.

## 5. Módulo de Etiquetas (Tags) - 🚧 Pendiente
**Objetivo:** Búsqueda semántica.
- [ ] `fred/tags`: Nube de etiquetas global.
- [ ] `fred/related_tags`: Etiquetas relacionadas.
- [ ] `fred/tags/series`: Búsqueda por combinación de tags.

## 6. Mapas y Datos Regionales (Maps) - 🔮 Futuro
- [ ] `fred/geoseries`: Datos geoespaciales.
- [ ] `fred/series/group`: Agrupación regional.

---
*Plan de Ejecución: Backend Update -> Frontend Tabs -> Integration*
