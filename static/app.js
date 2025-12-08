const API = '/api';
let state = {
    settings: [],
    logOffset: 0,
    logLimit: 50,
    logLoading: false,
    logFilter: '',
    logSearch: '',
    currentCam: null
};

// --- INIT ---
function init() {
    setupNav();
    setupLogs();
    
    // Persian Date Picker
    $(document).ready(function() {
        $('.pdate').pDatepicker({
            format: 'YYYY/MM/DD HH:mm',
            timePicker: { enabled: true },
            initialValue: false
        });
    });

    // Auto-load dash
    nav('dash');
    setInterval(fetchDash, 5000);
}

// --- NAVIGATION ---
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('minimized');
}

function nav(target) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    
    document.getElementById(target).classList.add('active');
    document.querySelectorAll(`[data-target="${target}"]`).forEach(n => n.classList.add('active'));
    
    if(target === 'dash') fetchDash();
    if(target === 'logs') loadLogs(true);
    if(target === 'settings') loadSettings();
}

function setupNav() {
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => nav(btn.dataset.target));
    });
}

function jumpToSection(id) {
    if(!id) return;
    const el = document.getElementById(id);
    if(el) el.scrollIntoView({ behavior: 'smooth' });
}

// --- DASHBOARD ---
async function fetchDash() {
    const res = await fetch(`${API}/cameras`);
    const cams = await res.json();
    
    // Stats
    const on = cams.filter(c => c.status === 'Online').length;
    const off = cams.length - on;
    const statsHtml = `<span style="color:var(--success)">${on} Online</span> • <span style="color:var(--danger)">${off} Offline</span>`;
    
    const sbStats = document.getElementById('sidebar-stats');
    if(sbStats) sbStats.innerHTML = `
        <div style="padding: 0 10px">
            <div style="font-size:24px; font-weight:700">${cams.length}</div>
            <div style="color:var(--text-dim)">Total Cameras</div>
            <div style="margin-top:5px; font-size:11px">${statsHtml}</div>
        </div>`;
        
    document.getElementById('mobile-stats').innerHTML = `${cams.length} Total • ${off} Down`;

    // Grouping
    const groups = {};
    cams.forEach(c => { if(!groups[c.nvr_ip]) groups[c.nvr_ip] = []; groups[c.nvr_ip].push(c); });
    const container = document.getElementById('nvr-container');
    container.innerHTML = '';
    
    Object.keys(groups).sort((a,b) => parseInt(a.split('.').pop()) - parseInt(b.split('.').pop())).forEach(ip => {
        const list = groups[ip];
        const nvrNum = ip.split('.').pop();
        const nvrOn = list.filter(c => c.status === 'Online').length;
        
        let cards = '';
        list.sort((a,b) => parseInt(a.channel_id) - parseInt(b.channel_id)).forEach(c => {
            const st = c.status === 'Online' ? 'online' : 'offline';
            const json = encodeURIComponent(JSON.stringify(c));
            cards += `
            <div class="cam-card ${st} imp-${c.importance}" onclick="openCam('${json}')">
                <div class="cam-name">${c.name}</div>
            </div>`;
        });

        container.insertAdjacentHTML('beforeend', `
            <div class="nvr-group">
                <div class="nvr-header" onclick="this.nextElementSibling.hidden = !this.nextElementSibling.hidden">
                    <div class="nvr-title">
                        <span class="material-symbols-rounded">dns</span>
                        <span>NVR ${nvrNum}</span>
                        <span class="nvr-ip">${ip}</span>
                    </div>
                    <div class="nvr-counts">${nvrOn}/${list.length}</div>
                </div>
                <div class="cam-grid">${cards}</div>
            </div>`);
    });
}

// --- LOGS ---
function setupLogs() {
    // Search
    let timer;
    document.getElementById('logSearch').addEventListener('keyup', (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => { state.logSearch = e.target.value; loadLogs(true); }, 500);
    });

    // Filters
    document.querySelectorAll('.chip').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            state.logFilter = btn.dataset.filter;
            loadLogs(true);
        });
    });

    // Infinite Scroll
    document.getElementById('logScroll').addEventListener('scroll', (e) => {
        if(e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 50) loadLogs();
    });
}

