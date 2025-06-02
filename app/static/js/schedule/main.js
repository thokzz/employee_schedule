// ===================
// CORE VARIABLES AND INITIALIZATION
// ===================

// Global variables - consolidated into single declaration
let currentShiftId = null;
let currentEmployeeId = null;
let currentDate = null;
let copiedShift = null;
let currentRemarkId = null;
let currentRemarkDate = null;
let dateRemarks = {};
let contextMenuData = null;

// Initialize page
document.addEventListener('DOMContentLoaded', function() {
    loadDateRemarks();
    setupColorPickers();
    setupEventListeners();
    loadPresetHolidays();
});

// ===================
// NAVIGATION FUNCTIONS
// ===================

function navigateDate(direction) {
    const currentDate = new Date(document.getElementById('date-picker').value);
    const viewType = window.scheduleConfig.viewType;
    
    if (viewType === 'day') {
        currentDate.setDate(currentDate.getDate() + direction);
    } else if (viewType === 'week') {
        currentDate.setDate(currentDate.getDate() + (direction * 7));
    } else if (viewType === 'month') {
        currentDate.setMonth(currentDate.getMonth() + direction);
    }
    
    window.location.href = `${window.scheduleConfig.urls.viewSchedule}?view=${viewType}&date=${currentDate.toISOString().split('T')[0]}`;
}

function navigateToDate(dateStr) {
    const viewType = window.scheduleConfig.viewType;
    window.location.href = `${window.scheduleConfig.urls.viewSchedule}?view=${viewType}&date=${dateStr}`;
}

// ===================
// UTILITY FUNCTIONS
// ===================

function getEmployeeInfo(employeeId) {
    return window.scheduleConfig.teamMembers[employeeId] || { name: 'Unknown', initials: '??' };
}

function showSuccessMessage(message) {
    const alertDiv = document.createElement('div');
    alertDiv.className = 'alert alert-success alert-dismissible fade show position-fixed';
    alertDiv.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    document.body.appendChild(alertDiv);
    
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, 3000);
}

function fetchEmployeeScheduleFormat(employeeId) {
    return fetch(`/schedule/api/employee/${employeeId}/schedule-format`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.currentEmployeeScheduleFormat = data.schedule_format;
                window.currentEmployeeBreakDuration = data.break_duration_minutes;
            } else {
                window.currentEmployeeScheduleFormat = '8_hour_shift';
                window.currentEmployeeBreakDuration = 30;
            }
        })
        .catch(error => {
            console.error('Error fetching employee schedule format:', error);
            window.currentEmployeeScheduleFormat = '8_hour_shift';
            window.currentEmployeeBreakDuration = 30;
        });
}

function updateBreakInfo() {
    const startTime = document.getElementById('startTime')?.value;
    const endTime = document.getElementById('endTime')?.value;
    const status = document.getElementById('shiftStatus')?.value;
    
    const breakInfoSection = document.getElementById('breakInfoSection');
    const breakInfoContent = document.getElementById('breakInfoContent');
    const durationInfo = document.getElementById('shiftDurationInfo');
    
    if (!breakInfoSection || !breakInfoContent || !durationInfo) return;
    
    if (startTime && endTime && status === 'scheduled') {
        const start = new Date(`2000-01-01T${startTime}:00`);
        const end = new Date(`2000-01-01T${endTime}:00`);
        
        if (end < start) {
            end.setDate(end.getDate() + 1);
        }
        
        const durationMs = end - start;
        const durationHours = durationMs / (1000 * 60 * 60);
        
        durationInfo.textContent = `Duration: ${durationHours.toFixed(1)} hours`;
        
        if (durationHours >= 4) {
            const employeeScheduleFormat = window.currentEmployeeScheduleFormat || '8_hour_shift';
            const breakDuration = window.currentEmployeeBreakDuration || 30;
            
            let breakType;
            if (employeeScheduleFormat === '9_hour_shift') {
                breakType = '1 hour paid break';
            } else {
                breakType = '30 minute paid break';
            }
            
            const breakStart = new Date(start.getTime() + (3 * 60 * 60 * 1000));
            const breakEnd = new Date(breakStart.getTime() + (breakDuration * 60 * 1000));
            
            breakInfoContent.innerHTML = `
                <strong>Break Schedule:</strong> ${breakType}<br>
                <strong>Break Time:</strong> ${breakStart.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} - ${breakEnd.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}<br>
                <small class="text-muted">Break starts 3 hours after shift begins (${employeeScheduleFormat.replace('_', ' ')} format)</small>
            `;
            breakInfoSection.style.display = 'block';
        } else {
            breakInfoContent.innerHTML = `
                <strong>No Break:</strong> Shift duration less than 4 hours<br>
                <small class="text-muted">Minimum 4 hours required for break eligibility</small>
            `;
            breakInfoSection.style.display = 'block';
        }
    } else {
        breakInfoSection.style.display = 'none';
        durationInfo.textContent = '';
    }
}

