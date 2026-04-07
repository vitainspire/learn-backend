from typing import List, Optional, Dict, Literal, Union
from pydantic import BaseModel, Field

class LessonMeta(BaseModel):
    lesson_title: str = Field(..., description="A clever, engaging title for the lesson")
    grade: str = Field(..., description="Target grade level")
    duration: str = Field(..., description="Total duration of the lesson, e.g., '45 mins'")

class MilestoneEvaluation(BaseModel):
    type: str = Field(..., description="Evaluation type: objective, observational, composite, etc.")
    threshold: float = Field(..., description="Success threshold as a decimal (0.0 to 1.0)")

class MilestoneActions(BaseModel):
    advance: str = Field(..., description="Action to take if milestone is reached")
    reinforce: str = Field(..., description="Action to take for moderate performance")
    reteach: str = Field(..., description="Action to take if student struggles significantly")

class Milestone(BaseModel):
    id: str = Field(..., description="Unique ID for the milestone, e.g., 'M1'")
    type: str = Field(..., description="Category: recognition, action, reasoning, integration, etc.")
    task: str = Field(..., description="The specific activity or challenge for the student")
    question: Optional[str] = Field(None, description="The verbal or written question to ask")
    expected_answer: Optional[str] = Field(None, description="The correct or desired response")
    follow_up: Optional[str] = Field(None, description="A prompt to probe deeper into student reasoning")
    evaluation: MilestoneEvaluation
    actions: MilestoneActions

class Teaching(BaseModel):
    method: str = Field(..., description="The instructional approach: demonstration, storytelling, etc.")
    examples: List[str] = Field(..., description="At least 2 clear, real-world examples")
    duration: str = Field(..., description="Time allocation for this specific concept")

class ConceptItem(BaseModel):
    name: str = Field(..., description="The specific sub-concept being taught")
    teaching: Teaching
    milestone: Milestone
    visual_description: Optional[str] = Field(None, description="Detailed prompt for generating a visual aid for this concept")

class Warmup(BaseModel):
    activity: str = Field(..., description="A quick 5-min activity to activate prior knowledge")
    duration: str = Field(..., description="Warm-up time allocation")

class Activity(BaseModel):
    activity: str = Field(..., description="A specific student-facing activity")
    duration: str = Field(..., description="Time allocation for the activity")

class ElaborateSection(BaseModel):
    we_do: str = Field(..., description="Guided practice activity (Teacher and Students together)")
    you_do: str = Field(..., description="Independent practice activity (Students alone)")
    duration: str = Field(..., description="Total time for elaboration")

class Assessment(BaseModel):
    questions: List[str] = Field(..., description="Final check-for-understanding questions")

class Closure(BaseModel):
    summary: str = Field(..., description="Key takeaways from the lesson")
    next_topic: str = Field(..., description="Bridge to the next logical concept in the sequence")

class StyleSpecificAssets(BaseModel):
    # Authority Style
    lecture_script: Optional[str] = Field(None, description="Detailed script for a teacher-led lecture")
    
    # Demonstrator Style
    watch_for_list: Optional[List[str]] = Field(None, description="Specific things students should watch for during a demonstration")
    demonstration_steps: Optional[List[str]] = Field(None, description="Step-by-step instructions for the teacher's demonstration")
    
    # Facilitator Style
    inquiry_lab_details: Optional[str] = Field(None, description="Details for a student-led discovery or 'Inquiry Lab' activity")
    discussion_prompts: Optional[List[str]] = Field(None, description="Open-ended questions to facilitate group discovery")
    
    # Delegator Style
    team_assignments: Optional[List[str]] = Field(None, description="Instructions for peer-to-peer or group team formation")
    role_cards: Optional[List[str]] = Field(None, description="Specific roles for students within a group (e.g., Researcher, Timer, Presenter)")
    peer_review_rubric: Optional[str] = Field(None, description="A simple rubric for students to evaluate each other's work")

class LessonPlan(BaseModel):
    meta: LessonMeta
    objective: List[str] = Field(..., description="List of learning objectives")
    resources: List[str] = Field(default_factory=list, description="List of materials and resources needed")
    
    # 5E Backbone + Gradual Release
    engage: Warmup = Field(..., description="Phase 1: Engage (Hook) - Activate prior knowledge")
    explore: Activity = Field(..., description="Phase 2: Explore (Students try) - Student discovery")
    explain: List[ConceptItem] = Field(default_factory=list, description="Phase 3: Explain (I Do) - Teacher-led explanation of concepts")
    elaborate: Optional[ElaborateSection] = Field(None, description="Phase 4: Elaborate (We Do + You Do) - Guided and independent practice")
    evaluate: Optional[Assessment] = Field(None, description="Phase 5: Evaluate (Check) - Assessment and reflection")
    
    final_milestone: Optional[Milestone] = Field(None, description="A cumulative task requiring integration of all lesson concepts")
    closure: Optional[Closure] = Field(None)
    timing_contingency: str = Field("Monitor pace and adjust as needed.", description="Alternative plan if the lesson runs too fast or too slow")
    fallback_strategy: str = Field("提供一對一指導或輔助教具。", description="Specific strategy to take if students are not understanding (Fallback if NO)")
    diversification_notes: str = Field("多元化教學以適應不同學習風格。", description="Specific notes on how this lesson accommodates different learning styles")
    style_assets: StyleSpecificAssets = Field(default_factory=StyleSpecificAssets, description="Tailored pedagogical assets based on the teacher's Grasha style")
