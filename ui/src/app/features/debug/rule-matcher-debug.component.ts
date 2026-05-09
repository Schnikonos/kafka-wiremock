import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSelectModule } from '@angular/material/select';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-rule-matcher-debug',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatButtonModule,
    MatIconModule,
    MatExpansionModule,
    MatSelectModule,
    MatProgressBarModule,
    MatSnackBarModule,
    MatTabsModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Rule Matching Debugger</mat-card-title>
          <mat-card-subtitle>Debug which rules match a message and see why - tests message against ALL rules in priority order</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <!-- Information Section -->
          <div class="info-section">
            <mat-icon class="info-icon">info</mat-icon>
            <div class="info-text">
              <strong>Purpose:</strong> Test a message (with optional key and headers) against all configured rules to see:
              <ul>
                <li>Which rule matches first (in priority order)</li>
                <li>Why rules matched or failed (per condition analysis)</li>
                <li>What output messages would be produced</li>
                <li>Context variables extracted for template rendering</li>
              </ul>
              <strong>Note:</strong> Rule name filtering is optional - leave empty to test against all rules
            </div>
          </div>

          <!-- Input Section -->
          <div class="input-section">
            <h3>Test Configuration</h3>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Topic</mat-label>
              <input matInput [(ngModel)]="topic" placeholder="e.g., orders.input">
              <mat-icon matSuffix>topic</mat-icon>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Message Key (optional)</mat-label>
              <input matInput [(ngModel)]="messageKey" placeholder="e.g., order-123">
              <mat-hint>Message key for key-based condition matching</mat-hint>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Message Headers (JSON, optional)</mat-label>
              <textarea matInput [(ngModel)]="messageHeaders" rows="2"
                        placeholder='{"header-name": "value"}'></textarea>
              <mat-hint>Headers for header-based condition matching</mat-hint>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Payload (JSON)</mat-label>
              <textarea matInput [(ngModel)]="payload" rows="6"
                        placeholder="{&#10;  &quot;eventType&quot;: &quot;ORDER_CREATED&quot;&#10;}"></textarea>
            </mat-form-field>

            <mat-form-field appearance="outline" class="full-width">
              <mat-label>Rule Name (Optional)</mat-label>
              <input matInput [(ngModel)]="ruleName" placeholder="Leave empty to test all rules">
              <mat-hint>Filter results to a specific rule</mat-hint>
            </mat-form-field>

            <div class="button-group">
              <button mat-raised-button color="primary" (click)="analyzeRules()" [disabled]="isAnalyzing">
                <mat-icon>bug_report</mat-icon>
                Analyze Matching
              </button>
              <button mat-stroked-button (click)="clearForm()">
                <mat-icon>clear</mat-icon>
                Clear
              </button>
            </div>

            <mat-progress-bar *ngIf="isAnalyzing" mode="indeterminate"></mat-progress-bar>
          </div>

          <!-- Results Section -->
          <mat-tab-group *ngIf="analysisResult" class="results-section">
            <!-- First Match Tab -->
            <mat-tab label="First Match">
              <ng-container *ngIf="analysisResult.first_match as match">
                <div class="match-result" [ngClass]="match.matched ? 'matched' : 'not-matched'">
                  <div class="result-header">
                    <mat-icon>{{ match.matched ? 'check_circle' : 'cancel' }}</mat-icon>
                    <span class="result-status">{{ match.matched ? 'MATCHED' : 'NO MATCH' }}</span>
                  </div>

                  <div *ngIf="match.matched" class="matched-info">
                    <h4>{{ match.rule_name }} (Priority #{{ match.rule_priority }})</h4>

                    <!-- Matched Conditions -->
                    <div *ngIf="match.conditions && match.conditions.length > 0" class="conditions-section">
                      <h5>Matched Conditions ({{ match.conditions.length }})</h5>
                      <div class="conditions-list">
                        <div *ngFor="let cond of match.conditions" class="condition-item matched-condition">
                          <mat-icon>check</mat-icon>
                          <div class="condition-detail">
                            <span class="condition-type">[{{ cond.type }}]</span>
                            <span *ngIf="cond.expression">{{ cond.expression }}</span>
                            <span *ngIf="cond.value" class="condition-value">= "{{ cond.value }}"</span>
                            <span *ngIf="cond.regex" class="condition-regex">matches /{{ cond.regex }}/</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- Extracted Context -->
                    <div *ngIf="match.context" class="context-section">
                      <h5>Extracted Context</h5>
                      <pre class="context-display">{{ match.context | json }}</pre>
                    </div>

                    <!-- Outputs -->
                    <div *ngIf="match.outputs && match.outputs.length > 0" class="outputs-section">
                      <h5>Generated Outputs ({{ match.outputs_count }})</h5>
                      <div class="outputs-list">
                        <div *ngFor="let output of match.outputs; let i = index" class="output-item">
                          <div class="output-header">
                            <span class="output-number">Output {{ i + 1 }}</span>
                            <span class="output-topic">📤 {{ output.topic }}</span>
                          </div>
                          <div *ngIf="output.delay_ms" class="output-meta">
                            Delay: {{ output.delay_ms }}ms
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div *ngIf="!match.matched" class="no-match-info">
                    <p>No rules matched this message for topic <code>{{ topic }}</code></p>
                  </div>
                </div>
              </ng-container>
            </mat-tab>

            <!-- All Rules Tab -->
            <mat-tab label="All Rules Analysis" *ngIf="analysisResult.all_rules">
              <div class="all-rules-section">
                <div *ngIf="analysisResult.all_rules.length === 0" class="empty-state">
                  <mat-icon>inbox</mat-icon>
                  <p>No rules found for this topic</p>
                </div>

                <div *ngFor="let rule of analysisResult.all_rules; let i = index" class="rule-analysis">
                  <div class="rule-header" [ngClass]="rule.matched ? 'matched' : 'not-matched'">
                    <mat-icon>{{ rule.matched ? 'check_circle' : 'cancel' }}</mat-icon>
                    <span class="rule-name">{{ rule.rule_name }}</span>
                    <span class="rule-priority">#{{ rule.rule_priority }}</span>
                    <span *ngIf="rule.matched" class="rule-status matched-tag">MATCHED</span>
                    <span *ngIf="!rule.matched" class="rule-status not-matched-tag">NO MATCH</span>
                  </div>

                  <mat-expansion-panel *ngIf="rule.conditions && rule.conditions.length > 0" class="conditions-panel">
                    <mat-expansion-panel-header>
                      <mat-panel-title>Conditions ({{ rule.matched_conditions }}/{{ rule.conditions.length }})</mat-panel-title>
                    </mat-expansion-panel-header>

                    <div class="conditions-detail">
                      <div *ngFor="let cond of rule.conditions"
                           class="condition-item"
                           [ngClass]="cond.matched ? 'matched-condition' : 'unmatched-condition'">
                        <mat-icon>{{ cond.matched ? 'check' : 'close' }}</mat-icon>
                        <div class="condition-detail">
                          <span class="condition-type">[{{ cond.type }}]</span>
                          <span *ngIf="cond.expression">{{ cond.expression }}</span>
                          <span *ngIf="cond.value" class="condition-value">= "{{ cond.value }}"</span>
                          <span *ngIf="cond.regex" class="condition-regex">matches /{{ cond.regex }}/</span>
                          <span *ngIf="cond.actual_value" class="actual-value">
                            (actual: {{ cond.actual_value }})
                          </span>
                        </div>
                      </div>
                    </div>
                  </mat-expansion-panel>
                </div>
              </div>
            </mat-tab>

            <!-- Message Analysis Tab -->
            <mat-tab label="Message Analysis">
              <div class="message-section">
                <h4>Topic</h4>
                <pre class="code-display">{{ topic }}</pre>

                <h4>Payload</h4>
                <pre class="code-display">{{ payload }}</pre>

                <h4>Total Rules for Topic</h4>
                <p>{{ analysisResult.total_rules }} rule(s)</p>
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

     .info-section {
       display: flex;
       gap: 16px;
       padding: 16px;
       background-color: #e3f2fd;
       border: 1px solid #90caf9;
       border-radius: 4px;
       margin-bottom: 24px;
     }

     .info-icon {
       color: #1976d2;
       flex-shrink: 0;
       margin-top: 2px;
     }

     .info-text {
       color: #1976d2;
       font-size: 14px;
       line-height: 1.6;
     }

     .info-text strong {
       font-weight: 500;
     }

     .info-text ul {
       margin: 8px 0 0 16px;
       padding: 0;
     }

     .info-text li {
       margin: 4px 0;
     }

     .input-section {
       margin-bottom: 32px;
       padding-bottom: 24px;
       border-bottom: 1px solid #eee;
     }

    .input-section h3 {
      margin: 0 0 16px 0;
      color: #333;
    }

    .full-width {
      width: 100%;
      margin-bottom: 16px;
    }

    .button-group {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
    }

    .results-section {
      margin-top: 24px;
    }

    .match-result {
      padding: 16px;
      border-radius: 4px;
      border-left: 4px solid;
    }

    .match-result.matched {
      background-color: #e8f5e9;
      border-left-color: #4caf50;
    }

    .match-result.not-matched {
      background-color: #ffebee;
      border-left-color: #f44336;
    }

    .result-header {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 16px;
    }

    .result-header mat-icon {
      font-size: 32px;
      width: 32px;
      height: 32px;
    }

    .match-result.matched .result-header mat-icon {
      color: #2e7d32;
    }

    .match-result.not-matched .result-header mat-icon {
      color: #c62828;
    }

    .result-status {
      font-size: 18px;
      font-weight: 500;
    }

    .matched-info h4 {
      margin: 0 0 12px 0;
      color: #1976d2;
      font-size: 16px;
    }

    .no-match-info {
      padding: 12px 0;
    }

    .no-match-info p {
      margin: 0;
      color: #666;
    }

    .conditions-section,
    .context-section,
    .outputs-section {
      margin-bottom: 16px;
      padding-bottom: 16px;
      border-bottom: 1px solid rgba(0,0,0,0.1);
    }

    .conditions-section:last-child,
    .context-section:last-child,
    .outputs-section:last-child {
      border-bottom: none;
    }

    h5 {
      margin: 0 0 12px 0;
      color: #333;
      font-size: 14px;
      font-weight: 500;
    }

    .conditions-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .condition-item {
      display: flex;
      gap: 12px;
      padding: 8px;
      border-radius: 3px;
      align-items: flex-start;
    }

    .matched-condition {
      background-color: rgba(76, 175, 80, 0.1);
    }

    .unmatched-condition {
      background-color: rgba(244, 67, 54, 0.1);
    }

    .condition-item mat-icon {
      margin-top: 2px;
    }

    .matched-condition mat-icon {
      color: #2e7d32;
    }

    .unmatched-condition mat-icon {
      color: #c62828;
    }

    .condition-detail {
      flex: 1;
      font-family: 'Courier New', monospace;
      font-size: 12px;
      color: #333;
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
      align-items: center;
    }

    .condition-type {
      display: inline-block;
      background-color: #e3f2fd;
      color: #1976d2;
      padding: 2px 6px;
      border-radius: 3px;
      font-weight: 500;
    }

    .condition-value,
    .condition-regex {
      color: #d32f2f;
    }

    .actual-value {
      color: #666;
      font-style: italic;
      background-color: #f5f5f5;
      padding: 2px 4px;
      border-radius: 2px;
    }

    code {
      background-color: #f5f5f5;
      padding: 2px 6px;
      border-radius: 3px;
      font-family: 'Courier New', monospace;
      font-size: 12px;
    }

    .context-display,
    .code-display {
      background-color: #f5f5f5;
      padding: 12px;
      border-radius: 4px;
      border: 1px solid #eee;
      overflow-x: auto;
      font-family: 'Courier New', monospace;
      font-size: 11px;
      margin: 8px 0;
    }

    .outputs-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .output-item {
      padding: 8px;
      background-color: #f0f8f0;
      border-left: 3px solid #4caf50;
      border-radius: 3px;
    }

    .output-header {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-bottom: 4px;
    }

    .output-number {
      font-size: 12px;
      color: #666;
      font-weight: 500;
    }

    .output-topic {
      font-family: 'Courier New', monospace;
      font-weight: 500;
      color: #2e7d32;
    }

    .output-meta {
      font-size: 12px;
      color: #666;
      margin-left: 16px;
    }

    .all-rules-section {
      padding: 16px 0;
    }

    .rule-analysis {
      margin-bottom: 16px;
    }

    .rule-header {
      display: flex;
      gap: 12px;
      padding: 12px;
      border-radius: 4px;
      align-items: center;
      background-color: #f9f9f9;
      border: 1px solid #eee;
    }

    .rule-header.matched {
      background-color: #e8f5e9;
      border-color: #4caf50;
    }

    .rule-header.not-matched {
      background-color: #ffebee;
      border-color: #f44336;
    }

    .rule-header mat-icon {
      font-size: 20px;
      width: 20px;
      height: 20px;
    }

    .rule-header.matched mat-icon {
      color: #2e7d32;
    }

    .rule-header.not-matched mat-icon {
      color: #c62828;
    }

    .rule-name {
      font-weight: 500;
      flex: 1;
      color: #1976d2;
    }

    .rule-priority {
      font-size: 12px;
      background-color: #fff3e0;
      color: #e65100;
      padding: 2px 8px;
      border-radius: 3px;
      font-weight: 500;
    }

    .rule-status {
      font-size: 11px;
      padding: 4px 8px;
      border-radius: 3px;
      font-weight: 500;
    }

    .matched-tag {
      background-color: #c8e6c9;
      color: #1b5e20;
    }

    .not-matched-tag {
      background-color: #ffcdd2;
      color: #b71c1c;
    }

    .conditions-panel {
      margin-top: 8px;
    }

    .conditions-detail {
      padding: 12px;
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

    .message-section {
      padding: 16px 0;
    }

    .message-section h4 {
      margin: 16px 0 8px 0;
      color: #333;
      font-size: 14px;
      font-weight: 500;
    }

    .message-section p {
      margin: 8px 0;
      color: #666;
    }
  `]
})
export class RuleMatcherDebugComponent implements OnInit {
  topic = '';
  payload = '';
  messageKey = '';
  messageHeaders = '';
  ruleName = '';
  isAnalyzing = false;
  analysisResult: any = null;

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar
  ) {}

  ngOnInit() {}

   analyzeRules() {
     const trimmedTopic = this.topic.trim();

     if (!trimmedTopic) {
       this.snackBar.open('Please specify a topic', 'Close', { duration: 3000 });
       return;
     }

     if (!this.payload.trim()) {
       this.snackBar.open('Please enter a payload', 'Close', { duration: 3000 });
       return;
     }

     try {
       const payloadObj = JSON.parse(this.payload);
       let headersObj: any = undefined;

       // Parse headers if provided
       if (this.messageHeaders.trim()) {
         try {
           headersObj = JSON.parse(this.messageHeaders);
         } catch (e) {
           this.snackBar.open('Invalid JSON in headers field', 'Close', { duration: 3000 });
           return;
         }
       }

       this.isAnalyzing = true;

       // Build request object
       const requestBody = {
         payload: payloadObj,
         key: this.messageKey.trim() || undefined,
         headers: headersObj
       };

       // Remove undefined fields
       if (!requestBody.key) delete requestBody.key;
       if (!requestBody.headers) delete requestBody.headers;

       // Use trimmed topic and rule name
       const trimmedRuleName = this.ruleName?.trim();
       this.api.debugRuleMatching(trimmedTopic, requestBody, trimmedRuleName || undefined).subscribe({
         next: (result) => {
           this.analysisResult = result;
           this.isAnalyzing = false;

           if (result.matched || (result.first_match && result.first_match.matched)) {
             this.snackBar.open('✓ Rule matched!', 'Close', { duration: 3000 });
           } else {
             this.snackBar.open('✗ No rule matched', 'Close', { duration: 3000 });
           }
         },
         error: (err) => {
           this.isAnalyzing = false;
           this.snackBar.open('Analysis failed: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
         }
       });
     } catch (e) {
       this.snackBar.open('Invalid JSON payload', 'Close', { duration: 3000 });
     }
   }

   clearForm() {
     this.topic = '';
     this.payload = '';
     this.messageKey = '';
     this.messageHeaders = '';
     this.ruleName = '';
     this.analysisResult = null;
   }
}

