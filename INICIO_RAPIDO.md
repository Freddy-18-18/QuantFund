# Inicio Rápido - QuantFund XAUUSD

Guía rápida en español para ejecutar la aplicación.

---

## ✅ Ya Tienes los Datos

Si ya tienes los datos de XAUUSD en PostgreSQL, sigue estos pasos:

### Paso 1: Verificar Datos

```powershell
# Verificar que tienes datos en PostgreSQL
powershell -ExecutionPolicy Bypass -File check_data.ps1
```

Deberías ver algo como:
```
 symbol | timeframe | total_bars |     start_date      |      end_date       | min_price | max_price
--------+-----------+------------+---------------------+---------------------+-----------+-----------
 XAUUSD | M1        |    2628000 | 2020-01-01 00:00:00 | 2024-12-31 23:59:00 |   1500.00 |   2100.00
```

### Paso 2: Instalar Dependencias

```powershell
# Solo instalar dependencias de Node.js
powershell -ExecutionPolicy Bypass -File install_deps.ps1
```

Esto instalará los paquetes necesarios de npm.

### Paso 3: Configurar Contraseña de PostgreSQL

Edita el archivo `dashboard/src-tauri/src/database.rs`:

Busca esta sección:
```rust
impl Default for DbConfig {
    fn default() -> Self {
        Self {
            host: "localhost".to_string(),
            port: 5432,
            user: "postgres".to_string(),
            password: "1818".to_string(),  // <-- CAMBIA ESTO
            dbname: "postgres".to_string(),
        }
    }
}
```

Cambia `"1818"` por tu contraseña de PostgreSQL.

### Paso 4: Ejecutar la Aplicación

```powershell
cd dashboard
npm run tauri dev
```

La aplicación se abrirá automáticamente.

---

## 🎯 Uso de la Aplicación

### 1. Verificar Datos
- En el panel izquierdo verás "XAUUSD Data"
- Debe mostrar el total de barras y rango de fechas
- Si no aparece, verifica la conexión a PostgreSQL

### 2. Configurar Estrategia
- Selecciona "SMA Crossover" del dropdown
- Ajusta los parámetros:
  - Fast Period: 20 (SMA rápida)
  - Slow Period: 50 (SMA lenta)
  - Position Size: 0.1 (10% del capital)

### 3. Configurar Riesgo
- Click en el ícono de Settings (⚙️)
- Ajusta:
  - Initial Capital: $100,000
  - Max Position Size: 10 lots
  - Max Leverage: 2.0x
  - Max Drawdown: 20%

### 4. Ejecutar Backtest
- Click en "Run Backtest"
- Verás una barra de progreso
- Los resultados aparecerán cuando termine

### 5. Analizar Resultados
- Total Return %
- Sharpe Ratio (>1 es bueno)
- Max Drawdown (menor es mejor)
- Win Rate
- Profit Factor (>1 significa ganancia)
- Estadísticas detalladas de trades

### 6. Exportar Resultados
- Click en "Export"
- Se descargará un archivo JSON con todos los datos

---

## 🐛 Solución de Problemas

### Error: "Database connection failed"

**Causa:** PostgreSQL no está corriendo o las credenciales son incorrectas.

**Solución:**
```powershell
# Verificar servicio PostgreSQL
Get-Service postgresql*

# Si no está corriendo, iniciarlo
Start-Service postgresql-x64-14  # Ajusta el nombre según tu versión
```

### Error: "No data available"

**Causa:** La tabla `xauusd_ohlcv` está vacía o no existe.

**Solución:**
```powershell
# Verificar datos
powershell -ExecutionPolicy Bypass -File check_data.ps1

# Si no hay datos, necesitas cargarlos
python download_histdata.py --start-year 2024 --end-year 2024
```

### Error: "Rust compilation failed"

**Causa:** Rust no está instalado o está desactualizado.

**Solución:**
```powershell
# Instalar Rust
winget install Rustlang.Rustup

# O actualizar
rustup update
```

### Error: "npm install failed"

**Causa:** Node.js no está instalado o hay problemas de red.

**Solución:**
```powershell
# Instalar Node.js
winget install OpenJS.NodeJS.LTS

# Limpiar caché y reinstalar
cd dashboard
Remove-Item -Recurse -Force node_modules
Remove-Item package-lock.json
npm install
```

---

## 📊 Entendiendo las Métricas

### Sharpe Ratio
- **> 2.0**: Excelente
- **1.0 - 2.0**: Bueno
- **< 1.0**: Pobre

### Sortino Ratio
- Similar al Sharpe pero solo considera volatilidad negativa
- Valores más altos son mejores

### Max Drawdown
- Pérdida máxima desde un pico
- **< 10%**: Excelente
- **10-20%**: Aceptable
- **> 20%**: Alto riesgo

### Win Rate
- Porcentaje de trades ganadores
- **> 60%**: Muy bueno
- **50-60%**: Bueno
- **< 50%**: Necesita mejora

### Profit Factor
- Ganancia total / Pérdida total
- **> 2.0**: Excelente
- **1.5 - 2.0**: Bueno
- **< 1.0**: Perdiendo dinero

### Calmar Ratio
- Return anualizado / Max Drawdown
- Valores más altos son mejores
- **> 1.0**: Bueno

---

## 🚀 Próximos Pasos

### 1. Experimentar con Parámetros
- Prueba diferentes períodos de SMA
- Ajusta el tamaño de posición
- Modifica los límites de riesgo

### 2. Optimización
- Ejecuta múltiples backtests con diferentes parámetros
- Compara resultados
- Encuentra la configuración óptima

### 3. Walk-Forward Testing
- Divide los datos en períodos
- Optimiza en período de entrenamiento
- Valida en período de prueba

### 4. Estrategias Adicionales
- Próximamente: Mean Reversion
- Próximamente: Momentum
- Próximamente: Volatility Breakout

---

## 📝 Notas Importantes

### Datos Históricos
- Los datos son de HistData.com
- Timeframe: M1 (1 minuto)
- Timezone: UTC (convertido desde EST)
- Calidad verificada (gaps, duplicados)

### Performance
- El backtest puede tardar según el rango de fechas
- 1 año de datos M1: ~2-5 minutos
- 5 años de datos M1: ~10-20 minutos

### Limitaciones Actuales
- Solo estrategia SMA Crossover implementada
- Resultados son simulados (no incluyen slippage real)
- No hay conexión a broker en vivo (próximamente MT5)

---

## 🎓 Recursos

- **Documentación Completa**: Ver `BUILD_AND_RUN.md`
- **Estado del Proyecto**: Ver `PROJECT_STATUS.md`
- **Arquitectura**: Ver `ARCHITECTURE.md`
- **Dashboard**: Ver `dashboard/README.md`

---

## 💡 Tips

1. **Empieza Simple**: Usa parámetros por defecto primero
2. **Valida Datos**: Siempre verifica que los datos estén cargados
3. **Guarda Resultados**: Exporta los backtests exitosos
4. **Compara**: Ejecuta múltiples configuraciones y compara
5. **Documenta**: Anota qué parámetros funcionan mejor

---

## ✅ Checklist Rápido

Antes de ejecutar:

- [ ] PostgreSQL corriendo
- [ ] Datos XAUUSD verificados (`check_data.ps1`)
- [ ] Contraseña configurada en `database.rs`
- [ ] Dependencias instaladas (`install_deps.ps1`)
- [ ] En directorio `dashboard`

Para ejecutar:
```powershell
npm run tauri dev
```

---

**¡Listo para empezar! 🎉**

Si tienes problemas, revisa la sección de "Solución de Problemas" arriba.
