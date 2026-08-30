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

  // THE HEADING IS THE ANSWER. It read "MQTT monitor" — the name the menu
  // rail and the hidden `h1` both already give it — while the one thing
  // somebody opens this screen to find out sat in a small chip in the
  // corner beside the button. The chip is gone; the sentence it held is the
  // largest thing on the screen, with the state dot the rest of the panel
  // uses in front of it.
  const listening = !!data.running;
  parts.push(el('div', { class: 'page-head' }, [
    el('h2', { class: 'verdict', dataset: { state: listening ? 'ok' : 'unknown' } }, [
      el('span', {
        class: 'dot', dataset: { state: listening ? 'ok' : 'unknown' },
        'aria-hidden': 'true',
      }),
      el('span', {
        text: listening
          ? t('mqtt.connected', {
            broker: data.broker || '', count: data.total || 0,
          })
          : t('mqtt.notConnected'),
      }),
    ]),
    el('div', { class: 'actions' }, [
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
    el('div', { class: 'card corner' }, [
      el('div', { class: 'card-head' }, [
        el('h3', { text: t('mqtt.topics') }),
      ]),
      // No dot in front of the name: every topic had the same blue one, so
      // it distinguished nothing and only narrowed the column the long
      // names actually needed.
      ...(topics.length ? topics.map(topic => el('div', {
        class: 'rule-row',
      }, [
        el('span', {
          class: 'mono truncate t-sm grow', title: topic.name,
          text: topic.name,
        }),
        el('span', {
          class: 'mono text-dim t-xs',
          text: String(topic.count),
        }),
      ])) : [el('div', {
        class: 'mono text-dim t-sm',
        text: t('mqtt.noMessageYet'),
      })]),
    ]),

    el('div', { class: 'mqtt-feed' }, [
      el('div', { class: 'row gap-3 mb-4' }, [
        el('span', { class: 'label', text: t('mqtt.stream') }),
        el('span', { class: 'grow' }),
        el('span', {
          class: 'mono text-dim t-xs',
          text: t('mqtt.showingRows', { count: messages.length }),
        }),
      ]),
      ...(messages.length ? messages.map(message => el('div', {
        class: 'mqtt-feed-row',
      }, [
        el('span', { class: 'text-dim', text: clockTime(message.time) }),
        el('span', {
          class: 'truncate mqtt-topic', title: message.topic,
          text: message.topic,
        }),
        el('span', {
          class: 'truncate payload', title: message.payload,
          text: message.payload,
        }),
      ])) : [el('div', {
        class: 'mono text-dim t-sm',
        text: t(data.running ? 'mqtt.waitingForMessages'
          : 'mqtt.listenerStopped'),
      })]),
    ]),
  ]));

  fill(root, parts);
}
