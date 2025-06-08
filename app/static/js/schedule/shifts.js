// ===================
// SHIFT MANAGEMENT
// ===================

function createShift(employeeId, date) {
    // Check if user can create shift for this employee
    const canEdit = window.scheduleConfig.canEdit || (employeeId === window.currentUserId);
    
    if (!canEdit) {
        alert('You can only edit your own shifts.');
        return;
    }
    
    // Your existing createShift code continues here...
    currentShiftId = null;
    currentEmployeeId = employeeId;
    
    document.getElementById('shiftForm').reset();
    document.getElementById('shiftId').value = '';
    document.getElementById('employeeId').value = employeeId;
    document.getElementById('shiftDate').value = date;
    
    // Reset color picker to default
    document.querySelectorAll('#shiftModal .color-option').forEach(option => {
        option.classList.remove('selected');
        if (option.dataset.color === '#007bff') {
            option.classList.add('selected');
        }
    });
    document.getElementById('shiftColor').value = '#007bff';
    document.getElementById('colorDisplay').textContent = '#007bff';
    
    const employee = getEmployeeInfo(employeeId);
    document.getElementById('employeeInfo').innerHTML = `
        <div class="d-flex align-items-center">
            <div class="employee-initials me-2">${employee.initials}</div>
            <span>${employee.name}</span>
        </div>
    `;
    
    document.getElementById('shiftModalTitle').textContent = 'Create Shift';
    document.getElementById('deleteShiftBtn').style.display = 'none';
    
    document.querySelectorAll('#startTime, #endTime, #shiftRole, #workArrangement').forEach(field => {
        field.removeAttribute('disabled');
    });
    
    fetchEmployeeScheduleFormat(employeeId);
    new bootstrap.Modal(document.getElementById('shiftModal')).show();
}

function editShift(shiftId, employeeId, date) {
    // Check if user can edit this specific shift
    const canEdit = window.scheduleConfig.canEdit || (employeeId === window.currentUserId);
    
    if (!canEdit) {
        // Show view-only details instead
        viewShiftDetails(shiftId);
        return;
    }
    currentShiftId = shiftId;
    currentEmployeeId = employeeId;
    
    fetch(`/schedule/api/shift/${shiftId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const shift = data.shift;
                document.getElementById('shiftId').value = shift.id;
                document.getElementById('employeeId').value = shift.employee_id;
                document.getElementById('shiftDate').value = shift.date;
                document.getElementById('startTime').value = shift.start_time || '';
                document.getElementById('endTime').value = shift.end_time || '';
                document.getElementById('shiftRole').value = shift.role || '';
                document.getElementById('shiftStatus').value = shift.status;
                document.getElementById('shiftNotes').value = shift.notes || '';
                document.getElementById('workArrangement').value = shift.work_arrangement || 'onsite';
                
                const shiftColor = shift.color || '#007bff';
                document.getElementById('shiftColor').value = shiftColor;
                document.getElementById('colorDisplay').textContent = shiftColor;
                
                document.querySelectorAll('#shiftModal .color-option').forEach(option => {
                    option.classList.remove('selected');
                    if (option.dataset.color === shiftColor) {
                        option.classList.add('selected');
                    }
                });
                
                const employee = getEmployeeInfo(employeeId);
                document.getElementById('employeeInfo').innerHTML = `
                    <div class="d-flex align-items-center">
                        <div class="employee-initials me-2">${employee.initials}</div>
                        <span>${employee.name}</span>
                    </div>
                `;
                
                document.getElementById('shiftModalTitle').textContent = 'Edit Shift';
                document.getElementById('deleteShiftBtn').style.display = 'block';
                
                fetchEmployeeScheduleFormat(employeeId).then(() => {
                    updateBreakInfo();
                });
                
                new bootstrap.Modal(document.getElementById('shiftModal')).show();
            } else {
                alert('Error loading shift: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error loading shift:', error);
            alert('Error loading shift data');
        });
}

function saveShift() {
    const formData = new FormData(document.getElementById('shiftForm'));
    const useDateRange = document.getElementById('useDateRange').checked;
    
    if (useDateRange && !currentShiftId) {
        saveShiftRange();
    } else {
        const data = Object.fromEntries(formData.entries());
        
        fetch('/schedule/api/shift', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showSuccessMessage(data.message || 'Shift saved successfully!');
                bootstrap.Modal.getInstance(document.getElementById('shiftModal')).hide();
                setTimeout(() => location.reload(), 1000);
            } else {
                alert('Error saving shift: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error saving shift:', error);
            alert('Error saving shift');
        });
    }
}

function viewShiftDetails(shiftId) {
    fetch(`/schedule/api/shift/${shiftId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showShiftDetailsModal(data.shift);
            } else {
                alert('Error loading shift details: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error loading shift details');
        });
}

