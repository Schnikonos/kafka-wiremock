import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatDialogModule, MatDialog } from '@angular/material/dialog';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { Rule } from '../../core/models';

@Component({
  selector: 'app-rules',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatExpansionModule,
    MatDialogModule,
    MatSnackBarModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Rules Configuration</mat-card-title>
          <mat-card-subtitle>View and test Kafka Wiremock rules with message matching</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Search -->
          <div class="search-section">
            <mat-form-field appearance="outline" class="search-field">
              <mat-label>Search Rules</mat-label>
              <input matInput placeholder="Search by rule name or topic..." [(ngModel)]="searchText"
                     (ngModelChange)="filterRules()">
              <mat-icon matSuffix>search</mat-icon>
            </mat-form-field>
          </div>

          <!-- Rules List -->
          <div *ngIf="filteredRules.length === 0" class="empty-state">
            <mat-icon>inbox</mat-icon>
            <p>{{ searchText ? 'No rules match your search' : 'No rules found' }}</p>
          </div>

          <div *ngFor="let rule of filteredRules; let i = index" class="rule-item">
            <mat-expansion-panel [expanded]="expandedRuleIndex === i">
              <mat-expansion-panel-header>
                <mat-panel-title class="rule-title">
                  <span class="rule-name">{{ rule.name }}</span>
                  <span class="rule-priority">#{{ rule.priority }}</span>
                </mat-panel-title>
                <mat-panel-description class="rule-description">
                  {{ rule.input_destination }} → {{ rule.outputs.length }} output(s)
                </mat-panel-description>
              </mat-expansion-panel-header>

              <div class="rule-details">
                <!-- Input Topic -->
                <div class="detail-section">
                  <h4>Input Topic</h4>
                  <p><code>{{ rule.input_destination }}</code></p>
                </div>

                <!-- Conditions -->
                <div class="detail-section" *ngIf="rule.conditions && rule.conditions.length > 0">
                  <h4>Matching Conditions ({{ rule.conditions.length }})</h4>
                  <div class="conditions-list">
                    <div *ngFor="let cond of rule.conditions; let j = index" class="condition">
                      <span class="condition-type">[{{ cond.type }}]</span>
                      <span *ngIf="cond.expression">{{ cond.expression }}</span>
                      <span *ngIf="cond.value">= {{ cond.value }}</span>
                      <span *ngIf="cond.regex">matches {{ cond.regex }}</span>
                    </div>
                  </div>
                </div>

                <!-- Outputs -->
                <div class="detail-section" *ngIf="rule.outputs && rule.outputs.length > 0">
                  <h4>Output Messages ({{ rule.outputs.length }})</h4>
                  <div class="outputs-list">
                    <div *ngFor="let output of rule.outputs; let j = index" class="output">
                      <div class="output-topic">📤 <code>{{ output.destination }}</code></div>
                      <div *ngIf="output.delay_ms" class="output-meta">
                        Delay: {{ output.delay_ms }}ms
                      </div>
                      <div *ngIf="output.headers" class="output-meta">
                        Headers: {{ Object.keys(output.headers).length }} headers
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Test Rule Matching -->
                <div class="detail-section">
                  <h4>Test Rule Matching</h4>
                  <p class="hint">Test if this rule matches a message with the given payload, key, and headers (key and headers are optional)</p>
                  <div class="test-section">
                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Message Key (optional)</mat-label>
                      <input matInput [(ngModel)]="testKeys[rule.name]" placeholder="message-key-123">
                    </mat-form-field>
                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Message Headers (JSON, optional)</mat-label>
                      <textarea matInput [(ngModel)]="testHeaders[rule.name]" rows="2" placeholder='{"header-name": "value"}'></textarea>
                    </mat-form-field>
                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Message Payload (JSON)</mat-label>
                      <textarea matInput [(ngModel)]="testPayloads[rule.name]"
                                rows="4" placeholder="{...}"></textarea>
                    </mat-form-field>
                    <button mat-raised-button color="primary" (click)="testRule(rule)">
                      <mat-icon>play_arrow</mat-icon>
                      Test Matching
                    </button>
                  </div>

                  <!-- Test Result -->
                  <div *ngIf="testResults[rule.name]" class="test-result"
                       [ngClass]="testResults[rule.name].matched ? 'matched' : 'not-matched'">
                    <mat-icon>{{ testResults[rule.name].matched ? 'check_circle' : 'cancel' }}</mat-icon>
                    <div>
                      <strong>{{ testResults[rule.name].matched ? 'MATCHED ✓' : 'NOT MATCHED ✗' }}</strong>
                      <p *ngIf="testResults[rule.name].matched">
                        Rule will produce {{ testResults[rule.name].outputs_count }} message(s)
                      </p>
                      <p *ngIf="!testResults[rule.name].matched && testResults[rule.name].error">
                        {{ testResults[rule.name].error }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            </mat-expansion-panel>
          </div>
        </mat-card-content>
      </mat-card>
    </div>
  `,
  styles: [`
    .container {
      padding: 24px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .search-section {
      margin-bottom: 24px;
    }

    .search-field {
      width: 400px;
      max-width: 100%;
    }

    .empty-state {
      text-align: center;
      padding: 40px;
      color: #757575;
    }

    .empty-state mat-icon {
      font-size: 48px;
      width: 48px;
      height: 48px;
      color: #bdbdbd;
      margin-bottom: 16px;
    }

    .rule-item {
      margin-bottom: 12px;
    }

    .rule-title {
      display: flex;
      gap: 12px;
      align-items: center;
      flex: 1;
    }

    .rule-name {
      font-weight: 500;
      color: #1976d2;
    }

    .rule-priority {
      font-size: 12px;
      background-color: #f5f5f5;
      padding: 4px 8px;
      border-radius: 4px;
      color: #666;
    }

    .rule-description {
      color: #999 !important;
      font-size: 12px !important;
    }

    .rule-details {
      padding: 16px 24px;
    }

    .detail-section {
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid #eee;
    }

    .detail-section:last-child {
      border-bottom: none;
    }

    .detail-section h4 {
      margin: 0 0 12px 0;
      color: #333;
      font-size: 14px;
      font-weight: 500;
    }

    .conditions-list {
      padding: 12px;
      background-color: #f9f9f9;
      border-radius: 4px;
      border-left: 3px solid #1976d2;
    }

    .condition {
      padding: 8px 0;
      font-family: 'Courier New', monospace;
      font-size: 12px;
      color: #333;
    }

    .condition-type {
      display: inline-block;
      background-color: #e3f2fd;
      color: #1976d2;
      padding: 2px 6px;
      border-radius: 3px;
      font-weight: 500;
      margin-right: 8px;
    }

    .outputs-list {
      padding: 12px;
      background-color: #f0f8f0;
      border-radius: 4px;
      border-left: 3px solid #4caf50;
    }

    .output {
      padding: 8px 0;
      margin-bottom: 8px;
    }

    .output:last-child {
      margin-bottom: 0;
    }

    .output-topic {
      font-family: 'Courier New', monospace;
      font-weight: 500;
      color: #2e7d32;
      margin-bottom: 4px;
    }

    .output-meta {
      font-size: 12px;
      color: #666;
      margin-left: 16px;
    }

    code {
      background-color: #f5f5f5;
      padding: 2px 6px;
      border-radius: 3px;
      font-family: 'Courier New', monospace;
      font-size: 12px;
    }

    .test-section {
      display: grid;
      gap: 12px;
    }

    .full-width {
      width: 100%;
    }

    .test-result {
      padding: 12px;
      border-radius: 4px;
      display: flex;
      gap: 12px;
      margin-top: 12px;
      align-items: flex-start;
    }

    .test-result.matched {
      background-color: #e8f5e9;
      border: 1px solid #4caf50;
    }

    .test-result.not-matched {
      background-color: #ffebee;
      border: 1px solid #f44336;
    }

    .test-result mat-icon {
      color: inherit;
    }

    .test-result.matched mat-icon {
      color: #2e7d32;
    }

    .test-result.not-matched mat-icon {
      color: #c62828;
    }

    .test-result strong {
      color: currentColor;
    }

    .test-result p {
      margin: 4px 0 0 0;
      font-size: 12px;
    }
  `]
})
export class RulesComponent implements OnInit {
  rules: Rule[] = [];
  filteredRules: Rule[] = [];
  searchText = '';
  expandedRuleIndex = -1;
  testPayloads: Record<string, string> = {};
  testKeys: Record<string, string> = {};
  testHeaders: Record<string, string> = {};
  testResults: Record<string, any> = {};

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit() {
    this.loadRules();
  }

  loadRules() {
    this.api.getRules().subscribe({
      next: (response) => {
        this.rules = response.rules;
        this.filteredRules = [...this.rules];
        // Sort by priority
        this.filteredRules.sort((a, b) => a.priority - b.priority);
      },
      error: (err) => {
        this.snackBar.open('Failed to load rules', 'Close', { duration: 5000 });
        console.error('Error loading rules:', err);
      }
    });
  }

  filterRules() {
    if (!this.searchText.trim()) {
      this.filteredRules = [...this.rules];
    } else {
      const searchLower = this.searchText.toLowerCase();
      this.filteredRules = this.rules.filter(rule =>
        rule.name.toLowerCase().includes(searchLower) ||
        rule.input_destination.toLowerCase().includes(searchLower) ||
        rule.outputs.some(out => out.destination.toLowerCase().includes(searchLower))
      );
    }
    this.expandedRuleIndex = -1;
  }

   testRule(rule: Rule) {
     const payloadStr = this.testPayloads[rule.name]?.trim();
     const keyStr = this.testKeys[rule.name]?.trim();
     const headersStr = this.testHeaders[rule.name]?.trim();

     if (!payloadStr) {
       this.snackBar.open('Please enter a test payload', 'Close', { duration: 3000 });
       return;
     }

     try {
       const payload = JSON.parse(payloadStr);

       // Parse optional key and headers
       let key: any = undefined;
       let headers: any = undefined;

       if (keyStr) {
         key = keyStr;
       }

       if (headersStr) {
         try {
           headers = JSON.parse(headersStr);
         } catch (e) {
           this.snackBar.open('Invalid JSON in headers field', 'Close', { duration: 3000 });
           return;
         }
       }

       // Create test message with key and headers
       const testMessage: any = {
         payload,
         key,
         headers
       };

       // Filter out undefined values
       if (!key) delete testMessage.key;
       if (!headers) delete testMessage.headers;

       this.api.testRuleMatching(rule.input_destination, testMessage, rule.name).subscribe({
         next: (result) => {
           this.testResults[rule.name] = result;
           if (!result.matched) {
             this.snackBar.open('Rule did not match test message', 'Close', { duration: 3000 });
           } else {
             this.snackBar.open('Rule matched! ✓', 'Close', { duration: 3000 });
           }
         },
         error: (err) => {
           this.snackBar.open('Error testing rule: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
         }
       });
     } catch (e) {
       this.snackBar.open('Invalid JSON payload', 'Close', { duration: 3000 });
     }
   }

  Object = Object;
}


