// Uygulama durumu (tek kaynak) ve abonelik.
//
// Bu nesnede parola YOKTUR ve olamaz: `ata()` bilinen anahtar listesi
// dışına yazmaz. Kimlik doğrulama formu değerini doğrudan API çağrısına
// verir, buraya uğratmaz.

const ANAHTARLAR = new Set([
  'rol', 'setNo', 'proje', 'gorunum', 'kategori', 'altTip', 'filtre',
  'cihazlar', 'sayilar', 'kilit', 'isler', 'acikIs', 'kuyrukAcik',
  'kilitAcik', 'duraklat', 'detayId', 'hedefGrup', 'surum', 'sonTarama',
  'aktifTarama', 'kenarAcik', 'piscuIp', 'yukleniyor', 'ipDurum',
  'cfgDurum', 'fwDurum', 'mqttDurum', 'piscuDurum', 'meta',
  'kontrolDurum', 'kontrolKategori',
]);

const _abone = new Set();

export const durum = {
  rol: null,
  setNo: 1,
  proje: null,
  meta: null,
  gorunum: 'genel',
  kategori: 'tum',
  altTip: null,
  filtre: 'tumu',
  cihazlar: [],
  sayilar: { basarili: 0, erisimBekleyen: 0, hatali: 0, okunmayan: 0 },
  kilit: [],
  isler: [],
  acikIs: null,
  kuyrukAcik: false,
  kilitAcik: false,
  duraklat: false,
  detayId: null,
  hedefGrup: 'Intercom',
  surum: '',
  sonTarama: null,
  aktifTarama: false,
  kenarAcik: false,
  piscuIp: null,
  yukleniyor: false,
  ipDurum: null,
  cfgDurum: null,
  fwDurum: null,
  mqttDurum: null,
  piscuDurum: null,
  kontrolDurum: null,
  kontrolKategori: 'tum',
};

// Hangi anahtarların değiştiği abonelere bildirilir: her değişimde bütün
// arayüzü yeniden çizmek, yalnız kuyruk panelini ilgilendiren bir tıklama
// için 42 satırlık cihaz tablosunu da baştan kurmak demekti.
export function ata(yama) {
  const degisen = [];
  for (const [k, v] of Object.entries(yama)) {
    if (!ANAHTARLAR.has(k)) {
      console.warn('durum: bilinmeyen anahtar yok sayıldı —', k);
      continue;
    }
    if (durum[k] !== v) { durum[k] = v; degisen.push(k); }
  }
  if (degisen.length) yayinla(degisen);
  return degisen.length > 0;
}

export function abone(fn) {
  _abone.add(fn);
  return () => _abone.delete(fn);
}

// `degisen` verilmezse "her şey değişmiş olabilir" demektir.
export function yayinla(degisen = null) {
  for (const fn of _abone) {
    try { fn(durum, degisen); } catch (e) { console.error(e); }
  }
}

export function cihazBul(id) {
  return durum.cihazlar.find(c => c.id === id) || null;
}

// Görünen cihazlar: kategori + alt tip + durum filtresi
export function gorunenCihazlar() {
  const kat = durum.kategori;
  const alt = durum.altTip;
  const f = durum.filtre;
  return durum.cihazlar.filter(c => {
    if (kat !== 'tum' && c.kategori !== kat) return false;
    if (alt) {
      const ad = kat === 'tum' ? c.type : (c.subtype || c.type);
      if (ad !== alt) return false;
    }
    if (f === 'aktif') return c.sonuc.durum === 'yesil';
    if (f === 'sorunlu') return c.sonuc.durum === 'kirmizi' || c.sonuc.durum === 'turuncu';
    return true;
  });
}
