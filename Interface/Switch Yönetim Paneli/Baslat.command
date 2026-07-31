#!/bin/bash
# Yedek başlatıcı: ".app" açılmazsa buna çift tıkla.
cd "$(dirname "$0")"
exec python3 app.py
