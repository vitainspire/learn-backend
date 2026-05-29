import json
from typing import List, Dict, Optional
from core.models import StudentProfile

class ConceptGraph:
    def __init__(self, ontology_dict: dict):
        self.ontology = ontology_dict
        self.adj = {} # topic_id/name -> list of dependents
        self.prereqs = {} # topic_id/name -> list of prerequisites
        
        # Mappings for strict ontology
        self.id_to_name = {}
        self.name_to_id = {}
        self.id_to_topic = {}
        
        self._build_graph()

    def _build_graph(self):
        # 1. Detect if it's strict ontology (has 'entities' and 'graphs')
        if 'entities' in self.ontology and 'graphs' in self.ontology:
            # Strict mode
            for topic in self.ontology['entities'].get('topics', []):
                tid = topic['id']
                tname = topic['name']
                self.id_to_name[tid] = tname
                self.name_to_id[tname] = tid
                self.id_to_topic[tid] = topic
                self.prereqs[tname] = [] # Use names for student profile compat
                if tname not in self.adj:
                    self.adj[tname] = []
            
            # Use concept_dependencies graph
            for edge in self.ontology['graphs'].get('concept_dependencies', []):
                child_id = edge['from']
                parent_id = edge['to']
                child_name = self.id_to_name.get(child_id)
                parent_name = self.id_to_name.get(parent_id)
                
                if child_name and parent_name:
                    if child_name not in self.prereqs: self.prereqs[child_name] = []
                    self.prereqs[child_name].append(parent_name)
                    if parent_name not in self.adj: self.adj[parent_name] = []
                    self.adj[parent_name].append(child_name)
        else:
            # Legacy mode
            for chapter in self.ontology.get('chapters', []):
                for topic in chapter.get('topics', []):
                    name = topic['topic_name']
                    prereqs = topic.get('prerequisites', [])
                    self.prereqs[name] = prereqs
                    if name not in self.adj:
                        self.adj[name] = []
                    for p in prereqs:
                        if p not in self.adj:
                            self.adj[p] = []
                        self.adj[p].append(name)

    def find_learning_gaps(self, student: StudentProfile, current_topic: str) -> List[str]:
        """Identify prerequisites for the current topic that the student hasn't mastered (threshold < 0.7)."""
        gaps = []
        # Support both name and ID (though names are used in mastery)
        prereqs = self.prereqs.get(current_topic, [])
        for p in prereqs:
            mastery = student.concept_mastery.get(p, 0.0)
            if mastery < 0.7:
                gaps.append(p)
        return gaps

    def recommend_next_concept(self, student: StudentProfile) -> Optional[dict]:
        """
        Suggest the next topic where all prerequisites are met but mastery is low.
        Returns the topic dict from the ontology.
        """
        # Strict ontology items
        if self.id_to_topic:
            for tid, topic in self.id_to_topic.items():
                name = self.id_to_name[tid]
                if student.concept_mastery.get(name, 0.0) >= 0.8:
                    continue 
                
                prereqs = self.prereqs.get(name, [])
                all_met = True
                for p in prereqs:
                    if student.concept_mastery.get(p, 0.0) < 0.7:
                        all_met = False
                        break
                
                if all_met:
                    # Return topic in a format compatible with legacy (or dict)
                    # The CLI expects 'topic_name' in some places, so we harmonize
                    topic_copy = dict(topic)
                    if 'name' in topic_copy and 'topic_name' not in topic_copy:
                        topic_copy['topic_name'] = topic_copy['name']
                    return topic_copy
        
        # Fallback to legacy structure loop
        for chapter in self.ontology.get('chapters', []):
            for topic in chapter.get('topics', []):
                name = topic['topic_name']
                if student.concept_mastery.get(name, 0.0) >= 0.8:
                    continue 
                
                prereqs = self.prereqs.get(name, [])
                all_met = True
                for p in prereqs:
                    if student.concept_mastery.get(p, 0.0) < 0.7:
                        all_met = False
                        break
                
                if all_met:
                    return topic
        return None
