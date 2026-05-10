import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder } from '@angular/forms';
import { MatCardModule } from '@angular/material/card';
import { MatTabsModule } from '@angular/material/tabs';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatTooltipModule } from '@angular/material/tooltip';
import { ApiService } from '../../core/services/api.service';
import { Message, InjectMessageRequest } from '../../core/models';

@Component({
  selector: 'app-messages',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatCardModule,
    MatTabsModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule,
    MatExpansionModule,
    MatSnackBarModule,
    MatSelectModule,
    MatTooltipModule
  ],
  template: `
    <div class="container">
      <mat-card>
        <mat-card-header>
          <mat-card-title>Message Inspector & Injector</mat-card-title>
          <mat-card-subtitle>Inject and consume messages from Kafka topics</mat-card-subtitle>
        </mat-card-header>
        <mat-card-content>
          <mat-tab-group>
            <!-- Inject Tab -->
            <mat-tab label="Inject Message">
              <div class="tab-content">
                <div class="inject-form">
                  <div class="form-section">
                    <h3>Inject a New Message</h3>

                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Target Topic</mat-label>
                      <input matInput [(ngModel)]="injectTopic" placeholder="e.g., orders.input">
                      <mat-icon matSuffix>topic</mat-icon>
                    </mat-form-field>

                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Message Payload (JSON)</mat-label>
                      <textarea matInput [(ngModel)]="injectPayload" rows="8"
                                placeholder="{&#10;  &quot;field&quot;: &quot;value&quot;&#10;}"></textarea>
                    </mat-form-field>

                    <div class="button-group">
                      <button mat-raised-button color="primary" (click)="injectMessage()" [disabled]="isInjecting">
                        <mat-icon>send</mat-icon>
                        Inject Message
                      </button>
                      <button mat-stroked-button (click)="clearInjectForm()">
                        <mat-icon>clear</mat-icon>
                        Clear
                      </button>
                    </div>

                    <mat-progress-bar *ngIf="isInjecting" mode="indeterminate"></mat-progress-bar>

                    <!-- Injection Result -->
                    <mat-expansion-panel *ngIf="injectResult" [expanded]="true" class="result-panel">
                      <mat-expansion-panel-header>
                        <mat-panel-title>
                          <mat-icon [ngClass]="injectResult.status === 'success' ? 'success' : 'error'">
                            {{ injectResult.status === 'success' ? 'check_circle' : 'error' }}
                          </mat-icon>
                          Message Injected
                        </mat-panel-title>
                      </mat-expansion-panel-header>
                      <div class="result-details">
                        <p><strong>Message ID:</strong> {{ injectResult.message_id }}</p>
                        <p><strong>Topic:</strong> {{ injectResult.topic }}</p>
                        <p><strong>Status:</strong> {{ injectResult.status }}</p>
                      </div>
                    </mat-expansion-panel>
                  </div>
                </div>
              </div>
            </mat-tab>

            <!-- Consume Tab -->
            <mat-tab label="Consume Messages">
              <div class="tab-content">
                <div class="consume-form">
                  <div class="form-section">
                    <h3>Read Messages from Topic</h3>

                    <mat-form-field appearance="outline" class="full-width">
                      <mat-label>Topic Name</mat-label>
                      <input matInput [(ngModel)]="consumeTopic" placeholder="e.g., payments.output">
                      <mat-icon matSuffix>topic</mat-icon>
                    </mat-form-field>

                    <div class="control-group">
                      <mat-form-field appearance="outline">
                        <mat-label>Message Limit</mat-label>
                        <input matInput type="number" [(ngModel)]="consumeLimit" min="1" max="100">
                      </mat-form-field>

                      <mat-form-field appearance="outline">
                        <mat-label>Timeout (ms)</mat-label>
                        <input matInput type="number" [(ngModel)]="consumeTimeout" min="100" max="5000" step="100">
                      </mat-form-field>
                    </div>

                    <div class="button-group">
                      <button mat-raised-button color="primary" (click)="consumeMessages()" [disabled]="isConsuming">
                        <mat-icon>cloud_download</mat-icon>
                        Read Messages
                      </button>
                      <button mat-stroked-button (click)="clearConsume()">
                        <mat-icon>clear</mat-icon>
                        Clear
                      </button>
                    </div>

                    <mat-progress-bar *ngIf="isConsuming" mode="indeterminate"></mat-progress-bar>

                    <!-- Messages Table -->
                    <div *ngIf="consumedMessages.length > 0" class="messages-section">
                      <h4>Messages ({{ consumedMessages.length }})</h4>
                      <div class="table-container">
                        <table mat-table [dataSource]="consumedMessages" class="messages-table">
                          <!-- Offset column -->
                          <ng-container matColumnDef="offset">
                            <th mat-header-cell *matHeaderCellDef>Offset</th>
                            <td mat-cell *matCellDef="let element">{{ element.offset }}</td>
                          </ng-container>

                          <!-- Timestamp column -->
                          <ng-container matColumnDef="timestamp">
                            <th mat-header-cell *matHeaderCellDef>Timestamp</th>
                            <td mat-cell *matCellDef="let element">
                              {{ element.timestamp | date:'short' }}
                            </td>
                          </ng-container>

                          <!-- Key column -->
                          <ng-container matColumnDef="key">
                            <th mat-header-cell *matHeaderCellDef>Key</th>
                            <td mat-cell *matCellDef="let element">
                              <code *ngIf="element.key">{{ element.key }}</code>
                              <span *ngIf="!element.key" class="empty">null</span>
                            </td>
                          </ng-container>

                          <!-- Value column -->
                          <ng-container matColumnDef="value">
                            <th mat-header-cell *matHeaderCellDef>Value</th>
                            <td mat-cell *matCellDef="let element">
                              <pre class="value-preview">{{ element.value | json }}</pre>
                            </td>
                          </ng-container>

                          <!-- Actions column -->
                          <ng-container matColumnDef="actions">
                            <th mat-header-cell *matHeaderCellDef>Actions</th>
                            <td mat-cell *matCellDef="let element">
                              <button mat-icon-button matTooltip="Copy"
                                      (click)="copyToClipboard(JSON.stringify(element.value, null, 2))">
                                <mat-icon>content_copy</mat-icon>
                              </button>
                            </td>
                          </ng-container>

                          <tr mat-header-row *matHeaderRowDef="messageColumns"></tr>
                          <tr mat-row *matRowDef="let row; columns: messageColumns;"></tr>
                        </table>
                      </div>
                    </div>

                    <div *ngIf="!isConsuming && consumeAttempted && consumedMessages.length === 0" class="empty-state">
                      <mat-icon>inbox</mat-icon>
                      <p>No messages found in topic</p>
                    </div>
                  </div>
                </div>
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

    .form-section {
      margin-bottom: 24px;
    }

    .form-section h3 {
      margin: 0 0 16px 0;
      color: #333;
    }

    .full-width {
      width: 100%;
      margin-bottom: 16px;
    }

    .control-group {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 16px;
      margin-bottom: 16px;
    }

    .button-group {
      display: flex;
      gap: 8px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }

    .result-panel {
      margin-top: 16px;
    }

    .result-details {
      padding: 12px 0;
    }

    .result-details p {
      margin: 8px 0;
      font-size: 14px;
    }

    .result-details code {
      background-color: #f5f5f5;
      padding: 2px 6px;
      border-radius: 3px;
      font-family: 'Courier New', monospace;
    }

    .messages-section {
      margin-top: 24px;
      padding-top: 24px;
      border-top: 1px solid #eee;
    }

    .messages-section h4 {
      margin: 0 0 16px 0;
      color: #333;
    }

    .table-container {
      overflow-x: auto;
    }

    .messages-table {
      width: 100%;
      border-collapse: collapse;
    }

    .value-preview {
      overflow: auto;
      font-size: 11px;
      padding: 8px;
      background-color: #f5f5f5;
      border-radius: 3px;
      margin: 0;
      max-height: 100px;
    }

    code {
      font-family: 'Courier New', monospace;
      font-size: 12px;
      background-color: #f5f5f5;
      padding: 2px 6px;
      border-radius: 3px;
    }

    .empty {
      color: #999;
      font-style: italic;
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

    mat-expansion-panel {
      margin-bottom: 12px;
    }

    .success {
      color: #2e7d32;
    }

    .error {
      color: #c62828;
    }
  `]
})
export class MessagesComponent implements OnInit {
  // Make JSON available in template
  JSON = JSON;

