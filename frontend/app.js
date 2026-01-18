// --- Configuration ---
const API = {
    USER: 'http://localhost:5001',
    ACCOUNT: 'http://localhost:5002',
    TRANS: 'http://localhost:5003'
};

// --- State ---
let currentToken = localStorage.getItem('token');
let currentUser = null;
let currentAccountId = null;

// --- Initialization ---
document.addEventListener('DOMContentLoaded', () => {
    if (currentToken) {
        showDashboard();
    } else {
        showAuth();
    }

    // Attach form listeners
    document.getElementById('login-form').addEventListener('submit', handleLogin);
    document.getElementById('register-form').addEventListener('submit', handleRegister);
});

// --- Auth Functions ---
async function handleLogin(e) {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;

    try {
        const res = await fetch(`${API.USER}/users/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'התחברות נכשלה');

        currentToken = data.token; // הנחה שהשרת מחזיר { token: "..." }
        localStorage.setItem('token', currentToken);
        
        // אופציונלי: שמירת שם משתמש אם השרת מחזיר אותו, או פענוח ה-JWT
        document.getElementById('user-greeting').innerText = `שלום, ${email}`;
        
        showDashboard();
    } catch (err) {
        showAlert(err.message, 'danger');
    }
}

async function handleRegister(e) {
    e.preventDefault();
    const data = {
        first_name: document.getElementById('reg-first').value,
        last_name: document.getElementById('reg-last').value,
        email: document.getElementById('reg-email').value,
        password: document.getElementById('reg-password').value
    };

    try {
        const res = await fetch(`${API.USER}/users/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!res.ok) throw new Error('הרשמה נכשלה');
        
        showAlert('ההרשמה הצליחה! נא להתחבר.', 'success');
        // מעבר לטאב התחברות
        const loginTab = new bootstrap.Tab(document.querySelector('#authTabs button[data-bs-target="#login-tab"]'));
        loginTab.show();
    } catch (err) {
        showAlert(err.message, 'danger');
    }
}

function logout() {
    localStorage.removeItem('token');
    currentToken = null;
    currentAccountId = null;
    showAuth();
}

// --- Dashboard Functions ---
async function loadAccounts() {
    try {
        const res = await fetchWithAuth(`${API.ACCOUNT}/accounts`);
        // הנחה: השרת מחזיר מערך של חשבונות או אובייקט עם מערך
        const accounts = Array.isArray(res) ? res : (res.accounts || []); 
        
        const container = document.getElementById('accounts-list');
        container.innerHTML = '';

        if (accounts.length === 0) {
            container.innerHTML = '<div class="col-12 text-center text-muted">אין לך חשבונות עדיין.</div>';
            return;
        }

        accounts.forEach(acc => {
            const card = document.createElement('div');
            card.className = 'col-md-4 mb-3';
            card.innerHTML = `
                <div class="card shadow-sm account-card border-start border-4 border-primary" onclick="openAccountDetails('${acc.id}')">
                    <div class="card-body">
                        <h5 class="card-title text-primary">${acc.type.toUpperCase()}</h5>
                        <p class="card-text text-muted mb-1">...${acc.account_number.slice(-4)}</p>
                        <h3 class="card-text">${formatMoney(acc.balance_cents)}</h3>
                    </div>
                </div>
            `;
            container.appendChild(card);
        });
    } catch (err) {
        console.error(err);
        showAlert('שגיאה בטעינת חשבונות', 'danger');
    }
}

async function createAccount() {
    const type = document.getElementById('new-acc-type').value;
    try {
        await fetchWithAuth(`${API.ACCOUNT}/accounts`, 'POST', { type });
        bootstrap.Modal.getInstance(document.getElementById('createAccountModal')).hide();
        showAlert('חשבון נוצר בהצלחה', 'success');
        loadAccounts();
    } catch (err) {
        showAlert('שגיאה ביצירת חשבון', 'danger');
    }
}

function openCreateAccountModal() {
    new bootstrap.Modal(document.getElementById('createAccountModal')).show();
}

// --- Account Details Functions ---
async function openAccountDetails(accountId) {
    currentAccountId = accountId;
    showSection('account-details-view');
    await loadAccountData();
    await loadHistory();
}

async function loadAccountData() {
    try {
        const acc = await fetchWithAuth(`${API.ACCOUNT}/accounts/${currentAccountId}`);
        document.getElementById('detail-acc-number').innerText = `חשבון ${acc.account_number}`;
        document.getElementById('detail-acc-type').innerText = acc.type.toUpperCase();
        document.getElementById('detail-acc-balance').innerText = formatMoney(acc.balance_cents);
    } catch (err) {
        showAlert('לא ניתן לטעון פרטי חשבון', 'danger');
    }
}

