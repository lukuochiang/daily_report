(function () {
  'use strict';

  var LANG_KEY = 'td-lang';
  var THEME_KEY = 'td-theme';
  var THEME_ORDER = ['system', 'light', 'dark'];
  var THEME_LABELS = { system: '跟随系统', light: '日间模式', dark: '夜间模式' };
  var THEME_ICONS = {
    system: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    light: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4"/></svg>',
    dark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 15.5A8.5 8.5 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5z"/></svg>'
  };

  function readStored(key, fallback) {
    try { return window.localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }

  function store(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* 隐私模式忽略 */ }
  }

  function applyLang(lang) {
    lang = lang === 'en' ? 'en' : 'zh';
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    document.querySelectorAll('[data-zh][data-en]').forEach(function (el) {
      var value = el.getAttribute(lang === 'en' ? 'data-en' : 'data-zh');
      if (value !== null) el.textContent = value;
    });
    document.querySelectorAll('[data-zh-ph][data-en-ph]').forEach(function (el) {
      var value = el.getAttribute(lang === 'en' ? 'data-en-ph' : 'data-zh-ph');
      if (value !== null) el.placeholder = value;
    });
    var button = document.getElementById('lang-toggle');
    if (button) {
      var label = button.querySelector('.lang-label');
      if (label) {
        label.textContent = lang === 'en' ? '中文' : 'EN';
      } else {
        button.textContent = lang === 'en' ? '中文' : 'EN';
      }
      button.setAttribute('aria-label', lang === 'en' ? '切换到中文 / Switch to Chinese' : 'Switch to English / 切换到英文');
      button.title = lang === 'en' ? '切换到中文' : 'Switch to English';
    }
    store(LANG_KEY, lang);
  }

  var langToggle = document.getElementById('lang-toggle');
  if (langToggle) {
    langToggle.addEventListener('click', function () {
      applyLang(document.documentElement.lang.indexOf('en') === 0 ? 'zh' : 'en');
    });
  }
  applyLang(readStored(LANG_KEY, 'zh'));

  function applyTheme(mode) {
    if (THEME_ORDER.indexOf(mode) === -1) mode = 'system';
    document.documentElement.setAttribute('data-theme', mode);
    var button = document.getElementById('theme-toggle');
    if (button) {
      button.innerHTML = THEME_ICONS[mode];
      button.title = THEME_LABELS[mode];
      button.setAttribute('aria-label', THEME_LABELS[mode]);
    }
    store(THEME_KEY, mode);
  }

  var themeToggle = document.getElementById('theme-toggle');
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var current = document.documentElement.getAttribute('data-theme') || 'system';
      applyTheme(THEME_ORDER[(THEME_ORDER.indexOf(current) + 1) % THEME_ORDER.length]);
    });
  }
  applyTheme(readStored(THEME_KEY, 'system'));

  function readAppData() {
    var node = document.getElementById('app-data');
    if (!node) return {};
    try {
      var rows = JSON.parse(node.textContent);
      var map = {};
      rows.forEach(function (row) { map[row.id] = row; });
      return map;
    } catch (e) {
      return {};
    }
  }

  function initNews() {
    var list = document.getElementById('news-list');
    if (!list) return;
    var meta = readAppData();
    var cards = Array.prototype.slice.call(list.querySelectorAll('.news-card'));
    var input = document.getElementById('news-search');
    var sort = document.getElementById('news-sort');
    var chips = Array.prototype.slice.call(document.querySelectorAll('#category-filters .chip'));
    var counter = document.getElementById('result-count');
    var empty = document.getElementById('no-results');
    var query = '';
    var category = 'all';

    function update() {
      var words = query.toLowerCase().split(/\s+/).filter(Boolean);
      var visible = 0;
      cards.forEach(function (card) {
        var info = meta[card.dataset.id] || {};
        var haystack = String(info.search || card.textContent).toLowerCase();
        var textOk = words.every(function (word) { return haystack.indexOf(word) !== -1; });
        var categoryOk = category === 'all' || card.dataset.category === category;
        var show = textOk && categoryOk;
        card.hidden = !show;
        if (show) visible++;
      });
      var sortBy = sort ? sort.value : 'importance';
      cards.slice().sort(function (a, b) {
        var ma = meta[a.dataset.id] || {};
        var mb = meta[b.dataset.id] || {};
        if (sortBy === 'time') {
          return String(mb.published_at || '').localeCompare(String(ma.published_at || ''));
        }
        return (mb.importance || 0) - (ma.importance || 0) ||
          String(mb.published_at || '').localeCompare(String(ma.published_at || ''));
      }).forEach(function (card) { list.appendChild(card); });
      if (counter) counter.textContent = String(visible);
      if (empty) empty.hidden = visible !== 0;
    }

    if (input) input.addEventListener('input', function () { query = input.value.trim(); update(); });
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (other) { other.classList.remove('active'); });
        chip.classList.add('active');
        category = chip.dataset.filter || 'all';
        update();
      });
    });
    if (sort) sort.addEventListener('change', update);
  }

  function initArchives() {
    var chips = Array.prototype.slice.call(document.querySelectorAll('#month-filters .chip'));
    if (!chips.length) return;
    var groups = Array.prototype.slice.call(document.querySelectorAll('.month-group'));
    chips.forEach(function (chip) {
      chip.addEventListener('click', function () {
        chips.forEach(function (other) { other.classList.remove('active'); });
        chip.classList.add('active');
        var month = chip.dataset.month || 'all';
        groups.forEach(function (group) {
          group.hidden = month !== 'all' && group.dataset.month !== month;
        });
      });
    });
  }

  initNews();
  initArchives();
})();
