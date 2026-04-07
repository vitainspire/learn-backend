import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.text import PP_ALIGN
from pptx.dml.color import RGBColor
from datetime import datetime

class PPTXService:
    def __init__(self):
        # Charcoal Minimal Palette
        self.COLORS = {
            'bg': RGBColor(33, 33, 33), # Dark Charcoal
            'primary': RGBColor(242, 242, 242), # Off-white
            'accent': RGBColor(16, 163, 127), # Teal/Greenish Accent
            'text_muted': RGBColor(180, 180, 180)
        }

    def _apply_design_accents(self, slide):
        """Adds premium geometric accents to the slide."""
        # Top Accent Line
        line = slide.shapes.add_shape(6, Inches(0.5), Inches(0.4), Inches(2), Inches(0.05))
        line.fill.solid()
        line.fill.fore_color.rgb = self.COLORS['accent']
        line.line.fill.background()
        
        # Left Sidebar for Title Slides
        sidebar = slide.shapes.add_shape(1, Inches(0), Inches(0), Inches(0.1), Inches(7.5))
        sidebar.fill.solid()
        sidebar.fill.fore_color.rgb = self.COLORS['accent']
        sidebar.line.fill.background()

    def _add_slide(self, prs, title):
        slide_layout = prs.slide_layouts[6] # Blank
        slide = prs.slides.add_slide(slide_layout)
        
        # Apply Dark Background
        background = slide.background
        fill = background.fill
        fill.solid()
        fill.fore_color.rgb = self.COLORS['bg']
        
        self._apply_design_accents(slide)
        
        # Add Title
        txBox = slide.shapes.add_textbox(Inches(0.7), Inches(0.6), Inches(12), Inches(1))
        tf = txBox.text_frame
        p = tf.add_paragraph()
        p.text = title.upper()
        p.font.bold = True
        p.font.size = Pt(32)
        p.font.color.rgb = self.COLORS['accent']
        p.alignment = PP_ALIGN.LEFT
        
        return slide

    def generate_lesson_pptx(self, lesson_data, output_path):
        prs = Presentation()
        prs.slide_width = Inches(13.33)  # Widescreen 16:9
        prs.slide_height = Inches(7.5)

        # SLIDE 1: ENGAGE
        print("DEBUG: Generating Slide 1 (Engage)")
        engage_data = lesson_data.get('engage') or {}
        slide1 = self._add_slide(prs, "Step 1: THE HOOK")
        
        # Lesson Title
        txBox = slide1.shapes.add_textbox(Inches(0.7), Inches(1.8), Inches(7), Inches(2))
        tf = txBox.text_frame
        p = tf.add_paragraph()
        p.text = lesson_data.get('meta', {}).get('lesson_title', "Untitled Lesson")
        p.font.bold = True
        p.font.size = Pt(54)
        p.font.color.rgb = self.COLORS['primary']
        p.line_spacing = 1.0

        # Hook Content
        txBox = slide1.shapes.add_textbox(Inches(8), Inches(1.8), Inches(4.5), Inches(4))
        fill = txBox.fill
        fill.solid()
        fill.fore_color.rgb = RGBColor(45, 45, 45) # Slightly lighter box
        
        tf = txBox.text_frame
        tf.word_wrap = True
        p = tf.add_paragraph()
        p.text = "LET'S BRAINSTORM"
        p.font.bold = True
        p.font.size = Pt(18)
        p.font.color.rgb = self.COLORS['accent']
        
        p = tf.add_paragraph()
        p.text = engage_data.get('activity', "No activity provided")
        p.font.size = Pt(20)
        p.font.color.rgb = self.COLORS['primary']

        # SLIDE 2: EXPLORE
        print("DEBUG: Generating Slide 2 (Explore)")
        explore_data = lesson_data.get('explore') or {}
        slide2 = self._add_slide(prs, "Step 2: DISCOVERY")
        
        txBox = slide2.shapes.add_textbox(Inches(0.5), Inches(2), Inches(12), Inches(3))
        tf = txBox.text_frame
        p = tf.add_paragraph()
        p.text = explore_data.get('activity', "No exploratory activity provided")
        p.font.bold = True
        p.font.size = Pt(36)
        p.font.color.rgb = self.COLORS['primary']

        # SLIDE 3: EXPLAIN
        print("DEBUG: Generating Slide 3 (Explain)")
        slide3 = self._add_slide(prs, "Step 3: CORE INSIGHTS")
        
        # Grid of concepts
        left = Inches(0.5)
        top = Inches(1.5)
        width = Inches(4)
        height = Inches(2.5)
        
        explain_concepts = lesson_data.get('explain') or []
        for i, concept in enumerate(explain_concepts[:6]): # Limit to first 6
            row = i // 3
            col = i % 3
            
            curr_left = left + (col * (width + Inches(0.2)))
            curr_top = top + (row * (height + Inches(0.2)))
            
            shape = slide3.shapes.add_textbox(curr_left, curr_top, width, height)
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(40, 40, 40)
            
            tf = shape.text_frame
            p = tf.add_paragraph()
            p.text = concept.get('name', 'Concept') or 'Concept'
            p.font.bold = True
            p.font.size = Pt(18)
            p.font.color.rgb = self.COLORS['accent']
            
            p = tf.add_paragraph()
            teaching_data = concept.get('teaching') or {}
            method_text = teaching_data.get('method', 'Teaching details pending...') or 'Teaching details pending...'
            p.text = (method_text[:147] + "...") if len(method_text) > 150 else method_text
            p.font.size = Pt(14)
            p.font.color.rgb = self.COLORS['text_muted']

        # SLIDE 4: ELABORATE
        print("DEBUG: Generating Slide 4 (Elaborate)")
        elaborate_data = lesson_data.get('elaborate') or {}
        slide4 = self._add_slide(prs, "Step 4: APPLIED LEARNING")
        
        # We Do
        shape = slide4.shapes.add_textbox(Inches(0.5), Inches(2), Inches(6), Inches(3))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(40, 40, 40)
        tf = shape.text_frame
        p = tf.add_paragraph()
        p.text = "WE DO"
        p.font.bold = True
        p.font.size = Pt(24)
        p.font.color.rgb = self.COLORS['accent']
        p = tf.add_paragraph()
        p.text = elaborate_data.get('we_do', 'Guided practice activity.')
        p.font.size = Pt(20)
        p.font.color.rgb = self.COLORS['primary']

        # You Do
        shape = slide4.shapes.add_textbox(Inches(6.8), Inches(2), Inches(6), Inches(3))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor(40, 40, 40)
        tf = shape.text_frame
        p = tf.add_paragraph()
        p.text = "YOU DO"
        p.font.bold = True
        p.font.size = Pt(24)
        p.font.color.rgb = self.COLORS['accent']
        p = tf.add_paragraph()
        p.text = elaborate_data.get('you_do', 'Independent practice activity.')
        p.font.size = Pt(20)
        p.font.color.rgb = self.COLORS['primary']

        # SLIDE 5: EVALUATE
        print("DEBUG: Generating Slide 5 (Evaluate)")
        evaluate_data = lesson_data.get('evaluate') or {}
        slide5 = self._add_slide(prs, "Step 5: MASTERY & REFLECTION")
        
        txBox = slide5.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(12), Inches(4))
        tf = txBox.text_frame
        questions = evaluate_data.get('questions') or []
        for q in questions:
            if not q: continue
            p = tf.add_paragraph()
            p.text = f"• {q}"
            p.font.size = Pt(24)
            p.font.color.rgb = self.COLORS['primary']
            p.space_after = Pt(12)

        prs.save(output_path)
        return output_path

pptx_service = PPTXService()
