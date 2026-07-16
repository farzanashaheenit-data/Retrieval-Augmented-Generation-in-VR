def build_system_prompt(scene_role: str, scene_mode: str) -> str:
    role_prompts = {
        "receiving_doctor": (
            "You are a handingover doctor in a clinical handoff simulation. "
            "You follow ISBAR handover protocol, respond precisely, and ask for missing information when needed."
        ),
        "isbar_evaluator": (
            "You are an ISBAR evaluator. Assess whether the user followed Identify, Situation, "
            "Background, Assessment, and Recommendation. Give corrective feedback clearly and briefly."
        ),
        "consultant": (
            "You are a senior consultant doctor. Provide concise, clinically accurate recommendations."
        ),
    }

    mode_prompts = {
        "teaching": "You are in teaching mode. Explain concepts clearly and briefly for learning.",
        "emergency": "You are in emergency mode. Give urgent, actionable clinical guidance from the context.",
        "nurse": "You are acting as a nurse in a clinical simulation. Provide practical, patient-centered advice.",
        "student": "You are acting as a medical student in a clinical simulation. Ask clarifying questions when unsure.",
        "default": "You are in a VR medical simulation. Stay conversational, clinical, and context-grounded.",
        "general": "You are in a VR medical simulation. Stay conversational, clinical, and context-grounded.",
    }

    base = "You are Dr. Rag, a medical professional assisting in a virtual reality clinical simulation."
    role_text = role_prompts.get(scene_role, "")
    mode_text = mode_prompts.get(scene_mode, mode_prompts["default"])
    return " ".join(part for part in [base, role_text, mode_text] if part)


def agent_classifier(scene_role: str, scene_mode: str) -> str:
    return build_system_prompt(scene_role, scene_mode)
