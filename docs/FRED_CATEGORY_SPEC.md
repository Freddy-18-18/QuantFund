# Especificación Técnica: FRED Categories API

Este documento detalla la implementación de los endpoints del grupo "Categories" para la terminal institucional QuantFund.

## Endpoints de Navegación Estructural

### 1. [GET] fred/category
- **Propósito**: Obtener la identidad de una carpeta.
- **Parámetros Clave**: `category_id`.
- **Uso**: Validar la existencia de una categoría antes de profundizar.

### 2. [GET] fred/category/children
- **Propósito**: Expansión del árbol de directorios.
- **Parámetros Clave**: `category_id`, `realtime_start`, `realtime_end`.
- **Nota**: Esencial para el explorador jerárquico.

### 3. [GET] fred/category/related
- **Propósito**: Descubrir conexiones no jerárquicas entre datos (ej. Deuda -> Tasas de Interés).
- **Uso**: Implementar sección de "Categorías Relacionadas" en el panel lateral.

## Endpoints de Contenido y Filtrado

### 4. [GET] fred/category/series
- **Propósito**: Listar indicadores dentro de una carpeta.
- **Capacidad Institucional**: 
  - Soporta `limit` (max 1000) y `offset`.
  - Permite ordenamiento por `popularity`, `last_updated`, etc.
  - **Filtro Avanzado**: Puede filtrar por `tag_names` (ej. solo mostrar datos "SA" - Seasonally Adjusted).

### 5. [GET] fred/category/tags & related_tags
- **Propósito**: Obtener las etiquetas descriptivas de los datos en una categoría.
- **Uso**: Crear un sistema de facetas (filtros) similar a los sitios de e-commerce pero para datos macroeconómicos.

---
*Documentación integrada el 7 de marzo de 2026.*
