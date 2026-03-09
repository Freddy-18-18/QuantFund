#!/bin/bash
# QuantFund Dashboard Setup Script

set -e

echo "========================================="
echo "QuantFund XAUUSD Dashboard Setup"
echo "========================================="
echo ""

# Check prerequisites
echo "Checking prerequisites..."

# Check Rust
if ! command -v cargo &> /dev/null; then
    echo "❌ Rust is not installed. Please install from https://rustup.rs/"
    exit 1
fi
echo "✅ Rust found: $(cargo --version)"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install from https://nodejs.org/"
    exit 1
fi
echo "✅ Node.js found: $(node --version)"

# Check PostgreSQL
if ! command -v psql &> /dev/null; then
    echo "⚠️  PostgreSQL client not found. Make sure PostgreSQL is installed and running."
else
    echo "✅ PostgreSQL found: $(psql --version)"
fi

echo ""
echo "Installing dependencies..."
echo ""

# Install frontend dependencies
cd dashboard
echo "📦 Installing Node.js dependencies..."
npm install

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Ensure PostgreSQL is running with XAUUSD data loaded"
echo "2. Run: cd dashboard && npm run tauri dev"
echo ""
echo "For production build: npm run tauri build"
echo ""
