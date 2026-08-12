// "Hedef grup" şeridi — IP atama, konfigürasyon, firmware ve kontrol
// listesi ekranlarının tepesindeki ortak seçici.
import { el } from '../core/dom.js';
import { durum, ata } from '../core/durum.js';

export function gruplar(op) {
  const meta = durum.meta;
  if (!meta) return [];
  return meta.gruplar.filter(g => g.ops.split(' ').includes(op));
}

export function eslesen(g) {
  if (g.tip === '*') return durum.cihazlar.filter(c => c.type !== 'Switch');
  return durum.cihazlar.filter(
    c => c.type === g.tip && (!g.alt || (c.subtype || '') === g.alt));
}

// Seçili grup bu işlemde geçerli değilse ilk geçerli gruba düşer.
export function gecerliGrup(op) {
  const liste = gruplar(op);
  if (!liste.length) return null;
  return liste.find(g => g.ad === durum.hedefGrup) || liste[0];
}

// İşlem ekranlarında hedef tek seçimdir. Yatay çip şeridi çok yer kaplıyor
// ve seçenek sayısı arttığında kaydırma gerektiriyordu; kompakt açılır liste
// aynı kapsamı daha sakin ve doğrudan gösterir. Cihaz sayıları seçenek adına
// eklenmez: sayı, işlemin kendi tablosunda zaten görünür.
export function secici(op, secilince = () => {}) {
  const liste = gruplar(op);
  const aktif = gecerliGrup(op);
  return el('label', { sinif: 'hedef-secici' }, [
    el('span', { sinif: 'etiket', metin: 'Cihaz türü' }),
    el('select', {
      sinif: 'alan',
      'aria-label': 'Hedef cihaz türü',
      disabled: !liste.length,
      onchange: (e) => {
        const grup = liste.find(g => g.ad === e.target.value);
        if (!grup) return;
        // Seçim bitti: odak listeden çıkarılır. Odaktaki bir liste açık
        // sayıldığı ve çizimi beklettiği için (bkz. app.odakAcilirListede)
        // bu olmadan yeni grubun alanları ekrana gelmiyordu.
        e.target.blur();
        ata({ hedefGrup: grup.ad });
        secilince(grup);
      },
    }, liste.map(g => el('option', {
      value: g.ad,
      selected: aktif && aktif.ad === g.ad ? true : null,
      metin: g.ad,
    }))),
  ]);
}

// Şerit sığmadığında sağ kenar soluyor (bkz. .serit maskesi). Sonuna
// gelindiğinde ya da hepsi sığdığında solmaya gerek yok; bunu ancak
// ölçerek bilebiliyoruz.
function kenariIsaretle(kap) {
  const guncelle = () => {
    // Ölçüm ancak öğe sayfaya girdikten sonra anlamlı; çağrıldığı yerde
    // henüz bağlı değil.
    if (!kap.isConnected) return;
    const son = kap.scrollLeft + kap.clientWidth >= kap.scrollWidth - 2;
    kap.dataset.son = son ? '1' : '0';
  };
  kap.addEventListener('scroll', guncelle, { passive: true });
  // requestAnimationFrame değil: pencere boyanmıyorken (arka planda,
  // simge durumunda) hiç çalışmıyor ve şerit sonsuza kadar solmuş kalıyor.
  setTimeout(guncelle, 0);
  return kap;
}

// `secenekler.coklu` verilirse şerit çoklu seçim yapar: seçili adlar
// çağıran ekranda tutulur (durum.hedefGrup tek ad taşıdığı için diğer
// ekranların davranışı değişmez), tıklama yalnız geri çağrıya gider.
export function ciz(op, secilenler = () => {}, secenekler = {}) {
  const { coklu = false, secili = null } = secenekler;
  const liste = gruplar(op);
  const aktif = gecerliGrup(op);
  const secildiMi = (g) => (coklu
    ? !!secili && secili.includes(g.ad)
    : !!aktif && aktif.ad === g.ad);
  return kenariIsaretle(el('div', {
    sinif: 'serit', role: 'group',
    'aria-label': coklu ? 'Hedef cihaz grupları' : 'Hedef cihaz grubu',
  }, [
    el('span', { sinif: 'etiket', metin: coklu ? 'Hedef gruplar' : 'Hedef grup' }),
    ...liste.map(g => el('button', {
      type: 'button', sinif: 'cip',
      'aria-pressed': String(secildiMi(g)),
      onclick: () => {
        if (!coklu) ata({ hedefGrup: g.ad });
        secilenler(g);
      },
    }, [
      el('span', { metin: g.ad }),
      el('span', { sinif: 'n', metin: String(eslesen(g).length) }),
    ])),
  ]));
}
