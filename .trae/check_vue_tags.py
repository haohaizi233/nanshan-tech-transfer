import os, re, sys

def check(path):
    text = open(path, encoding='utf-8').read()
    if '<template>' not in text:
        return
    tpl = text.split('</template>')[0]
    tag_re = re.compile(r'<(/?)([a-zA-Z][\w-]*)((?:"[^"]*"|\'[^\']*\'|[^>"\'/])*)>')
    void = {'image', 'input', 'br', 'hr', 'img'}
    stack = []
    errors = []
    for m in tag_re.finditer(tpl):
        close, tag, attrs = m.groups()
        raw = m.group(0)
        if tag.lower() in void:
            continue
        ln = tpl.count('\n', 0, m.start()) + 1
        self_close = raw.rstrip('>').rstrip().endswith('/')
        if close:
            if stack and stack[-1][0] == tag:
                stack.pop()
            else:
                errors.append('L%d: close </%s> but top=%s' % (ln, tag, stack[-1] if stack else None))
                if stack:
                    stack.pop()
        elif not self_close:
            stack.append((tag, ln))
    if errors or stack:
        print('\nFILE:', path)
        for e in errors: print(' ', e)
        if stack: print('  UNCLOSED:', stack)

root = r'C:\Users\admin\Desktop\南山小程序\南山小程序\南山'
for d, dirs, files in os.walk(root):
    if 'node_modules' in d or 'unpackage' in d:
        continue
    for f in files:
        if f.endswith('.vue'):
            check(os.path.join(d, f))
