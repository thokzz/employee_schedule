// Schedule Template Management Functions - ENHANCED WITH BETTER DELETE FUNCTIONALITY

// Global template manager instance
let templateManager = null;

// Initialize template system when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    templateManager = new ScheduleTemplateManager();
});

class ScheduleTemplateManager {
    constructor() {
        this.templates = [];
        this.organizationalScope = null;
        this.currentTemplate = null;
        this.init();
    }

    async init() {
        try {
            await this.loadOrganizationalScope();
            await this.loadTemplates();
            this.setupEventListeners();
        } catch (error) {
            console.error('Error initializing template manager:', error);
        }
    }

    async loadOrganizationalScope() {
        try {
            const response = await fetch('/schedule/api/organizational-scope');
            const data = await response.json();
            if (data.success) {
                this.organizationalScope = data.scope;
            }
        } catch (error) {
            console.error('Error loading organizational scope:', error);
        }
    }

    async loadTemplates() {
        try {
            const response = await fetch('/schedule/api/templates');
            const data = await response.json();
            if (data.success) {
                this.templates = data.templates;
                this.renderTemplatesGrid();
                this.populateQuickTemplateSelect();
            }
        } catch (error) {
            console.error('Error loading templates:', error);
            this.showAlert('Error loading templates', 'danger');
        }
    }

