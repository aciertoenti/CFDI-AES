import json
p1 = r"c:\Users\HP\AppData\Roaming\Code\User\workspaceStorage\c3dac1dcb5b287f855be0ce94b5f6276\GitHub.copilot-chat\chat-session-resources\7a112305-0590-4ee9-ab25-a6de9891b5b9\call_MHxjZk5NQWVMVndHalF0b285RkU__vscode-1787425240392\content.txt"
p2 = r"c:\Users\HP\AppData\Roaming\Code\User\workspaceStorage\c3dac1dcb5b287f855be0ce94b5f6276\GitHub.copilot-chat\chat-session-resources\7a112305-0590-4ee9-ab25-a6de9891b5b9\call_MHxidEllSUNWQnpaalN3SDd6NFA__vscode-1787425240393\content.txt"
with open(p1, encoding="utf-8") as f: project_data = json.load(f)
with open(p2, encoding="utf-8") as f: issues_data = json.load(f)
print("Project:", type(project_data))
if isinstance(project_data, dict):
    print("Keys:", list(project_data.keys()))
    if "items" in project_data:
        print("Items count:", len(project_data["items"]))
        print("First unique keys:", list(project_data["items"][0].keys()) if project_data["items"] else [])
        print("Fields of first item:", json.dumps(project_data["items"][0], indent=2))
elif isinstance(project_data, list):
    print("List count:", len(project_data))
    print("First item:", json.dumps(project_data[0], indent=2))
print("Issues:", type(issues_data), len(issues_data))
if issues_data: print("First issue:", json.dumps(issues_data[0], indent=2))
