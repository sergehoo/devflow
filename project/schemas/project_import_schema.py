PROJECT_IMPORT_SCHEMA = {
    "name": "devflow_project_import",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "project": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": ["string", "null"]},
                    "description": {"type": ["string", "null"]},
                    "tech_stack": {"type": ["string", "null"]},
                    "status": {
                        "type": ["string", "null"],
                        "enum": [
                            "PLANNED", "IN_PROGRESS", "IN_DELIVERY",
                            "BLOCKED", "DELAYED", "DONE", "ON_HOLD",
                            "CANCELLED", None
                        ]
                    },
                    "priority": {
                        "type": ["string", "null"],
                        "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL", None]
                    },
                    "start_date": {"type": ["string", "null"]},
                    "target_date": {"type": ["string", "null"]},
                },
                "required": ["name", "code", "description", "tech_stack", "status", "priority", "start_date", "target_date"]
            },
            "roadmap": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "start_date": {"type": ["string", "null"]},
                        "end_date": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"]}
                    },
                    "required": ["title", "description", "start_date", "end_date", "status"]
                }
            },
            "milestones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "due_date": {"type": ["string", "null"]},
                        "status": {"type": ["string", "null"]},
                        "related_roadmap_title": {"type": ["string", "null"]}
                    },
                    "required": ["name", "description", "due_date", "status", "related_roadmap_title"]
                }
            },
            "sprints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "goal": {"type": ["string", "null"]},
                        "start_date": {"type": ["string", "null"]},
                        "end_date": {"type": ["string", "null"]},
                        "team_name": {"type": ["string", "null"]},
                        "features": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["name", "goal", "start_date", "end_date", "team_name", "features"]
                }
            },
            "teams": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "team_type": {"type": ["string", "null"]},
                        "mission": {"type": ["string", "null"]}
                    },
                    "required": ["name", "team_type", "mission"]
                }
            },
            "features": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "sprint_name": {"type": ["string", "null"]},
                        "milestone_name": {"type": ["string", "null"]},
                        "estimated_cost": {"type": ["number", "null"]},
                        "estimated_revenue": {"type": ["number", "null"]},
                        "roi_percent": {"type": ["number", "null"]}
                    },
                    "required": ["title", "description", "sprint_name", "milestone_name", "estimated_cost", "estimated_revenue", "roi_percent"]
                }
            },
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": ["string", "null"]},
                        "feature_title": {"type": ["string", "null"]},
                        "sprint_name": {"type": ["string", "null"]},
                        "priority": {"type": ["string", "null"]},
                        "estimate_hours": {"type": ["number", "null"]},
                        "team_name": {"type": ["string", "null"]}
                    },
                    "required": ["title", "description", "feature_title", "sprint_name", "priority", "estimate_hours", "team_name"]
                }
            },
            "financials": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "approved_budget": {"type": ["number", "null"]},
                    "planned_revenue": {"type": ["number", "null"]},
                    "contingency_amount": {"type": ["number", "null"]},
                    "management_reserve_amount": {"type": ["number", "null"]},
                    "overhead_cost_amount": {"type": ["number", "null"]},
                    "tax_amount": {"type": ["number", "null"]},
                    "cost_per_sprint": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "sprint_name": {"type": "string"},
                                "cost": {"type": ["number", "null"]}
                            },
                            "required": ["sprint_name", "cost"]
                        }
                    },
                    "cost_per_feature": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "feature_title": {"type": "string"},
                                "cost": {"type": ["number", "null"]}
                            },
                            "required": ["feature_title", "cost"]
                        }
                    },
                    "roi_per_module": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "module_name": {"type": "string"},
                                "roi_percent": {"type": ["number", "null"]}
                            },
                            "required": ["module_name", "roi_percent"]
                        }
                    }
                },
                "required": [
                    "approved_budget",
                    "planned_revenue",
                    "contingency_amount",
                    "management_reserve_amount",
                    "overhead_cost_amount",
                    "tax_amount",
                    "cost_per_sprint",
                    "cost_per_feature",
                    "roi_per_module"
                ]
            },
            "kpis": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "value": {"type": ["number", "string", "null"]},
                        "unit": {"type": ["string", "null"]},
                        "module_name": {"type": ["string", "null"]}
                    },
                    "required": ["name", "value", "unit", "module_name"]
                }
            }
        },
        "required": [
            "project",
            "roadmap",
            "milestones",
            "sprints",
            "teams",
            "features",
            "tasks",
            "financials",
            "kpis"
        ]
    },
    "strict": True,
}