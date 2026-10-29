/* ============================================================
   MangaSpace — интерактив, анимации и настройки оформления
   ============================================================ */
(function () {
    'use strict';

    var root = document.documentElement;

    /* Кнопка «Назад» браузера: при уходе со страницы мы вешаем body.page-out
       (opacity: 0), и bfcache сохраняет страницу уже затемнённой — при возврате
       был чёрный экран. Снимаем класс ДО кэширования и ПОСЛЕ восстановления. */
    window.addEventListener('pagehide', function () {
        document.body.classList.remove('page-out');
    });
    window.addEventListener('pageshow', function () {
        document.body.classList.remove('page-out');
    });

    var THEMES = { dark: 'Тёмная', light: 'Светлая' };
    var ACCENT_NAMES = {
        orange: 'Оранжевый',
        pink: 'Розовый',
        violet: 'Фиолетовый',
        blue: 'Синий',
        emerald: 'Изумрудный',
        gold: 'Золотой'
    };

    function store(key, value) {
        try { localStorage.setItem(key, value); } catch (e) {}
    }

    function read(key, fallback) {
        try { return localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
    }

    function animEnabled() {
        return root.getAttribute('data-anim') !== 'off' &&
            !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    }

    /* ---------------- Помощники для кастомных цветов ---------------- */
    function hexToRgb(hex) {
        hex = String(hex || '').replace('#', '');
        if (hex.length === 3) {
            hex = hex.split('').map(function (c) { return c + c; }).join('');
        }
        var num = parseInt(hex, 16);
        if (isNaN(num)) return null;
        return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
    }

    function normalizeHex(hex) {
        hex = String(hex || '').trim();
        if (hex && hex.charAt(0) !== '#') hex = '#' + hex;
        return /^#[0-9a-fA-F]{6}$/.test(hex) ? hex.toLowerCase() : null;
    }

    function shadeHex(hex, factor) {
        var rgb = hexToRgb(hex);
        if (!rgb) return hex;
        var out = rgb.map(function (c) {
            return Math.max(0, Math.min(255, Math.round(factor < 0 ? c * (1 + factor) : c + (255 - c) * factor)));
        });
        return '#' + out.map(function (c) { return ('0' + c.toString(16)).slice(-2); }).join('');
    }

    function clearInlineAccent() {
        ['--accent', '--accent-rgb', '--accent-hover', '--accent-strong', '--accent-2'].forEach(function (v) {
            root.style.removeProperty(v);
        });
    }

    function clearInlineBg() {
        root.style.removeProperty('--bg-body');
    }

    function clearStoredCustom() {
        try {
            localStorage.removeItem('ms-accent-custom');
            localStorage.removeItem('ms-bg-custom');
        } catch (e) {}
    }

    /* ---------------- Toasts ---------------- */
    function ensureToastStack() {
        var stack = document.querySelector('.toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.className = 'toast-stack';
            document.body.appendChild(stack);
        }
        return stack;
    }

    function toast(message, icon) {
        var stack = ensureToastStack();
        var el = document.createElement('div');
        el.className = 'toast';
        el.innerHTML = '<i class="' + (icon || 'fa-solid fa-circle-check') + '"></i><span></span>';
        el.querySelector('span').textContent = message;
        stack.appendChild(el);
        setTimeout(function () {
            el.classList.add('hide');
            setTimeout(function () { el.remove(); }, 320);
        }, 2400);
    }

    /* ---------------- Тема / акцент / анимации ---------------- */
    function applyTheme(theme, silent) {
        theme = theme === 'light' ? 'light' : 'dark';
        root.setAttribute('data-theme', theme);
        store('ms-theme', theme);
        syncSettingsUI();
        if (!silent) toast('Тема: ' + THEMES[theme], theme === 'light' ? 'fa-solid fa-sun' : 'fa-solid fa-moon');
    }

    function applyAccent(accent, silent) {
        clearInlineAccent();
        if (!ACCENT_NAMES[accent]) accent = 'orange';
        root.setAttribute('data-accent', accent);
        store('ms-accent', accent);
        syncSettingsUI();
        if (!silent) toast('Акцент: ' + ACCENT_NAMES[accent], 'fa-solid fa-palette');
    }

    /* Свой (произвольный) акцентный цвет пипеткой */
    function applyCustomAccent(hex, silent) {
        hex = normalizeHex(hex);
        if (!hex) return;
        var rgb = hexToRgb(hex);
        root.setAttribute('data-accent', 'custom');
        root.style.setProperty('--accent', hex);
        root.style.setProperty('--accent-rgb', rgb.join(', '));
        root.style.setProperty('--accent-hover', shadeHex(hex, -0.15));
        root.style.setProperty('--accent-strong', shadeHex(hex, -0.28));
        root.style.setProperty('--accent-2', shadeHex(hex, 0.25));
        store('ms-accent-custom', hex);
        syncSettingsUI();
        if (!silent) toast('Свой акцент: ' + hex, 'fa-solid fa-eye-dropper');
    }

    /* Свой цвет основного фона */
    function applyCustomBg(hex, silent) {
        hex = normalizeHex(hex);
        if (!hex) return;
        root.style.setProperty('--bg-body', hex);
        store('ms-bg-custom', hex);
        syncSettingsUI();
        if (!silent) toast('Фон: ' + hex, 'fa-solid fa-fill-drip');
    }

    function resetCustomBg(silent) {
        clearInlineBg();
        try { localStorage.removeItem('ms-bg-custom'); } catch (e) {}
        syncSettingsUI();
        if (!silent) toast('Фон сброшен по умолчанию', 'fa-solid fa-rotate-left');
    }

    function applyAnim(state, silent) {
        var value = state === 'off' ? 'off' : 'on';
        root.setAttribute('data-anim', value);
        store('ms-anim', value);
        syncSettingsUI();
        if (value === 'on') initReveal(true);
        if (!silent) {
            toast(value === 'on' ? 'Анимации включены' : 'Анимации выключены',
                value === 'on' ? 'fa-solid fa-wand-magic-sparkles' : 'fa-solid fa-pause');
        }
    }

    function syncSettingsUI() {
        var theme = root.getAttribute('data-theme');
        var accent = root.getAttribute('data-accent');
        var anim = root.getAttribute('data-anim');

        document.querySelectorAll('[data-set-theme]').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-set-theme') === theme);
        });
        document.querySelectorAll('.swatch[data-accent]').forEach(function (btn) {
            btn.classList.toggle('active', btn.getAttribute('data-accent') === accent);
        });
        document.querySelectorAll('[data-set-anim]').forEach(function (btn) {
            var on = anim !== 'off';
            btn.classList.toggle('on', on);
            btn.setAttribute('aria-pressed', String(on));
        });
        document.querySelectorAll('#themeToggle [data-icon]').forEach(function (i) {
            i.style.display = '';
        });

        // Синхронизация пипеток кастомных цветов
        var customAccent = read('ms-accent-custom', '');
        var customBg = read('ms-bg-custom', '');
        var accentPicker = document.querySelector('[data-custom-accent]');
        var accentHex = document.querySelector('[data-custom-accent-hex]');
        var bgPicker = document.querySelector('[data-custom-bg]');
        var bgHex = document.querySelector('[data-custom-bg-hex]');

        if (accentPicker) {
            accentPicker.value = accent === 'custom' && customAccent ? customAccent : (accentPicker.defaultValue || '#ff7a1a');
        }
        if (accentHex) {
            accentHex.textContent = accent === 'custom' && customAccent ? customAccent : '#ff7a1a';
        }
        if (bgPicker) {
            bgPicker.value = customBg || bgPicker.defaultValue || '#0a0b10';
        }
        if (bgHex) {
            bgHex.textContent = customBg || '#0a0b10';
        }
    }

    /* ---------------- Шапка при скролле ---------------- */
    function initHeaderScroll() {
        var header = document.querySelector('header');
        if (!header || header.classList.contains('reader-header')) return;
        var ticking = false;
        function update() {
            header.classList.toggle('scrolled', window.scrollY > 24);
            ticking = false;
        }
        window.addEventListener('scroll', function () {
            if (!ticking) {
                ticking = true;
                window.requestAnimationFrame(update);
            }
        }, { passive: true });
        update();
    }

    /* ---------------- Появление элементов при скролле ---------------- */
    var revealObserver = null;

    function initReveal(force) {
        var selector = [
            '.manga-card',
            '.search-bar',
            '.empty-state',
            '.empty-catalog',
            '.auth-container',
            '.form-card',
            '.settings-card',
            '.profile-card',
            'main .container > *:not(.manga-grid):not(.toast-stack)'
        ].join(',');

        var nodes = Array.prototype.slice.call(document.querySelectorAll(selector));
        if (!nodes.length) return;

        nodes.forEach(function (el) {
            if (!el.hasAttribute('data-anim')) el.setAttribute('data-anim', '');
            if (el.dataset.staggerGroup === undefined) {
                var siblings = nodes.filter(function (n) {
                    return n.parentElement === el.parentElement;
                });
                var idx = siblings.indexOf(el);
                if (idx > 0) {
                    el.style.setProperty('--d', Math.min(idx * 70, 560) + 'ms');
                }
                el.dataset.staggerGroup = '1';
            }
        });

        if (!animEnabled()) {
            nodes.forEach(function (el) { el.classList.add('is-in'); });
            return;
        }

        if (revealObserver) revealObserver.disconnect();

        revealObserver = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-in');
                    revealObserver.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08, rootMargin: '0px 0px -6% 0px' });

        nodes.forEach(function (el) {
            if (force || !el.classList.contains('is-in')) {
                if (el.getBoundingClientRect().top < window.innerHeight) {
                    el.classList.add('is-in');
                } else {
                    revealObserver.observe(el);
                }
            }
        });
    }

    /* ---------------- 3D наклон карточек ---------------- */
    function initTilt() {
        if (!animEnabled()) return;
        if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;

        document.querySelectorAll('.manga-card').forEach(function (card) {
            card.addEventListener('pointermove', function (e) {
                var rect = card.getBoundingClientRect();
                var px = (e.clientX - rect.left) / rect.width - 0.5;
                var py = (e.clientY - rect.top) / rect.height - 0.5;
                card.classList.add('is-tilting');
                card.style.transform =
                    'translateY(-8px) scale(1.02) rotateX(' + (-py * 7).toFixed(2) +
                    'deg) rotateY(' + (px * 7).toFixed(2) + 'deg)';
            });
            card.addEventListener('pointerleave', function () {
                card.classList.remove('is-tilting');
                card.style.transform = '';
            });
        });
    }

    /* ---------------- Ripple на кнопках ---------------- */
    function initRipple() {
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('.btn, .theme-card, .icon-btn');
            if (!btn || !animEnabled()) return;
            btn.classList.remove('ripple');
            void btn.offsetWidth;
            btn.classList.add('ripple');
        });
    }

    /* ---------------- Уведомления ---------------- */
    function initNotifications() {
        var dropdown = document.getElementById('notif-dropdown');
        if (!dropdown) return;

        document.addEventListener('click', function (e) {
            if (!dropdown.contains(e.target) && !e.target.closest('.notif-btn')) {
                dropdown.classList.remove('show');
            }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') dropdown.classList.remove('show');
        });
    }

    window.toggleNotifications = function (event) {
        if (event) event.stopPropagation();
        var menu = document.getElementById('user-menu-dropdown');
        if (menu) menu.classList.remove('show');
        var dropdown = document.getElementById('notif-dropdown');
        if (!dropdown) return;
        var willShow = !dropdown.classList.contains('show');
        dropdown.classList.toggle('show');
        // Уведомления исчезают после просмотра
        if (willShow) window.readAllNotifications(true);
    };

    window.readAllNotifications = function (silent) {
        var wrapper = document.querySelector('[data-notifications-read-url]');
        if (!wrapper) return;
        fetch(wrapper.getAttribute('data-notifications-read-url'))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === 'ok') {
                    var badge = document.getElementById('notif-badge');
                    if (badge) badge.remove();
                    document.querySelectorAll('.notif-item').forEach(function (item) {
                        item.classList.remove('unread');
                        item.classList.add('read');
                    });
                    if (!silent) toast('Уведомления просмотрены и скрыты', 'fa-solid fa-check-double');
                }
            })
            .catch(function (err) { console.error('Ошибка уведомлений:', err); });
    };

    // Клик по уведомлению: оно удаляется и больше не появляется
    window.viewNotification = function (event, el) {
        var url = el.getAttribute('data-notif-url');
        if (url) {
            fetch(url).catch(function () {});
        }
        var badge = document.getElementById('notif-badge');
        if (badge) badge.remove();
        el.classList.remove('unread');
        el.classList.add('read');
        return true;
    };

    /* ---------------- Меню «три точки» ---------------- */
    function initUserMenu() {
        var dropdown = document.getElementById('user-menu-dropdown');
        if (!dropdown) return;

        document.addEventListener('click', function (e) {
            if (!dropdown.contains(e.target) && !e.target.closest('.user-menu-btn')) {
                dropdown.classList.remove('show');
            }
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') dropdown.classList.remove('show');
        });
    }

    window.toggleUserMenu = function (event) {
        if (event) event.stopPropagation();
        var notif = document.getElementById('notif-dropdown');
        if (notif) notif.classList.remove('show');
        var dropdown = document.getElementById('user-menu-dropdown');
        if (dropdown) dropdown.classList.toggle('show');
    };

    /* ---------------- Мобильное меню ---------------- */
    window.toggleMobileDrawer = function () {
        var drawer = document.getElementById('mobileDrawer');
        var overlay = document.getElementById('mobileOverlay');
        if (drawer) drawer.classList.toggle('active');
        if (overlay) overlay.classList.toggle('active');
        document.body.style.overflow = drawer && drawer.classList.contains('active') ? 'hidden' : '';
    };

    /* ---------------- Плавный переход между страницами ---------------- */
    function initPageTransition() {
        if (!animEnabled()) return;
        document.addEventListener('click', function (e) {
            var link = e.target.closest('a');
            if (!link || link.target === '_blank' || link.hasAttribute('download')) return;
            var href = link.getAttribute('href');
            if (!href || href.charAt(0) === '#' || href.indexOf('javascript:') === 0) return;
            if (link.dataset.noTransition !== undefined) return;
            if (link.origin && link.origin !== window.location.origin) return;
            if (link.pathname === window.location.pathname && link.hash) return;

            e.preventDefault();
            document.body.classList.add('page-out');
            setTimeout(function () { window.location.href = link.href; }, 170);
        });
    }

    /* ---------------- Настройки на странице settings ---------------- */
    function initSettingsPage() {
        document.querySelectorAll('[data-set-theme]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                applyTheme(btn.getAttribute('data-set-theme'));
            });
        });

        document.querySelectorAll('.swatch[data-accent]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                applyAccent(btn.getAttribute('data-accent'));
            });
        });

        document.querySelectorAll('[data-set-anim]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var next = root.getAttribute('data-anim') === 'off' ? 'on' : 'off';
                applyAnim(next);
                if (next === 'on') initReveal(true);
            });
        });

        // Пипетка: свой акцентный цвет
        document.querySelectorAll('[data-custom-accent]').forEach(function (picker) {
            picker.addEventListener('input', function () {
                applyCustomAccent(picker.value, true);
            });
            picker.addEventListener('change', function () {
                applyCustomAccent(picker.value);
            });
        });

        // Пипетка: свой цвет фона
        document.querySelectorAll('[data-custom-bg]').forEach(function (picker) {
            picker.addEventListener('input', function () {
                applyCustomBg(picker.value, true);
            });
            picker.addEventListener('change', function () {
                applyCustomBg(picker.value);
            });
        });

        // Сбросить кастомный фон
        document.querySelectorAll('[data-reset-bg]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                resetCustomBg();
            });
        });

        document.querySelectorAll('[data-reset-prefs]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                clearStoredCustom();
                clearInlineAccent();
                clearInlineBg();
                applyTheme('dark', true);
                applyAccent('orange', true);
                applyAnim('on', true);
                toast('Настройки сброшены до значений по умолчанию', 'fa-solid fa-rotate-left');
            });
        });
    }

    /* ---------------- Быстрое переключение темы в шапке ---------------- */
    function initThemeToggle() {
        document.querySelectorAll('#themeToggle').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
                applyTheme(next);
            });
        });
    }

    /* ---------------- Запуск ---------------- */
    function boot() {
        syncSettingsUI();
        initHeaderScroll();
        initRipple();
        initNotifications();
        initUserMenu();
        initThemeToggle();
        initSettingsPage();
        initReveal(false);
        initTilt();
        initPageTransition();

        // мобильное меню (кнопки в разметке вызывают toggleMobileDrawer)
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                var drawer = document.getElementById('mobileDrawer');
                if (drawer && drawer.classList.contains('active')) window.toggleMobileDrawer();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }

    // expose для отладки
    window.MangaSpace = {
        applyTheme: applyTheme,
        applyAccent: applyAccent,
        applyAnim: applyAnim,
        toast: toast
    };
})();
