import copy
from pipeline.core.flow.activity import SubProcess
from pipeline.engine.models import Status
from pipeline.parser.utils import recursive_replace_id
from pipeline.core.constants import PE
from django.utils import timezone


def _extract_subprocess_workflow_ids(graph_data):
    """Extract subprocess workflow ids from X6 graph_data."""
    workflow_ids = set()
    if not isinstance(graph_data, dict):
        return workflow_ids

    cells = graph_data.get('cells', [])
    if not isinstance(cells, list):
        return workflow_ids

    for cell in cells:
        if not isinstance(cell, dict):
            continue
        data = cell.get('data')
        if not isinstance(data, dict):
            continue

        node_type = str(data.get('type', '')).upper()
        if node_type != 'SUBPROCESS':
            continue

        inputs = data.get('componentInputs') or data.get('inputs') or {}
        workflow_id = None
        if isinstance(inputs, dict):
            workflow_id = inputs.get('workflow_id')
        if not workflow_id:
            workflow_id = data.get('workflow')

        if workflow_id not in (None, ''):
            workflow_ids.add(str(workflow_id))

    return workflow_ids


def build_workflow_graph_snapshot(root_workflow):
    """
    Build task graph snapshot from workflow.graph_data recursively.
    Returns:
    {
      root_workflow_id: str,
      captured_at: iso datetime str,
      graphs: { "<workflow_id>": graph_data },
      missing_workflow_ids: [str]
    }
    """
    from workflows.models import WorkflowDefinition

    graphs = {}
    missing_workflow_ids = []
    visited = set()
    queue = [str(root_workflow.id)]

    while queue:
        workflow_id = queue.pop(0)
        if workflow_id in visited:
            continue
        visited.add(workflow_id)

        try:
            wf = WorkflowDefinition.objects.get(id=workflow_id)
        except WorkflowDefinition.DoesNotExist:
            missing_workflow_ids.append(workflow_id)
            continue

        graph_data = copy.deepcopy(wf.graph_data or {})
        graphs[str(wf.id)] = graph_data

        for child_workflow_id in _extract_subprocess_workflow_ids(graph_data):
            if child_workflow_id not in visited:
                queue.append(child_workflow_id)

    return {
        'root_workflow_id': str(root_workflow.id),
        'captured_at': timezone.now().isoformat(),
        'graphs': graphs,
        'missing_workflow_ids': sorted(set(missing_workflow_ids)),
    }


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
