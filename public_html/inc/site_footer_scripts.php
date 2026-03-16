<script>
  (function () {
    var form = document.querySelector('[data-search-form]');
    var input = document.querySelector('[data-search-input]');
    var panel = document.querySelector('[data-search-suggest]');
    var list = document.querySelector('[data-search-suggest-list]');
    var submitLink = document.querySelector('[data-search-submit-link]');
    if (!form || !input || !panel || !list || !submitLink) return;

    var debounceTimer = null;
    var currentController = null;

    function escapeHtml(value) {
      return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    function closeSuggest() {
      panel.hidden = true;
      list.innerHTML = '';
    }

    function renderItems(items, query) {
      if (!items.length) {
        list.innerHTML = '<div class="search-suggest-empty">Nenhum produto encontrado para esta busca.</div>';
        panel.hidden = false;
        submitLink.href = '/busca.php?q=' + encodeURIComponent(query);
        return;
      }

      list.innerHTML = items.map(function (item) {
        return [
          '<a class="search-suggest-item" href="' + escapeHtml(item.offer_url) + '">',
          '<img src="' + escapeHtml(item.image) + '" alt="">',
          '<div class="search-suggest-copy">',
          '<strong>' + escapeHtml(item.title) + '</strong>',
          '<span>' + escapeHtml(item.store) + ' · ' + escapeHtml(item.category) + '</span>',
          '</div>',
          '</a>'
        ].join('');
      }).join('');
      submitLink.href = '/busca.php?q=' + encodeURIComponent(query);
      panel.hidden = false;
    }

    function fetchSuggest(query) {
      if (currentController) currentController.abort();
      currentController = new AbortController();
      fetch('/api/search.php?q=' + encodeURIComponent(query), { signal: currentController.signal })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (!data || data.ok !== true) {
            throw new Error((data && data.error) || 'Falha ao buscar sugestões.');
          }
          renderItems(data.items || [], query);
        })
        .catch(function (error) {
          if (error.name === 'AbortError') return;
          list.innerHTML = '<div class="search-suggest-empty">Não foi possível carregar as sugestões agora.</div>';
          submitLink.href = '/busca.php?q=' + encodeURIComponent(query);
          panel.hidden = false;
        });
    }

    input.addEventListener('input', function () {
      var query = input.value.trim();
      if (debounceTimer) window.clearTimeout(debounceTimer);
      if (query.length < 2) {
        closeSuggest();
        return;
      }
      debounceTimer = window.setTimeout(function () {
        fetchSuggest(query);
      }, 220);
    });

    input.addEventListener('focus', function () {
      if (input.value.trim().length >= 2 && list.innerHTML.trim() !== '') {
        panel.hidden = false;
      }
    });

    document.addEventListener('click', function (event) {
      if (!form.contains(event.target)) {
        closeSuggest();
      }
    });

    form.addEventListener('submit', function () {
      closeSuggest();
    });
  }());

  (function () {
    var links = document.querySelectorAll('a[href*="go=1"]');
    if (!links.length || typeof window.gtag !== 'function') return;

    links.forEach(function (link) {
      link.addEventListener('click', function () {
        var scope = link.closest('article, .list-card, .detail-panel') || document;
        var titleNode = scope.querySelector('h1, .card-title');
        var storeNode = scope.querySelector('.kicker');
        var label = titleNode ? titleNode.textContent.trim() : link.textContent.trim();
        var store = storeNode ? storeNode.textContent.trim() : '';
        var href = link.getAttribute('href') || '';

        gtag('event', 'click_out', {
          event_category: 'affiliate',
          event_label: label || href,
          affiliate_store: store,
          affiliate_target: href,
          page_path: window.location.pathname,
          transport_type: 'beacon'
        });

        gtag('event', 'conversion', {
          send_to: 'AW-975222683/41lzCO6H2M4ZEJvvgtED',
          transaction_id: ''
        });

        window.dataLayer = window.dataLayer || [];
        window.dataLayer.push({
          event: 'click_out',
          click_out_label: label || href,
          click_out_store: store,
          click_out_target: href,
          click_out_path: window.location.pathname
        });
      });
    });
  }());

  (function () {
    var panel = document.querySelector('[data-mobile-panel]');
    var toggles = document.querySelectorAll('[data-menu-toggle]');
    if (!panel || !toggles.length) return;

    toggles.forEach(function (toggle) {
      toggle.addEventListener('click', function () {
        var isOpen = panel.classList.toggle('is-open');
        toggles.forEach(function (button) {
          button.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
      });
    });

    panel.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', function () {
        panel.classList.remove('is-open');
        toggles.forEach(function (button) {
          button.setAttribute('aria-expanded', 'false');
        });
      });
    });
  }());

  (function () {
    var triggers = document.querySelectorAll('[data-load-more]');
    if (!triggers.length) return;

    function getRowStep(root) {
      if (!root) return 1;
      var template = window.getComputedStyle(root).getPropertyValue('grid-template-columns');
      if (!template) return 1;
      var columns = template.split(' ').filter(function (value) {
        return value && value !== '/';
      }).length;
      return Math.max(1, columns || 1);
    }

    function getStepValue(trigger, root, attributeName, fallbackAttribute) {
      var rawValue = trigger.getAttribute(attributeName);
      if (!rawValue && fallbackAttribute) {
        rawValue = trigger.getAttribute(fallbackAttribute);
      }
      if (rawValue === 'row') {
        return getRowStep(root);
      }
      if (rawValue === '2row') {
        return getRowStep(root) * 2;
      }
      var numeric = Number(rawValue || 0);
      if (numeric > 0) {
        return numeric;
      }
      return getRowStep(root);
    }

    function syncVisibility(trigger) {
      var selector = trigger.getAttribute('data-load-more');
      var root = selector ? document.querySelector(selector) : null;
      if (!root) return;

      var items = Array.prototype.slice.call(root.querySelectorAll('[data-load-more-item]'));
      if (!items.length) {
        trigger.setAttribute('hidden', 'hidden');
        return;
      }

      var initial = getStepValue(trigger, root, 'data-load-more-initial', 'data-load-more-step');
      items.forEach(function (item, index) {
        if (index < initial) {
          item.removeAttribute('hidden');
          item.classList.remove('is-hidden');
          return;
        }
        item.setAttribute('hidden', 'hidden');
        item.classList.add('is-hidden');
      });

      if (items.length <= initial) {
        trigger.setAttribute('hidden', 'hidden');
      } else {
        trigger.removeAttribute('hidden');
      }
    }

    triggers.forEach(function (trigger) {
      syncVisibility(trigger);

      trigger.addEventListener('click', function () {
        var selector = trigger.getAttribute('data-load-more');
        var root = selector ? document.querySelector(selector) : null;
        if (!root) return;

        var step = getStepValue(trigger, root, 'data-load-more-step');
        var items = Array.prototype.slice.call(root.querySelectorAll('[data-load-more-item]'));
        var hiddenItems = items.filter(function (item) {
          return item.hasAttribute('hidden');
        });

        hiddenItems.slice(0, step).forEach(function (item) {
          item.removeAttribute('hidden');
          item.classList.remove('is-hidden');
        });

        if (!items.some(function (item) { return item.hasAttribute('hidden'); })) {
          trigger.setAttribute('hidden', 'hidden');
        }
      });
    });
  }());
</script>
