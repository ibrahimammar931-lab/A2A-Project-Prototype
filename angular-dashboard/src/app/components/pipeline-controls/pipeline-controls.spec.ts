import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PipelineControls } from './pipeline-controls';

describe('PipelineControls', () => {
  let component: PipelineControls;
  let fixture: ComponentFixture<PipelineControls>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [PipelineControls],
    }).compileComponents();

    fixture = TestBed.createComponent(PipelineControls);
    component = fixture.componentInstance;
    await fixture.whenStable();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
