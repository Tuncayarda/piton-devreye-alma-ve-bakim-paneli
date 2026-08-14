// MQTT monitoring — subscribes to the broker and shows the incoming messages.
//
// The listener only runs when the user starts it and the buffer is a fixed
// size; memory does not grow while the screen stays open.

import { el, fill } from '../core/dom.js';
import { api } from '../core/api.js';
import { state, patch } from '../core/store.js';
import { showError } from '../components/toast.js';
import { clockTime } from '../core/format.js';
import { t } from '../core/i18n.js';

export async function refresh() {
  try {
    patch({ mqttState: await api.mqtt() });
  } catch {
    patch({ mqttState: null });
  }
}

export function render(root) {
  const data = state.mqttState
    || { running: false, topics: [], messages: [] };
  const parts = [];

  parts.push(el('div', { class: 'page-head' }, [
    el('div', {}, [el('h2', { text: t('nav.mqtt') })]),
    el('div', { class: 'actions' }, [
      el('span', {
        class: 'badge',
        style: data.running
          ? 'border-color:var(--ok-soft);color:var(--ok)'
          : 'color:var(--text-dim)',
        text: data.running
          ? t('mqtt.connected', {
            broker: data.broker || '', count: data.total || 0,
          })
          : t('mqtt.notConnected'),
      }),
      el('button', {
        type: 'button',
        class: data.running ? 'btn' : 'btn btn-primary',
        text: t(data.running ? 'mqtt.stop' : 'mqtt.start'),
        onclick: async () => {
          try {
            patch({ mqttState: data.running
              ? await api.mqttStop()
              : await api.mqttStart(state.setNo) });
          } catch (e) { showError(e.message); }
        },
      }),
    ]),
  ]));

  if (data.error) parts.push(el('p', { class: 'warning', text: data.error }));

  const topics = data.topics || [];
  const messages = data.messages || [];

  parts.push(el('div', { class: 'mqtt-grid' }, [
    el('div', { class: 'card' }, [
      el('div', {
        class: 'label', style: 'margin-bottom:10px', text: t('mqtt.topics'),
      }),
      ...(topics.length ? topics.map(topic => el('div', {
        style: 'display:flex;align-items:center;gap:8px;padding:7px 0;'
          + 'border-bottom:1px solid var(--line-soft)',
      }, [
        el('span', {
          class: 'dot', style: 'background:var(--accent)',
          'aria-hidden': 'true',
        }),
        el('span', {
          class: 'mono truncate', style: 'flex:1;font-size:11px',
          text: topic.name,
        }),
        el('span', {
          class: 'mono text-dim', style: 'font-size:10px',
          text: String(topic.count),
        }),
      ])) : [el('div', {
        class: 'mono text-dim', style: 'font-size:11px',
        text: t('mqtt.noMessageYet'),
      })]),
    ]),

    el('div', { class: 'mqtt-feed' }, [
      el('div', {
        style: 'display:flex;align-items:center;gap:10px;margin-bottom:11px',
      }, [
        el('span', { class: 'label', text: t('mqtt.stream') }),
        el('span', { style: 'flex:1' }),
        el('span', {
          class: 'mono text-dim', style: 'font-size:10px',
          text: t('mqtt.showingRows', { count: messages.length }),
        }),
      ]),
      ...(messages.length ? messages.map(message => el('div', {
        class: 'mqtt-feed-row',
      }, [
        el('span', { class: 'text-dim', text: clockTime(message.time) }),
        el('span', {
          style: 'color:var(--accent)', class: 'truncate',
          text: message.topic,
        }),
        el('span', {
          class: 'payload', title: message.payload, text: message.payload,
        }),
      ])) : [el('div', {
        class: 'mono text-dim', style: 'font-size:11px',
        text: t(data.running ? 'mqtt.waitingForMessages'
          : 'mqtt.listenerStopped'),
      })]),
    ]),
  ]));

  fill(root, parts);
}
