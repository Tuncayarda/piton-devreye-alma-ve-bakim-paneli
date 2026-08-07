#!/usr/bin/env python3
"""PISCU üzerindeki MQTT broker'dan telemetri.

İki retained kaynak okunur (betikler/device_verify.py ile aynı):

    ALFA/DeviceMap      bütün cihazların canlı durumu (NoError, Uptime, ...)
    ALFA/AppStatus/#    uygulama çalıştıran cihazların sürüm + donanım kimliği

Bu okuma bir tam tarama başına BİR kez yapılır ve sonucu o taramadaki
bütün MQTT kaynaklı cihazlara dağıtılır: 30 cihaz için 30 ayrı broker
bağlantısı açmanın anlamı yok.

paho-mqtt kurulu değilse ya da broker'a ulaşılamıyorsa uydurma veri
üretilmez; ilgili cihazlar "okunmadı" (gri) kalır ve sebebi yazılır.
"""
from __future__ import annotations

import json
import threading
import time

from . import ayar


class MqttYok(RuntimeError):
    """paho-mqtt kurulu değil ya da broker'a ulaşılamadı."""


def _istemci(client_id: str):
    try:
        import paho.mqtt.client as mqtt
        from paho.mqtt.enums import CallbackAPIVersion
    except ImportError:
        raise MqttYok("paho-mqtt kurulu değil — MQTT okuması yapılamıyor "
                      "(pip install paho-mqtt)")
    return mqtt.Client(CallbackAPIVersion.VERSION2, client_id=client_id)


def _topla(broker: str, port: int, topic: str, sure: float,
           client_id: str, tek: bool) -> dict:
    """Retained mesajları toplar. `tek` ise ilk mesajda çıkar."""
    cl = _istemci(client_id)
    kutu: dict[str, bytes] = {}
    bitti = threading.Event()

    def on_connect(c, u, f, rc, p=None):
        c.subscribe(topic)

    def on_message(c, u, msg):
        kutu.setdefault(msg.topic, msg.payload)
        if tek:
            bitti.set()

    cl.on_connect = on_connect
    cl.on_message = on_message
    try:
        cl.connect(broker, port, keepalive=10)
        cl.loop_start()
        if tek:
            bitti.wait(sure)
        else:
            time.sleep(sure)
    except Exception as exc:
        raise MqttYok(f"MQTT broker'a bağlanılamadı ({broker}:{port})") from exc
    finally:
        try:
            cl.loop_stop()
            cl.disconnect()
        except Exception:
            pass
    return kutu


def device_map(broker: str, port: int | None = None,
               sure: float | None = None) -> dict | None:
    """Canlı ALFA/DeviceMap. Mesaj gelmezse None."""
    kutu = _topla(broker, port or ayar.MQTT_PORT, ayar.MQTT_DEVICE_MAP_TOPIC,
                  sure or ayar.MQTT_TIMEOUT, "devreye_alma_devicemap", True)
    for yuk in kutu.values():
        try:
            return json.loads(yuk)
        except ValueError:
            continue
    return None


def app_status(broker: str, port: int | None = None,
               sure: float | None = None) -> dict:
    """ALFA/AppStatus/# altındaki uygulama durumu mesajları.

    Döner: {ClientId: payload}
    """
    kutu = _topla(broker, port or ayar.MQTT_PORT,
                  f"{ayar.MQTT_APP_STATUS_PREFIX}/#",
                  sure or ayar.MQTT_TIMEOUT, "devreye_alma_appstatus", False)
    bulunan: dict[str, dict] = {}
    for topic, yuk in kutu.items():
        try:
            veri = json.loads(yuk)
        except ValueError:
            continue
        if not isinstance(veri, dict):
            continue
        bulunan[veri.get("ClientId") or topic.rsplit("/", 1)[-1]] = veri
    return bulunan