function showShiftDetailsModal(shift) {
    // Create modal HTML
    const modalHtml = `
        <div class="modal fade" id="shiftDetailsModal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="bi bi-eye"></i> Shift Details
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-info">
                            <i class="bi bi-info-circle"></i>
                            <strong>View Only:</strong> You can view this shift but cannot edit it.
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">Employee</label>
                                    <p class="mb-0">${window.scheduleConfig.teamMembers[shift.employee_id]?.name || 'Unknown'}</p>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">Date</label>
                                    <p class="mb-0">${formatDate(shift.date)}</p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">Start Time</label>
                                    <p class="mb-0">${shift.start_time || 'Not set'}</p>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">End Time</label>
                                    <p class="mb-0">${shift.end_time || 'Not set'}</p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">Role</label>
                                    <p class="mb-0">${shift.role || 'No role specified'}</p>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label class="form-label fw-bold">Work Arrangement</label>
                                    <p class="mb-0">
                                        <span class="badge bg-secondary">
                                            ${shift.work_arrangement.toUpperCase()}
                                        </span>
                                    </p>
                                </div>
                            </div>
                        </div>
                        
                        <div class="mb-3">
                            <label class="form-label fw-bold">Status</label>
                            <p class="mb-0">
                                <span class="badge" style="background-color: ${shift.color};">
                                    ${shift.status.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                                </span>
                            </p>
                        </div>
                        
                        ${shift.notes ? `
                            <div class="mb-3">
                                <label class="form-label fw-bold">Notes</label>
                                <p class="mb-0 p-2 bg-light rounded">${shift.notes}</p>
                            </div>
                        ` : ''}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existingModal = document.getElementById('shiftDetailsModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Add modal to page
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('shiftDetailsModal'));
    modal.show();
    
    // Clean up modal when hidden
    document.getElementById('shiftDetailsModal').addEventListener('hidden.bs.modal', function() {
        this.remove();
    });
}

function saveShiftRange() {
    const formData = new FormData(document.getElementById('shiftForm'));
    const startDate = document.getElementById('startDate').value;
    const endDate = document.getElementById('endDate').value;
    const selectedDays = Array.from(document.querySelectorAll('input[name="days[]"]:checked')).map(cb => parseInt(cb.value));
    
    if (!startDate || !endDate) {
        alert('Please select both start and end dates for the range.');
        return;
    }
    
    if (selectedDays.length === 0) {
        alert('Please select at least one day of the week.');
        return;
    }
    
    if (new Date(startDate) > new Date(endDate)) {
        alert('Start date cannot be after end date.');
        return;
    }
    
    // Calculate date range
    const start = new Date(startDate);
    const end = new Date(endDate);
    const dates = [];
    
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
        const dayOfWeek = d.getDay();
        if (selectedDays.includes(dayOfWeek)) {
            dates.push(new Date(d).toISOString().split('T')[0]);
        }
    }
    
    if (dates.length === 0) {
        alert('No dates found matching the selected days of week in the specified range.');
        return;
    }
    
    if (dates.length > 50) {
        if (!confirm(`This will create ${dates.length} shifts. Continue?`)) {
            return;
        }
    }
    
    showSuccessMessage(`Creating ${dates.length} shifts...`);
    
    const promises = dates.map(date => {
        const shiftData = {
            employee_id: formData.get('employee_id'),
            date: date,
            start_time: formData.get('start_time'),
            end_time: formData.get('end_time'),
            role: formData.get('role'),
            status: formData.get('status'),
            notes: formData.get('notes'),
            color: formData.get('color'),
            work_arrangement: formData.get('work_arrangement')
        };
        
        return fetch('/schedule/api/shift', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(shiftData)
        })
        .then(response => response.json());
    });
    
    Promise.all(promises)
        .then(results => {
            const successful = results.filter(r => r.success).length;
            const failed = results.filter(r => !r.success).length;
            
            if (failed === 0) {
                showSuccessMessage(`Successfully created ${successful} shifts!`);
            } else {
                showSuccessMessage(`Created ${successful} shifts, ${failed} failed.`);
            }
            
            bootstrap.Modal.getInstance(document.getElementById('shiftModal')).hide();
            setTimeout(() => location.reload(), 2000);
        })
        .catch(error => {
            console.error('Error creating shift range:', error);
            alert('Error creating shifts');
        });
}

function deleteShift() {
    if (!currentShiftId) return;
    
    if (confirm('Are you sure you want to delete this shift?')) {
        fetch(`/schedule/api/shift/${currentShiftId}`, { method: 'DELETE' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showSuccessMessage(data.message || 'Shift deleted successfully!');
                    bootstrap.Modal.getInstance(document.getElementById('shiftModal')).hide();
                    setTimeout(() => location.reload(), 1000);
                } else {
                    alert('Error deleting shift: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error deleting shift:', error);
                alert('Error deleting shift');
            });
    }
}

function deleteShiftConfirm(shiftId) {
    if (confirm('Are you sure you want to delete this shift?')) {
        fetch(`/schedule/api/shift/${shiftId}`, { method: 'DELETE' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showSuccessMessage('Shift deleted successfully!');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    alert('Error deleting shift: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(error => {
                console.error('Error deleting shift:', error);
                alert('Error deleting shift');
            });
    }
}

// ===================
// COPY/PASTE FUNCTIONALITY
// ===================

function copyShift(shiftId, employeeId, date) {
    fetch(`/schedule/api/shift/${shiftId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                copiedShift = data.shift;
                showSuccessMessage('Shift copied! Right-click on any cell to paste.');
                
                document.querySelectorAll('.shift-card').forEach(card => card.classList.remove('copied-shift'));
                const copiedCard = document.querySelector(`[onclick*="editShift(${shiftId}"]`);
                if (copiedCard) copiedCard.classList.add('copied-shift');
            } else {
                alert('Error copying shift: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error copying shift:', error);
            alert('Error copying shift');
        });
}

