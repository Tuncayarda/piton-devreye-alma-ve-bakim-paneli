// Yazılım yükleme ekranı.
//
// Dosya CİHAZ BAŞINA seçilir: her satırın kendi dosyası ve hedef sürümü
// vardır. Aynı gruptaki iki cihaz aynı dosyayı almak zorunda değil; tek
// bir "seçili dosya" tutulduğunda hangi cihaza ne gittiği görünmüyordu.
// Hepsine aynı dosya gidecekse üstteki düğme bir çağrıda gruba yazar.
//
// Beklenen dosya türü cihaza göre değişir: anons ekipmanları imaj (.bin),
// Compartment LCD uygulama paketi (.apk) alıyor. Tür sunucudan gelir,
// ekran kendi tablosunu tutmaz.
//
// Dosya seçimi işletim sisteminin kendi penceresinden yapılır: tarayıcı
// sanal alanı `<input type=file>` seçiminin gerçek yolunu vermiyor, panel
// de dosyayı kendi dizinine kopyalamıyor — yalnız yolunu tutuyor. Bunun
// "Seç" düğmesi sunucuya gider, sunucu seçiciyi açar (bkz. core/dosya.sec)
// ve dönen yolu o cihaza atar. Seçim bellekte durur, uygulama kapanınca
// gider.
//
// Yükleme yalnız yolu olan cihazlarda var; şerit zaten yalnız o grupları
// listeler, yine de sunucudan gelen `yuklenebilir` bilgisi satırda
// gösterilir. Cihazlar birbirinden bağımsız olduğu için koşu paralel
// yürür (bkz. panel_api.firmware_isi).

import { el, doldur } from '../core/dom.js';
import { api } from '../core/api.js';
import { durum, ata } from '../core/durum.js';
import * as serit from '../parts/serit.js';
import * as islemSekmeleri from '../parts/islem_sekmeleri.js';
import * as diyalog from '../parts/diyalog.js';
import { hata, basari, bildir } from '../parts/bildirim.js';
import { deger, boyut, YOK } from '../core/bicim.js';

const KOLON = 'minmax(150px,1.1fr) 112px 92px minmax(210px,1.6fr) '
  + '100px minmax(120px,.8fr)';

// Toplu alandaki hedef sürüm yalnız bir kolaylık: seçilen dosyayla
// birlikte satırlara yazılır, kendisi saklanmaz. Ekran yeniden
// çizilirken kaybolmasın diye burada duruyor.
const yerel = { topluSurum: '', seciciAcik: false };

let tazeleSurumu = 0;

function grupAdi() {
  const g = serit.gecerliGrup('fw');
  return g ? g.ad : '';
}

export async function tazele() {
  const surum = ++tazeleSurumu;
  const setNo = durum.setNo;
  try {
    const y = await api.firmware(setNo, grupAdi());
    if (surum !== tazeleSurumu || setNo !== durum.setNo) return;
    ata({ fwDurum: y });
  } catch {
    if (surum !== tazeleSurumu) return;
    ata({ fwDurum: null });
  }
}

// Sunucudan gelen satırlar cihaz listesinin kendisidir; tarama yapılmamış
// olsa da DeviceMap'ten gelirler (sürüm sütunu o zaman boş kalır).
function satirlar() {
  const veri = durum.fwDurum;
  return (veri && veri.cihazlar) || [];
}

function seciliSayisi(liste) {
  return liste.filter(c => c.dosya && c.dosya.secili).length;
}

// Gruptaki cihazların beklediği dosya türü (.bin / .apk). Şerit tek grup
// gösterdiği için pratikte tek tür oluyor; yine de karışıksa ikisi de
// yazılır — kullanıcı neyin seçileceğini baştan bilsin.
// Aynı anda kaç cihaz yüklenir — sunucudaki havuzun genişliği.
function esZamanli() {
  const veri = durum.fwDurum;
  return (veri && veri.esZamanli) || 1;
}

function turMetni(liste) {
  const turler = [...new Set(liste.filter(c => c.uzanti).map(c => c.uzanti))];
  return turler.map(u => `.${u}`).join(' / ');
}

