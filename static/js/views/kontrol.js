// Kontrol Listesi — Excel'e yazılacak bilginin ön izlemesi.
//
// Amaç çıktının önceden görülebilmesi: sütunlar şablonun sütunlarıdır ve
// hepsi buradadır. Şablon değişirse liste de değişir; kodda ayrı bir
// kolon listesi tutulmuyor.
//
// Gri (N/A) hücre "bu cihaz türünde kullanılmıyor" demektir; "—" ise
// "henüz okunmadı". İkisi ayrı gösterilir.

import { el, doldur, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { hata, basari } from '../parts/bildirim.js';
import * as detay from '../parts/detay.js';
import * as diyalog from '../parts/diyalog.js';
import { YOK, saat, tazelik, DURUM_ETIKET } from '../core/bicim.js';

// Sütun genişlikleri: içeriği taşımayacak kadar, ekranı boğmayacak kadar.
const GENISLIK = {
  'Bölüm': 88,
  'Switch': 104,
  'Port': 52,
  'Cihaz Tanımı': 164,
  'IP Şablonu': 104,
  'Beklenen IP': 104,
  'Beklenen Versiyon': 112,
  'Beklenen SIP Dahili No': 124,
  'Cihaz İsmi': 164,
  'Bağlantı Bilgisi': 116,
  'Versiyon': 88,
  'Cihaz Numarası': 124,
  'Durum Açıklaması': 112,
  'Çalışma Süresi': 100,
};
const VARSAYILAN_GENISLIK = 112;

// Okunan değer ile şablondaki beklenen değerin eşleşmesi: soldaki sütun
// cihazdan okunur, sağdaki beklenendir. Tutuyorsa yeşil, tutmuyorsa
// kırmızı gösterilir — tabloya bakan biri sapmayı okumadan görsün.
const KARSILASTIR = {
  'Bağlantı Bilgisi': 'Beklenen IP',
  'Versiyon': 'Beklenen Versiyon',
  'SIP Dahili No': 'Beklenen SIP Dahili No',
};

// Karşılaştırma biçim farkına takılmasın: baş/son boşluk ve büyük-küçük
// harf anlam taşımıyor.
const sadelestir = (d) => String(d).trim().toLowerCase().replace(/\s+/g, ' ');

// Verinin ne kadar süre sonra "bayat" sayılacağı. Sahada Excel'i on
// dakika önceki okumadan üretmek işe yaramıyor: cihazlar o arada
// yeniden başlatılıyor, IP'si değişiyor, kablosu çekiliyor.
const BAYAT_SN = 120;

// Günlük kullanımda yalnız sapmalar görünür. Excel önizlemesi, şablonun
// bütün sütunlarını görmek isteyen kullanıcı için ayrı bir yerel sekmedir.
let raporSekmesi = 'sapmalar';

const SAPMA_KOLON = 'minmax(170px,1.1fr) 112px minmax(260px,1.7fr) 150px';

const bosMu = (v) => v === null || v === undefined || String(v).trim() === '';

function satirDegerleri(satir, sutunlar) {
  const degerler = new Map();
  satir.hucreler.forEach((h, i) => {
    if (!h.na && sutunlar[i]) degerler.set(sutunlar[i].ad, h.deger);
  });
  return degerler;
}

// Kullanıcının seçtiği sağlık tanımı: erişim + IP + varsa SIP dahili
// numarası. Sürüm ve diğer yapılandırma alanları raporda görünmeye devam
// eder, fakat cihazın temel kontrolleri geçip geçmediğini belirlemez.
function temelDegerlendir(satir, sutunlar) {
  const degerler = satirDegerleri(satir, sutunlar);
  const sorunlar = [];

  if (satir.durum !== 'yesil') {
    const kod = satir.durum === 'turuncu' ? 'giris'
      : satir.durum === 'gri' ? 'okunmadi' : 'erisim';
    const metin = kod === 'giris' ? 'Kullanıcı adı veya parola gerekli'
      : kod === 'okunmadi' ? 'Henüz okunmadı'
        : (satir.aciklama || 'Cihaza erişilemedi');
    sorunlar.push({ kod, metin, renk: satir.durum || 'kirmizi' });
    return { sorunlar, degerler, gecti: false };
  }

  const beklenenIp = degerler.get('Beklenen IP');
  const okunanIp = degerler.get('Bağlantı Bilgisi');
  if (!bosMu(beklenenIp)
      && (bosMu(okunanIp) || sadelestir(okunanIp) !== sadelestir(beklenenIp))) {
    sorunlar.push({
      kod: 'ip', renk: 'kirmizi',
      metin: bosMu(okunanIp)
        ? `IP doğrulanamadı · beklenen ${beklenenIp}`
        : `IP uyuşmuyor · beklenen ${beklenenIp}, okunan ${okunanIp}`,
    });
  }

  const beklenenSip = degerler.get('Beklenen SIP Dahili No');
  const okunanSip = degerler.get('SIP Dahili No');
  if (!bosMu(beklenenSip)
      && (bosMu(okunanSip) || sadelestir(okunanSip) !== sadelestir(beklenenSip))) {
    sorunlar.push({
      kod: 'sip', renk: 'kirmizi',
      metin: bosMu(okunanSip)
        ? `SIP dahili numarası okunamadı · beklenen ${beklenenSip}`
        : `SIP dahili numarası uyuşmuyor · beklenen ${beklenenSip}, okunan ${okunanSip}`,
    });
  }

  return { sorunlar, degerler, gecti: sorunlar.length === 0 };
}

function ozetKarti(ad, deger, renk, not) {
  return el('div', { sinif: 'dog-ozet-kart' }, [
    el('span', { sinif: 'ad', metin: ad }),
    el('strong', { stil: `color:var(--${renk})`, metin: String(deger) }),
    el('span', { sinif: 'not', metin: not }),
  ]);
}

function sapmaTablosu(satirlar, sutunlar) {
  const sapmalar = satirlar
    .map(s => ({ satir: s, sonuc: temelDegerlendir(s, sutunlar) }))
    .filter(x => !x.sonuc.gecti);

  if (!sapmalar.length) {
    return el('div', { sinif: 'bos-durum bos-durum-basarili' }, [
      el('strong', { metin: 'Temel kontrollerde sorun bulunmadı.' }),
      el('span', {
        metin: 'Seçili kapsamda erişim, IP ve SIP değerleri beklenenle uyumlu.',
      }),
    ]);
  }

  return el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:820px' }, [
      el('div', {
        sinif: 'tablo-basi', stil: `--tablo-kolon:${SAPMA_KOLON}`, role: 'row',
      }, ['Cihaz', 'Beklenen IP', 'Bulgu', 'Erişim durumu']
        .map(ad => el('span', { metin: ad }))),
      ...sapmalar.map(({ satir, sonuc }) => el('button', {
        type: 'button', sinif: 'tablo-satir dog-sapma-satir',
        stil: `--tablo-kolon:${SAPMA_KOLON}`,
        title: `${satir.ad} ayrıntılarını aç`,
        onclick: () => { if (satir.cihazId) detay.ac(satir.cihazId); },
      }, [
        el('span', { sinif: 'cihaz-ozet' }, [
          el('span', {
            sinif: 'nokta', veri: { durum: satir.durum }, 'aria-hidden': 'true',
          }),
          el('span', { sinif: 'mono kirp', metin: satir.ad || YOK }),
        ]),
        el('span', { sinif: 'mono', metin: satir.ip || YOK }),
        el('span', {
          sinif: 'sapma-metin',
          metin: sonuc.sorunlar.map(s => s.metin).join(' · '),
        }),
        el('span', {
          sinif: 'durum-yazi', veri: { durum: satir.durum },
          metin: DURUM_ETIKET[satir.durum] || YOK,
        }),
      ])),
    ]),
  ]);
}

