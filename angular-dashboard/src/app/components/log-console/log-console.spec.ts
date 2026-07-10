import { ComponentFixture, TestBed } from '@angular/core/testing';

import { LogConsole } from './log-console';

describe('LogConsole', () => {
  let component: LogConsole;
  let fixture: ComponentFixture<LogConsole>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LogConsole],
    }).compileComponents();

    fixture = TestBed.createComponent(LogConsole);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
