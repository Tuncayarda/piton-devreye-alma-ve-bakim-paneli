// Yazılım yükleme ekranı.
//
// Dosya seçimi: tarayıcı sanal alanında yerel dosya yolu okunamadığı için
// yol elle girilir (masaüstü penceresinde de aynı yol geçerlidir).
// Panel dosyayı kendi dizinine kopyalamaz; yalnızca yolunu tutar.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger, boyut, surumOf } from '../core/bicim.js';

const KOLON = 'minmax(180px,1.4fr) 118px 96px 96px minmax(180px,1fr)';
const yerel = { yol: '', surum: '' };

export async function tazele() {
  try {
    ata({ fwDurum: await api.firmware() });
  } catch {
    ata({ fwDurum: null });
  }
}

export function ciz(kok) {
  const g = serit.gecerliGrup('fw');
  const liste = g ? serit.eslesen(g) : [];
  const dosya = durum.fwDurum || { secili: false };
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'Yazılım Yükleme' })]),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Yüklemeyi Başlat',
        disabled: !dosya.secili || !liste.length,
        onclick: baslat,
      }),
    ]),
  ]));

  parcalar.push(serit.ciz('fw'));

  parcalar.push(el('div', {
    sinif: 'kart', stil: 'margin-top:14px;display:flex;gap:12px;'
      + 'align-items:flex-end;flex-wrap:wrap',
  }, [
    el('label', { stil: 'flex:1 1 320px' }, [
      el('span', { sinif: 'etiket', metin: 'Firmware dosyasının tam yolu' }),
      el('input', {
        sinif: 'alan', value: yerel.yol,
        placeholder: '/Users/…/intercom-1.2.6.bin',
        onchange: (e) => { yerel.yol = e.target.value.trim(); },
      }),
    ]),
    el('label', { stil: 'flex:0 1 150px' }, [
      el('span', { sinif: 'etiket', metin: 'Hedef sürüm' }),
      el('input', {
        sinif: 'alan', value: yerel.surum, placeholder: '1.2.6',
        onchange: (e) => { yerel.surum = e.target.value.trim(); },
      }),
    ]),
    el('button', {
      type: 'button', sinif: 'btn', metin: 'Dosyayı Doğrula',
      onclick: async () => {
        try {
          ata({ fwDurum: await api.firmwareDosya(yerel.yol, yerel.surum) });
          basari('Dosya seçildi');
        } catch (e) { hata(e.message); }
      },
    }),
  ]));

  parcalar.push(el('p', {
    sinif: dosya.secili ? 'bilgi' : 'uyari', stil: 'margin-top:10px',
    metin: dosya.secili
      ? `Seçili: ${dosya.ad} · ${boyut(dosya.boyut)}`
        + (dosya.surum ? ` · hedef sürüm ${dosya.surum}` : '')
      : 'Henüz dosya seçilmedi.',
  }));

  parcalar.push(el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:820px' }, [
      el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
        ['Cihaz', 'IP', 'Mevcut', 'Hedef', 'Durum']
          .map(b => el('span', { metin: b }))),
      ...(liste.length ? liste.map(c => el('div', {
        sinif: 'tablo-satir', stil: `--tablo-kolon:${KOLON}`,
      }, [
        el('span', { stil: 'display:flex;align-items:center;gap:8px;min-width:0' }, [
          el('span', { sinif: 'nokta', veri: { durum: c.sonuc.durum }, 'aria-hidden': 'true' }),
          el('span', { sinif: 'mono kirp', stil: 'font-size:12px', metin: c.ad }),
        ]),
        el('span', { sinif: 'mono acik', stil: 'font-size:11.5px', metin: c.ip }),
        el('span', { sinif: 'mono orta', stil: 'font-size:11.5px', metin: deger(surumOf(c)) }),
        el('span', {
          sinif: 'mono', stil: 'font-size:11.5px;color:var(--accent)',
          metin: deger(dosya.surum),
        }),
        el('span', {
          sinif: 'kirp', stil: 'font-size:11.5px;color:var(--orta)',
          metin: c.sonuc.durum === 'yesil'
            ? 'Yüklemeye hazır'
            : (c.sonuc.aciklama || 'Cihaz doğrulanmadı'),
        }),
      ])) : [el('div', { sinif: 'tablo-bos', metin: 'Bu grupta cihaz yok' })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

async function baslat() {
  const g = serit.gecerliGrup('fw');
  if (!g) return;
  try {
    const y = await api.firmwareYukle(durum.setNo, g.ad, null);
    ata({ kuyrukAcik: true, acikIs: y.id });
    if (y.yeni === false) bildir('Yükleme işi zaten kuyrukta');
    else basari('Yükleme kuyruğa alındı');
  } catch (e) { hata(e.message); }
}
