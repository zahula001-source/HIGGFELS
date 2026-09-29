import ast
import os
from pathlib import Path

base_dir = Path(r"d:\CODE\higgsfield-VIDEOAI")
main_py = base_dir / "main.py"

with open(main_py, "r", encoding="utf-8") as f:
    source_code = f.read()

tree = ast.parse(source_code)

def get_node_source(node):
    # Using ast.get_source_segment which accurately extracts the exact text
    return ast.get_source_segment(source_code, node)

# We want to extract definitions
# Let's map function names to their source code
functions = {}
classes = {}
routes = {}
other_nodes = []

for node in tree.body:
    if isinstance(node, ast.FunctionDef):
        # check if it has a route decorator
        is_route = any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.value.id == 'app'
            for d in node.decorator_list if isinstance(d.func, ast.Attribute) and hasattr(d.func.value, 'id')
        )
        if is_route:
            routes[node.name] = get_node_source(node)
        else:
            functions[node.name] = get_node_source(node)
    elif isinstance(node, ast.ClassDef):
        classes[node.name] = get_node_source(node)
    else:
        other_nodes.append(get_node_source(node))

print(f"Extracted {len(functions)} functions, {len(routes)} routes, {len(classes)} classes.")

# Let's write them to a JSON file so I can easily inspect and group them
import json
output = {
    "functions": functions,
    "routes": routes,
    "classes": classes,
}
with open(base_dir / "refactor_dump.json", "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print("Dumped to refactor_dump.json")
