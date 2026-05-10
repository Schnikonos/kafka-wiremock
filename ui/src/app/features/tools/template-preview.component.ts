import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormControl } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-template-preview',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatTabsModule,
    MatProgressBarModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Template Preview & Validation</mat-card-title>
          <mat-card-subtitle>Test template expressions with real-time rendering and placeholder resolution</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <mat-tab-group>
            <!-- Template Tester Tab -->
            <mat-tab label="Render Template">
              <div class="tab-content">
                <div class="input-section">
                  <h3>Template Configuration</h3>

                  <mat-form-field appearance="outline" class="full-width">
                    <mat-label>Template String</mat-label>
                    <textarea matInput [(ngModel)]="templateString" rows="6"
                              placeholder="Example template: {&#10;  &quot;id&quot;: prefixed with braces and placeholder names&#10;}"></textarea>
                    <mat-hint>Use braces syntax for variables</mat-hint>
                  </mat-form-field>

                  <h4>Context Variables (JSON)</h4>
                  <mat-form-field appearance="outline" class="full-width">
                    <mat-label>Context</mat-label>
                    <textarea matInput [(ngModel)]="contextString" rows="4"
                              placeholder='{&#10;  "amount": 99.99,&#10;  "customerId": "CUST-123"&#10;}'></textarea>
                  </mat-form-field>

                  <div class="button-group">
                    <button mat-raised-button color="primary" (click)="renderTemplate()" [disabled]="isRendering">
                      <mat-icon>play_arrow</mat-icon>
                      Render Template
                    </button>
                    <button mat-stroked-button (click)="clearForm()">
                      <mat-icon>clear</mat-icon>
                      Clear
                    </button>
                  </div>

                  <mat-progress-bar *ngIf="isRendering" mode="indeterminate"></mat-progress-bar>
                </div>

                 <!-- Rendering Result -->
                 <mat-expansion-panel *ngIf="renderResult" [expanded]="true" class="result-panel">
                   <mat-expansion-panel-header>
                     <mat-panel-title>
                       <mat-icon [ngClass]="renderResult.success !== false ? 'success' : 'error'">
                         {{ renderResult.success !== false ? 'check_circle' : 'error' }}
                       </mat-icon>
                       {{ renderResult.success !== false ? 'Rendered Successfully' : 'Rendering Failed' }}
                     </mat-panel-title>
                   </mat-expansion-panel-header>

                    <div class="result-content">
                      <h4>Output</h4>
                      <pre class="code-display">{{ (renderResult.rendered || renderResult.rendered_value || 'No output') }}</pre>

                      <h4>Details</h4>
                      <div class="details-grid">
                        <div class="detail-item">
                          <span class="label">Original Length</span>
                          <span class="value">{{ renderResult.template?.length || renderResult.template_length || 0 }} chars</span>
                        </div>
                        <div class="detail-item">
                          <span class="label">Rendered Length</span>
                          <span class="value">{{ (renderResult.rendered || renderResult.rendered_value)?.length || renderResult.rendered_length || 0 }} chars</span>
                        </div>
                       <div class="detail-item">
                         <span class="label">Substitutions</span>
                         <span class="value">{{ (renderResult.placeholders_found?.length || countSubstitutions(renderResult.template, renderResult.rendered_value)) }}</span>
                       </div>
                     </div>

                     <div *ngIf="renderResult.error || renderResult.error_message" class="error-message">
                       <mat-icon>warning</mat-icon>
                       <span>{{ renderResult.error || renderResult.error_message }}</span>
                     </div>

                     <button mat-stroked-button color="primary" (click)="copyResult()">
                       <mat-icon>content_copy</mat-icon>
                       Copy Result
                     </button>
                   </div>
                 </mat-expansion-panel>
              </div>
            </mat-tab>

            <!-- Placeholder Reference Tab -->
            <mat-tab label="Placeholder Reference">
              <div class="tab-content reference-content">
                <h3>Available Placeholders</h3>

                 <div class="placeholder-category">
                  <h4>Built-in Functions</h4>
                  <div class="placeholder-list">
                    <div class="placeholder-item">
                      <code ngNonBindable>{{uuid}}</code>
                      <span>UUID v4 - Generates a unique ID</span>
                      <span class="example">Example: b0e1f89c-c0d9-4d02-a6f1-d8e7c2b5f4a1</span>
                    </div>
                    <div class="placeholder-item">
                      <code ngNonBindable>{{now}}</code>
                      <span>Current timestamp in ISO-8601 format</span>
                      <span class="example">Example: 2026-05-06T14:30:45.123Z</span>
                    </div>
                    <div class="placeholder-item">
                      <code ngNonBindable>{{now+5m}}</code>
                      <span>Timestamp with offset (m=minutes, h=hours, d=days)</span>
                      <span class="example" ngNonBindable>Example: {{now+1h}}, {{now+30m}}, {{now+1d}}</span>
                    </div>
                    <div class="placeholder-item">
                      <code ngNonBindable>{{randomInt(1,100)}}</code>
                      <span>Random integer between min and max (inclusive)</span>
                      <span class="example" ngNonBindable>Example: {{randomInt(1,100)}} generates 1-100</span>
                    </div>
                  </div>
                </div>

                <div class="placeholder-category">
                  <h4>Context Variables (from message)</h4>
                  <div class="placeholder-list">
                    <div class="placeholder-item">
                      <code ngNonBindable>{{$.fieldName}}</code>
                      <span>JSONPath extraction from message context</span>
                      <span class="example" ngNonBindable>Example: {{$.orderId}}, {{$.customer.email}}</span>
                    </div>
                    <div class="placeholder-item">
                      <code ngNonBindable>{{message}}</code>
                      <span>The entire message object as JSON</span>
                      <span class="example" ngNonBindable>Example: {{message}} renders full message</span>
                    </div>
                  </div>
                </div>

                <div class="placeholder-category">
                  <h4>Custom Placeholders</h4>
                  <p class="hint">Defined in /config/custom_placeholders/</p>

                  <div *ngIf="customPlaceholders.length === 0" class="empty-state">
                    <mat-icon>inbox</mat-icon>
                    <p>No custom placeholders found</p>
                  </div>

                  <div *ngIf="customPlaceholders.length > 0" class="placeholder-list">
                    <div *ngFor="let ph of customPlaceholders" class="placeholder-item custom">
                      <code>{{ '{{' }}{{ ph.name }}{{ '}}' }}</code>
                      <span>{{ ph.docstring || 'Custom placeholder' }}</span>
                      <span *ngIf="ph.order" class="order-badge">Order: {{ ph.order }}</span>
                    </div>
                  </div>

                  <button mat-raised-button (click)="loadCustomPlaceholders()">
                    <mat-icon>refresh</mat-icon>
                    Refresh Custom Placeholders
                  </button>
                </div>

                <div class="placeholder-category">
                  <h4>Common Patterns</h4>
                  <div class="pattern-list">
                    <div class="pattern">
                      <code ngNonBindable>{{uuid}}</code> + <code ngNonBindable>{{now}}</code>
                      <span>Generate unique message ID with timestamp</span>
                    </div>
                    <div class="pattern">
                      <code ngNonBindable>{{$.amount}}</code> with <code ngNonBindable>{{randomInt(1,10)}}</code>
                      <span>Calculate derived values from input</span>
                    </div>
                    <div class="pattern">
                      <code ngNonBindable>{{now+24h}}</code>
                      <span>Set expiration timestamps</span>
                    </div>
                  </div>
                </div>
              </div>
            </mat-tab>

            <!-- Live Preview Tab -->
            <mat-tab label="Live Preview">
              <div class="tab-content">
                <h3>Quick Test Templates</h3>
                <p class="hint">Common templates for quick preview</p>

                <div class="template-examples">
                  <button *ngFor="let example of templateExamples" mat-stroked-button
                          (click)="loadExample(example)" class="example-button">
                    {{ example.label }}
                  </button>
                </div>

                <h4>Order Message Template</h4>
                <pre class="code-display example-template">{{exampleOrderTemplate}}</pre>

                <button mat-raised-button color="primary" (click)="renderExampleOrder()">
                  <mat-icon>play_arrow</mat-icon>
                  Test Order Template
                </button>

                <mat-expansion-panel *ngIf="exampleResult" [expanded]="true" class="result-panel">
                  <mat-expansion-panel-header>
                    <mat-panel-title>Preview Result</mat-panel-title>
                  </mat-expansion-panel-header>
                  <pre class="code-display">{{ exampleResult }}</pre>
                </mat-expansion-panel>
              </div>
            </mat-tab>
          </mat-tab-group>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .container {
      padding: 24px;
      max-width: 1400px;
      margin: 0 auto;
    }

    .tab-content {
      padding: 24px;
    }

    .input-section {
      margin-bottom: 24px;
    }

    .input-section h3 {
      margin: 0 0 16px 0;
      color: #333;
    }

    .input-section h4 {
      margin: 24px 0 12px 0;
      color: #666;
      font-size: 14px;
    }

    .full-width {
      width: 100%;
      margin-bottom: 16px;
    }

    .button-group {
      display: flex;
      gap: 8px;
      margin: 16px 0;
      flex-wrap: wrap;
    }

    .result-panel {
      margin-top: 24px;
    }

    .result-content {
      padding: 16px 0;
    }

    .result-content h4 {
      margin: 16px 0 8px 0;
      color: #333;
      font-size: 14px;
    }

    .code-display {
      background-color: #f5f5f5;
      border: 1px solid #eee;
      border-radius: 4px;
      padding: 12px;
      font-family: 'Courier New', monospace;
      font-size: 12px;
      overflow-x: auto;
      margin: 8px 0;
    }

    .details-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 16px;
      margin: 12px 0;
      padding: 12px;
      background-color: #f9f9f9;
      border-radius: 4px;
    }

    .detail-item {
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .detail-item .label {
      font-size: 12px;
      color: #999;
      font-weight: 500;
    }

    .detail-item .value {
      font-size: 16px;
      font-weight: 500;
      color: #333;
    }

    .error-message {
      display: flex;
      gap: 12px;
      padding: 12px;
      background-color: #ffebee;
      border-left: 3px solid #f44336;
      border-radius: 3px;
      color: #b71c1c;
      margin: 12px 0;
      align-items: flex-start;
    }

    .error-message mat-icon {
      margin-top: 2px;
      flex-shrink: 0;
    }

    .success {
      color: #2e7d32;
    }

    .error {
      color: #c62828;
    }

    .reference-content h3 {
      margin: 0 0 16px 0;
      color: #333;
    }

    .placeholder-category {
      margin-bottom: 32px;
    }

    .placeholder-category h4 {
      margin: 0 0 12px 0;
      color: #1976d2;
      font-size: 14px;
      font-weight: 500;
    }

    .placeholder-category .hint {
      margin: -8px 0 12px 0;
      font-size: 12px;
      color: #999;
    }

    .placeholder-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .placeholder-item {
      padding: 12px;
      background-color: #f9f9f9;
      border-radius: 4px;
      border-left: 3px solid #1976d2;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .placeholder-item code {
      background-color: #e3f2fd;
      color: #0d47a1;
      padding: 2px 6px;
      border-radius: 3px;
      font-weight: 500;
      display: inline-block;
      width: fit-content;
    }

    .placeholder-item span:nth-child(2) {
      color: #666;
      font-size: 14px;
    }

    .placeholder-item .example {
      color: #999;
      font-size: 12px;
      font-style: italic;
      margin-top: 4px;
    }

    .placeholder-item.custom {
      border-left-color: #4caf50;
    }

    .placeholder-item.custom code {
      background-color: #e8f5e9;
      color: #1b5e20;
    }

    .order-badge {
      display: inline-block;
      background-color: #fff3e0;
      color: #e65100;
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 11px;
      font-weight: 500;
    }

    .pattern-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .pattern {
      padding: 8px 12px;
      background-color: #f0f8f0;
      border-left: 3px solid #4caf50;
      border-radius: 3px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .pattern code {
      background-color: #e8f5e9;
      color: #1b5e20;
      padding: 2px 6px;
      border-radius: 3px;
      font-size: 12px;
      display: inline-block;
      width: fit-content;
    }

    .pattern span:nth-child(2) {
      color: #666;
      font-size: 12px;
    }

    .empty-state {
      text-align: center;
      padding: 40px;
      color: #999;
    }

    .empty-state mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: #bdbdbd;
      margin-bottom: 16px;
    }

    .template-examples {
      display: flex;
      gap: 8px;
      margin: 16px 0;
      flex-wrap: wrap;
    }

    .example-button {
      font-size: 12px;
    }

    .example-template {
      font-size: 11px;
      max-height: 200px;
    }
  `]
})
export class TemplatePreviewComponent implements OnInit {
  templateString = '';
  contextString = '';
  renderResult: any = null;
  customPlaceholders: any[] = [];
  isRendering = false;
  exampleResult: string = '';

  exampleOrderTemplate = `{
  "orderId": "{{uuid}}",
  "timestamp": "{{now}}",
  "expiresAt": "{{now+24h}}",
  "status": "PENDING",
  "amount": 99.99,
  "trackingNumber": "ORD-{{randomInt(100000,999999)}}"
}`;

  templateExamples = [
    { label: 'Simple UUID', template: '{{ "id": "{{uuid}}" }}' },
    { label: 'Full Order', template: this.exampleOrderTemplate },
    { label: 'With Context', template: '{{ "userId": "{{$.userId}}", "createdAt": "{{now}}" }}' },
    { label: 'Timestamp +1h', template: '{{ "expiresAt": "{{now+1h}}" }}' },
    { label: 'Random Data', template: '{{ "code": "CODE-{{randomInt(1000,9999)}}", "timestamp": "{{now}}" }}' },
  ];

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit() {
    this.loadCustomPlaceholders();
  }

  renderTemplate() {
    if (!this.templateString.trim()) {
      this.snackBar.open('Please enter a template string', 'Close', { duration: 3000 });
      return;
    }

    try {
      const context = this.contextString.trim() ? JSON.parse(this.contextString) : {};
      this.isRendering = true;

      this.api.renderTemplate(this.templateString, context).subscribe({
        next: (result) => {
          this.renderResult = result;
          this.isRendering = false;

          if (result.success) {
            this.snackBar.open('Template rendered successfully!', 'Close', { duration: 3000 });
          } else {
            this.snackBar.open('Template rendering completed with errors', 'Close', { duration: 3000 });
          }
        },
        error: (err) => {
          this.isRendering = false;
          this.snackBar.open('Rendering failed: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
        }
      });
    } catch (e) {
      this.snackBar.open('Invalid context JSON', 'Close', { duration: 3000 });
    }
  }

  renderExampleOrder() {
    this.templateString = this.exampleOrderTemplate;
    this.contextString = '';
    this.renderTemplate();
  }

  loadExample(example: any) {
    this.templateString = example.template;
    this.contextString = '';
  }

  clearForm() {
    this.templateString = '';
    this.contextString = '';
    this.renderResult = null;
    this.exampleResult = '';
  }

  loadCustomPlaceholders() {
    this.api.getCustomPlaceholders().subscribe({
      next: (placeholders: any) => {
        this.customPlaceholders = Array.isArray(placeholders) ? placeholders : (placeholders?.placeholders || []);
      },
      error: (err) => {
        console.error('Failed to load custom placeholders:', err);
        this.customPlaceholders = [];
      }
    });
  }

  copyResult() {
    const result = this.renderResult?.rendered || this.renderResult?.rendered_value;
    if (result) {
      navigator.clipboard.writeText(result).then(() => {
        this.snackBar.open('Result copied to clipboard!', 'Close', { duration: 2000 });
      }).catch(err => {
        console.error('Failed to copy:', err);
        this.snackBar.open('Failed to copy result', 'Close', { duration: 2000 });
      });
    } else {
      this.snackBar.open('No result to copy', 'Close', { duration: 2000 });
    }
  }

  countSubstitutions(original: string, rendered: string): number {
    if (!original) return 0;
    const placeholderMatches = original.match(/\{\{.*?\}\}/g) || [];
    return placeholderMatches.length;
  }
}

