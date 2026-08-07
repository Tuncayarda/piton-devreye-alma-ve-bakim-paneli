// Cihaz detay çekmecesi (sağdan açılır).
//
// Okunmamış alanlar için "—", o cihazda geçerli olmayan alanlar için
// "Bu cihazda uygulanmıyor" yazılır. İkisi aynı şey değildir.

import { el, doldur, odakTuzagi, $ } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import { deger, DURUM_ETIKET, DOGRULAMA_ETIKET, saat, YOK } from '../core/bicim.js';
import { kimlikDiyalogu } from './kilit.js';
import { hata } from './bildirim.js';

let coz = null;

export function kapat() {
  if (coz) { coz(); coz = null; }
  doldur($('#detay-yuva'), []);
  if (durum.detayId) ata({ detayId: null });
}

export async function ac(cihazId) {
  ata({ detayId: cihazId });
  try {
    const veri = await api.cihaz(durum.setNo, cihazId);
    ciz(veri);
  } catch (e) {
    hata(e.message);
    ata({ detayId: null });
  }
}

function blok(baslik, kaynak, satirlar) {
  return el('div', { sinif: 'detay-blok' }, [
    el('div', { sinif: 'basi' }, [
      el('h4', { metin: baslik }),
      el('span', { stil: 'flex:1' }),
      el('span', { sinif: 'etiket', metin: kaynak || '' }),
    ]),
    ...satirlar.map(([ad, dgr, renk]) => el('div', { sinif: 'detay-satir' }, [
      el('span', { sinif: 'ad', metin: ad }),
      el('span', {
        sinif: 'deger',
        stil: renk ? `color:var(--${renk})` : null,
        metin: deger(dgr),
      }),
    ])),
  ]);
}

