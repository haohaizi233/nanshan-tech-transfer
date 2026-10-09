from pathlib import Path
p = Path(r'C:\Users\admin\Desktop\南山小程序\南山小程序\南山\host\local-adapter.js')
text = p.read_text(encoding='utf-8')
for i, line in enumerate(text.splitlines(), 1):
    if 'hostCredential' in line:
        print(i, repr(line))
