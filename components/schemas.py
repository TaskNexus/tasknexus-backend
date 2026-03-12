# -*- coding: utf-8 -*-
from pipeline.core.flow.io import StringItemSchema, ArrayItemSchema, ObjectItemSchema


class ExtendedStringSchema(StringItemSchema):
    def __init__(self, description, param_type=None, enum=None, visible_when=None):
        self.param_type = param_type
        self.visible_when = visible_when
        super().__init__(description=description, enum=enum)

    def as_dict(self):
        base = super().as_dict()
        if self.param_type:
            base["param_type"] = self.param_type
        if isinstance(self.visible_when, dict) and self.visible_when:
            base["visible_when"] = self.visible_when
        return base


class ExtendedArraySchema(ArrayItemSchema):
    def __init__(self, item_schema, description, param_type=None, enum=None, visible_when=None):
        self.param_type = param_type
        self.visible_when = visible_when
        super().__init__(item_schema=item_schema, description=description, enum=enum)

    def as_dict(self):
        base = super().as_dict()
        if self.param_type:
            base["param_type"] = self.param_type
        if isinstance(self.visible_when, dict) and self.visible_when:
            base["visible_when"] = self.visible_when
        return base


class ExtendedObjectSchema(ObjectItemSchema):
    def __init__(self, property_schemas, description, param_type=None, enum=None, visible_when=None):
        self.param_type = param_type
        self.visible_when = visible_when
        super().__init__(property_schemas=property_schemas, description=description, enum=enum)

    def as_dict(self):
        base = super().as_dict()
        if self.param_type:
            base["param_type"] = self.param_type
        if isinstance(self.visible_when, dict) and self.visible_when:
            base["visible_when"] = self.visible_when
        return base
