// Oturumluk işlem geçmişi.
//
// Bu görünüm yeni bir kayıt üretmez ve tarayıcı deposuna hiçbir şey yazmaz.
// Yalnız global durumdaki `isler` dizisini düzenler; uygulama kapatıldığında
// sunucunun bellek içi iş listesiyle birlikte geçmiş de kaybolur.

import { el, doldur } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';
import { YOK, IS_SONUC_ETIKET, IS_SONUC_RENK } from '../core/bicim.js';

const DEVAM_EDEN = new Set(['bekliyor', 'calisiyor']);
const SONUCLANAN = new Set(['tamam', 'iptal', 'hata']);

const DURUM_RENK = {
  bekliyor: 'gri',
  calisiyor: 'mavi',
  tamam: 'yesil',
  iptal: 'turuncu',
  hata: 'kirmizi',
};

const DURUM_METNI = {
  bekliyor: 'Sırada',
  calisiyor: 'Çalışıyor',
  tamam: 'Tamamlandı',
  iptal: 'Durduruldu',
  hata: 'Başarısız',
};

const TUR_ADI = {
  tarama: 'Sistem taraması',
  ip: 'IP atama',
  ipfab: 'Fabrika IP adresine döndürme',
  cfg: 'Cihaz ayarlarını uygulama',
  fw: 'Yazılım yükleme',
  excel: 'Excel raporu oluşturma',
};

const KOLON = 'minmax(235px,1.7fr) minmax(120px,.8fr) 105px '
  + 'minmax(125px,.8fr) minmax(210px,1.4fr) 105px';

function isAdi(j) {
  if (j.tur === 'tarama' && j.otomatik) return 'Otomatik sistem taraması';
  return TUR_ADI[j.tur] || String(j.baslik || 'İşlem').replace(
    'Konfigürasyon', 'Cihaz ayarları');
}

// Sunucudaki başlığın ilk bölümü çoğunlukla işlem türüdür. Türü yukarıda
// tutarlı bir dille yazdığımız için burada yalnız kapsamı (switch, port ya da
// cihaz sayısı) gösteririz.
function isKapsami(j) {
  const parcalar = String(j.baslik || '').split(' · ').slice(1);
  if (parcalar[0] === `Set ${j.setNo}`) parcalar.shift();
  return parcalar.join(' · ');
}

function zaman(ts) {
  if (!ts) return YOK;
  return new Date(ts * 1000).toLocaleTimeString('tr-TR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
}

function sure(j) {
  if (!j.baslama) return 'Henüz başlamadı';
  const son = j.bitis || Date.now() / 1000;
  const saniye = Math.max(0, Math.round(son - j.baslama));
  if (saniye < 60) return `${saniye} sn`;
  const dakika = Math.floor(saniye / 60);
  const kalan = saniye % 60;
  if (dakika < 60) return kalan ? `${dakika} dk ${kalan} sn` : `${dakika} dk`;
  const saat = Math.floor(dakika / 60);
  return `${saat} sa ${dakika % 60} dk`;
}

function durumMetni(j) {
  if (j.iptalIstendi && DEVAM_EDEN.has(j.durum)) return 'Durduruluyor…';
  return DURUM_METNI[j.durum] || 'Bilinmiyor';
}

function sonucMetni(j) {
  if (DEVAM_EDEN.has(j.durum)) {
    return j.asama || (j.durum === 'bekliyor'
      ? 'İşlem sırasını bekliyor' : 'İşlem yürütülüyor');
  }
  if (j.hata) return j.hata;

  const s = j.sayilar || {};
  const basarili = Number(s.basarili || 0);
  const bekleyen = Number(s.erisimBekleyen || 0);
  const hatali = Number(s.hatali || 0);
  const atlanan = Number(s.atlanan || 0);
  const toplam = Number(s.toplam || 0);
  if (!toplam) {
    if (j.durum === 'iptal') return 'İşlem tamamlanmadan durduruldu';
    if (j.durum === 'hata') return 'İşlem tamamlanamadı';
    return 'İşlem başarıyla tamamlandı';
  }

  const parcalar = [];
  const sonucEtiketi = IS_SONUC_ETIKET[j.sonuc];
  if (sonucEtiketi) parcalar.push(sonucEtiketi);
  parcalar.push(`${basarili} başarılı`);
  if (bekleyen) parcalar.push(`${bekleyen} cihaz için giriş bilgisi gerekli`);
  if (hatali) parcalar.push(`${hatali} başarısız`);
  if (atlanan) parcalar.push(`${atlanan} atlandı`);
  return parcalar.join(' · ');
}

function isSatiri(j) {
  const oran = Math.round(Number(j.ilerleme || 0) * 100);
  const kapsam = isKapsami(j);
  const renk = DURUM_RENK[j.durum] || 'gri';
  const sonucRengi = IS_SONUC_RENK[j.sonuc] || renk;
  const baslangic = j.baslama || j.olusturma;

  return el('div', {
    sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}`,
  }, [
    el('span', {
      stil: 'display:flex;flex-direction:column;gap:3px;min-width:0',
    }, [
      el('span', { sinif: 'acik', stil: 'font-size:12.5px', metin: isAdi(j) }),
      kapsam ? el('span', {
        sinif: 'mono soluk kirp', stil: 'font-size:10.5px',
        title: kapsam, metin: kapsam,
      }) : null,
      j.otomatik ? el('span', {
        sinif: 'rozet', stil: 'align-self:flex-start', metin: 'Otomatik',
      }) : null,
    ]),
    el('span', { stil: 'display:flex;align-items:center;gap:8px;min-width:0' }, [
      el('span', { sinif: 'nokta', veri: { durum: renk }, 'aria-hidden': 'true' }),
      el('span', {
        sinif: 'durum-yazi', veri: { durum: renk }, stil: 'font-size:12px',
        metin: DEVAM_EDEN.has(j.durum)
          ? `${durumMetni(j)} · %${oran}` : durumMetni(j),
      }),
    ]),
    el('span', {
      sinif: 'mono orta', stil: 'font-size:11px',
      metin: `Tren seti ${j.setNo ?? YOK}`,
    }),
    el('span', {
      stil: 'display:flex;flex-direction:column;gap:3px',
    }, [
      el('span', { sinif: 'mono acik', stil: 'font-size:11px', metin: zaman(baslangic) }),
      el('span', { sinif: 'mono soluk', stil: 'font-size:10px', metin: sure(j) }),
    ]),
    el('span', {
      sinif: 'durum-yazi', veri: { durum: sonucRengi },
      stil: 'font-size:11.5px;line-height:1.45',
      title: sonucMetni(j), metin: sonucMetni(j),
    }),
    el('button', {
      type: 'button', sinif: 'btn btn-kucuk', metin: 'Ayrıntıları aç',
      onclick: () => ata({ acikIs: j.id, kuyrukAcik: true, kilitAcik: false }),
    }),
  ]);
}

function bolum(ad, aciklama, isler, bosMetni) {
  return el('section', { stil: 'margin-top:20px' }, [
    el('div', { sinif: 'kart-basi' }, [
      el('h3', { metin: ad }),
      el('span', { sinif: 'rozet', metin: String(isler.length) }),
      el('span', { sinif: 'sayfa-alt', stil: 'margin:0', metin: aciklama }),
    ]),
    el('div', { sinif: 'tablo-sar', stil: 'margin-top:0' }, [
      el('div', { sinif: 'tablo', stil: '--tablo-min:1040px' }, [
        el('div', {
          sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}`, role: 'row',
        }, ['İşlem', 'Durum', 'Tren seti', 'Başlangıç ve süre', 'Sonuç', ''].map(
          ad_ => el('span', { metin: ad_ }))),
        ...(isler.length
          ? isler.map(isSatiri)
          : [el('div', { sinif: 'tablo-bos', metin: bosMetni })]),
      ]),
    ]),
  ]);
}

