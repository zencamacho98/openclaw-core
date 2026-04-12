import os

def create_documentation_file():
    docs_dir = 'docs'
    file_name = 'FRANK_SMOKE_TEST.md'
    content = '# Frank Lloyd Smoke Test Documentation\n\nThis document serves as the smoke test documentation for Frank Lloyd.'
    os.makedirs(docs_dir, exist_ok=True)
    with open(os.path.join(docs_dir, file_name), 'w') as file:
        file.write(content)

create_documentation_file()
