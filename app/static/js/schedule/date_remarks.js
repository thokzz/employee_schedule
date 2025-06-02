// ===================
// DATE REMARKS MANAGEMENT
// ===================

function loadDateRemarks() {
    const startDate = window.scheduleConfig.dates.first;
    const endDate = window.scheduleConfig.dates.last;
    
    fetch(`/schedule/api/date-remarks?start_date=${startDate}&end_date=${endDate}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                dateRemarks = {};
                data.remarks.forEach(remark => {
                    dateRemarks[remark.date] = remark;
                    displayDateRemark(remark);
                });
            }
        })
        .catch(error => console.error('Error loading date remarks:', error));
}

function displayDateRemark(remark) {
    const dateHeader = document.getElementById(`date-header-${remark.date}`);
    const remarkContainer = document.getElementById(`date-remark-${remark.date}`);
    
    if (dateHeader && remarkContainer) {
        dateHeader.classList.add(`has-${remark.remark_type}`);
        
        const badge = document.createElement('span');
        badge.className = `badge ${remark.badge_class} date-remark-badge`;
        badge.style.backgroundColor = remark.color;
        badge.textContent = remark.title;
        badge.title = remark.description || remark.title;
        badge.onclick = () => editDateRemark(remark.date);
        
        remarkContainer.innerHTML = '';
        remarkContainer.appendChild(badge);
    }
}

function editDateRemark(dateStr) {
    currentRemarkDate = dateStr;
    const remark = dateRemarks[dateStr];
    
    document.getElementById('dateRemarkForm').reset();
    document.getElementById('remarkDate').value = dateStr;
    document.getElementById('remarkDateDisplay').textContent = new Date(dateStr).toLocaleDateString('en-US', {
        weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
    
    if (remark) {
        currentRemarkId = remark.id;
        document.getElementById('remarkId').value = remark.id;
        document.getElementById('remarkTitle').value = remark.title;
        document.getElementById('remarkDescription').value = remark.description || '';
        document.getElementById('remarkType').value = remark.remark_type;
        document.getElementById('isWorkDay').checked = remark.is_work_day;
        document.getElementById('remarkColor').value = remark.color;
        document.getElementById('remarkColorDisplay').textContent = remark.color;
        updateRemarkColorPicker(remark.color);
        document.getElementById('deleteRemarkBtn').style.display = 'block';
    } else {
        currentRemarkId = null;
        document.getElementById('deleteRemarkBtn').style.display = 'none';
    }
    
    document.getElementById('dateRemarkModalTitle').textContent = remark ? 'Edit Date Remark' : 'Add Date Remark';
    new bootstrap.Modal(document.getElementById('dateRemarkModal')).show();
}

function updateRemarkColorPicker(selectedColor) {
    document.querySelectorAll('#dateRemarkModal .color-option').forEach(option => {
        option.classList.remove('selected');
        if (option.dataset.color === selectedColor) {
            option.classList.add('selected');
        }
    });
}

function saveDateRemark() {
    const formData = new FormData(document.getElementById('dateRemarkForm'));
    const data = Object.fromEntries(formData.entries());
    
    if (!data.title || !data.title.trim()) {
        alert('Please enter a title for the date remark.');
        return;
    }
    
    fetch('/schedule/api/date-remarks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessMessage(data.message || 'Date remark saved successfully!');
            bootstrap.Modal.getInstance(document.getElementById('dateRemarkModal')).hide();
            dateRemarks[data.remark.date] = data.remark;
            displayDateRemark(data.remark);
        } else {
            alert('Error saving date remark: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error saving date remark:', error);
        alert('Error saving date remark');
    });
}

function deleteDateRemark() {
    if (!currentRemarkId) return;
    
    if (confirm('Are you sure you want to delete this date remark?')) {
        fetch(`/schedule/api/date-remarks/${currentRemarkId}`, { method: 'DELETE' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showSuccessMessage('Date remark deleted successfully!');
                    bootstrap.Modal.getInstance(document.getElementById('dateRemarkModal')).hide();
                    
                    const dateHeader = document.getElementById(`date-header-${currentRemarkDate}`);
                    const remarkContainer = document.getElementById(`date-remark-${currentRemarkDate}`);
                    
                    if (dateHeader) dateHeader.className = 'date-header';
                    if (remarkContainer) remarkContainer.innerHTML = '';
                    
                    delete dateRemarks[currentRemarkDate];
                } else {
                    alert('Error deleting date remark: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error deleting date remark:', error);
                alert('Error deleting date remark');
            });
    }
}