function excelOnizlemesi(satirlar, v) {
  const kolon = v.sutunlar
    .map(s => `${GENISLIK[s.ad] || VARSAYILAN_GENISLIK}px`)
    .join(' ');
  const enAz = v.sutunlar
    .reduce((t, s) => t + (GENISLIK[s.ad] || VARSAYILAN_GENISLIK), 0)
    + v.sutunlar.length * 10;

  return [
    el('div', { sinif: 'bilgi dog-excel-notu' }, [
      'Bu görünüm üretilecek Excel dosyasının tam sütun yapısını gösterir. ',
      'Günlük inceleme için Sapmalar sekmesini kullanabilirsiniz.',
    ]),
    el('div', { sinif: 'tablo-sar' }, [
      el('div', { sinif: 'tablo', stil: `--tablo-min:${enAz}px` }, [
        el('div', {
          sinif: 'tablo-basi', stil: `--tablo-kolon:${kolon}`, role: 'row',
        }, v.sutunlar.map(s => el('span', {
          sinif: 'kirp', title: s.ad, metin: s.ad,
        }))),
        ...(satirlar.length
          ? satirlar.map(s => satirCiz(s, v.sutunlar, kolon))
          : [el('div', {
              sinif: 'tablo-bos', metin: 'Bu kategoride cihaz bulunamadı.',
            })]),
      ]),
    ]),
    el('div', { sinif: 'lejant lejant-sade' }, [
      el('span', {}, [el('i', { stil: 'background:var(--turuncu)' }),
        'Turuncu: proje varsayılanı']),
      el('span', {}, [el('i', { stil: 'background:var(--yesil)' }),
        'Yeşil: beklenenle uyumlu']),
      el('span', {}, [el('i', { stil: 'background:var(--kirmizi)' }),
        'Kırmızı: beklenenle uyuşmuyor']),
      el('span', {}, [el('i', { stil: 'background:#2a3339' }),
        'Gri alan: bu cihaz türünde kullanılmıyor']),
      el('span', { stil: 'margin-left:auto',
        metin: `${satirlar.length} satır · ${v.sutunlar.length} sütun` }),
    ]),
  ];
}

