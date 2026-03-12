from rest_framework import serializers

from .models import ComponentNodeTemplate


FORBIDDEN_NODE_TYPES = {
    "START",
    "END",
    "SUBPROCESS",
    "BRANCH",
    "PARALLEL",
    "CONVERGE",
    "CONDITIONAL",
    "EXCLUSIVE_GATEWAY",
    "PARALLEL_GATEWAY",
    "CONVERGE_GATEWAY",
    "CONDITIONAL_PARALLEL",
}

ALLOWED_NODE_DATA_KEYS = {
    "label",
    "type",
    "icon",
    "componentCode",
    "version",
    "componentInputs",
    "componentOutputs",
    "inputs",
    "outputs",
    "errorIgnorable",
    "skippable",
    "retryable",
}


class ComponentNodeTemplateSerializer(serializers.ModelSerializer):
    created_by = serializers.IntegerField(source="created_by_id", read_only=True)

    class Meta:
        model = ComponentNodeTemplate
        fields = [
            "id",
            "name",
            "node_data",
            "component_code",
            "component_version",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ("component_code", "component_version", "created_by", "created_at", "updated_at")

    def validate_name(self, value):
        name = str(value or "").strip()
        if not name:
            raise serializers.ValidationError("name is required.")
        return name

    def _sanitize_node_data(self, raw_data):
        if not isinstance(raw_data, dict):
            raise serializers.ValidationError("node_data must be an object.")

        node_type = str(raw_data.get("type") or "").strip().upper()
        if node_type in FORBIDDEN_NODE_TYPES:
            raise serializers.ValidationError("Only component nodes can be saved as templates.")

        component_code = str(raw_data.get("componentCode") or "").strip()
        if not component_code:
            raise serializers.ValidationError("node_data.componentCode is required for component templates.")

        sanitized = {}
        for key in ALLOWED_NODE_DATA_KEYS:
            if key in raw_data:
                sanitized[key] = raw_data[key]

        sanitized["componentCode"] = component_code
        sanitized["type"] = str(sanitized.get("type") or "CUSTOM").strip().upper()

        if sanitized["type"] in FORBIDDEN_NODE_TYPES:
            raise serializers.ValidationError("Only component nodes can be saved as templates.")

        if not isinstance(sanitized.get("inputs"), dict):
            sanitized["inputs"] = {}
        if not isinstance(sanitized.get("outputs"), list):
            sanitized["outputs"] = []
        if not isinstance(sanitized.get("componentInputs"), list):
            sanitized["componentInputs"] = []
        if not isinstance(sanitized.get("componentOutputs"), list):
            sanitized["componentOutputs"] = []

        sanitized["label"] = str(sanitized.get("label") or component_code).strip() or component_code
        sanitized["icon"] = str(sanitized.get("icon") or "Component").strip() or "Component"
        sanitized["errorIgnorable"] = bool(sanitized.get("errorIgnorable", False))
        sanitized["skippable"] = bool(sanitized.get("skippable", True))
        sanitized["retryable"] = bool(sanitized.get("retryable", True))
        sanitized["version"] = str(sanitized.get("version") or "").strip()

        return sanitized

    def validate(self, attrs):
        node_data = attrs.get("node_data")
        if node_data is None and self.instance is None:
            raise serializers.ValidationError({"node_data": "node_data is required."})

        if node_data is not None:
            sanitized = self._sanitize_node_data(node_data)
            attrs["node_data"] = sanitized
            attrs["component_code"] = sanitized["componentCode"]
            attrs["component_version"] = str(sanitized.get("version") or "")

        return attrs
