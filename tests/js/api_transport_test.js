import assert from "node:assert/strict";

import { apiOlustur } from "../../static/js/core/api.js";
import {
  CAPABILITY_ISARETI,
  tasimaOlustur,
  TRANSPORT_ISARETI,
} from "../../static/js/core/transport.js";

const basarili = (body = {}) => ({ ok: true, status: 200, body });
const CAPABILITY = "A".repeat(43);

Deno.test("api yüzeyi mevcut 37 metodunu korur", () => {
  const api = apiOlustur({ istek: () => basarili() });
  const metotlar = Object.keys(api).filter((ad) => ad !== "ApiHatasi").sort();
  assert.deepEqual(
    metotlar,
    [
      "adminGiris",
      "cihaz",
      "durum",
      "excel",
      "firmware",
      "firmwareSec",
      "firmwareSil",
      "firmwareSurum",
      "firmwareYukle",
      "ipFabrika",
      "ipKorunan",
      "ipKosu",
      "ipPanel",
      "ipPlan",
      "is",
      "isDosya",
      "isIptal",
      "isSil",
      "isler",
      "kimlikDene",
      "kimlikHepsiniUnut",
      "kimlikUnut",
      "kilit",
      "konfig",
      "konfigAlanlar",
      "konfigHedef",
      "konfigSifirla",
      "konfigUygula",
      "kontrol",
      "mqtt",
      "mqttBasla",
      "mqttDur",
      "piscu",
      "proje",
      "surum",
      "tarama",
      "yenile",
    ].sort(),
  );
});

Deno.test("api GET sorgusunu ve POST gövdesini taşıyıcıya aynen verir", async () => {
  const cagrilar = [];
  const api = apiOlustur({
    istek: (...args) => {
      cagrilar.push(args);
      return basarili({ tamam: true });
    },
  });

  await api.ipPlan(2, "A B", "1,2", "sw/1");
  const govde = { set: 2, switch: "sw-1", portlar: "1,2" };
  await api.ipKosu(govde);

  assert.deepEqual(cagrilar[0], [
    "GET",
    "/api/ip/plan?set=2&gruplar=A+B&portlar=1%2C2&switch=sw%2F1",
    {},
  ]);
  assert.deepEqual(cagrilar[1], ["POST", "/api/ip/kosu", govde]);
});

Deno.test("başarısız zarf ApiHatasi kodunu ve gövdesini korur", async () => {
  const govde = { hata: "Tarama sürüyor", durum: { aktifTarama: true } };
  const api = apiOlustur({
    istek: () => ({ ok: false, status: 409, body: govde }),
  });

  await assert.rejects(
    () => api.yenile(1, ["d1"]),
    (hata) => {
      assert.ok(hata instanceof api.ApiHatasi);
      assert.equal(hata.message, "Tarama sürüyor");
      assert.equal(hata.kod, 409);
      assert.equal(hata.govde, govde);
      return true;
    },
  );
});

Deno.test("taşıma arızası kod 0 olan ApiHatasi olur", async () => {
  const api = apiOlustur({
    istek: () => {
      throw new Error("iç ayrıntı");
    },
  });

  await assert.rejects(
    () => api.surum(),
    (hata) => {
      assert.ok(hata instanceof api.ApiHatasi);
      assert.equal(hata.message, "Panel servisine ulaşılamadı");
      assert.equal(hata.kod, 0);
      assert.deepEqual(hata.govde, {});
      return true;
    },
  );
});

Deno.test("işaretsiz sayfa mevcut HTTP fetch taşımasını kullanır", async () => {
  const kok = new EventTarget();
  let cagri = null;
  // Capability yalnız bridge işareti varsa anlamlıdır.
  kok[CAPABILITY_ISARETI] = null;
  kok.fetch = (yol, secenek) => {
    cagri = { yol, secenek };
    return {
      ok: true,
      status: 200,
      headers: { get: () => "application/json; charset=utf-8" },
      json: () => ({ tamam: true }),
    };
  };
  const tasima = tasimaOlustur(kok);

  const sonuc = await tasima.istek("POST", "/api/tarama", { set: 3 });

  assert.deepEqual(sonuc, basarili({ tamam: true }));
  assert.equal(cagri.yol, "/api/tarama");
  assert.equal(cagri.secenek.method, "POST");
  assert.equal(cagri.secenek.body, '{"set":3}');
  assert.equal(cagri.secenek.cache, "no-store");
  assert.equal(cagri.secenek.headers["Content-Type"], "application/json");
});

