# Build & Run Instructions

Instrucciones detalladas para compilar y ejecutar la plataforma QuantFund XAUUSD.

---

## 🔧 Requisitos del Sistema

### Hardware Mínimo
- CPU: 4 cores
- RAM: 8 GB
- Disco: 10 GB libres
- Internet: Para descarga de datos

### Hardware Recomendado
- CPU: 8+ cores
- RAM: 16 GB
- Disco: 50 GB SSD
- Internet: Conexión estable

### Software
- Windows 10/11, Linux, o macOS
- Rust 1.75+
- Node.js 18+
- PostgreSQL 14+
- Python 3.11+

---

## 📦 Instalación de Dependencias

### 1. Instalar Rust

**Windows:**
```powershell
# Descargar e instalar desde https://rustup.rs/
# O usar winget:
winget install Rustlang.Rustup
```

**Linux/Mac:**
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

Verificar:
```bash
rustc --version
cargo --version
```

### 2. Instalar Node.js

**Windows:**
```powershell
winget install OpenJS.NodeJS.LTS
```

**Linux:**
```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**Mac:**
```bash
brew install node
```

Verificar:
```bash
node --version
npm --version
```

### 3. Instalar PostgreSQL

**Windows:**
```powershell
winget install PostgreSQL.PostgreSQL
```

**Linux:**
```bash
sudo apt-get install postgresql postgresql-contrib
```

**Mac:**
```bash
brew install postgresql
brew services start postgresql
```

Verificar:
```bash
psql --version
```

### 4. Instalar Python

**Windows:**
```powershell
winget install Python.Python.3.11
```

**Linux:**
```bash
sudo apt-get install python3.11 python3-pip
```

**Mac:**
```bash
brew install python@3.11
```

Verificar:
```bash
python --version
pip --version
```

---

## 🚀 Setup del Proyecto

### Paso 1: Clonar o Navegar al Proyecto

```bash
cd QuantFund
```

### Paso 2: Ejecutar Script de Setup

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File setup_dashboard.ps1
```

**Linux/Mac:**
```bash
chmod +x setup_dashboard.sh
./setup_dashboard.sh
```

Este script:
- ✅ Verifica dependencias
- ✅ Instala paquetes Node.js
- ✅ Prepara el entorno

---

## 💾 Configuración de Base de Datos

### 1. Iniciar PostgreSQL

**Windows:**
```powershell
# PostgreSQL se inicia automáticamente como servicio
# Para verificar:
Get-Service postgresql*
```

**Linux:**
```bash
sudo systemctl start postgresql
sudo systemctl enable postgresql
```

**Mac:**
```bash
brew services start postgresql
```

### 2. Crear Base de Datos (si es necesario)

```bash
# Conectar a PostgreSQL
psql -U postgres

# Crear base de datos (opcional)
CREATE DATABASE quantfund;

# Salir
\q
```

### 3. Configurar Credenciales

Editar `dashboard/src-tauri/src/database.rs`:

```rust
impl Default for DbConfig {
    fn default() -> Self {
        Self {
            host: "localhost".to_string(),
            port: 5432,
            user: "postgres".to_string(),
            password: "TU_PASSWORD_AQUI".to_string(),
            dbname: "postgres".to_string(),
        }
    }
}
```

---

## 📊 Descarga de Datos XAUUSD

### Instalar Dependencias Python

```bash
pip install pandas psycopg2-binary histdata
```

### Descargar Datos Históricos

```bash
# Descargar 2020-2024 (recomendado)
python download_histdata.py --start-year 2020 --end-year 2024 --timeframe M1

# O solo un año para pruebas rápidas
python download_histdata.py --start-year 2024 --end-year 2024 --timeframe M1
```

**Tiempo estimado:**
- 1 año: 5-10 minutos
- 5 años: 20-40 minutos

### Verificar Datos

```bash
psql -U postgres -c "SELECT COUNT(*), MIN(datetime), MAX(datetime) FROM xauusd_ohlcv WHERE symbol='XAUUSD' AND timeframe='M1';"
```

Deberías ver algo como:
```
  count  |         min         |         max         
---------+---------------------+---------------------
 2628000 | 2020-01-01 00:00:00 | 2024-12-31 23:59:00
```

---

## 🏗️ Compilación

### Modo Desarrollo

```bash
cd dashboard

# Compilar y ejecutar en modo desarrollo
npm run tauri dev
```

Esto:
1. Compila el backend Rust
2. Inicia el servidor de desarrollo Vite
3. Abre la aplicación automáticamente

**Hot Reload:** Los cambios en TypeScript se recargan automáticamente.  
**Rust Changes:** Requieren reiniciar (Ctrl+C y volver a ejecutar).

### Modo Producción

```bash
cd dashboard

# Build optimizado
npm run tauri build
```

**Salida:**
- Windows: `dashboard/src-tauri/target/release/quantfund-dashboard.exe`
- Linux: `dashboard/src-tauri/target/release/quantfund-dashboard`
- Mac: `dashboard/src-tauri/target/release/bundle/macos/QuantFund Dashboard.app`

**Tiempo de compilación:**
- Primera vez: 5-10 minutos
- Subsecuentes: 1-3 minutos

---

## ▶️ Ejecución

### Desarrollo

```bash
cd dashboard
npm run tauri dev
```

### Producción (después de build)

**Windows:**
```powershell
.\dashboard\src-tauri\target\release\quantfund-dashboard.exe
```