def sip_portlari(broker: str, port: int | None = None,
                 sure: float | None = None) -> dict:
    """ALFA/SipPort/<ip> — cihaz başına SIP dahili numarası.

        ALFA/SipPort/10.1.1.40  {"SipPort": 6001}

    Compartment LCD'nin dahili numarası cihazdan yalnızca uygulama
    açılışında bir kez günlüğe yazılıyor ("SIP engine started:
    sip:6001@..."); günlük tamponu dönünce o satır kayboluyor ve numara
    okunamaz oluyordu. Aynı bilgi burada retained duruyor: cihaza hiç
    dokunmadan, uygulamayı yeniden başlatmadan okunur.

    Konu adları çözülmüş IP taşır (şablon değil).

    Döner: {ip: dahili_no}
    """
    kutu = _topla(broker, port or ayar.MQTT_PORT, f"{ayar.MQTT_SIP_PORT_PREFIX}/#",
                  sure or ayar.MQTT_TIMEOUT, "devreye_alma_sipport", False)
    bulunan: dict[str, str] = {}
    for topic, yuk in kutu.items():
        ip = topic.rsplit("/", 1)[-1]
        try:
            veri = json.loads(yuk)
        except ValueError:
            continue
        deger = veri.get("SipPort") if isinstance(veri, dict) else None
        if deger not in (None, ""):
            bulunan[ip] = str(deger)
    return bulunan


class Telemetri:
    """Bir taramada toplanan MQTT görüntüsü.

    `hata` doluysa MQTT kaynaklı cihazlar gri kalır ve bu metin sebep
    olarak gösterilir. Sessizce boş sözlük döndürüp cihazları "hatalı"
    göstermek yanıltıcı olurdu.
    """

    def __init__(self, broker: str | None):
        self.broker = broker
        self.harita: dict[str, dict] = {}     # IP -> DeviceMap kaydı
        self.uygulama: dict[str, dict] = {}   # ClientId -> AppStatus
        self.sip: dict[str, str] = {}         # IP -> SIP dahili no
        self.set_no = None
        self.hata: str | None = None

    def topla(self, beklenen_set: int | None = None) -> "Telemetri":
        if not self.broker:
            self.hata = "PISCU adresi bulunamadı — MQTT okunamadı"
            return self
        try:
            ham = device_map(self.broker)
        except MqttYok as exc:
            self.hata = str(exc)
            return self
        except Exception:
            self.hata = f"MQTT broker'a ulaşılamadı ({self.broker})"
            return self

        if not ham:
            self.hata = f"{ayar.MQTT_DEVICE_MAP_TOPIC} retained mesajı gelmedi"
        else:
            for sw in ham.get("Switches") or []:
                self.set_no = sw.get("TrainSet", self.set_no)
                seti = sw.get("TrainSet", beklenen_set)
                if sw.get("IP"):
                    self._ekle(sw["IP"], sw, seti)
                for dv in sw.get("Devices") or []:
                    if dv.get("IP"):
                        self._ekle(dv["IP"], dv, seti)
            if (beklenen_set is not None and self.set_no is not None
                    and str(self.set_no) != str(beklenen_set)):
                # Başka bir setin telemetrisi bu setin satırlarına sızmamalı.
                self.harita.clear()
                self.hata = (f"Broker set {self.set_no} bildiriyor, "
                             f"istenen set {beklenen_set}")

        try:
            self.uygulama = app_status(self.broker)
        except Exception:
            pass
        try:
            self.sip = sip_portlari(self.broker)
        except Exception:
            pass
        return self

    def sip_dahili(self, ip: str) -> str:
        """Cihazın ALFA/SipPort altında duyurulan dahili numarası."""
        return self.sip.get(str(ip), "")

    def _ekle(self, ip, kayit: dict, set_no) -> None:
        """Kaydı hem şablon hem çözülmüş IP ile indeksler.

        Broker'daki DeviceMap adresleri ŞABLONDUR (10.n.1.4); panel ise
        cihazı çözülmüş adresiyle (10.1.1.4) arar. Yalnız gelen anahtarla
        saklandığında hiçbir arama tutmuyor, MQTT kaynaklı bütün cihazlar
        "telemetride bulunamadı" diye kırmızıya düşüyordu.
        """
        from .device_map import coz

        anahtarlar = {str(ip)}
        if set_no is not None:
            anahtarlar.add(coz(str(ip), set_no))
        for a in anahtarlar:
            self.harita[a] = kayit

    def kayit(self, ip: str) -> dict | None:
        return self.harita.get(ip)

    def dto(self) -> dict:
        return {"broker": self.broker, "hata": self.hata,
                "setNo": self.set_no, "kayitSayisi": len(self.harita),
                "uygulamaSayisi": len(self.uygulama)}

    def uygulama_kaydi(self, ip: str, anahtar_kelime: str) -> dict | None:
        """Önce DeviceIP eşleşmesi; DeviceIP hiç yoksa ClientId'ye düşer."""
        for veri in self.uygulama.values():
            if str(veri.get("DeviceIP", "")).strip() == ip:
                return veri
        kw = anahtar_kelime.lower()
        for anahtar, veri in self.uygulama.items():
            if kw in str(anahtar).lower() and not str(veri.get("DeviceIP", "")).strip():
                return veri
        return None