export async function tazele() {
  try {
    ata({ kontrolDurum: await api.kontrol(durum.setNo) });
  } catch (e) {
    hata(e.message);
    ata({ kontrolDurum: null });
  }
}

// ── tazelik göstergesi ───────────────────────────────────────────────────
// "37 sn önce" yazısı saniyede bir kendini yeniler. Bunun için bütün
// ekranı çizmeye gerek yok — metin doğrudan yazılır (ip.js ile aynı yol).
let sayacZaman = null;

function ekrandaMi() {
  return durum.gorunum === 'dog' && !!durum.rol;
}

function tazelikYaz() {
  const e = $('#dog-tazelik');
  if (!e) return;
  const ts = Number(e.dataset.okuma) || 0;
  if (!ts) {
    e.textContent = 'Henüz tarama yapılmadı';
    e.dataset.bayat = '1';
    return;
  }
  const sn = Math.max(0, Math.round(Date.now() / 1000 - ts));
  e.textContent = `Son tarama ${saat(ts)} · ${tazelik(ts)} önce`;
  e.dataset.bayat = sn > BAYAT_SN ? '1' : '0';
}

// Tik ekrandan çıkılınca kendi kendine durur: `ekrandaMi()` yanlışa
// düştüğünde bir sonraki tur kurulmaz (ip.js ile aynı yol).
function sayaciKur() {
  clearTimeout(sayacZaman);
  if (!ekrandaMi()) return;
  tazelikYaz();
  sayacZaman = setTimeout(sayaciKur, 1000);
}

// Verinin yaşı — Excel onayı da bunu kullanır.
function sonTaramaZamani() {
  const v = durum.kontrolDurum;
  return (v && v.sonTarama) || durum.sonTarama || 0;
}

// Taramayı öne çeken eylem app.js'ten gelir: dakikalık sayacı da o
// sıfırlıyor (bkz. app.js guncelle). Burada ikinci bir /api/tarama
// çağrısı yazmak, düğmeye basıldıktan hemen sonra otomatik turun da
// tetiklenmesi demekti.
let taramayiOneCek = () => {};

