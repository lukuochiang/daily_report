(function () {
  'use strict';

  var STORAGE_KEY = 'td-lang';

  function storedLang() {
    try { return window.localStorage.getItem(STORAGE_KEY) || 'zh'; } catch (e) { return 'zh'; }
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
      button.textContent = lang === 'en' ? '中文' : 'EN';
      button.setAttribute('aria-label', lang === 'en' ? '切换到中文' : 'Switch to English');
    }
    try { window.localStorage.setItem(STORAGE_KEY, lang); } catch (e) { /* 隐私模式忽略 */ }
  }

  var toggle = document.getElementById('lang-toggle');
  if (toggle) {
    toggle.addEventListener('click', function () {
      applyLang(document.documentElement.lang.indexOf('en') === 0 ? 'zh' : 'en');
    });
  }
  applyLang(storedLang());

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
