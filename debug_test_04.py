import json

with open('test_04.json') as f:
    d = json.load(f)

print('=== Model 1 Bottleneck ===')
print(d['technical_analysis']['bottlenecks'][0])

print('\n=== Plan Structure ===')
plan = d['explain_plan_dry'][0]['Plan']

def show_nodes(node, indent=0):
    print('  ' * indent + node.get('Node Type', 'UNKNOWN'))
    for child in node.get('Plans', []):
        show_nodes(child, indent + 1)

show_nodes(plan)