async function loadLogs(reset = false) {
    if(reset) {
        state.logOffset = 0;
        document.getElementById('log-list').innerHTML = '';
        state.logLoading = false;
    }
    if(state.logLoading) return;
    state.logLoading = true;
    document.getElementById('logLoader').style.display = 'block';

    const url = `${API}/logs?limit=${state.logLimit}&offset=${state.logOffset}&q=${state.logFilter || state.logSearch}`;
    const res = await fetch(url);
    const logs = await res.json();
    state.logLoading = false;
    document.getElementById('logLoader').style.display = 'none';

    if(logs.length > 0) {
        state.logOffset += logs.length;
        const html = logs.map(l => {
            const isErr = ['Error','Failed','Offline'].includes(l.state);
            const clr = isErr ? 'state-err' : 'state-ok';
            // Mobile optimized row
            const detail = l.details.replace(/(\d+m)/, '<span style="color:var(--danger);font-weight:bold">$1</span>');
            
            // Responsive Table Row
            if(window.innerWidth > 768) {
                return `<div class="log-row">
                    <div class="log-time">${l.shamsi_date}</div>
                    <div class="log-type">${l.log_type}</div>
                    <div class="log-state ${clr}">${l.state}</div>
                    <div class="log-detail">${detail}</div>
                </div>`;
            } else {
                return `<div class="log-row">
                    <div class="log-top">
                        <span class="log-type">${l.log_type}</span>
                        <span class="log-time">${l.shamsi_date}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:center">
                         <span class="log-state ${clr}">${l.state}</span>
                         <span style="font-size:12px; color:#ccc">${detail}</span>
                    </div>
                </div>`;
            }
        }).join('');
        document.getElementById('log-list').insertAdjacentHTML('beforeend', html);
    }
}

// --- REPORTS ---
function setPreset(h) {
    // We set values on the underlying input for the persian datepicker to pick up? 
    // Actually the persian datepicker library manages its own internal state.
    // For simplicity, we calculate timestamps directly here for "Preset" buttons
    // and pass them to generation, ignoring the input UI for presets.
    const end = Date.now()/1000;
    const start = end - (h * 3600);
    doGenReport(start, end);
}

function genReport() {
    // Get values from pDatepicker inputs (timestamps)
    const t1 = $('#startDt').pDatepicker('getState').selected.unixDate;
    const t2 = $('#endDt').pDatepicker('getState').selected.unixDate;
    if(!t1 || !t2) return alert("Select range");
    doGenReport(t1/1000, t2/1000);
}

async function doGenReport(s, e) {
    const list = document.getElementById('rep-list');
    list.innerHTML = '<div style="text-align:center; padding:20px">Analyzing...</div>';
    
    const res = await fetch(`${API}/reports/generate?start=${s}&end=${e}`);
    const data = await res.json();
    
    if(data.length === 0) {
        list.innerHTML = '<div class="empty-state"><span class="material-symbols-rounded">check_circle</span><p>No downtime found.</p></div>';
        return;
    }

    const max = Math.max(...data.map(i => i.mins));
    list.innerHTML = data.map(i => {
        const pct = (i.mins / max) * 100;
        return `
        <div class="rep-item">
            <div class="rep-bar-wrap">
                <div style="display:flex; justify-content:space-between; margin-bottom:4px; font-size:13px">
                    <span style="font-weight:600">${i.name}</span>
                </div>
                <div class="rep-bar-bg"><div class="rep-bar-fill" style="width:${pct}%"></div></div>
            </div>
            <div class="rep-val">${i.mins}m</div>
        </div>`;
    }).join('');
}

// --- SETTINGS ---
async function loadSettings() {
    const sRes = await fetch(`${API}/settings`);
    state.settings = await sRes.json();
    renderConfig();
    
    const cRes = await fetch(`${API}/config/csv`);
    document.getElementById('csvEditor').value = await cRes.text();
    
    const nRes = await fetch(`${API}/nvrs`);
    const nvrs = await nRes.json();
    document.getElementById('nvr-list').innerHTML = nvrs.map(n => `
        <div class="list-item">
            <span>${n.ip} <span style="color:var(--text-dim)">(${n.user})</span></span>
            <button class="btn-icon" onclick="delNVR('${n.ip}')"><span class="material-symbols-rounded" style="color:var(--danger)">delete</span></button>
        </div>`).join('');
}

