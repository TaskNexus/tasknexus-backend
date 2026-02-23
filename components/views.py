
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from pipeline.component_framework.library import ComponentLibrary
from .models import ComponentCategory

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
            icon = getattr(component_cls, 'icon', '')
            
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
                'icon': icon,
                'inputs': inputs,
                'outputs': outputs
            })
            
        return Response(components)


class CategoryViewSet(viewsets.ViewSet):
    """
    API endpoint for managing component category icons.
    GET  /api/categories/       -> list all categories (auto-syncs from components)
    PATCH /api/categories/{name}/ -> update a category's icon
    """

    def list(self, request):
        # Collect all category names from registered components
        category_names = set()
        for code, version_dict in ComponentLibrary.components.items():
            if not isinstance(version_dict, dict) or not version_dict:
                continue
            for v, cls in version_dict.items():
                cat = getattr(cls, 'category', 'Uncategorized')
                category_names.add(cat)
                break

        # Ensure each category exists in DB (create with default icon if missing)
        for cat_name in category_names:
            ComponentCategory.objects.get_or_create(
                name=cat_name,
                defaults={'icon': 'Component'}
            )

        # Return all saved categories
        categories = ComponentCategory.objects.all().order_by('name')
        data = [{'name': c.name, 'icon': c.icon} for c in categories]
        return Response(data)

    def partial_update(self, request, pk=None):
        """
        PATCH /api/categories/{name}/
        Body: { "icon": "Sparkles" }
        """
        name = pk
        icon = request.data.get('icon')
        if not icon:
            return Response({'error': 'icon is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            category = ComponentCategory.objects.get(name=name)
        except ComponentCategory.DoesNotExist:
            category = ComponentCategory.objects.create(name=name, icon=icon)
            return Response({'name': category.name, 'icon': category.icon}, status=status.HTTP_201_CREATED)

        category.icon = icon
        category.save()
        return Response({'name': category.name, 'icon': category.icon})
