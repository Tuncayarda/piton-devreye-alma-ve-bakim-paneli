// Choosing and clearing the APK for a Compartment LCD run.
//
// The DOM half of the software step. Its decisions — which rows may take an
// APK, which file belongs to which device — are made in ./software.js, which
// stays free of the DOM so those rules can be tested without one. What is
// left here is the file picker, the clear button and the fields they draw.

import { el } from '../../core/dom.js';
import { api } from '../../core/api.js';
import { state, patch } from '../../core/store.js';
import { showError, showSuccess } from '../../components/toast.js';
import { fileSize } from '../../core/format.js';
import { LCD_GROUP, local } from './state.js';
import {
  deviceMapName, isCompartmentPlan, mergedSoftware, softwareDeviceIds,
  softwareFiles, softwareRows,
} from './software.js';
import { t } from '../../core/i18n.js';


export function currentPlanIs(plan, setNo) {
  return state.setNo === setNo
    && !!state.ipState && state.ipState.plan === plan
    && isCompartmentPlan(plan);
}
export function applySoftwareReply(plan, reply) {
  plan.software = mergedSoftware(plan, reply);
  patch({ ipState: { ...state.ipState } });
}
export async function pickApk(plan) {
  const ids = softwareDeviceIds(plan);
  if (!ids.length || local.apkPickerOpen) return;
  const setNo = state.setNo;
  local.apkPickerOpen = true;
  patch({ ipState: { ...state.ipState } });
  try {
    const reply = await api.firmwarePick(setNo, LCD_GROUP, ids);
    if (!currentPlanIs(plan, setNo)) return;
    if (!reply.cancelled) {
      applySoftwareReply(plan, reply);
      showSuccess(t('firmware.fileSelectedFor', { count: ids.length }));
    }
  } catch (error) {
    showError(error.message);
  } finally {
    local.apkPickerOpen = false;
    if (state.view === 'ip' && state.ipState) {
      patch({ ipState: { ...state.ipState } });
    }
  }
}
export async function removeApks(plan) {
  const ids = softwareDeviceIds(plan);
  if (!ids.length || local.apkPickerOpen) return;
  const setNo = state.setNo;
  try {
    const reply = await api.firmwareRemove(setNo, LCD_GROUP, ids);
    if (currentPlanIs(plan, setNo)) applySoftwareReply(plan, reply);
  } catch (error) {
    showError(error.message);
  }
}
export function apkFields(plan, check) {
  const rows = softwareRows(plan);
  const files = softwareFiles(plan);
  const ready = rows.filter(row => files[row.deviceId]
    && files[row.deviceId].selected).length;
  const supported = !!(plan.software && plan.software.supported
    && plan.software.extension === 'apk');

  return el('div', { class: 'ip-apk-block' }, [
    el('div', { class: 'ip-apk-head' }, [
      el('span', { class: 'label', text: t('ip.apkFiles') }),
      el('span', {
        class: ready === rows.length && rows.length
          ? 'badge ip-ready-badge' : 'badge',
        text: t('ip.apkReadyCount', { ready, count: rows.length }),
      }),
    ]),
    el('div', { class: 'ip-apk-controls' }, [
      el('div', { class: 'ip-apk-actions' }, [
        el('button', {
          type: 'button', class: 'btn btn-small btn-primary',
          text: local.apkPickerOpen ? t('firmware.selectingFile')
            : t('ip.selectApkFor', { count: rows.length }),
          title: '.apk',
          disabled: !supported || !rows.length || local.apkPickerOpen,
          onclick: () => pickApk(plan),
        }),
        el('button', {
          type: 'button', class: 'btn btn-small',
          text: t('firmware.clearTheSelections'),
          disabled: !ready || local.apkPickerOpen,
          onclick: () => removeApks(plan),
        }),
      ]),
    ]),
    el('div', { class: 'ip-apk-list' }, rows.map(row => {
      const file = files[row.deviceId] || { selected: false };
      return el('div', {
        class: 'ip-apk-row', dataset: { selected: file.selected ? '1' : '0' },
      }, [
        el('span', { class: 'mono truncate', text: deviceMapName(row) }),
        el('span', {
          class: file.selected ? 'mono truncate' : 'mono truncate text-dim',
          title: file.name || t('firmware.noFileSelectedYet'),
          text: file.selected ? file.name : t('firmware.noFileSelected'),
        }),
        el('span', {
          class: file.selected ? 'text-mid' : 'text-dim',
          text: file.selected
            ? t('firmware.readyToInstall', { size: fileSize(file.size) }) : '—',
        }),
      ]);
    })),
    check.apkError ? el('p', {
      class: 'ip-field-error ip-apk-error', role: 'alert',
      text: check.apkError,
    }) : null,
  ]);
}
