document.addEventListener('DOMContentLoaded', () => {
    // ---- Tabs Logic ----
    const navBtns = document.querySelectorAll('.nav-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            navBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.style.display = 'none');
            
            btn.classList.add('active');
            const tabId = `tab-${btn.dataset.tab}`;
            document.getElementById(tabId).style.display = 'block';

            if (btn.dataset.tab === 'docs') {
                loadReadme();
            }
        });
    });

    // ---- Readme Loader ----
    let readmeLoaded = false;
    async function loadReadme() {
        if (readmeLoaded) return;
        const container = document.getElementById('readme-content');
        try {
            const res = await fetch('/api/readme');
            const data = await res.json();
            container.innerHTML = marked.parse(data.content);
            readmeLoaded = true;
        } catch (err) {
            container.innerHTML = `<p style="color:red">Failed to load documentation: ${err.message}</p>`;
        }
    }

    // ---- Parser Logic ----
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const parsingState = document.getElementById('parsing-state');
    const resultsSection = document.getElementById('results-section');
    const resetBtn = document.getElementById('reset-btn');

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
        });
    });

    dropZone.addEventListener('dragover', () => dropZone.classList.add('dragover'));
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', (e) => {
        dropZone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });
    
    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => handleFiles(e.target.files));
    resetBtn.addEventListener('click', resetApp);

    function handleFiles(files) {
        if (files.length === 0) return;
        const file = files[0];
        
        const ext = file.name.split('.').pop().toLowerCase();
        if (!['pdf', 'txt', 'md'].includes(ext)) {
            alert("Unsupported file format. Please upload PDF or TXT.");
            return;
        }
        uploadFile(file);
    }

    async function uploadFile(file) {
        dropZone.style.display = 'none';
        resultsSection.style.display = 'none';
        parsingState.style.display = 'flex';

        const formData = new FormData();
        formData.append('file', file);

        try {
            const response = await fetch('/api/parse', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Parsing failed');
            }

            const data = await response.json();
            displayResults(data);
        } catch (error) {
            alert(`Error: ${error.message}`);
            resetApp();
        }
    }

    function displayResults(data) {
        parsingState.style.display = 'none';
        resultsSection.style.display = 'flex';

        const badge = document.getElementById('status-badge');
        const summary = document.getElementById('result-summary');
        
        if (data.status === 'APPROVED') {
            badge.textContent = 'APPROVED';
            badge.className = 'badge approved';
        } else {
            badge.textContent = 'FLAGGED FOR REVIEW';
            badge.className = 'badge flagged';
        }
        summary.textContent = data.summary;

        // Issues
        const issuesContainer = document.getElementById('issues-container');
        const issuesList = document.getElementById('issues-list');
        issuesList.innerHTML = '';

        if (data.issues && data.issues.length > 0) {
            issuesContainer.style.display = 'block';
            data.issues.forEach(issue => {
                const li = document.createElement('li');
                li.innerHTML = `<strong>[${issue.severity}] ${issue.code}</strong>: ${issue.message}`;
                issuesList.appendChild(li);
            });
        } else {
            issuesContainer.style.display = 'none';
        }

        // Extracted Data
        const doc = data.data || {};
        
        const formatMoney = (val) => val != null ? `$${val.toFixed(2)}` : '-';
        const formatLocation = (loc) => {
            if (!loc) return '-';
            let parts = [];
            if (loc.facility_name) parts.push(loc.facility_name);
            if (loc.city) parts.push(`${loc.city}, ${loc.state} ${loc.zip_code}`);
            return parts.length > 0 ? parts.join('<br/>') : '-';
        };

        document.getElementById('val-carrier').textContent = doc.carrier_name || '-';
        document.getElementById('val-load').textContent = doc.load_number || '-';
        document.getElementById('val-pickup').innerHTML = formatLocation(doc.pickup_location);
        document.getElementById('val-delivery').innerHTML = formatLocation(doc.delivery_location);
        document.getElementById('val-linehaul').textContent = formatMoney(doc.total_linehaul_rate);
        document.getElementById('val- fuel').textContent = formatMoney(doc.fuel_surcharge);
        document.getElementById('val-total').textContent = formatMoney(doc.total_pay);
        document.getElementById('val-weight').textContent = doc.weight_lbs != null ? `${doc.weight_lbs.toLocaleString()} lbs` : '-';
    }

    function resetApp() {
        fileInput.value = '';
        dropZone.style.display = 'block';
        parsingState.style.display = 'none';
        resultsSection.style.display = 'none';
    }
});