Deno.test("bridge işareti invoke kullanır ve fetch çağırmaz", async () => {
  const kok = new EventTarget();
  let fetchSayisi = 0;
  let cagri = null;
  kok[TRANSPORT_ISARETI] = "bridge";
  kok[CAPABILITY_ISARETI] = CAPABILITY;
  kok.fetch = () => {
    fetchSayisi += 1;
  };
  kok.pywebview = {
    api: {
      invoke: (...args) => {
        cagri = args;
        return basarili({ surum: "1.0" });
      },
    },
  };
  const tasima = tasimaOlustur(kok);

  const sonuc = await tasima.istek("GET", "/api/surum");

  assert.deepEqual(cagri, [CAPABILITY, "GET", "/api/surum", {}]);
  assert.deepEqual(sonuc, basarili({ surum: "1.0" }));
  assert.equal(fetchSayisi, 0);
});

Deno.test("bridge ilk çağrıda pywebviewready olayını bekler", async () => {
  const kok = new EventTarget();
  kok[TRANSPORT_ISARETI] = "bridge";
  kok[CAPABILITY_ISARETI] = CAPABILITY;
  kok.fetch = () => {
    throw new Error("fetch kullanılmamalı");
  };
  const tasima = tasimaOlustur(kok);
  const bekleyen = tasima.istek("GET", "/api/surum");

  queueMicrotask(() => {
    kok.pywebview = {
      api: { invoke: () => basarili({ hazir: true }) },
    };
    kok.dispatchEvent(new Event("pywebviewready"));
  });

  assert.deepEqual(await bekleyen, basarili({ hazir: true }));
});

Deno.test("pywebviewready kurulum yarışında ikinci denetim köprüyü bulur", async () => {
  class YarisliKok extends EventTarget {
    addEventListener(tur, dinleyici, secenek) {
      super.addEventListener(tur, dinleyici, secenek);
      if (tur === "pywebviewready" && !this.pywebview) {
        this.pywebview = {
          api: {
            invoke: () => basarili({ hazir: true }),
          },
        };
      }
    }
  }

  const kok = new YarisliKok();
  kok[TRANSPORT_ISARETI] = "bridge";
  kok[CAPABILITY_ISARETI] = CAPABILITY;
  kok.fetch = () => {
    throw new Error("fetch kullanılmamalı");
  };
  const tasima = tasimaOlustur(kok);

  assert.deepEqual(
    await tasima.istek("GET", "/api/surum"),
    basarili({ hazir: true }),
  );
});

Deno.test("bridge invoke hatasında HTTP geri dönüşü yapılmaz", async () => {
  const kok = new EventTarget();
  let fetchSayisi = 0;
  kok[TRANSPORT_ISARETI] = "bridge";
  kok[CAPABILITY_ISARETI] = CAPABILITY;
  kok.fetch = () => {
    fetchSayisi += 1;
  };
  kok.pywebview = {
    api: {
      invoke: () => {
        throw new Error("bridge kapandı");
      },
    },
  };
  const tasima = tasimaOlustur(kok);

  await assert.rejects(() => tasima.istek("GET", "/api/surum"));
  assert.equal(fetchSayisi, 0);
});

Deno.test("bridge capability eksikse fail-closed kalır", async () => {
  const kok = new EventTarget();
  let fetchSayisi = 0;
  let invokeSayisi = 0;
  kok[TRANSPORT_ISARETI] = "bridge";
  kok.fetch = () => {
    fetchSayisi += 1;
  };
  kok.pywebview = {
    api: {
      invoke: () => {
        invokeSayisi += 1;
        return basarili();
      },
    },
  };
  const tasima = tasimaOlustur(kok);

  await assert.rejects(
    () => tasima.istek("GET", "/api/surum"),
    /köprü yeteneği geçersiz/,
  );
  assert.equal(invokeSayisi, 0);
  assert.equal(fetchSayisi, 0);
});

Deno.test("bridge geçersiz capability değerlerini reddeder", async () => {
  for (
    const capability of [
      null,
      {},
      "",
      "A".repeat(42),
      "A".repeat(44),
      `${"A".repeat(42)}!`,
    ]
  ) {
    const kok = new EventTarget();
    kok[TRANSPORT_ISARETI] = "bridge";
    kok[CAPABILITY_ISARETI] = capability;
    kok.fetch = () => {
      throw new Error("fetch kullanılmamalı");
    };
    kok.pywebview = {
      api: { invoke: () => basarili() },
    };

    await assert.rejects(
      () => tasimaOlustur(kok).istek("GET", "/api/surum"),
      /köprü yeteneği geçersiz/,
    );
  }
});