function filtreler(devam, sonuc) {
  const secenekler = [
    { id: 'tumu', ad: `Tümü (${devam.length + sonuc.length})` },
    { id: 'devam', ad: `Devam eden (${devam.length})` },
    { id: 'sonuc', ad: `Sonuçlanan (${sonuc.length})` },
  ];
  return el('div', {
    stil: 'display:flex;gap:2px;border:1px solid var(--cizgi-kuvvetli)',
    role: 'group', 'aria-label': 'Geçmiş filtresi',
  }, secenekler.map(f => el('button', {
    type: 'button', sinif: 'btn btn-kucuk',
    stil: 'border:0;letter-spacing:.02em;text-transform:none;'
      + 'font-family:var(--f-govde);font-size:12.5px'
      + (durum.gecmisFiltresi === f.id
        ? ';background:var(--accent);color:var(--derin)' : ''),
    'aria-pressed': String(durum.gecmisFiltresi === f.id),
    metin: f.ad,
    onclick: () => ata({ gecmisFiltresi: f.id }),
  })));
}

export function ciz(kok) {
  const uygun = (durum.isler || []).filter(
    j => DEVAM_EDEN.has(j.durum) || SONUCLANAN.has(j.durum));
  const sirali = uygun.slice().sort((a, b) =>
    (b.bitis || b.baslama || b.olusturma || 0)
      - (a.bitis || a.baslama || a.olusturma || 0));
  const devam = sirali.filter(j => DEVAM_EDEN.has(j.durum));
  const sonuc = sirali.filter(j => SONUCLANAN.has(j.durum));

  const parcalar = [
    el('div', { sinif: 'sayfa-basi' }, [
      el('h2', { metin: 'Geçmiş' }),
      filtreler(devam, sonuc),
    ]),
  ];

  if (durum.gecmisFiltresi !== 'sonuc') {
    parcalar.push(bolum(
      'Devam eden işlemler',
      'Kuyrukta bekleyen ve şu anda yürütülen işlemler',
      devam,
      'Şu anda devam eden işlem yok.',
    ));
  }
  if (durum.gecmisFiltresi !== 'devam') {
    parcalar.push(bolum(
      'Sonuçlanan işlemler',
      'Tamamlanan, durdurulan veya hata ile sonuçlanan işlemler',
      sonuc,
      'Bu oturumda henüz sonuçlanan işlem yok.',
    ));
  }

  doldur(kok, parcalar);
}
