// Arayüzün Python'a nasıl ulaştığını tek yerde seçer.
//
// Normal tarayıcı sayfasında işaret yoktur ve mevcut aynı-origin HTTP
// uçları kullanılır. Masaüstü için üretilen tek HTML, modüller çalışmadan
// önce açıkça şunu yazar:
//
//   window.__PANEL_TRANSPORT__ = 'bridge';
//   window.__PANEL_CAPABILITY__ = '<oturumluk-rastgele-deger>';
//
// Bridge modu bilinçli olarak HTTP'ye geri düşmez. Köprü kurulamazsa hata
// çağırana gider; aksi davranış paketleme hatasını gizler ve uygulamayı
// yeniden yerel ağ döngüsüne bağımlı kılar.

export const TRANSPORT_ISARETI = "__PANEL_TRANSPORT__";
export const CAPABILITY_ISARETI = "__PANEL_CAPABILITY__";

const BRIDGE_MODU = "bridge";
const BRIDGE_BEKLEME_MS = 15000;
const CAPABILITY_DESENI = /^[A-Za-z0-9_-]{43}$/;

const nesne = (deger) =>
  deger !== null &&
  typeof deger === "object" &&
  !Array.isArray(deger);

function zarfDogrula(zarf) {
  if (
    !nesne(zarf) ||
    typeof zarf.ok !== "boolean" ||
    !Number.isInteger(zarf.status)
  ) {
    throw new Error("Masaüstü köprüsü geçersiz yanıt verdi");
  }
  return {
    ok: zarf.ok,
    status: zarf.status,
    body: nesne(zarf.body) ? zarf.body : {},
  };
}

export function tasimaOlustur(kok = globalThis) {
  let bridgeBekleme = null;

  const bridgeModu = () => kok[TRANSPORT_ISARETI] === BRIDGE_MODU;

  const bridgeCapability = () => {
    const capability = kok[CAPABILITY_ISARETI];
    if (
      typeof capability !== "string" ||
      !CAPABILITY_DESENI.test(capability)
    ) {
      throw new Error("Masaüstü köprü yeteneği geçersiz");
    }
    return capability;
  };

  const bridgeApi = () => {
    const api = kok.pywebview && kok.pywebview.api;
    return api && typeof api.invoke === "function" ? api : null;
  };

  // İlk denetim ile olay dinleyicisinin kurulması arasında pywebviewready
  // gelebilir. Dinleyici eklendikten sonra ikinci kez bakılması bu yarışı
  // kapatır. API zaten hazırsa olayı boşuna beklemeyiz.
  const bridgeBekle = () => {
    const hazir = bridgeApi();
    if (hazir) return hazir;
    if (bridgeBekleme) return bridgeBekleme;

    bridgeBekleme = new Promise((resolve, reject) => {
      let bitti = false;
      let zaman = null;
      const zamanKur = (kok.setTimeout || globalThis.setTimeout).bind(kok);
      const zamanSil = (kok.clearTimeout || globalThis.clearTimeout).bind(kok);

      const temizle = () => {
        kok.removeEventListener("pywebviewready", olay);
        if (zaman !== null) zamanSil(zaman);
      };
      const bitir = (islem, deger) => {
        if (bitti) return;
        bitti = true;
        temizle();
        islem(deger);
      };
      const olay = () => {
        const api = bridgeApi();
        if (api) bitir(resolve, api);
        else bitir(reject, new Error("Masaüstü köprüsü hazır değil"));
      };

      kok.addEventListener("pywebviewready", olay, { once: true });

      // Olay, yukarıdaki dinleyici kurulmadan hemen önce gelmiş olabilir.
      const aradaHazirlanan = bridgeApi();
      if (aradaHazirlanan) {
        bitir(resolve, aradaHazirlanan);
        return;
      }

      zaman = zamanKur(() =>
        bitir(
          reject,
          new Error("Masaüstü köprüsü zamanında hazırlanmadı"),
        ), BRIDGE_BEKLEME_MS);
    });
    return bridgeBekleme;
  };

  const httpIstek = async (yontem, yol, govde) => {
    const secenek = {
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    };
    if (yontem !== "GET") {
      secenek.method = yontem;
      secenek.body = JSON.stringify(govde || {});
    }
    const yanit = await kok.fetch(yol, secenek);
    let body = {};
    const tur = yanit.headers.get("Content-Type") || "";
    if (tur.includes("application/json")) {
      try {
        body = await yanit.json();
      } catch {
        body = {};
      }
    }
    return {
      ok: yanit.ok,
      status: yanit.status,
      body: nesne(body) ? body : {},
    };
  };

  const bridgeIstek = async (yontem, yol, govde) => {
    const capability = bridgeCapability();
    const api = await bridgeBekle();
    const zarf = await api.invoke(capability, yontem, yol, govde || {});
    return zarfDogrula(zarf);
  };

  return {
    istek(yontem, yol, govde = {}) {
      return bridgeModu()
        ? bridgeIstek(yontem, yol, govde)
        : httpIstek(yontem, yol, govde);
    },
  };
}

export const tasima = tasimaOlustur();
