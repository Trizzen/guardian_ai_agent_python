import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { AppComponent } from './app';
import { SentinelApiService } from './sentinel-api.service';
import { SentinelSnapshot } from './models';

const snapshot: SentinelSnapshot = {
  dashboard: {
    identity: {
      name: 'Jaza Soulminder',
      role: 'Sentinel',
      message: 'Jaza manages the bigger picture.',
    },
    metrics: {
      needs_my_attention: 2,
      active_work: 1,
      ready: 1,
      waiting: 0,
      completed_today: 0,
      prepared_for_star: 1,
    },
    needs_attention: [],
    attention_projects: [],
    attention_check_ins: [],
    upcoming: [],
    recent_notes: [],
    recent_check_ins: [],
  },
  petPresence: {
    available: true,
    selected_pet: 'jaza',
    selected_avatar_id: 'custom:jaza-soulminder',
    display_name: 'Jaza Soulminder',
    message: null,
  },
  programs: [
    {
      id: 'daily-command',
      name: 'Daily Command',
      short_name: 'Daily Command',
      description: 'Daily priorities and focused check-ins.',
      capabilities: ['priorities'],
      accent: 'violet',
    },
  ],
  projects: [],
  workItems: [],
  reporting: {
    guard_this_kingdom: { connected: true, message: null },
    luna: { ready: true, provider: 'openai', model: 'gpt-5.6-luna', message: null },
    target_user_scope: 1002,
    windows: ['today', 'week', 'month', 'ytd', 'all'],
    domains: [{ id: 'daily-command', label: 'Daily Command' }],
    source_policy: 'GTK is read-only evidence.',
  },
};

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        {
          provide: SentinelApiService,
          useValue: {
            snapshot$: of(snapshot),
            selectPet: () => of(snapshot.petPresence),
            getDomainReport: () =>
              of({
                available: true,
                domain: 'daily-command',
                domain_label: 'Daily Command',
                window: 'week',
                window_label: 'This Week',
                source: { guard_this_kingdom: true, mode: 'read_only', target_user_id: 1002 },
                stats: {
                  scheduled_goals: 2,
                  completed_goals: 1,
                  failed_goals: 1,
                  live_goals: 0,
                  completion_rate: 50,
                  failure_rate: 50,
                  recorded_minutes: 20,
                  completed_minutes: 10,
                  average_completed_minutes: 10,
                  goal_type_minutes: { Spirit: 10 },
                  behavior_distribution: { standard: 2, sliding: 0 },
                  garden_records: 0,
                  garden_events: 0,
                },
                activity: [],
                overdue_activity: [],
                attention_signals: [],
                planning_context: { source: 'jaza_local_json', source_role: 'planning_state_not_gtk_evidence' },
                classification: { classified_count: 2, unclassified_count: 0, ambiguous_for_luna: [] },
                provenance: { record_count: 2, generated_at: '2026-08-09T12:00:00Z', report_version: 'jaza-report-v1' },
                insight: null,
              }),
          },
        },
      ],
    }).compileComponents();
  });

  it('renders the Sentinel identity and attention contract', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();

    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Jaza Soulminder');
    expect(text).toContain('Jaza manages the bigger picture.');
    expect(text).toContain('Needs My Attention');
    expect(text).toContain('Daily Command');
    expect(text).toContain('Jaza Active');
    expect(text).toContain('Hand to Star');
    expect(text).toContain('GTK Data Connected');
    expect(text).toContain('Luna Ready');
    expect(text).toContain('Daily Command Intelligence');
    expect(text).toContain('Generate Jaza Insight');
    expect(text).toContain('No autonomous execution');
  });
});
