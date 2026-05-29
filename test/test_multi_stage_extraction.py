import json
import os
import sys

# Mock for Vertex AI model and robust_json_parse to test the aggregation logic

def mock_stage_1(chapter_idx, chunk_title):
    # Returns Chapters & Core Concepts Graph
    return {
        "entities": {
            "chapters": [
                {"id": f"C_{chapter_idx}", "number": chapter_idx, "title": chunk_title}
            ]
        },
        "graphs": {
            "chapter_structure": []
        }
    }

def mock_stage_2(chapter_idx):
    # Returns Topics & Dependencies Graph for the chapter
    return {
        "entities": {
            "topics": [
                {
                    "id": f"T_{chapter_idx}_1", 
                    "name": "Topic A", 
                    "summary": "Summary A", 
                    "chapter_id": f"C_{chapter_idx}", 
                    "prerequisites": []
                },
                {
                    "id": f"T_{chapter_idx}_2", 
                    "name": "Topic B", 
                    "summary": "Summary B", 
                    "chapter_id": f"C_{chapter_idx}", 
                    "prerequisites": [f"T_{chapter_idx}_1"]
                }
            ]
        },
        "graphs": {
            "concept_dependencies": [
                {"from": f"T_{chapter_idx}_2", "to": f"T_{chapter_idx}_1", "type": "prerequisite"}
            ],
            "chapter_structure": [
                {"from": f"C_{chapter_idx}", "to": f"T_{chapter_idx}_1", "type": "contains"},
                {"from": f"C_{chapter_idx}", "to": f"T_{chapter_idx}_2", "type": "contains"}
            ]
        }
    }

def mock_stage_3(chapter_idx):
    # Returns Exercises & Details Graph for the topics
    return {
        "entities": {
            "exercises": [
                {"id": f"E_{chapter_idx}_1_1", "text": "Solve 1+1", "topic_id": f"T_{chapter_idx}_1"}
            ],
            "sidebars": [
                {"id": f"S_{chapter_idx}_2_1", "text": "Fun fact!", "topic_id": f"T_{chapter_idx}_2"}
            ]
        },
        "graphs": {
            "exercise_mapping": [
                {"from": f"E_{chapter_idx}_1_1", "to": f"T_{chapter_idx}_1", "type": "tests"}
            ]
        }
    }

def merge_entities_graphs(full_ontology, chunk_data):
    # Merge Entities
    chunk_entities = chunk_data.get('entities', {})
    for key in ["chapters", "topics", "exercises", "sidebars"]:
        existing_ids = set(e['id'] for e in full_ontology['entities'][key])
        for entity in chunk_entities.get(key, []):
            if entity.get('id') not in existing_ids:
                full_ontology['entities'][key].append(entity)
                existing_ids.add(entity.get('id'))
    
    # Merge Graphs
    new_graphs = chunk_data.get('graphs', {})
    for graph_key in ["chapter_structure", "exercise_mapping", "concept_dependencies"]:
        if graph_key not in full_ontology['graphs']:
            full_ontology['graphs'][graph_key] = []
        existing_edges = set((e['from'], e['to'], e.get('type')) for e in full_ontology['graphs'][graph_key])
        for edge in new_graphs.get(graph_key, []):
            edge_tuple = (edge.get('from'), edge.get('to'), edge.get('type'))
            if edge_tuple not in existing_edges:
                full_ontology['graphs'][graph_key].append(edge)
                existing_edges.add(edge_tuple)

def test_multi_stage_extraction():
    full_ontology = {
        "subject": "Test Book",
        "entities": {
            "chapters": [],
            "topics": [],
            "exercises": [],
            "sidebars": []
        },
        "graphs": {
            "chapter_structure": [],
            "exercise_mapping": [],
            "concept_dependencies": []
        }
    }

    # Simulate chunk processing for two chapters
    print("Simulating multi-stage extraction for 2 chunks/chapters...")
    for idx_1 in range(2):
        chap_id = idx_1 + 1
        
        # Pass 1
        data_s1 = mock_stage_1(chap_id, f"Chapter {chap_id}")
        merge_entities_graphs(full_ontology, data_s1)
        
        # Pass 2
        data_s2 = mock_stage_2(chap_id)
        merge_entities_graphs(full_ontology, data_s2)
        
        # Pass 3
        data_s3 = mock_stage_3(chap_id)
        merge_entities_graphs(full_ontology, data_s3)

    print("\n[SUCCESS] Extraction completed. Resulting Ontology Summary:")
    print(f"Chapters: {len(full_ontology['entities']['chapters'])}")
    print(f"Topics: {len(full_ontology['entities']['topics'])}")
    print(f"Exercises: {len(full_ontology['entities']['exercises'])}")
    print("\nGraphs:")
    for graph_key, edges in full_ontology['graphs'].items():
        print(f"  {graph_key}: {len(edges)} edges")
        
    if len(full_ontology['entities']['chapters']) == 2 and len(full_ontology['graphs']['concept_dependencies']) == 2:
        print("\n=> Test Passed! Merging logic works across stages and chunks.")
    else:
        print("\n=> Test Failed! Assertion mismatch on final counts.")

if __name__ == "__main__":
    test_multi_stage_extraction()
