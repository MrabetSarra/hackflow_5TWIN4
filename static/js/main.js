/**
 * HackFlow - Main Front-End JavaScript
 * Thème Sombre / Clair, Interactions, Démo Toasts, Sidebar Toggle & Countdown
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialisation des tooltips Bootstrap
  const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
  tooltipTriggerList.map((tooltipTriggerEl) => new bootstrap.Tooltip(tooltipTriggerEl));

  // 2. Gestion Globale du Thème Sombre / Clair (Persistant)
  const applyTheme = (theme) => {
    document.documentElement.setAttribute('data-bs-theme', theme);
    localStorage.setItem('hackflow-theme', theme);

    // Mettre à jour tous les boutons / icônes de thème sur la page
    document.querySelectorAll('.theme-toggle-btn').forEach((btn) => {
      const sunIcon = btn.querySelector('.theme-icon-light');
      const moonIcon = btn.querySelector('.theme-icon-dark');
      const textEl = btn.querySelector('.theme-text');

      if (theme === 'dark') {
        if (sunIcon) sunIcon.classList.remove('d-none');
        if (moonIcon) moonIcon.classList.add('d-none');
        if (textEl) textEl.textContent = 'Clair';
        btn.setAttribute('title', 'Passer en thème clair');
      } else {
        if (sunIcon) sunIcon.classList.add('d-none');
        if (moonIcon) moonIcon.classList.remove('d-none');
        if (textEl) textEl.textContent = 'Sombre';
        btn.setAttribute('title', 'Passer en thème sombre');
      }
    });
  };

  // Récupérer le thème actuel ou le thème système
  const currentTheme = document.documentElement.getAttribute('data-bs-theme') || 
    localStorage.getItem('hackflow-theme') || 
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  applyTheme(currentTheme);

  // Attacher l'écouteur à tous les sélecteurs de thème
  document.querySelectorAll('.theme-toggle-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      const current = document.documentElement.getAttribute('data-bs-theme') || 'light';
      const target = current === 'dark' ? 'light' : 'dark';
      applyTheme(target);
    });
  });

  // 3. Toggle de la Sidebar Mobile
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.querySelector('.app-sidebar');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      sidebar.classList.toggle('show');
    });

    document.addEventListener('click', (e) => {
      if (!sidebar.contains(e.target) && !sidebarToggle.contains(e.target) && sidebar.classList.contains('show')) {
        sidebar.classList.remove('show');
      }
    });
  }

  // 4. Toasts de notification pour les actions visuelles (Démo)
  const showToast = (message = 'Action simulée avec succès pour la démo !', type = 'info') => {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container position-fixed top-0 end-0 p-3';
      container.style.zIndex = '9999';
      document.body.appendChild(container);
    }

    const toastEl = document.createElement('div');
    toastEl.className = 'toast align-items-center text-white bg-dark border-0 shadow-lg';
    toastEl.setAttribute('role', 'alert');
    toastEl.setAttribute('aria-live', 'assertive');
    toastEl.setAttribute('aria-atomic', 'true');
    toastEl.innerHTML = `
      <div class="d-flex">
        <div class="toast-body d-flex align-items-center gap-2">
          <i class="bi bi-info-circle-fill text-primary"></i>
          <span>${message}</span>
        </div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    `;
    container.appendChild(toastEl);
    const toast = new bootstrap.Toast(toastEl, { delay: 3500 });
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
  };

  // Attacher le toast aux boutons interactifs sans formulaire
  document.querySelectorAll('[data-demo-toast]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      const msg = btn.getAttribute('data-demo-toast') || 'Action enregistrée pour la démo HackFlow.';
      showToast(msg);
    });
  });

  // 5. Compte à rebours du Hackathon (dynamique)
  const updateDeadlineCountdowns = () => {
    document.querySelectorAll('[data-live-countdown]').forEach((element) => {
      const deadline = new Date(element.dataset.liveCountdown);
      if (Number.isNaN(deadline.getTime())) return;

      const remainingMinutes = Math.floor((deadline.getTime() - Date.now()) / 60000);
      if (remainingMinutes < 0) {
        element.textContent = element.dataset.countdownExpired || 'Deadline passed';
        return;
      }

      const hours = Math.floor(remainingMinutes / 60);
      const minutes = String(remainingMinutes % 60).padStart(2, '0');
      element.textContent = `${element.dataset.countdownPrefix || ''}${hours}h${minutes}mn`;
    });
  };
  updateDeadlineCountdowns();
  window.setInterval(updateDeadlineCountdowns, 1000);

  const hoursEl = document.getElementById('cd-hours');
  const minsEl = document.getElementById('cd-minutes');
  const secsEl = document.getElementById('cd-seconds');

  if (hoursEl && minsEl && secsEl) {
    let totalSeconds = 34 * 3600 + 42 * 60 + 15; // 34h 42m 15s restants
    setInterval(() => {
      if (totalSeconds > 0) {
        totalSeconds--;
        const h = Math.floor(totalSeconds / 3600);
        const m = Math.floor((totalSeconds % 3600) / 60);
        const s = totalSeconds % 60;
        hoursEl.textContent = String(h).padStart(2, '0');
        minsEl.textContent = String(m).padStart(2, '0');
        secsEl.textContent = String(s).padStart(2, '0');
      }
    }, 1000);
  }

  // Accessibility preferences are local to this browser and apply across the app.
  const root = document.documentElement;
  const panel = document.getElementById('displayOptionsPanel');
  const toggle = document.getElementById('displayOptionsToggle');
  if (panel && toggle) {
    const size = Number(localStorage.getItem('hackflow-a11y-size') || 0);
    root.dataset.a11ySize = String(Math.max(-1, Math.min(2, size)));
    const highContrast = localStorage.getItem('hackflow-a11y-contrast') === 'true';
    root.classList.toggle('a11y-high-contrast', highContrast);
    const contrastButton = document.getElementById('a11yContrast');
    contrastButton?.setAttribute('aria-pressed', String(highContrast));
    const displayOptions = [
      ['a11ySpacing', 'hackflow-a11y-spacing', 'a11y-more-spacing'],
      ['a11yLinks', 'hackflow-a11y-links', 'a11y-underline-links'],
      ['a11yFont', 'hackflow-a11y-font', 'a11y-simple-font'],
      ['a11yMotion', 'hackflow-a11y-motion', 'a11y-reduced-motion'],
      ['a11yFocus', 'hackflow-a11y-focus', 'a11y-strong-focus'],
      ['a11yAlign', 'hackflow-a11y-align', 'a11y-align-left'],
      ['a11yHeadings', 'hackflow-a11y-headings', 'a11y-highlight-headings'],
    ];
    displayOptions.forEach(([buttonId, storageKey, className]) => {
      const button = document.getElementById(buttonId);
      const enabled = localStorage.getItem(storageKey) === 'true';
      root.classList.toggle(className, enabled);
      button?.setAttribute('aria-pressed', String(enabled));
      button?.addEventListener('click', () => {
        const next = !root.classList.contains(className);
        root.classList.toggle(className, next);
        button.setAttribute('aria-pressed', String(next));
        localStorage.setItem(storageKey, String(next));
      });
    });

    const setPanelOpen = (open) => {
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      toggle.setAttribute('aria-label', open ? 'Close accessibility options' : 'Open accessibility options');
      if (open) panel.querySelector('button')?.focus();
    };
    toggle.addEventListener('click', () => setPanelOpen(panel.hidden));
    panel.querySelector('[data-a11y-close]')?.addEventListener('click', () => {
      setPanelOpen(false);
      toggle.focus();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !panel.hidden) {
        setPanelOpen(false);
        toggle.focus();
      }
    });
    panel.querySelectorAll('[data-a11y-size]').forEach((button) => {
      button.addEventListener('click', () => {
        const next = Number(button.dataset.a11ySize) === 0
          ? 0
          : Math.max(-1, Math.min(2, Number(root.dataset.a11ySize) + Number(button.dataset.a11ySize)));
        root.dataset.a11ySize = String(next);
        localStorage.setItem('hackflow-a11y-size', String(next));
      });
    });
    contrastButton?.addEventListener('click', () => {
      const enabled = !root.classList.contains('a11y-high-contrast');
      root.classList.toggle('a11y-high-contrast', enabled);
      contrastButton.setAttribute('aria-pressed', String(enabled));
      localStorage.setItem('hackflow-a11y-contrast', String(enabled));
    });
    document.getElementById('a11yReset')?.addEventListener('click', () => {
      root.dataset.a11ySize = '0';
      localStorage.setItem('hackflow-a11y-size', '0');
      root.classList.remove('a11y-high-contrast');
      localStorage.setItem('hackflow-a11y-contrast', 'false');
      contrastButton?.setAttribute('aria-pressed', 'false');
      displayOptions.forEach(([buttonId, storageKey, className]) => {
        root.classList.remove(className);
        localStorage.setItem(storageKey, 'false');
        document.getElementById(buttonId)?.setAttribute('aria-pressed', 'false');
      });
    });
  }
});
