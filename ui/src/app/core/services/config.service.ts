import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject } from 'rxjs';

@Injectable({
  providedIn: 'root'
})
export class ConfigService {
  private apiUrl = '/api';

  constructor(private http: HttpClient) {}

  /**
   * Get all topic configurations
   */
  getTopics(): Observable<any> {
    return this.http.get(`${this.apiUrl}/config/topics`);
  }

  /**
   * Get specific topic configuration
   */
  getTopic(topicName: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/config/topics/${topicName}`);
  }

  /**
   * Get all JMS queue managers
   */
  getQueueManagers(): Observable<any> {
    return this.http.get(`${this.apiUrl}/config/jms-queue-managers`);
  }

  /**
   * Get specific queue manager configuration
   */
  getQueueManager(qmName: string): Observable<any> {
    return this.http.get(`${this.apiUrl}/config/jms-queue-managers/${qmName}`);
  }

  /**
   * Get available JMS providers
   */
  getAvailableProviders(): Observable<any> {
    return this.http.get(`${this.apiUrl}/jms/providers`);
  }

  // ---------------------------------------------------------------------------
  // JMS Listener control
  // ---------------------------------------------------------------------------

  /** Get overall listener engine status */
  getListenerStatus(): Observable<any> {
    return this.http.get(`${this.apiUrl}/jms/listener`);
  }

  /** Start the JMS listener engine */
  startListener(): Observable<any> {
    return this.http.post(`${this.apiUrl}/jms/listener/start`, {});
  }

  /** Stop the JMS listener engine */
  stopListener(): Observable<any> {
    return this.http.post(`${this.apiUrl}/jms/listener/stop`, {});
  }

  /** Get per-queue enabled/paused status */
  getQueueStatuses(): Observable<any> {
    return this.http.get(`${this.apiUrl}/jms/queues`);
  }

  /** Pause a specific queue */
  pauseQueue(queueName: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/jms/queues/${encodeURIComponent(queueName)}/pause`, {});
  }

  /** Resume a specific queue */
  resumeQueue(queueName: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/jms/queues/${encodeURIComponent(queueName)}/resume`, {});
  }

  // ---------------------------------------------------------------------------
  // Database connections
  // ---------------------------------------------------------------------------

  /** Get all configured databases with provider type and pool statistics */
  getDatabaseStatus(): Observable<any> {
    return this.http.get(`${this.apiUrl}/db/status`);
  }

  /** Get available DB provider drivers and whether they are installed */
  getDatabaseProviders(): Observable<any> {
    return this.http.get(`${this.apiUrl}/db/providers`);
  }
}