// ===================
// COLOR PICKER SETUP
// ===================

function setupColorPickers() {
    // Date remarks color picker
    document.querySelectorAll('#dateRemarkModal .color-option').forEach(option => {
        option.addEventListener('click', function() {
            document.querySelectorAll('#dateRemarkModal .color-option').forEach(opt => opt.classList.remove('selected'));
            this.classList.add('selected');
            
            const selectedColor = this.dataset.color;
            document.getElementById('remarkColor').value = selectedColor;
            document.getElementById('remarkColorDisplay').textContent = selectedColor;
        });
    });
    
    // Shift modal color picker
    document.querySelectorAll('#shiftModal .color-option').forEach(option => {
        option.addEventListener('click', function() {
            document.querySelectorAll('#shiftModal .color-option').forEach(opt => opt.classList.remove('selected'));
            this.classList.add('selected');
            
            const selectedColor = this.dataset.color;
            document.getElementById('shiftColor').value = selectedColor;
            document.getElementById('colorDisplay').textContent = selectedColor;
        });
    });
}

// ===================
// EVENT LISTENERS SETUP
// ===================

function setupEventListeners() {
    // Shift modal event listeners
    const startTimeInput = document.getElementById('startTime');
    const endTimeInput = document.getElementById('endTime');
    const statusSelect = document.getElementById('shiftStatus');
    
    startTimeInput?.addEventListener('change', updateBreakInfo);
    endTimeInput?.addEventListener('change', updateBreakInfo);
    statusSelect?.addEventListener('change', function() {
        updateBreakInfo();
        
        const timeFields = document.querySelectorAll('#startTime, #endTime');
        const roleField = document.getElementById('shiftRole');
        const workArrangementField = document.getElementById('workArrangement');
        
        if (this.value === 'scheduled') {
            timeFields.forEach(field => field.removeAttribute('disabled'));
            roleField?.removeAttribute('disabled');
            workArrangementField?.removeAttribute('disabled');
        } else {
            timeFields.forEach(field => {
                field.setAttribute('disabled', 'disabled');
                if (['rest_day', 'sick_leave', 'personal_leave', 'emergency_leave', 'annual_vacation', 'holiday_off'].includes(this.value)) {
                    field.value = '';
                }
            });
            if (['rest_day'].includes(this.value)) {
                roleField?.setAttribute('disabled', 'disabled');
                if (roleField) roleField.value = '';
                workArrangementField?.setAttribute('disabled', 'disabled');
                if (workArrangementField) workArrangementField.value = 'onsite';
            } else {
                roleField?.removeAttribute('disabled');
                workArrangementField?.removeAttribute('disabled');
            }
        }
    });
    
    // Work arrangement styling
    document.getElementById('workArrangement')?.addEventListener('change', function() {
        const value = this.value;
        const parent = this.parentElement;
        
        parent.classList.remove('arrangement-wfh', 'arrangement-onsite', 'arrangement-hybrid', 'arrangement-ob');
        
        if (value !== 'onsite') {
            parent.classList.add(`arrangement-${value}`);
        }
    });
    
    // Date range functionality
    document.getElementById('useDateRange')?.addEventListener('change', function() {
        const dateRangeSection = document.getElementById('dateRangeSection');
        const daysOfWeekSection = document.getElementById('daysOfWeekSection');
        const singleDateField = document.getElementById('shiftDate');
        
        if (this.checked) {
            dateRangeSection.style.display = 'block';
            daysOfWeekSection.style.display = 'block';
            dateRangeSection.classList.add('show');
            daysOfWeekSection.classList.add('show');
            
            const currentDate = singleDateField.value || new Date().toISOString().split('T')[0];
            document.getElementById('startDate').value = currentDate;
            
            const endDate = new Date(currentDate);
            endDate.setDate(endDate.getDate() + 6);
            document.getElementById('endDate').value = endDate.toISOString().split('T')[0];
            
            singleDateField.disabled = true;
            singleDateField.style.opacity = '0.5';
        } else {
            dateRangeSection.style.display = 'none';
            daysOfWeekSection.style.display = 'none';
            
            singleDateField.disabled = false;
            singleDateField.style.opacity = '1';
        }
    });
    
    // Quick day selection buttons
    const daysOfWeekSection = document.getElementById('daysOfWeekSection');
    if (daysOfWeekSection) {
        const buttonContainer = document.createElement('div');
        buttonContainer.className = 'mt-2 mb-2';
        
        const weekdaysBtn = document.createElement('button');
        weekdaysBtn.type = 'button';
        weekdaysBtn.className = 'btn btn-sm btn-outline-primary me-2';
        weekdaysBtn.textContent = 'Weekdays Only';
        weekdaysBtn.onclick = function() {
            document.querySelectorAll('input[name="days[]"]').forEach(cb => cb.checked = false);
            ['dayMon', 'dayTue', 'dayWed', 'dayThu', 'dayFri'].forEach(id => {
                document.getElementById(id).checked = true;
            });
        };
        
        const allDaysBtn = document.createElement('button');
        allDaysBtn.type = 'button';
        allDaysBtn.className = 'btn btn-sm btn-outline-secondary';
        allDaysBtn.textContent = 'All Days';
        allDaysBtn.onclick = function() {
            document.querySelectorAll('input[name="days[]"]').forEach(cb => cb.checked = true);
        };
        
        buttonContainer.appendChild(weekdaysBtn);
        buttonContainer.appendChild(allDaysBtn);
        daysOfWeekSection.appendChild(buttonContainer);
    }
    
    // Hide context menus when clicking elsewhere
    document.addEventListener('click', function(e) {
        if (!e.target.closest('.context-menu')) {
            hideContextMenu();
            hideCellContextMenu();
        }
    });
    
    // Prevent default context menu for schedule cells only
    document.addEventListener('contextmenu', function(e) {
        if (!e.target.closest('.shift-card') && !e.target.closest('.add-shift-btn')) {
            return true;
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            switch(e.key) {
                case 'ArrowLeft':
                    e.preventDefault();
                    navigateDate(-1);
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    navigateDate(1);
                    break;
                case 'e':
                    if (window.scheduleConfig.canEdit) {
                        e.preventDefault();
                        exportSchedule();
                    }
                    break;
                case 'p':
                    if (window.scheduleConfig.canEdit) {
                        e.preventDefault();
                        publishSchedule();
                    }
                    break;
                case 'c':
                    if (document.querySelector('.shift-card:focus')) {
                        e.preventDefault();
                        const focusedShift = document.querySelector('.shift-card:focus');
                        const onclick = focusedShift.getAttribute('onclick');
                        const matches = onclick.match(/editShift\((\d+), (\d+), '([^']+)'\)/);
                        if (matches) {
                            copyShift(parseInt(matches[1]), parseInt(matches[2]), matches[3]);
                        }
                    }
                    break;
                case 'v':
                    if (copiedShift && document.querySelector('.shift-card:focus, .add-shift-btn:focus')) {
                        e.preventDefault();
                        const focusedElement = document.querySelector('.shift-card:focus, .add-shift-btn:focus');
                        const onclick = focusedElement.getAttribute('onclick');
                        const matches = onclick.match(/createShift\((\d+), '([^']+)'\)/);
                        if (matches) {
                            pasteShift(parseInt(matches[1]), matches[2]);
                        }
                    }
                    break;
            }
        }
    });
}