export function ciz(kok, guncelle) {
  if (guncelle) taramayiOneCek = guncelle;
  const v = durum.kontrolDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [
      el('h2', { metin: 'Doğrulama ve raporlar' }),
      // Liste kendiliğinden tazeleniyor; ne kadar taze olduğu burada
      // yazar. Excel onayı da aynı damgayı gösterir.
      el('div', {
        id: 'dog-tazelik', sinif: 'sayfa-alt dog-tazelik',
        veri: { okuma: sonTaramaZamani() || 0 },
      }),
    ]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Şimdi tara',
        disabled: durum.aktifTarama,
        // Üst bardaki "Güncelle" ile aynı iş: sıradaki taramayı öne
        // çeker, kuyruk paneli açılmaz, haber kuyruk düğmesinde belirir.
        onclick: () => taramayiOneCek(),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Excel oluştur',
        onclick: excelOnayi,
      }),
    ]),
  ]));

  if (!v) {
    parcalar.push(el('p', {
      sinif: 'bilgi',
      metin: 'Doğrulama verisi alınamadı. Biraz sonra yeniden deneyin.',
    }));
    doldur(kok, parcalar);
    return;
  }

  // ── yerel görünüm ve kategori filtresi ──
  parcalar.push(el('div', {
    sinif: 'yerel-sekmeler rapor-sekmeleri', role: 'tablist',
    'aria-label': 'Rapor görünümü',
  }, [
    ['sapmalar', 'Sapmalar'],
    ['excel', 'Excel önizlemesi'],
  ].map(([id, ad]) => el('button', {
    type: 'button', sinif: 'yerel-sekme', role: 'tab',
    'aria-selected': String(raporSekmesi === id),
    'aria-pressed': String(raporSekmesi === id),
    metin: ad,
    onclick: () => { raporSekmesi = id; ciz(kok); },
  }))));

  const kategoriler = durum.meta ? durum.meta.kategoriler : [];
  const tumSatirlar = v.bolumler.flatMap(b => b.satirlar);
  const cihazKategorisi = new Map(
    durum.cihazlar.map(c => [c.id, c.kategori]));

  const seciliKat = durum.kontrolKategori || 'tum';
  const sayim = (id) => (id === 'tum'
    ? tumSatirlar.length
    : tumSatirlar.filter(
      s => cihazKategorisi.get(s.cihazId) === id).length);

  parcalar.push(el('div', {
    sinif: 'serit', role: 'group', 'aria-label': 'Kategori filtresi',
  }, [
    el('span', { sinif: 'etiket', metin: 'Kategori' }),
    ...kategoriler.map(k => el('button', {
      type: 'button', sinif: 'cip',
      'aria-pressed': String(seciliKat === k.id),
      title: k.tipler,
      onclick: () => ata({ kontrolKategori: k.id }),
    }, [
      el('span', { metin: k.ad }),
      el('span', { sinif: 'n', metin: String(sayim(k.id)) }),
    ])),
  ]));

  const satirlar = seciliKat === 'tum'
    ? tumSatirlar
    : tumSatirlar.filter(s => cihazKategorisi.get(s.cihazId) === seciliKat);

  const sonuclar = satirlar.map(s => temelDegerlendir(s, v.sutunlar));
  const gecen = sonuclar.filter(s => s.gecti).length;
  const erisim = sonuclar.filter(s => s.sorunlar.some(
    x => ['erisim', 'giris', 'okunmadi'].includes(x.kod))).length;
  const ip = sonuclar.filter(s => s.sorunlar.some(x => x.kod === 'ip')).length;
  const sip = sonuclar.filter(s => s.sorunlar.some(x => x.kod === 'sip')).length;

  parcalar.push(el('div', { sinif: 'dog-olcut' }, [
    el('span', { sinif: 'etiket', metin: 'Temel kontrol ölçütleri' }),
    el('span', { metin: 'Erişim · IP · SIP dahili numarası' }),
  ]));
  parcalar.push(el('div', { sinif: 'dog-ozet-izgara' }, [
    ozetKarti('Temel kontrolleri geçen', gecen, 'yesil',
      `Toplam ${satirlar.length} cihaz`),
    ozetKarti('Erişim sorunu', erisim, erisim ? 'kirmizi' : 'yesil',
      'Yanıt alınamayan veya giriş bilgisi gereken cihazlar'),
    ozetKarti('IP sapması', ip, ip ? 'kirmizi' : 'yesil', 'Beklenen ve okunan IP'),
    ozetKarti('SIP sapması', sip, sip ? 'kirmizi' : 'yesil',
      'SIP kullanan cihazlarda'),
  ]));

  if (raporSekmesi === 'excel') {
    parcalar.push(...excelOnizlemesi(satirlar, v));
  } else {
    parcalar.push(el('div', { sinif: 'bolum-basi' }, [
      el('div', {}, [
        el('h3', { metin: 'İncelenecek cihazlar' }),
      ]),
      el('span', { sinif: 'rozet', metin: `${satirlar.length - gecen} cihaz` }),
    ]));
    parcalar.push(sapmaTablosu(satirlar, v.sutunlar));
  }

  doldur(kok, parcalar);
  sayaciKur();
}

