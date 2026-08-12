#!/usr/bin/env python3
r"""Yükseltilmiş yetki akışı (yetki.py).

Uygulama yetkisiz açılmıyor; bu doğru ama tek başına yetmiyordu: çift
tıklayan kullanıcı hiçbir şey görmüyor, sebebini de öğrenemiyordu. Artık bir
pencere çıkıyor ve oradan yönetici olarak yeniden başlatılabiliyor.

Buradaki testler pencere AÇMAZ; asıl kararı veren saf işlevleri sabitler:
hangi platformda hangi komutla yükseltiliyor ve kullanıcının cevabı akışı
nasıl bitiriyor. Yanlış kurulan bir komut satırı, kullanıcının parolasını
girip hiçbir şeyin açılmadığını görmesi demek.

YOL KARŞILAŞTIRMASI: testler POSIX planlarını Windows'ta da kuruyor (üretimde
plan hep kendi sisteminde kurulur, ama denetim her yerde çalışmalı). Yol
mutlaklaştırma testi ÇALIŞTIRAN sistemin kurallarına göre yapılır —
Windows'ta `/panel/app.py` → `D:\panel\app.py`. Bu yüzden beklenen değerler
sabit dize olarak değil, aynı işlevden (`os.path.abspath`) türetilir; kabuk
ve AppleScript kaçırmasından geçen metinlerde ise yol yerine dosya adı
aranır. Windows CI bunu bir kez yakaladı.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from .ortak import KOK  # noqa: F401  (sys.path kurulumu)

import yetki


_PLAN = {"yol": "osascript", "exe": "", "argv": [], "dizin": "",
         "komut": ["osascript", "-e", "..."]}


class SahteSurec:
    """`subprocess.Popen` yerine geçen kanal.

    Varsayılanı BİTMEYEN bir süreçtir (`poll()` → None): yükseltme kanalı
    sahada tam olarak böyle davranıyor, başlattığı panel kapanana kadar
    dönmüyor. Kodun onu beklememesi gerekiyor.
    """

    def __init__(self, kod=None, hata=""):
        self._kod = kod
        self._hata = hata
        self.beklendi = False

    def poll(self):
        return self._kod

    def wait(self, timeout=None):
        self.beklendi = True
        return self._kod

    def communicate(self, timeout=None):
        self.beklendi = True
        return "", self._hata

    def kill(self):
        self._kod = -9


class YukseltmePlani(unittest.TestCase):

    def test_windows_runas_ile_yukseltir(self):
        plan = yetki.yukseltme_plani(
            "Windows", calistirilabilir=r"C:\Python\python.exe",
            argv=[r"C:\panel\app.py", "--tarayici"], donmus=False,
            calisma_dizini=r"C:\panel")

        self.assertEqual(plan["yol"], "runas")
        self.assertEqual(plan["exe"], r"C:\Python\python.exe")
        self.assertEqual(plan["argv"][-1], "--tarayici")
        self.assertTrue(plan["argv"][0].endswith("app.py"))
        self.assertEqual(plan["dizin"], r"C:\panel")

    def test_paketlenmis_uygulamada_argv0_tekrar_verilmez(self):
        """Paketlenmiş uygulamada argv[0] uygulamanın kendisidir.

        İkinci kez verilseydi yükseltilmiş süreç kendini argüman sanırdı.
        """
        plan = yetki.yukseltme_plani(
            "Windows", calistirilabilir=r"C:\panel\Panel.exe",
            argv=[r"C:\panel\Panel.exe", "--admin-parolasi", "x"],
            donmus=True)

        self.assertEqual(plan["argv"], ["--admin-parolasi", "x"])

    def test_betik_kipinde_mutlak_yol_verilir(self):
        """Yükseltilmiş süreç başka bir dizinde açılabilir."""
        plan = yetki.yukseltme_plani("Darwin", calistirilabilir="/usr/bin/py",
                                     argv=["app.py"], donmus=False,
                                     terminal=False)

        # Beklenen değer aynı işlevden türetilir; "mutlak" tanımı testi
        # çalıştıran sisteme göre değişiyor (bkz. modül başlığı).
        self.assertEqual(plan["argv"], [os.path.abspath("app.py")])

    def test_tek_yol_sistem_penceresidir(self):
        """Terminale devretme yok: yükseltmenin tek yolu izin penceresi.

        Kullanıcı izni pencereden verir; uygulamanın terminalle işi yok ve
        parola hiçbir yerde uygulamadan geçmez.
        """
        for sistem, beklenen in (("Darwin", "osascript"), ("Windows", "runas")):
            plan = yetki.yukseltme_plani(
                sistem, calistirilabilir="/usr/bin/py",
                argv=["/panel/app.py"], donmus=False)
            self.assertEqual(plan["yol"], beklenen)
            self.assertNotIn("sudo", " ".join(plan["komut"]))

    def test_macos_sistem_penceresiyle_yukseltir(self):
        plan = yetki.yukseltme_plani("Darwin", calistirilabilir="/usr/bin/py",
                                     argv=["/panel/app.py"], donmus=False,
                                     calisma_dizini="/panel")

        self.assertEqual(plan["yol"], "osascript")
        # Yol, testi çalıştıran sistemin kurallarıyla mutlaklaşır (Windows'ta
        # "D:\panel\app.py"); bu yüzden yolun kendisi değil, plana girdiği
        # doğrulanır. Karşılaştırma metni kabuk ve AppleScript kaçırmasından
        # geçtiği için ham dize aranmaz (bkz. modül başlığı).
        self.assertEqual(plan["argv"], [os.path.abspath("/panel/app.py")])
        betik = plan["komut"][-1]
        self.assertIn("with administrator privileges", betik)
        # Arkaplana atılmazsa osascript uygulama kapanana kadar bekler.
        self.assertIn("&", betik)
        # Yeni süreç açılışta düşerse geriye bakılacak tek yer bu günlük.
        self.assertIn(os.path.basename(yetki.gunluk_yolu()), betik)
        self.assertIn(os.path.basename(yetki.pid_yolu()), betik)

    def test_macos_komutunda_nohup_kullanilmaz(self):
        """`do shell script` terminalsiz çalıştırıyor.

        Sahada ölçüldü: macOS'un nohup'ı orada "can't detach from console:
        Inappropriate ioctl for device" deyip düşüyor ve panel hiç
        başlamıyordu. Arkaplana atmak için `&` yeterli.
        """
        plan = yetki.yukseltme_plani("Darwin", calistirilabilir="/usr/bin/py",
                                     argv=["/panel/app.py"], donmus=False,
                                     terminal=False)

        self.assertNotIn("nohup", plan["komut"][-1])
        self.assertIn("< /dev/null", plan["komut"][-1])

    def test_linux_pkexec_yoksa_otomatik_yukseltme_yok(self):
        with mock.patch.object(yetki.shutil, "which", return_value=None):
            plan = yetki.yukseltme_plani("Linux", calistirilabilir="/usr/bin/py",
                                         argv=["/panel/app.py"], donmus=False,
                                         terminal=False)
        self.assertEqual(plan["yol"], "")

        with mock.patch.object(yetki.shutil, "which",
                               return_value="/usr/bin/pkexec"):
            plan = yetki.yukseltme_plani("Linux", calistirilabilir="/usr/bin/py",
                                         argv=["/panel/app.py"], donmus=False,
                                         terminal=False)
        self.assertEqual(plan["yol"], "pkexec")
        self.assertIn(os.path.abspath("/panel/app.py"), plan["komut"])

    def test_applescript_tirnagi_kacirilir(self):
        """Yol tırnak içeriyorsa komut bozulmamalı."""
        self.assertEqual(yetki._applescript_metin('a"b\\c'), '"a\\"b\\\\c"')


class KorumaliKlasor(unittest.TestCase):
    """macOS'ta korumalı klasörler denemeden ÖNCE bilinir.

    Sahada iki kez parola girildi ve iki kez "Operation not permitted"
    alındı: yükseltilmiş süreç Masaüstü'ndeki kendi dosyalarını okuyamıyor.
    Bunun önceden söylenmesi, boşuna parola istememek demek.
    """

    def test_masaustu_korumalidir(self):
        ev = os.path.expanduser("~")
        for ad in ("Desktop", "Documents", "Downloads"):
            self.assertEqual(
                yetki.korumali_klasor(os.path.join(ev, ad, "dap"), "Darwin"),
                ad)

    def test_korumasiz_klasor_bos_doner(self):
        ev = os.path.expanduser("~")
        self.assertEqual(
            yetki.korumali_klasor(os.path.join(ev, "Projeler", "dap"),
                                  "Darwin"), "")

    def test_yalnizca_macos(self):
        yol = os.path.join(os.path.expanduser("~"), "Desktop", "dap")
        for sistem in ("Windows", "Linux"):
            self.assertEqual(yetki.korumali_klasor(yol, sistem), "")

    def test_akis_korumali_klasorde_once_uyarir(self):
        with (mock.patch.object(yetki, "korumali_klasor",
                                return_value="Desktop"),
              mock.patch.object(yetki, "yukseltme_plani",
                                return_value={"yol": "osascript"}),
              mock.patch.object(yetki, "sor", return_value="cikis") as sor):
            yetki.akis(lambda *_: None)

        ipucu = sor.call_args.kwargs.get("ipucu", "")
        self.assertIn("Desktop", ipucu)
        self.assertIn("dışına taşıyın", ipucu)


class YukseltmeSonucu(unittest.TestCase):

    def test_yolu_olmayan_sistemde_elle_baslatma_anlatilir(self):
        tamam, mesaj = yetki.yukselt({"yol": "", "exe": "", "argv": [],
                                      "komut": [], "dizin": ""})
        self.assertFalse(tamam)
        self.assertIn("otomatik yükseltme yok", mesaj)

    def test_kullanici_izni_reddederse_soylenir(self):
        with (mock.patch.object(yetki.subprocess, "Popen",
                                return_value=SahteSurec(
                                    kod=1, hata="execution error: User "
                                                "canceled. (-128)")),
              mock.patch.object(yetki, "_pid_oku", return_value=0)):
            tamam, mesaj = yetki.yukselt(_PLAN)

        self.assertFalse(tamam)
        self.assertEqual(mesaj, "Yönetici izni verilmedi")

    def test_basarili_yukseltme(self):
        with (mock.patch.object(yetki.subprocess, "Popen",
                                return_value=SahteSurec()),
              mock.patch.object(yetki, "_pid_oku", return_value=4242),
              mock.patch.object(yetki, "yeni_surec_durumu",
                                return_value=(True, "")) as durum):
            self.assertEqual(yetki.yukselt(_PLAN), (True, ""))

        durum.assert_called_once_with(pid=4242)

    def test_yukseltme_kanalinin_bitmesi_beklenmez(self):
        """Kanal, başlattığı sürecin BİTMESİNİ bekliyor; biz beklemeyiz.

        Beklenince eski süreç yeni panel kapanana kadar yaşıyordu: Dock'ta
        ikinci bir uygulama olarak duruyor, panel kapanınca da PID'i ölü
        bulup yanlışlıkla "açılışta düştü" penceresi açıyordu.
        """
        surec = SahteSurec()               # hiç bitmeyen kanal (poll → None)
        with (mock.patch.object(yetki.subprocess, "Popen",
                                return_value=surec) as popen,
              mock.patch.object(yetki, "_pid_oku", return_value=4242),
              mock.patch.object(yetki, "yeni_surec_durumu",
                                return_value=(True, ""))):
            self.assertEqual(yetki.yukselt(_PLAN), (True, ""))

        self.assertFalse(surec.beklendi, "kanalın bitmesi beklenmemeli")
        # Kendi oturumunda: biz çıkınca yeni süreç etkilenmemeli.
        self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_surec_ayakta_degilse_basarisiz(self):
        """PID yazıldı ama süreç açılışta düştüyse bu bir başarı değil."""
        with (mock.patch.object(yetki.subprocess, "Popen",
                                return_value=SahteSurec()),
              mock.patch.object(yetki, "_pid_oku", return_value=4242),
              mock.patch.object(yetki, "yeni_surec_durumu",
                                return_value=(False, "düştü"))):
            self.assertEqual(yetki.yukselt(_PLAN), (False, "düştü"))


class YeniSurecDurumu(unittest.TestCase):

    def _dosyalar(self, pid: str, gunluk: str):
        import tempfile

        dizin = tempfile.mkdtemp(prefix="devreye-yetki-")
        pid_yolu = os.path.join(dizin, "p.pid")
        gunluk_yolu = os.path.join(dizin, "p.log")
        if pid is not None:
            with open(pid_yolu, "w", encoding="utf-8") as d:
                d.write(pid)
        with open(gunluk_yolu, "w", encoding="utf-8") as d:
            d.write(gunluk)
        return (mock.patch.object(yetki, "pid_yolu", lambda: pid_yolu),
                mock.patch.object(yetki, "gunluk_yolu", lambda: gunluk_yolu))

    def test_yasayan_surec_basarilidir(self):
        p, g = self._dosyalar(str(os.getpid()), "")
        with p, g:
            self.assertEqual(yetki.yeni_surec_durumu(bekle=0), (True, ""))

    def test_olen_surecte_gunlugun_son_satiri_sebeptir(self):
        # 2**22'nin üstü: PID aralığının dışında, kesinlikle yaşamıyor.
        p, g = self._dosyalar("4194303", "bir şey\nnohup: can't detach\n")
        with p, g:
            tamam, mesaj = yetki.yeni_surec_durumu(bekle=0)

        self.assertFalse(tamam)
        self.assertIn("açılışta düştü", mesaj)
        self.assertIn("can't detach", mesaj)

    def test_macos_gizlilik_korumasi_aciklanir(self):
        """"Operation not permitted" dosya izniyle karıştırılıyor."""
        p, g = self._dosyalar("4194303",
                              "can't open file '/Users/x/Desktop/dap/app.py': "
                              "[Errno 1] Operation not permitted\n")
        with p, g, mock.patch.object(yetki.platform, "system",
                                     return_value="Darwin"):
            _tamam, mesaj = yetki.yeni_surec_durumu(bekle=0)

        self.assertIn("gizlilik koruması", mesaj)
        self.assertIn("sudo python3 app.py", mesaj)

    def test_pid_okunamazsa_suclanmaz(self):
        p, g = self._dosyalar(None, "")
        with p, g:
            self.assertEqual(yetki.yeni_surec_durumu(bekle=0), (True, ""))


class Akis(unittest.TestCase):

    def test_cikis_secilirse_uygulama_acilmaz(self):
        with mock.patch.object(yetki, "sor", return_value="cikis"):
            self.assertEqual(yetki.akis(lambda *_: None), 1)

    def test_onaydan_sonra_dock_simgesi_kaldirilir(self):
        """Eski süreç doğrulama boyunca yaşıyor ama görünmemeli.

        Görünürse yeni panelin yanında ikinci bir uygulama gibi duruyor.
        """
        with (mock.patch.object(yetki, "sor", return_value="yukselt"),
              mock.patch.object(yetki, "dock_gizle") as gizle,
              mock.patch.object(yetki, "yukselt", return_value=(True, ""))):
            self.assertEqual(yetki.akis(lambda *_: None), 0)

        gizle.assert_called_once()

    def test_cikista_dock_simgesine_dokunulmaz(self):
        """Kullanıcı "Çıkış" derse süreç zaten kapanıyor."""
        with (mock.patch.object(yetki, "sor", return_value="cikis"),
              mock.patch.object(yetki, "dock_gizle") as gizle):
            yetki.akis(lambda *_: None)

        gizle.assert_not_called()

    def test_terminale_devredilmez(self):
        """Yükseltme düşse bile başka bir yola sapılmaz.

        Kullanıcının kuralı: yetki yalnız sistem penceresinden istenir.
        """
        with (mock.patch.object(yetki, "sor",
                                side_effect=["yukselt", "cikis"]),
              mock.patch.object(yetki, "yukselt",
                                return_value=(False, "düştü")) as yukselt):
            self.assertEqual(yetki.akis(lambda *_: None), 1)

        self.assertEqual(yukselt.call_count, 1)

    def test_yukseltme_basarisizsa_sebebi_gosterilir(self):
        gorulen = []
        with (mock.patch.object(yetki, "sor",
                                side_effect=["yukselt", "cikis"]) as sor,
              mock.patch.object(yetki, "yukselt",
                                return_value=(False, "Yönetici izni verilmedi"))):
            kod = yetki.akis(gorulen.append)

        self.assertEqual(kod, 1)
        # Sebep hem konsola hem ikinci pencereye gider: kullanıcı UAC'yi
        # reddettiğinde ekranın sessizce kapanması, hatanın kendisiydi.
        self.assertIn("Yönetici izni verilmedi", " ".join(gorulen))
        self.assertIn("Yönetici izni verilmedi", sor.call_args.args[0])

    def test_pencere_kapatilabilir_ortamda_acilmaz(self):
        """PANEL_YETKI_PENCERESI=0 → kimsenin başında olmadığı koşu asılmaz."""
        with mock.patch.dict(os.environ, {"PANEL_YETKI_PENCERESI": "0"}):
            self.assertEqual(yetki.sor(), "cikis")


if __name__ == "__main__":
    unittest.main()
