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
});
