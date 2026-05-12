import { Component, OnInit, Inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatCardModule } from '@angular/material/card';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSelectModule } from '@angular/material/select';
import { MatDividerModule } from '@angular/material/divider';

import { AppConfigService, AppSettings } from '../../core/services/app-config.service';

@Component({
  selector: 'app-settings-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatIconModule,
    MatSnackBarModule,
    MatCardModule,
    MatSlideToggleModule,
    MatDividerModule,
    MatSelectModule,
  ],
  template: `
    <h2 mat-dialog-title>Application Settings</h2>
    <mat-dialog-content>
      <form [formGroup]="settingsForm">
        <mat-card class="settings-card">
          <mat-card-header>
            <mat-card-title class="section-title">UI Settings</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Test Recap Threshold</mat-label>
              <input
                matInput
                type="number"
                formControlName="testRecapThreshold"
                min="0"
                placeholder="100">
              <mat-icon matSuffix>tune</mat-icon>
              <mat-hint>
                Show recap popup when test runs exceed this value (0 = always show, 100+ = rarely show)
              </mat-hint>
            </mat-form-field>
          </mat-card-content>
        </mat-card>

        <mat-card class="settings-card">
          <mat-card-header>
            <mat-card-title class="section-title">Verbose / Diagnostic Mode</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-label">Verbose Rules</span>
                <span class="toggle-hint">Log per-condition match diagnostics for every rule evaluation (expected value, actual value, result)</span>
              </div>
              <mat-slide-toggle formControlName="verboseRules" color="accent"></mat-slide-toggle>
            </div>

            <mat-divider class="divider"></mat-divider>

            <div class="toggle-row">
              <div class="toggle-info">
                <span class="toggle-label">Verbose Tests</span>
                <span class="toggle-hint">Include sent/received messages and per-condition breakdowns in test log files</span>
              </div>
              <mat-slide-toggle formControlName="verboseTests" color="accent"></mat-slide-toggle>
            </div>
          </mat-card-content>
        </mat-card>

        <mat-card class="settings-card">
          <mat-card-header>
            <mat-card-title class="section-title">Export</mat-card-title>
          </mat-card-header>
          <mat-card-content>
            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Default Export Format</mat-label>
              <mat-select formControlName="exportFormat">
                <mat-option value="json">
                  JSON — full-fidelity, suitable for programmatic processing
                </mat-option>
                <mat-option value="html">
                  HTML — visual report with collapsible details, open in any browser
                </mat-option>
                <mat-option value="csv">
                  CSV — condensed summary table, open in Excel / Google Sheets
                </mat-option>
              </mat-select>
              <mat-hint>Used by the Export button on the Tests and Logs pages</mat-hint>
            </mat-form-field>
          </mat-card-content>
        </mat-card>

        <div class="info-box">
          <mat-icon class="info-icon">info</mat-icon>
          <div class="info-text">
            <strong>Note:</strong> Settings are persisted to <code>config/app-settings.json</code> and survive container recreation.
          </div>
        </div>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="onCancel()">Cancel</button>
      <button
        mat-raised-button
        color="primary"
        (click)="onSave()"
        [disabled]="settingsForm.invalid || isSaving">
        <mat-icon *ngIf="!isSaving">save</mat-icon>
        <mat-icon *ngIf="isSaving" class="spinner">sync</mat-icon>
        {{ isSaving ? 'Saving...' : 'Save Settings' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: [`
    mat-dialog-content {
      padding: 20px;
      min-width: 420px;
    }

    .settings-card {
      margin-bottom: 20px;
    }

    .section-title {
      font-size: 16px;
      font-weight: 500;
      margin: 0;
    }

    mat-card-content {
      padding: 16px;
    }

    .full-width {
      width: 100%;
    }

    .toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 8px 0;
    }

    .toggle-info {
      display: flex;
      flex-direction: column;
      gap: 4px;
      flex: 1;
    }

    .toggle-label {
      font-size: 14px;
      font-weight: 500;
      color: #333;
    }

    .toggle-hint {
      font-size: 12px;
      color: #777;
      line-height: 1.4;
    }

    .divider {
      margin: 8px 0;
    }

    .info-box {
      display: flex;
      gap: 12px;
      padding: 12px;
      background-color: #e3f2fd;
      border: 1px solid #90caf9;
      border-radius: 4px;
      color: #1976d2;
      font-size: 14px;
      margin-bottom: 16px;
    }

    .info-icon {
      color: #1976d2;
      flex-shrink: 0;
      margin-top: 2px;
    }

    .info-text {
      line-height: 1.5;
    }

    .info-text code {
      background-color: #e0e0e0;
      padding: 2px 6px;
      border-radius: 3px;
      font-family: 'Courier New', monospace;
      font-size: 12px;
    }

    .spinner {
      animation: spin 1s linear infinite;
    }

    @keyframes spin {
      from {
        transform: rotate(0deg);
      }
      to {
        transform: rotate(360deg);
      }
    }

    mat-dialog-actions {
      padding: 16px 0 0 0;
    }
  `]
})
export class AppSettingsDialogComponent implements OnInit {
  settingsForm: FormGroup;
  isSaving = false;

  constructor(
    private fb: FormBuilder,
    private appConfigService: AppConfigService,
    private snackBar: MatSnackBar,
    public dialogRef: MatDialogRef<AppSettingsDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: any
  ) {
    this.settingsForm = this.fb.group({
      testRecapThreshold: [100, [Validators.required, Validators.min(0)]],
      verboseRules: [false],
      verboseTests: [false],
      exportFormat: ['json'],
    });
  }

  ngOnInit() {
    const settings = this.appConfigService.getSettings();
    if (settings) {
      this.settingsForm.patchValue({
        testRecapThreshold: settings.ui.test_recap_threshold,
        verboseRules: settings.ui.verbose_rules ?? false,
        verboseTests: settings.ui.verbose_tests ?? false,
        exportFormat: settings.ui.export_format ?? 'json',
      });
    }
  }

  onSave() {
    if (this.settingsForm.invalid) {
      return;
    }

    this.isSaving = true;

    const newSettings: AppSettings = {
      ui: {
        test_recap_threshold: this.settingsForm.get('testRecapThreshold')?.value ?? 100,
        verbose_rules: this.settingsForm.get('verboseRules')?.value ?? false,
        verbose_tests: this.settingsForm.get('verboseTests')?.value ?? false,
        export_format: this.settingsForm.get('exportFormat')?.value ?? 'json',
      }
    };

    this.appConfigService.updateSettings(newSettings).subscribe({
      next: (updatedSettings) => {
        this.isSaving = false;
        this.snackBar.open('✓ Settings saved successfully', 'Close', { duration: 3000 });
        this.dialogRef.close(updatedSettings);
      },
      error: (err) => {
        this.isSaving = false;
        this.snackBar.open('✗ Failed to save settings: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
      }
    });
  }

  onCancel() {
    this.dialogRef.close();
  }
}