function renderConfig() {
    const container = document.getElementById('config-forms');
    container.innerHTML = '';
    const groups = {
        'Email': ['MAIL_ENABLED', 'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USER', 'MAIL_PASS', 'MAIL_RECIPIENTS', 'MAIL_FIRST_ALERT_DELAY_MINUTES', 'MAIL_LOW_IMPORTANCE_DELAY_MINUTES', 'MAIL_ALERT_FREQUENCY_MINUTES', 'MAIL_MUTE_AFTER_N_ALERTS'],
        'Telegram': ['TELEGRAM_ENABLED', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_IDS', 'TELEGRAM_PROXY', 'TELEGRAM_FIRST_ALERT_DELAY_MINUTES', 'TELEGRAM_LOW_IMPORTANCE_DELAY_MINUTES', 'TELEGRAM_ALERT_FREQUENCY_MINUTES', 'TELEGRAM_MUTE_AFTER_N_ALERTS']
    };

    for(const [title, keys] of Object.entries(groups)) {
        let html = `<div class="card" id="sec-${title.toLowerCase()}"><div class="card-header"><h3>${title}</h3><button class="btn btn-sm btn-outline" onclick="testConn('${title.toLowerCase()}')">Test</button></div><div style="padding:15px">`;
        
        keys.forEach(k => {
            const item = state.settings.find(s => s.key === k); if(!item) return;
            const label = k.split('_').slice(1).join(' ').toLowerCase().replace(/\b\w/g, c=>c.toUpperCase());
            
            if(k.endsWith('ENABLED')) {
                html += `
                <div class="config-row">
                    <span class="config-label">${label}</span>
                    <label class="toggle-switch">
                        <input type="checkbox" id="${k}" ${item.value==='true'?'checked':''}>
                        <span class="slider"></span>
                    </label>
                </div>`;
            } else {
                html += `
                <div class="config-row">
                    <span class="config-label">${label}</span>
                    <div class="config-input-wrap">
                        <input class="input" id="${k}" value="${item.value||''}" type="${k.includes('PASS')||k.includes('TOKEN')?'password':'text'}">
                    </div>
                </div>`;
            }
        });
        html += `</div></div>`;
        container.innerHTML += html;
    }
}

async function saveAll() {
    for (const s of state.settings) {
        const el = document.getElementById(s.key);
        if (el) {
            let val = el.value;
            if (el.type === 'checkbox') val = el.checked ? 'true' : 'false';
            if (val !== s.value) await fetch(`${API}/settings/${s.key}`, { method: 'PUT', headers: {'Content-Type':'application/json'}, body: JSON.stringify({key: s.key, value: val}) });
        }
    }
    await fetch(`${API}/config/csv`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({content: document.getElementById('csvEditor').value}) });
    showToast('Settings Saved');
}

async function apply() { await saveAll(); await fetch(`${API}/monitor/restart`, {method:'POST'}); showToast('Monitor Restarted'); location.reload(); }
async function testConn(type) { try { const res = await fetch(`/api/test/${type}`, {method:'POST'}); if(res.ok) alert('Passed'); else alert('Failed'); } catch(e){alert(e);} }
async function addNVR() { const ip=document.getElementById('nvrIp').value; const u=document.getElementById('nvrUser').value; const p=document.getElementById('nvrPass').value; await fetch(`${API}/nvrs`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ip, user:u, password:p||null, enabled:true})}); loadSettings(); }
async function delNVR(ip) { if(confirm('Delete?')) await fetch(`${API}/nvrs/${ip}`, {method:'DELETE'}); loadSettings(); }

function showToast(msg) { const t = document.getElementById('toast'); t.textContent = msg; t.classList.add('show'); setTimeout(() => t.classList.remove('show'), 2000); }

// --- MODAL ---
async function openCam(json) {
    const c = JSON.parse(decodeURIComponent(json));
    state.currentCam = c;
    document.getElementById('m-name').textContent = c.name;
    document.getElementById('m-ip').textContent = c.ip;
    document.getElementById('m-nvr').textContent = `NVR ${c.nvr_ip} / Ch ${c.channel_id}`;
    document.getElementById('m-status').textContent = c.status;
    document.getElementById('m-status').style.color = c.status === 'Online' ? 'var(--success)' : 'var(--danger)';
    document.getElementById('m-last').textContent = c.last_online ? new Date(c.last_online).toLocaleTimeString() : '-';
    
    // Highlight Importance
    document.querySelectorAll('.imp-selector .btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-imp-${c.importance}`).classList.add('active');

    document.getElementById('modalBackdrop').classList.add('open');
    
    const res = await fetch(`${API}/stats/${c.id}`);
    const s = await res.json();
    document.getElementById('m-d1').textContent = s.down_1h + 'm';
    document.getElementById('m-d24').textContent = s.down_24h + 'm';
}
async function setImp(val) {
    if(!state.currentCam) return;
    await fetch(`${API}/cameras/${state.currentCam.id}`, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify({importance:val}) });
    document.querySelectorAll('.imp-selector .btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-imp-${val}`).classList.add('active');
    loadDash();
}
function closeModal() { document.getElementById('modalBackdrop').classList.remove('open'); }

// Init
init();