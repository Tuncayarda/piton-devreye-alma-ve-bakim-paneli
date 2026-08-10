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
import { YOK, saat, tazelik } from '../core/bicim.js';

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
      el('h2', { metin: 'Kontrol Listesi' }),
      // Liste kendiliğinden tazeleniyor; ne kadar taze olduğu burada
      // yazar. Excel onayı da aynı damgayı gösterir.
      el('div', {
        id: 'dog-tazelik', sinif: 'sayfa-alt dog-tazelik',
        veri: { okuma: sonTaramaZamani() || 0 },
      }),
    ]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Yeniden Oku',
        disabled: durum.aktifTarama,
        // Üst bardaki "Güncelle" ile aynı iş: sıradaki taramayı öne
        // çeker, kuyruk paneli açılmaz, haber kuyruk düğmesinde belirir.
        onclick: () => taramayiOneCek(),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Excel Üret',
        onclick: excelOnayi,
      }),
    ]),
  ]));

  if (!v) {
    parcalar.push(el('p', {
      sinif: 'bilgi', metin: 'Şablon önizlemesi alınamadı.',
    }));
    doldur(kok, parcalar);
    return;
  }

  // ── kategori filtresi ──
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

  // ── tablo ──
  const kolon = v.sutunlar
    .map(s => `${GENISLIK[s.ad] || VARSAYILAN_GENISLIK}px`)
    .join(' ');
  const enAz = v.sutunlar
    .reduce((t, s) => t + (GENISLIK[s.ad] || VARSAYILAN_GENISLIK), 0)
    + v.sutunlar.length * 10;

  parcalar.push(el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: `--tablo-min:${enAz}px` }, [
      el('div', {
        sinif: 'tablo-basi', stil: `--tablo-kolon:${kolon}`, role: 'row',
      }, v.sutunlar.map(s => el('span', {
        sinif: 'kirp', title: s.ad, metin: s.ad,
      }))),
      ...(satirlar.length
        ? satirlar.map(s => satirCiz(s, v.sutunlar, kolon))
        : [el('div', {
            sinif: 'tablo-bos', metin: 'Bu kategoride cihaz yok',
          })]),
    ]),
  ]));

  parcalar.push(el('div', { sinif: 'lejant' }, [
    el('span', {}, [el('i', { stil: 'background:var(--yesil)' }),
      'Okundu ve doğrulandı']),
    el('span', {}, [el('i', { stil: 'background:var(--turuncu)' }),
      'Kimlik bekliyor']),
    el('span', {}, [el('i', { stil: 'background:var(--kirmizi)' }), 'Hata']),
    el('span', {}, [el('i', { stil: 'background:var(--turuncu)' }),
      'Turuncu yazı = beklenen (şablon) değeri']),
    el('span', {}, [el('i', { stil: 'background:var(--yesil)' }),
      'Yeşil/kırmızı yazı = okunan değer beklenenle uyuyor / uymuyor']),
    el('span', {}, [el('i', { stil: 'background:#2a3339' }),
      'Gri kutu = bu cihaz türünde kullanılmıyor']),
    el('span', {}, [el('i', {
      stil: 'background:transparent;border:1px solid var(--cizgi-kuvvetli)',
    }), '— henüz okunmadı']),
    el('span', {
      stil: 'margin-left:auto',
      metin: `${satirlar.length} satır · ${v.sutunlar.length} sütun`,
    }),
  ]));

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
        ? `Excel, son taramada okunan değerlerden üretilir. O tarama ${saat(ts)}'de bitti.`
        : 'Bu tren setinde henüz tarama yapılmadı; Excel boş değerlerle üretilir.',
    ]),
    el('div', { sinif: 'ozet-kutu' }, [
      satir('Verinin yaşı', ts ? `${tazelik(ts)} önce` : YOK,
        bayat ? 'var(--turuncu)' : 'var(--yesil)'),
      satir('Doğrulanan', `${s.basarili ?? 0}`, 'var(--yesil)'),
      satir('Erişim bekleyen', `${s.erisimBekleyen ?? 0}`, 'var(--turuncu)'),
      satir('Yanıt vermeyen', `${s.hatali ?? 0}`, 'var(--kirmizi)'),
    ]),
    bayat ? el('p', {
      sinif: 'uyari', stil: 'margin-top:12px',
      metin: 'Bu veri tazeliğini yitirmiş olabilir. Cihazlar o zamandan '
        + 'beri yeniden başlatılmış ya da kablosu çekilmiş olabilir; '
        + 'önce taramayı öne çekmek daha doğru bir dosya üretir.',
    }) : el('p', {
      sinif: 'bilgi', stil: 'margin-top:12px',
      metin: 'Veri taze — dosya cihazların şu anki durumunu yansıtır.',
    }),
  ]);

  const uret = async () => {
    diyalog.kapat();
    try {
      const y = await api.excel(durum.setNo);
      ata({ kuyrukAcik: true, acikIs: y.id });
      basari('Excel işi kuyruğa alındı');
    } catch (e) { hata(e.message); }
  };

  diyalog.ac({
    baslik: 'Excel üret',
    icerik,
    eylemler: [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Önce Güncelle',
        disabled: durum.aktifTarama,
        title: durum.aktifTarama
          ? 'Tarama zaten sürüyor' : 'Taramayı öne çek, Excel\'i sonra üret',
        onclick: () => { diyalog.kapat(); taramayiOneCek(); },
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil',
        metin: bayat ? 'Yine de Üret' : 'Excel Üret',
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