// Excel'i üretmeden önce verinin yaşını gösterir.
//
// Gerekçe sahadan: dosya üretildiğinde kimse hangi ana ait olduğunu
// bilmiyordu. On dakika önce okunmuş bir görüntüden Excel çıkarmak,
// o dosyayı imzalayan kişiye yanlış bir "şu an böyle" belgesi veriyor.
// Onay kutusu bu yüzden bilgi kutusu değil, karar noktası: taze değilse
// önce taramayı öne çekmeyi öneriyor.
function excelOnayi() {
  const ts = sonTaramaZamani();
  const yas = ts ? Math.round(Date.now() / 1000 - ts) : null;
  const bayat = yas === null || yas > BAYAT_SN;
  const s = (durum.kontrolDurum && durum.kontrolDurum.sayilar)
    || durum.sayilar || {};

  const satir = (ad, deger, renk) => el('div', { sinif: 'ozet-satir' }, [
    el('span', { metin: ad }),
    el('span', { stil: renk ? `color:${renk}` : null, metin: String(deger) }),
  ]);

  const icerik = el('div', {}, [
    el('p', { sinif: 'aciklama' }, [
      ts
        ? `Excel son taramada okunan değerlerden oluşturulur. Tarama ${saat(ts)}'de tamamlandı.`
        : 'Bu tren setinde henüz tarama yapılmadı. Excel boş değerlerle oluşturulur.',
    ]),
    el('div', { sinif: 'ozet-kutu' }, [
      satir('Verinin yaşı', ts ? `${tazelik(ts)} önce` : YOK,
        bayat ? 'var(--turuncu)' : 'var(--yesil)'),
      satir('Erişilebilir', `${s.basarili ?? 0}`, 'var(--yesil)'),
      satir('Giriş bilgisi gerekli', `${s.erisimBekleyen ?? 0}`, 'var(--turuncu)'),
      satir('İncelenecek', `${s.hatali ?? 0}`, 'var(--kirmizi)'),
    ]),
    bayat ? el('p', {
      sinif: 'uyari', stil: 'margin-top:12px',
      metin: 'Veri güncelliğini yitirmiş olabilir. Dosyayı oluşturmadan '
        + 'önce yeniden tarama yapmak daha güvenilir bir sonuç verir.',
    }) : el('p', {
      sinif: 'bilgi', stil: 'margin-top:12px',
      metin: 'Veri güncel. Dosya son taramanın sonuçlarını yansıtır.',
    }),
  ]);

  const uret = async () => {
    diyalog.kapat();
    try {
      const y = await api.excel(durum.setNo);
      ata({ kuyrukAcik: true, acikIs: y.id });
      basari('Excel oluşturma işlemi kuyruğa alındı');
    } catch (e) { hata(e.message); }
  };

  diyalog.ac({
    baslik: 'Excel oluştur',
    icerik,
    eylemler: [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Önce tara',
        disabled: durum.aktifTarama,
        title: durum.aktifTarama
          ? 'Tarama zaten sürüyor' : 'Taramayı öne çek, Excel\'i sonra üret',
        onclick: () => { diyalog.kapat(); taramayiOneCek(); },
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil',
        metin: bayat ? 'Yine de oluştur' : 'Excel oluştur',
        onclick: uret,
      }),
    ],
  });
}

