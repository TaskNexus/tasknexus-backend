import copy
from pipeline.core.flow.activity import SubProcess
from pipeline.engine.models import Status
from pipeline.parser.utils import recursive_replace_id
from pipeline.core.constants import PE


def regenerate_pipeline_ids_full(pipeline_tree):
    new_tree = copy.deepcopy(pipeline_tree)
    
    id_maps = recursive_replace_id(new_tree)
    
    node_map = {}
    subprocess_maps = {}
    
    def _flatten_id_maps(maps, target_node_map, target_subprocess_maps, is_root=True):
        for pipeline_id, pipeline_maps in maps.items():
            if isinstance(pipeline_maps, dict):
                if is_root:
                    for section in [PE.start_event, PE.end_event, PE.activities, PE.gateways]:
                        if section in pipeline_maps and isinstance(pipeline_maps[section], dict):
                            target_node_map.update(pipeline_maps[section])
                
                if 'subprocess' in pipeline_maps:
                    for sub_pid, sub_map in pipeline_maps['subprocess'].items():
                        flat_sub_map = {}
                        for sec in [PE.start_event, PE.end_event, PE.activities, PE.gateways]:
                            if sec in sub_map and isinstance(sub_map[sec], dict):
                                flat_sub_map.update(sub_map[sec])
                        
                        target_subprocess_maps[sub_pid] = flat_sub_map
                        
                        if 'subprocess' in sub_map:
                            _flatten_id_maps(
                                {sub_pid: sub_map}, 
                                target_node_map, 
                                target_subprocess_maps, 
                                is_root=False
                            )
    
    _flatten_id_maps(id_maps, node_map, subprocess_maps, is_root=True)
    
    return new_tree, node_map, subprocess_maps

def expand_pipeline_tree(pipeline_tree):
    from workflows.models import WorkflowDefinition

    for act_id, act in pipeline_tree.get('activities', {}).items():
        if act.get('type') == 'SubProcess':
            if 'pipeline' in act:
                expand_pipeline_tree(act['pipeline'])
                continue
                
            template_id = act.get('template_id')
            if not template_id:
                pass
            
            if template_id:
                try:
                    child_workflow = WorkflowDefinition.objects.get(id=template_id)
                    child_tree = copy.deepcopy(child_workflow.pipeline_tree)
                    
                    child_tree['id'] = act['id']

                    expand_pipeline_tree(child_tree)
                    
                    act['pipeline'] = child_tree
                    if 'params' not in act:
                        act['params'] = {}
                    
                    if 'template_id' in act:
                        del act['template_id']
                        
                except Exception as e:
                    print(f"Failed to expand subprocess {template_id}: {e}")
                    
    return pipeline_tree