// ===================
// EXPORT FUNCTIONS
// ===================

function publishSchedule() {
    if (confirm('Are you sure you want to publish this schedule? Team members will be notified.')) {
        alert('Schedule published successfully! Notifications sent to team members.');
    }
}

function exportSchedule() {
    const today = new Date(window.scheduleConfig.selectedDate);
    const monday = new Date(today);
    monday.setDate(today.getDate() - today.getDay() + 1);
    const sunday = new Date(today);
    sunday.setDate(today.getDate() - today.getDay() + 7);
    
    document.getElementById('exportStartDate').value = monday.toISOString().split('T')[0];
    document.getElementById('exportEndDate').value = sunday.toISOString().split('T')[0];
    
    new bootstrap.Modal(document.getElementById('exportModal')).show();
}

function exportWorksched() {
    const today = new Date(window.scheduleConfig.selectedDate);
    const monday = new Date(today);
    monday.setDate(today.getDate() - today.getDay() + 1);
    const sunday = new Date(today);
    sunday.setDate(today.getDate() - today.getDay() + 7);
    
    document.getElementById('exportWorkschedStartDate').value = monday.toISOString().split('T')[0];
    document.getElementById('exportWorkschedEndDate').value = sunday.toISOString().split('T')[0];
    
    new bootstrap.Modal(document.getElementById('exportWorkschedModal')).show();
}

function doExport() {
    const startDate = document.getElementById('exportStartDate').value;
    const endDate = document.getElementById('exportEndDate').value;
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }
    
    window.location.href = `${window.scheduleConfig.urls.exportSchedule}?start_date=${startDate}&end_date=${endDate}`;
    bootstrap.Modal.getInstance(document.getElementById('exportModal')).hide();
}

function doExportWorksched() {
    const startDate = document.getElementById('exportWorkschedStartDate').value;
    const endDate = document.getElementById('exportWorkschedEndDate').value;
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates');
        return;
    }
    
    if (new Date(startDate) > new Date(endDate)) {
        alert('Start date cannot be after end date');
        return;
    }
    
    window.location.href = `${window.scheduleConfig.urls.exportWorksched}?start_date=${startDate}&end_date=${endDate}`;
    bootstrap.Modal.getInstance(document.getElementById('exportWorkschedModal')).hide();
}

function showTemplateModal() {
    new bootstrap.Modal(document.getElementById('templateModal')).show();
}

function applyTemplate(templateType) {
    if (confirm(`Apply ${templateType} template to current schedule? This will overwrite existing shifts.`)) {
        alert(`${templateType.charAt(0).toUpperCase() + templateType.slice(1)} template applied successfully!`);
        bootstrap.Modal.getInstance(document.getElementById('templateModal')).hide();
        location.reload();
    }
}
