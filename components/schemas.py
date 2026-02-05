# -*- coding: utf-8 -*-
from pipeline.core.flow.io import StringItemSchema, ArrayItemSchema


class ExtendedStringSchema(StringItemSchema):
    def __init__(self, description, param_type=None, enum=None):
        self.param_type = param_type
        super().__init__(description=description, enum=enum)

    def as_dict(self):
        base = super().as_dict()
        if self.param_type:
            base["param_type"] = self.param_type
        return base


class ExtendedArraySchema(ArrayItemSchema):
    def __init__(self, item_schema, description, param_type=None, enum=None):
        self.param_type = param_type
        super().__init__(item_schema=item_schema, description=description, enum=enum)

    def as_dict(self):
        base = super().as_dict()
        if self.param_type:
            base["param_type"] = self.param_type
        return base
