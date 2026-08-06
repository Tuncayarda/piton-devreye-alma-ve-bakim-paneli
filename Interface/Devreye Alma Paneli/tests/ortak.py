#!/usr/bin/env python3
"""Testlerin ortak kurulumu."""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
if str(KOK) not in sys.path:
    sys.path.insert(0, str(KOK))

# Panelin kalıcı verisi (konfigürasyon varsayılanları) testlerde geçici bir
# dizine yazılır: testler kullanıcının gerçek ayarlarını ne okur ne bozar.
import os  # noqa: E402
os.environ["PANEL_VERI_DIZINI"] = tempfile.mkdtemp(prefix="devreye-veri-")

from core import (ayar, device_map, firmware, isler, kimlik,  # noqa: E402
                  konfig, switch_okuma)
import panel_api  # noqa: E402

from . import sahte  # noqa: E402


class PanelTesti(unittest.TestCase):
    """Her testte temiz bir DeviceMap, temiz bellek ve temiz görünüm."""

    def kur_harita(self, harita: dict) -> device_map.Envanter:
        dosya = Path(tempfile.mkdtemp(prefix="devreye-test-")) / "DeviceMap.json"
        dosya.write_text(json.dumps(harita, ensure_ascii=False),
                         encoding="utf-8")
        self.harita_yolu = dosya
        ayar.DEVICE_MAP = dosya
        device_map.onbellegi_bosalt()
        return device_map.yukle(1, dosya)

    def setUp(self):
        self._eski_device_map = ayar.DEVICE_MAP
        self._eski_kyland = ayar.KYLAND_PORT
        self._eski_video = ayar.VIDEO_PORT
        self._eski_anons = ayar.ANONS_PORT
        # Bir önceki test panel_api.temizle() çağırmış olabilir; kuyruk
        # kapalı kalırsa bu testin işleri hiç başlamaz.
        isler.YONETICI.ac()
        self.kuyrugu_bosalt()
        kimlik.hepsini_unut()
        # Kayıtlı varsayılan dosyası da silinir: bir testin girdiği değer
        # bir sonrakine sızmasın.
        konfig.varsayilanlari_sil()
        firmware.temizle()
        for g in list(isler._GORUNUM.values()):
            g.temizle()
        isler._GORUNUM.clear()

    def tearDown(self):
        ayar.DEVICE_MAP = self._eski_device_map
        ayar.KYLAND_PORT = self._eski_kyland
        ayar.VIDEO_PORT = self._eski_video
        ayar.ANONS_PORT = self._eski_anons
        try:
            switch_okuma.modul().SWITCH_PORT = self._eski_kyland
        except Exception:
            pass
        device_map.onbellegi_bosalt()
        kimlik.hepsini_unut()
        self.kuyrugu_bosalt()

    @staticmethod
    def kuyrugu_bosalt(sure: float = 30.0) -> None:
        """Kuyruğu gerçekten boşaltır.

        Yalnız iptal edip silmeyi denemek yetmiyor: çalışan bir iş
        silinemediği için kuyrukta kalıyor ve bir sonraki testin aynı
        anahtarlı işi "zaten var" diye reddediliyordu. Burada işlerin
        bitmesi BEKLENİR.
        """
        for j in isler.YONETICI.liste():
            isler.YONETICI.iptal(j.id)
        bitis = time.time() + sure
        while time.time() < bitis:
            kalan = [j for j in isler.YONETICI.liste()
                     if j.durum in (isler.BEKLIYOR, isler.CALISIYOR)]
            if not kalan:
                break
            time.sleep(0.1)
        for j in isler.YONETICI.liste():
            isler.YONETICI.sil(j.id)

    # ---- yardımcılar ----
    def switch_portu(self, port: int) -> None:
        """Sahte switch'in portunu hem panele hem kardeş backend'e uygula."""
        ayar.KYLAND_PORT = port
        switch_okuma.modul().SWITCH_PORT = port

    def isi_bekle(self, is_: isler.Is, sure: float = 30.0) -> isler.Is:
        bitti = threading.Event()

        def kontrol():
            for _ in range(int(sure / 0.05)):
                if is_.durum in (isler.TAMAM, isler.IPTAL, isler.HATA):
                    break
                bitti.wait(0.05)
            bitti.set()

        t = threading.Thread(target=kontrol, daemon=True)
        t.start()
        t.join(sure + 1)
        return is_


class ServisTesti(PanelTesti):
    """Gerçek HTTP servisini ayağa kaldıran testler."""

    def servis_ac(self):
        srv = panel_api.sunucu("127.0.0.1", 0)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{port}"

    @staticmethod
    def cagir(taban: str, yol: str, govde=None, yontem=None):
        """Basit HTTP istemcisi — (durum kodu, gövde) döndürür."""
        import urllib.error
        import urllib.request

        veri = None if govde is None else json.dumps(govde).encode()
        istek = urllib.request.Request(
            taban + yol, data=veri,
            method=yontem or ("POST" if veri is not None else "GET"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(istek, timeout=20) as y:
                return y.status, json.loads(y.read() or b"{}")
        except urllib.error.HTTPError as e:
            ham = e.read()
            try:
                return e.code, json.loads(ham or b"{}")
            except ValueError:
                return e.code, {"ham": ham.decode("utf-8", "replace")}