    setupEventListeners() {
        // Template search
        const searchInput = document.getElementById('templateSearch');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                this.filterTemplates('search', e.target.value);
            });
        }

        // Tab change handlers
        document.querySelectorAll('#templateTabs button').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                this.updateTemplateActions(e.target.id);
            });
        });

        // Form submission handlers
        this.setupFormHandlers();
    }

    setupFormHandlers() {
        // Create template form handler
        const createForm = document.getElementById('createTemplateForm');
        if (createForm) {
            createForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleCreateTemplate();
            });
        }

        // Apply template form handler
        const applyForm = document.getElementById('applyTemplateForm');
        if (applyForm) {
            applyForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.handleApplyTemplate();
            });
        }
    }

    async handleCreateTemplate() {
        try {
            const form = document.getElementById('createTemplateForm');
            const formData = new FormData(form);
            
            const data = {
                name: formData.get('name'),
                description: formData.get('description'),
                start_date: formData.get('start_date'),
                end_date: formData.get('end_date'),
                is_public: formData.has('is_public'),
                scope_type: formData.get('scope_type'),
                scope_id: formData.get('scope_id')
            };

            const response = await fetch('/schedule/api/templates/create-snapshot', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                await this.loadTemplates(); // Refresh templates list
                
                // Clear form
                form.reset();
                
                // Switch back to browse tab
                const browseTab = document.getElementById('browse-tab');
                if (browseTab) {
                    browseTab.click();
                }
            } else {
                this.showAlert(result.error || 'Error creating template', 'danger');
            }
        } catch (error) {
            console.error('Error creating template:', error);
            this.showAlert('Error creating template', 'danger');
        }
    }

    async handleApplyTemplate() {
        try {
            const form = document.getElementById('applyTemplateForm');
            const formData = new FormData(form);
            
            const templateId = formData.get('template_id');
            const data = {
                target_start_date: formData.get('target_start_date'),
                target_end_date: formData.get('target_end_date'),
                target_section_id: formData.get('target_scope_id'),
                replace_existing: formData.has('replace_existing'),
                employee_mappings: this.currentEmployeeMappings || {}
            };

            const response = await fetch(`/schedule/api/templates/${templateId}/apply`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('applyTemplateModal'));
                if (modal) {
                    modal.hide();
                }
                
                // Refresh schedule view
                if (typeof refreshScheduleView === 'function') {
                    refreshScheduleView();
                }
            } else {
                this.showAlert(result.error || 'Error applying template', 'danger');
            }
        } catch (error) {
            console.error('Error applying template:', error);
            this.showAlert('Error applying template', 'danger');
        }
    }

    renderTemplatesGrid() {
        const grid = document.getElementById('templatesGrid');
        if (!grid) return;

        if (this.templates.length === 0) {
            grid.innerHTML = `
                <div class="col-12">
                    <div class="text-center py-5">
                        <i class="bi bi-files fs-1 text-muted"></i>
                        <h5 class="text-muted mt-3">No Templates Found</h5>
                        <p class="text-muted">Create your first template by capturing a schedule snapshot.</p>
                    </div>
                </div>
            `;
            return;
        }

        grid.innerHTML = this.templates.map(template => {
            // Determine if user can delete this template
            const canDelete = this.canUserDeleteTemplate(template);
            
            return `
                <div class="col-lg-4 col-md-6 mb-3" data-template-id="${template.id}">
                    <div class="card h-100 template-card" style="cursor: pointer;" onclick="viewTemplate(${template.id})">
                        <div class="card-header d-flex justify-content-between align-items-start">
                            <h6 class="mb-0 flex-grow-1">${this.escapeHtml(template.name)}</h6>
                            <div class="dropdown" onclick="event.stopPropagation();">
                                <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">
                                    <i class="bi bi-three-dots"></i>
                                </button>
                                <ul class="dropdown-menu">
                                    <li><h6 class="dropdown-header">Template Actions</h6></li>
                                    <li><a class="dropdown-item" href="#" onclick="useTemplate(${template.id})">
                                        <i class="bi bi-arrow-repeat text-primary"></i> Apply Template
                                    </a></li>
                                    <li><a class="dropdown-item" href="#" onclick="viewTemplate(${template.id})">
                                        <i class="bi bi-eye text-info"></i> View Details
                                    </a></li>
                                    <li><a class="dropdown-item" href="#" onclick="duplicateTemplate(${template.id})">
                                        <i class="bi bi-files text-success"></i> Duplicate
                                    </a></li>
                                    ${canDelete ? `
                                    <li><hr class="dropdown-divider"></li>
                                    <li><a class="dropdown-item text-danger" href="#" onclick="deleteTemplate(${template.id}, '${this.escapeHtml(template.name)}')">
                                        <i class="bi bi-trash"></i> Delete Template
                                    </a></li>
                                    ` : ''}
                                </ul>
                            </div>
                        </div>
                        <div class="card-body">
                            <p class="text-muted small mb-2">${this.escapeHtml(template.description || 'No description')}</p>
                            
                            <div class="row text-center mb-2">
                                <div class="col-4">
                                    <div class="text-primary fw-bold">${template.duration_days || 7}</div>
                                    <small class="text-muted">Days</small>
                                </div>
                                <div class="col-4">
                                    <div class="text-success fw-bold">${template.total_employees || 0}</div>
                                    <small class="text-muted">Employees</small>
                                </div>
                                <div class="col-4">
                                    <div class="text-info fw-bold">${template.total_shifts || 0}</div>
                                    <small class="text-muted">Shifts</small>
                                </div>
                            </div>

                            <div class="d-flex justify-content-between align-items-center">
                                <span class="badge ${template.is_public ? 'bg-success' : 'bg-secondary'} small">
                                    ${template.is_public ? 'Public' : 'Private'}
                                </span>
                                <small class="text-muted">
                                    Used ${template.usage_count || 0} times
                                </small>
                            </div>
                        </div>
                        <div class="card-footer bg-light">
                            <small class="text-muted">
                                By: ${this.escapeHtml(template.created_by)} • 
                                ${template.last_used_at ? new Date(template.last_used_at).toLocaleDateString() : 'Never used'}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    canUserDeleteTemplate(template) {
        // Check if current user can delete this template
        // Only creator or admin can delete
        return window.currentUser && (
            window.currentUser.role === 'administrator' || 
            template.created_by === window.currentUser.name
        );
    }

    populateQuickTemplateSelect() {
        const select = document.getElementById('quickTemplateSelect');
        if (!select) return;

        select.innerHTML = '<option value="">Choose a template...</option>' +
            this.templates.map(template => 
                `<option value="${template.id}">${this.escapeHtml(template.name)} (${template.duration_days || 7} days)</option>`
            ).join('');
    }

    updateTemplateActions(activeTabId) {
        const actionsContainer = document.getElementById('templateActions');
        if (!actionsContainer) return;

        if (activeTabId === 'create-tab') {
            actionsContainer.innerHTML = `
                <button type="button" class="btn btn-primary" onclick="templateManager.handleCreateTemplate()">
                    <i class="bi bi-camera"></i> Create Template
                </button>
            `;
        } else {
            actionsContainer.innerHTML = '';
        }
    }

    showAlert(message, type = 'info') {
        // Enhanced alert with auto-dismiss
        showTemplateAlert(message, type);
    }

    escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Enhanced Alert Function
function showTemplateAlert(message, type = 'info') {
    // Remove any existing alerts
    const existingAlert = document.querySelector('.template-alert');
    if (existingAlert) {
        existingAlert.remove();
    }

    // Create alert element
    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show template-alert" role="alert" style="position: fixed; top: 80px; right: 20px; z-index: 1055; min-width: 300px;">
            <strong>${type === 'danger' ? 'Error!' : type === 'success' ? 'Success!' : 'Info:'}</strong> ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;

    // Add to body
    document.body.insertAdjacentHTML('beforeend', alertHtml);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        const alert = document.querySelector('.template-alert');
        if (alert) {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }
    }, 5000);
}

// ENHANCED: Global functions with better UX
function showTemplateModal() {
    try {
        const modalElement = document.getElementById('templateManagementModal');
        if (!modalElement) {
            console.error('Template modal element not found');
            return;
        }
        
        let modal = bootstrap.Modal.getInstance(modalElement);
        if (!modal) {
            modal = new bootstrap.Modal(modalElement);
        }
        modal.show();
    } catch (error) {
        console.error('Error showing template modal:', error);
    }
}

function showQuickTemplateModal() {
    try {
        const modalElement = document.getElementById('quickApplyTemplateModal');
        if (!modalElement) {
            console.error('Quick template modal element not found');
            return;
        }
        
        let modal = bootstrap.Modal.getInstance(modalElement);
        if (!modal) {
            modal = new bootstrap.Modal(modalElement);
        }
        modal.show();
    } catch (error) {
        console.error('Error showing quick template modal:', error);
    }
}

function createTemplateFromCurrentWeek() {
    showTemplateModal();
    
    setTimeout(() => {
        const createTab = document.getElementById('create-tab');
        if (createTab) {
            createTab.click();
        }
        
        if (window.scheduleConfig && window.scheduleConfig.viewType === 'week') {
            const startDateInput = document.querySelector('#createTemplateForm input[name="start_date"]');
            const endDateInput = document.querySelector('#createTemplateForm input[name="end_date"]');
            const nameInput = document.querySelector('#createTemplateForm input[name="name"]');
            
            if (startDateInput && window.scheduleConfig.dates) {
                startDateInput.value = window.scheduleConfig.dates.first;
            }
            if (endDateInput && window.scheduleConfig.dates) {
                endDateInput.value = window.scheduleConfig.dates.last;
            }
            if (nameInput && !nameInput.value) {
                const weekStart = new Date(window.scheduleConfig.dates.first);
                nameInput.value = `Week of ${weekStart.toLocaleDateString()}`;
            }
        }
    }, 100);
}

function createTemplate() {
    if (templateManager) {
        templateManager.handleCreateTemplate();
    } else {
        console.error('Template manager not initialized');
    }
}

async function useTemplate(templateId) {
    try {
        const response = await fetch(`/schedule/api/templates/${templateId}`);
        const data = await response.json();
        
        if (data.success) {
            document.getElementById('applyTemplateId').value = templateId;
            document.getElementById('selectedTemplateName').textContent = data.template.name;
            document.getElementById('templateDuration').textContent = `${data.template.duration_days || 7} days`;
            document.getElementById('templateEmployees').textContent = `${data.template.total_employees || 0} employees`;
            document.getElementById('templateShifts').textContent = `${data.template.total_shifts || 0} shifts`;
            
            const modalElement = document.getElementById('applyTemplateModal');
            if (modalElement) {
                let modal = bootstrap.Modal.getInstance(modalElement);
                if (!modal) {
                    modal = new bootstrap.Modal(modalElement);
                }
                modal.show();
            }
        }
    } catch (error) {
        console.error('Error loading template:', error);
        showTemplateAlert('Error loading template details', 'danger');
    }
}

async function viewTemplate(templateId) {
    try {
        const response = await fetch(`/schedule/api/templates/${templateId}`);
        const data = await response.json();
        
        if (data.success) {
            // Create and show template details modal
            showTemplateDetailsModal(data.template);
        }
    } catch (error) {
        console.error('Error loading template details:', error);
        showTemplateAlert('Error loading template details', 'danger');
    }
}

function showTemplateDetailsModal(template) {
    // Create template details modal HTML
    const modalHtml = `
        <div class="modal fade" id="templateDetailsViewModal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="bi bi-file-text"></i> ${templateManager.escapeHtml(template.name)}
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="row">
                            <div class="col-md-6">
                                <h6>Template Information</h6>
                                <table class="table table-sm">
                                    <tr><td><strong>Name:</strong></td><td>${templateManager.escapeHtml(template.name)}</td></tr>
                                    <tr><td><strong>Type:</strong></td><td>${template.template_type || 'Weekly'}</td></tr>
                                    <tr><td><strong>Duration:</strong></td><td>${template.duration_days || 7} days</td></tr>
                                    <tr><td><strong>Scope:</strong></td><td>${template.scope_display || 'N/A'}</td></tr>
                                    <tr><td><strong>Visibility:</strong></td><td>${template.is_public ? 'Public' : 'Private'}</td></tr>
                                    <tr><td><strong>Usage:</strong></td><td>${template.usage_count || 0} times</td></tr>
                                </table>
                            </div>
                            <div class="col-md-6">
                                <h6>Statistics</h6>
                                <div class="row text-center">
                                    <div class="col-4">
                                        <div class="bg-primary text-white rounded p-2 mb-2">
                                            <div class="fw-bold">${template.total_employees || 0}</div>
                                            <small>Employees</small>
                                        </div>
                                    </div>
                                    <div class="col-4">
                                        <div class="bg-success text-white rounded p-2 mb-2">
                                            <div class="fw-bold">${template.total_shifts || 0}</div>
                                            <small>Shifts</small>
                                        </div>
                                    </div>
                                    <div class="col-4">
                                        <div class="bg-info text-white rounded p-2 mb-2">
                                            <div class="fw-bold">${template.duration_days || 7}</div>
                                            <small>Days</small>
                                        </div>
                                    </div>
                                </div>
                                
                                <h6 class="mt-3">Created</h6>
                                <p class="text-muted small">
                                    By: ${templateManager.escapeHtml(template.created_by)}<br>
                                    On: ${new Date(template.created_at).toLocaleDateString()}
                                    ${template.last_used_at ? `<br>Last used: ${new Date(template.last_used_at).toLocaleDateString()}` : ''}
                                </p>
                            </div>
                        </div>
                        
                        ${template.description ? `
                        <div class="mt-3">
                            <h6>Description</h6>
                            <p class="text-muted">${templateManager.escapeHtml(template.description)}</p>
                        </div>
                        ` : ''}
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        <button type="button" class="btn btn-outline-primary" onclick="duplicateTemplate(${template.id}); $('#templateDetailsViewModal').modal('hide');">
                            <i class="bi bi-files"></i> Duplicate
                        </button>
                        <button type="button" class="btn btn-primary" onclick="useTemplate(${template.id}); $('#templateDetailsViewModal').modal('hide');">
                            <i class="bi bi-arrow-repeat"></i> Apply Template
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Remove existing modal
    const existingModal = document.getElementById('templateDetailsViewModal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add modal to body and show
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modal = new bootstrap.Modal(document.getElementById('templateDetailsViewModal'));
    modal.show();

    // Clean up when hidden
    document.getElementById('templateDetailsViewModal').addEventListener('hidden.bs.modal', () => {
        document.getElementById('templateDetailsViewModal').remove();
    });
}

async function duplicateTemplate(templateId) {
    try {
        const templateName = prompt('Enter name for the duplicate template:');
        if (!templateName || templateName.trim() === '') return;
        
        const response = await fetch(`/schedule/api/templates/${templateId}/duplicate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: templateName.trim()
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showTemplateAlert(result.message, 'success');
            if (templateManager) {
                await templateManager.loadTemplates();
            }
        } else {
            showTemplateAlert(result.error || 'Error duplicating template', 'danger');
        }
    } catch (error) {
        console.error('Error duplicating template:', error);
        showTemplateAlert('Error duplicating template', 'danger');
    }
}

// ENHANCED: Delete Template with Better Confirmation
async function deleteTemplate(templateId, templateName = '') {
    // Show enhanced confirmation modal
    const confirmed = await showDeleteConfirmationModal(templateId, templateName);
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/schedule/api/templates/${templateId}`, {
            method: 'DELETE',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const result = await response.json();
        
        if (result.success) {
            showTemplateAlert(result.message, 'success');
            if (templateManager) {
                await templateManager.loadTemplates();
            }
        } else {
            showTemplateAlert(result.error || 'Error deleting template', 'danger');
        }
    } catch (error) {
        console.error('Error deleting template:', error);
        showTemplateAlert('Error deleting template', 'danger');
    }
}

// Enhanced Delete Confirmation Modal
function showDeleteConfirmationModal(templateId, templateName) {
    return new Promise((resolve) => {
        const modalHtml = `
            <div class="modal fade" id="deleteTemplateConfirmModal" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header border-0">
                            <h5 class="modal-title text-danger">
                                <i class="bi bi-exclamation-triangle-fill"></i> Delete Template
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-danger">
                                <i class="bi bi-shield-exclamation"></i>
                                <strong>This action cannot be undone!</strong>
                            </div>
                            <p>Are you sure you want to permanently delete this template?</p>
                            
                            <div class="card bg-light">
                                <div class="card-body">
                                    <h6 class="card-title text-primary">${templateManager.escapeHtml(templateName)}</h6>
                                    <p class="card-text text-muted small mb-0">
                                        This will permanently remove the template and all its configuration. 
                                        Schedules already created from this template will not be affected.
                                    </p>
                                </div>
                            </div>
                            
                            <div class="mt-3">
                                <p class="text-muted small">
                                    <i class="bi bi-info-circle"></i>
                                    <strong>What happens when you delete:</strong>
                                </p>
                                <ul class="text-muted small">
                                    <li>Template configuration is permanently removed</li>
                                    <li>Template usage history is lost</li>
                                    <li>Other users can no longer access this template</li>
                                    <li>Existing schedules created from this template remain unchanged</li>
                                </ul>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="bi bi-x-circle"></i> Cancel
                            </button>
                            <button type="button" class="btn btn-danger" id="confirmDeleteTemplateBtn">
                                <i class="bi bi-trash-fill"></i> Yes, Delete Template
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Remove existing modal
        const existingModal = document.getElementById('deleteTemplateConfirmModal');
        if (existingModal) {
            existingModal.remove();
        }

        // Add modal to body
        document.body.insertAdjacentHTML('beforeend', modalHtml);

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('deleteTemplateConfirmModal'));
        modal.show();

        // Handle confirmation
        document.getElementById('confirmDeleteTemplateBtn').addEventListener('click', () => {
            modal.hide();
            resolve(true);
        });

        // Handle cancellation and cleanup
        document.getElementById('deleteTemplateConfirmModal').addEventListener('hidden.bs.modal', () => {
            document.getElementById('deleteTemplateConfirmModal').remove();
            resolve(false);
        });
    });
}

async function quickApplyTemplate() {
    const templateId = document.getElementById('quickTemplateSelect').value;
    const targetDate = document.getElementById('quickTargetDate').value;
    const replaceExisting = document.getElementById('quickReplaceExisting').checked;
    
    if (!templateId || !targetDate) {
        showTemplateAlert('Please select a template and target date', 'warning');
        return;
    }
    
    try {
        // Get template details to calculate end date
        const templateResponse = await fetch(`/schedule/api/templates/${templateId}`);
        const templateData = await templateResponse.json();
        
        if (!templateData.success) {
            showTemplateAlert('Error loading template details', 'danger');
            return;
        }
        
        const template = templateData.template;
        const startDate = new Date(targetDate);
        const endDate = new Date(startDate);
        endDate.setDate(startDate.getDate() + (template.duration_days - 1));
        
        // Apply template
        const response = await fetch(`/schedule/api/templates/${templateId}/apply`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                target_start_date: targetDate,
                target_end_date: endDate.toISOString().split('T')[0],
                replace_existing: replaceExisting
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showTemplateAlert(result.message, 'success');
            
            // Close modal
            const modalElement = document.getElementById('quickApplyTemplateModal');
            const modal = bootstrap.Modal.getInstance(modalElement);
            if (modal) {
                modal.hide();
            }
            
            // Refresh schedule view
            if (typeof refreshScheduleView === 'function') {
                refreshScheduleView();
            }
        } else {
            showTemplateAlert(result.error || 'Error applying template', 'danger');
        }
    } catch (error) {
        console.error('Error applying template:', error);
        showTemplateAlert('Error applying template', 'danger');
    }
}

function filterTemplates(type, searchTerm = '') {
    if (!templateManager) return;
    
    let filteredTemplates = [...templateManager.templates];

    if (type === 'mine') {
        filteredTemplates = filteredTemplates.filter(t => t.created_by === window.currentUser?.name);
    } else if (type === 'public') {
        filteredTemplates = filteredTemplates.filter(t => t.is_public);
    } else if (type === 'search' && searchTerm) {
        const term = searchTerm.toLowerCase();
        filteredTemplates = filteredTemplates.filter(t => 
            t.name.toLowerCase().includes(term) || 
            (t.description && t.description.toLowerCase().includes(term))
        );
    }

    // Update filter buttons
    document.querySelectorAll('.btn-group .btn').forEach(btn => {
        btn.classList.remove('active');
    });
    
    if (type !== 'search') {
        const activeBtn = document.querySelector(`.btn-group .btn[onclick*="${type}"]`);
        if (activeBtn) {
            activeBtn.classList.add('active');
        }
    }

    // Temporarily store all templates and render filtered ones
    const allTemplates = templateManager.templates;
    templateManager.templates = filteredTemplates;
    templateManager.renderTemplatesGrid();
    templateManager.templates = allTemplates;
}

function updateScopeOptions() {
    const scopeType = document.querySelector('select[name="scope_type"]').value;
    const scopeSelection = document.getElementById('scopeSelection');
    const scopeSelect = document.querySelector('select[name="scope_id"]');
    
    if (!scopeType || !templateManager.organizationalScope) {
        scopeSelection.style.display = 'none';
        return;
    }
    
    scopeSelection.style.display = 'block';
    
    let options = '<option value="">Select...</option>';
    
    switch (scopeType) {
        case 'department':
            if (templateManager.organizationalScope.departments) {
                options += templateManager.organizationalScope.departments.map(dept => 
                    `<option value="${dept.id}">${templateManager.escapeHtml(dept.name)}</option>`
                ).join('');
            }
            break;
        case 'division':
            if (templateManager.organizationalScope.divisions) {
                options += templateManager.organizationalScope.divisions.map(div => 
                    `<option value="${div.id}">${templateManager.escapeHtml(div.name)}</option>`
                ).join('');
            }
            break;
        case 'section':
            if (templateManager.organizationalScope.sections) {
                options += templateManager.organizationalScope.sections.map(sec => 
                    `<option value="${sec.id}">${templateManager.escapeHtml(sec.name)}</option>`
                ).join('');
            }
            break;
        case 'unit':
            if (templateManager.organizationalScope.units) {
                options += templateManager.organizationalScope.units.map(unit => 
                    `<option value="${unit.id}">${templateManager.escapeHtml(unit.name)}</option>`
                ).join('');
            }
            break;
    }
    
    scopeSelect.innerHTML = options;
}

function updateTargetScopeOptions() {
    const scopeType = document.querySelector('select[name="target_scope_type"]').value;
    const scopeSelection = document.getElementById('targetScopeSelection');
    const scopeSelect = document.querySelector('select[name="target_scope_id"]');
    
    if (!scopeType || !templateManager.organizationalScope) {
        scopeSelection.style.display = 'none';
        return;
    }
    
    scopeSelection.style.display = 'block';
    
    let options = '<option value="">Select...</option>';
    
    switch (scopeType) {
        case 'section':
            if (templateManager.organizationalScope.sections) {
                options += templateManager.organizationalScope.sections.map(sec => 
                    `<option value="${sec.id}">${templateManager.escapeHtml(sec.name)}</option>`
                ).join('');
            }
            break;
        case 'unit':
            if (templateManager.organizationalScope.units) {
                options += templateManager.organizationalScope.units.map(unit => 
                    `<option value="${unit.id}">${templateManager.escapeHtml(unit.name)}</option>`
                ).join('');
            }
            break;
    }
    
    scopeSelect.innerHTML = options;
}

async function generatePreview() {
    const form = document.getElementById('applyTemplateForm');
    const formData = new FormData(form);
    const templateId = formData.get('template_id');
    
    if (!templateId) {
        showTemplateAlert('No template selected', 'warning');
        return;
    }
    
    try {
        const data = {
            target_start_date: formData.get('target_start_date'),
            target_end_date: formData.get('target_end_date'),
            target_section_id: formData.get('target_scope_id')
        };
        
        const response = await fetch(`/schedule/api/templates/${templateId}/preview`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (result.success) {
            displayApplicationPreview(result.preview);
        } else {
            showTemplateAlert(result.error || 'Error generating preview', 'danger');
        }
    } catch (error) {
        console.error('Error generating preview:', error);
        showTemplateAlert('Error generating preview', 'danger');
    }
}

function displayApplicationPreview(preview) {
    const previewContainer = document.getElementById('applicationPreview');
    const previewContent = document.getElementById('previewContent');
    
    if (!previewContainer || !previewContent) return;
    
    let html = `
        <div class="row">
            <div class="col-md-6">
                <h6><i class="bi bi-info-circle text-info"></i> Application Summary</h6>
                <ul class="list-group list-group-flush">
                    <li class="list-group-item d-flex justify-content-between">
                        <span>Date Range:</span>
                        <strong>${preview.date_range}</strong>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>Duration Match:</span>
                        <span class="badge ${preview.duration_match ? 'bg-success' : 'bg-warning'}">
                            ${preview.duration_match ? 'Perfect' : 'Mismatch'}
                        </span>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>Shifts to Create:</span>
                        <strong class="text-primary">${preview.shifts_to_create}</strong>
                    </li>
                    <li class="list-group-item d-flex justify-content-between">
                        <span>Target Employees:</span>
                        <strong class="text-success">${preview.target_employees.length}</strong>
                    </li>
                </ul>
            </div>
            <div class="col-md-6">
                <h6><i class="bi bi-exclamation-triangle text-warning"></i> Potential Issues</h6>
                ${preview.conflicts ? `
                <div class="alert alert-warning">
                    <strong>${preview.existing_shifts}</strong> existing shifts found. 
                    ${preview.existing_shifts > 0 ? 'Enable "Replace existing shifts" to overwrite them.' : ''}
                </div>
                ` : `
                <div class="alert alert-success">
                    <i class="bi bi-check-circle"></i> No conflicts detected!
                </div>
                `}
                
                ${!preview.duration_match ? `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle"></i>
                    <strong>Duration Mismatch!</strong> Template duration doesn't match target date range.
                </div>
                ` : ''}
            </div>
        </div>
        
        ${preview.target_employees.length > 0 ? `
        <div class="mt-3">
            <h6><i class="bi bi-people text-primary"></i> Target Employees (${preview.target_employees.length})</h6>
            <div class="row">
                ${preview.target_employees.slice(0, 12).map(emp => `
                    <div class="col-md-4 col-sm-6 mb-1">
                        <small class="text-muted">${templateManager.escapeHtml(emp.name)}</small>
                        ${emp.role ? `<br><small class="text-info">${templateManager.escapeHtml(emp.role)}</small>` : ''}
                    </div>
                `).join('')}
                ${preview.target_employees.length > 12 ? `
                    <div class="col-12">
                        <small class="text-muted">... and ${preview.target_employees.length - 12} more employees</small>
                    </div>
                ` : ''}
            </div>
        </div>
        ` : ''}
    `;
    
    previewContent.innerHTML = html;
    previewContainer.style.display = 'block';
}

function applySelectedTemplate() {
    if (templateManager) {
        templateManager.handleApplyTemplate();
    } else {
        console.error('Template manager not initialized');
    }
}

// Utility function to refresh templates list
function refreshTemplates() {
    if (templateManager) {
        templateManager.loadTemplates();
        showTemplateAlert('Templates refreshed', 'info');
    }
}

// Add keyboard shortcuts for template management
document.addEventListener('keydown', function(e) {
    // Ctrl+Shift+T to open template modal
    if (e.ctrlKey && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        showTemplateModal();
    }
    
    // Escape key to close modals
    if (e.key === 'Escape') {
        const openModals = document.querySelectorAll('.modal.show');
        openModals.forEach(modal => {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) {
                bsModal.hide();
            }
        });
    }
});

// Auto-refresh templates every 30 seconds if modal is open
setInterval(() => {
    const templateModal = document.getElementById('templateManagementModal');
    if (templateModal && templateModal.classList.contains('show') && templateManager) {
        templateManager.loadTemplates();
    }
}, 30000);