// Bir hücrenin yazı rengi ve ipucu metni.
//
// Renk hücrenin ne anlattığına göre seçilir: beklenen (şablon) değerleri
// turuncu, cihazdan okunan değerler beklenenle karşılaştırılıp yeşil ya da
// kırmızı, erişilebilirlik yeşil/kırmızı. Karşılaştıracak beklenen değer
// yoksa eski nötr renkler korunur.
function hucreVurgu(ad, hucre, degerler) {
  const deger = hucre.deger === null || hucre.deger === undefined
    ? '' : String(hucre.deger);
  if (deger === '') return { renk: 'var(--cok-soluk)', ipucu: 'Henüz okunmadı' };

  if (ad.startsWith('Beklenen')) {
    return { renk: 'var(--turuncu)', ipucu: `${deger} — beklenen değer` };
  }

  if (ad === 'Durum Açıklaması') {
    const aktif = sadelestir(deger) === 'aktif';
    return {
      renk: aktif ? 'var(--yesil)' : 'var(--kirmizi)',
      ipucu: aktif ? 'Cihaza erişildi' : 'Cihaza erişilemedi',
    };
  }

  const beklenen = String(degerler.get(KARSILASTIR[ad]) || '');
  if (beklenen) {
    return sadelestir(deger) === sadelestir(beklenen)
      ? { renk: 'var(--yesil)', ipucu: `${deger} — beklenenle aynı` }
      : { renk: 'var(--kirmizi)', ipucu: `Beklenen: ${beklenen} · Okunan: ${deger}` };
  }

  return {
    renk: hucre.kaynak === 'okuma' ? 'var(--metin)' : 'var(--acik)',
    ipucu: deger,
  };
}

function satirCiz(satir, sutunlar, kolon) {
  // Okunan hücreyi beklenen hücreyle karşılaştırabilmek için satırın
  // değerlerini sütun başlığına göre indeksliyoruz.
  const degerler = new Map();
  satir.hucreler.forEach((h, i) => {
    if (!h.na && sutunlar[i]) degerler.set(sutunlar[i].ad, h.deger);
  });

  return el('button', {
    type: 'button', sinif: 'tablo-satir',
    stil: `--tablo-kolon:${kolon}`,
    veri: { durum: satir.durum },
    title: `${satir.ad} · ${satir.ip} — ${satir.aciklama}`,
    onclick: () => { if (satir.cihazId) detay.ac(satir.cihazId); },
  }, satir.hucreler.map((h, i) => {
    if (h.na) {
      // Şablonda gri boyanmış hücre: bu cihaz türünde geçersiz alan.
      // Metin yazmıyoruz — 23 sütunun yarısında "N/A" görmek tabloyu
      // okunmaz hale getiriyordu. Gri zemin zaten anlamı taşıyor,
      // açıklama ipucu metninde ve lejantta duruyor.
      return el('span', {
        sinif: 'na-hucre', title: 'Bu cihaz türünde kullanılmıyor',
        'aria-label': 'Bu cihaz türünde kullanılmıyor',
      });
    }
    const bos = h.deger === '' || h.deger === null;
    if (i === 0) {
      // İlk sütun satırın durum rengini de taşısın
      return el('span', {
        stil: 'display:flex;align-items:center;gap:7px;min-width:0',
      }, [
        el('span', {
          sinif: 'nokta', veri: { durum: satir.durum }, 'aria-hidden': 'true',
        }),
        el('span', {
          sinif: 'mono kirp', stil: 'font-size:11px',
          metin: bos ? YOK : String(h.deger),
        }),
      ]);
    }
    const ad = sutunlar[i] ? sutunlar[i].ad : '';
    const { renk, ipucu } = hucreVurgu(ad, h, degerler);
    return el('span', {
      sinif: 'mono kirp',
      stil: `font-size:11px;color:${renk}`,
      title: `${ad}${ad ? ' — ' : ''}${ipucu}`,
      metin: bos ? YOK : String(h.deger),
    });
  }));
}
