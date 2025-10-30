patterns = ['list', 'all documents', 'all files', 'what documents', 'what files', 'show me documents', 'show me files', 'how many documents', 'how many files', 'document list', 'file list', 'enumerate', 'inventory']

queries = [
    'What is the Gatepass number on that?',
    'What is the gatepass number of TCO005?',
    'What is the G.P# of TCO005?',
    'Is there a G.P.# in TCO005?',
    'What are the contents of TCO005?'
]

print("Testing if queries match listing patterns:\n")
for q in queries:
    matches = [p for p in patterns if p in q.lower()]
    print(f'{q}')
    print(f'  Matches: {matches if matches else "NONE (should use hybrid search)"}')
    print()

