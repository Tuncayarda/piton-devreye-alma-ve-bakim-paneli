// MQTT İzleme — broker'a abone olup gelen mesajları gösterir.
//
// Dinleyici yalnız kullanıcı başlattığında çalışır ve tampon sabit
// boyutludur; ekran açık kaldıkça bellek büyümez.

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { hata } from '../parts/bildirim.js';
import { saat } from '../core/bicim.js';

export async function tazele() {
  try {
    ata({ mqttDurum: await api.mqtt() });
  } catch {
    ata({ mqttDurum: null });
  }
}

export function ciz(kok) {
  const v = durum.mqttDurum || { calisiyor: false, topicler: [], mesajlar: [] };
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    el('div', {}, [el('h2', { metin: 'MQTT İzleme' })]),
    el('div', { sinif: 'eylemler' }, [
      el('span', {
        sinif: 'rozet',
        stil: v.calisiyor
          ? 'border-color:var(--yesil-zayif);color:var(--yesil)'
          : 'color:var(--soluk)',
        metin: v.calisiyor
          ? `${v.broker || ''} · Bağlı · ${v.toplam || 0} mesaj`
          : 'Bağlı değil',
      }),
      el('button', {
        type: 'button',
        sinif: v.calisiyor ? 'btn' : 'btn btn-birincil',
        metin: v.calisiyor ? 'Durdur' : 'Başlat',
        onclick: async () => {
          try {
            ata({ mqttDurum: v.calisiyor
              ? await api.mqttDur()
              : await api.mqttBasla(durum.setNo) });
          } catch (e) { hata(e.message); }
        },
      }),
    ]),
  ]));

  if (v.hata) parcalar.push(el('p', { sinif: 'uyari', metin: v.hata }));

  parcalar.push(el('div', { sinif: 'mqtt-izgara' }, [
    el('div', { sinif: 'kart' }, [
      el('div', { sinif: 'etiket', stil: 'margin-bottom:10px', metin: "Topic'ler" }),
      ...(v.topicler.length ? v.topicler.map(t => el('div', {
        stil: 'display:flex;align-items:center;gap:8px;padding:7px 0;'
          + 'border-bottom:1px solid var(--cizgi-hafif)',
      }, [
        el('span', { sinif: 'nokta', stil: 'background:var(--accent)', 'aria-hidden': 'true' }),
        el('span', { sinif: 'mono kirp', stil: 'flex:1;font-size:11px', metin: t.ad }),
        el('span', { sinif: 'mono soluk', stil: 'font-size:10px', metin: String(t.n) }),
      ])) : [el('div', {
        sinif: 'mono soluk', stil: 'font-size:11px',
        metin: 'Henüz mesaj gelmedi',
      })]),
    ]),

    el('div', { sinif: 'akis' }, [
      el('div', {
        stil: 'display:flex;align-items:center;gap:10px;margin-bottom:11px',
      }, [
        el('span', { sinif: 'etiket', metin: 'Akış' }),
        el('span', { stil: 'flex:1' }),
        el('span', {
          sinif: 'mono soluk', stil: 'font-size:10px',
          metin: `${(v.mesajlar || []).length} satır gösteriliyor`,
        }),
      ]),
      ...((v.mesajlar || []).length ? v.mesajlar.map(m => el('div', {
        sinif: 'akis-satir',
      }, [
        el('span', { sinif: 'soluk', metin: saat(m.zaman) }),
        el('span', { stil: 'color:var(--accent)', sinif: 'kirp', metin: m.topic }),
        el('span', { sinif: 'govde', title: m.govde, metin: m.govde }),
      ])) : [el('div', {
        sinif: 'mono soluk', stil: 'font-size:11px',
        metin: v.calisiyor ? 'Mesaj bekleniyor…' : 'Dinleyici kapalı',
      })]),
    ]),
  ]));

  doldur(kok, parcalar);
}
