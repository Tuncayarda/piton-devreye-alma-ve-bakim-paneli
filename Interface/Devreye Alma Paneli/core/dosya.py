#!/usr/bin/env python3
"""Üretilen dosyayı işletim sisteminin kendi uygulamasıyla açmak.

Panel bir Excel çıkarınca kullanıcının sıradaki işi onu açmaktır; dosyayı
Finder/Gezgin'de elle aramak gereksiz bir adım.

Buradaki iki işlev YOL ALMAZ, yol çağıran taraftan gelir — ama arayüzden
gelen bir metin olarak değil: iş kaydında duran, panelin kendi yazdığı
yol olarak. Tarayıcıdan gelen metinle dosya açmak, yerel serviste bile
"herhangi bir dosyayı aç" ucu demek olurdu.

Komutlar kabuk üzerinden değil, argüman listesiyle çalıştırılır; dosya
adında boşluk ya da kabuk karakteri olması bir şeyi değiştirmez.
"""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def _komut(yol: Path, klasor: bool) -> list[str]:
    sistem = platform.system()
    if sistem == "Darwin":
        # -R dosyayı Finder'da seçili gösterir.
        return ["open", "-R", str(yol)] if klasor else ["open", str(yol)]
    if sistem == "Windows":
        if klasor:
            return ["explorer", f"/select,{yol}"]
        return ["cmd", "/c", "start", "", str(yol)]
    return ["xdg-open", str(yol.parent if klasor else yol)]


def ac(yol: Path | str, klasor: bool = False) -> None:
    """Dosyayı (ya da bulunduğu klasörü) açar.

    Dosya yoksa hata verir: "açtım" deyip hiçbir şey olmaması, kullanıcıyı
    dosyanın nerede olduğunu aramaya bırakır.
    """
    p = Path(yol)
    if not p.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {p}")
    try:
        # Windows'ta explorer dosyayı seçtiğinde 1 döndürebiliyor; çıkış
        # kodu burada bir şey ifade etmiyor, o yüzden check edilmez.
        subprocess.run(_komut(p, klasor), check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10)
    except FileNotFoundError as exc:      # açıcı komut yok (kimi Linux)
        raise RuntimeError(
            "Dosyayı açacak bir uygulama bulunamadı") from exc
    except subprocess.SubprocessError as exc:
        raise RuntimeError("Dosya açılamadı") from exc