function ciz(c) {
  const s = c.sonuc || {};
  const a = s.alanlar || {};
  const yb = c.yontemBilgi || {};
  const renk = { yesil: 'yesil', turuncu: 'turuncu', kirmizi: 'kirmizi', gri: 'soluk' }[s.durum];

  const eylemler = [
    el('button', {
      type: 'button', sinif: 'btn btn-birincil', metin: 'Durumu Oku',
      onclick: async () => {
        try {
          await api.yenile(durum.setNo, [c.id]);
          await ac(c.id);
        } catch (e) { hata(e.message); }
      },
    }),
  ];
  if (s.dogrulama === 'kimlik_bekliyor') {
    eylemler.push(el('button', {
      type: 'button', sinif: 'btn', metin: 'Kimlik Gir',
      onclick: () => kimlikDiyalogu({
        ...c, aciklama: s.aciklama, kimlikGrubu: c.kimlikGrubu,
      }),
    }));
  }
  if (c.kimlikVar) {
    eylemler.push(el('button', {
      type: 'button', sinif: 'btn', metin: 'Kimliği Unut',
      onclick: async () => {
        try {
          await api.kimlikUnut(durum.setNo, c.id);
          await ac(c.id);
        } catch (e) { hata(e.message); }
      },
    }));
  }

  // Compartment LCD'de "Versiyon" Android build kimliği değil, panel
  // uygulamasının sürümüdür (dumpsys package … versionName). Paket adı ve
  // güncelleme tarihi olmadan hangi sürümün nereden geldiği belli olmuyor.
  const androidSatir = c.yontem === 'adb' ? [
    ['Uygulama', a.paket],
    ['Sürüm kodu', a.surumKodu],
    ['Hedef SDK', a.hedefSdk],
    ['Son güncelleme', a.guncelleme],
  ] : [];

  const kimlikBloku = blok('Kimlik', `Proje listesi + ${yb.kod || c.yontem}`, [
    ['Cihaz İsmi', c.ad],
    ['Type / SubType', c.tipEtiket],
    ['Versiyon', a.surum, a.surum ? 'yesil' : null],
    ...androidSatir,
    ['Model', a.model],
    ['Cihaz Numarası', a.seri],
    ['Durum', DURUM_ETIKET[s.durum] || YOK, renk],
    ['Doğrulama', DOGRULAMA_ETIKET[s.dogrulama] || YOK, renk],
    ['Açıklama', s.aciklama],
    ['Çalışma Süresi', a.calisma],
  ]);

  const agBloku = blok('Ağ', `Şablon ${c.ipSablonu}`, [
    ['IP Şablonu', c.ipSablonu],
    ['Beklenen IP', c.ip],
    ['Bağlantı', s.durum === 'yesil' ? c.ip : 'Doğrulanmış bağlantı yok',
      s.durum === 'yesil' ? 'yesil' : 'soluk'],
    ['Switch · Port', c.portEtiket],
    ['MAC', a.mac],
    ['Ağ / Zaman', a.agZaman],
    ['Saat Dilimi', a.saatDilimi],
  ]);

  const sipSatir = c.pbxExtension ? [
    ['SIP PBX IP (proje)', c.piscuIp],
    ['Beklenen SIP Dahili No', c.pbxExtension],
    ['Cihazın bildirdiği', a.sipDahili,
      a.sipDahili ? (String(a.sipDahili) === String(c.pbxExtension)
        ? 'yesil' : 'kirmizi') : null],
    ['Cihazın bildirdiği PBX', a.sipPbx],
    // ADB cihazlarında kayıt durumu uygulamanın kendi günlüğünden gelir;
    // PBX'e sorulmuş bir doğrulama değildir (bkz. MIMARI §12).
    ...(c.yontem === 'adb'
      ? [['SIP kayıt durumu (cihaz günlüğü)', a.sipKayit,
          String(a.sipKayit || '').startsWith('registered') ? 'yesil'
            : (a.sipKayit ? 'kirmizi' : null)],
         // Numara cihazın günlüğünden mi yoksa broker'daki duyurudan mı
         // geldi? İkisi aynı değeri vermeli; kaynağı gizlemek, cihazdan
         // okunmamış bir değeri okunmuş gibi gösterirdi.
         ['Dahili numaranın kaynağı', a.sipDahiliKaynak],
         ['PBX adresinin kaynağı', a.sipPbxKaynak]]
      // Gain ses seviyesinden ayrı bir ayardır (cihazda speakerGain /
      // micGain); ikisi aynı satırda gösterilmez. "SIP Arama No" cihazın
      // çağrı başlattığı hedeftir, kendi dahilisi değil.
      : [['SIP Arama No (cihazın aradığı)', a.sipArama],
         ['Hoparlör Ses Seviyesi', a.hoparlor],
         ['Mikrofon Ses Seviyesi', a.mikrofon],
         ['Hoparlör Gain', a.hoparlorGain],
         ['Mikrofon Gain', a.mikrofonGain]]),
  ] : [
    ['Okuma yöntemi', yb.kod || c.yontem],
    ['Yol', yb.yol],
    ['Periyot', yb.periyot ? `${yb.periyot} sn` : 'Elle'],
    ['Kimlik gerekiyor mu', yb.kimlik_ister ? 'Evet' : 'Hayır'],
    ['Bellekte kimlik', c.kimlikVar ? 'Var (yalnız bu oturum)' : 'Yok'],
  ];

  const kutu = el('div', { sinif: 'detay', role: 'dialog', 'aria-modal': 'true',
    'aria-label': `${c.ad} ayrıntıları` }, [
    el('div', { stil: 'display:flex;align-items:flex-start;gap:14px' }, [
      el('div', { stil: 'flex:1;min-width:0' }, [
        el('div', { sinif: 'ust-etiket', metin: c.tipEtiket }),
        el('h2', { stil: 'margin:5px 0 0', metin: c.ad }),
        el('div', {
          sinif: 'mono orta', stil: 'margin-top:5px;font-size:11.5px',
          metin: `${c.ip} · ${c.portEtiket}`,
        }),
      ]),
      el('button', {
        type: 'button', sinif: 'btn btn-x', 'aria-label': 'Kapat',
        onclick: kapat,
      }, ['×']),
    ]),
    el('div', { stil: 'display:flex;gap:8px;margin-top:16px;flex-wrap:wrap' }, eylemler),
    el('div', {
      sinif: 'bilgi', stil: 'margin-top:14px',
      metin: s.okumaZamani
        ? `Son okuma ${saat(s.okumaZamani)} · yöntem ${yb.kod || c.yontem}`
        : 'Bu cihaz henüz okunmadı',
    }),
    kimlikBloku,
    agBloku,
    blok(c.pbxExtension ? 'SIP' : 'Kaynak', yb.yol || '', sipSatir),
  ]);

  const perde = el('div', {
    sinif: 'perde sag',
    onclick: (e) => { if (e.target === perde) kapat(); },
  }, [kutu]);

  doldur($('#detay-yuva'), [perde]);
  if (coz) coz();
  coz = odakTuzagi(perde, kapat);
  const ilk = kutu.querySelector('button');
  if (ilk) ilk.focus();
}
