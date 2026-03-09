# Plan de Integración Total: FRED API (823,000+ Series)

Este documento registra el progreso de la implementación de la capacidad total de la FRED API en la plataforma QuantFund.

## 1. Categorías (Categories)
- [x] **fred/category**: Obtener metadatos de una categoría.
- [x] **fred/category/children**: Navegación jerárquica de carpetas.
- [ ] **fred/category/related**: Categorías vinculadas.
- [x] **fred/category/series**: Listado de indicadores por carpeta.
- [ ] **fred/category/tags**: Filtrado por etiquetas de categoría.
- [ ] **fred/category/related_tags**: Etiquetas relacionadas.

## 2. Lanzamientos (Releases)
- [ ] **fred/releases**: Calendario de publicaciones globales.
- [ ] **fred/releases/dates**: Fechas de próximos lanzamientos.
- [ ] **fred/release**: Detalles de un reporte específico.
- [ ] **fred/release/series**: Series contenidas en un reporte.
- [ ] **fred/release/sources**: Fuentes de un lanzamiento.
- [ ] **fred/release/tables**: Tablas estructuradas de reportes.

## 3. Series de Datos (Series) - *EL NÚCLEO*
- [x] **fred/series**: Metadatos básicos del indicador.
- [ ] **fred/series/categories**: Ubicación en el árbol de datos.
- [x] **fred/series/observations**: Datos históricos (Valores).
- [x] **fred/series/search**: Motor de búsqueda global (823k series).
- [ ] **fred/series/updates**: Monitor de actualizaciones en tiempo real.
- [ ] **fred/series/vintagedates**: Historial de revisiones de datos.

## 4. Fuentes y Etiquetas (Sources & Tags)
- [ ] **fred/sources**: Listado de instituciones proveedoras.
- [ ] **fred/source**: Detalle de institución (ej. BLS, BEA).
- [ ] **fred/tags**: Explorador de etiquetas global.
- [ ] **fred/tags/series**: Búsqueda multivariable por etiquetas.

## 5. Datos Regionales y Mapas (Geospatial)
- [ ] **Shape Files**: Datos para visualización cartográfica.
- [ ] **Series Regional Data**: Datos por estado, condado y MSA.

---
*Documento generado el 7 de marzo de 2026 para seguimiento de desarrollo institucional.*
