import sys
msg = sys.stdin.read()
print(msg.replace('Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>', '').strip())
