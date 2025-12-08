const API = '/api';
let state = {
    settings: [],
    logs: [],
    logOffset: 0,
    logFilter: '',
    logLoading: false,
    currentCam: null
};

// --- NAVIGATION ---
function initNav() {
    const tabs = document.querySelectorAll('.nav-item');
    tabs.forEach(t => {
        t.addEventListener('click', () => {
            const target = t.dataset.target;
            document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            
            document.getElementById(target).classList.add('active');
            // Activate both desktop and mobile buttons
            document.querySelectorAll(`[data-target="${target}"]`).forEach(n => n.classList.add('active'));
            
            if(target === 'dash') loadDash();
            if(target === 'logs') loadLogs(true);
            if(target === 'settings') loadSettings();
        });
    });
}

// --- DASHBOARD ---
async function loadDash() {
    const res = await fetch(`${API}/cameras`);
    const cams = await res.json();
    
    // Stats
    const on = cams.filter(c => c.status === 'Online').length;
    const off = cams.length - on;
    const statsHtml = `<span class="stat-pill ok">${on} Online</span> <span class="stat-pill err">${off} Offline</span>`;
    document.getElementById('sidebar-stats').innerHTML = statsHtml;
    document.getElementById('mobile-stats').innerHTML = statsHtml;

    // Grouping
    const groups = {};
    cams.forEach(c => { if(!groups[c.nvr_ip]) groups[c.nvr_ip] = []; groups[c.nvr_ip].push(c); });
    
    const container = document.getElementById('nvr-container');
    container.innerHTML = '';
    
    // Sort NVRs by IP suffix
    const sortedIps = Object.keys(groups).sort((a,b) => parseInt(a.split('.').pop()) - parseInt(b.split('.').pop()));

    sortedIps.forEach(ip => {
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
                <div class="cam-meta"><span>N${nvrNum}</span><span>C${c.channel_id}</span></div>
            </div>`;
        });

        const html = `
        <div class="nvr-header" onclick="this.nextElementSibling.hidden = !this.nextElementSibling.hidden">
            <div class="nvr-title">
                <span class="material-icons-round">dns</span>
                <span>NVR ${nvrNum}</span>
                <span class="nvr-ip">${ip}</span>
            </div>
            <div class="nvr-counts">${nvrOn}/${list.length}</div>
        </div>
        <div class="cam-grid">${cards}</div>`;
        container.insertAdjacentHTML('beforeend', html);
    });
}

document.getElementById('btn-sync').onclick = loadDash;

// --- LOGS ---
async function loadLogs(reset = false) {
    if(reset) {
        state.logOffset = 0;
        document.getElementById('log-list').innerHTML = '';
        state.logLoading = false;
    }
    if(state.logLoading) return;
    
    state.logLoading = true;
    document.getElementById('logLoader').style.display = 'block';
    
    const q = document.getElementById('logSearch').value;
    const url = `${API}/logs?limit=50&offset=${state.logOffset}&q=${state.logFilter || q}`;
    
    const res = await fetch(url);
    const logs = await res.json();
    state.logLoading = false;
    document.getElementById('logLoader').style.display = 'none';
    
    if(logs.length > 0) {
        state.logOffset += logs.length;
        const html = logs.map(l => {
            const isErr = ['Error','Failed','Offline'].includes(l.state);
            const clr = isErr ? 'var(--danger)' : 'var(--success)';
            return `<tr>
                <td class="log-time">${l.shamsi_date}</td>
                <td><span class="stat-pill" style="font-size:11px">${l.log_type}</span></td>
                <td style="color:${clr}; font-weight:600">${l.state}</td>
                <td>${l.details}</td>
            </tr>`;
        }).join('');
        document.getElementById('log-list').insertAdjacentHTML('beforeend', html);
    }
}

// Log Filters
document.querySelectorAll('.chip').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        state.logFilter = btn.dataset.filter;
        loadLogs(true);
    });
});

// Search Debounce
let timer;
document.getElementById('logSearch').addEventListener('keyup', () => {
    clearTimeout(timer);
    timer = setTimeout(() => loadLogs(true), 500);
});

// Scroll Infinite
document.getElementById('logScroll').addEventListener('scroll', (e) => {
    if(e.target.scrollTop + e.target.clientHeight >= e.target.scrollHeight - 50) loadLogs();
});

// --- REPORTS ---
function setPreset(h) {
    const end = new Date();
    const start = new Date(end.getTime() - (h * 60 * 60 * 1000));
    // Local ISO adjustment
    start.setMinutes(start.getMinutes() - start.getTimezoneOffset());
    end.setMinutes(end.getMinutes() - end.getTimezoneOffset());
    document.getElementById('startDt').value = start.toISOString().slice(0,16);
    document.getElementById('endDt').value = end.toISOString().slice(0,16);
}

async function genReport() {
    const s = new Date(document.getElementById('startDt').value).getTime() / 1000;
    const e = new Date(document.getElementById('endDt').value).getTime() / 1000;
    if(!s || !e) return alert("Select dates");

    const con = document.getElementById('rep-list');
    con.innerHTML = '<div class="loader" style="display:block">Analyzing...</div>';
    document.getElementById('rep-empty').style.display = 'none';

    const res = await fetch(`${API}/reports/generate?start=${s}&end=${e}`);
    const data = await res.json();
    
    if(data.length === 0) {
        con.innerHTML = '<div class="empty-state">No downtime found in this range.</div>';
        return;
    }

    const max = Math.max(...data.map(i => i.mins));
    con.innerHTML = data.map(i => {
        const pct = (i.mins / max) * 100;
        return `
        <div class="rep-row">
            <div class="rep-info">
                <span class="rep-name">${i.name}</span>
                <div class="rep-bar"><div class="rep-fill" style="width:${pct}%"></div></div>
            </div>
            <div class="rep-val">${i.mins}m</div>
        </div>`;
    }).join('');
}

// --- SETTINGS ---
async function loadSettings() {
    // 1. Configs
    const sRes = await fetch(`${API}/settings`);
    state.settings = await sRes.json();
    const container = document.getElementById('config-forms');
    container.innerHTML = '';
    
    const groups = {
        'Email': ['MAIL_ENABLED', 'MAIL_SERVER', 'MAIL_PORT', 'MAIL_USER', 'MAIL_PASS', 'MAIL_RECIPIENTS', 'MAIL_FIRST_ALERT_DELAY_MINUTES', 'MAIL_LOW_IMPORTANCE_DELAY_MINUTES', 'MAIL_ALERT_FREQUENCY_MINUTES', 'MAIL_MUTE_AFTER_N_ALERTS'],
        'Telegram': ['TELEGRAM_ENABLED', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_IDS', 'TELEGRAM_PROXY', 'TELEGRAM_FIRST_ALERT_DELAY_MINUTES', 'TELEGRAM_LOW_IMPORTANCE_DELAY_MINUTES', 'TELEGRAM_ALERT_FREQUENCY_MINUTES', 'TELEGRAM_MUTE_AFTER_N_ALERTS']
    };
    
    // Dynamic sidebar links
    const navCon = document.getElementById('config-nav');
    navCon.innerHTML = '';

    for(const [grp, keys] of Object.entries(groups)) {
        // Add nav link
        navCon.innerHTML += `<button class="btn btn-outline" style="width:100%; text-align:left; margin-bottom:5px" onclick="document.getElementById('grp-${grp}').scrollIntoView()">${grp}</button>`;
        
        let html = `<div class="card" id="grp-${grp}"><div class="card-header"><h3>${grp}</h3><button class="btn btn-sm btn-outline" onclick="testConn('${grp.toLowerCase()}')">Test</button></div><div style="padding:15px">`;
        
        keys.forEach(k => {
            const item = state.settings.find(s => s.key === k);
            if(!item) return;
            const label = k.split('_').slice(1).join(' ').toLowerCase().replace(/\b\w/g, c=>c.toUpperCase());
            
            if(k.endsWith('ENABLED')) {
                html += `<div style="display:flex; justify-content:space-between; margin-bottom:10px; align-items:center"><span style="font-size:13px; font-weight:600; color:#aaa">${label}</span><input type="checkbox" id="${k}" ${item.value==='true'?'checked':''}></div>`;
            } else {
                html += `<div class="control-group"><label>${label}</label><input id="${k}" class="input" value="${item.value||''}" type="${k.includes('PASS')||k.includes('TOKEN')?'password':'text'}"></div>`;
            }
        });
        html += `</div></div>`;
        container.innerHTML += html;
    }

    // 2. CSV
    const cRes = await fetch(`${API}/config/csv`);
    document.getElementById('csvEditor').value = await cRes.text();

    // 3. NVRs
    const nRes = await fetch(`${API}/nvrs`);
    const nvrs = await nRes.json();
    document.getElementById('nvr-list').innerHTML = nvrs.map(n => `
        <div class="list-item">
            <span>${n.ip} <span style="color:#666">(${n.user})</span></span>
            <button class="btn-icon" style="width:24px; height:24px; border:none" onclick="delNVR('${n.ip}')"><span class="material-icons-round" style="font-size:16px; color:var(--danger)">delete</span></button>
        </div>`).join('');
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
    showToast('Saved');
}

async function apply() {
    await saveAll();
    await fetch(`${API}/monitor/restart`, { method: 'POST' });
    showToast('Monitor Restarted');
}

async function addNVR() {
    const ip = document.getElementById('nvrIp').value;
    const u = document.getElementById('nvrUser').value;
    const p = document.getElementById('nvrPass').value;
    await fetch(`${API}/nvrs`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ip, user:u, password:p||null, enabled:true}) });
    loadSettings();
}
async function delNVR(ip) { if(confirm('Delete?')) await fetch(`${API}/nvrs/${ip}`, { method:'DELETE' }); loadSettings(); }
async function testConn(type) { 
    try { const res = await fetch(`/api/test/${type}`, {method:'POST'}); if(res.ok) alert('Passed'); else alert('Failed'); } catch(e){alert(e);} 
}

function showToast(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
}

// --- MODAL ---
async function openCam(json) {
    const c = JSON.parse(decodeURIComponent(json));
    state.currentCam = c;
    document.getElementById('m-name').textContent = c.name;
    document.getElementById('m-det').textContent = `${c.ip} (NVR: ${c.nvr_ip})`;
    document.getElementById('m-status').textContent = c.status;
    document.getElementById('m-status').style.color = c.status === 'Online' ? 'var(--success)' : 'var(--danger)';
    document.getElementById('m-last').textContent = c.last_online ? new Date(c.last_online).toLocaleString() : '-';
    
    // Highlight active Importance
    document.querySelectorAll('.imp-selector .btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-imp-${c.importance}`).classList.add('active');

    document.getElementById('modalBackdrop').classList.add('open');
    
    // Fetch stats
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
    loadDash(); // Refresh bg
}

function closeModal() {
    document.getElementById('modalBackdrop').classList.remove('open');
}

// Init
initNav();
loadDash();
setInterval(loadDash, 10000);