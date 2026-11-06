'use strict';

window.RatoNetUI = {
  escapeHTML(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  },
  safeURL(value) {
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch { return ''; }
  },
  color(value) {
    return /^#[0-9a-f]{6}$/i.test(value) ? value : '#ff6600';
  },
};