export function ciz(kok) {
  const liste = satirlar();
  const secili = seciliSayisi(liste);
  const yuklenebilir = liste.filter(c => c.yuklenebilir).length;
  const parcalar = [];

  parcalar.push(el('div', { sinif: 'sayfa-basi' }, [
    // Başlık üç işlem ekranında da aynı: hangi ekranda olduğumuzu
    // altındaki sekme şeridi zaten söylüyor.
    el('h2', { metin: 'İşlemler' }),
    el('div', { sinif: 'eylemler' }, [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Seçimleri temizle',
        disabled: !secili,
        title: 'Bu gruptaki bütün dosya seçimlerini kaldır',
        onclick: () => seciminiSil(null),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Yüklemeyi başlat',
        disabled: !secili,
        title: secili
          ? `${secili} cihaz için yükleme işlemi kuyruğa alınır`
          : 'Önce en az bir cihaza dosya seçin',
        onclick: baslat,
      }),
    ]),
  ]));

  parcalar.push(islemSekmeleri.ciz());
  parcalar.push(serit.secici('fw', () => tazele()));

  // ── toplu seçim ──
  // Sahadaki olağan durum: bütün gruba aynı dosya. Bir kez seçilir;
  // satırlar yine ayrı ayrı değiştirilebilir.
  const tur = turMetni(liste);
  parcalar.push(el('section', { sinif: 'kart kose fw-toplu' }, [
    el('div', { sinif: 'fw-toplu-basi' }, [
      el('h3', { metin: 'Toplu seçim' }),
    ]),
    el('div', { sinif: 'fw-toplu-alanlar' }, [
      el('label', { sinif: 'fw-alan-dar', for: 'fw-toplu-surum' }, [
        el('span', { sinif: 'etiket', metin: 'Hedef sürüm' }),
        el('input', {
          id: 'fw-toplu-surum', sinif: 'alan', value: yerel.topluSurum,
          placeholder: '1.2.6', autocomplete: 'off', spellcheck: 'false',
          oninput: (e) => { yerel.topluSurum = e.target.value.trim(); },
        }),
      ]),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil',
        metin: yerel.seciciAcik
          ? 'Dosya seçiliyor…'
          : (yuklenebilir
            ? `Dosya seç ve ${yuklenebilir} cihaza uygula`
            : 'Dosya seç'),
        disabled: !yuklenebilir || yerel.seciciAcik,
        // Beklenen dosya türü ayrı bir açıklama satırı olarak değil,
        // seçimi yapan düğmenin ipucunda duruyor.
        title: `Bilgisayarınızın dosya penceresi açılır${tur ? ` (${tur})` : ''}`,
        onclick: () => dosyaSec(null, yerel.topluSurum),
      }),
    ]),
    el('p', {
      sinif: 'ip-alan-yardim',
      metin: 'Hedef sürüm isteğe bağlıdır; yükleme sonrasında doğrulanır.',
    }),
  ]));

  // ── cihaz başına satırlar ──
  parcalar.push(el('div', { sinif: 'tablo-sar' }, [
    el('div', { sinif: 'tablo', stil: '--tablo-min:960px' }, [
      el('div', { sinif: 'tablo-basi', stil: `--tablo-kolon:${KOLON}` },
        ['Cihaz', 'IP', 'Mevcut sürüm', 'Yüklenecek dosya', 'Hedef sürüm', 'Durum']
          .map(b => el('span', { metin: b }))),
      ...(liste.length
        ? liste.map(satirCiz)
        : [el('div', {
            sinif: 'tablo-bos',
            metin: durum.fwDurum
              ? 'Bu grupta cihaz yok' : 'Cihaz listesi yükleniyor…',
          })]),
    ]),
  ]));

  doldur(kok, parcalar);
}

function satirCiz(c) {
  const d = c.dosya || { secili: false };
  const yol = d.yol || '';
  return el('div', {
    sinif: 'tablo-satir fw-satir', stil: `--tablo-kolon:${KOLON}`,
    veri: { secili: d.secili ? '1' : '0' },
  }, [
    el('span', { sinif: 'fw-cihaz' }, [
      el('span', {
        sinif: 'nokta', veri: { durum: durumRengi(c) }, 'aria-hidden': 'true',
      }),
      el('span', { sinif: 'mono kirp', stil: 'font-size:12px', metin: c.ad }),
    ]),
    el('span', { sinif: 'mono acik', stil: 'font-size:11.5px', metin: c.ip }),
    el('span', {
      sinif: 'mono orta', stil: 'font-size:11.5px',
      metin: deger(c.mevcutSurum),
    }),
    // Dosya adı + seçme/kaldırma düğmeleri. Yol elle yazılmaz; tam yol
    // ipucu metninde durur (satırda okunacak kadar yer yok).
    c.yuklenebilir
      ? el('div', { sinif: 'fw-dosya' }, [
          el('span', {
            sinif: d.secili ? 'mono kirp' : 'mono kirp soluk',
            title: yol || 'Henüz dosya seçilmedi',
            metin: d.secili ? d.ad : 'seçilmedi',
          }),
          el('button', {
            type: 'button', sinif: 'btn btn-kucuk fw-sec-btn',
            metin: d.secili ? 'Değiştir' : 'Seç',
            disabled: yerel.seciciAcik,
            title: `${c.ad} için yüklenecek dosyayı seç`
              + (c.uzanti ? ` (.${c.uzanti})` : ''),
            onclick: () => dosyaSec([c.cihazId], d.surum || ''),
          }),
          d.secili ? el('button', {
            type: 'button', sinif: 'btn btn-x',
            metin: '×', title: 'Bu cihazın seçimini kaldır',
            'aria-label': `${c.ad} seçimini kaldır`,
            onclick: () => seciminiSil([c.cihazId]),
          }) : null,
        ])
      : el('span', {
          sinif: 'soluk', stil: 'font-size:11.5px',
          metin: 'Desteklenmiyor',
        }),
    c.yuklenebilir
      ? el('input', {
          sinif: 'alan fw-surum-alan', value: d.surum || '',
          placeholder: '—', autocomplete: 'off', spellcheck: 'false',
          'aria-label': `${c.ad} için hedef sürüm`,
          disabled: !d.secili,
          title: d.secili
            ? 'Yükleme sonrası cihazdan beklenen sürüm'
            : 'Önce bu cihaza bir dosya seçin',
          onchange: (e) => {
            if (d.secili) surumYaz([c.cihazId], e.target.value.trim());
          },
        })
      : el('span', { sinif: 'soluk', metin: YOK }),
    el('span', { sinif: 'kirp fw-durum', metin: durumMetni(c, d) }),
  ]);
}

