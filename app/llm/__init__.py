"""
The model-facing half of the AI suggestion workflow.

Nothing in here touches the database. It builds the prompt from a node's data profile, declares
the wrangle operations as callable tools, asks Gemini which ones to offer, and hands the answer
back as plain dicts. app/server_utils/ai_wrangle.py decides whether any of it is safe to run.
"""