# ─────────────────────────────────────────────────── canlı MQTT dinleyici ──
class Dinleyici:
    """MQTT İzleme ekranı için sınırlı bir abone.

    Kullanıcı ekranı açıp "Başlat" deyince çalışır, kapatınca durur. Mesaj
    tamponu sabit boyutludur (`sinir`): saatlerce açık kalan bir pencere
    belleği doldurmaz. Gövdeler kırpılır — akış ekranı bir kayıt sistemi
    değil, canlı bir göstergedir.
    """

    SINIR = 300
    GOVDE_SINIRI = 400

    def __init__(self):
        self._kilit = threading.Lock()
        self._mesaj: list[dict] = []
        self._sayac: dict[str, int] = {}
        self._cl = None
        self._broker: str | None = None
        self._hata: str | None = None
        self._toplam = 0

    def calisiyor(self) -> bool:
        return self._cl is not None

    def basla(self, broker: str, port: int | None = None,
              topic: str = "#") -> None:
        with self._kilit:
            if self._cl is not None:
                return
            self._hata = None
        try:
            cl = _istemci("devreye_alma_izleme")
        except MqttYok as exc:
            self._hata = str(exc)
            return

        def on_connect(c, u, f, rc, p=None):
            c.subscribe(topic)

        def on_message(c, u, msg):
            try:
                govde = msg.payload.decode("utf-8", "replace")
            except Exception:
                govde = "<ikili veri>"
            with self._kilit:
                self._toplam += 1
                self._sayac[msg.topic] = self._sayac.get(msg.topic, 0) + 1
                self._mesaj.append({
                    "zaman": time.time(),
                    "topic": msg.topic,
                    "govde": govde[:self.GOVDE_SINIRI],
                })
                if len(self._mesaj) > self.SINIR:
                    del self._mesaj[:len(self._mesaj) - self.SINIR]

        cl.on_connect = on_connect
        cl.on_message = on_message
        try:
            cl.connect(broker, port or ayar.MQTT_PORT, keepalive=15)
            cl.loop_start()
        except Exception:
            self._hata = f"MQTT broker'a bağlanılamadı ({broker})"
            return
        with self._kilit:
            self._cl, self._broker = cl, broker

    def dur(self) -> None:
        with self._kilit:
            cl, self._cl = self._cl, None
        if cl is not None:
            try:
                cl.loop_stop()
                cl.disconnect()
            except Exception:
                pass

    def durum(self) -> dict:
        with self._kilit:
            topicler = sorted(self._sayac.items(), key=lambda x: -x[1])[:20]
            return {
                "calisiyor": self._cl is not None,
                "broker": self._broker,
                "hata": self._hata,
                "toplam": self._toplam,
                "topicler": [{"ad": t, "n": n} for t, n in topicler],
                "mesajlar": list(reversed(self._mesaj[-60:])),
            }


DINLEYICI = Dinleyici()
