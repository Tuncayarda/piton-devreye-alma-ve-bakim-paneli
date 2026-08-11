// Yerel API istemcisi.
//
// Parola YALNIZCA `kimlikDene()` çağrısının gövdesinde, tek seferlik
// olarak yola çıkar. Hiçbir yerde saklanmaz, global duruma yazılmaz,
// başka bir isteğe eklenmez. Sunucu da onu geri döndürmez.

import { tasima } from "./transport.js";

class ApiHatasi extends Error {
  constructor(mesaj, kod, govde) {
    super(mesaj);
    this.kod = kod;
    this.govde = govde || {};
  }
}

export function apiOlustur(tasiyici = tasima) {
  async function istek(yontem, yol, giden = {}) {
    let zarf;
    try {
      zarf = await tasiyici.istek(yontem, yol, giden);
      if (
        !zarf || typeof zarf.ok !== "boolean" ||
        !Number.isInteger(zarf.status)
      ) throw new Error("geçersiz yanıt");
    } catch {
      throw new ApiHatasi("Panel servisine ulaşılamadı", 0, {});
    }
    const govde = zarf.body && typeof zarf.body === "object" &&
        !Array.isArray(zarf.body)
      ? zarf.body
      : {};
    if (!zarf.ok) {
      throw new ApiHatasi(
        govde.hata || `İstek başarısız (${zarf.status})`,
        zarf.status,
        govde,
      );
    }
    return govde;
  }

  const get = (yol, sorgu = {}) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(sorgu)) {
      if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
    }
    const q = p.toString();
    return istek("GET", yol + (q ? `?${q}` : ""));
  };

  const post = (yol, govde = {}) => istek("POST", yol, govde);

  return {
    ApiHatasi,

    surum: () => get("/api/surum"),
    proje: (set) => get("/api/proje", { set }),
    durum: (set) => get("/api/durum", { set }),
    cihaz: (set, id) => get("/api/cihaz", { set, id }),
    kilit: (set) => get("/api/kilit", { set }),
    kontrol: (set) => get("/api/kontrol", { set }),

    isler: () => get("/api/isler"),
    is: (id) => get("/api/is", { id }),
    isIptal: (id) => post("/api/is/iptal", { id }),
    isSil: (id) => post("/api/is/sil", { id }),
    // Açılacak dosyanın yolu istemcide yok; sunucu iş kaydından okur.
    isDosya: (id, satir, klasor = false) =>
      post("/api/is/dosya", { id, satir, klasor }),

    // `otomatik`: arayüzün dakikalık keşif turu. Kuyrukta elle başlatılan
    // taramadan ayrılır ve geçmişte birikmez (bkz. core/isler _budama).
    tarama: (set, otomatik = false) => post("/api/tarama", { set, otomatik }),
    yenile: (set, cihazlar) => post("/api/yenile", { set, cihazlar }),

    // Parolanın tek geçtiği yer. Çağıran taraf, yanıt döner dönmez formu
    // temizler; değeri saklamaz.
    kimlikDene: (set, cihazId, kullanici, parola, grubaUygula) =>
      post("/api/kimlik", { set, cihazId, kullanici, parola, grubaUygula }),
    kimlikUnut: (set, cihazId) => post("/api/kimlik/unut", { set, cihazId }),
    kimlikHepsiniUnut: () => post("/api/kimlik/unut", { hepsi: true }),

    adminGiris: (parola) => post("/api/admin/giris", { parola }),

    // `gruplar`: virgülle ayrılmış grup adları — koşuya birden çok cihaz
    // grubu girebiliyor.
    ipPlan: (set, gruplar, portlar, sw) =>
      get("/api/ip/plan", { set, gruplar, portlar, switch: sw }),
    ipPanel: (set, sw) => get("/api/ip/panel", { set, switch: sw }),
    // Koşunun dokunmaması gereken portlar: bilgisayarın yeri ve switch'ler
    // arası bağlantılar. Hepsi MAC tablolarından bulunur, hiçbiri sorulmaz.
    ipKorunan: (set) => get("/api/ip/korunan", { set }),
    ipKosu: (govde) => post("/api/ip/kosu", govde),
    // Test akışı: seçili cihazlara "IP'ni fabrika adresine çevir" isteği.
    ipFabrika: (govde) => post("/api/ip/fabrika", govde),

    konfig: (set, id, grup) => get("/api/konfig", { set, id, grup }),
    // Cihaza gitmeyen hızlı uç: alan listesi + hedefler. Grup değişince
    // ekran bunu bekler, yavaş cihaz okumasını değil.
    konfigAlanlar: (set, id, grup) =>
      get("/api/konfig/alanlar", { set, id, grup }),
    konfigSifirla: (set, cihazId, grup) =>
      post("/api/konfig/sifirla", { set, cihazId, grup }),
    // kapsam: 'grup' = değer bütün gruba yazılır, 'cihaz' = yalnız o cihaza.
    konfigHedef: (set, cihazId, alan, deger, grup, kapsam = "cihaz") =>
      post("/api/konfig/hedef", { set, cihazId, alan, deger, grup, kapsam }),
    konfigUygula: (set, grup, cihazlar) =>
      post("/api/konfig/uygula", { set, grup, cihazlar }),

    // İmaj cihaz başına seçilir. `cihazlar` verilirse yalnız o cihazlara,
    // verilmezse gruptaki bütün cihazlara atanır/silinir.
    firmware: (set, grup) => get("/api/firmware", { set, grup }),
    // Dosya seçici işletim sisteminde açılır: tarayıcı gerçek yolu vermiyor.
    // İstek, kullanıcı pencereyi kapatana kadar sürer — zaman aşımı yok.
    firmwareSec: (set, grup, cihazlar, surum) =>
      post("/api/firmware/sec", { set, grup, cihazlar, surum }),
    firmwareSurum: (set, grup, cihazlar, surum) =>
      post("/api/firmware/surum", { set, grup, cihazlar, surum }),
    firmwareSil: (set, grup, cihazlar) =>
      post("/api/firmware/sil", { set, grup, cihazlar }),
    firmwareYukle: (set, grup, cihazlar) =>
      post("/api/firmware/yukle", { set, grup, cihazlar }),

    excel: (set) => post("/api/excel", { set }),

    piscu: (set) => get("/api/piscu", { set }),
    mqtt: () => get("/api/mqtt"),
    mqttBasla: (set) => post("/api/mqtt/basla", { set }),
    mqttDur: () => post("/api/mqtt/dur"),
  };
}

export const api = apiOlustur();