// Satırdaki nokta cihazın son okuma durumunu gösterir; cihaz listesi
// taramadan geliyor, sunucu yanıtında yok.
function durumRengi(c) {
  const cihaz = (durum.cihazlar || []).find(x => x.id === c.cihazId);
  return (cihaz && cihaz.sonuc && cihaz.sonuc.durum) || 'gri';
}

// Dosya adı yan sütunda zaten duruyor; burada onu tekrar etmek yerine
// seçimin geri kalanı (boyut) yazılır.
function durumMetni(c, d) {
  if (!c.yuklenebilir) return 'Yükleme desteklenmiyor';
  if (!d.secili) return 'Dosya seçilmedi';
  return `${boyut(d.boyut)} · yüklemeye hazır`;
}

// ── eylemler ────────────────────────────────────────────────────────────
// `cihazlar` null ise işlem bütün gruba uygulanır (sunucu grup adından
// çözer); yoksa yalnız verilen cihazlara.

// Dosya penceresi sunucuda, yani işletim sisteminde açılır. İstek o
// pencere kapanana kadar sürer: bu sırada bütün seçme düğmeleri kilitli
// kalır, yoksa arka arkaya iki pencere açılabiliyordu.
async function dosyaSec(cihazlar, surum) {
  if (yerel.seciciAcik) return;
  yerel.seciciAcik = true;
  ata({ fwDurum: { ...durum.fwDurum } });          // düğmeleri kilitle
  try {
    const y = await api.firmwareSec(durum.setNo, grupAdi(), cihazlar, surum);
    yerel.seciciAcik = false;
    if (y.iptal) { await tazele(); return; }
    await tazele();
    basari(cihazlar
      ? 'Dosya seçildi' : `Dosya ${y.cihazSayisi} cihaz için seçildi`);
  } catch (e) {
    yerel.seciciAcik = false;
    hata(e.message);
    await tazele();
  }
}

async function surumYaz(cihazlar, surum) {
  try {
    await api.firmwareSurum(durum.setNo, grupAdi(), cihazlar, surum);
    await tazele();
  } catch (e) { hata(e.message); }
}

async function seciminiSil(cihazlar) {
  try {
    await api.firmwareSil(durum.setNo, grupAdi(), cihazlar);
    await tazele();
  } catch (e) { hata(e.message); }
}

// Yükleme cihazı yeniden başlatır ve dakikalarca sürebilir; yanlışlıkla
// basılacak bir düğme olmamalı, onay istenir.
function baslat() {
  const liste = satirlar().filter(c => c.dosya && c.dosya.secili);
  if (!liste.length) return;
  const grup = grupAdi();
  diyalog.ac({
    baslik: 'Yazılım yüklemeyi başlat',
    icerik: el('div', {}, [
      el('p', { sinif: 'aciklama' }, [
        `${liste.length} cihaza dosya yüklenecek. Yükleme tamamlandıktan sonra `
        + 'her cihazın sürümü okunarak doğrulanır. Anons ekipmanları işlem '
        + 'sırasında yeniden başlatılır.',
      ]),
      // Kaç tanesinin aynı anda yürüdüğü sunucudan gelir; kullanıcı
      // sahada "hangi cihazlar şimdi kararacak" sorusunu buradan yanıtlar.
      esZamanli() > 1 ? el('p', {
        sinif: 'bilgi', stil: 'margin-top:8px',
        metin: `Aynı anda en fazla ${esZamanli()} cihaza yükleme yapılır; `
          + 'kalan işlemler sıraya alınır.',
      }) : null,
      el('div', { sinif: 'fw-onay-liste' }, liste.map(c => el('div', {
        sinif: 'satir',
      }, [
        el('span', { sinif: 'mono kirp', metin: c.ad }),
        el('b', { sinif: 'mono kirp', metin: c.dosya.ad }),
      ]))),
    ]),
    eylemler: [
      el('button', {
        type: 'button', sinif: 'btn', metin: 'Vazgeç',
        onclick: () => diyalog.kapat(),
      }),
      el('button', {
        type: 'button', sinif: 'btn btn-birincil', metin: 'Yüklemeyi başlat',
        onclick: async () => {
          diyalog.kapat();
          try {
            const y = await api.firmwareYukle(
              durum.setNo, grup, liste.map(c => c.cihazId));
            ata({ kuyrukAcik: true, acikIs: y.id });
            if (y.yeni === false) bildir('Bu yazılım yükleme işlemi zaten kuyrukta');
            else basari('Yazılım yükleme işlemi kuyruğa alındı');
          } catch (e) { hata(e.message); }
        },
      }),
    ],
  });
}
