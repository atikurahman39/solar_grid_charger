#!/bin/bash
# =====================================================
#  Solar-Grid Charger — one-time git setup
#  Run this once inside the solar-grid-charger/ folder.
# =====================================================
set -e

echo "==> Initialising git repository..."
git init

echo "==> Setting main as the default branch..."
git branch -M main

echo "==> Staging all files (.gitignore already excludes secrets/data/models)..."
git add .

echo "==> Creating the first commit..."
git commit -m "Initial commit: firmware, backend, and ML pipeline"

echo ""
echo "======================================================================"
echo " Local repo is ready. Now connect it to GitHub:"
echo ""
echo "   1. Create an EMPTY repo on github.com (no README/.gitignore)."
echo "      Suggested name: solar-grid-charger"
echo ""
echo "   2. Link it and push (replace USERNAME):"
echo ""
echo "      git remote add origin https://github.com/USERNAME/solar-grid-charger.git"
echo "      git push -u origin main"
echo ""
echo "   When asked for a password, paste a Personal Access Token"
echo "   (GitHub → Settings → Developer settings → Personal access tokens),"
echo "   NOT your account password."
echo "======================================================================"
