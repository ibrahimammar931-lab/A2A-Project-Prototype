import { ComponentFixture, TestBed } from '@angular/core/testing';

import { WorkflowLauncher } from './workflow-launcher';

describe('WorkflowLauncher', () => {
  let component: WorkflowLauncher;
  let fixture: ComponentFixture<WorkflowLauncher>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [WorkflowLauncher],
    }).compileComponents();

    fixture = TestBed.createComponent(WorkflowLauncher);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
