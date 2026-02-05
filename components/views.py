
from rest_framework import viewsets
from rest_framework.response import Response
from pipeline.component_framework.library import ComponentLibrary

class ComponentViewSet(viewsets.ViewSet):
    """
    API endpoint that allows components to be viewed.
    """
    def list(self, request):
        components = []
        # ComponentLibrary.components is a dict of {code: {version: ComponentClass}}
        for code, version_dict in ComponentLibrary.components.items():
            if not isinstance(version_dict, dict) or not version_dict:
                continue
                
            # Pick a version - prioritization: '1.0' > any other > 'legacy'
            # Or just take the first one found that isn't legacy if possible, or just the first one.
            # Simplified approach: take the last one (assuming order implies newness? Unlikely in dict)
            # or explicitly look for 1.0.
            
            target_cls = None
            # Sort versions to try getting the latest? 
            # For now, let's just grab one.
            for v, cls in version_dict.items():
                target_cls = cls
                if v != 'legacy':
                    break # Prefer non-legacy
            
            if not target_cls:
                continue
                
            component_cls = target_cls

            # Get metadata if available, otherwise defaults
            name = getattr(component_cls, 'name', code)
            category = getattr(component_cls, 'category', 'Uncategorized')
            version = getattr(component_cls, 'version', '1.0')
            description = getattr(component_cls, 'description', '')
            
            # Get inputs/outputs schema
            # Instantiate service to get formats? Or access static methods?
            # bamboo-engine formatting involves creating an instance or calling class methods if defined.
            # In our example, inputs_format is an instance method of Service.
            # But we can instantiate the service easily? 
            # component_cls.bound_service is the Service class.
            
            inputs = []
            outputs = []
            
            try:
                service = component_cls.bound_service()
                
                if hasattr(service, 'inputs_format'):
                     # returns list of InputItem
                     for item in service.inputs_format():
                         input_data = {
                             'name': item.name,
                             'key': item.key,
                             'type': item.type,
                             'required': item.required
                         }
                         # Include schema if present
                         if item.schema:
                             input_data['schema'] = item.schema.as_dict()
                         inputs.append(input_data)
                         
                if hasattr(service, 'outputs_format'):
                     # returns list of OutputItem
                     for item in service.outputs_format():
                         outputs.append({
                             'name': item.name,
                             'key': item.key,
                             'type': item.type
                         })
            except Exception:
                pass

            components.append({
                'code': code,
                'name': name,
                'category': category,
                'version': version,
                'description': description,
                'inputs': inputs,
                'outputs': outputs
            })
            
        return Response(components)
