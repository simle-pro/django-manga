/* MangaSpace — раннее применение сохранённых настроек (без мигания темы) */
(function () {
    function hexToRgb(hex) {
        hex = String(hex || '').replace('#', '');
        if (hex.length === 3) hex = hex.split('').map(function (c) { return c + c; }).join('');
        var num = parseInt(hex, 16);
        if (isNaN(num)) return null;
        return [(num >> 16) & 255, (num >> 8) & 255, num & 255];
    }

    function shadeHex(hex, factor) {
        var rgb = hexToRgb(hex);
        if (!rgb) return hex;
        var out = rgb.map(function (c) {
            return Math.max(0, Math.min(255, Math.round(factor < 0 ? c * (1 + factor) : c + (255 - c) * factor)));
        });
        return '#' + out.map(function (c) { return ('0' + c.toString(16)).slice(-2); }).join('');
    }

    function normalizeHex(hex) {
        hex = String(hex || '').trim();
        if (hex && hex.charAt(0) !== '#') hex = '#' + hex;
        return /^#[0-9a-fA-F]{6}$/.test(hex) ? hex.toLowerCase() : null;
    }

    try {
        var theme = localStorage.getItem('ms-theme');
        var accent = localStorage.getItem('ms-accent');
        var anim = localStorage.getItem('ms-anim');
        var accentCustom = normalizeHex(localStorage.getItem('ms-accent-custom'));
        var bgCustom = normalizeHex(localStorage.getItem('ms-bg-custom'));
        var root = document.documentElement;

        root.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
        root.setAttribute('data-accent', accentCustom ? 'custom' : (accent || 'orange'));
        root.setAttribute('data-anim', anim === 'off' ? 'off' : 'on');

        if (accentCustom) {
            var rgb = hexToRgb(accentCustom);
            root.style.setProperty('--accent', accentCustom);
            root.style.setProperty('--accent-rgb', rgb.join(', '));
            root.style.setProperty('--accent-hover', shadeHex(accentCustom, -0.15));
            root.style.setProperty('--accent-strong', shadeHex(accentCustom, -0.28));
            root.style.setProperty('--accent-2', shadeHex(accentCustom, 0.25));
        }

        if (bgCustom) {
            root.style.setProperty('--bg-body', bgCustom);
        }
    } catch (e) {
        document.documentElement.setAttribute('data-theme', 'dark');
        document.documentElement.setAttribute('data-accent', 'orange');
        document.documentElement.setAttribute('data-anim', 'on');
    }
})();
