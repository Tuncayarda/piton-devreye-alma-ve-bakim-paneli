// Konfigürasyon ekranı: cihazdaki değer ↔ hedef değer.
//
// "Cihazdaki değer" sütunu okunmadıysa boş (—) kalır. Hedef değer
// bellekte tutulur; hiçbir dosyaya yazılmaz. Bu ekranda parola alanı
// yoktur ve olamaz.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger } from '../core/bicim.js';

const KOLON = 'minmax(160px,1.1fr) minmax(130px,1fr) minmax(130px,1fr) 120px';

const SONUC_ETIKET = {
  uyuyor: ['Uyuşuyor', 'yesil'],
  farkli: ['Farklı', 'turuncu'],
  okunamadi: ['Okunamadı', 'kirmizi'],
  hedef_yok: ['Hedef yok', 'soluk'],
};

const yerel = { cihazId: null, hataMetni: '', kimlikGerek: false };

function hedefCihazlar() {
  const g = serit.gecerliGrup('cfg');
  return g ? serit.eslesen(g) : [];
}

export async function tazele() {
  const liste = hedefCihazlar();
  if (!liste.length) { ata({ cfgDurum: null }); return; }
  if (!liste.some(c => c.id === yerel.cihazId)) yerel.cihazId = liste[0].id;
  try {
    const y = await api.konfig(durum.setNo, yerel.cihazId);
    yerel.hataMetni = y.hata || '';
    yerel.kimlikGerek = !!y.kimlik;
    ata({ cfgDurum: y });
  } catch (e) {
    yerel.hataMetni = e.message;
    ata({ cfgDurum: { cihazId: yerel.cihazId, satirlar: [] } });
  }
}

export function ciz(kok) {
  const liste = hedefCihazlar();
  const veri = durum.cfgDurum;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'Konfigürasyon' })]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Cihazdan Çek',
        disabled: !liste.length, onclick: tazele,
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Gruba Uygula',
        disabled: !liste.length, onclick: uygula,
      }),
    ]),
  ]));

  parcalar.push(serit.ciz('cfg', () => { yerel.cihazId = null; tazele(); }));

  if (!liste.length) {
    parcalar.push(el('p', {
      sinif: 'bilgi', stil: 'margin-top:16px',
      metin: 'Bu grupta konfigüre edilebilir cihaz yok.',
    }));
    doldur(kok, parcalar);
    return;
  }

  parcalar.push(el('div', {
    stil: 'display:flex;align-items:center;gap:10px;margin:14px 0;flex-wrap:wrap',
  }, [
    el('span', { sinif: 'etiket', metin: 'Cihaz' }),
    el('select', {
      sinif: 'alan', stil: 'width:auto;min-width:220px',
      onchange: (e) => { yerel.cihazId = e.target.value; tazele(); },
    }, liste.map(c => el('option', {
      value: c.id, selected: c.id === yerel.cihazId ? true : null,
      metin: `${c.ad} · ${c.ip}`,
    }))),
  ]));

  if (yerel.hataMetni) {
    parcalar.push(el('p', {
      sinif: yerel.kimlikGerek ? 'bilgi' : 'uyari',
      metin: yerel.hataMetni
        + (yerel.kimlikGerek
          ? ' — kilit menüsünden kullanıcı adı/parola girin.' : ''),
    }));
  }

  const satirlar = (veri && veri.satirlar) || [];
  parcalar.push(el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:700px' }, [
      el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
        ['Alan', 'Cihazdaki değer', 'Hedef değer', 'Sonuç']
          .map(b => el('span', { metin: b }))),
      ...(satirlar.length ? satirlar.map(satirCiz)
        : [el('div', {
            sinif: 'tablo-bos',
            metin: 'Cihazdan değer okunamadı — "Cihazdan Çek" ile deneyin',
          })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

function satirCiz(f) {
  const [etiket, renk] = SONUC_ETIKET[f.sonuc] || ['—', 'soluk'];
  return el('div', { sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}` }, [
    el('span', { sinif: 'mono', stil: 'font-size:12px', metin: f.etiket }),
    el('span', { sinif: 'mono orta kirp', stil: 'font-size:12px', metin: deger(f.mevcut) }),
    f.duzenlenebilir
      ? el('input', {
          sinif: 'alan', stil: 'padding:5px 8px;font-size:12px',
          value: f.hedef, 'aria-label': `${f.etiket} hedef değeri`,
          onchange: async (e) => {
            try {
              const y = await api.konfigHedef(
                durum.setNo, yerel.cihazId, f.alan, e.target.value);
              ata({ cfgDurum: y });
            } catch (err) { hata(err.message); }
          },
        })
      : el('span', { sinif: 'mono acik kirp', stil: 'font-size:12px', metin: deger(f.hedef) }),
    el('span', {
      stil: `font-family:var(--f-baslik);font-weight:600;font-size:12.5px;`
        + `letter-spacing:.08em;text-transform:uppercase;color:var(--${renk})`,
      metin: etiket,
    }),
  ]);
}

async function uygula() {
  const g = serit.gecerliGrup('cfg');
  if (!g) return;
  try {
    const y = await api.konfigUygula(durum.setNo, g.ad, null);
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Konfigürasyon işi zaten kuyrukta');
    else basari('Konfigürasyon kuyruğa alındı');
  } catch (e) { hata(e.message); }
}
