import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import {
  Test,
  Send,
  Rule,
  Message,
  HealthStatus,
  BulkTestExecutionRequest,
  BulkSendExecutionRequest,
  BulkTestExecutionResult,
  BulkSendExecutionResult,
  InjectMessageRequest,
  InjectMessageResponse,
  ListsResponse
} from '../models';

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private apiUrl = '/api';

  constructor(private http: HttpClient) {}

  private handleError(error: HttpErrorResponse) {
    let errorMessage = 'An error occurred';
    // Check if ErrorEvent exists (it may not in SSR/Node.js environments)
    if (typeof ErrorEvent !== 'undefined' && error.error instanceof ErrorEvent) {
      errorMessage = `Error: ${error.error.message}`;
    } else {
      errorMessage = `Error Code: ${error.status}\nMessage: ${error.message}`;
    }
    console.error(errorMessage);
    return throwError(() => new Error(errorMessage));
  }

  /**
   * Health check endpoint
   */
  getHealth(): Observable<HealthStatus> {
    return this.http.get<HealthStatus>(`${this.apiUrl}/health`)
      .pipe(catchError(this.handleError));
  }

  /**
   * List all tests
   */
  getTests(): Observable<{ total: number; tests: Test[] }> {
    return this.http.get<{ total: number; tests: Test[] }>(`${this.apiUrl}/tests`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Run tests in bulk with repeat and parallelism options
   */
  runTestsBulk(request: BulkTestExecutionRequest): Observable<BulkTestExecutionResult> {
    return this.http.post<BulkTestExecutionResult>(`${this.apiUrl}/tests:bulk`, request)
      .pipe(catchError(this.handleError));
  }

  /**
   * List all sends
   */
  getSends(): Observable<{ total: number; sends: Send[] }> {
    return this.http.get<{ total: number; sends: Send[] }>(`${this.apiUrl}/send`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Run sends in bulk with repeat option
   */
  runSendsBulk(request: BulkSendExecutionRequest): Observable<BulkSendExecutionResult> {
    return this.http.post<BulkSendExecutionResult>(`${this.apiUrl}/send:bulk`, request)
      .pipe(catchError(this.handleError));
  }

  /**
   * Get all rules
   */
  getRules(): Observable<{ rules: Rule[] }> {
    return this.http.get<{ rules: Rule[] }>(`${this.apiUrl}/rules`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Get rules for a specific topic
   */
  getRulesByTopic(topic: string): Observable<{ rules: Rule[] }> {
    return this.http.get<{ rules: Rule[] }>(`${this.apiUrl}/rules/${topic}`)
      .pipe(catchError(this.handleError));
  }

   /**
    * Test rule matching for a message with optional key and headers
    */
   testRuleMatching(topic: string, message: any, ruleName?: string): Observable<any> {
     const url = ruleName
       ? `${this.apiUrl}/rules:match?topic=${topic}&rule_name=${ruleName}`
       : `${this.apiUrl}/rules:match?topic=${topic}`;

     // Message can be { payload, key?, headers? } or just the payload
     const body = message.payload !== undefined
       ? message
       : { payload: message };

     return this.http.post<any>(url, body)
       .pipe(catchError(this.handleError));
   }

  /**
   * Inject a message to a topic
   */
  injectMessage(topic: string, request: InjectMessageRequest): Observable<InjectMessageResponse> {
    return this.http.post<InjectMessageResponse>(`${this.apiUrl}/inject/${topic}`, request)
      .pipe(catchError(this.handleError));
  }

  /**
   * Get messages from a topic
   */
  getMessages(topic: string, limit: number = 10, timeoutMs: number = 500): Observable<Message[]> {
    return this.http.get<Message[]>(`${this.apiUrl}/messages/${topic}?limit=${limit}&timeout_ms=${timeoutMs}`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Get test execution logs
   */
  getTestLogs(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/tests/logs`)
      .pipe(catchError(this.handleError));
  }

   /**
    * Get test log for specific test
    */
   getTestLog(testId: string): Observable<any> {
     return this.http.get<any>(`${this.apiUrl}/tests/logs/${testId}`)
       .pipe(catchError(this.handleError));
   }

  /**
   * Debug: Decode a message payload
   */
  decodeMessage(topic: string, payload: string): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/debug/decode`, { topic, payload })
      .pipe(catchError(this.handleError));
  }

  /**
   * Debug: Test rule matching (detailed analysis)
   */
  debugRuleMatching(topic: string, payload: any, ruleName?: string): Observable<any> {
    const url = ruleName
      ? `${this.apiUrl}/debug/match?topic=${topic}&rule_name=${ruleName}`
      : `${this.apiUrl}/debug/match?topic=${topic}`;
    return this.http.post<any>(url, payload)
      .pipe(catchError(this.handleError));
  }

  /**
   * Debug: Get all discovered topics
   */
  getTopics(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/debug/topics`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Debug: Get message cache statistics
   */
  getCacheStats(): Observable<any> {
    return this.http.get<any>(`${this.apiUrl}/debug/cache`)
      .pipe(catchError(this.handleError));
  }

  /**
   * Debug: Render template with context
   */
  renderTemplate(template: string, context: Record<string, any>): Observable<any> {
    return this.http.post<any>(`${this.apiUrl}/debug/template/render`, { template, context })
      .pipe(catchError(this.handleError));
  }

  /**
   * Get custom placeholders
   */
  getCustomPlaceholders(): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/custom-placeholders`)
      .pipe(catchError(this.handleError));
  }
}
