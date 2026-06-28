// ─── Alerts auto-dismiss ─────────────────────────────────────────────────────
document.querySelectorAll('.alert[data-auto-dismiss]').forEach(el => {
  setTimeout(() => el.remove(), 5000);
});

// ─── Cupón validación en tiempo real ────────────────────────────────────────
const couponInput = document.getElementById('coupon-input');
const couponStatus = document.getElementById('coupon-status');
const priceDisplay = document.getElementById('price-display');

if (couponInput) {
  let debounceTimer;
  couponInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(async () => {
      const code = couponInput.value.trim();
      if (!code) { couponStatus.textContent = ''; return; }

      const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
      const res = await fetch('/payments/validate-coupon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
        body: JSON.stringify({ code }),
      });
      const data = await res.json();
      if (data.valid) {
        const label = data.type === 'percent'
          ? `${data.value}% de descuento`
          : `$${data.value} de descuento`;
        couponStatus.innerHTML = `<span class="text-success">✅ ${label} - ${data.description}</span>`;
      } else {
        couponStatus.innerHTML = `<span class="text-danger">❌ Cupón inválido</span>`;
      }
    }, 500);
  });
}

// ─── Toggle dark sidebar on mobile ──────────────────────────────────────────
const menuBtn = document.getElementById('menu-toggle');
const sidebar = document.querySelector('.sidebar');
if (menuBtn && sidebar) {
  menuBtn.addEventListener('click', () => sidebar.classList.toggle('open'));
}

// ─── Confirm dialogs ─────────────────────────────────────────────────────────
document.querySelectorAll('[data-confirm]').forEach(el => {
  el.addEventListener('click', e => {
    if (!confirm(el.dataset.confirm)) e.preventDefault();
  });
});

// ─── Fetch toggle helpers (admin) ────────────────────────────────────────────
async function apiPost(url, data = {}) {
  const csrf = document.querySelector('meta[name=csrf-token]')?.content || '';
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: JSON.stringify(data),
  });
  return res.json();
}

// ─── Admin: inline credit grant ──────────────────────────────────────────────
const addCreditsForm = document.getElementById('add-credits-form');
if (addCreditsForm) {
  addCreditsForm.addEventListener('submit', async e => {
    e.preventDefault();
    const userId = addCreditsForm.dataset.userId;
    const amount = parseInt(document.getElementById('credit-amount').value);
    const note = document.getElementById('credit-note').value;
    const data = await apiPost(`/admin/users/${userId}/add-credits`, { amount, note });
    if (data.credits !== undefined) {
      document.getElementById('credits-display').textContent = data.credits;
      document.getElementById('credit-amount').value = '';
      showToast('Créditos agregados ✅');
    }
  });
}

// ─── Toast ────────────────────────────────────────────────────────────────────
function showToast(msg, type = 'success') {
  const t = document.createElement('div');
  t.className = `alert alert-${type}`;
  t.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;min-width:260px;animation:fadeIn .2s';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}