async function loadHistory() {
    try {
        const history = await fetchWithAuth(`${API.TRANS}/transactions/${currentAccountId}/history`);
        const tbody = document.getElementById('transactions-table-body');
        tbody.innerHTML = '';
        
        // הנחה: history הוא מערך. אם לא, תתאים לפי התשובה של השרת
        const txs = Array.isArray(history) ? history : (history.transactions || []);

        txs.forEach(tx => {
            const isIncoming = tx.to_bank_account_id === currentAccountId;
            const amountClass = isIncoming ? 'amount-plus' : 'amount-minus';
            const sign = isIncoming ? '+' : '-';
            const type = tx.from_bank_account_id ? 'העברה' : (isIncoming ? 'הפקדה' : 'משיכה');
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${new Date(tx.created_at).toLocaleString('he-IL')}</td>
                <td>${type}</td>
                <td>${isIncoming ? (tx.from_bank_account_id || '-') : (tx.to_bank_account_id || '-')}</td>
                <td class="${amountClass}" dir="ltr">${sign}${formatMoney(tx.amount)}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        console.error("History load error", err);
    }
}

// --- Transaction Functions ---
function openActionModal(actionType) {
    const modal = new bootstrap.Modal(document.getElementById('transactionModal'));
    document.getElementById('trans-type').value = actionType;
    
    const titles = { 'deposit': 'הפקדת כסף', 'withdraw': 'משיכת כסף', 'transfer': 'העברת כספים' };
    document.getElementById('trans-modal-title').innerText = titles[actionType];
    
    // הצג/הסתר שדה יעד
    document.getElementById('dest-account-group').style.display = (actionType === 'transfer') ? 'block' : 'none';
    document.getElementById('trans-amount').value = '';
    document.getElementById('trans-dest-acc').value = '';
    
    modal.show();
}

async function submitTransaction() {
    const type = document.getElementById('trans-type').value;
    const amountDollars = parseFloat(document.getElementById('trans-amount').value);
    const destAccount = document.getElementById('trans-dest-acc').value;
    
    if (!amountDollars || amountDollars <= 0) {
        alert("נא להזין סכום חוקי");
        return;
    }

    // המרה לסנטים
    const amountCents = Math.round(amountDollars * 100);
    
    let url, body;

    if (type === 'deposit') {
        url = `${API.TRANS}/transactions/${currentAccountId}/deposit`;
        body = { amount: amountCents };
    } else if (type === 'withdraw') {
        url = `${API.TRANS}/transactions/${currentAccountId}/withdraw`;
        body = { amount: amountCents };
    } else if (type === 'transfer') {
        url = `${API.TRANS}/transactions/${currentAccountId}/transfer`;
        // שים לב: הפרמטרים צריכים להתאים בדיוק למה שה-API שלך מצפה
        body = { to_account_id: destAccount, amount: amountCents };
    }

    try {
        await fetchWithAuth(url, 'POST', body);
        bootstrap.Modal.getInstance(document.getElementById('transactionModal')).hide();
        showAlert('הפעולה בוצעה בהצלחה!', 'success');
        
        // רענון נתונים
        await loadAccountData();
        await loadHistory();
    } catch (err) {
        showAlert(`שגיאה בביצוע הפעולה: ${err.message}`, 'danger');
    }
}

// --- Helpers ---
async function fetchWithAuth(url, method = 'GET', body = null) {
    const headers = {
        'Authorization': `Bearer ${currentToken}`,
        'Content-Type': 'application/json'
    };
    
    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    const res = await fetch(url, options);
    const data = await res.json();
    
    if (!res.ok) {
        // אם הטוקן פג תוקף
        if (res.status === 401) logout();
        throw new Error(data.message || data.error || 'Request failed');
    }
    return data;
}

function formatMoney(cents) {
    return (cents / 100).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

function showAlert(msg, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
        ${msg}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    document.getElementById('alert-container').appendChild(alertDiv);
    setTimeout(() => alertDiv.remove(), 3000);
}

function showSection(sectionId) {
    ['auth-view', 'dashboard-view', 'account-details-view'].forEach(id => {
        document.getElementById(id).style.display = 'none';
    });
    document.getElementById(sectionId).style.display = 'block'; // או flex במידת הצורך
}

function showAuth() {
    showSection('auth-view');
    document.getElementById('nav-user-info').style.setProperty('display', 'none', 'important');
}

function showDashboard() {
    showSection('dashboard-view');
    document.getElementById('nav-user-info').style.setProperty('display', 'flex', 'important');
    loadAccounts();
}