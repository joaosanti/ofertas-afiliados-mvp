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

  (function () {
    var rails = document.querySelectorAll('[data-auto-carousel]');
    if (!rails.length) return;

    rails.forEach(function (rail) {
      var speed = Number(rail.getAttribute('data-auto-carousel-speed') || 0.6);
      var isPaused = false;
      var rafId = 0;

      function step() {
        if (!isPaused) {
          rail.scrollLeft += speed;
          if (rail.scrollLeft >= (rail.scrollWidth - rail.clientWidth) / 2) {
            rail.scrollLeft = 0;
          }
        }
        rafId = window.requestAnimationFrame(step);
      }

      rail.addEventListener('mouseenter', function () {
        isPaused = true;
      });
      rail.addEventListener('mouseleave', function () {
        isPaused = false;
      });
      rail.addEventListener('touchstart', function () {
        isPaused = true;
      }, { passive: true });
      rail.addEventListener('touchend', function () {
        isPaused = false;
      }, { passive: true });

      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
      }

      step();

      window.addEventListener('beforeunload', function () {
        if (rafId) {
          window.cancelAnimationFrame(rafId);
        }
      });
    });
  }());

  (function () {
    var root = document.querySelector('[data-home-video-player]');
    if (!root) return;

    var video = root.querySelector('[data-home-video-element]');
    var titleNode = root.querySelector('[data-home-video-title]');
    var storeNode = root.querySelector('[data-home-video-store]');
    var priceNode = root.querySelector('[data-home-video-price]');
    var oldPriceNode = root.querySelector('[data-home-video-old-price]');
    var discountNode = root.querySelector('[data-home-video-discount]');
    var linkNode = root.querySelector('[data-home-video-link]');
    var soundButton = root.querySelector('[data-home-video-sound]');
    var soundIcon = root.querySelector('[data-home-video-sound-icon]');
    var prevButton = root.querySelector('[data-home-video-prev]');
    var nextButton = root.querySelector('[data-home-video-next]');
    var playlistNode = root.querySelector('[data-home-video-playlist]');
    if (!video || !playlistNode) return;

    var playlist = [];
    try {
      playlist = JSON.parse(playlistNode.textContent || '[]');
    } catch (error) {
      playlist = [];
    }

    if (!playlist.length) {
      return;
    }

    var currentIndex = 0;
    var soundEnabled = !video.muted;

    function setHidden(node, shouldHide) {
      if (!node) return;
      node.classList.toggle('is-hidden', !!shouldHide);
    }

    function syncSoundButton() {
      if (!soundButton) return;
      soundEnabled = !video.muted;
      soundButton.classList.toggle('is-active', soundEnabled);
      soundButton.setAttribute('aria-label', soundEnabled ? 'Desativar som' : 'Ativar som');
      soundButton.setAttribute('title', soundEnabled ? 'Desativar som' : 'Ativar som');
      if (soundIcon) {
        soundIcon.innerHTML = soundEnabled ? '&#128266;' : '&#128263;';
      }
    }

    function updateVideo(item, shouldAutoPlay) {
      if (!item || !item.video_url) return;

      video.pause();
      video.src = item.video_url;
      video.poster = item.poster || '';
      video.muted = !soundEnabled;
      video.load();

      if (titleNode) titleNode.textContent = item.title || '';
      if (storeNode) storeNode.textContent = item.store || '';
      if (priceNode) priceNode.textContent = item.price || '';
      if (oldPriceNode) {
        oldPriceNode.textContent = item.old_price || '';
        setHidden(oldPriceNode, !item.old_price);
      }
      if (discountNode) {
        discountNode.textContent = item.discount ? ('-' + item.discount + '%') : '';
        setHidden(discountNode, !item.discount);
      }
      if (linkNode) {
        linkNode.href = item.href || '#';
      }

      if (shouldAutoPlay) {
        var playPromise = video.play();
        if (playPromise && typeof playPromise.catch === 'function') {
          playPromise.catch(function () {
            video.muted = true;
            syncSoundButton();
            var fallbackPlay = video.play();
            if (fallbackPlay && typeof fallbackPlay.catch === 'function') {
              fallbackPlay.catch(function () {});
            }
          });
        }
      }
    }

    function nextVideo() {
      if (playlist.length <= 1) {
        video.currentTime = 0;
        var replay = video.play();
        if (replay && typeof replay.catch === 'function') {
          replay.catch(function () {});
        }
        return;
      }

      currentIndex = (currentIndex + 1) % playlist.length;
      updateVideo(playlist[currentIndex], true);
    }

    function previousVideo() {
      if (playlist.length <= 1) {
        video.currentTime = 0;
        var replay = video.play();
        if (replay && typeof replay.catch === 'function') {
          replay.catch(function () {});
        }
        return;
      }

      currentIndex = (currentIndex - 1 + playlist.length) % playlist.length;
      updateVideo(playlist[currentIndex], true);
    }

    video.addEventListener('ended', nextVideo);
    video.addEventListener('error', nextVideo);
    video.addEventListener('volumechange', syncSoundButton);

    if (prevButton) {
      prevButton.addEventListener('click', previousVideo);
      prevButton.classList.toggle('is-hidden', playlist.length <= 1);
    }

    if (nextButton) {
      nextButton.addEventListener('click', nextVideo);
      nextButton.classList.toggle('is-hidden', playlist.length <= 1);
    }

    if (soundButton) {
      soundButton.addEventListener('click', function () {
        video.muted = !video.muted;
        syncSoundButton();
        if (soundEnabled) {
          var playPromise = video.play();
          if (playPromise && typeof playPromise.catch === 'function') {
            playPromise.catch(function () {});
          }
        }
      });
      syncSoundButton();
    }

    updateVideo(playlist[currentIndex], true);
  }());
</script>