**Linux:**
```bash
./dashboard/src-tauri/target/release/quantfund-dashboard
```

**Mac:**
```bash
open "dashboard/src-tauri/target/release/bundle/macos/QuantFund Dashboard.app"
```

---

## 🧪 Testing

### Tests Rust

```bash
# Todos los tests
cargo test --workspace

# Tests específicos
cargo test --package quantfund-core
cargo test --package quantfund-strategy
cargo test --package quantfund-backtest

# Con output detallado
cargo test --workspace -- --nocapture
```

### Tests Python

```bash
cd research
pip install pytest
pytest
```

### Tests Frontend

```bash
cd dashboard
npm test
```

---

## 🐛 Troubleshooting

### Error: "Database connection failed"

**Solución:**
```bash
# Verificar que PostgreSQL está corriendo
# Windows:
Get-Service postgresql*

# Linux:
sudo systemctl status postgresql

# Verificar credenciales en database.rs
```

### Error: "Rust compilation failed"

**Solución:**
```bash
# Actualizar Rust
rustup update

# Limpiar y recompilar
cd dashboard/src-tauri
cargo clean
cargo build
```

### Error: "Node modules not found"

**Solución:**
```bash
cd dashboard
rm -rf node_modules package-lock.json
npm install
```

### Error: "No data available"

**Solución:**
```bash
# Verificar datos en PostgreSQL
psql -U postgres -c "SELECT COUNT(*) FROM xauusd_ohlcv;"

# Si está vacío, ejecutar download script
python download_histdata.py --start-year 2024 --end-year 2024
```

### Error: "Tauri build failed"

**Solución:**
```bash
# Instalar dependencias de sistema (Linux)
sudo apt-get install libwebkit2gtk-4.0-dev \
    build-essential \
    curl \
    wget \
    file \
    libssl-dev \
    libgtk-3-dev \
    libayatana-appindicator3-dev \
    librsvg2-dev

# Verificar versiones
rustc --version  # Debe ser 1.75+
node --version   # Debe ser 18+
```

---

## 📝 Logs y Debugging

### Ver Logs de la Aplicación

**Desarrollo:**
Los logs aparecen en la consola donde ejecutaste `npm run tauri dev`

**Producción:**
```bash
# Windows:
$env:RUST_LOG="debug"
.\quantfund-dashboard.exe

# Linux/Mac:
RUST_LOG=debug ./quantfund-dashboard
```

### Niveles de Log

```bash
# Error only
RUST_LOG=error

# Warning y error
RUST_LOG=warn

# Info, warning, error
RUST_LOG=info

# Debug (verbose)
RUST_LOG=debug

# Trace (muy verbose)
RUST_LOG=trace
```

### Logs de PostgreSQL

**Windows:**
```
C:\Program Files\PostgreSQL\14\data\log\
```

**Linux:**
```
/var/log/postgresql/
```

**Mac:**
```
/usr/local/var/log/postgresql/
```

---

## 🔄 Actualización

### Actualizar Dependencias

```bash
# Rust
rustup update

# Node.js packages
cd dashboard
npm update

# Python packages
pip install --upgrade pandas psycopg2-binary
```

### Rebuild Completo

```bash
# Limpiar todo
cd dashboard/src-tauri
cargo clean

cd ..
rm -rf node_modules dist

# Reinstalar
npm install

# Rebuild
npm run tauri build
```

---

## 📦 Distribución

### Crear Instalador

```bash
cd dashboard
npm run tauri build
```

**Salida:**
- Windows: `.exe` y `.msi` en `target/release/bundle/`
- Linux: `.deb`, `.AppImage` en `target/release/bundle/`
- Mac: `.dmg`, `.app` en `target/release/bundle/`

### Empaquetar para Distribución

```bash
# Crear archivo ZIP con ejecutable y documentación
# Windows:
Compress-Archive -Path dashboard/src-tauri/target/release/quantfund-dashboard.exe, QUICKSTART.md, README.md -DestinationPath QuantFund-v0.1.0-windows.zip

# Linux:
tar -czf QuantFund-v0.1.0-linux.tar.gz \
    dashboard/src-tauri/target/release/quantfund-dashboard \
    QUICKSTART.md \
    README.md
```

---

## 🎯 Checklist Pre-Ejecución

Antes de ejecutar por primera vez:

- [ ] Rust instalado y actualizado
- [ ] Node.js instalado
- [ ] PostgreSQL corriendo
- [ ] Python instalado
- [ ] Dependencias instaladas (`setup_dashboard.ps1`)
- [ ] Datos XAUUSD descargados
- [ ] Credenciales de DB configuradas
- [ ] Tests pasando (`cargo test`)

---

## 📚 Recursos Adicionales

- **Documentación Rust:** https://doc.rust-lang.org/
- **Documentación Tauri:** https://tauri.app/
- **Documentación React:** https://react.dev/
- **Documentación PostgreSQL:** https://www.postgresql.org/docs/

---

## 🎉 ¡Listo!

Si todos los pasos se completaron exitosamente, deberías poder:

1. ✅ Ejecutar `npm run tauri dev`
2. ✅ Ver el dashboard abrirse
3. ✅ Ver estadísticas de datos XAUUSD
4. ✅ Configurar y ejecutar backtests
5. ✅ Ver resultados y métricas

**¡Feliz Trading! 🚀**
