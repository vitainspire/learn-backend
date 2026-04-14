import os
import json
import time
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt
from rich.layout import Layout
from rich import print as rprint
from rich.theme import Theme

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from core.models import StudentProfile, TeacherProfile, get_default_teacher, get_default_student
from engines.progress_engine import update_student_mastery, calculate_mastery
from engines.concept_graph import ConceptGraph
from services.ai_services import generate_lesson_plan_v2, generate_study_plan
from engines.class_engine import ClassEngine

# Custom Theme for a premium feel
custom_theme = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "red",
    "success": "green",
    "vibrant": "magenta bold",
    "teacher": "blue bold",
    "student": "orange3 bold"
})

console = Console(theme=custom_theme)
OUTPUT_DIR = Path(__file__).parent / "output"

class ShowcaseCLI:
    def __init__(self):
        self.student = get_default_student()
        self.teacher = get_default_teacher()
        self.current_book = None
        self.ontology = None
        self.cg = None

    def main_menu(self):
        while True:
            console.clear()
            console.print(Panel.fit(
                "[vibrant]ADAPTIVE LEARNING PLATFORM SHOWCASE[/vibrant]\n[cyan]Empowering Teachers | Personalizing Education[/cyan]",
                border_style="magenta"
            ))
            console.print("\n[teacher]1. Teacher Portal[/teacher]")
            console.print("[student]2. Student Portal[/student]")
            console.print("[white]0. Exit[/white]")

            choice = Prompt.ask("\nSelect Mode", choices=["1", "2", "0"])

            if choice == "1":
                self.teacher_portal()
            elif choice == "2":
                self.student_portal()
            else:
                break

    def _select_book(self):
        books = [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and (d / "ontology.json").exists()]
        if not books:
            console.print("[error]No books found in output directory! Please run 'textbook_intelligence.py analyze' first.[/error]")
            time.sleep(2)
            return False

        table = Table(title="Select a Textbook", border_style="cyan")
        table.add_column("ID", style="dim")
        table.add_column("Book Name", style="cyan")

        for idx, book in enumerate(books):
            table.add_row(str(idx + 1), book.name)

        console.print(table)
        choice = IntPrompt.ask("Select Book ID", default=1)
        
        if 1 <= choice <= len(books):
            self.current_book = books[choice - 1]
            with open(self.current_book / "ontology.json", "r", encoding="utf-8") as f:
                self.ontology = json.load(f)
            self.cg = ConceptGraph(self.ontology)
            return True
        return False

    # --- TEACHER PORTAL ---
    def teacher_portal(self):
        if not self._select_book(): return

        while True:
            console.clear()
            console.print(Panel(f"[teacher]TEACHER PORTAL[/teacher] | Book: [cyan]{self.current_book.name}[/cyan]", border_style="blue"))
            console.print(f"Current Style: [vibrant]{self.teacher.teaching_style}[/vibrant] | Duration: [cyan]{self.teacher.lesson_duration}[/cyan]")
            
            console.print("\n1. Configure Teaching Style")
            console.print("2. Generate Adaptive Lesson Plan")
            console.print("3. View Class Progress (Concept Graph)")
            console.print("0. Back to Main Menu")

            choice = Prompt.ask("\nAction", choices=["1", "2", "3", "0"])

            if choice == "1":
                self.teacher.teaching_style = Prompt.ask("Set Style", choices=["lecture", "activity", "storytelling"], default=self.teacher.teaching_style)
                self.teacher.lesson_duration = Prompt.ask("Set Duration", default=self.teacher.lesson_duration)
            elif choice == "2":
                self._generate_lesson_flow()
            elif choice == "3":
                self._view_class_dashboard()
            else:
                break

    def _generate_lesson_flow(self):
        # Support strict entities or legacy chapters
        chapters = self.ontology.get('entities', {}).get('chapters') or self.ontology.get('chapters', [])
        
        table = Table(title="Select Chapter")
        for idx, chap in enumerate(chapters):
            table.add_row(str(idx + 1), chap.get('chapter_title') or chap.get('title'))
        console.print(table)
        
        chap_idx = IntPrompt.ask("Select Chapter ID") - 1
        chapter = chapters[chap_idx]
        chap_id = chapter.get('id') or chap_idx # fallback for legacy

        # Filter topics by chapter_id if strict, else use legacy list
        if 'entities' in self.ontology:
            topics = [t for t in self.ontology['entities'].get('topics', []) if t.get('chapter_id') == chap_id]
        else:
            topics = chapter.get('topics', [])
            
        table = Table(title=f"Topics in {chapter.get('chapter_title') or chapter.get('title')}")
        for idx, topic in enumerate(topics):
            table.add_row(str(idx + 1), topic.get('topic_name') or topic.get('name'))
        console.print(table)
        
        topic_idx = IntPrompt.ask("Select Topic ID") - 1
        topic = topics[topic_idx]
        topic_name = topic.get('topic_name') or topic.get('name')

        # Collect all topic names in this chapter for continuity context
        chapter_topic_names = [t.get('topic_name') or t.get('name') for t in topics]

        with console.status("[vibrant]AI is tailoring the lesson plan...[/vibrant]"):
            # Use the harmonized topic_name
            gaps = self.cg.find_learning_gaps(self.student, topic_name)
            plan = generate_lesson_plan_v2(
                topic_name=topic_name,
                ontology_context=json.dumps(topic, indent=2),
                chapter_topics=chapter_topic_names,
                grade="Grade 1",
                duration=self.teacher.lesson_duration,
                teacher_profile=vars(self.teacher),
                student_profile=vars(self.student),
                learning_gaps=gaps
            )
        
        # Render the new 6-part flow beautifully
        console.clear()
        console.print(Panel(f"[vibrant]{plan.get('title', 'Lesson Plan')}[/vibrant]", border_style="magenta"))
        console.print(f"[cyan]Objective:[/cyan] {plan.get('objective', 'N/A')}")
        console.print(f"[dim]Style: {plan.get('metadata', {}).get('teaching_style')} | Difficulty: {plan.get('metadata', {}).get('difficulty')}[/dim]\n")

        for step in plan.get('flow', []):
            phase = step.get('phase')
            duration = step.get('time')
            goal = step.get('goal')
            
            # Color coding for different phases
            color = "yellow" if "Warm-Up" in phase else "cyan" if "Introduction" in phase else "green" if "Activity" in phase else "blue"
            
            content = f"[bold {color}]{phase} ({duration})[/bold {color}]\n[dim]{goal}[/dim]\n"
            
            if "scaffolding_steps" in step:
                content += "\n".join([f"• {s}" for s in step['scaffolding_steps']])
            elif "activity_details" in step:
                content += f"\n[italic]{step['activity_details']}[/italic]"
            elif "questions" in step:
                content += "\nQuestions: " + ", ".join(step['questions'])
            elif "summary" in step:
                content += f"\nSummary: {step['summary']}\nNext Day: {step.get('next_day_forecast')}"
            else:
                content += f"\n{step.get('script')}\n[italic]Interaction: {step.get('interaction')}[/italic]"

            console.print(Panel(content, border_style=color))

        console.print(f"\n[dim]Adaptation Log: {plan.get('adaptation_log')}[/dim]")
        
        teach_now = Prompt.ask("\nMark this topic as 'Taught Today' for your students?", choices=["y", "n"], default="y")
        if teach_now == "y":
            self.teacher.taught_today.append({
                "topic_name": topic_name,
                "book": self.current_book.name,
                "chapter_idx": chap_idx,
                "topic_idx": topic_idx
            })
            # Simulate pushing to student notification queue
            self.student.notifications.append({
                "type": "taught_today",
                "topic_name": topic_name,
                "book": self.current_book.name,
                "chapter_idx": chap_idx,
                "topic_idx": topic_idx,
                "message": f"This was taught in class today! Do you want a personalized study plan for '{topic_name}'?"
            })
            console.print(f"[success]Topic '{topic_name}' marked as taught. Students notified![/success]")
            time.sleep(1)
        
        Prompt.ask("\nPress Enter to continue")

    def _view_class_dashboard(self):
        # Mock students for demo
        s1 = get_default_student(); s1.student_id = "S101"; s1.concept_mastery = {"Shapes": 0.45, "Numbers": 0.8}
        s2 = get_default_student(); s2.student_id = "S102"; s2.concept_mastery = {"Shapes": 0.85, "Numbers": 0.9}
        s3 = get_default_student(); s3.student_id = "S103"; s3.concept_mastery = {"Shapes": 0.30, "Numbers": 0.7, "Addition": 0.4}
        s3.frustration_level = 0.8
        
        engine = ClassEngine([s1, s2, s3, self.student])
        stats = engine.get_topic_mastery_stats()
        at_risk = engine.get_at_risk_students()
        suggestions = engine.get_teaching_suggestions()

        console.print("\n[teacher]CLASSROOM ANALYTICS[/teacher]")
        
        # 1. Topic Stats
        table = Table(title="Topic Mastery & Coverage", border_style="blue")
        table.add_column("Topic", style="cyan")
        table.add_column("Avg Mastery", justify="center")
        table.add_column("Struggling", justify="center")

        for s in stats:
            table.add_row(s['topic'], f"{int(s['avg_mastery']*100)}%", f"[red]{s['students_struggling']}[/red]")
        console.print(table)

        # 2. At Risk
        if at_risk:
            table_risk = Table(title="At-Risk Students", border_style="red")
            table_risk.add_column("Student ID", style="magenta")
            table_risk.add_column("Avg Mastery", justify="center")
            table_risk.add_column("Frustration", justify="center")
            for r in at_risk:
                table_risk.add_row(r['student_id'], f"{int(r['avg_mastery']*100)}%", f"[vibrant]{r['frustration']}[/vibrant]")
            console.print(table_risk)

        # 3. Suggestions
        console.print(Panel("\n".join(suggestions), title="[teacher]AI Co-Teacher Advice[/teacher]", border_style="green"))
        
        Prompt.ask("\nPress Enter to return")

    # --- STUDENT PORTAL ---
    def student_portal(self):
        while True:
            console.clear()
            console.print(Panel(f"[student]STUDENT PORTAL[/student] | Student: [cyan]{self.student.student_id}[/cyan]", border_style="orange3"))
            
            # Show current state
            frustration = f"[red]{self.student.frustration_level}[/red]" if self.student.frustration_level > 0.5 else f"[green]{self.student.frustration_level}[/green]"
            console.print(f"Learning Style: [cyan]{self.student.learning_style}[/cyan] | Frustration: {frustration}")
            
            # Show Notifications/Updates
            if self.student.notifications:
                for idx, note in enumerate(self.student.notifications):
                    console.print(Panel(f"[vibrant]CLASS UPDATE:[/vibrant] {note['message']}", border_style="yellow"))

            console.print("\n1. Configure Learning Style")
            console.print("2. Current Mastery Roadmap")
            console.print("3. Take Quiz (Knowledge Check)")
            console.print("4. Generate My Study Plan")
            console.print("5. Respond to Class Updates")
            console.print("0. Back to Main Menu")

            choice = Prompt.ask("\nAction", choices=["1", "2", "3", "4", "5", "0"])

            if choice == "1":
                self.student.learning_style = Prompt.ask("Your Style", choices=["visual", "story", "examples", "auditory"], default=self.student.learning_style)
            elif choice == "2":
                self._view_roadmap()
            elif choice == "3":
                self._take_quiz_flow()
            elif choice == "4":
                self._generate_study_flow()
            elif choice == "5":
                self._handle_notifications()
            else:
                break

    def _view_roadmap(self):
        if not self.ontology:
            if not self._select_book(): return

        table = Table(title="Knowledge Roadmap")
        table.add_column("Concept", style="cyan")
        table.add_column("Mastery", justify="center")
        
        for topic, m in self.student.concept_mastery.items():
            color = "green" if m >= 0.8 else "yellow" if m >= 0.6 else "red"
            table.add_row(topic, f"[{color}]{int(m*100)}%[/{color}]")
        
        console.print(table)
        
        next_topic = self.cg.recommend_next_concept(self.student)
        if next_topic:
            console.print(Panel(f"Recommended Next Concept: [vibrant]{next_topic['topic_name']}[/vibrant]", border_style="green"))
        else:
            console.print("[success]You have mastered the current curriculum path![/success]")
            
        Prompt.ask("\nPress Enter to return")

    def _take_quiz_flow(self):
        if not self.ontology:
            if not self._select_book(): return
            
        topic_name = Prompt.ask("Enter topic name to test (e.g., Shapes)")
        score = float(Prompt.ask("Enter score (0.0 to 1.0)"))
        attempts = IntPrompt.ask("Number of attempts", default=1)
        hints = IntPrompt.ask("Hints used", default=0)
        
        performance = {
            "score": score,
            "attempts": attempts,
            "time_spent": 300,
            "hints_used": hints,
            "expected_time": 300
        }
        
        update_student_mastery(self.student, topic_name, performance)
        console.print(f"[success]System updated! New mastery for {topic_name}: {self.student.concept_mastery[topic_name]}[/success]")
        console.print(f"Current Frustration: {self.student.frustration_level}")
        time.sleep(2)

    def _generate_study_flow(self):
        if not self.ontology:
            if not self._select_book(): return

        next_topic = self.cg.recommend_next_concept(self.student)
        if not next_topic:
            console.print("[warning]No new topics to study right now. Master your current ones first![/warning]")
            time.sleep(2)
            return

        with console.status(f"[vibrant]Generating a quest for {next_topic['topic_name']}...[/vibrant]"):
            plan = generate_study_plan(
                student_profile=vars(self.student),
                ontology_context=json.dumps(next_topic, indent=2),
                topic_name=next_topic['topic_name'],
                grade="Grade 1"
            )
            
        console.print(Panel(plan, title=f"Your Next Learning Quest: {next_topic['topic_name']}", border_style="magenta"))
        Prompt.ask("\nPress Enter to continue")

    def _handle_notifications(self):
        if not self.student.notifications:
            console.print("[info]No active class updates.[/info]")
            time.sleep(1)
            return

        note = self.student.notifications[0] # Handle first for demo
        console.print(f"\n[vibrant]Notification:[/vibrant] {note['message']}")
        confirm = Prompt.ask("Generate this study plan now?", choices=["y", "n"], default="y")
        
        if confirm == "y":
            # Load context for the specific topic
            with open(OUTPUT_DIR / note['book'] / "ontology.json", "r", encoding="utf-8") as f:
                temp_ontology = json.load(f)
            
            # Use strict layout if present
            if 'entities' in temp_ontology:
                chapters = temp_ontology['entities'].get('chapters', [])
                chap = chapters[note['chapter_idx']]
                chap_id = chap.get('id')
                topics = [t for t in temp_ontology['entities'].get('topics', []) if t.get('chapter_id') == chap_id]
                topic_context = topics[note['topic_idx']]
            else:
                topic_context = temp_ontology['chapters'][note['chapter_idx']]['topics'][note['topic_idx']]
            
            with console.status(f"[vibrant]Creating your post-lecture quest for {note['topic_name']}...[/vibrant]"):
                plan = generate_study_plan(
                    student_profile=vars(self.student),
                    ontology_context=json.dumps(topic_context, indent=2),
                    topic_name=note['topic_name'],
                    grade="Grade 3",
                    context_type="post-lecture-review"
                )
            
            console.print(Panel(plan, title=f"Review Quest: {note['topic_name']}", border_style="magenta"))
            self.student.notifications.pop(0) # Clear after handling
            Prompt.ask("\nPress Enter to continue")
        else:
            clear = Prompt.ask("Clear this notification?", choices=["y", "n"], default="n")
            if clear == "y":
                self.student.notifications.pop(0)

if __name__ == "__main__":
    cli = ShowcaseCLI()
    cli.main_menu()