function pasteShift(employeeId, date) {
    if (!copiedShift) {
        alert('No shift copied. Please copy a shift first.');
        return;
    }
    
    const newShiftData = {
        employee_id: employeeId,
        date: date,
        start_time: copiedShift.start_time,
        end_time: copiedShift.end_time,
        role: copiedShift.role,
        status: copiedShift.status,
        notes: copiedShift.notes,
        color: copiedShift.color,
        work_arrangement: copiedShift.work_arrangement
    };
    
    fetch('/schedule/api/shift', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newShiftData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessMessage('Shift pasted successfully!');
            setTimeout(() => location.reload(), 1000);
        } else {
            alert('Error pasting shift: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error pasting shift:', error);
        alert('Error pasting shift');
    });
}

// ===================
// CONTEXT MENU FUNCTIONALITY
// ===================

function formatDate(dateStr) {
    const date = new Date(dateStr + 'T00:00:00');
    return date.toLocaleDateString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

function showShiftContextMenu(event, shiftId, employeeId, date) {
    event.preventDefault();
    event.stopPropagation();
    
    contextMenuData = { shiftId, employeeId, date, type: 'shift' };
    
    const contextMenu = document.getElementById('contextMenu');
    const pasteOption = document.getElementById('pasteOption');
    
    pasteOption.style.display = copiedShift ? 'flex' : 'none';
    
    contextMenu.style.left = event.pageX + 'px';
    contextMenu.style.top = event.pageY + 'px';
    contextMenu.style.display = 'block';
    
    setTimeout(() => {
        document.addEventListener('click', hideContextMenu, { once: true });
    }, 10);
}

function showCellContextMenu(event, employeeId, date) {
    event.preventDefault();
    event.stopPropagation();
    
    contextMenuData = { employeeId, date, type: 'cell' };
    
    const cellContextMenu = document.getElementById('cellContextMenu');
    const pasteCellOption = document.getElementById('pasteCellOption');
    
    pasteCellOption.style.display = copiedShift ? 'flex' : 'none';
    
    cellContextMenu.style.left = event.pageX + 'px';
    cellContextMenu.style.top = event.pageY + 'px';
    cellContextMenu.style.display = 'block';
    
    setTimeout(() => {
        document.addEventListener('click', hideCellContextMenu, { once: true });
    }, 10);
}

function hideContextMenu() {
    document.getElementById('contextMenu').style.display = 'none';
}

function hideCellContextMenu() {
    document.getElementById('cellContextMenu').style.display = 'none';
}

function contextMenuCopy() {
    if (contextMenuData && contextMenuData.type === 'shift') {
        copyShift(contextMenuData.shiftId, contextMenuData.employeeId, contextMenuData.date);
    }
    hideContextMenu();
}

function contextMenuPaste() {
    if (contextMenuData && contextMenuData.type === 'shift') {
        pasteShift(contextMenuData.employeeId, contextMenuData.date);
    }
    hideContextMenu();
}

function contextMenuEdit() {
    if (contextMenuData && contextMenuData.type === 'shift') {
        editShift(contextMenuData.shiftId, contextMenuData.employeeId, contextMenuData.date);
    }
    hideContextMenu();
}

function contextMenuDelete() {
    if (contextMenuData && contextMenuData.type === 'shift') {
        deleteShiftConfirm(contextMenuData.shiftId);
    }
    hideContextMenu();
}

function contextMenuCreate() {
    if (contextMenuData && contextMenuData.type === 'cell') {
        createShift(contextMenuData.employeeId, contextMenuData.date);
    }
    hideCellContextMenu();
}

function contextMenuPasteCell() {
    if (contextMenuData && contextMenuData.type === 'cell') {
        pasteShift(contextMenuData.employeeId, contextMenuData.date);
    }
    hideCellContextMenu();
}
