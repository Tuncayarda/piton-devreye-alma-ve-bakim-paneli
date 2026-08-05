// Kontrol Listesi — Excel'e yazılacak bilginin ön izlemesi.
//
// Amaç çıktının önceden görülebilmesi: sütunlar şablonun sütunlarıdır ve
// hepsi buradadır. Şablon değişirse liste de değişir; kodda ayrı bir
// kolon listesi tutulmuyor.
//
// Gri (N/A) hücre "bu cihaz türünde kullanılmıyor" demektir; "—" ise
// "henüz okunmadı". İkisi ayrı gösterilir.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import * as detay from '../parts/detay.js';
import * as kuyruk from '../parts/kuyruk.js';
import { YOK } from '../core/bicim.js';

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

export async function tazele() {
  try {
    ata({ kontrolDurum: await api.kontrol(durum.setNo) });
  } catch (e) {
    hata(e.message);
    ata({ kontrolDurum: null });
  }
}

export function ciz(kok) {
  const v = durum.kontrolDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'Kontrol Listesi' })]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Yeniden Oku',
        disabled: durum.aktifTarama,
        // Üst bardaki "Güncelle" ile aynı iş: kuyruk paneli açılmaz,
        // haber kuyruk düğmesinde belirir.
        onclick: async () => {
          try {
            const y = await api.tarama(durum.setNo);
            ata({ acikIs: y.id, aktifTarama: true });
            if (y.yeni === false) bildir('Bu set için tarama zaten sürüyor');
            else kuyruk.isaretle();
          } catch (e) { hata(e.message); }
        },
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Excel Üret',
        onclick: async () => {
          try {
            const y = await api.excel(durum.setNo);
            ata({ kuyrukAcik: true, acikIs: y.id });
            basari('Excel işi kuyruğa alındı');
          } catch (e) { hata(e.message); }
        },
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
