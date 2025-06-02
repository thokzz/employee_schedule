// ===================
// HOLIDAY MANAGEMENT
// ===================

function showHolidayManagement() {
    loadPresetHolidays();
    loadCurrentRemarks();
    new bootstrap.Modal(document.getElementById('holidayManagementModal')).show();
}

function loadPresetHolidays() {
    fetch('/schedule/api/holidays/preset')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const container = document.getElementById('holidayPresetList');
                container.innerHTML = '';
                
                data.holidays.forEach(holiday => {
                    const item = document.createElement('div');
                    item.className = 'holiday-preset-item';
                    item.innerHTML = `
                        <div class="form-check">
                            <input class="form-check-input holiday-preset-checkbox" type="checkbox" 
                                   value='${JSON.stringify(holiday)}' id="holiday-${holiday.month}-${holiday.day}">
                            <label class="form-check-label" for="holiday-${holiday.month}-${holiday.day}">
                                <strong>${holiday.title}</strong><br>
                                <small class="text-muted">${getMonthName(holiday.month)} ${holiday.day}</small>
                            </label>
                        </div>
                    `;
                    container.appendChild(item);
                });
                
                // Set default year from config
                const yearInput = document.getElementById('holidayYear');
                if (yearInput && !yearInput.value) {
                    yearInput.value = new Date(window.scheduleConfig.selectedDate).getFullYear();
                }
                
                document.getElementById('selectAllHolidays').addEventListener('change', function() {
                    document.querySelectorAll('.holiday-preset-checkbox').forEach(cb => cb.checked = this.checked);
                });
            }
        })
        .catch(error => console.error('Error loading preset holidays:', error));
}

function loadCurrentRemarks() {
    const year = document.getElementById('holidayYear').value || new Date(window.scheduleConfig.selectedDate).getFullYear();
    const startDate = `${year}-01-01`;
    const endDate = `${year}-12-31`;
    
    fetch(`/schedule/api/date-remarks?start_date=${startDate}&end_date=${endDate}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const container = document.getElementById('currentRemarksLista');
                container.innerHTML = '';
                
                if (data.remarks.length === 0) {
                    container.innerHTML = '<div class="text-muted">No date remarks found for this year.</div>';
                    return;
                }
                
                data.remarks.forEach(remark => {
                    const item = document.createElement('div');
                    item.className = 'card mb-2';
                    item.innerHTML = `
                        <div class="card-body p-2">
                            <div class="d-flex justify-content-between align-items-start">
                                <div>
                                    <div class="fw-bold">${remark.title}</div>
                                    <small class="text-muted">${new Date(remark.date).toLocaleDateString()}</small>
                                    ${remark.description ? `<div class="small">${remark.description}</div>` : ''}
                                    <span class="badge ${remark.badge_class}" style="background-color: ${remark.color};">
                                        ${remark.remark_type.replace('_', ' ').toUpperCase()}
                                    </span>
                                </div>
                                <button class="btn btn-sm btn-outline-danger" onclick="deleteDateRemarkFromList(${remark.id}, '${remark.date}')">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </div>
                        </div>
                    `;
                    container.appendChild(item);
                });
            }
        })
        .catch(error => console.error('Error loading current remarks:', error));
}

function deleteDateRemarkFromList(remarkId, dateStr) {
    if (confirm('Are you sure you want to delete this date remark?')) {
        fetch(`/schedule/api/date-remarks/${remarkId}`, { method: 'DELETE' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showSuccessMessage('Date remark deleted successfully!');
                    loadCurrentRemarks();
                    
                    delete dateRemarks[dateStr];
                    const dateHeader = document.getElementById(`date-header-${dateStr}`);
                    const remarkContainer = document.getElementById(`date-remark-${dateStr}`);
                    
                    if (dateHeader) dateHeader.className = 'date-header';
                    if (remarkContainer) remarkContainer.innerHTML = '';
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

function applyPresetHolidays() {
    const year = document.getElementById('holidayYear').value || new Date(window.scheduleConfig.selectedDate).getFullYear();
    const selectedCheckboxes = document.querySelectorAll('.holiday-preset-checkbox:checked');
    
    if (selectedCheckboxes.length === 0) {
        alert('Please select at least one holiday to apply.');
        return;
    }
    
    const holidays = Array.from(selectedCheckboxes).map(cb => JSON.parse(cb.value));
    
    fetch('/schedule/api/holidays/apply-preset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ year: parseInt(year), holidays: holidays })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessMessage(data.message);
            loadCurrentRemarks();
            loadDateRemarks();
        } else {
            alert('Error applying preset holidays: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error applying preset holidays:', error);
        alert('Error applying preset holidays');
    });
}

function getMonthName(monthNum) {
    const months = ['', 'January', 'February', 'March', 'April', 'May', 'June',
                   'July', 'August', 'September', 'October', 'November', 'December'];
    return months[monthNum];
}
