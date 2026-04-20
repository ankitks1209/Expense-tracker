#!/usr/bin/env python3
"""Fix the input area to use st.text_area instead of complex HTML textarea"""

import re

with open('app.py', 'r') as f:
    lines = f.readlines()

# Find the line with "# Input row + Keyboard shortcuts"
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if '# Input row + Keyboard shortcuts' in line or '# Input row + Support for multiline' in line:
        start_idx = i
    if start_idx is not None and 'with reset_col:' in line:
        end_idx = i
        break

if start_idx and end_idx:
    # Replace that entire section with clean code
    replacement = '''    # Input row + Support for multiline and command examples
    input_col, send_col = st.columns([5, 1])
    with input_col:
        user_input = st.text_area(
            "User Input",
            placeholder="Type a transaction… (Shift+Enter for new line)\\n\\nExamples:\\n- paid 500 groceries\\n- received 20k salary\\n- change second one to 500\\n- category should be Groceries\\n- date was yesterday",
            key="chat_input",
            height=60,
            label_visibility="collapsed",
        ).strip()
    with send_col:
        send = st.button("📤 Send", key="send_btn", use_container_width=True)
    
    reset_col, _ = st.columns([1, 6])
'''
    
    lines = lines[:start_idx] + [replacement] + lines[end_idx:]

with open('app.py', 'w') as f:
    f.writelines(lines)

print("✓ Input area fixed successfully")