  // Inject form
  injectTopic = '';
  injectPayload = '';
  isInjecting = false;
  injectResult: any = null;

  // Consume form
  consumeTopic = '';
  consumeLimit = 10;
  consumeTimeout = 500;
  isConsuming = false;
  consumedMessages: Message[] = [];
  consumeAttempted = false;

  messageColumns: string[] = ['offset', 'timestamp', 'key', 'value', 'actions'];

  constructor(
    private api: ApiService,
    private snackBar: MatSnackBar,
    private fb: FormBuilder
  ) {}

  ngOnInit() {}

  injectMessage() {
    if (!this.injectTopic.trim()) {
      this.snackBar.open('Please specify a topic', 'Close', { duration: 3000 });
      return;
    }

    try {
      const payload = JSON.parse(this.injectPayload);
      this.isInjecting = true;
      const request: InjectMessageRequest = { message: payload };

      this.api.injectMessage(this.injectTopic, request).subscribe({
        next: (result) => {
          this.injectResult = result;
          this.isInjecting = false;
          this.snackBar.open('Message injected successfully!', 'Close', { duration: 3000 });
        },
        error: (err) => {
          this.isInjecting = false;
          this.snackBar.open('Failed to inject message: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
        }
      });
    } catch (e) {
      this.snackBar.open('Invalid JSON payload', 'Close', { duration: 3000 });
    }
  }

  clearInjectForm() {
    this.injectTopic = '';
    this.injectPayload = '';
    this.injectResult = null;
  }

  consumeMessages() {
    if (!this.consumeTopic.trim()) {
      this.snackBar.open('Please specify a topic', 'Close', { duration: 3000 });
      return;
    }

    this.isConsuming = true;
    this.consumeAttempted = true;

    this.api.getMessages(this.consumeTopic, this.consumeLimit, this.consumeTimeout).subscribe({
      next: (messages) => {
        this.consumedMessages = messages;
        this.isConsuming = false;
        if (messages.length === 0) {
          this.snackBar.open('No messages found', 'Close', { duration: 3000 });
        }
      },
      error: (err) => {
        this.isConsuming = false;
        this.snackBar.open('Failed to consume messages: ' + (err.message || 'Unknown error'), 'Close', { duration: 5000 });
      }
    });
  }

  clearConsume() {
    this.consumeTopic = '';
    this.consumedMessages = [];
    this.consumeAttempted = false;
  }

  copyToClipboard(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      this.snackBar.open('Copied to clipboard!', 'Close', { duration: 2000 });
    });
  }
}


